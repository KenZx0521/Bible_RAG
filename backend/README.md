# Bible RAG Backend

聖經知識型 RAG 系統後端服務 - 基於新標點和合本聖經 PDF。

## 技術棧

- **Web 框架**: FastAPI + Uvicorn
- **資料庫**: PostgreSQL + pgvector (向量檢索)
- **圖資料庫**: Neo4j (知識圖譜)
- **LLM**: Ollama (gemma3:4b)
- **Embeddings**: FlagEmbedding bge-m3 (1024 維度)

## 快速開始 (給前端開發者)

### 前置需求

- Docker + Docker Compose
- Python 3.11+ (建議使用 uv)
- Ollama 已安裝並拉取 `gemma3:4b` 模型

### 1. 啟動後端服務 (一鍵啟動)

```bash
cd backend

# 啟動基礎設施 (PostgreSQL + Neo4j + Ollama)
docker compose --profile full up -d

# 等待服務就緒 (~30秒)
sleep 30

# 建立虛擬環境並安裝依賴
uv venv && source .venv/bin/activate && uv pip install -e .

# 執行資料庫遷移
alembic upgrade head

# 解析聖經 PDF 並建立索引 (約需 10-15 分鐘)
python -m scripts.build_index --pdf pdf/cmn-cu89t_a4.pdf

# 啟動 API 服務
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. 驗證服務

```bash
# 確認 API 運行
curl http://localhost:8000/api/v1/books | head

# 確認 Neo4j 連線
curl http://localhost:8000/api/v1/graph/health

# 測試 RAG 查詢
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "聖經怎麼談饒恕？"}'
```

### 3. 可選：建置知識圖譜 (需要數小時)

```bash
# LLM 實體標註 (約 6-10 小時)
python -m scripts.entity_extractor --batch-size 10

# 建置 Neo4j 圖譜
python -m scripts.build_graph

# 計算主題關聯
python -m scripts.compute_topic_relations
```

---

## API 文件 (供前端使用)

### 互動式文檔

| 端點 | 說明 |
|------|------|
| [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs) | **Swagger UI** - 互動式 API 測試 |
| [http://localhost:8000/api/v1/redoc](http://localhost:8000/api/v1/redoc) | **ReDoc** - 閱讀式 API 文檔 |
| [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json) | **OpenAPI JSON** - 匯入 Postman 用 |

### Postman 匯入方式

1. 打開 Postman → **Import**
2. 選擇 **Link** 標籤
3. 貼上: `http://localhost:8000/api/v1/openapi.json`
4. 點擊 **Continue** → **Import**
5. 即可看到所有 API 端點及範例

---

Base URL: `http://localhost:8000/api/v1`

### RAG 查詢 API

#### POST `/query` - 主查詢端點

