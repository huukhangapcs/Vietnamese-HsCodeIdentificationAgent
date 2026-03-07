import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    print("\n\n### TEST CASE CHAPTER 6 - 1: Hoa cẩm chướng tươi ###")
    pipeline.classify("Hoa cẩm chướng cắt cành tươi dùng để cắm lẵng hoa.")
    
    print("\n\n### TEST CASE CHAPTER 6 - 2: Cây phong lan giống ###")
    pipeline.classify("Cây phong lan giống nhập khẩu.")
