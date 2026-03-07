import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from agents.coder import HSCoderAgent
from agents.tier1_router import Tier1Router
from agents.analyzer import ItemAnalyzer
from linter.gatekeeper import HSGatekeeper
from qa.auditor import QAAuditorAgent
from core.cache_manager import CacheManager

class HSPipeline:
    def __init__(self):
        self.analyzer = ItemAnalyzer()
        self.router = Tier1Router()
        self.coder = HSCoderAgent()
        self.gatekeeper = HSGatekeeper()
        self.auditor = QAAuditorAgent()
        self.cache_manager = CacheManager()
        
    def classify(self, item_description: str, extracted_features: dict = None, max_revisions: int = 2, stream_callback=None, input_callback=None):
        if stream_callback:
            stream_callback({"type": "info", "message": f"=============================================="})
            stream_callback({"type": "info", "message": f"MÔ PHỎNG CODING AGENT CHO: {item_description}"})
            stream_callback({"type": "info", "message": f"=============================================="})
            
        if not extracted_features:
            extracted_features = self.analyzer.analyze(item_description)
            
        print(f"\n{'='*50}")
        print(f"MÔ PHỎNG CODING AGENT CHO: {item_description}")
        print(f"{'='*50}")
        
        # 0. Fast Path: Input Validation (Chặn Dữ liệu rác)
        if extracted_features and extracted_features.get("is_valid") is False:
            reason = extracted_features.get("reason", "Vui lòng mô tả hàng hoá rõ ràng hơn.")
            print(f"\n🛑 [FAST REJECT] Dữ liệu vô nghĩa: {reason}")
            if stream_callback:
                stream_callback({"type": "info", "message": f"🛑 [FAST REJECT] Dữ liệu không hợp lệ: {reason}"})
                stream_callback({"type": "fast_path_result", "data": {
                    "is_agentic_path": False,
                    "final_section_id": "UNKNOWN",
                    "confidence": "REJECTED",
                    "reasoning": reason
                }})
            return {"status": "ERROR", "message": reason, "source": "analyzer_validation"}
            
        # 0.5 Fast Path: Check Cache
        cached_result = self.cache_manager.get(item_description, extracted_features)
        if cached_result:
            print(f"\n⚡ [FAST PATH] CACHE HIT! Độ trễ ~0s.")
            print(f"Mã HS Cache: {cached_result['hs_code']}")
            print(f"Lý do (Lưu trữ): {cached_result['reasoning']}")
            if stream_callback:
                stream_callback({"type": "info", "message": "⚡ [FAST PATH] CACHE HIT! Độ trễ ~0s."})
                stream_callback({"type": "fast_path_result", "data": {
                    "is_agentic_path": False,
                    "final_section_id": cached_result["hs_code"],
                    "confidence": "CACHE",
                    "reasoning": cached_result["reasoning"]
                }})
            return {"status": "SUCCESS", "final_hs_code": cached_result["hs_code"], "reasoning": cached_result["reasoning"], "source": "cache"}
            
        revision = 0
        current_feedback = ""
        
        while revision <= max_revisions:
            if revision > 0:
                print(f"\n--- BẮT ĐẦU REVISION {revision} ---")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"--- BẮT ĐẦU REVISION {revision} ---"})
                
            # 1. Tier-1 Router tìm nhóm Heading (Thay thế ReAct mù mờ)
            # Avoid re-routing if we are just answering a clarification
            if not current_feedback and "Thông tin bổ sung" in item_description:
                # Nếu đang trả lời câu hỏi phụ, giữ nguyên node xuất phát ban đầu
                # (Chúng ta không chặn luồng này vì Coder Agent sẽ lo liệu dựa vào messages context)
                pass 
                
            # Bổ sung kết quả Step 0 vào chuỗi nội dung cho LLM dễ suy luận
            enhanced_desc = f"Tên hàng: {item_description}\n"
            if extracted_features:
                enhanced_desc += f"\n[Step 0 - Basics Extraction (Reference)]\n"
                enhanced_desc += f"- Item Name: {extracted_features.get('item_name', 'Unknown')}\n"
                enhanced_desc += f"- State/Condition: {extracted_features.get('state_or_condition', 'Unknown')}\n"
                enhanced_desc += f"- Material: {extracted_features.get('material', 'Unknown')}\n"
                enhanced_desc += f"- Function: {extracted_features.get('function', 'Unknown')}\n"

            # --- TIER-1 ROUTING V2 (4-STEP RAG) ---
            from tools.knowledge_tools import get_section_notes
            
            # 1. Pipeline gọi Tier-1 Router để xác định Section
            target_section = self.router.route_to_section(enhanced_desc, current_feedback=current_feedback, stream_callback=stream_callback)
            if target_section == "UNKNOWN":
                target_section = "SECTION_I" # Tạm thời fallback
                
            # 2. Truy xuất Section Notes (để lấy Exclusions/Rules bơm vào prompt)
            section_notes_data = get_section_notes(target_section)
            section_notes_text = ""
            if "structured_notes" in section_notes_data:
                excl = section_notes_data["structured_notes"].get("exclusions", [])
                rules = section_notes_data["structured_notes"].get("classification_rules", [])
                
                if excl:
                    section_notes_text += "EXCLUSIONS (Loại trừ):\n"
                    for e in excl:
                        section_notes_text += f"- {e.get('condition')} -> {e.get('action')}\n"
                if rules:
                    section_notes_text += "\nRULES (Quy tắc chung):\n"
                    for r in rules:
                        section_notes_text += f"- {r.get('rule')}\n"

            # 3. Pipeline gọi Tier-1 Router để xác định Chapter (đưa Section Notes vào làm cảnh báo)
            target_chapter = self.router.route_to_chapter(enhanced_desc, target_section, section_notes=section_notes_text, current_feedback=current_feedback, stream_callback=stream_callback)
            if target_chapter == "UNKNOWN":
                # Fallback về chapter đầu tiên của Section đã route (không hardcode "01")
                from tools.knowledge_tools import get_chapters_for_section
                fallback_chapters = get_chapters_for_section(target_section)
                target_chapter = fallback_chapters[0] if fallback_chapters else "01"
                
            # 4. Gắn ID của Chapter vừa tìm được làm node xuất phát đệ quy cho Coder Agent
            starting_node_id = target_chapter
                
            # 2. Coder sinh mã nháp từ vị trí Heading đã tìm
            prompt = enhanced_desc
            if current_feedback:
                prompt += f"\n\n[LƯU Ý TỪ LẦN TRƯỚC BỊ LỖI]: {current_feedback}\nHãy tra cứu kỹ lại Chú giải hoặc Nhóm khác để tìm mã đúng."
                
            draft_result = self.coder.classify_item(prompt, starting_node_id, max_steps=8, stream_callback=stream_callback, input_callback=input_callback)
            hs_code = draft_result.get("hs_code", "UNKNOWN")
            
            # --- INCORPORATE HUMAN-IN-THE-LOOP ---
            # Lưu ý phần block User Tự Động đã được xử lý phía trong `coder.py` bằng `input_callback`.
            # Nên tại đây không cần cắt Request stream về Frontend như lúc trước để bảo toàn Context.
            if hs_code == "CLARIFICATION_NEEDED":
                print("\n[Pipeline - SYSTEM FAIL] - Lỗi. Không nên lọt vào đây nếu input_callback hoạt động đúng.")
                return {
                    "final_hs_code": "CLARIFICATION_NEEDED",
                    "reasoning": "Fallback Error",
                    "status": "CLARIFICATION_NEEDED"
                }
                
            if hs_code == "UNSUPPORTED_CHAPTER":
                print(f"\n[Pipeline - UNSUPPORTED] 🛑 {draft_result.get('reasoning')}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"🛑 HỆ THỐNG TẠM DỪNG: {draft_result.get('reasoning')}"})
                    stream_callback({"type": "slow_path_result", "data": {
                        "is_agentic_path": True,
                        "final_section_id": "UNSUPPORTED",
                        "confidence": "ERROR",
                        "reasoning": f"**Hệ thống hiện tại chưa hỗ trợ chương này:**\n{draft_result.get('reasoning')}"
                    }})
                return {
                    "final_hs_code": "UNSUPPORTED",
                    "reasoning": draft_result.get("reasoning"),
                    "status": "UNSUPPORTED"
                }
            
            print(f"\n[Pipeline] Draft Code: {hs_code}")
            if stream_callback:
                stream_callback({"type": "info", "message": f"[Pipeline] Draft Code: {hs_code}"})
            
            # 2. Linter kiểm tra luật cứng
            is_valid, linter_msg = self.gatekeeper.check(hs_code, enhanced_desc, extracted_features)
            if not is_valid:
                print(f"[Pipeline] ❌ Linter Failed: {linter_msg}")
                if stream_callback:
                    stream_callback({"type": "error", "message": f"[Pipeline] ❌ Linter Failed: {linter_msg}"})
                current_feedback = linter_msg
                revision += 1
                continue
                
            print(f"[Pipeline] ✅ Linter Passed.")
            if stream_callback:
                stream_callback({"type": "info", "message": f"[Pipeline] ✅ Linter Passed."})
            
            # 3. QA Auditor kiểm thử (Red Team)
            audit_result = self.auditor.audit(enhanced_desc, draft_result)
            
            if audit_result.get("status") == "FAIL":
                print(f"[Pipeline] ❌ QA Test Failed: {audit_result.get('feedback')}")
                if stream_callback:
                    stream_callback({"type": "error", "message": f"QA Auditor Failed: {audit_result['feedback']}"})
                current_feedback = audit_result.get("feedback")
                revision += 1
                continue
            
            print(f"[Pipeline] ✅ QA Test Passed.")
            if stream_callback:
                stream_callback({"type": "info", "message": "🎉 QA Auditor APPROVED!"})
                stream_callback({"type": "slow_path_result", "data": {
                    "is_agentic_path": True,
                    "final_section_id": hs_code,
                    "confidence": "HIGH (QA Checked)",
                    "reasoning": draft_result.get("reasoning", ""),
                    "clarifications": draft_result.get("clarifications", [])
                }})
            
            # 4. Success Pipeline (Green)
            print(f"\n[Pipeline] 🎉 THÀNH CÔNG! Mã HS Cuối Cùng: {hs_code}")
            print(f"Lý do: {draft_result.get('reasoning')}")
            
            # Format clarification to contextualize the Cache Key
            clarifications_made = draft_result.get("clarifications", [])
            enhanced_cache_key = item_description
            if clarifications_made:
                clarification_texts = " - ".join([f"Q: {c['question']} A: {c['answer']}" for c in clarifications_made])
                enhanced_cache_key = f"{item_description} [{clarification_texts}]"
                
            # Write-back to Cache
            self.cache_manager.set(enhanced_cache_key, hs_code, draft_result.get('reasoning'), extracted_features)
            print(f"💾 Đã lưu vào Cache để dùng cho Fast Path lần sau.")
            if stream_callback:
                stream_callback({"type": "info", "message": f"🎉 THÀNH CÔNG! Mã HS Cuối Cùng: {hs_code}"})
                stream_callback({"type": "info", "message": f"Lý do: {draft_result.get('reasoning')}"})
                stream_callback({"type": "info", "message": "💾 Đã lưu vào Cache để dùng cho Fast Path lần sau."})
            
            return {
                "final_hs_code": hs_code,
                "reasoning": draft_result.get("reasoning"),
                "status": "SUCCESS",
                "source": "agent",
                "revisions": revision
            }
            
        print(f"\n[Pipeline] ⛔ THẤT BẠI: Vượt quá số lần sửa (Max Revisions). Cần chuyên gia (Human) hỗ trợ.")
        return {
            "final_hs_code": "UNKNOWN",
            "reasoning": current_feedback,
            "status": "HUMAN_INTERVENTION_REQUIRED",
            "revisions": revision
        }

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    # Test case 1: Ngựa vằn sống (Slow Path)
    print("\\n\\n### TEST CASE 1: Ngựa vằn sống (Lần 1 - SLOW PATH) ###")
    pipeline.classify("Sản phẩm là Ngựa vằn sống (Live zebra).", extracted_features={"loại": "động vật sống"})
    
    # Test case 1.5: Ngựa vằn sống (Fast Path Hit)
    print("\\n\\n### TEST CASE 1.5: Ngựa vằn sống (Lần 2 - FAST PATH) ###")
    pipeline.classify("Sản phẩm là Ngựa vằn sống (Live zebra).", extracted_features={"loại": "động vật sống"})
    
    # Test case 2: Voi làm xiếc (Exclusion case)
    print("\\n\\n### TEST CASE 2: Voi làm xiếc ###")
    pipeline.classify("Voi đang sống đang được sử dụng làm động vật biểu diễn trong rạp xiếc (Circus elephant).", extracted_features={"loại": "động vật sống"})
    
    # Test case 3: Cá voi sống (Exclusion case)
    print("\\n\\n### TEST CASE 3: Cá voi sống ###")
    pipeline.classify("Cá voi sống (Live whale).", extracted_features={"loại": "động vật sống"})
    
    # Test case 4: Cá ngừ đông lạnh
    print("\\n\\n### TEST CASE 4: Cá ngừ đông lạnh ###")
    pipeline.classify("Cá ngừ đại dương đông lạnh.", extracted_features={"loại": "đông lạnh"})

    # Test case 5: Human-in-The-Loop Interactive Test
    print("\\n\\n### TEST CASE 5: Tương tác Clarification (Human-in-The-Loop) ###")
    pipeline.classify("Nhập khẩu 100 con ngựa về trang trại.")