執行完整 RAG 管線，回傳 LLM 生成的答案與相關經文。

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "聖經怎麼談饒恕？", "mode": "auto", "options": {"max_results": 5}}'
```

**Request:**

```json
{
  "query": "聖經怎麼談饒恕？",
  "mode": "auto",
  "options": {
    "max_results": 5,
    "include_graph": true
  }
}
```

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `query` | string | 是 | 使用者自然語言問題 |
| `mode` | string | 否 | 查詢模式: `auto`/`verse`/`topic`/`person`/`event` |
| `options.max_results` | int | 否 | 回傳段落數量 (預設 5) |
| `options.include_graph` | bool | 否 | 是否包含圖譜上下文 (預設 true) |

**Response:**

```json
{
  "answer": "根據聖經教導，饒恕是基督徒信仰的核心...",
  "segments": [
    {
      "id": 1234,
      "book_name": "馬太福音",
      "chapter_start": 18,
      "verse_start": 21,
      "chapter_end": 18,
      "verse_end": 35,
      "title": "饒恕弟兄的比喻",
      "text": "那時，彼得進前來，對耶穌說..."
    }
  ],
  "meta": {
    "query_type": "TOPIC_QUESTION",
    "used_retrievers": ["dense", "sparse", "graph"],
    "total_processing_time_ms": 2500,
    "llm_model": "gemma3:4b"
  },
  "graph_context": {
    "related_topics": ["饒恕", "恩典", "憐憫"],
    "related_persons": ["耶穌", "彼得"]
  }
}
```

---

### 書卷 API

#### GET `/books` - 取得所有書卷

```bash
curl http://localhost:8000/api/v1/books
```

```json
{
  "books": [
    {"id": 4, "name_zh": "創世記", "abbrev_zh": "創", "testament": "OT", "order_index": 1},
    {"id": 5, "name_zh": "出埃及記", "abbrev_zh": "出", "testament": "OT", "order_index": 2},
    {"id": 43, "name_zh": "馬太福音", "abbrev_zh": "太", "testament": "NT", "order_index": 40}
  ],
  "total": 66
}
```

#### GET `/books/{book_id}` - 取得書卷詳情

```bash
curl http://localhost:8000/api/v1/books/4
```

```json
{
  "id": 4,
  "name_zh": "創世記",
  "abbrev_zh": "創",
  "testament": "OT",
  "order_index": 1,
  "chapter_count": 50,
  "verse_count": 1319,
  "pericope_count": 221
}
```

#### GET `/books/{book_id}/chapters` - 取得書卷的所有章節

```bash
curl http://localhost:8000/api/v1/books/4/chapters
```

```json
{
  "book_id": 4,
  "book_name": "創世記",
  "chapters": [
    {"chapter": 1, "verse_count": 27},
    {"chapter": 2, "verse_count": 25},
    {"chapter": 3, "verse_count": 22}
  ]
}
```

#### GET `/books/{book_id}/pericopes` - 取得書卷的所有段落

#### GET `/books/{book_id}/verses` - 取得書卷的所有經文

| Query 參數 | 說明 |
|------------|------|
| `chapter` | 篩選指定章節 |

---

### 段落 API

#### GET `/pericopes` - 段落列表

| Query 參數 | 說明 |
|------------|------|
| `skip` | 分頁偏移 (預設 0) |
| `limit` | 每頁數量 (預設 20, 最大 100) |
| `book_id` | 篩選書卷 |

#### GET `/pericopes/{pericope_id}` - 段落詳情

```bash
curl http://localhost:8000/api/v1/pericopes/52
```

```json
{
  "id": 52,
  "book_id": 4,
  "book_name": "創世記",
  "title": "第1章",
  "reference": "創世記 1:1-31",
  "chapter_start": 1,
  "verse_start": 1,
  "chapter_end": 1,
  "verse_end": 31,
  "summary": null,
  "verses": [
    {"id": 238, "book_id": 4, "book_name": "創世記", "chapter": 1, "verse": 1, "text": "起初，上帝創造天地。", "reference": "創世記 1:1"},
    {"id": 239, "book_id": 4, "book_name": "創世記", "chapter": 1, "verse": 2, "text": "地是空虛混沌，深淵上面一片黑暗；上帝的靈運行在水面上。", "reference": "創世記 1:2"}
  ]
}
```

---

### 經文 API

#### GET `/verses` - 經文列表

| Query 參數 | 說明 |
|------------|------|
| `skip` | 分頁偏移 |
| `limit` | 每頁數量 |
| `book_id` | 篩選書卷 |
| `chapter` | 篩選章節 |
| `pericope_id` | 篩選段落 |

#### GET `/verses/{verse_id}` - 經文詳情

```bash
curl http://localhost:8000/api/v1/verses/238
```

```json
{
  "id": 238,
  "book_id": 4,
  "book_name": "創世記",
  "chapter": 1,
  "verse": 1,
  "text": "起初，上帝創造天地。",
  "reference": "創世記 1:1",
  "pericope_id": 52,
  "pericope_title": "第1章"
}
```

#### GET `/verses/search` - 經文搜尋

```bash
curl "http://localhost:8000/api/v1/verses/search?q=創造&limit=3"
```

| Query 參數 | 說明 |
|------------|------|
| `q` | 搜尋關鍵字 (必填) |
| `book_id` | 篩選書卷 |
| `limit` | 結果數量 (預設 20) |

```json
{
  "query": "創造",
  "verses": [
    {"id": 238, "book_id": 4, "book_name": "創世記", "chapter": 1, "verse": 1, "text": "起初，上帝創造天地。", "rank": 0.95},
    {"id": 264, "book_id": 4, "book_name": "創世記", "chapter": 1, "verse": 27, "text": "上帝就照著自己的形像創造人...", "rank": 0.88}
  ],
  "total": 45
}
```

---

### 知識圖譜 API

#### GET `/graph/health` - Neo4j 連線狀態

```bash
curl http://localhost:8000/api/v1/graph/health
```

```json
{"status": "healthy", "uri": "bolt://localhost:7687"}
```

#### GET `/graph/stats` - 圖譜統計

```bash
curl http://localhost:8000/api/v1/graph/stats
```

```json
{
  "total_persons": 1833,
  "total_places": 2295,
  "total_groups": 2011,
  "total_events": 5349,
  "total_topics": 3437,
  "total_relationships": 189155
}
```

#### GET `/graph/entity/search` - 實體搜尋

```bash
curl "http://localhost:8000/api/v1/graph/entity/search?name=摩西&type=PERSON&limit=5"
```

| Query 參數 | 說明 |
|------------|------|
| `name` | 名稱 (模糊搜尋) |
| `type` | 類型: `PERSON`/`PLACE`/`GROUP`/`EVENT` |
| `limit` | 結果數量 |

```json
{
  "entities": [
    {"id": 156, "name": "摩西", "type": "PERSON"},
    {"id": 289, "name": "摩西的母親", "type": "PERSON"}
  ],
  "total": 2
}
```

#### GET `/graph/entity/{entity_id}` - 實體詳情

```json
{
  "id": 100,
  "name": "亞伯拉罕",
  "type": "PERSON",
  "description": null,
  "related_verses_count": 234,
  "related_entities": [
    {"id": 101, "name": "撒拉", "type": "PERSON"},
    {"id": 102, "name": "以撒", "type": "PERSON"}
  ]
}
```

#### GET `/graph/topic/search` - 主題搜尋

| Query 參數 | 說明 |
|------------|------|
| `name` | 名稱 |
| `type` | 類型: `DOCTRINE`/`MORAL`/`HISTORICAL`/`PROPHETIC`/`OTHER` |

#### GET `/graph/topic/{topic_id}` - 主題詳情

```json
{
  "id": 50,
  "name": "饒恕",
  "type": "MORAL",
  "description": null,
  "related_verses_count": 89,
  "related_topics": [
    {"id": 51, "name": "恩典", "type": "DOCTRINE"}
  ]
}
```

#### GET `/graph/verse/{verse_id}/entities` - 經文的所有實體

```bash
curl http://localhost:8000/api/v1/graph/verse/238/entities
```

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "persons": [],
  "places": [],
  "groups": [],
  "events": [
    {"id": 1, "name": "上帝創造天地", "type": "EVENT"},
    {"id": 2, "name": "光與暗的分開", "type": "EVENT"},
    {"id": 11, "name": "照著上帝的形象創造人", "type": "EVENT"}
  ],
  "topics": [
    {"id": 1, "name": "創造", "type": "HISTORICAL"},
    {"id": 2, "name": "光與暗的分隔", "type": "DOCTRINE"},
    {"id": 4, "name": "生命之源", "type": "DOCTRINE"}
  ]
}
```

