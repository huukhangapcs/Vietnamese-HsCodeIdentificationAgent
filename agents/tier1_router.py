import os
import json
import sys

# Define absolute path to be able to import local modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from tools.knowledge_tools import get_all_sections, get_chapters_for_section, get_chapter_title

class Tier1Router:
    """
    State Machine Zero-Shot Router for HS Code Architecture.
    Instead of using a ReAct loop with tools (which accumulates thousands of tokens),
    this router requests a single zero-shot classification from a list of options.
    """
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"

    def _get_top_candidate_sections(self, item_description: str, sections: list) -> list:
        """
        Step 1A: Ask LLM to propose top 3 possible sections based purely on material and function.
        Returns a list of section IDs.
        """
        options_text = "\n".join([f"- {s['id']}: {s['title']}" for s in sections])
        
        system_prompt = f"""You are the Tier-1 Router for Customs HS Code Classification.
Your task is to propose the Top 3 most likely broad Sections (Phần) of the HS nomenclature for the given item.
Focus entirely on: What is it made of (Material)? and What does it do (Function)?

Available Sections:
{options_text}

Respond STRICTLY with a JSON object containing EXACTLY this key:
{{
  "candidates": ["SECTION_X", "SECTION_Y", "SECTION_Z"]
}}
Do not return any other text outside the JSON block."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Classify this item: {item_description}"}
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
            return result.get("candidates", [])
        except Exception as e:
            print(f"  ❌ Lỗi lấy Top Candidates: {e}")
            return []

    def route_to_section(self, item_description: str, current_feedback: str = "", stream_callback=None) -> str:
        """
        Step 1: Identify the high-level Section based on the item description.
        Uses a 2-step approach: Top 3 candidates -> Check Legal Notes -> Final Section.
        Returns the exact Section ID (e.g. 'SECTION_I').
        """
        sections = get_all_sections()
        if not sections:
            return "UNKNOWN"
            
        print(f"\n🚦 [Tier-1 Router] Bắt đầu điều phối Section cho: '{item_description}'")
        if stream_callback:
            stream_callback({"type": "info", "message": f"🚦 [Tier-1 Router] Bắt đầu rà soát Danh mục Section..."})
        
        # 1. Get Top 3 Candidates
        candidates = self._get_top_candidate_sections(item_description, sections)
        valid_ids = [s['id'] for s in sections]
        candidates = [c for c in candidates if c in valid_ids]
        
        if not candidates:
             return "UNKNOWN"
             
        print(f"  ✅ Top ứng viên: {candidates}")
        if stream_callback:
            stream_callback({"type": "info", "message": f"  ✅ Đã khoanh vùng Top {len(candidates)} Sections tiềm năng: {', '.join(candidates)}"})
        
        # 2. Check Notes and Pick the Best One
        from tools.knowledge_tools import get_section_notes
        notes_context = ""
        for cand in candidates:
            cand_notes = get_section_notes(cand)
            if "error" not in cand_notes:
                excl = cand_notes.get("structured_notes", {}).get("exclusions", [])
                if excl:
                    notes_context += f"\n--- {cand} EXCLUSIONS (Loại trừ) ---\n"
                    for e in excl:
                        notes_context += f"- {e.get('condition')} -> {e.get('action')}\n"
        
        options_text = "\n".join([f"- {s['id']}: {s['title']} ({s.get('description', '')})" for s in sections if s['id'] in candidates])
        
        feedback_prompt = f"\n\nWARNING/FEEDBACK FROM PREVIOUS ATTEMPT:\n{current_feedback}\nPlease pick a DIFFERENT Section or reconsider." if current_feedback else ""
        
        system_prompt = f"""You are the Tier-1 Router for Customs HS Code Classification.
Your task is to select the SINGLE best Section from the provided candidates based on the item description.

[CRITICAL INSTRUCTION]
1. Ignore marketing names. Focus entirely on Material and Function.
2. LEGAL EXCLUSIONS HAVE PARAMOUNT AUTHORITY. Read the exclusions carefully. If the item is described in the exclusions of a candidate section, YOU MUST NOT CHOOSE THAT SECTION.

Candidate Sections:
{options_text}{feedback_prompt}
{notes_context}

