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
- **完整評估框架**：100 題五類型測試集，13 項指標（RAGAS + 自定義檢索指標 + LLM Judge）

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
mkdir -p ~/.cache/uv-bible-rag-backend   # backend 建置用的 uv 快取目錄(必須存在,見下方說明)
docker compose up -d
```

> **Docker 建置快取**:backend 映像檔的 `uv sync` 會掛載主機目錄 `~/.cache/uv-bible-rag-backend`(可用 `BACKEND_UV_CACHE_DIR` 改路徑)當 uv 快取,torch 與 CUDA 套件(約 4 GB)有快取就不重新下載。目錄是空的也能建置,只是會全部重抓。已有舊映像檔時可先從映像檔匯出快取:
>
> ```bash
> cid=$(docker create bible_rag-backend:pre-fix-2026-07-31)   # 任何含 /root/.cache/uv 的舊 backend 映像檔
> docker cp "$cid:/root/.cache/uv" ~/.cache/uv-bible-rag-backend && docker rm "$cid"
> ```
>
> 快取由 uv 0.12.0 寫入,Dockerfile 釘住同一版 uv;升級 uv 版本時快取可能失效(會自動重抓,不會出錯)。建置期間的寫入不會回寫主機目錄,映像檔本身也不含快取。

此指令啟動：
- **backend** — FastAPI 服務 (port 8000)
- **postgres** — PostgreSQL + pgvector (port 5432)
- **qdrant** — Qdrant 向量資料庫 (port 6333)
- **neo4j** — Neo4j 圖譜資料庫 (port 7474/7687)，只在 `--profile kg` 時啟動；R1 起 backend 不讀 Neo4j（D-09）

backend 啟動時依 `RAG_ENV`（prod／staging）讀 `rag_meta.serving` 決定服務哪個 build（`RAG_BUILD_ID` 只能核對、不能改選），
從 `rag_meta.builds` 取得該 build 的 PG schema、Qdrant collection 與契約檔目錄（`/contracts` 唯讀掛載），
並做握手檢查；任一項不符時 `/api/v1/health` 回 503 並列出不符項，`STRICT_BUILD_CHECK=true`（預設）時啟動失敗。

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
Bible_RAG/
├── backend/                    # FastAPI 後端（讀 rag_meta.serving 指定的 build）
│   ├── main.py                 # 應用程式入口 + lifespan 管理
│   ├── config.py               # pydantic-settings 設定
│   ├── serving/                # build 選擇、契約檔驗證、握手（design §7.8）
│   ├── routers/
│   │   ├── query.py            # RAG 查詢端點
│   │   ├── verse.py            # 經文與章查詢端點
│   │   ├── entity.py           # 已退役（410，D-08）
│   │   └── health.py           # 健康檢查與握手結果
│   ├── database/
│   │   ├── postgres.py         # build schema 的查詢（search_path = b{build_id}）
│   │   ├── content.py          # chunk 文字、節單位組裝（純函式）
│   │   └── qdrant_db.py        # build collection 的向量搜尋
│   └── utils/
│       ├── signal_detector.py  # 路由信號（契約的 routing_lexicon）+ 決策樹
│       ├── intent_classifier.py# LLM 意圖分類器
│       ├── verse_parser.py     # 經文引用解析（ragcommon.refs）
│       ├── embedder.py         # BGE-M3 嵌入模型
│       ├── reranker.py         # BGE Reranker v2
│       ├── generator.py        # LLM 回答生成
│       ├── llm/                # 多 LLM Provider 抽象層
│       └── retrieval/
│           ├── router.py           # 檢索、重排、釘選與事件附加槽
│           ├── routes.py           # R1–R6 與 fallback
│           ├── dense.py            # Qdrant dense 檢索
│           ├── verse_retriever.py  # SQL 經文直查
│           ├── pins.py             # 排序融合與釘選
│           └── event_registry.py   # 契約的事件註冊表（v2）
├── bible_chunking/             # 聖經文本前處理
│   ├── markdown_parser.py      # Markdown 聖經解析
│   ├── hierarchical_chunker.py # 階層式分塊
│   ├── nt_cross_references.py  # 新約交叉引用
│   └── tokenizer_wrapper.py    # 分詞器封裝
├── bible_md/                   # 66 卷聖經 Markdown 原始資料
├── bible_pdf/                  # 66 卷聖經 PDF 原始資料
├── config/
│   └── relations/              # 關係抽取類型與先驗 YAML
├── scripts/                    # 建庫管線（host-side）
│   ├── process_bible.py        # 聖經文本處理管線
│   ├── convert_bible_pdf.py    # 聖經 PDF → Markdown 轉換
│   ├── extract_entities.py     # 實體抽取管線入口
│   ├── entity_extraction/      # NER + LLM 實體抽取模組
│   ├── relation_extraction/    # Grounded 關係抽取模組
│   ├── generate_embeddings.py  # 嵌入向量生成（BGE-M3）
│   ├── generate_sparse_vectors.py # BM25 稀疏向量（CKIP 分詞）
│   ├── embed_entities.py       # Entity 節點向量化（bible_entities）
│   ├── import_postgres.py      # PostgreSQL 資料匯入
│   ├── import_qdrant.py        # Qdrant 向量匯入（dense）
│   ├── import_qdrant_hybrid.py # Qdrant 混合匯入（dense + sparse）
│   ├── import_neo4j.py         # Neo4j 圖譜匯入
│   ├── import_relations_neo4j.py # 關係三元組匯入 Neo4j
│   ├── import_tsk_crossrefs.py # TSK 串珠交叉引用匯入
│   ├── backfill_*.py           # KG P0 資料修復（mentions/aliases/events）
│   ├── cleanup_noise_entities.py # 噪音實體清理
│   └── db/schema.sql           # PostgreSQL 資料庫 Schema
├── evaluation/                 # 評估框架
│   ├── run_eval.py             # 評估 CLI 入口
│   ├── quick_retrieval_eval.py # 檢索指標快評（不經 LLM 生成）
│   ├── src/
│   │   ├── evaluator.py        # 評估主邏輯
│   │   ├── collector.py        # RAG 回應收集
│   │   ├── rag_client.py       # RAG API 客戶端
│   │   ├── relevance_judge.py  # LLM 相關性評判
│   │   ├── visualizer.py       # Dashboard 視覺化
│   │   ├── llm/                # LLM Judge 客戶端
│   │   └── metrics/
│   │       ├── ragas_eval.py       # RAGAS 指標
│   │       ├── coverage_eval.py    # Point Coverage（LLM Judge）
│   │       ├── retrieval.py        # 檢索品質指標
│   │       └── semantic_similarity.py # 語意相似度
│   └── results_*/              # 評估結果（依管線/回答模型/階段分目錄）
├── docs/                       # 專案文檔（README 地圖＋現況文件＋records/ 紀錄＋archive/ 快照＋reference/ 參考）
├── paper/                      # 論文資產（PDF、發現紀錄 record/、工具 tools/）
├── figures/                    # 論文圖（fig1 系統架構圖）
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
| `pericopes` | 段落單元 | 2,779 |
| `chunks` | 分塊 | 431 |
| `entities` | 實體（六型：人物/地名/群體/事件/物件/主題） | 9,122 |
| `entity_mentions` | 實體提及 | 173,768 |

### Qdrant (向量資料庫)

| Collection | Points | 向量 | 用途 |
|------------|--------|------|------|
| `bible_embeddings` | 34,072 | dense 1024 維（BGE-M3） | 純語意檢索 |
| `bible_embeddings_hybrid` | 34,072 | dense + sparse（BM25） | 混合檢索（RRF），預設啟用 |
| `bible_entities` | 9,122 | dense 1024 維 | entity_query 實體檢索 |

> 34,072 points = pericope（2,610）+ chunk（431）+ verse（31,031）三粒度混合索引。

### Neo4j (知識圖譜)

- 節點：13,589（Person, Place, Event, Theme, Object, Group, Pericope, Chunk, Chapter, Book）
- 關係：319,988（CROSS_REFERENCES 250,418 · MENTIONS 46,205 · 語意關係邊 37 型 15,926 · CONTAINS/NEXT/NEXT_BOOK）

> 數字為 2026-07-06 live 快照（KG P0 修復 + TSK 串珠匯入後）。完整架構見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | 服務健康檢查 |
| `POST` | `/api/v1/query` | RAG 聖經查詢 |
| `GET` | `/api/v1/verse/{book_id}/{chapter}` | 章查詢（段落、篇題、卷分隔） |
| `GET` | `/api/v1/verse/{book_id}/{chapter}/{verse}` | 經文查詢（合併節回整個 unit；缺號槽回「本譯本此節從缺」加註腳） |
| `GET` | `/api/v1/entity/{id}` | 已退役，回 410（D-08） |
| `GET` | `/docs` | Swagger UI |

### Query Request

```json
{
  "question": "保羅在大馬色路上遇到了什麼事？",
  "top_k": 5,
  "include_sources": true,
  "include_context": false
}
```

`include_context=true` 時每個 source 多回 `context` 欄位:交給生成器的完整區塊(`[i] 書卷 第N章 - 標題 (節)` + 經文),供評估端 judge 使用;預設 false、不影響既有欄位。

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
      "score": 0.92,
      "strategy": "graph_event",
      "rerank_score": 0.88,
      "context": null
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
| `BACKEND_UV_CACHE_DIR` | backend 映像檔建置時掛載的 uv 快取目錄（Docker 建置用，需存在） | `~/.cache/uv-bible-rag-backend` |
| `RAG_ENV` | backend 讀 `rag_meta.serving` 的哪一列（`prod`／`staging`） | `prod` |
| `RAG_BUILD_ID` | 預期服務的 build；必須等於 `rag_meta.serving` 該 env 指定的 build，不同就是握手不符（不能用來繞過 serving） | 無 |
| `STRICT_BUILD_CHECK` | 握手不符時啟動失敗；`false` 時仍啟動，但不服務資料，只在 `/api/v1/health` 回 503 | `true` |
| `CONTRACTS_ROOT` | 契約檔目錄的掛載點（compose 設為 `/contracts`）；未設時直接用 `rag_meta.builds.contracts_dir` | 無 |

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

- **RAGAS**：Faithfulness（zh 主讀數 + strict 守門，judge 看生成器同款含標頭 context）、Answer Relevancy、Context Recall、Answer Correctness
- **LLM Judge**：Answer Coverage（答案要點涵蓋率）
- **Retrieval**：Hit Rate、Recall@k、Precision@k、F1@k、MRR、MAP@k、NDCG@k
- **Semantic Similarity**：嵌入向量餘弦相似度

## Data Pipeline

從零重建的概略。順序與閘門以 [docs/build_database.md](docs/build_database.md)「執行順序」為準：各步的判準、指令前綴（`uv run --project scripts python`）與第 1 批 W1 的重灌鏈都在那裡，下面括號裡的 Step 是該文件的步驟編號。若從 [docs/staging_promotion.md](docs/staging_promotion.md) R0 的 `llm_artifacts.tgz` 還原了 LLM 產物，三個呼叫 LLM 的步驟都不必重跑：Step 1 在第 1 批期間改跑 `check_merged_inputs.py`，不要 merge（W1 的重灌鏈同樣以它取代 Step 1）；Step 6 沿用還原的 relations.jsonl；Step 7 改走 `--replay --fail-on-stale`。

```bash
# 1. 處理聖經 Markdown → JSON（Step 0）
python scripts/process_bible.py
python scripts/tools/check_step0.py         # sha 閘門，結束碼 0 才往下
python scripts/validate_output.py output    # 交叉引用閘門（第 1B 批起必跑），結束碼 0 才往下

