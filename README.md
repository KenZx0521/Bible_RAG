# Bible RAG

繁體中文聖經問答系統，採用信號驅動六路由 Graph RAG 架構，整合 PostgreSQL、Qdrant、Neo4j 三大資料庫，實現多策略檢索與回答生成。

## Features

- **信號驅動路由**：6 種布林信號自動判定最佳檢索路由（R1–R6 + Fallback）
- **三資料庫整合**：PostgreSQL（結構化資料）、Qdrant（向量語意搜尋）、Neo4j（知識圖譜）
- **多策略並行檢索**：SQL 直查、語意檢索、圖譜走訪、交叉引用平行執行
- **智慧意圖分類**：Regex 經文偵測 + LLM 語意分類的混合方法
- **實體辭典比對**：內建人物、地名、事件辭典，無需 LLM 即可快速比對
- **BGE-M3 + Reranker**：語意嵌入搜尋搭配 BGE Reranker v2 重排序
- **多 LLM 支援**：Ollama（Gemma 3 4B）、Claude、OpenAI、Gemini
- **完整評估框架**：100 題五類型測試集，19 項指標（RAGAS + 自定義 + LLM Judge）

## Architecture

```
使用者查詢
    │
    ├─ 1. 經文引用偵測 (Regex)
    ├─ 2. 意圖分類 (LLM)
    │
    ▼
信號偵測器 (6 signals)
    │
    ├─ has_book_chapter_verse  → R1: SQL 直查
    ├─ has_book_chapter        → R2: SQL + 語意
    ├─ has_multi_book          → R5: 交叉引用 ∥ 圖譜 + 語意 + SQL
    ├─ has_multi_person        → R3: 圖譜(人物) + 語意 + SQL
    ├─ has_event_keyword       → R4: 圖譜(事件) + 語意 + SQL
    ├─ has_place               → R6: 圖譜(地名) + 語意 + SQL
    └─ (none)                  → Fallback: 語意檢索
    │
    ▼
融合去重 → BGE Reranker → 回答生成 (LLM)
```

## Tech Stack

| 元件 | 技術 |
|------|------|
| Backend | FastAPI + uvicorn |
| 結構化資料 | PostgreSQL 15 + pgvector |
| 向量搜尋 | Qdrant 1.7 |
| 知識圖譜 | Neo4j 5.15 Community + APOC |
| 嵌入模型 | BAAI/bge-m3 (1024 dim) |
| 重排序 | BAAI/bge-reranker-v2-m3 |
| 生成模型 | Ollama (gemma3:4b) / Claude / OpenAI / Gemini |
| 套件管理 | uv |
| 容器化 | Docker Compose |

## Prerequisites

