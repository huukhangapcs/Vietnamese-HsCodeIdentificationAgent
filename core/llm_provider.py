import os
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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
                raise ValueError("ERROR: Không tìm thấy API KEY Deepseek. Set env var DEEPSEEK_API_KEY.")

        _llm_client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
            timeout=60.0,       # Timeout 60s per request (mặc định là vô hạn)
            max_retries=0,      # Tắt retry mặc định của OpenAI, dùng tenacity thay thế
        )

    return _llm_client


def llm_call_with_retry(client, **kwargs):
    """
    Wrapper gọi LLM với retry tự động dùng tenacity.
    - Retry tối đa 3 lần cho bất kỳ exception (timeout, rate limit, connection error)
    - Exponential backoff: 2s → 4s → 8s
    - Reraise exception cuối cùng nếu vẫn fail
    
    Usage:
        response = llm_call_with_retry(client, model="deepseek-chat", messages=[...])
    """
    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call():
        return client.chat.completions.create(**kwargs)

    return _call()
