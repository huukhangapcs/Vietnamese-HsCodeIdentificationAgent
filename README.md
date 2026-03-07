# 🛃 HS Code Identification Agent v2

An **agentic AI system** for automatic HS (Harmonized System) Code classification of import/export goods — with a two-path architecture (Fast Path & Slow Path), streaming interface, and a curated Vietnamese customs knowledge base.

---

## 📐 Architecture Overview

```
User Query (Vietnamese/English)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (app.py)                   │
│  SSE Streaming  │  Session Management  │  Rate Limiting + Auth   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      HSPipeline (core/pipeline.py)              │
│                                                                  │
│  Step 0: ItemAnalyzer ──► Validate + Extract Features (1 LLM)   │
│              │                                                   │
│              ├─── Invalid ──► FAST REJECT                        │
│              │                                                   │
│              ▼                                                   │
│  Step 0.5: CacheManager ──► Cache Hit? ──► Return Cached Result  │
│              │                                                   │
│              ▼                                                   │
│  Step 0.8: Keyword Search (RapidFuzz) ─────────────────────────►│
│              │                            ┌─── Gate A (no LLM)  │
│              │  Score ≥ 75/80?            │   Hardcoded rules    │
│              │                            │   Chapter exclusions │
│              ├── YES ──► Gate A ──PASS──► Gate B (QA Auditor)   │
│              │              │              1 LLM + ChromaDB      │
│              │           FAIL             │                      │
│              │              │             ├── PASS ──► Return ✅  │
│              │              ▼             └── FAIL ──► Slow Path │
│              │         Slow Path                                  │
│              └── NO ──► Slow Path                                │
│                              │                                   │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │                      SLOW PATH                            │   │
│  │                                                           │   │
│  │  Tier1Router: Section → Chapter (2 LLM + RAG ChromaDB)   │   │
│  │        │                                                  │   │
│  │        ▼                                                  │   │
│  │  HSCoderAgent: Tree traversal + Human-in-the-Loop         │   │
│  │        │         (up to 8 steps, clarification Q&A)       │   │
│  │        ▼                                                  │   │
│  │  HSGatekeeper (Linter): Hardcoded rule check              │   │
│  │        │── FAIL ──► Revision (max 2) ──► back to Router   │   │
│  │        ▼                                                  │   │
│  │  QAAuditorAgent: Red-team verification (1 LLM + ChromaDB) │   │
│  │        │── FAIL ──► Revision                              │   │
│  │        └── PASS ──► Cache + Return ✅                     │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
hscodever3/
│
├── app.py                    # FastAPI server — SSE streaming, session mgmt, endpoints
│
├── core/
│   ├── pipeline.py           # HSPipeline — orchestrates all steps
│   ├── cache_manager.py      # Redis-backed (or in-memory) LRU cache
│   ├── llm_provider.py       # LLM client factory (DeepSeek-compatible OpenAI API)
│   ├── schemas.py            # Pydantic request/response schemas
│   └── security.py           # Rate limiting, input sanitization, prompt injection defense
│
├── agents/
│   ├── analyzer.py           # ItemAnalyzer — Step 0: validate + extract features (1 LLM call)
│   ├── tier1_router.py       # Tier1Router — Section → Chapter routing (2 LLM + RAG)
│   └── coder.py              # HSCoderAgent — recursive HS tree traversal + clarification loop
│
├── linter/
│   └── gatekeeper.py         # HSGatekeeper — deterministic hardcoded rule enforcement
│
├── qa/
│   └── auditor.py            # QAAuditorAgent — red-team LLM + ChromaDB verification
│
├── tools/
│   ├── knowledge_tools.py    # Core RAG engine: ChromaDB queries, chapter rules loader, keyword search
│   ├── extract_aku.py        # Batch AKU extraction from raw HS data
│   ├── migrate_searchable_db.py  # Builds hsdata_searchable.json from hsdata.csv
│   └── optimize_db.py        # ChromaDB optimization utilities
│
├── database/
│   ├── chapter_X_rules.json  # Chapters 1–20: classification rules (inclusions, exclusions, logic)
│   ├── chapter_X_tree.json   # Chapters 1–20: full HS code tree with semantic_path
│   ├── general_rules.json    # Global HS classification rules (GRI rules)
│   ├── sections_info_aku.json # Section-level notes and AKUs (Atomic Knowledge Units)
│   ├── hsdata_searchable.json # Full searchable HS database (12MB)
│   ├── hs_cache.json         # Persistent result cache
│   ├── approved_cache.json   # User-approved results (fine-tuning signal)
│   ├── build_vector_db.py    # Script to populate ChromaDB from JSON data
│   └── chroma_db/            # ChromaDB vector store (legal notes embeddings)
│
├── index.html                # Single-page webapp frontend
├── Dockerfile / docker-compose.yml / nginx/   # Production deployment
└── requirements.txt
```

---

## 🔄 Classification Pipeline — Detailed Steps

