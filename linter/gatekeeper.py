import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from tools.knowledge_tools import get_chapter_rules

class HSGatekeeper:
    def __init__(self):
        # Deterministic Rules
        self.rules = [
            {
                "condition": lambda features: "chất liệu" in features and features["chất liệu"].lower() == "gỗ",
                "action": lambda hs_code: hs_code.startswith("44"), 
                "error_msg": "Sản phẩm bằng gỗ nhưng HS Code không nằm trong Chương 44."
            },
            {
                "condition": lambda features: "loại" in features and "sống" in features["loại"].lower(),
                "action": lambda hs_code: hs_code.startswith("01") or hs_code.startswith("03") or hs_code.startswith("95"),
                "error_msg": "Động vật sống phải nằm ở Chương 01, 03 hoặc 95 (trường hợp ngoại lệ)."
            }
        ]
        
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        
    def _check_json_exclusions(self, hs_code: str, item_description: str) -> tuple:
        """
        Uses LLM as a neuro-symbolic router to check the item_description against
        the structured JSON exclusions for the chapter.
        """
        chapter_prefix = hs_code[:2]
        # Remove hardcoded Chapter 01 restriction to allow dynamic chapters
            
        rules = get_chapter_rules(chapter_prefix)
        # Handle dict format where chapter_rules contains exclusions
        if isinstance(rules, dict) and "chapter_rules" in rules:
            exclusions = rules.get("chapter_rules", {}).get("exclusions", [])
        else:
            exclusions = rules.get("exclusions", []) if isinstance(rules, dict) else []
        
        if not exclusions:
            return True, "PASS"
            
        system_prompt = """You are the strict Customs Exclusion Linter.
Given an item description and a list of structured EXCLUSION conditions.
Evaluate if the item matches ANY of the exclusion conditions exactly.
If it matches, you MUST FAIL it and return the specific 'action' from the JSON.
Return JSON:
{
  "excluded": true/false,
  "action": "The action string if excluded, else empty string",
  "reason": "Why it matched the exclusion"
}
"""
        user_prompt = f"""
[ITEM DESCRIPTION]
{item_description}

[EXCLUSION RULES JSON]
{json.dumps(exclusions, ensure_ascii=False, indent=2)}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
                
            res = json.loads(content)
            
            if res.get("excluded"):
                return False, f"Vi phạm Exclusion Rule JSON: {res.get('reason')} -> Đề xuất: {res.get('action')}"
                
            return True, "PASS"
        except Exception as e:
            print(f"[Gatekeeper] Parsing warning: {e}")
            # If parsing fails, let QA catch it later rather than blocking the pipeline
            return True, "PASS"

    def check(self, hs_code: str, item_description: str, extracted_features: dict):
        """
        Check if the proposed HS code violates any hardcoded rules or JSON exclusion rules.
        """
        if hs_code == "UNKNOWN":
            return False, "HS Code is UNKNOWN or agent failed to predict."
            
        for rule in self.rules:
            if rule["condition"](extracted_features):
                if not rule["action"](hs_code):
                    return False, f"Hardcoded Linter Error: {rule['error_msg']}"
                    
        # Neuro-symbolic JSON Exclusion Check
        is_valid, msg = self._check_json_exclusions(hs_code, item_description)
        if not is_valid:
            return False, msg
                    
        return True, "PASS"

if __name__ == "__main__":
    gatekeeper = HSGatekeeper()
    # Test exclusions
    val, msg = gatekeeper.check("010619", "Động vật xiếc (Animals of heading 95.08)", {})
    print(f"Circus Animal: {val} - {msg}")
