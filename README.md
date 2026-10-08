# Bible RAG

繁體中文聖經問答系統。語料是 66 卷 PDF：和合本修訂版（RCUV）上帝版。PDF 版權頁寫「新標點和合本」，但內文是 RCUV。

所有資料都從 PDF 決定性地重建成版本化的 build，backend 只服務 `rag_meta.serving` 指定的 build。檢索以 BGE-M3 dense 檢索、cross-encoder 重排與 R1–R6 路由組合候選，再由 LLM 依檢索到的經文回答。

完整架構見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## Features

- **從 PDF 重建**：`ragdata` 建出 7 個內容定址的資料層（src、text、struct、emb、kg0、events、route），每層都要過閘門。同一個 commit 會建出同一個 `build_id`。
- **版本化服務**：一份 release 投影到三處：
  - PG schema `b{build_id}`；
  - Qdrant collection `passages__{build_id}`；
  - 契約目錄 `contracts/{build_id}/`。

  backend 啟動時與這三處做嚴格握手，不符就不服務。
- **節位模型**：合併節、缺號槽（「本譯本此節從缺」加註腳）、詩篇篇題、標題與註腳都是一級資料。
- **信號驅動路由**：R1–R6 加 fallback。路由詞表由 PDF 的名稱層、事件註冊表與查詢別名編出（R2）。
- **檢索**：BGE-M3 dense 檢索，bge-reranker-v2-m3 重排，排序融合 α=0.3，加 chapter 與 book_anchor 兩種 pin。
- **事件註冊表附加槽**：R4、R5 的問題命中事件觸發詞時，在 top-k 之後附加 1 段人工整理的事件錨點。
- **多 LLM**：Ollama、Claude、OpenAI、Gemini。
- **評估**：500 題五類型題庫（GT v1／v2），每份結果記錄 build、GT 版本與編碼指紋。

