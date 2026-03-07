import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    print("\n\n### TEST CASE CHAPTER 5 - 1: Tóc người chưa xử lý ###")
    pipeline.classify("Tóc người chưa xử lý.")
    
    print("\n\n### TEST CASE CHAPTER 5 - 2: Ruột lợn muối ###")
    pipeline.classify("Ruột lợn được ướp muối đóng gói hộp xốp.")
