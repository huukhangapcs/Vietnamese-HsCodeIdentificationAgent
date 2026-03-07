import json
import os
import csv
import re
import threading
# NOTE: chromadb and sentence_transformers are lazy-imported inside
# _get_vector_collections() to avoid Python 3.14 / pydantic-v1 incompatibility.
# All functions that do NOT use vector search work without chromadb installed.

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HSDATA_PATH = os.path.join(BASE_DIR, "hsdata.csv")
SECTIONS_INFO_PATH = os.path.join(BASE_DIR, "database", "sections_info_aku.json")
# Cache to avoid reloading (sửa thành dictionary để cache đa chương)
_trees_cache = {}
_rules_cache = {}
_sections_info_cache = None
_general_rules_cache = None
_titles_cache = {}  # BUG-3 FIX: cache chapter titles to avoid repeated file reads
_fast_search_cache = None
_cache_lock = threading.Lock()  # [FIX-6] Thread-safe cold-start cache loading

CHROMA_DB_PATH = os.path.join(BASE_DIR, "database", "chroma_db")

_chroma_client = None
_embed_fn = None
_collection_nodes = None
_collection_rules = None

def _get_vector_collections():
    """Lazy-initialise ChromaDB + embedding model on first use."""
    global _chroma_client, _embed_fn, _collection_nodes, _collection_rules
    if _chroma_client is None:
        # Lazy imports — kept here so the module loads fine on Python 3.14
        # even when chromadb/pydantic-v1 is broken in that environment.
        import chromadb as _chromadb
        from chromadb.utils import embedding_functions as _emb_fns
        from sentence_transformers import SentenceTransformer as _ST

        class _CustomEmbeddingFunction(_emb_fns.EmbeddingFunction):
            def __init__(self, model_name="paraphrase-multilingual-MiniLM-L12-v2"):
                self.model = _ST(model_name)
            def __call__(self, input):
                return self.model.encode(input).tolist()

        _embed_fn = _CustomEmbeddingFunction()
        _chroma_client = _chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collection_nodes = _chroma_client.get_collection(name="hs_nodes", embedding_function=_embed_fn)
        _collection_rules = _chroma_client.get_collection(name="hs_rules", embedding_function=_embed_fn)
    return _collection_nodes, _collection_rules


def _load_fast_search_cache():
    """Load hsdata_searchable.json vào RAM. Thread-safe: dùng lock để tránh double-load khi cold start."""
    global _fast_search_cache
    if _fast_search_cache is not None:  # Fast path: đã load rồi thì skip
        return
    with _cache_lock:  # [FIX-6] Chỉ 1 thread load, các thread khác đợi
        if _fast_search_cache is not None:  # Double-check sau khi acquire lock
            return
        try:
            db_path = os.path.join(BASE_DIR, "database", "hsdata_searchable.json")
            with open(db_path, "r", encoding="utf-8") as f:
                _fast_search_cache = json.load(f)
            print(f"[cache] Loaded {len(_fast_search_cache):,} records from hsdata_searchable.json")
        except Exception as e:
            print(f"Error loading hsdata_searchable.json: {e}")
            _fast_search_cache = []  # Ensure it's an empty list on error