服務端不使用 Neo4j，也沒有 sparse／hybrid 檢索；知識圖譜只到 L0 名稱與 L1 事件（見 [ARCHITECTURE §7](docs/ARCHITECTURE.md#7-kg-的範圍)）。

## Architecture

```
資料（離線，ragdata）
bible_pdf/ ─→ src → text → struct → emb
                       └→ kg0、events → route
           ─→ release（releases/{build_id}.json）
           ─→ loader ─→ PG schema b{build_id}
                     ├→ Qdrant passages__{build_id}
                     └→ contracts/{build_id}/
rag_meta.serving（env → build_id, 映像）─→ backend 啟動時讀取並握手

查詢（線上，backend）
使用者查詢
    ├─ 1. 經文引用偵測（ragcommon.refs）
    ├─ 2. 意圖分類（LLM）
    ▼
信號偵測（契約的路由詞表）
    ├─ 書＋章＋節            → R1: PG 直查，不重排
    ├─ 書＋章，且點名多卷     → R5
    ├─ 書＋章                → R2: 該章段落 ＋ dense
    ├─ 多卷或 cross_reference → R5: dense ＋ 章段落 ＋ book_anchor ＋ SQL 補充
    ├─ 兩個以上人物          → R3: dense ＋ book_anchor ＋ SQL 補充
    ├─ 事件觸發詞            → R4: 同 R3 ＋ 事件附加槽
    ├─ 地名                  → R6: 同 R3
    └─ （無）                → fallback: dense ＋ book_anchor
    ▼
去重 → BGE Reranker → 排序融合 → pins → top-k →（R4/R5）事件附加槽 → LLM 生成
```

## Tech Stack

| 元件 | 技術 |
|------|------|
| Backend | FastAPI + uvicorn |
| 資料管線 | `ragdata`（共用程式 `packages/ragcommon`） |
| 結構化資料 | PostgreSQL 15（pgvector 映像） |
| 向量搜尋 | Qdrant v1.13.2（dense） |
| 嵌入模型 | BAAI/bge-m3（1024 維） |
| 重排序 | BAAI/bge-reranker-v2-m3 |
| 生成模型 | Ollama（現役 gemma4:e4b-it-q8_0）／Claude／OpenAI／Gemini |
| 套件管理 | uv（`backend/`、`scripts/`、`evaluation/` 各一套） |
| 容器化 | Docker Compose |

## Prerequisites

- Docker 與 Docker Compose。compose 的 `ollama` 服務要用 NVIDIA GPU。
- 一個已載入並 promote 的 build：
  - store（`RAG_STORE`，預設 `/mnt/ollama-data/bible_rag_store`）有 `contracts/{build_id}/`；
  - PG 與 Qdrant 有該 build 的資料；
  - `rag_meta.serving` 有該 env 的列。

  建法見下方 [Data Pipeline](#data-pipeline)。
- Python 3.11 以上與 [uv](https://github.com/astral-sh/uv)：只有開發、建資料與評估需要。

## Quick Start

### 1. 複製環境設定

```bash
cp .env.example .env
```

依需求編輯 `.env`，設定 LLM provider 與 API key。`.env.example` 仍留著舊管線的鍵（`NEO4J_*`、`HYBRID_*`、`ENTITY_EXTRACT_*`、`RE_*`、`DESC_*` 等），backend 不讀它們。

### 2. 建資料並指定服務的 build

照 [docs/rebuild_pipeline.md](docs/rebuild_pipeline.md) 跑 `pipeline run --load --verify`，再用 `promote` 寫入 `rag_meta.serving`。

### 3. 啟動服務

```bash
mkdir -p ~/.cache/uv-bible-rag-backend   # backend 建置用的 uv 快取目錄，必須存在
docker compose up -d
```

> **Docker 建置快取**：backend 映像的 `uv sync` 會掛載主機目錄 `~/.cache/uv-bible-rag-backend` 當 uv 快取（可用 `BACKEND_UV_CACHE_DIR` 改路徑）。有快取時，torch 與 CUDA 套件（約 4 GB）不會重新下載。
> - 目錄是空的也能建置，只是要全部重抓。
> - 快取由 uv 0.12.0 寫入，Dockerfile 釘住同一版 uv。
> - 映像本身不含快取。
>
> 已有舊映像時，可以先從映像匯出快取：
>
> ```bash
> cid=$(docker create <任何含 /root/.cache/uv 的舊 backend 映像>)
> docker cp "$cid:/root/.cache/uv" ~/.cache/uv-bible-rag-backend && docker rm "$cid"
> ```

此指令啟動：

| 服務 | 埠 | 說明 |
|---|---|---|
| backend | 8000 | FastAPI；契約目錄由 `${RAG_STORE}/contracts` 唯讀掛到 `/contracts` |
| postgres | 5432 | PostgreSQL 15（pgvector 映像） |
| qdrant | 6333／6334 | 向量資料庫 |
| ollama | 11434 | 本地 LLM（GPU） |

compose 裡的 `neo4j` 只在 `--profile kg` 時啟動，只供回滾到 legacy；backend 不讀 Neo4j。

**backend 怎麼選 build**：
- 啟動時依 `RAG_ENV`（prod／staging）讀一次 `rag_meta.serving`。`RAG_BUILD_ID` 只能核對，不能改選。
- 從 `rag_meta.builds` 取得該 build 的 PG schema、Qdrant collection 與契約目錄，然後握手。
- 任一項不符時，`/api/v1/health` 回 503 並列出不符項。`STRICT_BUILD_CHECK=true`（預設）時啟動失敗。

使用本地 LLM 時，在 ollama 服務拉好 `.env` 的 `OLLAMA_MODEL`：

```bash
docker exec ollama ollama pull gemma4:e4b-it-q8_0
```

### 4. 確認服務健康

```bash
curl http://localhost:8000/api/v1/health
```

回應含服務狀態、編碼指紋，以及握手結果：服務的 `build_id`，或不符項清單。

### 5. 查詢測試

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "根據約翰福音3:16，上帝如何表達祂對世人的愛？"}'
```

## Project Structure

```
Bible_RAG/
├── backend/                    # FastAPI 後端（服務 rag_meta.serving 指定的 build）
│   ├── main.py                 # 應用程式入口與 lifespan（啟動時握手）
│   ├── config.py               # pydantic-settings 設定
│   ├── serving/                # build 選擇、契約檔驗證、握手
│   ├── routers/                # query、verse、health；entity 回 410
│   ├── database/               # PG（search_path = b{build_id}）、Qdrant、節單位組裝
│   └── utils/
│       ├── signal_detector.py  # 路由信號（契約的路由詞表）與決策樹
│       ├── intent_classifier.py# LLM 意圖分類
│       ├── verse_parser.py     # 經文引用解析（ragcommon.refs）
│       ├── embedder.py         # BGE-M3 查詢編碼
│       ├── reranker.py         # BGE Reranker v2
│       ├── generator.py        # LLM 回答生成
│       ├── llm/                # 多 LLM provider
│       └── retrieval/          # 路由、dense、經文直查、融合與 pin、事件附加槽
├── ragdata/                    # 資料管線：契約、閘門、各層建置、GT v2、release、loader、promote
├── packages/ragcommon/         # 共用程式：ids、books、refs、versification、encoder、routing
├── bible_pdf/                  # 66 卷 PDF（唯一的語料來源）
├── config/
│   ├── registries/             # 人工註冊表：errata、versification、正規化、divine_refs、events、query_aliases…
│   └── gold/                   # GT v2 的人工判斷、變更紀錄與凍結檔
├── scripts/                    # ragdata 的執行環境（pyproject.toml、uv.lock）與 derive_ragcommon_data.py
├── evaluation/                 # 評估框架（見 evaluation/README.md）
├── docs/                       # 文件（地圖：docs/README.md）
├── paper/                      # 論文資產
├── figures/                    # 論文圖
├── ground_truth.json           # GT v1：500 題（5 類型 × 100）
├── ground_truth.v2.json        # GT v2：同 500 題，引用對齊重建後的文字層
├── docker-compose.yml          # backend、postgres、qdrant、ollama（neo4j 只在 --profile kg）
├── docker-compose.staging.yml  # staging backend（R1：:8002）
├── Dockerfile                  # backend 映像
└── .env.example                # 環境變數範例
```

## Data

一個 build 的資料分在三處，名稱都帶 `build_id`。下表數字出自 R1 build `b20261008_6daa4f31`。R2 build `b20261008_e05d3e55` 除了事件與路由詞，其餘都相同。

| 項目 | 數量 |
|---|---|
| 書／章 | 66／1,189 |
| 節單位（unit） | 31,021，其中 70 個合併節 |
| 節位（slot） | 31,103，其中 11 個缺號槽 |
| 詩篇篇題／標題／註腳 | 116／2,603／1,013 |
| pericope／passage／chunk | 2,610／2,773／433 |
| 嵌入記錄（＝ Qdrant 點數） | 34,058（verse 31,021、passage 2,604、chunk 433） |
| 名稱（kg0） | 2,926 |
| 事件 | R1 33；R2 31 |
| 路由詞 | R1 348（legacy 凍結詞表）；R2 3,298 |

- **PostgreSQL**：schema `b{build_id}`（例如 `bb20261008_e05d3e55`），19 張表；`rag_meta` schema 有 `builds`、`serving`、`serving_history`。
- **Qdrant**：collection `passages__{build_id}`，dense 1024 維，payload 帶 kind、passage_id、pericope_id、start_key／end_key。
- **契約**：`contracts/{build_id}/` 放路由詞表、查詢別名、事件註冊表、編碼指紋、書卷表、verse_index 等，附逐檔 sha256 的 `manifest.json`。

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | 服務健康、編碼指紋與握手結果（不符回 503） |
| `POST` | `/api/v1/query` | RAG 聖經查詢 |
| `GET` | `/api/v1/verse/{book_id}/{chapter}` | 章查詢（段落、篇題、卷分隔） |
| `GET` | `/api/v1/verse/{book_id}/{chapter}/{verse}` | 經文查詢（合併節回整個 unit；缺號槽回「本譯本此節從缺」加註腳） |
| `GET` | `/api/v1/entity/{id}` | 已退役，回 410（D-08） |
| `GET` | `/docs` | Swagger UI |

### Query Request

```json
{
  "question": "保羅歸主的經過為何？",
  "top_k": 5,
  "include_sources": true,
  "include_context": false
}
```

選用欄位：

| 欄位 | 用途 |
|---|---|
| `include_context` | 每個 source 附上交給生成器的區塊（`[i] 書卷 第N章 - 標題 (節)` 加經文），供評估端 judge 使用 |
| `retrieval_only` | 只跑檢索與重排，不生成 |
| `semantic_only` | 只走 dense 基線，不經路由 |
| `use_graph` | 只控制事件附加槽，覆寫設定 |
| `graph_strategies` | `["event_registry"]` 或 `[]`，覆寫設定 |
| `fusion_alpha` | 覆寫融合 α，0 表示純 reranker 排序 |

### Query Response

下例只示意欄位，數值不是實際輸出。

```json
{
  "answer": "根據使徒行傳第9章……",
  "sources": [
    {
      "id": "ps:act.9.1",
      "kind": "passage",
      "book": "使徒行傳",
      "chapter": 9,
      "title": "掃羅的轉變",
      "verse_range": "1-19",
      "start_key": "act.9.1",
      "end_key": "act.9.19",
      "passage_id": "ps:act.9.1",
      "score": 0.83,
      "rerank_score": 0.79,
      "strategy": "hybrid_hybrid",
      "found_by": ["hybrid_hybrid"],
      "build_id": "b20261008_e05d3e55",
      "context": null
    }
  ],
  "intent": {"type": "event", "entities": ["保羅"], "verse_refs": [], "rejected_refs": []},
  "retrieval_stats": {
    "route_used": "R4",
    "strategies_used": ["semantic", "sql_supplement"],
    "total_candidates": 18,
    "reranked_top_k": 5,
    "graph_strategies": ["event_registry"],
    "fusion_alpha": 0.3,
    "event_registry_events": ["ev0002"]
  }
}
```

- `id` 依 `ragcommon.ids` 的文法：`ps:` 是 passage，`ck:` 是 chunk，`vs:` 是 verse 記錄，`vr:` 是節範圍。
- 事件附加槽附加的段落 `strategy` 是 `event_registry`，沒有分數。

## Configuration

設定都在 `.env`，backend 讀的鍵如下；預設值取自 `backend/config.py`。

### build 與握手

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `RAG_ENV` | 讀 `rag_meta.serving` 的哪一列（`prod`／`staging`） | `prod` |
| `RAG_BUILD_ID` | 預期服務的 build；必須等於 serving 指定的 build，否則握手不符 | 無 |
| `STRICT_BUILD_CHECK` | 握手不符時啟動失敗；`false` 時仍啟動，但不服務資料，只在 health 回 503 | `true` |
| `CONTRACTS_ROOT` | 契約目錄的掛載點（compose 設為 `/contracts`）；未設時用 `rag_meta.builds.contracts_dir` | 無 |
| `RAG_STORE` | compose 掛載契約目錄的來源（store 根目錄） | `/mnt/ollama-data/bible_rag_store` |

### LLM

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `LLM_PROVIDER` | `ollama`／`claude`／`openai`／`gemini` | `ollama` |
| `OLLAMA_BASE_URL` | Ollama 位址（compose 覆寫為 `http://ollama:11434`） | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama 模型（`.env.example` 為 `gemma4:e4b-it-q8_0`） | `gemma3:4b` |
| `ANTHROPIC_API_KEY`／`CLAUDE_MODEL` | Claude | —／`claude-haiku-4-5` |
| `OPENAI_API_KEY`／`OPENAI_MODEL` | OpenAI | —／`gpt-4o-mini` |
| `GOOGLE_API_KEY`／`GEMINI_MODEL` | Gemini | —／`gemini-2.0-flash` |
| `LLM_MAX_TOKENS` | 回應最大 token 數 | `100000` |
| `LLM_TEMPERATURE` | 生成溫度 | `0.1` |

### 檢索

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `RAG_USE_GRAPH` | 事件附加槽總開關（可逐請求以 `use_graph` 覆寫） | `true` |
| `RAG_GRAPH_STRATEGIES` | JSON 陣列：`["event_registry"]` 或 `[]` | `["event_registry"]` |
| `RAG_EVENT_REGISTRY_SLOTS` | 附加槽最多附加幾段 | `1` |
| `RAG_RANK_FUSION_ENABLED`／`RAG_RANK_FUSION_ALPHA` | 排序融合 | `true`／`0.3` |

### 資料庫與部署

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `POSTGRES_HOST`／`POSTGRES_PORT`／`POSTGRES_DB` | PostgreSQL（compose 把 host 覆寫為 `postgres`） | `localhost`／`5432`／`bible_rag` |
| `POSTGRES_USER`／`POSTGRES_PASSWORD` | PostgreSQL 帳密 | `bible`／`bible_password` |
| `QDRANT_HOST`／`QDRANT_HTTP_PORT`／`QDRANT_GRPC_PORT` | Qdrant（compose 把 host 覆寫為 `qdrant`） | `localhost`／`6333`／`6334` |
| `BACKEND_PORT` | backend 對外埠 | `8000` |
| `BACKEND_UV_CACHE_DIR` | 建置 backend 映像時掛載的 uv 快取目錄（需存在） | `~/.cache/uv-bible-rag-backend` |

## Database Access

### PostgreSQL

```bash
docker exec -it bible_rag_postgres psql -U bible -d bible_rag
```

```sql
-- 各 env 正在服務的 build 與登記過的 build
SELECT * FROM rag_meta.serving;
SELECT build_id, pg_schema, qdrant_collection, points FROM rag_meta.builds;

-- 查某個 build 的資料
SET search_path = bb20261008_e05d3e55;
SELECT pericope_id, book_id, start, "end" FROM pericopes LIMIT 10;
SELECT slot_key, status, unit_key FROM verse_slots WHERE status = 'omitted_variant';
```

本機工具（pgAdmin、DBeaver）連 `localhost:5432`，資料庫 `bible_rag`，帳密 `bible`／`bible_password`。

### Qdrant

```bash
curl http://localhost:6333/collections
curl http://localhost:6333/collections/passages__b20261008_e05d3e55
```

Dashboard：`http://localhost:6333/dashboard`。

### FastAPI Swagger UI

`http://localhost:8000/docs`

## Evaluation

題庫 500 題，5 類各 100 題：

| 類型 | 範例 |
|------|------|
| VERSE_LOOKUP | 根據約翰福音 3:16，神如何表達祂對世人的愛？ |
| TOPIC_QUESTION | 聖經中如何定義「信心」？ |
| PERSON_QUESTION | 摩西與葉忒羅的關係如何？ |
| EVENT_QUESTION | 出埃及過程中經歷了哪些神蹟？ |
| GENERAL_BIBLE_QUESTION | 新約福音書的寫作背景為何？ |

- **GT v1**（`ground_truth.json`）：原本的 100 題標 family `legacy_head`，2026-07-11 擴充到 500 題。不再改動。
- **GT v2**（`ground_truth.v2.json`）：同樣 500 題，引用對齊重建後的文字層（`gold_slots`），凍結在 `config/gold/gt_v2_freeze.json`。新 build 只能用 GT v2 評估。

```bash
cd evaluation
uv run python quick_retrieval_eval.py --gt v2 --label <名稱>   # 只跑檢索（不生成）
uv run python run_eval.py --gt v2                              # 收集 → 評估 → 視覺化
```

- `BACKEND_URL` 等評估專屬設定放在 `evaluation/.env`（範本 `evaluation/.env.example`）。
- 每份結果的 meta 都記 `data_build_id`、`gt_version`、`gt_sha` 與編碼指紋。
- 指標、閘門與預登記見 [evaluation/README.md](evaluation/README.md)。
- 論文的 Rounds 0–3 是在 legacy 資料、GT v1 與有 bug 的查詢端 tokenizer 下產生的，不能和新 build 的結果直接比較（[ARCHITECTURE §10](docs/ARCHITECTURE.md#10-舊結果的適用範圍)）。

## Data Pipeline

資料管線的唯一入口文件是 [docs/rebuild_pipeline.md](docs/rebuild_pipeline.md)：前置環境、各層閘門、推導檔、promote 與回滾、unload、測試指令都在那裡。

一個指令從 PDF 建到驗證完成：

```bash
export HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
env PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python -m ragdata \
  pipeline run --load --verify --report pipeline.json
```

之後用 `ragdata promote --env <prod|staging> --build <build_id> --image <digest>` 指定服務的 build，再重啟 backend。

## Development

```bash
# 後端依賴與本地啟動（需先有 PostgreSQL、Qdrant 與已 promote 的 build）
cd backend && uv sync
uv run uvicorn main:app --reload --port 8000

# 評估依賴
cd evaluation && uv sync
```

四套測試的指令見 [docs/rebuild_pipeline.md](docs/rebuild_pipeline.md) §8。

## License

MIT
