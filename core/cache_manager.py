import json
import os
import time
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE_DIR, "database", "hs_cache.json")

# ─── Redis backend (tuỳ chọn) ─────────────────────────────────────────────────
_redis_client = None
_redis_available = False
CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 ngày TTL cho Redis entries


def _get_redis():
    """Lazy-init Redis client. Trả None nếu Redis không khả dụng."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        _redis_available = False
        return None

    try:
        import redis
        client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()   # Test kết nối
        _redis_client = client
        _redis_available = True
        print(f"[CacheManager] ✅ Redis connected: {redis_url}")
        return _redis_client
    except Exception as e:
        print(f"[CacheManager] ⚠️  Redis unavailable ({e}), falling back to JSON file cache.")
        _redis_available = False
        return None


class CacheManager:
    def __init__(self):
        # Ensure database directory exists (cho JSON fallback)
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)

        # Thử dùng Redis trước, nếu không có thì load JSON
        r = _get_redis()
        if r is None:
            self._json_cache = self._load_json_cache()
        else:
            self._json_cache = {}   # Không cần load khi có Redis

    # ─── JSON fallback persistence ───────────────────────────────────────────

    def _load_json_cache(self) -> dict:
        if not os.path.exists(CACHE_FILE):
            return {}
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[CacheManager] Error loading JSON cache: {e}")
            return {}

    def _save_json_cache(self):
        """Atomic write để tránh corrupt nếu 2 threads ghi đồng thời."""
        try:
            dir_path = os.path.dirname(CACHE_FILE)
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8',
                dir=dir_path, delete=False, suffix='.tmp'
            ) as tmp_f:
                json.dump(self._json_cache, tmp_f, ensure_ascii=False, indent=2)
                tmp_path = tmp_f.name
            shutil.move(tmp_path, CACHE_FILE)  # Atomic replace
        except Exception as e:
            print(f"[CacheManager] Error saving JSON cache: {e}")

    # ─── Key normalization ───────────────────────────────────────────────────

    def _normalize_key(self, description: str, features: dict) -> str:
        """
        Tạo cache key deterministic từ description + features.
        Trong production nên dùng semantic vector embedding.
        """
        key_str = description.lower().strip()
        if features:
            sorted_features = sorted(features.items())
            feature_str = "_".join(f"{k}:{v}" for k, v in sorted_features).lower()
            key_str = f"{key_str}|{feature_str}"
        return f"hscode:{key_str}"   # Prefix namespace cho Redis

    # ─── Public API ──────────────────────────────────────────────────────────

    def get(self, description: str, features: dict = None) -> dict:
        """Lấy cached HS Code. Trả None nếu miss."""
        key = self._normalize_key(description, features or {})

        r = _get_redis()
        if r:
            try:
                raw = r.get(key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as e:
                print(f"[CacheManager] Redis GET error: {e}, falling back to JSON")

        # JSON fallback
        return self._json_cache.get(key)

    def set(self, description: str, hs_code: str, reasoning: str, features: dict = None):
        """Lưu kết quả vào cache (Redis nếu có, JSON nếu không)."""
        key = self._normalize_key(description, features or {})
        entry = {
            "hs_code": hs_code,
            "reasoning": reasoning,
            "timestamp": time.time(),
            "source": "Agentic ReAct Pipeline"
        }

        r = _get_redis()
        if r:
            try:
                r.setex(key, CACHE_TTL_SECONDS, json.dumps(entry, ensure_ascii=False))
                return
            except Exception as e:
                print(f"[CacheManager] Redis SET error: {e}, falling back to JSON")

        # JSON fallback
        self._json_cache[key] = entry
        self._save_json_cache()