- Docker & Docker Compose
- [Ollama](https://ollama.ai/) 安裝於主機（或設定雲端 LLM API Key）
- Python 3.10+（僅開發與評估需要）
- [uv](https://github.com/astral-sh/uv)（僅開發需要）

## Quick Start

### 1. 複製環境設定

```bash
cp .env.example .env
```

依需求編輯 `.env`，設定 LLM Provider 和 API Key。

### 2. 啟動 Ollama 模型（使用本地 LLM 時）

```bash
ollama pull gemma3:4b
```

### 3. 啟動所有服務

```bash
docker compose up -d
```

此指令啟動：
- **backend** — FastAPI 服務 (port 8000)
- **postgres** — PostgreSQL + pgvector (port 5432)
- **qdrant** — Qdrant 向量資料庫 (port 6333)
- **neo4j** — Neo4j 圖譜資料庫 (port 7474/7687)

### 4. 確認服務健康

```bash
curl http://localhost:8000/api/v1/health
```

### 5. 查詢測試

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "根據約翰福音3:16，神如何表達祂對世人的愛？"}'
```

## Project Structure

```
Senior/
├── backend/                    # FastAPI 後端
│   ├── main.py                 # 應用程式入口 + lifespan 管理
│   ├── config.py               # pydantic-settings 設定
│   ├── routers/
│   │   ├── query.py            # RAG 查詢端點
│   │   ├── verse.py            # 經文查詢端點
│   │   ├── entity.py           # 實體查詢端點
│   │   └── health.py           # 健康檢查端點
│   ├── database/
│   │   ├── postgres.py         # PostgreSQL 連線與查詢
│   │   ├── qdrant_db.py        # Qdrant 向量搜尋
│   │   ├── qdrant_hybrid.py    # Qdrant 混合搜尋
│   │   └── neo4j_db.py         # Neo4j 圖譜查詢
│   └── utils/
│       ├── signal_detector.py  # 6-signal 查詢偵測器 + 決策樹
│       ├── intent_classifier.py# LLM 意圖分類器
│       ├── entity_dicts.py     # 人物/地名/事件辭典比對
│       ├── verse_parser.py     # 經文引用解析 (Regex)
│       ├── embedder.py         # BGE-M3 嵌入模型
│       ├── reranker.py         # BGE Reranker v2
│       ├── generator.py        # LLM 回答生成
│       ├── sparse_encoder.py   # BM25 稀疏編碼
│       ├── llm/                # 多 LLM Provider 抽象層
│       └── retrieval/
│           ├── router.py           # 6-route 信號驅動路由器
│           ├── verse_retriever.py  # SQL 經文直查
│           ├── semantic_retriever.py# Qdrant 語意檢索
│           ├── hybrid_retriever.py # 混合檢索 (Dense + Sparse)
│           ├── graph_retriever.py  # Neo4j 圖譜走訪
│           └── cross_ref_retriever.py # 交叉引用檢索
├── bible_chunking/             # 聖經文本前處理
│   ├── markdown_parser.py      # Markdown 聖經解析
│   ├── hierarchical_chunker.py # 階層式分塊
│   ├── entity_extraction/      # NER + LLM 實體抽取
│   └── nt_cross_references.py  # 新約交叉引用
├── bible_md/                   # 66 卷聖經 Markdown 原始資料
├── scripts/
│   ├── process_bible.py        # 聖經文本處理管線
│   ├── extract_entities.py     # 實體抽取管線
│   ├── generate_embeddings.py  # 嵌入向量生成
│   ├── import_postgres.py      # PostgreSQL 資料匯入
│   ├── import_qdrant.py        # Qdrant 向量匯入
│   ├── import_neo4j.py         # Neo4j 圖譜匯入
│   └── db/schema.sql           # PostgreSQL 資料庫 Schema
├── evaluation/                 # 評估框架
│   ├── run_eval.py             # 評估 CLI 入口
│   ├── src/
│   │   ├── evaluator.py        # 評估主邏輯
│   │   ├── collector.py        # RAG 回應收集
│   │   ├── rag_client.py       # RAG API 客戶端
│   │   ├── relevance_judge.py  # LLM 相關性評判
│   │   ├── visualizer.py       # Dashboard 視覺化
│   │   └── metrics/
│   │       ├── ragas_eval.py       # RAGAS 指標
│   │       ├── llm_judge.py        # LLM Judge 指標
│   │       ├── reference_based.py  # 參考答案比對
│   │       ├── retrieval.py        # 檢索品質指標
│   │       └── semantic_similarity.py # 語意相似度
│   └── results/                # 評估結果
├── ground_truth.json           # 100 題測試集（5 類型 × 20 題）
├── docker-compose.yml          # Docker Compose 設定
├── Dockerfile                  # 後端 Docker 映像
└── .env.example                # 環境變數範例
```

## Database Schema

### PostgreSQL (結構化資料)

| 表格 | 說明 | 筆數 |
|------|------|------|
| `books` | 66 卷書卷 | 66 |
| `chapters` | 章節 | 1,189 |
| `pericopes` | 段落單元 | ~2,600 |
| `chunks` | 分塊 | ~400 |
| `entities` | 實體 (人物/地名/事件) | ~5,000 |
| `entity_mentions` | 實體提及 | ~90,000 |

### Qdrant (向量資料庫)

- Collection：`bible_embeddings`
- 向量數量：3,041
- 維度：1024 (BGE-M3)

### Neo4j (知識圖譜)

- 節點：19,317 (Person, Place, Event, Theme, Object, Group, Pericope, Chunk, Chapter, Book)
- 關係：58,031 (MENTIONS, CONTAINS, NEXT, CROSS_REFERENCES, NEXT_BOOK)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | 服務健康檢查 |
| `POST` | `/api/v1/query` | RAG 聖經查詢 |
| `GET` | `/api/v1/verse/{ref}` | 經文查詢 |
| `GET` | `/api/v1/entity/{name}` | 實體查詢 |
| `GET` | `/docs` | Swagger UI |

### Query Request

```json
{
  "question": "保羅在大馬色路上遇到了什麼事？",
  "top_k": 5,
  "include_sources": true
}
```

### Query Response

```json
{
  "answer": "根據使徒行傳第9章...",
  "sources": [
    {
      "id": "act:9:p1",
      "book": "使徒行傳",
      "chapter": 9,
      "title": "掃羅歸主",
      "verse_range": "1-9",
      "score": 0.92
    }
  ],
  "intent": {
    "type": "event",
    "entities": ["保羅"],
    "verse_refs": []
  },
  "retrieval_stats": {
    "strategies_used": ["graph_event", "semantic"],
    "total_candidates": 15,
    "reranked_top_k": 5,
    "route_used": "R4"
  }
}
```

## Configuration

所有設定透過 `.env` 管理，複製範例後依需求修改：

```bash
cp .env.example .env
```

### LLM 設定

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供者（`ollama` / `claude` / `openai` / `gemini`） | `claude` |
| `ANTHROPIC_API_KEY` | Claude API Key | — |
| `CLAUDE_MODEL` | Claude 模型名稱 | `claude-haiku-4-5` |
| `GOOGLE_API_KEY` | Gemini API Key | — |
| `GEMINI_MODEL` | Gemini 模型名稱 | `gemini-1.5-flash` |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `OPENAI_MODEL` | OpenAI 模型名稱 | `gpt-4o-mini` |
| `OLLAMA_BASE_URL` | Ollama 服務位址 | `http://localhost:11434` |

### LLM 請求參數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `LLM_MAX_TOKENS` | 回應最大 token 數 | `1024` |
| `LLM_TEMPERATURE` | 生成溫度（0.0–1.0，越低越確定性） | `0.1` |
| `LLM_RATE_LIMIT_DELAY` | 請求間隔秒數（限流） | `1.0` |
| `LLM_MAX_RETRIES` | 最大重試次數 | `3` |
| `LLM_RETRY_DELAY` | 重試等待秒數 | `5.0` |

### 資料庫連線

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `POSTGRES_HOST` | PostgreSQL 主機 | `localhost` |
| `POSTGRES_PORT` | PostgreSQL 埠號 | `5432` |
| `POSTGRES_DB` | 資料庫名稱 | `bible_rag` |
| `POSTGRES_USER` | 使用者帳號 | `bible` |
| `POSTGRES_PASSWORD` | 使用者密碼 | `bible_password` |
| `QDRANT_HOST` | Qdrant 主機 | `localhost` |
| `QDRANT_HTTP_PORT` | Qdrant HTTP 埠號 | `6333` |
| `QDRANT_GRPC_PORT` | Qdrant gRPC 埠號 | `6334` |
| `NEO4J_URI` | Neo4j Bolt 連線 URI | `bolt://localhost:7687` |
| `NEO4J_HTTP_PORT` | Neo4j HTTP 埠號 | `7474` |
| `NEO4J_BOLT_PORT` | Neo4j Bolt 埠號 | `7687` |
| `NEO4J_USER` | Neo4j 帳號 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密碼 | `neo4j_password` |

### 其他設定

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `CKIP_USE_GPU` | CKIP NER 模型是否使用 GPU | `false` |
| `BATCH_SIZE` | 實體抽取批次大小 | `5` |
| `VERBOSE` | 是否啟用詳細日誌 | `false` |
| `BACKEND_PORT` | 後端服務埠號（Docker 部署用） | `8000` |

> **Docker Compose 注意事項**：使用 `docker compose up` 時，以下變數會自動被 `docker-compose.yml` 覆寫，不需手動修改：
> - `POSTGRES_HOST` → `postgres`
> - `QDRANT_HOST` → `qdrant`
> - `NEO4J_URI` → `bolt://neo4j:7687`
> - `OLLAMA_BASE_URL` → `http://host.docker.internal:11434`

## Database Access

服務啟動後，可透過瀏覽器或 CLI 工具存取各資料庫的管理介面。

### Neo4j Browser

```
http://localhost:7474
```

- 開啟後輸入帳號密碼（預設 `neo4j` / `neo4j_password`）
- 可直接執行 Cypher 查詢，例如：

```cypher
// 查看所有節點標籤與數量
MATCH (n) RETURN labels(n) AS label, count(*) AS count ORDER BY count DESC;

// 查詢特定人物的相關段落
MATCH (p:Person {canonical_name: "保羅"})-[:MENTIONS]-(per:Pericope)
RETURN per.title, per.id LIMIT 10;
```

### Qdrant Dashboard

```
http://localhost:6333/dashboard
```

- 無需帳號密碼，開啟即可使用
- 可瀏覽 Collection 列表、查看向量點數、執行相似度搜尋
- REST API 也可直接存取：

```bash
# 查看所有 collections
curl http://localhost:6333/collections

# 查看 bible_embeddings collection 資訊
curl http://localhost:6333/collections/bible_embeddings
```

### PostgreSQL

PostgreSQL 沒有內建 Web UI，可透過以下方式連線：

**psql CLI**（Docker 內）：

```bash
docker exec -it bible_rag_postgres psql -U bible -d bible_rag
```

```sql
-- 查看所有表格
\dt

-- 查看書卷列表
SELECT id, name, testament, total_chapters FROM books ORDER BY "order";

-- 查看段落範例
SELECT id, title, book_name, chapter_num FROM pericopes LIMIT 10;
```

**外部連線**（本機工具如 pgAdmin、DBeaver、DataGrip）：

| 參數 | 值 |
|------|------|
| Host | `localhost` |
| Port | `5432` |
| Database | `bible_rag` |
| User | `bible` |
| Password | `bible_password` |

### FastAPI Swagger UI

```
http://localhost:8000/docs
```

- 所有 API 端點的互動式文件，可直接在頁面上測試查詢

## Evaluation

評估框架使用 100 題測試集，涵蓋 5 類問題：

| 類型 | 題數 | 範例 |
|------|------|------|
| VERSE_LOOKUP | 20 | 根據約翰福音 3:16，神如何表達祂對世人的愛？ |
| TOPIC_QUESTION | 20 | 聖經中如何定義「信心」？ |
| PERSON_QUESTION | 20 | 摩西與葉忒羅的關係如何？ |
| EVENT_QUESTION | 20 | 出埃及過程中經歷了哪些神蹟？ |
| GENERAL_BIBLE_QUESTION | 20 | 新約福音書的寫作背景為何？ |

### 執行評估

```bash
cd evaluation

# 完整評估管線
uv run python run_eval.py

# 僅收集 RAG 回應
uv run python run_eval.py --collect-only

# 僅執行批次指標計算
uv run python run_eval.py --eval-only

# 僅生成 Dashboard
uv run python run_eval.py --visualize-only
```

### 評估指標

- **RAGAS**：Faithfulness、Answer Relevancy、Context Precision、Context Recall
- **LLM Judge**：Point Coverage（答案要點涵蓋率）
- **Reference-based**：BLEU、ROUGE-L、BERTScore
- **Retrieval**：MRR、Hit Rate、Context Relevancy
- **Semantic Similarity**：嵌入向量餘弦相似度

## Data Pipeline

建構資料庫的完整管線：

```bash
# 1. 處理聖經 Markdown → JSON
python scripts/process_bible.py

# 2. 抽取實體 (人物/地名/事件)
python scripts/extract_entities.py

# 3. 生成嵌入向量
python scripts/generate_embeddings.py

# 4. 匯入 PostgreSQL
python scripts/import_postgres.py

# 5. 匯入 Qdrant 向量
python scripts/import_qdrant.py

# 6. 匯入 Neo4j 圖譜
python scripts/import_neo4j.py
```

## Development

```bash
# 安裝後端依賴
cd backend && uv sync

# 本地啟動 (需先啟動 PostgreSQL/Qdrant/Neo4j)
uv run uvicorn main:app --reload --port 8000

# 安裝評估依賴
cd evaluation && uv sync
```

## License

MIT
