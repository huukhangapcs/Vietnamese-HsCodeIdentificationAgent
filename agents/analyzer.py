import os
import json
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client

class ItemAnalyzer:
    def __init__(self):
        self.client = get_llm_client()
        self.model = "deepseek-chat"
        
    def verify_input(self, item_description: str) -> dict:
        """Kiểm tra tính hợp lệ kết hợp Thuật toán (Heuristics) và LLM"""
        desc_lower = item_description.strip().lower()
        
        # 1. Thuật toán: Độ dài & Từ khóa tĩnh
        if len(desc_lower) < 2:
            return {"is_valid": False, "reason": "Mô tả quá ngắn, không cấu thành hàng hóa."}
            
        stop_words = ["hello", "hi", "ok", "test", "alo", "chào", "xin chào", "tôi cần hỏi", "hỏi xíu"]
        for word in stop_words:
            if desc_lower == word or desc_lower.startswith(word + " "):
                return {"is_valid": False, "reason": f"Phát hiện từ khóa giao tiếp '{word}', đây không phải là mô tả hàng hóa."}
                
        # 2. LLM Validation: Lọc hành vi phức tạp
        system_prompt = """You are an Input Validator for a Customs HS Code system.
Determine if the user's input is a valid description of a physical good/product to be imported/exported.
If the input is just conversational, a question without an item, meaningless, or not a physical good, it is INVALID.
Respond STRICTLY with a JSON object:
{
  "is_valid": true/false (boolean),
  "reason": "Lý do bằng tiếng Việt nếu không hợp lệ (nếu hợp lệ để chuỗi rỗng)"
}"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Input: {item_description}"}
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
                
            return json.loads(content.strip())
        except Exception as e:
            # Fallback
            return {"is_valid": True, "reason": ""}

    def extract_features(self, item_description: str) -> dict:
        """Trích xuất 4 đặc trưng cơ bản bằng Tiếng Anh"""
        system_prompt = """You are an Expert Customs Item Analyzer.
Your task is to analyze the user's item description (which is usually in Vietnamese) and explicitly extract 4 core physical characteristics IN ENGLISH to help classify the HS Code.

Respond STRICTLY with a JSON object containing EXACTLY these keys (all values MUST be translated to English):
{
  "item_name": "What is the specific name of the item? (English)",
  "state_or_condition": "What is the physical state or condition (e.g., fresh, frozen, dried, new, used, unassembled, liquid, powder)? If not mentioned, write 'Unknown'. (English)",
  "material": "What is the primary material composition (e.g., plastic, wood, steel, cotton)? If not applicable, write 'Not Applicable'. (English)",
  "function": "What is the main function or purpose (e.g., used for seating, agricultural machinery)? (English)"
}"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this item: {item_description}"}
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
            print(f"  👉 Item Name: {result.get('item_name', 'Unknown')}")
            print(f"  👉 State/Condition: {result.get('state_or_condition', 'Unknown')}")
            print(f"  👉 Material: {result.get('material', 'Unknown')}")
            print(f"  👉 Function: {result.get('function', 'Unknown')}")
            return result
        except Exception as e:
            print(f"Analyzer Error: {e}")
            return {}

    def analyze(self, item_description: str) -> dict:
        """
        Main pipeline step 0: Validates input, then extracts features.
        """
        print(f"\n[Step 0 - Analyzer] Đang kiểm tra tính hợp lệ của dữ liệu...")
        validation = self.verify_input(item_description)
        
        if not validation.get("is_valid", True):
            print(f"  👉 Hợp lệ: False - {validation.get('reason')}")
            return {"is_valid": False, "reason": validation.get("reason")}
            
        print(f"\n[Step 0 - Analyzer] Đang trích xuất đặc trưng cơ bản bằng Tiếng Anh...")
        features = self.extract_features(item_description)
        features["is_valid"] = True
        return features

if __name__ == "__main__":
    analyzer = ItemAnalyzer()
    res = analyzer.analyze("Ghế xoay văn phòng có đệm bọc da")
    print(res)
