import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

if __name__ == "__main__":
    pipeline = HSPipeline()
    
    print("\n\n### TEST CASE CHAPTER 4 - 1: Sữa chua hương dâu ###")
    pipeline.classify("Sữa chua hương dâu đóng hộp.")
    
    print("\n\n### TEST CASE CHAPTER 4 - 2: Pho mát vân xanh ###")
    pipeline.classify("Pho mát vân xanh.")
