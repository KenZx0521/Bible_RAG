# Bible RAG 後續步驟

## 目前完成

- [x] Hierarchical Chunking（Book → Chapter → Pericope → Chunk）
- [x] JSONL 輸出（7 個檔案）

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
python scripts/process_bible.py --input-dir bible_md --output-dir output

### 輸出
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

---

## Step 2: Embeddings 生成

### 輸入
- `output/embedding_queue.jsonl`（3,041 筆）

### 模型
- BGE-M3（BAAI/bge-m3）
- 維度：1024
- 最大 tokens：8192

### 輸出
- `output/embeddings.jsonl`（或直接寫入向量資料庫）

---

## Step 3: 匯入 PostgreSQL

### 匯入資料
- `output/books.jsonl`
- `output/chapters.jsonl`
- `output/pericopes.jsonl`
- `output/chunks.jsonl`
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

---

## Step 4: 匯入 Qdrant

### 匯入資料
- Embeddings（from Step 2）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings`（pericope + chunk embeddings）

---

## Step 5: 匯入 Neo4j

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
