import json
import os
import time
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE_DIR, "database", "hs_cache.json")

class CacheManager:
    def __init__(self):
        # Ensure database directory exists
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if not os.path.exists(CACHE_FILE):
            return {}
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[CacheManager] Error loading cache: {e}")
            return {}

    def _save_cache(self):
        # ATOMIC WRITE: ghi temp file rồi rename để tránh corrupt nếu 2 threads ghi đồng thời
        try:
            dir_path = os.path.dirname(CACHE_FILE)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8',
                dir=dir_path, delete=False, suffix='.tmp'
            ) as tmp_f:
                json.dump(self.cache, tmp_f, ensure_ascii=False, indent=2)
                tmp_path = tmp_f.name
            shutil.move(tmp_path, CACHE_FILE)  # Atomic replace
        except Exception as e:
            print(f"[CacheManager] Error saving cache: {e}")

    def _normalize_key(self, description: str, features: dict) -> str:
        """
        Creates a deterministic hashable key based on description and extracted features.
        In a production system, this could be a semantic vector embedding.
        For MVP, we use exact matching of the lowercased description + features.
        """
        key_str = description.lower().strip()
        if features:
            # Sort features to ensure consistent key ordering
            sorted_features = sorted(features.items())
            feature_str = "_".join(f"{k}:{v}" for k, v in sorted_features).lower()
            key_str = f"{key_str}|{feature_str}"
        return key_str

    def get(self, description: str, features: dict = None) -> dict:
        """
        Retrieves a cached HS Code result.
        Returns None if Miss.
        """
        key = self._normalize_key(description, features or {})
        return self.cache.get(key)

    def set(self, description: str, hs_code: str, reasoning: str, features: dict = None):
        """
        Saves a successful QA-approved run into the cache.
        """
        key = self._normalize_key(description, features or {})
        self.cache[key] = {
            "hs_code": hs_code,
            "reasoning": reasoning,
            "timestamp": time.time(),
            "source": "Agentic ReAct Pipeline"
        }
        self._save_cache()
