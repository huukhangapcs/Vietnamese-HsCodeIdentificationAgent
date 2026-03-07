import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.llm_provider import get_llm_client

# File paths
INPUT_FILE = os.path.join(BASE_DIR, "sections_info.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "database", "sections_info_aku.json")

client = get_llm_client()

SYSTEM_PROMPT = """Bạn là một chuyên gia về Hệ thống phân loại HS Code của Hải quan.
Nhiệm vụ của bạn là nhận đầu vào là các "Chú giải Phần" (Legal Notes) của hệ thống HS Code và cấu trúc hóa chúng thành định dạng JSON chuẩn.

Các chú giải pháp lý thường bao gồm 3 phần chính:
1. Exclusions (Loại trừ): Những mặt hàng không thuộc phần này.
2. Definitions (Định nghĩa khái niệm): Giải thích từ ngữ hoặc quy cách (ví dụ "Bột", "pellets").
3. Classification Rules (Quy tắc phân loại): Các nguyên tắc phân loại đặc thù.

HÃY CẤU TRÚC HÓA ĐOẠN VĂN BẢN (CHÚ GIẢI TIẾNG VIỆT VÀ TIẾNG ANH) THÀNH JSON SAU:
{
  "exclusions": [
    {
      "condition": "Mô tả điều kiện loại trừ. (Ví dụ: Động vật sống phục vụ xiếc)",
      "action": "Trỏ tới đâu. (Ví dụ: Chuyển sang Chương 95)",
      "keywords": ["từ khóa 1", "từ khóa 2", "..."] // Trích xuất 3-5 từ khóa quan trọng để phục vụ hệ thống RAG search.
    }
  ],
  "definitions": [
    {
      "term": "Thuật ngữ (Ví dụ: Viên)",
      "meaning": "Định nghĩa của thuật ngữ đó."
    }
  ],
  "classification_rules": [
    {
      "rule": "Mô tả quy tắc định hướng phân loại."
    }
  ]
}

- Nếu một hạng mục không có dữ liệu chắt lọc được, hãy để mảng rỗng `[]`.
- Không tự sáng tác quy tắc, CHỈ dựa trên đoạn văn bản được cung cấp.
- Trả về CHỈ một block JSON hợp lệ, không có markdown code block (không có ```json ... ```), bắt đầu bằng '{' và kết thúc bằng '}' để có thể load bằng json.loads().
"""

def extract_structured_notes(section_id, notes_vi, notes_en):
    user_prompt = f"""
Hãy phân tích và bóc tách các chú giải pháp lý sau cho {section_id}:

[NOTES_VI]
{notes_vi}

[NOTES_EN]
{notes_en}
"""
    print(f"Đang bóc tách {section_id}...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        
        # Clean markdown if present
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        return json.loads(content)
        
    except Exception as e:
        print(f"Lỗi khi xử lý {section_id}: {e}")
        # In out raw content to see why it failed
        if 'content' in locals():
            print(f"Raw output:\n{content}")
        return {
            "exclusions": [],
            "definitions": [],
            "classification_rules": [{"rule": f"Error parsing: {notes_vi}"}]
        }

def main():
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        old_data = json.load(f)
        
    new_data = {}
    
    # Đảm bảo thư mục lưu trữ tồn tại
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Ta xử lý từng section 1
    total = len(old_data)
    count = 1
    for section_id, info in old_data.items():
        print(f"[{count}/{total}] Bắt đầu: {section_id}")
        notes_vi = info.get("notes_vi", "")
        notes_en = info.get("notes_en", "")
        
        # Nếu không có note thì ta tạo JSON trống trực tiếp
        structured_notes = {"exclusions": [], "definitions": [], "classification_rules": []}
        
        if notes_vi.strip() or notes_en.strip():
            structured_notes = extract_structured_notes(section_id, notes_vi, notes_en)
            
        new_data[section_id] = {
            "title_vi": info.get("title_vi", ""),
            "title_en": info.get("title_en", ""),
            "structured_notes": structured_notes,
            # Giữ lại bản ghi cũ làm fallback nếu LLM miss thông tin
            "raw_notes_vi": notes_vi, 
            "raw_notes_en": notes_en
        }
        count += 1
        
        # Save tiến trình liên tục để tránh mất dữ liệu nếu đứt gãy
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as out_f:
            json.dump(new_data, out_f, ensure_ascii=False, indent=2)

    print(f"\\n✅ Hoàn tất! File đã được lưu tại: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
