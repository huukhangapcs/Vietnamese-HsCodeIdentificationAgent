import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client

TREE_FILE = os.path.join(BASE_DIR, "database", "chapter_1_tree.json")
RULES_FILE = os.path.join(BASE_DIR, "database", "chapter_1_rules.json")

client = get_llm_client()

def _add_semantic_path_to_tree(nodes, parent_path=""):
    for node in nodes:
        # Build the semantic path for the current node
        current_desc = node.get("description_en", "").strip().rstrip(":")
        if parent_path:
            # Tránh lặp nội dung nếu mô tả đã rõ ràng, nhưng ở mức cơ bản, nối chuỗi là an toàn nhất
            semantic_path = f"{parent_path} > {current_desc}"
        else:
            semantic_path = current_desc
            
        node["semantic_path"] = semantic_path
        
        # Recurse for children
        children = node.get("children", [])
        if children:
            _add_semantic_path_to_tree(children, semantic_path)

def optimize_tree():
    print("Bắt đầu tối ưu hóa chapter_1_tree.json...")
    with open(TREE_FILE, 'r', encoding='utf-8') as f:
        tree_data = json.load(f)
        
    _add_semantic_path_to_tree(tree_data)
    
    with open(TREE_FILE, 'w', encoding='utf-8') as f:
        json.dump(tree_data, f, ensure_ascii=False, indent=2)
    print("✅ Đã thêm `semantic_path` cho toàn bộ Tree.")

def extract_keywords_with_llm(condition_text):
    prompt = f"""
Trích xuất cho tôi danh sách từ 2 đến 6 từ khóa (danh từ, cụm danh từ) bắt buộc mang ý nghĩa nhận diện cốt lõi từ trong câu điều kiện loại trừ HS Code tiếng Anh sau. KHÔNG giải thích, CHỈ trả về mảng chuỗi kiểu JSON (ví dụ: ["fish", "crustaceans", "molluscs"]).
Câu: "{condition_text}"
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        return json.loads(content)
    except Exception as e:
        print(f"Lỗi extract_keywords_with_llm: {e}")
        return []

def optimize_rules():
    print("Bắt đầu tối ưu hóa chapter_1_rules.json...")
    with open(RULES_FILE, 'r', encoding='utf-8') as f:
        rules_data = json.load(f)
        
    exclusions = rules_data.get("exclusions", [])
    for exc in exclusions:
        if "keywords" not in exc:
            print(f"  Trích xuất keywords cho: {exc['condition'][:50]}...")
            exc["keywords"] = extract_keywords_with_llm(exc["condition"])
    
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(rules_data, f, ensure_ascii=False, indent=2)
    print("✅ Đã cập nhật `keywords` cho chapter_1_rules.json.")

if __name__ == "__main__":
    optimize_tree()
    optimize_rules()