def fast_keyword_search(keywords: list[str], top_k=3, leaf_only: bool = True, chapter_id: str = None):
    """
    Tìm kiếm nhanh bằng lexical/fuzzy match (rapidfuzz).
    Dành riêng cho cụm từ khóa tiếng Anh trích xuất từ LLM (Phase 2),
    cọ xát thẳng vào `search_text_en` (chứa breadcrumbs) để đạt precision cao.

    Args:
        keywords:   Danh sách từ khóa tiếng Anh (từ Analyzer).
        top_k:      Số kết quả tối đa.
        leaf_only:  True (mặc định) → chỉ trả 8-digit HS codes, bỏ heading/subheading trung gian.
        chapter_id: VD "01" → chỉ scan ~150 records trong chapter đó thay vì toàn bộ 15k.
    """
    _load_fast_search_cache()
    if not _fast_search_cache or not keywords:
        return []

    from rapidfuzz import fuzz

    # [FIX] Stop words: bao gồm cả HS-specific noise words thường xuất hiện
    # trong mọi description nhưng không có giá trị phân biệt
    stopwords = {
        # Basic English
        "of", "and", "or", "for", "the", "in", "with", "without", "a", "an",
        "to", "from", "by", "at", "on", "its", "their", "as", "into",
        # HS-specific noise: xuất hiện ở hầu hết mọi node, không giúp phân biệt
        "other", "type", "kind", "sorts", "product", "products",
        "goods", "article", "articles", "item", "items", "not",
        "including", "excluded", "thereof", "hereof"
    }

    clean_keywords = []
    for q in keywords:
        # [FIX] Strip punctuation khỏi mỗi word trước khi lọc stop words
        # VD: "frozen," → "frozen", "pork." → "pork"
        q_words = [
            w.strip(".,;:!?()[]")
            for w in str(q).lower().split()
        ]
        # Lọc stop words và từ quá ngắn (1 ký tự) sau khi strip
        q_words = [w for w in q_words if w and w not in stopwords and len(w) > 1]
        if q_words:
            clean_keywords.append(" ".join(q_words))

    if not clean_keywords:
        return []

    # Normalize chapter_id nếu được truyền vào (VD: "1" -> "01")
    target_chapter = str(chapter_id).zfill(2) if chapter_id else None

    results = []
    for item in _fast_search_cache:
        # [IMPROVEMENT 1] Leaf-only filter: bỏ qua intermediate heading/subheading nodes
        # is_leaf=True nghĩa là hs_code có đúng 8 chữ số — là mã có thể submit được
        if leaf_only and not item.get("is_leaf", True):
            continue

        # [IMPROVEMENT 2] Chapter filter: skip records không thuộc chapter mong muốn
        # Giảm scan từ ~15k xuống còn ~120-200 records → tăng tốc đáng kể
        if target_chapter and item.get("chapter_id") != target_chapter:
            continue

        # [FIX-1] Strip | và : separators khỏi breadcrumb text trước khi tokenize
        # VD: "Live horses | Horses:" → "Live horses  Horses " → words không chứa "|" hay "horses:"
        text_en_clean = re.sub(r"[|:]", " ", str(item.get("search_text_en", "")).lower())
        text_en = text_en_clean  # dùng clean text cho cả scoring
        text_en_words = set(text_en_clean.split())

        max_score_for_item = 0

        for clean_query in clean_keywords:
            q_words_set = set(clean_query.split())

            # Tiền lọc: nếu không có từ nào chung, thử tiếp với aliases
            if not (q_words_set & text_en_words):
                aliases = item.get("aliases", [])
                alias_words = set(w for a in aliases for w in a.lower().split())
                if not (q_words_set & alias_words):
                    continue

            score_en_set = fuzz.token_set_ratio(clean_query, text_en)
            score_en_partial = fuzz.partial_ratio(clean_query, text_en)

            # Kết hợp tỉ lệ: partial match mạnh hơn để chuỗi dài không bị phạt nặng
            base_score = max(score_en_set, score_en_partial) * 0.85 + fuzz.token_sort_ratio(clean_query, text_en) * 0.15

            # Bonus khi EXACT MATCH trong search_text hoặc description
            if clean_query in text_en:
                base_score += 15
            desc_en_original = str(item.get("description_en", "")).lower()
            if clean_query in desc_en_original:
                base_score += 10

            # [IMPROVEMENT 3] Alias scoring: khớp qua tên đồng nghĩa, weight = 0.9x
            for alias in item.get("aliases", []):
                alias_lower = alias.lower()
                alias_score = fuzz.token_set_ratio(clean_query, alias_lower) * 0.9
                if clean_query in alias_lower:
                    alias_score += 10
                if alias_score > base_score:
                    base_score = alias_score

            if base_score > max_score_for_item:
                max_score_for_item = base_score

        if max_score_for_item > 0:
            results.append({
                "hs_code": item["hs_code"],
                "description_en": item["description_en"],
                "description_vn": item["description_vn"],
                "score": min(100, max_score_for_item)  # Giới hạn max là 100
            })

    # Sắp xếp theo score giảm dần
    results = sorted(results, key=lambda x: x["score"], reverse=True)

    # Loại bỏ các kết quả rác (score < 50)
    filtered = [r for r in results[:top_k] if r["score"] >= 50]
    return filtered



