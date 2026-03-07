import os
from openai import OpenAI

# Define absolute path to be able to access the key file from anywhere
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_llm_client = None

def get_llm_client():
    global _llm_client
    if _llm_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            key_path = os.path.join(BASE_DIR, "key_deepseek")
            try:
                with open(key_path, "r") as f:
                    api_key = f.read().strip()
            except FileNotFoundError:
                raise ValueError("ERROR: Không tìm thấy API KEY Deepseek.")
                
        _llm_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        
    return _llm_client
