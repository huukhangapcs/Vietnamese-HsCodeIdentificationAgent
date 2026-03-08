import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from agents.coder import HSCoderAgent
from agents.tier1_router import Tier1Router
from agents.analyzer import ItemAnalyzer
from agents.judge import JudgeAgent
from linter.gatekeeper import HSGatekeeper
from qa.auditor import QAAuditorAgent
from core.cache_manager import CacheManager

class HSPipeline:
    def __init__(self):
        self.analyzer = ItemAnalyzer()
        self.router = Tier1Router()
        self.coder = HSCoderAgent()
        self.judge = JudgeAgent()
        self.gatekeeper = HSGatekeeper()
        self.auditor = QAAuditorAgent()
        self.cache_manager = CacheManager()

    def _fast_path_gate_a(self, hs_code: str, features: dict, chapter_id: str) -> tuple[bool, str]:
        """
        Gate A: Deterministic fast-fail checks — 0 LLM call, 0 ChromaDB query.

        A1. Hardcoded Linter rules (từ self.gatekeeper.rules):
            - "live" animal không ở chapter 01/03/95 → REJECT
            - "wood" material không ở chapter 44 → REJECT

        A2. JSON keyword-based chapter exclusion check (từ chapter_X_rules.json):
            - Lấy exclusion keywords từ cache (đã load vào RAM)
            - Intersection với feature words → nếu khớp → REJECT

        Returns: (is_ok, rejection_reason)
        """
        from tools.knowledge_tools import get_chapter_rules

        # A1: Hardcoded Linter rules (reuse từ gatekeeper, chỉ phần hardcoded — không gọi ChromaDB)
        for rule in self.gatekeeper.rules:
            try:
                if rule["condition"](features) and not rule["action"](hs_code):
                    return False, f"Hardcoded rule: {rule['error_msg']}"
            except Exception:
                pass  # Bỏ qua nếu feature key không tồn tại

        # A2: Chapter exclusion keyword check (deterministic, từ JSON đã cache)
        try:
            chapter_rules = get_chapter_rules(chapter_id)  # Đọc từ _rules_cache (RAM)
        except Exception:
            return True, ""  # Không có rules → pass qua (safe default)

        # Gộp tất cả relevant text từ features để so sánh cụm từ
        full_features_text = " " + " ".join(
            str(features.get(key, "")).lower() 
            for key in ("item_name", "material", "state_or_condition", "function")
        ) + " "

        for excl in chapter_rules.get("exclusions", []):
            excl_keywords = [k.lower().strip() for k in excl.get("keywords", [])]
            
            # Phrase-level matching (tránh bẫy từ đơn "apple" dính vào "apple logo")
            matched_phrase = None
            for kw in excl_keywords:
                if f" {kw} " in full_features_text:
                    matched_phrase = kw
                    break

            if matched_phrase:
                condition = excl.get("condition", "")
                action = excl.get("action", "")
                return False, (
                    f"Chapter {chapter_id} exclusion matched [{matched_phrase}]: "
                    f"{condition} → {action}"
                )

        return True, ""


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
            
        # 0.1 Màng lọc Chống mờ nhạt (Vagueness Gate)
        if extracted_features:
            unknown_count = 0
            for field in ["item_name", "state_or_condition", "material", "function"]:
                if str(extracted_features.get(field, "")).strip().lower() == "unknown":
                    unknown_count += 1
                    
            if unknown_count >= 2:
                vagueness_msg = "Mô tả của bạn quá chung chung. Vui lòng cung cấp thêm thông tin về CHẤT LIỆU hoặc CHỨC NĂNG để hệ thống có thể phân loại chính xác."
                print(f"\n⚠️ [VAGUENESS GATE] Từ chối xử lý do thiếu dữ kiện ({unknown_count}/4 Unknown).")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"⚠️ [THIẾU THÔNG TIN]: {vagueness_msg}"})
                    stream_callback({"type": "slow_path_result", "data": {
                        "is_agentic_path": True,
                        "final_section_id": "CLARIFICATION_NEEDED",
                        "confidence": "LOW",
                        "reasoning": vagueness_msg,
                        "clarifications": [{"question": "Bạn có thể mô tả chi tiết hơn về mặt hàng này không?", "answer": ""}]
                    }})
                return {"status": "CLARIFICATION_NEEDED", "message": vagueness_msg, "source": "analyzer_vagueness"}

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
            
        # 0.8 Fast Path: Keywords Search (Lexical & Fuzzy)
        from tools.knowledge_tools import fast_keyword_search
        
        # Thử search bằng cả tiếng Việt (gốc) và tiếng Anh (extracted) để lấy điểm cao nhất
        # Phase 2 & 3: Keyword Generation & Search
        # Bắt lấy list từ khóa Tiếng Anh đã được Analyzer đẻ ra
        search_keywords = extracted_features.get("search_keywords", []) if extracted_features else []
        fast_path_hint_node = None
        fast_path_hint_reason = ""

        if not search_keywords:
            # [FIX] Không dùng item_description tiếng Việt làm keyword tiếng Anh
            # Analyzer fail → bỏ qua keyword search, đẩy thẳng xuống Slow Path
            print("[FAST PATH] Analyzer chưa generate keywords — skip keyword search, vào Slow Path.")
            if stream_callback:
                stream_callback({"type": "info", "message": "[FAST PATH] Không có keywords, chuyển sang Deep Reasoning..."})
            all_candidates = []  # Skip thẳng xuống Slow Path
        else:
            # Gọi thẳng vào hàm Search với list từ khóa tiếng Anh
            all_candidates = fast_keyword_search(search_keywords, top_k=3, leaf_only=False)
        
        if all_candidates:
            # Lọc trùng lặp hs_code giữ điểm cao nhất
            unique_cands = {}
            for c in all_candidates:
                if c["hs_code"] not in unique_cands or c["score"] > unique_cands[c["hs_code"]]["score"]:
                    unique_cands[c["hs_code"]] = c
                    
            sorted_unique_cands = sorted(unique_cands.values(), key=lambda x: x["score"], reverse=True)
            print(f"\n[FAST PATH] Top Candidate: {sorted_unique_cands[0]['hs_code']} - Score: {sorted_unique_cands[0]['score']}")
            
            best_candidate = sorted_unique_cands[0]
            num_unique = len(sorted_unique_cands)

            # [FIX-4] Single-candidate bias: nếu chỉ có 1 kết quả duy nhất
            # thì yêu cầu score cao hơn (80+) để tránh confirmation bias
            effective_threshold = 75 if num_unique >= 2 else 80  # [FIX-5] Tăng từ 70 → 75/80

            if best_candidate["score"] >= effective_threshold and best_candidate.get("is_leaf", True):
                print(f"🚀 [FAST PATH] KEYWORD ENGINE MATCH! (Score: {best_candidate['score']})")

                chapter_id_cand = best_candidate["hs_code"][:2]

                # ══════════════════════════════════════════════════════════════
                # GATE A — Deterministic checks (0 LLM, 0 ChromaDB) ≈ 1ms
                # ══════════════════════════════════════════════════════════════
                gate_a_pass, gate_a_msg = self._fast_path_gate_a(
                    best_candidate["hs_code"], extracted_features or {}, chapter_id_cand
                )
                if not gate_a_pass:
                    print(f"[FAST PATH] ⛔ Gate A REJECT: {gate_a_msg} → Slow Path")
                    if stream_callback:
                        stream_callback({"type": "info", "message": f"⛔ [FAST PATH] Phát hiện vi phạm rule: {gate_a_msg}. Chuyển sang Deep Reasoning..."})
                    # Không tốn LLM/ChromaDB — xuống Slow Path ngay
                else:
                    # ══════════════════════════════════════════════════════════
                    # GATE B — QA Auditor (1 ChromaDB + 1 LLM) ≈ 3s
                    # Chỉ chạy khi Gate A đã xác nhận "không vi phạm rule rõ ràng"
                    # ══════════════════════════════════════════════════════════
                    if stream_callback:
                        stream_callback({"type": "info", "message": f"🚀 [FAST PATH] Gate A passed. Gọi QA Auditor kiểm tra (Score: {best_candidate['score']})..."})

                    # Enrich reasoning với đầy đủ features để Auditor judge chính xác hơn
                    feat = extracted_features or {}
                    simulated_draft = {
                        "hs_code": best_candidate["hs_code"],
                        "reasoning": (
                            f"Fast-Track Keyword Match (Score {best_candidate['score']}).\n"
                            f"Matched: {best_candidate['description_en']} / {best_candidate['description_vn']}.\n"
                            f"Item features — name: {feat.get('item_name', '?')}, "
                            f"state: {feat.get('state_or_condition', '?')}, "
                            f"material: {feat.get('material', '?')}, "
                            f"function: {feat.get('function', '?')}.\n"
                            f"Gate A (chapter rules): PASSED — không phát hiện vi phạm exclusion rõ ràng."
                        )
                    }

                    # [FIX-2] try/except để tránh crash khi LLM timeout
                    try:
                        audit_result = self.auditor.audit(
                            item_description=item_description,
                            draft_result=simulated_draft
                        )
                    except Exception as audit_err:
                        print(f"⚠️ QA Auditor lỗi: {audit_err} — đẩy xuống Slow Path")
                        if stream_callback:
                            stream_callback({"type": "info", "message": "⚠️ QA Auditor gặp lỗi, chuyển sang Deep Reasoning..."})
                        audit_result = {}  # Treat như FAIL → escalate to Slow Path

                    if audit_result.get("status", "").upper() == "PASS":
                        print("✅ QA Auditor DUYỆT kết quả tự động!")
                        if stream_callback:
                            stream_callback({"type": "fast_path_result", "data": {
                                "is_agentic_path": False,
                                "final_section_id": best_candidate["hs_code"],
                                "confidence": f"HIGH (Keyword Score {best_candidate['score']})",
                                "reasoning": f"Khớp nối từ khóa siêu tốc.\nKiểm định QA: {audit_result.get('feedback', 'Hợp lệ')}"
                            }})
                        # Cache the result
                        safe_features = extracted_features if isinstance(extracted_features, dict) else {}
                        self.cache_manager.set(
                            description=item_description,
                            hs_code=best_candidate["hs_code"],
                            reasoning=f"Keyword Match (Score {best_candidate['score']}). {audit_result.get('feedback', '')}",
                            features=safe_features
                        )
                        return {
                            "status": "SUCCESS",
                            "final_hs_code": best_candidate["hs_code"],
                            "reasoning": f"Khớp nối từ khóa siêu tốc ({best_candidate['score']} điểm). Kiểm định QA: {audit_result.get('feedback', 'Hợp lệ')}",
                            "source": "keyword_search"
                        }
                    else:
                        print(f"❌ QA Auditor TỪ CHỐI kết quả tự động: {audit_result.get('feedback', 'Không giải thích')}")
                        print("Đẩy lại luồng LLM sâu...")
                        if stream_callback:
                            stream_callback({"type": "info", "message": f"❌ QA Auditor TỪ CHỐI kết quả Keyword: {audit_result.get('reasoning', '')}. Chuyển sang luồng Deep Reasoning Agent!"})
            elif not best_candidate.get("is_leaf", True) and best_candidate["score"] >= 85:
                # [NEW HINT LOGIC] Fast Path không chốt được do là mã 4/6 số, đẩy xuống Slow Path làm Hint
                print(f"💡 [FAST PATH] TÌM THẤY MANH MỐI (HINT)! (Score: {best_candidate['score']}) - Node: {best_candidate['hs_code']}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"💡 [FAST PATH] Tìm thấy manh mối phân loại tại {best_candidate['hs_code']} (Score: {best_candidate['score']}). Chuyển giao về Agent Coder..."})
                fast_path_hint_node = best_candidate["hs_code"]
                fast_path_hint_reason = f"Keyword HINT (Score {best_candidate['score']}): {best_candidate['description_en']} / {best_candidate['description_vn']}"

        # ═══════════════════════════════════════════════════════════════════════
        # [NEW V3] PHASE 1: HYBRID CANDIDATE GENERATION (RERANKER POOL BUILDER)
        # ═══════════════════════════════════════════════════════════════════════
        from tools.knowledge_tools import search_hs_nodes, get_chapter_rules, get_section_notes
        
        print("\n[V3 PHASE 1] Đang gom ứng viên (Candidate Generation)...")
        if stream_callback:
            stream_callback({"type": "info", "message": "🔍 [PHASE 1] Đang thu thập danh sách ứng viên diện rộng bằng trí tuệ nhân tạo..."})
            
        candidate_pool = []
        seen_codes = set()
        
        # 1.1 Lấy Top 5 từ Elastic/Keyword (Nếu có)
        if all_candidates:
            for c in sorted_unique_cands[:5]:
                if c["hs_code"] not in seen_codes:
                    candidate_pool.append({
                        "hs_code": c["hs_code"],
                        "description": f"{c.get('description_en', '')} / {c.get('description_vn', '')}"
                    })
                    seen_codes.add(c["hs_code"])
                    
        # 1.2 Lấy Top 5 từ Semantic Vector Search (Mô tả tiếng Việt/Anh)
        vector_query = item_description
        if extracted_features:
            vector_query += f". Material: {extracted_features.get('material','')}. Function: {extracted_features.get('function','')}"
            
        vector_res = search_hs_nodes(vector_query)
        if "results" in vector_res:
            for c in vector_res["results"]:
                if c["hs_code"] not in seen_codes:
                    candidate_pool.append({
                        "hs_code": c["hs_code"],
                        "description": c["description"]
                    })
                    seen_codes.add(c["hs_code"])
                    
        # 1.3 Bơm Legal Notes (Rules/Exclusions) vào từng ứng viên
        local_rules_cache = {}
        for cand in candidate_pool:
            ch_id = cand["hs_code"][:2]
            try:
                if ch_id not in local_rules_cache:
                    rules_data = get_chapter_rules(ch_id)
                    exclText = ""
                    # Giả định nếu rules_data có 'exclusions'
                    if isinstance(rules_data, dict) and "exclusions" in rules_data:
                        for ex in rules_data.get("exclusions", []):
                            exclText += f"- Exclude if {ex.get('condition','')} -> go to {ex.get('action','')}\n"
                    else: 
                         # Nếu string thô
                         exclText = str(rules_data).split("Nhóm")[0][:300] if isinstance(rules_data, str) else ""
                    local_rules_cache[ch_id] = exclText.strip()
                
                cand["legal_notes"] = local_rules_cache[ch_id]
            except Exception:
                cand["legal_notes"] = ""
                
        # ═══════════════════════════════════════════════════════════════════════
        # [NEW V3] PHASE 2: LLM JUDGE (ONE-SHOT ELIMINATION)
        # ═══════════════════════════════════════════════════════════════════════
        judge_failed = True
        judge_feedback = ""
        
        if candidate_pool:
            print(f"\n[V3 PHASE 2] LLM Judge đang chấm {len(candidate_pool)} ứng viên...")
            if stream_callback:
                stream_callback({"type": "info", "message": f"⚖️ [PHASE 2] Khởi động AI Judge chấm điểm {len(candidate_pool)} mã HS ứng viên tiềm năng nhất..."})
                
            judge_res = self.judge.evaluate_candidates(item_description, candidate_pool, extracted_features)
            
            if judge_res.get("status") == "SUCCESS":
                chosen_code = judge_res.get("chosen_code")
                reasoning = judge_res.get("reasoning")
                print(f"✅ [JUDGE PASS] Judge đã chốt mã: {chosen_code}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"✅ Giám khảo AI chốt mã {chosen_code} thành công. Đang gửi sang Auditor..."})
                    
                # Chạy qua Gatekeeper và Auditor
                is_valid, linter_msg = self.gatekeeper.check(chosen_code, item_description, extracted_features)
                if is_valid:
                    draft_mock = {"hs_code": chosen_code, "reasoning": reasoning}
                    audit_res = self.auditor.audit(item_description, draft_mock)
                    if audit_res.get("status") != "FAIL":
                        # Thành công 100% - BYPASS CODER LOOP
                        print("\n[Pipeline V3] 🎉 THÀNH CÔNG NHỜ RERANKER! Bỏ qua Slow Path.")
                        if stream_callback:
                            stream_callback({"type": "info", "message": "🎉 THÀNH CÔNG! (Reranker Pipeline)"})
                            stream_callback({"type": "slow_path_result", "data": {
                                "is_agentic_path": True,
                                "final_section_id": chosen_code,
                                "confidence": "HIGH (LLM Judge & QA Checked)",
                                "reasoning": reasoning,
                                "clarifications": []
                            }})
                        self.cache_manager.set(item_description, chosen_code, reasoning, extracted_features)
                        return {
                            "status": "SUCCESS",
                            "final_hs_code": chosen_code,
                            "reasoning": reasoning,
                            "source": "v3_reranker"
                        }
                    else:
                        print(f"❌ [JUDGE REJECTED BY AUDITOR] {audit_res.get('feedback')}")
                        judge_feedback = f"Judge chọn {chosen_code} nhưng QA Auditor phản bác: {audit_res.get('feedback')}."
                        if stream_callback:
                            stream_callback({"type": "warning", "message": f"⚠️ Auditor từ chối quyết định của Judge: {audit_res.get('feedback')}. Kích hoạt Deep Agentic Coder!"})
                else:
                    print(f"❌ [JUDGE REJECTED BY LINTER] {linter_msg}")
                    judge_feedback = f"Judge chọn {chosen_code} nhưng vi phạm luật cứng: {linter_msg}."
                    if stream_callback:
                        stream_callback({"type": "warning", "message": f"⚠️ Judge vi phạm luật cứng: {linter_msg}. Kích hoạt Deep Agentic Coder!"})
            else:
                print(f"⚠️ [JUDGE FAIL] Không tìm được mã phù hợp trong rổ ứng viên.")
                judge_feedback = f"Judge đã loại toàn bộ ứng viên ở Phase 2: {judge_res.get('reasoning')}"
                if stream_callback:
                    stream_callback({"type": "warning", "message": f"⚠️ Judge loại bỏ toàn bộ {len(candidate_pool)} ứng viên. Kích hoạt Deep Agentic Coder!"})
        else:
            print(f"⚠️ [V3 PHASE 1] Không gom được ứng viên nào. Fallback to Slow Path.")
            if stream_callback:
                stream_callback({"type": "warning", "message": "⚠️ Không tìm thấy ứng viên khới điểm. Kích hoạt Deep Agentic Coder..."})

        # ═══════════════════════════════════════════════════════════════════════
        # [OLD V2] PHASE 3: THE SLOW PATH FALLBACK (AGENTIC REACT)
        # ═══════════════════════════════════════════════════════════════════════
        revision = 0
        current_feedback = judge_feedback # Truyền feedback của Judge/Auditor xuống cho Coder bắt đầu
        
        # Lấy Top Chapters từ Rổ Ứng Viên để Bypass Router
        candidate_chapters = []
        if candidate_pool:
            unique_ch = set()
            for cand in candidate_pool:
                ch = cand["hs_code"][:2]
                if ch not in unique_ch:
                    unique_ch.add(ch)
                    candidate_chapters.append(ch)
        
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
                
            if revision == 0 and fast_path_hint_node:
                print(f"Bỏ qua Tier-1 Router, sử dụng Hint từ Fast Path: {fast_path_hint_node}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"💡 Bỏ qua phân tích sơ bộ, tập trung điều tra từ nhóm {fast_path_hint_node}"})
                target_chapter = fast_path_hint_node[:2]
                starting_node_ids = [fast_path_hint_node]
                
                enhanced_desc = f"Tên hàng: {item_description}\n"
                if extracted_features:
                    enhanced_desc += f"\n[Step 0 - Basics Extraction (Reference)]\n"
                    enhanced_desc += f"- Item Name: {extracted_features.get('item_name', 'Unknown')}\n"
                    enhanced_desc += f"- State/Condition: {extracted_features.get('state_or_condition', 'Unknown')}\n"
                    enhanced_desc += f"- Material: {extracted_features.get('material', 'Unknown')}\n"
                    enhanced_desc += f"- Function: {extracted_features.get('function', 'Unknown')}\n"
                
                enhanced_desc += f"\n\n[LƯU Ý ĐẶC BIỆT TỪ FAST PATH]:\nHệ thống đã lexical keyword search với độ tự tin cao và nghi ngờ hàng hóa thuộc nhóm {fast_path_hint_node}.\n**TUY NHIÊN, ĐÂY CHỈ LÀ GỢI Ý (HINT)**. Trách nhiệm của bạn là phải ĐÁNH GIÁ LẠI xem nhóm {fast_path_hint_node} này CÓ THỰC SỰ ĐÚNG với mô tả hàng hóa không. Nếu ĐÚNG, hãy đi sâu vào nhánh con. Nếu THẤY SAI HOÀN TOÀN, hãy mạnh dạn YÊU CẦU THÊM THÔNG TIN (Clarification) hoặc tìm nhóm khác chứ KHÔNG bị ép buộc chốt mã ở đây."
            elif revision == 0 and candidate_chapters:
                print(f"Bỏ qua Tier-1 Router, sử dụng danh sách Chương từ V3 Reranker: {candidate_chapters[:3]}")
                if stream_callback:
                    stream_callback({"type": "info", "message": f"💡 Bỏ qua phân tích sơ bộ, hệ thống khoanh vùng được các Chương {candidate_chapters[:3]}"})
                starting_node_ids = candidate_chapters[:3]
                
                enhanced_desc = f"Tên hàng: {item_description}\n"
                if extracted_features:
                    enhanced_desc += f"\n[Step 0 - Basics Extraction (Reference)]\n"
                    enhanced_desc += f"- Item Name: {extracted_features.get('item_name', 'Unknown')}\n"
                    enhanced_desc += f"- State/Condition: {extracted_features.get('state_or_condition', 'Unknown')}\n"
                    enhanced_desc += f"- Material: {extracted_features.get('material', 'Unknown')}\n"
                    enhanced_desc += f"- Function: {extracted_features.get('function', 'Unknown')}\n"
            else:
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
                target_chapters = self.router.route_to_chapter(enhanced_desc, target_section, section_notes=section_notes_text, current_feedback=current_feedback, stream_callback=stream_callback)
                if not target_chapters or target_chapters == "UNKNOWN":
                    # Fallback về chapter đầu tiên của Section đã route (không hardcode "01")
                    from tools.knowledge_tools import get_chapters_for_section
                    fallback_chapters = get_chapters_for_section(target_section)
                    target_chapters = [fallback_chapters[0]] if fallback_chapters else ["01"]
                    
                # 4. Gắn LIST ID của Chapters vừa tìm được làm node xuất phát đệ quy cho Coder Agent
                starting_node_ids = target_chapters
                
            # 2. Coder sinh mã nháp từ vị trí Heading đã tìm
            prompt = enhanced_desc
            if current_feedback:
                prompt += f"\n\n[LƯU Ý TỪ LẦN TRƯỚC BỊ LỖI]: {current_feedback}\nHãy tra cứu kỹ lại Chú giải hoặc Nhóm khác để tìm mã đúng."
                
            draft_result = self.coder.classify_item(prompt, starting_node_ids, max_steps=8, stream_callback=stream_callback, input_callback=input_callback)
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
                    stream_callback({"type": "warning", "message": f"⚠️ Linter Failed: {linter_msg}. Đang yêu cầu LLM thử lại..."})
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
                    stream_callback({"type": "warning", "message": f"⚠️ QA Auditor TỪ CHỐI mã HS này: {audit_result['feedback']}. Đang yêu cầu LLM thử lại..."})
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