SECTION_TO_CHAPTERS = {
    "SECTION_I": ["01", "02", "03", "04", "05"],
    "SECTION_II": ["06", "07", "08", "09", "10", "11", "12", "13", "14"],
    "SECTION_III": ["15"],
    "SECTION_IV": ["16", "17", "18", "19", "20", "21", "22", "23", "24"],
    "SECTION_V": ["25", "26", "27"],
    "SECTION_VI": ["28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38"],
    "SECTION_VII": ["39", "40"],
    "SECTION_VIII": ["41", "42", "43"],
    "SECTION_IX": ["44", "45", "46"],
    "SECTION_X": ["47", "48", "49"],
    "SECTION_XI": [str(i).zfill(2) for i in range(50, 64)],
    "SECTION_XII": ["64", "65", "66", "67"],
    "SECTION_XIII": ["68", "69", "70"],
    "SECTION_XIV": ["71"],
    "SECTION_XV": [str(i).zfill(2) for i in range(72, 84)],
    "SECTION_XVI": ["84", "85"],
    "SECTION_XVII": ["86", "87", "88", "89"],
    "SECTION_XVIII": ["90", "91", "92"],
    "SECTION_XIX": ["93"],
    "SECTION_XX": ["94", "95", "96"],
    "SECTION_XXI": ["97"]
}

def _make_pseudo_nodes_unique(nodes, parent_id=""):
    for node in nodes:
        if node["hs_code"].startswith("PSEUDO_NODE"):
            node["hs_code"] = f"{parent_id}_{node['hs_code']}" if parent_id else node["hs_code"]
        
        if "children" in node and node["children"]:
            _make_pseudo_nodes_unique(node["children"], node["hs_code"])

def get_chapter_tree(chapter_id: str):
    global _trees_cache

    # Chuẩn hóa chapter_id thành 2 chữ số (VD: '1' -> '01')
    ch_id_str = str(chapter_id).zfill(2)

    if ch_id_str in _trees_cache:
        return _trees_cache[ch_id_str]

    # Thử đọc file monolithic trước (chapter_XX_tree.json)
    mono_path = os.path.join(BASE_DIR, "database", f"chapter_{int(ch_id_str)}_tree.json")
    if os.path.exists(mono_path):
        try:
            with open(mono_path, 'r', encoding='utf-8') as f:
                tree_data = json.load(f)
            _make_pseudo_nodes_unique(tree_data)
            _trees_cache[ch_id_str] = tree_data
            return tree_data
        except Exception:
            return []

    # Fallback: merge sub-tree files (VD: chapter_28_sub1_tree.json … chapter_28_sub6_tree.json)
    merged = []
    sub_idx = 1
    while True:
        sub_path = os.path.join(BASE_DIR, "database", f"chapter_{int(ch_id_str)}_sub{sub_idx}_tree.json")
        if not os.path.exists(sub_path):
            break
        try:
            with open(sub_path, 'r', encoding='utf-8') as f:
                sub_data = json.load(f)
            merged.extend(sub_data)
        except Exception:
            pass
        sub_idx += 1

    if merged:
        _make_pseudo_nodes_unique(merged)
        _trees_cache[ch_id_str] = merged
        return merged

    return []

