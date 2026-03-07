import os
import json
import sys

# Define absolute path to be able to import local modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from tools.knowledge_tools import get_chapter_rules

class QAAuditorAgent:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        
    def filter_rules_for_rag(self, item_description: str, hs_code: str, rules: dict) -> list:
        """
        Lightweight RAG implementation. Instead of embedding, we do keyword/heading matching.
        It keeps only rules that MIGHT be relevant to the item or the targeted HS code.
        """
        filtered_exclusions = []
        item_desc_lower = item_description.lower()
        heading_prefix = hs_code[:4] if len(hs_code) >= 4 else hs_code
        
        for rule in rules.get("exclusions", []):
            condition = rule.get("condition", "").lower()
            
            # Simple keyword matching heuristics (In production, use Vector DB here)
            # If the rule mentions the heading we are looking at, it's relevant
            if heading_prefix in condition:
                filtered_exclusions.append(rule)
                continue
                
            # Basic keyword overlap (e.g. 'fish', 'whale', 'circus')
            keywords = [word for word in condition.replace(",", "").split() if len(word) > 3]
            if any(kw in item_desc_lower for kw in keywords):
                filtered_exclusions.append(rule)
                continue
                
        # If no strict match, it's safer to just return all rules to avoid missing edge cases during MVP
        if not filtered_exclusions:
             return rules.get("exclusions", [])
             
        return filtered_exclusions
        
    def audit(self, item_description: str, draft_result: dict) -> dict:
        """
        Takes the proposed HS Code from the Coder and tries to validate it.
        Returns a dict: {"status": "PASS" | "FAIL", "feedback": "..."}
        """
        hs_code = draft_result.get("hs_code", "")
        reasoning = draft_result.get("reasoning", "")
        
        if not hs_code or hs_code == "UNKNOWN":
            return {"status": "FAIL", "feedback": "Không có mã HS Code Dự thảo để kiểm tra."}
            
        chapter_prefix = hs_code[:2]
        
        # Load specifically the rules for that Chapter
        rules_data = get_chapter_rules(chapter_prefix)
        rules = rules_data.get("chapter_rules", {})
        section_notes = rules_data.get("section_notes", {})
        
        # [Strategy 3: RAG Rules] Filter rules to reduce tokens, focusing on relevant exclusions
        relevant_exclusions = self.filter_rules_for_rag(item_description, hs_code, rules)
        
        rag_rules = {
            "chapter": chapter_prefix,
            "relevant_exclusions_to_check": relevant_exclusions,
            "section_notes_to_check": section_notes
        }
        
        legal_notes = json.dumps(rag_rules, ensure_ascii=False, indent=2)
        
        system_prompt = """You are the 'QA Auditor Agent' (Red Team) for Customs HS Code Classification.
Your goal is to AUDIT the proposed HS Code from the Coder Agent. 
You will be given the item description, the proposed HS Code, the Coder's reasoning, and the Legal Notes of that Chapter.

[GENERAL INTERPRETATIVE RULE 1 (GIR 1) - THE SUPREME RULE]
The titles of Sections, Chapters and sub-Chapters are provided for ease of reference only; for legal purposes, classification shall be determined according to the terms of the headings and any relative Section or Chapter Notes.

Your task:
1. LƯU Ý SỐNG CÒN: Nếu Biểu thuế là một cuốn sách, thì "Chú giải" chính là "hướng dẫn sử dụng trước khi dùng". Bỏ qua chú giải là sai lầm nghiêm trọng nhất! Bạn phải đảm bảo mã HS được chọn KHÔNG NẰM TRONG NHÓM BỊ LOẠI TRỪ bởi các quy định pháp lý.
2. Verify if the item is explicitly EXCLUDED by the Chapter Notes OR Section Notes. These Notes have paramount legal authority over the Coder's basic logic.
3. If the Coder's reasoning contradicts ANY Section or Chapter Note, you must FAIL the classification and cite the specific Note.
4. If the Coder followed the Notes (e.g. classifying a circus elephant in 95.08 instead of 01.06 as dictated by Chapter 1 Exclusion Note), you MUST PASS it. Do not let general knowledge overrule the explicit Legal Notes.
5. ĐẶC BIỆT LƯU Ý KHI ĐÁNH GIÁ MÃ NGOÀI CHƯƠNG: Nếu mã dự thảo của Coder là một mã 8 chữ số nhưng không tồn tại trong nomenclature (ví dụ Coder điền 04100000 do bị buộc phải xuất 8 số, thay vì chỉ 04.10) NHƯNG mã đó được chuyển hướng HỢP LÝ bởi một Exclusion Rule có thực (VD: Rule Chương 02 nói Côn trùng sang 0410). BẠN PHẢI CHẤP NHẬN (PASS) mã đó vì Coder đã áp dụng đúng luật, dù mã nhóm chưa có cơ sở dữ liệu để soi chi tiết.
6. If it is valid and compliant with the headings and Notes, you PASS the classification.

You must return EXACTLY a JSON format:
{
  "status": "PASS", // or "FAIL"
  "feedback": "Explain why it passes or fails, citing the specific rule, heading, or Note applied."
}
Return nothing else besides the JSON block.
"""
        user_prompt = f"""
[ITEM DESCRIPTION]
{item_description}

[PROPOSED HS CODE]
{hs_code}

[CODER REASONING]
{reasoning}

[SECTION & CHAPTER {chapter_prefix} LEGAL NOTES]
{legal_notes}
"""
        
        print(f"\n--- BẮT ĐẦU QA AUDITOR (Test Suite) ---")
        print(f"Kiểm thử mã nháp: {hs_code}")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0
            )
            
            content = response.choices[0].message.content
            
            # Extract JSON block between { and }
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                json_str = content[start_idx:end_idx+1]
                result = json.loads(json_str)
                print(f"Status: {result.get('status')}")
                print(f"Feedback: {result.get('feedback')}")
                return result
            else:
                raise ValueError("No JSON block found")
            
        except Exception as e:
            msg = f"Auditor error parsing JSON: {e}"
            print(msg)
            return {"status": "FAIL", "feedback": msg}

if __name__ == "__main__":
    qa = QAAuditorAgent()
    draft = {
        "hs_code": "010619",
        "reasoning": "Ngựa vằn sống không phải ngựa thông thường, nằm ở nhóm động vật có vú khác 0106.19"
    }
    res = qa.audit("Ngựa vằn sống", draft)
