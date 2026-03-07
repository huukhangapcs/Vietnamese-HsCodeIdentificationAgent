import json
import os
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(BASE_DIR, "chroma_db")

# Dùng model đa ngữ (hỗ trợ Tiếng Việt & Tiếng Anh cực tốt)
print("Loading Embedding Model...")
# Wrap SentenceTransformer in Chroma's embedding function
class CustomEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model_name="paraphrase-multilingual-MiniLM-L12-v2"):
        self.model = SentenceTransformer(model_name)
    
    def __call__(self, input):
        # input is a list of strings
        embeddings = self.model.encode(input)
        return embeddings.tolist()

embed_fn = CustomEmbeddingFunction()

# Khởi tạo Chroma Client lưu trên ổ cứng
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

print("Creating/Connecting Collections...")
# Tạo 2 Collection: 1 cho Danh mục hàng hóa (Nodes), 1 cho Chú giải pháp lý (Rules)
collection_nodes = client.get_or_create_collection(
    name="hs_nodes",
    embedding_function=embed_fn,
    metadata={"hnsw:space": "cosine"}
)

collection_rules = client.get_or_create_collection(
    name="hs_rules",
    embedding_function=embed_fn,
    metadata={"hnsw:space": "cosine"}
)

def build_nodes():
    print("Building HS Nodes Vectors...")
    documents = []
    metadatas = []
    ids = []
    
    # Quét tất cả các file chapter_*_tree.json
    for filename in os.listdir(BASE_DIR):
        if filename.startswith("chapter_") and filename.endswith("_tree.json"):
            chapter_id = filename.split("_")[1]
            filepath = os.path.join(BASE_DIR, filename)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                tree_data = json.load(f)
                
            # Đệ quy để lôi toàn bộ nodes ra
            def process_node(node):
                hs_code = node.get("hs_code", "")
                
                # Bắt Exception cho tiếng anh lẫn tiếng việt đã bị xoá
                desc = node.get("semantic_path", node.get("description_en", node.get("description_vi", "")))
                if not desc:
                    desc = f"Heading {hs_code}"
                
                # Text để nhúng Vector (Càng rõ nghĩa càng tốt)
                embed_text = f"HS Code: {hs_code}. Description: {desc}"
                
                documents.append(embed_text)
                metadatas.append({
                    "hs_code": hs_code,
                    "chapter_id": chapter_id,
                    "description": desc,
                    "is_leaf": len(node.get("children", [])) == 0
                })
                # Đảm bảo ID duy nhất bằng UUID để tránh lỗi trùng lặp PSEUDO_NODE
                ids.append(str(uuid.uuid4()))
                
                for child in node.get("children", []):
                    process_node(child)
                    
            for root_node in tree_data:
                process_node(root_node)

    if documents:
        # Xóa cũ trước khi batch insert
        print(f"  Inserting {len(documents)} nodes...")
        batch_size = 5000
        for i in range(0, len(documents), batch_size):
            end = i + batch_size
            collection_nodes.upsert(
                documents=documents[i:end],
                metadatas=metadatas[i:end],
                ids=ids[i:end]
            )
        print("Done HS Nodes!")

def build_rules():
    print("Building HS Rules Vectors...")
    documents = []
    metadatas = []
    ids = []
    
    # 1. Section Notes
    sections_path = os.path.join(BASE_DIR, "sections_info_aku.json")
    if os.path.exists(sections_path):
        with open(sections_path, 'r', encoding='utf-8') as f:
            sections_data = json.load(f)
            
        for sec_id, data in sections_data.items():
            structured_notes = data.get("structured_notes", {})
            for idx, excl in enumerate(structured_notes.get("exclusions", [])):
                condition = excl.get("condition", "")
                action = excl.get("action", "")
                
                doc = f"Exclusion Note for {sec_id}: If {condition}, then {action}"
                documents.append(doc)
                metadatas.append({"level": "section", "section_id": sec_id, "type": "exclusion", "condition": condition, "action": action})
                ids.append(str(uuid.uuid4()))
                
            for idx, inc in enumerate(structured_notes.get("inclusions", [])):
                desc = inc if isinstance(inc, str) else inc.get("description", "")
                doc = f"Inclusion Note for {sec_id}: Specifically includes {desc}"
                documents.append(doc)
                metadatas.append({"level": "section", "section_id": sec_id, "type": "inclusion", "description": desc})
                ids.append(str(uuid.uuid4()))

    # 2. Chapter Rules
    for filename in os.listdir(BASE_DIR):
        if filename.startswith("chapter_") and filename.endswith("_rules.json"):
            chapter_id = filename.split("_")[1]
            filepath = os.path.join(BASE_DIR, filename)
            
            with open(filepath, 'r', encoding='utf-8') as f:
                rules_data = json.load(f)
                
            for idx, excl in enumerate(rules_data.get("exclusions", [])):
                condition = excl.get("condition", "")
                action = excl.get("action", "")
                
                doc = f"Exclusion Rule for Chapter {chapter_id}: If {condition}, then {action}"
                documents.append(doc)
                metadatas.append({"level": "chapter", "chapter_id": chapter_id, "type": "exclusion", "condition": condition, "action": action})
                ids.append(str(uuid.uuid4()))
                
            for idx, inc in enumerate(rules_data.get("inclusions", [])):
                desc = inc if isinstance(inc, str) else inc.get("description", "")
                doc = f"Inclusion Rule for Chapter {chapter_id}: Covers {desc}"
                documents.append(doc)
                metadatas.append({"level": "chapter", "chapter_id": chapter_id, "type": "inclusion", "description": desc})
                ids.append(str(uuid.uuid4()))

    if documents:
        print(f"  Inserting {len(documents)} rule chunks...")
        collection_rules.upsert(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        print("Done HS Rules!")

if __name__ == "__main__":
    print("=== STARTING VECTOR DB BUILDER ===")
    build_nodes()
    build_rules()
    print("=== FINISHED BUILDING VECTOR DB ===")