def get_chapter_rules_raw(chapter_id: str):
    global _rules_cache
    
    ch_id_str = str(chapter_id).zfill(2)
    
    if ch_id_str not in _rules_cache:
        try:
            path = os.path.join(BASE_DIR, "database", f"chapter_{int(ch_id_str)}_rules.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    _rules_cache[ch_id_str] = json.load(f)
            else:
                 _rules_cache[ch_id_str] = {} # Không có rule nào thì rỗng
        except Exception as e:
            return {}
    return _rules_cache[ch_id_str]

def get_general_rules(rule_ids: list = None) -> dict:
    """
    Retrieves the General Interpretative Rules (GIR) from the database.
    If rule_ids is provided (e.g. ['GIR_2a', 'GIR_3']), it only returns those specific rules.
    If the array is empty, it returns an explicit error to prevent dumping all rules into context!
    """
    global _general_rules_cache
    if not _general_rules_cache:
        rules_path = os.path.join(BASE_DIR, "database", "general_rules.json")
        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                _general_rules_cache = json.load(f)
        except Exception as e:
            return {"error": f"Failed to load general rules: {e}"}
            
    if not rule_ids:
        # PROTECT CONTEXT WINDOW: NEVER DUMP ALL RULES
        return {"error": "SYSTEM BLOCK: You MUST specify explicitly which rule_ids you want to retrieve. Fetching all General Rules at once is forbidden due to context limits. Example parameter: {'rule_ids': ['GIR_2a', 'GIR_3a']}"}
        
    return {k: v for k, v in _general_rules_cache.items() if k in rule_ids}

def get_section_notes(section_id: str) -> dict:
    """
    Retrieves structured Section Notes.
    """
    global _sections_info_cache
    if not _sections_info_cache:
        try:
            with open(SECTIONS_INFO_PATH, 'r', encoding='utf-8') as f:
                _sections_info_cache = json.load(f)
        except Exception as e:
            return {"error": str(e)}
            
    section_data = _sections_info_cache.get(section_id, None)
    
    if not section_data:
        return {"error": f"Section {section_id} not found"}
        
    # Extract structural components
    structured_notes = section_data.get("structured_notes", {})

    return {
        "title": section_data.get("short_title_en", section_data.get("title_en", section_data.get("title_vi", ""))),
        "structured_notes": structured_notes
    }

def _find_node_and_children(nodes, target_id):
    """
    Recursively find a node by hs_code and return its immediate children.
    """
    for node in nodes:
        if node.get("hs_code") == target_id:
            return node
            
        children = node.get("children", [])
        if children:
            res = _find_node_and_children(children, target_id)
            if res:
                return res
    return None

def navigate_node(node_id: str) -> dict:
    """
    Given a node_id (e.g., '01', '0101', 'PSEUDO_NODE_1_0'), returns the node info
    and its immediate children for the agent to choose from.
    If node_id is '01' (Chapter 1), returns the top-level headings.
    """
    def _trim_desc(desc: str, max_len: int = 250) -> str:
        """Helper to trim long descriptions to save tokens."""
        if not desc: return ""
        if len(desc) <= max_len: return desc
        return desc[:max_len] + "...(cut)"
        
    # Xác định Chapter từ node_id
    if len(node_id) < 2: return {"error": "Invalid node_id"}
    chapter_id = node_id[:2]
    
    tree = get_chapter_tree(chapter_id)
    if not tree:
        return {"error": f"Dữ liệu của Chương {chapter_id} chưa được hỗ trợ trong hệ thống MVP hiện tại."}
    
    if len(node_id) == 2:
        # Mục gốc của một chương (VD: '01', '02')
        chapter_title = "Động vật sống" if node_id == "01" else "Thịt và phụ phẩm dạng thịt ăn được" if node_id == "02" else "Cá và động vật giáp xác, thân mềm, thủy sinh không xương sống" if node_id == "03" else f"Chương {node_id}"
        return {
            "current_node": node_id,
            "description": f"Chương {int(node_id)}: {chapter_title}",
            "is_leaf": False,
            "children": [{"hs_code": n["hs_code"], "description": _trim_desc(n.get("description_en", n.get("description_vi", "")))} for n in tree]
        }
        
    found_node = _find_node_and_children(tree, node_id)
    if found_node:
        children = found_node.get("children", [])
        return {
            "current_node": node_id,
            "description": _trim_desc(found_node.get("semantic_path", found_node.get("description_en", found_node.get("description_vi", "")))),
            "is_leaf": len(children) == 0,
            "children": [{"hs_code": c["hs_code"], "description": _trim_desc(c.get("semantic_path", c.get("description_en", c.get("description_vi", ""))))} for c in children]
        }
    
    return {"error": f"Không tìm thấy node {node_id} trong danh sách của Chương {chapter_id}."}
def get_section_for_chapter(chapter_id: str) -> str:
    """Helper to map a 2-digit chapter ID to its roman numeral Section ID."""
    try:
        ch = int(chapter_id)
        if 1 <= ch <= 5: return "SECTION_I"
        elif 6 <= ch <= 14: return "SECTION_II"
        elif ch == 15: return "SECTION_III"
        elif 16 <= ch <= 24: return "SECTION_IV"
        elif 25 <= ch <= 27: return "SECTION_V"
        elif 28 <= ch <= 38: return "SECTION_VI"
        elif 39 <= ch <= 40: return "SECTION_VII"
        elif 41 <= ch <= 43: return "SECTION_VIII"
        elif 44 <= ch <= 46: return "SECTION_IX"
        elif 47 <= ch <= 49: return "SECTION_X"
        elif 50 <= ch <= 63: return "SECTION_XI"
        elif 64 <= ch <= 67: return "SECTION_XII"
        elif 68 <= ch <= 70: return "SECTION_XIII"
        elif ch == 71: return "SECTION_XIV"
        elif 72 <= ch <= 83: return "SECTION_XV"
        elif 84 <= ch <= 85: return "SECTION_XVI"
        elif 86 <= ch <= 89: return "SECTION_XVII"
        elif 90 <= ch <= 92: return "SECTION_XVIII"
        elif ch == 93: return "SECTION_XIX"
        elif 94 <= ch <= 96: return "SECTION_XX"
        elif ch == 97: return "SECTION_XXI"
    except ValueError:
        pass
    return "UNKNOWN_SECTION"

def get_chapter_rules(chapter_id: str, item_description: str = "") -> dict:
    """
    Returns the parsed JSON rules (inclusions, exclusions) for a chapter, 
    ALONG WITH the RAG filtered Section Notes to ensure full legal compliance.
    """
    # Extract just the first 2 characters in case agent passes '0106' instead of '01'
    base_chapter = str(chapter_id)[:2]
    
    section_id = get_section_for_chapter(base_chapter)
    # Cung cấp item_description cho section notes để lọc bớt context rác
    section_notes = get_section_notes(section_id)
    
    rules = get_chapter_rules_raw(base_chapter)
    
    if not rules:
        return {
            "chapter_rules": {},
            "section_notes": section_notes,
            "warning": f"Quy tắc (Rules) cho Chương {base_chapter} chưa có sẵn."
        }
    
    # RAG Rule Filtering
    if item_description and "exclusions" in rules:
        filtered_exclusions = []
        item_desc_lower = item_description.lower()
        
        for rule in rules["exclusions"]:
            # Nếu có sẵn keywords từ LLM thì duyệt qua keywords
            # Nếu không thì vẫn fallback về split thủ công như cũ
            if "keywords" in rule and isinstance(rule["keywords"], list):
                keywords = [k.lower() for k in rule["keywords"]]
            else:
                condition = rule.get("condition", "").lower()
                keywords = [word for word in condition.replace(",", "").split() if len(word) > 3]
                
            if any(kw in item_desc_lower for kw in keywords):
                filtered_exclusions.append(rule)
        
        # Only overwrite if we found specific matches, otherwise return all to be safe
        if filtered_exclusions:
            # Create a copy so we don't mutate the cached dictionary
            filtered_rules = rules.copy()
            filtered_rules["exclusions"] = filtered_exclusions
            return {"chapter_rules": filtered_rules, "section_notes": section_notes}
            
    return {"chapter_rules": rules, "section_notes": section_notes}

def get_all_sections() -> list:
    """Returns a list of all sections with their ID and title."""
    global _sections_info_cache
    if not _sections_info_cache:
        try:
            with open(SECTIONS_INFO_PATH, 'r', encoding='utf-8') as f:
                _sections_info_cache = json.load(f)
        except Exception:
            return []
    
    sections = []
    # Make sure to return them in order SECTION_I to SECTION_XXI
    # Python 3.7+ preserves insertion order, which should be fine if JSON is ordered, 
    # but we will just trust the order in JSON.
    for sec_id, data in _sections_info_cache.items():
        title_to_use = data.get("short_title", data.get("title", ""))
        sections.append({
            "id": sec_id,
            "title": title_to_use
        })
    return sections

def get_chapters_for_section(section_id: str) -> list:
    """Returns a list of chapter IDs belonging to a given section."""
    return SECTION_TO_CHAPTERS.get(section_id, [])

def get_chapter_title(chapter_id: str) -> str:
    """Helper to get just the title of a chapter for the Tier-1 router."""
    global _titles_cache
    ch_id_str = str(chapter_id).zfill(2)

    # BUG-3 FIX: use cache to avoid reading file on every call
    if ch_id_str in _titles_cache:
        return _titles_cache[ch_id_str]

    # Check whether a monolithic tree file exists
    mono_path = os.path.join(BASE_DIR, "database", f"chapter_{int(ch_id_str)}_tree.json")
    has_mono = os.path.exists(mono_path)

    tree_data = get_chapter_tree(ch_id_str)

    if has_mono and tree_data:
        # Standard case: first node IS the chapter root heading
        title = tree_data[0].get("description_en", f"Chapter {ch_id_str}")
    else:
        # Sub-tree split (e.g. Chapter 28): first node is a sub-heading, not the chapter.
        # Use the rules file [inclusions][0] for a proper chapter-level description.
        rules = get_chapter_rules_raw(ch_id_str)
        inclusions = rules.get("inclusions", [])
        if inclusions:
            title = inclusions[0][:150]
        elif tree_data:
            title = tree_data[0].get("description_en", f"Chapter {ch_id_str}")
        else:
            title = f"Chapter {ch_id_str}"

    _titles_cache[ch_id_str] = title
    return title


def search_hs_nodes(query: str, chapter_id: str = None) -> dict:
    """Semantically search HS nodes using ChromaDB"""
    try:
        col_nodes, _ = _get_vector_collections()
        where_clause = {"chapter_id": str(chapter_id).zfill(2)} if chapter_id else None
        
        # Nếu chapter chưa được index trong VectorDB, Chroma sẽ báo lỗi. Trả fallback báo lỗi an toàn.
        try:
            results = col_nodes.query(query_texts=[query], n_results=5, where=where_clause)
        except Exception as query_e:
            return {"error": f"Lỗi truy vấn Vector DB (có thể chương {chapter_id} chưa được index): {query_e}"}
            
        matches = []
        if results.get("ids") and len(results["ids"]) > 0:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i]
                matches.append({
                    "hs_code": meta["hs_code"],
                    "description": meta["description"],
                    "distance": round(dist, 4)
                })
        return {"query": query, "results": matches}
    except Exception as e:
        return {"error": str(e)}