# 2. 抽取實體 (人物/地名/事件)（Step 1，含 LLM，要跑數小時）
python scripts/extract_entities.py

# 3. 生成嵌入向量與 BM25 稀疏向量（Step 2 / 2.1）
python scripts/generate_embeddings.py
python scripts/generate_sparse_vectors.py

# 4. 匯入 PostgreSQL（Step 3）
python scripts/import_postgres.py

# 5. 匯入 Qdrant（dense 與 hybrid 兩個 collection；Step 4 / 4.1）
python scripts/import_qdrant.py
python scripts/import_qdrant_hybrid.py

# 6. 匯入 Neo4j 圖譜（Step 5，先清空再重建）
python scripts/import_neo4j.py

# 7. 關係抽取、後處理（Step 6.05，離線）與匯入（grounded RE；Step 6 / 6.05 / 6.1）
python -m scripts.relation_extraction.extract_relations
python -m scripts.relation_extraction.relation_postprocess
python scripts/import_relations_neo4j.py   # 只收 6.05 的 relations_clean.jsonl；圖裡已有語意邊就拒絕（第 6 步清庫後才是空的）

# 8. Entity 節點向量化，第一次（Step 8a，Qdrant bible_entities collection）
#    只為讓第 10 步有 collection 可寫，這時 P/P/G 的描述還是空的
python scripts/embed_entities.py --recreate

