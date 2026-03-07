import json
import asyncio
import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import threading
import queue
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.pipeline import HSPipeline

import uuid
from pydantic import BaseModel

app = FastAPI(title="HS Code Agentic Router V13")

# Keep a pipeline instance ready
pipeline = HSPipeline()

# Store active input queues for each session { session_id: queue.Queue }
active_sessions = {}

class AnswerPayload(BaseModel):
    session_id: str
    answer: str

class ApprovePayload(BaseModel):
    query: str
    hs_code: str

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/stream")
async def stream_agent(q: str, session_id: str):
    """
    Streaming endpoint using Server-Sent Events (SSE) and Threading Queue.
    """
    q_stream = queue.Queue()
    input_q = queue.Queue()
    
    # Đăng ký session để nhận câu trả lời từ LLM (Clarification)
    active_sessions[session_id] = input_q

    def stream_callback(data):
        q_stream.put(data)
        
    def input_callback():
        # Block luồng (Thread) Agent lại, chờ người dùng gọi API /submit_answer
        return input_q.get()

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
async def submit_answer(payload: AnswerPayload):
    """
    Endpoint này 'đánh thức' Agent bằng cách nhét câu trả lời vào Input Queue
    của Session tương ứng.
    """
    if payload.session_id in active_sessions:
        active_sessions[payload.session_id].put(payload.answer)
        return {"status": "success", "message": "Answer submitted to LLM Queue."}
    return {"status": "error", "message": "Session not found or expired."}

@app.post("/approve_hs")
async def approve_hs(payload: ApprovePayload):
    """
    Endpoint lưu kết quả phê duyệt của người dùng làm Cache dữ liệu / Lịch sử / Fine-tuning.
    """
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
        
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "message": "HS Code saved to cache."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Deploy dev server at port 8000
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
