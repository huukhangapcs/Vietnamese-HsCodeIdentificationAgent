# 🛃 HS Code Identification Agent v3

An **agentic AI system** for automatic HS (Harmonized System) Code classification of import/export goods — with a two-path architecture (Fast Path & Slow Path), streaming interface, and a curated Vietnamese customs knowledge base.

---

## 📐 Architecture Overview (Pipeline V3: Hybrid Reranker)

```
User Query (Vietnamese/English)
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (app.py)                  │
│  SSE Streaming  │  Session Management  │  Rate Limiting + Auth  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      HSPipeline (core/pipeline.py)              │
│                                                                 │
│  Step 0: ItemAnalyzer ──► Validate + Extract Features (1 LLM)   │
│              │                                                  │
│              ├─── Invalid / Vague ──► FAST REJECT / CLARIFY     │
│              │                                                  │
│              ▼                                                  │
│  Step 0.5: CacheManager ──► Cache Hit? ──► Return Cached Result │
│              │                                                  │
│              ▼                                                  │
│  Step 0.8: Keyword Search (RapidFuzz) ────────────────────────► │
│              │                            ┌─── Gate A (no LLM)  │
│              │  Score ≥ 75/80?            │   Hardcoded rules   │
│              │                            │   Chapter exclusions│
│              ├── YES ──► Gate A ──PASS──► Gate B (QA Auditor)   │
│              │              │              1 LLM + ChromaDB     │
│              │           FAIL             │                     │
│              │              │             ├── PASS ──► Return ✅ │
│              │              ▼             └── FAIL ──► Phase 1  │
│              │          Phase 1                                 │
│              └── NO ──► Phase 1                                 │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │           PHASE 1: HYBRID CANDIDATE GENERATION           │   │
│  │  Merge Top 5 RapidFuzz + Top 5 ChromaDB Vector matches   │   │
│  │  Fetch specific Legal Notes for all Candidates in Pool   │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │           PHASE 2: LLM JUDGE "ONE-SHOT" ELIMINATION      │   │
│  │  1 LLM evaluates all candidates & Eliminates by Rule     │   │
│  │        │── PASS ──► Gatekeeper & QA Auditor ──► Return ✅ │   │
│  │        └── FAIL (All candidates rejected) ──► Phase 3    │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐   │
│  │           PHASE 3: THE SLOW PATH FALLBACK (AGENTIC)      │   │
│  │  Tier1Router: Section → Chapter (2 LLM + RAG ChromaDB)   │   │
│  │  HSCoderAgent: Recursive HS tree traversal + human Q&A   │   │
│  │  HSGatekeeper & QAAuditorAgent: Final Verification       │   │
│  └──────────────────────────────────────────────────────────┘   │
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
│   ├── analyzer.py           # ItemAnalyzer — Step 0: validate + extract features
│   ├── judge.py              # JudgeAgent — Phase 2: One-shot LLM elimination over Candidate Pool
│   ├── tier1_router.py       # Tier1Router — Phase 3 Fallback Section → Chapter routing
│   └── coder.py              # HSCoderAgent — Phase 3 Fallback recursive tree traversal
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
│   ├── chapter_X_rules.json  # Ch.1–40: classification rules (inclusions, exclusions, logic)
│   ├── chapter_X_tree.json   # Ch.1–27, Ch.36: full HS code tree with semantic_path
│   ├── chapter_28_subN_tree.json  # Ch.28: 6 sub-chapter trees (28_sub1 to 28_sub6)
│   ├── general_rules.json    # Global HS classification rules (GRI rules)
│   ├── sections_info_aku.json # Section-level notes and AKUs (Atomic Knowledge Units)
│   ├── hsdata_searchable.json # Full searchable HS database (12MB)
│   ├── hs_cache.json         # Persistent result cache
│   ├── approved_cache.json   # User-approved results (fine-tuning signal)
│   ├── build_vector_db.py    # Script to populate ChromaDB from JSON data
│   └── chroma_db/            # ChromaDB vector store (~47 MB, 9,300+ embeddings)
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
| 0 | `ItemAnalyzer` | Heuristic fast-fail → 1 LLM call: validate input, check vagueness, extract features + generate search keywords |
| 0.5 | `CacheManager` | Redis/in-memory cache lookup. Cache hit → instant return |
| 0.8 | Keyword Search | RapidFuzz fuzzy search on `hsdata_searchable.json`. Score ≥ 75/80 → Fast Path |
| Gate A | `_fast_path_gate_a` | **0 LLM**: check hardcoded linter rules + JSON chapter exclusion keywords |
| Gate B | `QAAuditorAgent` | **1 LLM + ChromaDB**: red-team audit of keyword match candidate |

### 🕵️‍♂️ V3 Hybrid Reranker Path (5–8s)

| Step | Component | Description |
|------|-----------|-------------|
| Phase 1 | Candidate Gen | **0 LLM**: Merge Top 5 Keyword search results + Top 5 ChromaDB Vector matches into a candidate pool. Notes caching applied. |
| Phase 2 | `JudgeAgent` | **1 LLM**: Receives pool + fetched legal notes. "One-off" evaluation to eliminate bad matches by rules and select the single BEST HS code. **(Token Compressed via Chapter Grouping)** |
| Validation | `HSGatekeeper` / `QAAuditorAgent` | Linter + Red-team audit of Judge's decision. PASS → Return ✅ |

### 🧠 Slow Path Fallback (10–30s)

| Step | Component | Description |
|------|-----------|-------------|
| Phase 3 | `Tier1Router` | **Bypassed automatically** if Candidate Pool exists. Otherwise, routes Section → Chapter. |
| | `HSCoderAgent` | Active Recursive tree traversal. Explores node by node. Starts from Phase 1 chapters directly. Human-in-the-loop clarification via SSE. |
| | `HSGatekeeper` / `QAAuditorAgent` | Final LLM audit + ChromaDB validation. FAIL → revision loop |

### 🛠️ Phase 4 & 4.1: Optimization and Deep Bug Fixes
- **Token Compression:** Candidate grouping before LLM evaluation saves 60% prompt tokens.
- **Python 3.14 / Pydantic V1 Patch:** Custom monkey patch to restore ChromaDB functionality and prevent silent Vector DB failures.
- **Auditor Hallucination Fix:** Included Node Description strings alongside 8-digit codes in prompts to enforce deterministic rule-checking.
- **Coder Agent Anti-Loop:** Strict instructions to prevent `DeepSeek Reasoner` from dead-looping on empty Vector DB queries.

---

## 🗄️ Knowledge Base — Database Status

### 📊 Coverage Summary (as of 2026-03-08)

| Asset | Count | Details |
|-------|-------|---------|
| **Rules JSON** | **97 / 97 chapters** | All chapters complete |
| **Tree JSON** | **31 mono + 7 sub-trees** | Ch. 1–27, Ch. 36, Ch. 42, Ch. 43; Ch. 28 (6 sub-trees) |
| **ChromaDB size** | **~72 MB** | 3,473 node embeddings + 2,668 rule chunk embeddings |
| **Total inclusions** | **1,209** | Heading-level scope definitions (structured JSON format: `{"heading": "XX.XX", "description": "..."}`) |
| **Total exclusions** | **584** | All with keyword triggers for Gate A filter |
| **Total classification rules** | **595** | Avg **6.1 rules/chapter**, indexed into ChromaDB |
| **Avg rule detail** | **~560 chars/rule** | Rebuilt Ch.1–11 avg 539–620 chars/rule |
| **Vectorized Metadata** | **100% Coverage** | All `scope_note`, `chapter_title`, Section rules, and Section definitions are indexed |

### 🗂️ Rules Coverage by Section

| Section | Chapters | Description | Rules JSON | Tree JSON |
|---------|----------|-------------|:----------:|:---------:|
| **Section I** | 1–5 | Live animals; animal products | ✅ Complete | ✅ Complete |
| **Section II** | 6–14 | Vegetable products | ✅ Complete | ✅ Complete |
| **Section III** | 15 | Animal or vegetable fats and oils | ✅ Complete | ✅ Complete |
| **Section IV** | 16–24 | Prepared foodstuffs | ✅ Complete | ✅ Complete |
| **Section V** | 25–27 | Mineral products | ✅ Complete | ✅ Complete |
| **Section VI** | 28–38 | Chemical products | ✅ Complete | ⚠️ Ch.28 only (sub-trees) |
| **Section VII** | 39–40 | Plastics & Rubber | ✅ Complete | ❌ Pending |
| **Section VIII** | 41–43 | Hides, leather, furs | ✅ Complete | ✅ Complete |
| **Section IX** | 44–46 | Wood, cork, straw | ✅ Complete | ❌ Pending |
| **Section X** | 47–49 | Pulp, paper, books | ✅ Complete | ❌ Pending |
| **Section XI** | 50–63 | Textiles | ✅ Complete | ❌ Pending |
| **Section XII** | 64–67 | Footwear, headgear | ✅ Complete | ❌ Pending |
| **Section XIII** | 68–70 | Stone, ceramic, glass | ✅ Complete | ❌ Pending |
| **Section XIV** | 71 | Precious metals, jewellery | ✅ Complete | ❌ Pending |
| **Section XV** | 72–83 | Base metals | ✅ Complete | ❌ Pending |
| **Section XVI** | 84–85 | Machinery & Electronics | ✅ Complete | ❌ Pending |
| **Section XVII** | 86–89 | Transport | ✅ Complete | ❌ Pending |
| **Section XVIII** | 90–92 | Instruments, clocks | ✅ Complete | ❌ Pending |
| **Section XIX** | 93 | Arms & ammunition | ✅ Complete | ❌ Pending |
| **Section XX** | 94–96 | Miscellaneous manufactured | ✅ Complete | ❌ Pending |
| **Section XXI** | 97 | Works of art | ✅ Complete | ❌ Pending |

> **Note:** Chapters without Tree JSON are handled by the LLM reasoning path (Slow Path) using ChromaDB embeddings + `hsdata.csv`.

### `chapter_X_rules.json` Schema
```json
{
  "chapter_code": "04",
  "chapter_title": "Dairy produce; birds' eggs; natural honey...",
  "scope_note": "Note 1: ... Note 2: yoghurt conditions ... (Official HS Notes)",
  "inclusions": [
    {
      "heading": "04.01",
      "description": "Milk and cream, not concentrated..."
    }
  ],
  "exclusions": [
    {
      "condition": "Products from whey with lactose ≥ 95%...",
      "action": "Redirect to heading 17.02",
      "keywords": ["pure lactose 95%", "17.02"]
    }
  ],
  "classification_rules": [
    {
      "rule": "Note 3 — Butter fat% thresholds",
      "description": "Butter = milkfat 80–95%, water ≤16%...",
      "priority": 1
    }
  ]
}
```

**ChromaDB vector types** (indexed in `hs_rules` collection):

| `type` metadata | Count | Searchable via |
|-----------------|-------|---------------|
| `exclusion` | ~584 | `query_legal_notes()` → `EXCLUSION: If ... -> ...` |
| `inclusion` | ~1,209 | `query_legal_notes()` → `INCLUSION: ...` |
| `classification_rule` | ~595 | `query_legal_notes()` → `RULE (priority N): ...` |

### `chapter_X_tree.json` Schema
```json
[
  {
    "level": 0,
    "hs_code": "3901",
    "description_en": "Polymers of ethylene in primary forms",
    "children": [...],
    "semantic_path": "Plastics > Polymers of ethylene > ..."
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

## 🏗️ Adding a New Chapter

1. Add `chapter_N_raw.txt` and `chapter_N_notes.txt` to the project root
2. Run analysis and generate `database/chapter_N_rules.json` + `database/chapter_N_tree.json`
3. Re-run `database/build_vector_db.py` to index new data into ChromaDB

---

## 📄 License

Internal use — Vietnamese Customs HS Code Classification System.
