import os
import json
import sys

# Define absolute path to be able to import local modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from core.schemas import CODER_TOOLS
from tools.knowledge_tools import get_section_notes, get_chapter_rules, get_general_rules, search_hs_nodes, query_legal_notes

class HSCoderAgent:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        self.tools = CODER_TOOLS
        
    def execute_tool(self, function_name, arguments):
        if function_name == "get_section_notes":
            section_id = arguments.get("section_id")
            return json.dumps(get_section_notes(section_id), ensure_ascii=False)
        elif function_name == "get_chapter_rules":
            chapter_id = arguments.get("chapter_id")
            item_description = arguments.get("item_description", "")
            return json.dumps(get_chapter_rules(chapter_id, item_description), ensure_ascii=False)
        elif function_name == "get_general_rules":
            rule_ids = arguments.get("rule_ids", [])
            return json.dumps(get_general_rules(rule_ids), ensure_ascii=False)
        elif function_name == "search_hs_nodes":
            query = arguments.get("query")
            chapter_id = arguments.get("chapter_id")
            return json.dumps(search_hs_nodes(query, chapter_id), ensure_ascii=False)
        elif function_name == "query_legal_notes":
            query = arguments.get("query")
            section_id = arguments.get("section_id")
            chapter_id = arguments.get("chapter_id")
            return json.dumps(query_legal_notes(query, section_id, chapter_id), ensure_ascii=False)
        elif function_name == "ask_user_clarification":
            # Return a special flag to break the react loop and return to pipeline
            question = arguments.get("question")
            options = arguments.get("options", [])
            return f"CLARIFICATION_NEEDED:{json.dumps({'question': question, 'options': options}, ensure_ascii=False)}"
        else:
            return f"Error: function {function_name} not found."

    def classify_item(self, item_description: str, starting_node_ids: list, max_steps: int = 5, current_feedback: str = "", stream_callback=None, input_callback=None) -> dict:
        """
        Runs the ReAct loop to classify the item, starting straight from localized nodes.
        """
        # Đảm bảo starting_node_ids là list
        if isinstance(starting_node_ids, str):
            starting_node_ids = [starting_node_ids]
            
        candidate_chapters_str = ", ".join(starting_node_ids)
        primary_chap = starting_node_ids[0] if starting_node_ids else "01"

        system_prompt = f"""You are the 'Coder Agent' for Customs HS Code Classification.
Your job is to determine the correct HS Code (up to 4, 6 or 8 digits) for a given item.

[Top 3 Candidate Chapters from Router]: {candidate_chapters_str}
(These are your starting points, but you have the freedom to explore globally if they do not fit the Material or Function perfectly.)

[EXPERT REASONING FRAMEWORK - THE 3 GOLDEN QUESTIONS]
Before making any tool calls, you MUST explicitly analyze the item description:
1. Material (Chất liệu chính là gì?): Determines the Chapter.
2. Function/Purpose (Công dụng chính để làm gì?): Determines the Heading.
3. Specific Characteristics (Đặc tính riêng biệt?): Determines the Subheading.

[CRITICAL INSTRUCTIONS (Based on GIRs - 6 Quy tắc vàng)]
1. GIR 1: Phân loại phải dựa vào nội dung Nhóm hàng và Chú giải (Section/Chapter Notes).
   IMMEDIATELY call query_legal_notes(query, "TBD", "{primary_chap}") to check EXCLUSIONS.
2. MULTI-PATH & GLOBAL SEARCH: DO NOT GUESS HS CODES. You should call search_hs_nodes(query, chapter_id=None) for GLOBAL SEARCH using a highly descriptive semantic query. If you suspect a specific candidate chapter, pass its chapter_id.
3. CHAPTER/PATH JUMPING: If the results in one candidate chapter hit an Exclusion Note or do not fit, switch to the next candidate chapter immediately.
4. If stuck between distinct valid options and lacking info, CALL ask_user_clarification(question).
5. ANTI-LOOP MECHANISM (CRITICAL): If you have called tools 3 times without finding a matching heading/subheading, STOP SEARCHING IMMEDIATELY. Make a best-effort prediction using available info, or return "UNKNOWN"/ask_user_clarification. DO NOT retry the exact same query twice.

Return your final answer in JSON format:
{{"hs_code": "01012100", "reasoning": "Detailed explanation citing the specific heading texts and any Legal Notes applied..."}}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Classify this item: {item_description}"}
        ]
        
        print(f"\n--- BẮT ĐẦU CODER AGENT (ReAct) ---")
        print(f"Item: {item_description}")
        
        step = 0
        clarification_count = 0
        clarifications = []
        while step < max_steps:
            step += 1
            print(f"\n[Bước {step}] Đang suy nghĩ...")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto"
            )
            
            response_msg = response.choices[0].message
            
            if response_msg.tool_calls:
                # Convert all tool calls to pure dicts to avoid Pydantic serialization bugs in python 3.14
                tool_calls_dicts = []
                for tc in response_msg.tool_calls:
                    tool_calls_dicts.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
                
                # Append ONE assistant message containing ALL tool calls (Correct OpenAI schema)
                messages.append({"role": "assistant", "tool_calls": tool_calls_dicts})

                for tool_call in response_msg.tool_calls:
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    
                    print(f"🛠  Action: Gọi công cụ `{function_name}` với tham số {arguments}")
                    if stream_callback:
                        stream_callback({
                            "type": "action",
                            "function": function_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False)
                        })
                    
                    # Execute tool
                    tool_result = self.execute_tool(function_name, arguments)
                    
                    if "chưa được hỗ trợ" in str(tool_result) or "chưa được index" in str(tool_result):
                        error_msg = json.loads(tool_result).get("error", "Dữ liệu chưa được hỗ trợ (Unindexed).") if "{" in str(tool_result) else "Dữ liệu chưa được hỗ trợ"
                        return {"hs_code": "UNSUPPORTED_CHAPTER", "reasoning": error_msg}
                        
                    if stream_callback and not str(tool_result).startswith("CLARIFICATION_NEEDED:"):
                        stream_callback({
                            "type": "observation",
                            "length": len(str(tool_result)),
                            "data": str(tool_result)[:1000] # Bắt 1000 kí tự để không nổ frontend
                        })
                    
                    if str(tool_result).startswith("CLARIFICATION_NEEDED:"):
                        clarification_count += 1
                        # Nếu KHÔNG CÓ input_callback (chạy thuần Terminal CLI rỗng), chặn ở lần 2 để tránh dead-loop
                        if not input_callback and clarification_count > 1:
                            tool_result = "SYSTEM BLOCK: You have already asked for clarification. You MUST make a best-effort prediction using available information instead of asking again."
                            messages.append({"role": "system", "content": tool_result})
                            continue
                        else:
                            try:
                                payload_str = str(tool_result).split("CLARIFICATION_NEEDED:")[1]
                                payload = json.loads(payload_str)
                                question = payload.get("question")
                                options = payload.get("options", [])
                            except:
                                question = str(tool_result).split("CLARIFICATION_NEEDED:")[1]
                                options = []
                            
                            # Nếu Web mode (có input_callback)
                            if input_callback and stream_callback:
                                stream_callback({
                                    "type": "clarification_request",
                                    "question": question,
                                    "options": options
                                })
                                print(f"🛑 [PAUSE THREAD] Chờ phản hồi từ người dùng cho câu hỏi: {question}")
                                # BLOCKING CALL - CHỜ QUEUE GET()
                                user_answer = input_callback()
                                print(f"▶ [RESUME THREAD] Người dùng đã chọn: {user_answer}")
                                
                                clarifications.append({"question": question, "answer": user_answer})
                                
                                # Thay đổi tool_result thành câu trả lời để LLM đọc như 1 tool output
                                tool_result = f"Người dùng đã trả lời: '{user_answer}'. Vui lòng tiếp tục phân tích và suy luận mã HS cuối cùng."
                            else:
                                # Fallback Terminal mode
                                return {"hs_code": "CLARIFICATION_NEEDED", "question": question, "options": options, "reasoning": "Need more info from user."}
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": str(tool_result)[:1500]  # Tăng giới hạn lên 1500 ký tự để đọc đầy đủ hơn
                    })

                # ---------------------------------------------------------
                # STRATEGY: SUMMARIZATION MEMORY (thay Hard Pruning)
                # Thay vì xóa cứng các message cũ (dễ làm Agent "mất trí nhớ"),
                # ta tóm tắt lại các bước đã đi thành 1 context message gọn.
                # ---------------------------------------------------------
                HISTORY_THRESHOLD = 3  # Giảm xuống 3 để tránh bùng nổ Token
                if len(messages) > HISTORY_THRESHOLD:
                    # Thu thập tất cả các tool calls + results cũ (trừ system + user prompt gốc)
                    old_pairs = messages[2:]  # Bỏ qua index 0 (system) và 1 (user prompt)
                    
                    # Tóm tắt gọn lại: chỉ giữ function name, args ngắn gọn, và kết quả quan trọng
                    summary_lines = []
                    for msg in old_pairs:
                        if msg.get("role") == "assistant" and msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                try:
                                    args_obj = tc.get("function", {}).get("arguments", "{}")
                                    if isinstance(args_obj, str):
                                        args_obj = json.loads(args_obj)
                                    # Lấy tham số quan trọng nhất (node_id, chapter_id, query...)
                                    key_arg = (args_obj.get("node_id") or args_obj.get("chapter_id") 
                                               or args_obj.get("query", "")[:40] or "")
                                    summary_lines.append(f"• Called {tc.get('function', {}).get('name')}({key_arg})")
                                except Exception:
                                    summary_lines.append(f"• Called {tc.get('function', {}).get('name')}")
                        elif msg.get("role") == "tool":
                            # Chỉ giữ phần đầu của kết quả (quan trọng nhất)
                            content_preview = str(msg.get("content", ""))[:150].replace("\n", " ")
                            summary_lines.append(f"  → Result: {content_preview}")

                    if summary_lines:
                        summary_text = "CONTEXT MEMORY (Các bước đã thực hiện):\n" + "\n".join(summary_lines[-10:])  # Max 10 dòng
                        # Reset messages: giữ system + user prompt gốc + summary
                        messages = [
                            messages[0],  # system
                            messages[1],  # user original prompt
                            {"role": "system", "content": summary_text}
                        ]
                        print(f"  📝 [Memory] Đã tóm tắt {len(old_pairs)} messages cũ thành context summary.")

            else:
                # No more tool calls, it should be the final answer
                content = response_msg.content
                print(f"✅ Final Answer: {content}")
                
                try:
                    # Extract JSON block between { and }
                    start_idx = content.find('{')
                    end_idx = content.rfind('}')
                    
                    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                        json_str = content[start_idx:end_idx+1]
                        result = json.loads(json_str)
                        result["clarifications"] = clarifications
                        return result
                    else:
                        raise ValueError("No JSON block found")
                        
                except Exception as e:
                    return {"hs_code": "UNKNOWN", "reasoning": f"Format error: {e}"}
        
        return {"hs_code": "UNKNOWN", "reasoning": "Quá số bước tối đa (Max steps reached)! Coder bị tắc nghẽn."}

if __name__ == "__main__":
    agent = HSCoderAgent()
    print("Testing Interactive Mode...")
    # Using 'Ngựa' which is very vague. It should ask whether it's for breeding or other.
    res = agent.classify_item("Mình muốn nhập khẩu 100 con Ngựa sống về nông trại.")
    print(f"\\nClarification Triggered: {res}")
