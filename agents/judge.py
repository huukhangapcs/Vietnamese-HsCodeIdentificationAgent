import os
import json
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client

_JUDGE_SYSTEM_PROMPT = """You are the 'Judge Agent' for an HS Code Reranking Pipeline.
You will be provided with a [Target Item] and a [Candidate Pool] containing up to 10 potential HS Codes.
Each Candidate includes its Description and Legal Notes (Exclusions/Rules).

Your task is to play the role of a Multiple-Choice Examiner. Evaluate the [Candidate Pool] and select the SINGLE BEST MATCH for the [Target Item].

[REASONING FRAMEWORK - THE ELIMINATION PROCESS]
1. Read the [Target Item] description thoroughly. Identify its Material and Function.
2. Examine each Candidate in the Pool one by one.
3. If a Candidate's Legal Notes explicitly EXCLUDE the item, you MUST eliminate it.
4. If a Candidate's description fundamentally conflicts with the item (e.g., Plastic vs Wood), eliminate it.
5. Rank the remaining candidates and pick the one that fits perfectly.

[RESPONSE FORMAT]
You must respond STRICTLY with a SINGLE JSON block containing your final verdict. Do not write any markdown outside the JSON block.

If you find a valid candidate:
{
  "status": "SUCCESS",
  "chosen_code": "01012100",
  "reasoning": "I eliminated candidate 1 because of Exclusion Note X. I selected candidate 2 because it perfectly matches the item's material and function."
}

If ALL candidates are invalid/excluded, or if they are all irrelevant (Rổ rác):
{
  "status": "FAIL",
  "chosen_code": null,
  "reasoning": "All candidates were either excluded by the legal notes or did not match the item description. Requesting fallback to deep research."
}
"""

class JudgeAgent:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        
    def evaluate_candidates(self, item_description: str, candidate_pool: list, extracted_features: dict = None) -> dict:
        """
        Evaluates a list of candidates and selects the best one.
        candidate_pool: list of dicts {"hs_code": str, "description": str, "legal_notes": str}
        """
        if not candidate_pool:
            return {"status": "FAIL", "reasoning": "Candidate pool is empty."}
            
        print(f"\n--- BẮT ĐẦU JUDGE AGENT (Reranking) ---")
        print(f"Đánh giá {len(candidate_pool)} ứng viên...")
        
        # Build prompt payload (Token Compressed by Grouping By Chapter)
        chapters_map = {}
        for cand in candidate_pool:
            ch_id = cand.get('hs_code', '')[:2]
            if not ch_id:
                continue
                
            if ch_id not in chapters_map:
                chapters_map[ch_id] = {
                    "legal_notes": cand.get('legal_notes', '') or 'Không có ràng buộc đặc biệt.',
                    "candidates": []
                }
            chapters_map[ch_id]["candidates"].append(cand)
            
        pool_text = ""
        cand_idx = 1
        for ch_id, ch_data in chapters_map.items():
            pool_text += f"\n=== CHƯƠNG {ch_id} ===\n"
            pool_text += f"[Legal Notes chung của Chương {ch_id}]:\n{ch_data['legal_notes']}\n"
            pool_text += f"[Ứng viên thuộc Chương {ch_id}]:\n"
            for cand in ch_data["candidates"]:
                pool_text += f" - [CANDIDATE {cand_idx}] HS Code: {cand.get('hs_code')} | Tên nhóm: {cand.get('description')}\n"
                cand_idx += 1
                
        user_prompt = f"[TARGET ITEM]\n{item_description}\n"
        if extracted_features:
            user_prompt += f"Trích xuất đặc tính: {json.dumps(extracted_features, ensure_ascii=False)}\n"
            
        user_prompt += f"\n[CANDIDATE POOL]\n{pool_text}"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0
            )
            
            content = response.choices[0].message.content
            start_idx = content.find('{')
            end_idx = content.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                json_str = content[start_idx:end_idx+1]
                result = json.loads(json_str)
                print(f" Judge Status: {result.get('status')} - Chosen: {result.get('chosen_code')}")
                return result
            else:
                raise ValueError("No JSON block found")
                
        except Exception as e:
            print(f"⚠️ [JudgeAgent] Error parsing JSON: {e}")
            return {"status": "ERROR", "reasoning": str(e)}

if __name__ == "__main__":
    # Test case
    judge = JudgeAgent()
    item = "Ghế xoay văn phòng có đệm bọc da"
    pool = [
        {"hs_code": "940130", "description": "Swivel seats with variable height adjustment", "legal_notes": ""},
        {"hs_code": "392690", "description": "Other articles of plastics (Sản phẩm bằng nhựa khác)", "legal_notes": "Exclusion: Plastics used for sitting are classified in Chapter 94."}
    ]
    res = judge.evaluate_candidates(item, pool)
    print(res)
