import json
import asyncio
import datetime
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import threading
import queue
import sys
import os
import tempfile
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline
from core.security import rate_limiter, start_rate_limiter_cleanup

import uuid
from pydantic import BaseModel, field_validator

# API Key auth (optional - set env var HSCODE_API_KEY to enable)
_API_KEY = os.getenv("HSCODE_API_KEY", "")  # Rỗng = tắt auth (dev mode)

app = FastAPI(title="HS Code Agentic Router V13")

# Keep a pipeline instance ready
pipeline = HSPipeline()

# Store active input queues for each session { session_id: {"queue": queue.Queue, "created_at": float} }
# BUG-4 FIX: thêm timestamp để cleanup session bị treo (client disconnect)
active_sessions = {}
SESSION_TTL_SECONDS = 30 * 60  # 30 phút

def _cleanup_expired_sessions():
    """Background thread: xóa session quá TTL để tránh memory leak."""
    while True:
        time.sleep(300)  # Chạy mỗi 5 phút
        now = time.time()
        expired = [sid for sid, data in list(active_sessions.items())
                   if now - data.get("created_at", now) > SESSION_TTL_SECONDS]
        for sid in expired:
            active_sessions.pop(sid, None)
            print(f"[SessionCleanup] Expired session removed: {sid}")

threading.Thread(target=_cleanup_expired_sessions, daemon=True).start()
start_rate_limiter_cleanup()  # Dọn dẹp rate limiter buckets định kỳ


def _check_auth_and_rate(request: Request):
    """Kiểm tra API key và rate limit. Raise HTTPException nếu vi phạm."""
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate limiting (luôn áp dụng)
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Quá nhiều request. Vui lòng thử lại sau 1 phút."
        )

    # 2. API Key auth (chỉ khi HSCODE_API_KEY được set)
    if _API_KEY:
        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != _API_KEY:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: API key không hợp lệ."
            )

class AnswerPayload(BaseModel):
    session_id: str
    answer: str

    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v):
        # Validate UUID format để tránh spam vào session_id tùy ý
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError('session_id phải là UUID hợp lệ')
        return v

class ApprovePayload(BaseModel):
    query: str
    hs_code: str

    @field_validator('query')
    @classmethod
    def validate_query_length(cls, v):
        if len(v) > 3000:
            raise ValueError('query quá dài (tối đa 3000 ký tự)')
        return v

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/stream")
async def stream_agent(q: str, session_id: str, request: Request):
    """
    Streaming endpoint using Server-Sent Events (SSE) and Threading Queue.
    """
    _check_auth_and_rate(request)

    # Validate input length
    if len(q) > 2000:
        raise HTTPException(status_code=400, detail="Query quá dài (tối đa 2000 ký tự).")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query không được để trống.")

    q_stream = queue.Queue()
    input_q = queue.Queue()
    
    # Đăng ký session với timestamp để TTL cleanup có thể xóa nếu client disconnect
    active_sessions[session_id] = {"queue": input_q, "created_at": time.time()}

    def stream_callback(data):
        q_stream.put(data)
        
    def input_callback():
        # Block luồng (Thread) Agent lại, chờ người dùng gọi API /submit_answer
        # Timeout 25 phút để không block mãi mãi nếu user bỏ đi
        return input_q.get(timeout=SESSION_TTL_SECONDS - 300)

    def run_pipeline():
        try:
            pipeline.classify(q, stream_callback=stream_callback, input_callback=input_callback)
            q_stream.put(None) # EOF
        except Exception as e:
            q_stream.put({"type": "error", "message": str(e)})
            q_stream.put(None)
        finally:
            # Dọn dẹp session khi hoàn tất
            if session_id in active_sessions:
                del active_sessions[session_id]

    # Khởi tạo 1 thread Background để chạy Pipeline Agentic
    threading.Thread(target=run_pipeline, daemon=True).start()

    async def event_generator():
        while True:
            # Non-blocking read queued objects using asyncio.to_thread
            event = await asyncio.to_thread(q_stream.get)
            if event is None:
                break
                
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/submit_answer")
async def submit_answer(payload: AnswerPayload, request: Request):
    """
    Endpoint này 'đánh thức' Agent bằng cách nhét câu trả lời vào Input Queue
    của Session tương ứng.
    """
    # Rate limit áp dụng nhưng không cần auth key (frontend gọi internal)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Quá nhiều request.")

    if payload.session_id in active_sessions:
        active_sessions[payload.session_id]["queue"].put(payload.answer)
        return {"status": "success", "message": "Answer submitted to LLM Queue."}
    return {"status": "error", "message": "Session not found or expired."}

@app.post("/approve_hs")
async def approve_hs(payload: ApprovePayload, request: Request):
    """
    Endpoint lưu kết quả phê duyệt của người dùng làm Cache dữ liệu / Lịch sử / Fine-tuning.
    """
    _check_auth_and_rate(request)

    # Validate hs_code format: 8 chữ số
    if not payload.hs_code.isdigit() or len(payload.hs_code) not in (4, 6, 8):
        raise HTTPException(status_code=400, detail="hs_code phải là 4, 6 hoặc 8 chữ số.")

    cache_path = os.path.join(BASE_DIR, "database", "approved_cache.json")
    try:
        data = []
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except ValueError:
                    data = []

        new_entry = {
            "query": payload.query,
            "hs_code": payload.hs_code,
            "timestamp": datetime.datetime.now().isoformat()
        }
        data.append(new_entry)

        # ATOMIC WRITE: ghi vào temp file rồi rename để tránh corrupt
        dir_path = os.path.dirname(cache_path)
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8',
            dir=dir_path, delete=False, suffix='.tmp'
        ) as tmp_f:
            json.dump(data, tmp_f, ensure_ascii=False, indent=2)
            tmp_path = tmp_f.name
        shutil.move(tmp_path, cache_path)  # Atomic replace

        return {"status": "success", "message": "HS Code saved to cache."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Dev server: bind 127.0.0.1 (local only). Dùng 0.0.0.0 khi deploy qua Docker/nginx.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
