import os
import json
import sys

# Define absolute path to be able to import local modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client
from core.schemas import CODER_TOOLS
from tools.knowledge_tools import navigate_node, get_section_notes, get_chapter_rules, get_general_rules, search_hs_nodes, query_legal_notes

class HSCoderAgent:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        self.tools = CODER_TOOLS
        
    def execute_tool(self, function_name, arguments):
        if function_name == "navigate_node":
            node_id = arguments.get("node_id")
            return json.dumps(navigate_node(node_id), ensure_ascii=False)
        elif function_name == "get_section_notes":
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

    def classify_item(self, item_description: str, starting_node_id: str, max_steps: int = 15, current_feedback: str = "", stream_callback=None, input_callback=None) -> dict:
        """
        Runs the ReAct loop to classify the item, starting straight from a localized node.
        """
        system_prompt = f"""You are the 'Coder Agent' for Customs HS Code Classification.
Your job is to determine the correct HS Code (up to 4, 6 or 8 digits) for a given item.

[GENERAL INTERPRETATIVE RULE 1 (GIR 1) - THE SUPREME RULE]
The titles of Sections, Chapters and sub-Chapters are provided for ease of reference only.
For legal purposes, classification shall be determined exclusively according to the terms of the headings and any relative Section or Chapter Notes.
If the Legal Notes state that an item belongs to another chapter (e.g., 9508 instead of 0106), you MUST obey the Note over the Chapter Name.
[EXPERT REASONING FRAMEWORK - THE 3 GOLDEN QUESTIONS]
Before making any tool calls, you MUST explicitly analyze the item description by answering these 3 questions in your thought process (do not skip this step):
1. Material (Chất liệu chính là gì?): Determines the Chapter (e.g., Plastic -> 39, Wood -> 44).
2. Function/Purpose (Công dụng chính để làm gì?): Determines the Heading (e.g., Plastic used for Seating -> 9401 instead of 3926).
3. Specific Characteristics (Đặc tính riêng biệt?): Determines the Subheading (e.g., Swivel chair -> 9401.30 vs Wooden chair -> 9401.61).
Focus on the essence of the good, NEVER be overly influenced by marketing names. If the user's description is missing crucial info that is ACTUALLY RELEVANT to classify this specific object, use the `ask_user_clarification` tool. 
⚠️ EXCEPTION TO MATERIAL QUESTION: Do NOT ask the user for "Material" if the item is obviously a Live Animal, Plant, Food, Chemical, or a highly Complex Machine/Vehicle where the physical "material composition" (like plastic/metal) is completely irrelevant to the HS Code.
[CRITICAL INSTRUCTIONS (Based on GIRs - 6 Quy tắc vàng)]
1. GIR 1 (LUÔN ÁP DỤNG TRƯỚC TIÊN): Phân loại phải dựa vào nội dung Nhóm hàng và Chú giải (Section/Chapter Notes). Tên chương, phần chỉ để tham khảo.
   IMMEDIATELY call query_legal_notes(query, "TBD", "{str(starting_node_id)[:2]}") to check EXCLUSIONS. You MUST ensure your item is not legally excluded from the current Chapter.
2. GIR 2a, 3a, 4, 5: Call get_general_rules if dealing with unassembled, mixture, or packaging goods.
3. VECTOR SEARCH NAVIGATION: DO NOT GUESS HS CODES. You MUST call search_hs_nodes(query, chapter_id) using a highly descriptive semantic query (e.g. 'smartwatch bluetooth electronic') to retrieve the top 5 relevant subheadings from the database. 
4. CHAPTER JUMPING: If the vector search returns highly relevant Results with distances < 1.0 that belong to a DIFFERENT Chapter, and they fit your Material/Function analysis better, you ARE AUTHORIZED to switch your focus to that new Chapter.
5. If stuck between distinct valid options to move forward and lacking info, CALL ask_user_clarification(question).

Once you reach a leaf node OR hit an explicit Exclusion Rule, return your final answer in JSON format:
{{"hs_code": "01012100", "reasoning": "Detailed explanation citing the specific heading texts and any Legal Notes applied..."}}
Do not return any other markdown outside the JSON block.
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
                    
                    if tool_result.startswith("CLARIFICATION_NEEDED:"):
                        clarification_count += 1
                        # Nếu KHÔNG CÓ input_callback (chạy thuần Terminal CLI rỗng), chặn ở lần 2 để tránh dead-loop
                        if not input_callback and clarification_count > 1:
                            tool_result = "SYSTEM BLOCK: You have already asked for clarification. You MUST make a best-effort prediction using available information instead of asking again."
                            messages.append({"role": "system", "content": tool_result})
                            continue
                        else:
                            try:
                                payload_str = tool_result.split("CLARIFICATION_NEEDED:")[1]
                                payload = json.loads(payload_str)
                                question = payload.get("question")
                                options = payload.get("options", [])
                            except:
                                question = tool_result.split("CLARIFICATION_NEEDED:")[1]
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
                    
                    # ---------------------------------------------------------
                    # STRATEGY 1: MESSAGE PRUNING (Token Optimization)
                    # Bỏ cắt JSON thô bạo do làm LLM bị loạn vì mất rules và sai format JSON
                    # Cứ để full message để Agent giữ được context đầy đủ.
                    # ---------------------------------------------------------
                    
                    # Add newest tool call and result to messages in FULL
                    messages.append({"role": "assistant", "tool_calls": [tool_call]})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": str(tool_result)
                    })
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
