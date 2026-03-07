import os
import sys

# Đảm bảo import core package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))

from core.pipeline import HSPipeline

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    print("\n\n### TEST CASE CHAPTER 2: Thịt gà (Chưa chặt mảnh, đông lạnh) ###")
    pipeline.classify(
        "Thịt gà (Gallus domesticus) chưa chặt mảnh, đông lạnh.", 
        extracted_features={"material": "Thịt gà", "function": "Thực phẩm", "loại": "đông lạnh", "chưa chặt mảnh": True}
    )
    
    print("\n\n### TEST CASE CHAPTER 2 EXCLUSION: Côn trùng ###")
    pipeline.classify(
        "Côn trùng khô làm món ăn đặc sản.", 
        extracted_features={"material": "Côn trùng", "function": "Thực phẩm"}
    )