def query_legal_notes(query: str, section_id: str, chapter_id: str) -> dict:
    """Semantically search legal exclusions/inclusions using ChromaDB"""
    try:
        _, col_rules = _get_vector_collections()
        
        sec_results = {"ids": [[]]}
        ch_results = {"ids": [[]]}
        
        try:
            sec_results = col_rules.query(
                query_texts=[query], 
                n_results=3, 
                where={"section_id": section_id}
            )
        except Exception as e:
            # BUG-6 FIX: log warning thay vì nuốt lỗi im lặng
            print(f"[knowledge_tools] Section query warning (section={section_id}): {e}")
        
        try:
            ch_results = col_rules.query(
                query_texts=[query], 
                n_results=3, 
                where={"chapter_id": str(chapter_id).zfill(2)}
            )
        except Exception as e:
            # BUG-6 FIX: log warning thay vì nuốt lỗi im lặng
            print(f"[knowledge_tools] Chapter query warning (chapter={chapter_id}): {e}")
        
        def format_res(res):
            out = []
            if not res or not res.get("ids") or not res["ids"][0]: return out
            for i in range(len(res["ids"][0])):
                meta = res["metadatas"][0][i]
                if meta.get("type") == "exclusion":
                    out.append(f"EXCLUSION: If {meta.get('condition', '')} -> {meta.get('action', '')}")
                else:
                    out.append(f"INCLUSION: {meta.get('description', '')}")
            return list(set(out)) # Xóa trùng
            
        return {
            "query": query,
            "relevant_section_notes": format_res(sec_results),
            "relevant_chapter_rules": format_res(ch_results)
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print("Test navigate_node('01'):")
    print(json.dumps(navigate_node("01"), ensure_ascii=False, indent=2))
    
    print("\\nTest navigate_node('0106'):")
    print(json.dumps(navigate_node("0106"), ensure_ascii=False, indent=2))
    
    # Test pseudo node traversal uniqueness
    print("\\nTest navigate_node('0106_PSEUDO_NODE_1_0'):")
    print(json.dumps(navigate_node("0106_PSEUDO_NODE_1_0"), ensure_ascii=False, indent=2))
    
    print("\\nTest get_chapter_rules('01'):")
    print(json.dumps(get_chapter_rules("01"), ensure_ascii=False, indent=2))
