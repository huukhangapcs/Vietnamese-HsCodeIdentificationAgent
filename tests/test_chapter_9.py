import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

def run_tests():
    pipeline = HSPipeline()

    print("\n" + "="*50)
    print("### TEST CASE CHAPTER 9 - 1: Cubeb Pepper (Expected Exclusion) ###")
    print("="*50)
    # Cubeb pepper should be excluded from Ch9 and thrown out to 12.11
    pipeline.classify("Hạt tiêu Cubeb (Cubeb pepper - Piper cubeba) dạng khô dùng trong dược liệu.")
    
    print("\n" + "="*50)
    print("### TEST CASE CHAPTER 9 - 2: Pure White Pepper (Expected 0904.11) ###")
    print("="*50)
    # Regular pepper
    pipeline.classify("Hạt tiêu trắng (White pepper) nguyên hạt chưa xay hoặc nghiền.")
    
    print("\n" + "="*50)
    print("### TEST CASE CHAPTER 9 - 3: Spice Mixture containing Vanilla and Pepper (Expected 0910) ###")
    print("="*50)
    # Different headings mixer -> should be 0910
    pipeline.classify("Hỗn hợp gia vị gồm hạt tiêu trắng (White pepper) và vani (Vanilla) đã nghiền.")

if __name__ == "__main__":
    run_tests()
