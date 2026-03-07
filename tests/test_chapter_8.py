import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    print("\n\n### TEST CASE CHAPTER 8 - 1: Quả dừa non (Young coconut) ###")
    pipeline.classify("Quả dừa non (Young coconut) tươi dùng làm nước uống.")
    
    print("\n\n### TEST CASE CHAPTER 8 - 2: Hạt điều nguyên vỏ (Cashew nuts in shell) ###")
    pipeline.classify("Hạt điều thô chưa bóc vỏ tươi.")
