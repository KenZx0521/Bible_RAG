# Bible RAG 後續步驟

## 目前完成

- [x] Hierarchical Chunking（Book → Chapter → Pericope → Chunk）
- [x] JSONL 輸出（7 個檔案）
### 指令
python scripts/process_bible.py --input-dir bible_md --output-dir output
---

## Step 1: 實體抽取

### 輸入
- `output/embedding_queue.jsonl`（3,041 筆）

### 待抽取實體類型
| 類型 | 說明 |
|------|------|
| Person | 人物（亞伯拉罕、摩西、耶穌） |
| Place | 地點（耶路撒冷、埃及、加利利） |
| Group | 群體（以色列人、法利賽人） |
| Event | 事件（出埃及、復活） |
| Object | 物件（約櫃、會幕） |
| Theme | 主題（救贖、恩典、信心） |

### 指令
# NER-only (無 API 成本)
python scripts/extract_entities.py --ner-only

# 完整抽取 (需設定 API key)
python scripts/extract_entities.py

### 輸出
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

---

## Step 2: Embeddings 生成 ✅

### 輸入
- `output/embedding_queue.jsonl`（3,041 筆）

### 模型
- BGE-M3（BAAI/bge-m3）
- 維度：1024
- 最大 tokens：8192

### 指令
```bash
python scripts/generate_embeddings.py --batch-size 32
```

### 輸出
- `output/embeddings.jsonl`（3,041 筆，每筆 1024 維向量）

---

## Step 2.1: Sparse Vectors 生成（Hybrid Search）

### 說明
為 Hybrid Search 生成 BM25-based sparse vectors，使用 CKIP 進行中文斷詞。

### 輸入
- `output/embedding_queue.jsonl`

### 指令
```bash
python scripts/generate_sparse_vectors.py --batch-size 32

# 使用 GPU 加速 CKIP
python scripts/generate_sparse_vectors.py --batch-size 32 --use-gpu
```

### 輸出
- `output/sparse_vectors.jsonl`（每筆包含 sparse vector indices 和 values）
- `output/bm25_vocabulary.json`（BM25 詞彙表和 IDF 值）

---

## Step 3: 匯入 PostgreSQL ✅

### 匯入資料
- `output/books.jsonl`
- `output/chapters.jsonl`
- `output/pericopes.jsonl`
- `output/chunks.jsonl`
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

### 指令
```bash
python scripts/import_postgres.py
```

### 結果
- books: 66 records
- chapters: 1,189 records
- pericopes: 2,779 records
- chunks: 431 records
- entities: 14,845 records
- entity_mentions: 80,912 records
- **總計: 100,222 records**

---

## Step 4: 匯入 Qdrant ✅

### 匯入資料
- Embeddings（from Step 2）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings`（pericope + chunk embeddings）

### 指令
```bash
python scripts/import_qdrant.py
```

### 結果
- Vectors: 3,041 (1024 維度)

---

## Step 4.1: 匯入 Qdrant Hybrid Collection

### 說明
建立包含 dense + sparse vectors 的 hybrid collection，支援 RRF 混合檢索。

### 匯入資料
- `output/embeddings.jsonl`（dense vectors）
- `output/sparse_vectors.jsonl`（sparse vectors）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings_hybrid`
  - dense: 1024D BGE-M3 向量（COSINE distance）
  - sparse: BM25-based sparse 向量

### 指令
```bash
python scripts/import_qdrant_hybrid.py
```

### 結果
- Points: 3,041（每個點包含 dense + sparse vectors）

### 啟用 Hybrid Search
在 `.env` 中設定：
```bash
HYBRID_SEARCH_ENABLED=true
```

---

## Step 5: 匯入 Neo4j ✅

### 匯入資料
- `output/neo4j_nodes.jsonl`（4,465 筆）
- `output/neo4j_relationships.jsonl`（8,209 筆）
- 實體節點與關係（from Step 1）

### 節點類型
- Book、Chapter、Pericope、Chunk
- Person、Place、Group、Event、Object、Theme

### 關係類型
- CONTAINS、NEXT、NEXT_BOOK
- CROSS_REFERENCES
- MENTIONS（實體出現）

### 指令
```bash
python scripts/import_neo4j.py
```

### 結果
- Total nodes: 19,310
- Total relationships: 57,877

---

## 資料庫啟動指令

```bash
# 啟動所有資料庫
docker compose up -d

# 停止資料庫
docker compose down
```

### 服務端點
| 服務 | 端點 |
|------|------|
| PostgreSQL | localhost:5432 |
| Qdrant | http://localhost:6333/dashboard |
| Neo4j | http://localhost:7474 |