Strictly respond with the EXACT Section ID (e.g., '{candidates[0]}') that most specifically describes the item.
Do not respond with anything else. No reasoning, no markdown formatting."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Classify this item: {item_description}"}
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=20,
                temperature=0.0
            )
            section_id = response.choices[0].message.content.strip()
            section_id = section_id.replace("```", "").replace("'", "").replace('"', "").strip()
            
            if section_id in candidates:
                print(f"  ✅ Nhánh Section chốt hạ: {section_id}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"  ⚖️ Đã đối chiếu Legal Notes của {len(candidates)} Sections. Quyết định chốt hạ: {section_id}"})
                return section_id
            elif section_id in valid_ids:
                print(f"  ⚠️ LLM chọn {section_id} ngoài danh sách, ép về Top 1: {candidates[0]}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"  ⚠️ LLM chọn {section_id} ngoài danh sách đề xuất, tự động ép về: {candidates[0]}"})
                return candidates[0]
            else:
                print(f"  ❌ LLM trả về mã rác: {section_id}, fallback về {candidates[0]}")
                return candidates[0]
        except Exception as e:
            print(f"  ❌ Lỗi kết nối API: {e}")
            return "UNKNOWN"

    def route_to_chapter(self, item_description: str, section_id: str, section_notes: str = "", current_feedback: str = "", stream_callback=None) -> str:
        """
        Step 3: Once a section is identified, classify into the specific Chapter.
        Takes Section notes into account for exclusions.
        """
        chapters = get_chapters_for_section(section_id)
        if not chapters:
            return "UNKNOWN"
            
        options_list = []
        for ch in chapters:
            title = get_chapter_title(ch)
            options_list.append(f"- {ch}: {title}")
            
        options_text = "\n".join(options_list)
        
        feedback_prompt = f"\n\nWARNING/FEEDBACK FROM PREVIOUS ATTEMPT:\n{current_feedback}\nPlease pick a DIFFERENT Chapter or reconsider." if current_feedback else ""
        
        notes_prompt = f"\n\nSECTION NOTES & EXCLUSIONS (CRITICAL):\n{section_notes}\nDO NOT route to a chapter if it is explicitly excluded in the notes above." if section_notes else ""
        
        system_prompt = f"""You are the Tier-1 Router for Customs HS Code Classification.
Your task is to route the item to the correct Chapter (Chương) within the established Section {section_id}.
[CRITICAL ROUTING INSTRUCTIONS]
1. Ignore marketing names. Focus entirely on answering two questions: What is it made of (Material)? and What does it do (Function)?
2. Remember that Chapter/Section Notes have paramount legal authority.{notes_prompt}

Strictly respond with the EXACT Chapter ID (e.g., '01', '85') that most specifically describes the item.
Do not respond with anything else.

Available Chapters in {section_id}:
{options_text}{feedback_prompt}

Remember, you must ONLY output the EXACT Chapter ID from the list above. No reasoning, no markdown formatting."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Classify this item: {item_description}"}
        ]
        
        print(f"\n🚦 [Tier-1 Router] Bắt đầu điều phối Chapter trong {section_id} cho: '{item_description}'")
        if stream_callback:
            stream_callback({"type": "info", "message": f"🚦 [Tier-1 Router] Định tuyến Chương (Chapter) trong khuôn khổ {section_id}..."})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=20,
                temperature=0.0
            )
            chapter_id = response.choices[0].message.content.strip()
            chapter_id = chapter_id.replace("```", "").replace("'", "").replace('"', "").strip()
            
            if chapter_id in chapters:
                print(f"  ✅ Nhánh Chapter Zero-shot: {chapter_id}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"  🎯 Đã khoá mục tiêu Chương: {chapter_id}"})
                return chapter_id
            else:
                fallback_ch = chapters[0] if chapters else "UNKNOWN"
                print(f"  ❌ LLM trả về mã rác: {chapter_id}, ép về {fallback_ch}")
                return fallback_ch
        except Exception as e:
            print(f"  ❌ Lỗi kết nối API: {e}")
            return "UNKNOWN"

if __name__ == "__main__":
    router = Tier1Router()
    
    print("Test Routing Ngựa:")
    sec = router.route_to_section("Ngựa thuần chủng để sinh sản")
    print(sec)
    if sec != "UNKNOWN":
        res = router.route_to_chapter("Ngựa thuần chủng để sinh sản", sec)
        print(res)
    
    print("\nTest Routing Đàn Piano:")
    sec2 = router.route_to_section("Đàn piano điện tử")
    print(sec2)
    if sec2 != "UNKNOWN":
        res2 = router.route_to_chapter("Đàn piano điện tử", sec2)
        print(res2)
