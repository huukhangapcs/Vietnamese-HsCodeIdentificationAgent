import json
from tools.knowledge_tools import query_legal_notes

try:
    res = query_legal_notes("raw crocodile skin reptile hide", "SECTION_VIII", "41")
    print(json.dumps(res, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")
