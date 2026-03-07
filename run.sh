#!/bin/bash
# Script để chạy server cho Agentic HS Code UI
# File gốc: app.py (FastAPI)

echo "=================================================="
echo "Khởi động Agentic HS Code Backend Server (FastAPI)"
echo "Truy cập giao diện UI tại: http://localhost:8000"
echo "=================================================="

# Sử dụng python3 gọi trực tiếp app.py hoặc dùng dòng lện uvicorn
python app.py
