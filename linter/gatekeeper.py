import sys
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from tools.knowledge_tools import get_section_for_chapter, query_legal_notes


class HSGatekeeper:
    def __init__(self):
        # Deterministic Rules
        # NOTE: Analyzer luôn trả key tiếng Anh: "material", "function", "state_or_condition", "item_name"
        self.rules = [
            {
                # BUG-5 FIX: đổi "chất liệu" → "material" và "gỗ" → "wood"
                "condition": lambda features: "material" in features and "wood" in features["material"].lower(),
                "action": lambda hs_code: hs_code.startswith("44"),
                "error_msg": "Sản phẩm bằng gỗ (wood) nhưng HS Code không nằm trong Chương 44."
            },
            {
                # BUG-5 FIX: đổi "loại"/"sống" → check "state_or_condition" hoặc "item_name" có chứa "live"
                "condition": lambda features: (
                    ("state_or_condition" in features and "live" in features["state_or_condition"].lower()) or
                    ("item_name" in features and "live" in features["item_name"].lower())
                ),
                "action": lambda hs_code: hs_code.startswith("01") or hs_code.startswith("03") or hs_code.startswith("95"),
                "error_msg": "Động vật sống (live animal) phải nằm ở Chương 01, 03 hoặc 95 (trường hợp ngoại lệ)."
            }
        ]

    def _check_semantic_exclusions(self, hs_code: str, item_description: str) -> tuple:
        """
        [OPTIMIZED — NO LLM]
        Uses ChromaDB vector search (query_legal_notes) to find semantically relevant
        exclusion rules, then checks them with pure Python logic.
        Zero API calls, near-zero latency.
        """
        chapter_prefix = hs_code[:2]
        section_id = get_section_for_chapter(chapter_prefix)

        try:
            results = query_legal_notes(item_description, section_id, chapter_prefix)
        except Exception as e:
            print(f"[Gatekeeper] ChromaDB query warning: {e}. Skipping exclusion check.")
            return True, "PASS"

        if "error" in results:
            # ChromaDB not available or chapter not indexed — pass through silently
            return True, "PASS"

        relevant_notes = results.get("relevant_chapter_rules", []) + results.get("relevant_section_notes", [])

        for note in relevant_notes:
            note_lower = str(note).lower()
            # If the note is an exclusion AND it mentions routing to a DIFFERENT chapter
            if "exclusion:" in note_lower:
                # Extract "see X.XX" or "heading XX" patterns as chapter redirect signals
                redirect_chapters = re.findall(r'\b(\d{2})\.\d{2}\b', note)
                for redirect_ch in redirect_chapters:
                    if redirect_ch != chapter_prefix and hs_code.startswith(chapter_prefix):
                        # This exclusion rule points to a DIFFERENT heading family
                        action_text = note.split("->")[-1].strip() if "->" in note else note
                        return False, f"Vi phạm Exclusion Rule (Semantic): {note[:200]} → Xem xét: {action_text}"

        return True, "PASS"

    def check(self, hs_code: str, item_description: str, extracted_features: dict):
        """
        Check if the proposed HS code violates any hardcoded rules or exclusion rules.
        """
        if hs_code == "UNKNOWN":
            return False, "HS Code is UNKNOWN or agent failed to predict."

        for rule in self.rules:
            if rule["condition"](extracted_features):
                if not rule["action"](hs_code):
                    return False, f"Hardcoded Linter Error: {rule['error_msg']}"

        # [OPTIMIZED] Semantic exclusion check via ChromaDB — no LLM call
        is_valid, msg = self._check_semantic_exclusions(hs_code, item_description)
        if not is_valid:
            return False, msg

        return True, "PASS"


if __name__ == "__main__":
    gatekeeper = HSGatekeeper()
    # Test exclusions
    val, msg = gatekeeper.check("010619", "Động vật xiếc (Animals of heading 95.08)", {})
    print(f"Circus Animal: {val} - {msg}")