# 9. TSK 串珠交叉引用（Pericope 層 CROSS_REFERENCES；Step 9）
#    資料檔不進 git（output/ 被 ignore），fresh clone 需先自
#    https://github.com/scrollmapper/bible_databases 下載（openbible.info CC-BY）
python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt

# 10. KG 修復與 curated 資料重放（重建後必跑，Step 10.1–10.5，細節見 docs/build_database.md Step 10）
python scripts/backfill_aliases.py
python scripts/cleanup_noise_entities.py
# python scripts/backfill_event_relations.py --legacy-cooccurrence   # 10.3 已退出預設鏈，只供對照組與重現論文
python scripts/backfill_head_events.py
python scripts/backfill_manual_patches.py --apply

# 11. Entity 描述（Step 7，含 LLM；必須在 10.5 之後）與第二次向量化（Step 8b，用最終的描述重嵌）
python -m scripts.relation_extraction.desc_generator
python scripts/embed_entities.py --recreate

# 12. 品質閘門（Step 10.6；從零用 --target prod，在乾淨的 shell 跑，判準見 Step 10.6）與 registry 比對
python scripts/validate_kg.py --live --target prod
python scripts/check_identity.py --target prod --fail-on id
python scripts/export_event_registry.py --check   # 結束碼 0 才算建完
```

> 第 10 步不可省略：P0 與排序層修復的 curated 資料（字典 aliases、噪音清理、18 個頭部 Event 節點、106 條手動圖邊）不在 JSONL 產物中，缺了它們重建出的圖譜停在 P0 前狀態。P0 的共現關係升格（10.3，嚴格精確率約 0.2）已在第 1A 批退出預設鏈，不帶 `--legacy-cooccurrence` 會直接結束。唯一不需重放的是 `backfill_verse_mentions.py` — 其 verse→pericope remap 已內建於 `import_neo4j.py`。執行紀錄：[docs/records/2026-07-06_kg_p0_execution.md](docs/records/2026-07-06_kg_p0_execution.md)、[docs/records/2026-07-06_kg_fixes_execution.md](docs/records/2026-07-06_kg_fixes_execution.md)。

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