#### GET `/graph/relationships` - 關係子圖 (視覺化用)

```bash
curl "http://localhost:8000/api/v1/graph/relationships?entity_id=1&entity_type=TOPIC&depth=1"
```

| Query 參數 | 說明 |
|------------|------|
| `entity_id` | 中心實體 ID (必填) |
| `entity_type` | 實體類型: `PERSON`/`PLACE`/`GROUP`/`EVENT`/`TOPIC` (必填) |
| `depth` | 展開深度 (預設 2, 最大 3) |

```json
{
  "nodes": [
    {"id": "topic_1", "label": "創造", "type": "Topic", "properties": {"type": "HISTORICAL"}},
    {"id": "topic_2", "label": "光與暗的分隔", "type": "Topic", "properties": {"type": "DOCTRINE"}}
  ],
  "edges": [
    {"source": "topic_1", "target": "topic_2", "type": "RELATED_TO", "properties": {"weight": 0.2093}}
  ]
}
```

#### GET `/graph/topic/{topic_id}/related` - 關聯主題

```bash
curl http://localhost:8000/api/v1/graph/topic/1/related
```

```json
{
  "topic_id": 1,
  "topic_name": "創造",
  "related": [
    {"id": 2, "name": "光與暗的分隔", "type": "DOCTRINE", "weight": 0.2093, "co_occurrence": 27},
    {"id": 3, "name": "天、地和海的命名", "type": "HISTORICAL", "weight": 0.2093, "co_occurrence": 27},
    {"id": 4, "name": "生命之源", "type": "DOCTRINE", "weight": 0.2093, "co_occurrence": 27}
  ],
  "total": 3
}
```

#### GET `/graph/verse/{verse_id}/cross-references` - 經文交叉參照

```bash
curl http://localhost:8000/api/v1/graph/verse/238/cross-references
```

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "quotes": [],
  "quoted_by": [],
  "alludes_to": [],
  "alluded_by": [],
  "total": 0
}
```

> 註：需執行 `python -m scripts.import_cross_references` 匯入交叉參照資料

#### GET `/graph/verse/{verse_id}/prophecies` - 預言應驗連結

```bash
curl http://localhost:8000/api/v1/graph/verse/238/prophecies
```

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "is_ot": true,
  "fulfillments": [],
  "prophecies": [],
  "total": 0
}
```

> 註：需執行 `python -m scripts.import_prophecy_links` 匯入預言應驗資料

