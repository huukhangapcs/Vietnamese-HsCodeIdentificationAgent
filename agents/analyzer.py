import os
import json
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from core.security import sanitize_input

# Heuristic fast-fail — không tốn 1 token LLM nào
_STOP_WORDS = {"hello", "hi", "ok", "test", "alo", "chào", "xin chào", "tôi cần hỏi", "hỏi xíu"}

# Single combined prompt — validation + feature extraction in ONE call
_COMBINED_SYSTEM_PROMPT = """You are a Customs Input Validator AND Feature Extractor for an HS Code Classification system.

STEP 1 — VALIDITY CHECK:
Determine if the input is a valid description of a physical good/product to be imported or exported.
If it is conversational, questionless, nonsensical, or not a physical good → set "is_valid": false.

STEP 2 — FEATURE EXTRACTION (only if valid):
If valid, extract the 4 core physical characteristics IN ENGLISH.

Respond STRICTLY with ONE JSON object containing ALL these keys:
{
  "is_valid": true or false,
  "reason": "Lý do bằng tiếng Việt nếu không hợp lệ, để chuỗi rỗng nếu hợp lệ",
  "item_name": "Specific name of the item in English, or '' if invalid",
  "state_or_condition": "Physical state (e.g. fresh, frozen, live, new, used, liquid, powder). Write 'Unknown' if not mentioned, or '' if invalid",
  "material": "Primary material (e.g. plastic, wood, steel, cotton). Write 'Not Applicable' if irrelevant, or '' if invalid",
  "function": "Main function/purpose in English, or '' if invalid",
  "search_keywords": ["list of 2-4 strategic English phrases to strictly fuzzy-search the HS Nomenclature database (e.g. ['frozen whole chicken', 'poultry meat']). Generate only if valid."]
}
Do NOT output any text outside the JSON block."""


class ItemAnalyzer:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"

    def _heuristic_fast_fail(self, desc_lower: str) -> dict | None:
        """Pure-Python heuristics — zero LLM cost. Returns rejection dict or None."""
        if len(desc_lower.strip()) < 2:
            return {"is_valid": False, "reason": "Mô tả quá ngắn, không cấu thành hàng hóa."}
        for word in _STOP_WORDS:
            if desc_lower == word or desc_lower.startswith(word + " "):
                return {"is_valid": False, "reason": f"Phát hiện từ khóa giao tiếp '{word}', đây không phải là mô tả hàng hóa."}
        return None  # passes heuristics

    def analyze(self, item_description: str) -> dict:
        """
        [OPTIMIZED] Main pipeline Step 0.
        Performs input validation + feature extraction in a SINGLE LLM call.
        Returns a unified dict with 'is_valid' plus all feature fields.
        """
        # 0. Prompt Injection Defense
        sanitized = sanitize_input(item_description)
        if sanitized != item_description:
            print(f"  ⚠️ [Analyzer] Phát hiện prompt injection attempt. Input đã được sanitize.")
        item_description = sanitized

        print(f"\n[Step 0 - Analyzer] Kiểm tra hợp lệ + trích xuất đặc trưng (1 call)...")

        # 1. Heuristic fast-fail (no LLM cost at all)
        rejection = self._heuristic_fast_fail(item_description.lower())
        if rejection:
            print(f"  ⚡ [Heuristic Fast-Fail] {rejection['reason']}")
            return rejection

        # 2. Single combined LLM call
        messages = [
            {"role": "system", "content": _COMBINED_SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify this input: {item_description}"}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            content = response.choices[0].message.content
            if content.startswith("```"):
                content = '\n'.join([l for l in content.split('\n') if not l.startswith("```")])

            result = json.loads(content.strip())

            if not result.get("is_valid", True):
                print(f"  👉 Hợp lệ: False - {result.get('reason')}")
                return {"is_valid": False, "reason": result.get("reason", "")}

            # Valid path — log features
            print(f"  👉 Item Name: {result.get('item_name', 'Unknown')}")
            print(f"  👉 State/Condition: {result.get('state_or_condition', 'Unknown')}")
            print(f"  👉 Material: {result.get('material', 'Unknown')}")
            print(f"  👉 Function: {result.get('function', 'Unknown')}")
            print(f"  🔑 Search Keywords: {result.get('search_keywords', [])}")
            result["is_valid"] = True
            return result

        except Exception as e:
            print(f"  ⚠️ [Analyzer] LLM error: {e}. Falling back to pass-through.")
            return {"is_valid": True, "reason": "", "item_name": item_description,
                    "state_or_condition": "Unknown", "material": "Unknown", "function": "Unknown", "search_keywords": [item_description]}


if __name__ == "__main__":
    analyzer = ItemAnalyzer()
    res = analyzer.analyze("Ghế xoay văn phòng có đệm bọc da")
    print(res)

