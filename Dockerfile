FROM python:3.11-slim

WORKDIR /app

# Cài dependencies hệ thống cần thiết cho sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Chạy với uvicorn binding 0.0.0.0 trong container (nginx xử lý exposure ra ngoài)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