#### GET `/graph/pericope/{pericope_id}/parallels` - 福音書平行經文

```bash
curl http://localhost:8000/api/v1/graph/pericope/52/parallels
```

```json
{
  "pericope_id": 52,
  "pericope_title": "第1章",
  "pericope_reference": "創世記 1:1-31",
  "parallels": [],
  "total": 0
}
```

> 註：平行經文僅適用於福音書 (馬太、馬可、路加)，需執行 `python -m scripts.import_synoptic_parallels` 匯入

---

## 專案結構

```text
backend/
├── app/
│   ├── api/v1/endpoints/     # API 端點
│   │   ├── books.py          # 書卷 API
│   │   ├── graph.py          # 圖譜 API
│   │   ├── pericopes.py      # 段落 API
│   │   ├── query.py          # RAG 查詢 API
│   │   └── verses.py         # 經文 API
│   ├── core/
│   │   ├── config.py         # 設定管理
│   │   ├── database.py       # PostgreSQL 連線
│   │   └── neo4j_client.py   # Neo4j 客戶端
│   ├── models/
│   │   ├── orm.py            # SQLAlchemy ORM 模型
│   │   └── schemas/          # Pydantic 回應模型
│   ├── services/
│   │   ├── rag_pipeline.py   # RAG 管線
│   │   ├── llm_client.py     # Ollama LLM 客戶端
│   │   ├── embedding_service.py
│   │   ├── fusion.py         # RRF 融合
│   │   └── retrievers/       # 三種檢索器
│   └── main.py               # FastAPI 入口
├── scripts/
│   ├── build_index.py        # 索引建置
│   ├── entity_extractor.py   # LLM 實體標註
│   ├── build_graph.py        # Neo4j 圖譜建置
│   └── compute_topic_relations.py  # 主題關聯計算
├── pdf/
│   └── cmn-cu89t_a4.pdf      # 新標點和合本聖經
└── pyproject.toml
```

---

## RAG Pipeline 流程

```text
使用者查詢
    │
    ▼
┌─────────────┐
│  查詢分類    │ ← LLM 判斷查詢類型
└─────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│           平行檢索                   │
├─────────────┬───────────┬───────────┤
│ Dense       │ Sparse    │ Graph     │
│ (pgvector)  │ (FTS)     │ (Neo4j)   │
└─────────────┴───────────┴───────────┘
    │
    ▼
┌─────────────┐
│  RRF 融合   │ k=60
└─────────────┘
    │
    ▼
┌─────────────┐
│ Context 建構│ ← 取得段落經文
└─────────────┘
    │
    ▼
┌─────────────┐
│  LLM 生成   │ ← Ollama (gemma3:4b)
└─────────────┘
    │
    ▼
  回應結果
```

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL 連線字串 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j URI |
| `NEO4J_USER` | `neo4j` | Neo4j 使用者 |
| `NEO4J_PASSWORD` | `password` | Neo4j 密碼 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `LLM_MODEL_NAME` | `gemma3:4b` | LLM 模型名稱 |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-m3` | 嵌入模型 |
| `RRF_K` | `60` | RRF 參數 |
| `TOP_K_PERICOPES` | `5` | 預設回傳段落數 |

---

## 腳本說明

### build_index.py - 索引建置

```bash
# 完整建置 (解析 PDF + 嵌入向量)
python -m scripts.build_index --pdf pdf/cmn-cu89t_a4.pdf

# 只更新嵌入向量
python -m scripts.build_index --pdf pdf/cmn-cu89t_a4.pdf --embeddings-only
```

### entity_extractor.py - LLM 實體標註

```bash
# 標準執行 (支援斷點續傳)
python -m scripts.entity_extractor --batch-size 10

# 重新開始
python -m scripts.entity_extractor --no-resume
```

### build_graph.py - Neo4j 圖譜建置

```bash
# 建置圖譜
python -m scripts.build_graph

# 追加模式 (不清除現有資料)
python -m scripts.build_graph --no-clear
```

### compute_topic_relations.py - 主題關聯計算

```bash
# 計算主題共現關係
python -m scripts.compute_topic_relations

# 自訂閾值
python -m scripts.compute_topic_relations --min-cooccurrence 10 --min-weight 0.2
```

---

## 資料統計

| 項目 | 數量 |
|------|------|
| 書卷 | 66 |
| 章節 | 1,189 |
| 經文 | 31,103 |
| 段落 | 7,912 |
| 人物 (Person) | 1,833 |
| 地點 (Place) | 2,295 |
| 群體 (Group) | 2,011 |
| 事件 (Event) | 5,349 |
| 主題 (Topic) | 3,437 |
| 圖譜關係總數 | 189,155 |