### ⚡ Fast Path (< 5s)

| Step | Component | Description |
|------|-----------|-------------|
| 0 | `ItemAnalyzer` | Heuristic fast-fail → 1 LLM call: validate input + extract 4 features + generate search keywords |
| 0.5 | `CacheManager` | Redis/in-memory cache lookup. Cache hit → instant return |
| 0.8 | Keyword Search | RapidFuzz fuzzy search on `hsdata_searchable.json`. Score ≥ 75 (2+ results) or ≥ 80 (1 result) → Fast Path |
| Gate A | `_fast_path_gate_a` | **0 LLM**: check hardcoded linter rules + JSON chapter exclusion keywords |
| Gate B | `QAAuditorAgent` | **1 LLM + ChromaDB**: red-team audit of keyword match candidate |

### 🧠 Slow Path (10–30s)

| Step | Component | Description |
|------|-----------|-------------|
| 1 | `Tier1Router` | 2-step zero-shot routing: Top-3 Sections → RAG legal notes → final Section → Chapter |
| 2 | `HSCoderAgent` | Recursive tree traversal from target Chapter. Up to 8 steps. Human-in-the-loop clarification via SSE |
| 3 | `HSGatekeeper` | Deterministic linting. FAIL → revision loop (max 2 revisions) |
| 4 | `QAAuditorAgent` | Final red-team LLM audit + ChromaDB. PASS → cache write + return |

---

## 🗄️ Knowledge Base

The `database/` directory contains structured JSON knowledge for **Chapters 1–20** of Section I–IV (Live animals, Food & Agriculture):

### `chapter_X_rules.json`
```json
{
  "chapter_code": "16",
  "inclusions": ["..."],
  "exclusions": [
    {
      "condition": "...",
      "action": "Redirect to Chapter X",
      "keywords": ["keyword1", "keyword2"]
    }
  ],
  "classification_rules": [
    { "rule": "...", "description": "...", "priority": 1 }
  ]
}
```

### `chapter_X_tree.json`
```json
[
  {
    "level": 0,
    "hs_code": "1601",
    "description_en": "Sausages and similar products...",
    "children": [...],
    "semantic_path": "Sausages and similar products > ..."
  }
]
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- DeepSeek API key (or any OpenAI-compatible API)

### Installation

```bash
# Clone and install
pip install -r requirements.txt

# Set API key
echo "your-deepseek-api-key" > key_deepseek

# Build vector database (first time only)
cd database
python build_vector_db.py

# Run development server
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

### Docker Deployment

```bash
docker-compose up -d
```

The app runs behind **Nginx** as reverse proxy on port 80.

---

## 🌐 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI (single-page app) |
| `GET` | `/stream?q=...&session_id=...` | **SSE**: stream classification events |
| `POST` | `/submit_answer` | Human-in-the-loop: submit clarification answer |
| `POST` | `/approve_hs` | Save user-approved HS code to cache |
| `GET` | `/health` | Health check |

### SSE Event Types

```javascript
{ "type": "info",             "message": "Step log..." }
{ "type": "fast_path_result", "data": { "final_section_id": "17011200", ... } }
{ "type": "slow_path_result", "data": { "final_section_id": "17011200", ... } }
{ "type": "error",            "message": "Error details" }
```

---

## 🔒 Security Features

- **Rate limiting**: 30 req/min per IP (configurable)
- **API Key auth**: Optional via `HSCODE_API_KEY` env var
- **Input sanitization**: Prompt injection defense in `ItemAnalyzer`
- **Session TTL**: 30-minute session cleanup to prevent memory leaks
- **Atomic file writes**: Temp-file rename pattern for cache integrity
- **Input length limits**: 2000 chars for queries, 3000 for approve payloads

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HSCODE_API_KEY` | `""` (disabled) | Optional API key for auth |
| `ALLOWED_ORIGINS` | `http://localhost:8000` | CORS allowed origins (comma-separated) |
| `REDIS_URL` | `None` | Redis URL for distributed cache (optional) |

---

## 🧪 Testing

```bash
pytest tests/ -v
```

---

## 📊 Chapters Covered

| Section | Chapters | Description |
|---------|----------|-------------|
| Section I | 1–5 | Live animals; animal products |
| Section II | 6–14 | Vegetable products |
| Section III | 15 | Animal or vegetable fats and oils |
| Section IV | 16–24 | Prepared foodstuffs *(Ch. 16–20 complete)* |

> Chapters 21–97 are handled by the LLM reasoning path without local JSON rules (use ChromaDB + raw HS nomenclature).

---

## 🏗️ Adding a New Chapter

1. Add `chapter_N_raw.txt` and `chapter_N_notes.txt` to the project root
2. Run analysis and generate `database/chapter_N_rules.json` + `database/chapter_N_tree.json`
3. Re-run `database/build_vector_db.py` to index new data into ChromaDB

---

## 📄 License

Internal use — Vietnamese Customs HS Code Classification System.
