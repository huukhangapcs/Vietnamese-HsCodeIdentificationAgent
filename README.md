# 🤖 HS Code Identification Agent

> Hệ thống phân loại mã HS Code tự động dựa trên **Multi-Agent Agentic Pipeline** kết hợp LLM DeepSeek + Vector Database.

---

## 📋 Mục lục
- [Tổng quan](#-tổng-quan)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Cài đặt](#-cài-đặt)
- [Cấu hình](#-cấu-hình)
- [Chạy ứng dụng](#-chạy-ứng-dụng)
- [Cấu trúc thư mục](#-cấu-trúc-thư-mục)
- [API Reference](#-api-reference)
- [Bảo mật](#-bảo-mật)

---

## 🎯 Tổng quan

Hệ thống tự động phân loại hàng hoá xuất nhập khẩu theo **Biểu thuế HS (Harmonized System)** đến 8 chữ số, dựa trên mô tả bằng ngôn ngữ tự nhiên (tiếng Việt hoặc tiếng Anh).

**Điểm nổi bật:**
- 🧠 **Multi-Agent**: 5 agent chuyên biệt phối hợp theo pipeline
- ⚡ **Fast Path**: Cache hit trả kết quả gần như tức thì (~0s)
- 🔍 **Semantic Search**: ChromaDB vector search để tìm mã HS liên quan
- 👤 **Human-in-the-Loop**: Agent tự động hỏi người dùng khi cần thêm thông tin
- ✅ **QA Auditor**: Red-team agent kiểm tra kết quả trước khi trả về
- 🔐 **Security hardened**: Rate limiting, XSS protection, prompt injection defense

---

## 🏗️ Kiến trúc hệ thống

```
                        User Query (Mô tả hàng hoá)
                                    │
                    ┌───────────────▼──────────────────┐
                    │  [Step 0] ItemAnalyzer           │
                    │  • Validate input (heuristic+LLM)│
                    │  • Extract: name, material,       │
                    │    function, state/condition      │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
                    │  [Cache] CacheManager            │
                    │  • Exact-match lookup            │
                    │  • HIT → Fast Path (~0s)         │
                    │  • MISS → tiếp tục pipeline      │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
                    │  [Step 1] Tier1Router            │
                    │  Pass 1: Top-3 Section candidates│
                    │  Pass 2: Check Legal Notes →     │
                    │          chốt Section + Chapter  │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
                    │  [Step 2] HSCoderAgent (ReAct)   │
                    │  Max 15 steps, 6 tools:          │
                    │  • navigate_node                 │
                    │  • search_hs_nodes (vector)      │
                    │  • query_legal_notes             │
                    │  • get_chapter_rules             │
                    │  • get_general_rules (GIR)       │
                    │  • ask_user_clarification ─────► Human-in-the-Loop
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
                    │  [Step 3] HSGatekeeper (Linter)  │
                    │  • Hardcoded rules (wood→ch44)   │
                    │  • Neuro-symbolic exclusion check│
                    └───────────────┬──────────────────┘
                                    │ PASS
                    ┌───────────────▼──────────────────┐
                    │  [Step 4] QAAuditorAgent         │
                    │  • Red-team: check legal notes   │
                    │  • FAIL → Revision loop (max 2x) │
                    └───────────────┬──────────────────┘
                                    │ PASS
                    ┌───────────────▼──────────────────┐
                    │  Final HS Code (8 chữ số) ✅     │
                    │  + Write-back to Cache           │
                    └──────────────────────────────────┘
```

### Stack công nghệ
| Layer | Công nghệ |
|-------|-----------|
| **LLM** | DeepSeek Chat (via OpenAI-compatible API) |
| **Vector DB** | ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2` |
| **Backend** | FastAPI + SSE (Server-Sent Events) |
| **Frontend** | Vanilla HTML/CSS/JS, dark mode, glassmorphism |
| **Database** | JSON files (HS tree, rules, cache) |

---

## ⚙️ Cài đặt

### Yêu cầu
- Python 3.10+
- pip

### Cài dependencies

```bash
# Tạo virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Cài packages
pip install fastapi uvicorn openai chromadb sentence-transformers pydantic
```

### Build Vector Database (lần đầu tiên)

```bash
python database/build_vector_db.py
```

---

## 🔧 Cấu hình

### API Key DeepSeek (bắt buộc)

**Cách an toàn — dùng environment variable:**

```bash
# Thêm vào ~/.zshrc hoặc ~/.bashrc
export DEEPSEEK_API_KEY="sk-your-key-here"
source ~/.zshrc
```

> ⚠️ **KHÔNG** lưu key trực tiếp vào file và commit lên git.

### API Key bảo vệ endpoint (tuỳ chọn, cho production)

```bash
export HSCODE_API_KEY="your-secret-api-key"
# Frontend sẽ cần gửi header: X-API-Key: your-secret-api-key
```

---

## 🚀 Chạy ứng dụng

```bash
# Development (local only)
python app.py
# Hoặc
bash run.sh

# Truy cập tại: http://localhost:8000
```

---

## 📁 Cấu trúc thư mục

```
hscodever3/
├── app.py                   # FastAPI server, SSE streaming, auth, rate limiting
├── run.sh                   # Script khởi động nhanh
├── index.html               # Frontend (SPA, dark mode, real-time terminal)
│
├── core/
│   ├── pipeline.py          # Orchestrator chính (5-step pipeline)
│   ├── llm_provider.py      # LLM client factory (env var → file fallback)
│   ├── cache_manager.py     # JSON-based cache với atomic write
│   ├── schemas.py           # Pydantic schemas & tool definitions
│   └── security.py          # Rate limiter, prompt injection sanitizer
│
├── agents/
│   ├── analyzer.py          # Step 0: validate + extract features
│   ├── tier1_router.py      # Step 1: zero-shot Section/Chapter routing
│   └── coder.py             # Step 2: ReAct loop (max 15 steps)
│
├── linter/
│   └── gatekeeper.py        # Step 3: hardcoded rules + LLM exclusion check
│
├── qa/
│   └── auditor.py           # Step 4: red-team QA agent
│
├── tools/
│   ├── knowledge_tools.py   # ChromaDB search + JSON tree navigation
│   ├── extract_aku.py       # Tool build knowledge base
│   └── optimize_db.py       # Tool tối ưu vector DB
│
├── database/
│   ├── chapter_*_tree.json  # HS nomenclature tree (chương 1-9)
│   ├── chapter_*_rules.json # Legal notes & exclusion rules
│   ├── general_rules.json   # 6 General Interpretative Rules (GIR)
│   ├── sections_info_aku.json # 21 Sections metadata
│   ├── hs_cache.json        # Cache LLM results (fast path)
│   └── approved_cache.json  # Human-approved results history
│
├── tests/                   # Integration test scripts
├── 6quytac/                 # 6 General Interpretive Rules reference docs
└── .gitignore               # Bảo vệ secrets, venv, node_modules, cache
```

---

## 📡 API Reference

### `GET /stream`
Phân loại hàng hoá (SSE streaming real-time).

| Param | Type | Mô tả |
|-------|------|--------|
| `q` | string | Mô tả hàng hoá (max 2000 ký tự) |
| `session_id` | UUID | Session ID do frontend tạo |

**SSE Event types:** `info`, `action`, `observation`, `clarification_request`, `fast_path_result`, `slow_path_result`, `error`

---

### `POST /submit_answer`
Gửi câu trả lời khi agent cần clarification (Human-in-the-Loop).

```json
{ "session_id": "uuid", "answer": "Câu trả lời của user" }
```

---

### `POST /approve_hs`
Lưu kết quả phê duyệt vào approved cache.

```json
{ "query": "Mô tả hàng hoá", "hs_code": "01012100" }
```

---

## 🔐 Bảo mật

| Lớp | Biện pháp |
|-----|-----------|
| **API Key** | Lưu qua env var `DEEPSEEK_API_KEY`, KHÔNG commit file key |
| **Authentication** | Optional `HSCODE_API_KEY` via `X-API-Key` header |
| **Rate Limiting** | 15 request/phút per IP (in-memory, thread-safe) |
| **XSS** | Frontend dùng `textContent` + `safeRenderText()`, không `innerHTML` trực tiếp |
| **Prompt Injection** | `sanitize_input()` detect 14 injection patterns |
| **Input Validation** | Query max 2000 ký tự, UUID session_id, hs_code format check |
| **Atomic Writes** | `hs_cache.json` và `approved_cache.json` dùng tmp+rename pattern |

---

## 📊 Coverage hiện tại

| Phạm vi | Trạng thái |
|---------|-----------|
| Chương 1–9 (JSON tree + rules) | ✅ Đầy đủ |
| ChromaDB vector index | ⚠️ Một phần chương |
| Chương 10–97 | 🔴 `UNSUPPORTED_CHAPTER` |

> Để mở rộng: thêm file `chapter_N_tree.json` và `chapter_N_rules.json` vào `database/`, rồi chạy lại `build_vector_db.py`.
