# 聖經知識型 RAG 系統規格說明書（spec.md）

## 1. 文件資訊

### 1.1 版本資訊

* 版本：v0.1
* 日期：2025-12-13
* 作者：個人 Side Project

### 1.2 目的

本文件定義一套以「新標點和合本聖經 PDF」為唯一資料來源的知識型 RAG（Retrieval-Augmented Generation）系統之技術規格。系統目標為：

* 讓使用者透過自然語言詢問問題，獲得基於聖經文本的解釋與教導，而不僅是單純查詢經文。
* 利用向量檢索與知識圖譜（Neo4j）將聖經中人物、事件、主題之間的關係可視化。
* 滿足本地部署需求，模型推論由本機 Ollama 完成。

### 1.3 範圍

* 前端：React + TypeScript + Vite SPA，與後端透過 REST API 溝通。
* 後端：Python（FastAPI）為主，負責 API、RAG pipeline、索引建立。
* 資料儲存：PostgreSQL + pgvector（向量檢索）與 Neo4j（知識圖譜）。
* 嵌入與 LLM：FlagEmbedding / transformers（bge-m3 embeddings）與 Ollama（本地 LLM）。
* 系統部署規模以單人 Side Project 管理維運為前提。

### 1.4 名詞定義

* **RAG**：Retrieval-Augmented Generation，以檢索增強生成式模型之架構。
* **Pericope（段落單元）**：由聖經書卷中的小標題界定的一段經文，通常對應一個情節或教導單元。
* **RRF**：Reciprocal Rank Fusion，多檢索器結果融合方法。
* **KG**：Knowledge Graph（知識圖譜）。

---

## 2. 系統目標與非目標

### 2.1 系統目標

1. 支援使用者以繁體中文自然語言提問，系統能回應：

   * 聖經相關知識解釋（人物、事件、教義、主題）。
   * 核心相關經文節選與引用位置。
   * 與問題相關的跨卷書、跨時代經文關聯。

2. 提供視覺化探索功能：

   * 人物關係圖（Person–Person）。
   * 主題與書卷的分布熱力圖。
   * 聖經內部交叉參照、預言與應驗的圖形化連結。

3. 支援本地 LLM 推論：

   * 所有 LLM 生成均透過本機 Ollama 完成，確保資料不離開本機。

4. 提供穩定、可維護的後端 API 介面，方便前端與後續擴充。

### 2.2 非目標

1. 不處理多版本聖經對照（僅單一 PDF 版本）。
2. 不提供多人協作、帳號系統與權限管理（視為單機使用）。
3. 不實作完整靈修或課程管理平台（僅專注於查詢與探索）。
4. 不追求大規模並發或高可用部署（單人、單機規模即可）。

---

## 3. 使用者與用例

### 3.1 目標使用者

* 對聖經有興趣的一般讀者。
* 需要快速查詢主題與經文關聯的查經者。
* 想從人物、事件、主題等角度系統性理解聖經內容的研究者。

### 3.2 典型用例

1. **主題查詢**：

   * 問題：「聖經怎麼談饒恕？」
   * 系統：回應短摘要，列出多處關鍵經文，並展示關聯主題與書卷分布。

2. **人物查詢**：

   * 問題：「請介紹亞伯拉罕的一生。」
   * 系統：給出人物生平概述、主要事件 timeline、相關經文列表及人物關係圖。

3. **事件查詢**：

   * 問題：「出埃及事件的主要過程為何？」
   * 系統：輸出事件分段描述與主要經文，並在地圖或時間軸上標示。

4. **經文解析**：

   * 問題：「雅各書 2 章講的信心與行為關係是什麼？」
   * 系統：提供經文段落與上下文，並說明主題與相關書卷（如羅馬書）的對照。

---

## 4. 高階架構

### 4.1 系統組件

* **前端 Web 客戶端**：

  * React + TypeScript + Vite
  * TanStack Query（資料抓取與快取）
  * Zustand（全域 UI 狀態管理）

* **後端 API 服務**：

  * Python + FastAPI
  * RAG pipeline（檢索、RRF、context 建構、LLM 生成）
  * 索引建立與 PDF 解析工具

* **資料儲存層**：

  * PostgreSQL（結構化資料 + full-text search）
  * pgvector extension（向量儲存與檢索）
  * Neo4j（Bible Knowledge Graph）

* **模型層**：

  * Ollama（本地 LLM 推論，如 `llama3` / `qwen` 等）
  * FlagEmbedding / transformers（bge-m3 embeddings）

### 4.2 架構圖

```mermaid
flowchart LR
  subgraph Client[Client]
    UI[React + TS + Vite\nTanStack Query + Zustand]
  end

  subgraph Server[Backend]
    API[FastAPI REST API]
    PIPE[RAG Pipeline\n(Query Routing / RRF / Context Builder)]
    INGEST[Ingestion & Indexer CLI]
  end

  subgraph DB[Storage]
    PG[(PostgreSQL\n+ pgvector)]
    NEO[(Neo4j\nKnowledge Graph)]
  end

  subgraph Models[Local Models]
    OLLAMA[Ollama LLM]
    EMBED[FlagEmbedding\n(bge-m3)]
  end

  UI <--> API
  API --> PIPE
  API --> PG
  API --> NEO
  PIPE --> PG
  PIPE --> NEO
  PIPE --> OLLAMA
  PIPE --> EMBED
  INGEST --> PG
  INGEST --> NEO
  INGEST --> EMBED
```

---

## 5. 技術棧與元件選型

### 5.1 前端

* 框架：React 18 + TypeScript + Vite
* 狀態管理：

  * TanStack Query：處理 API 請求、快取、錯誤邏輯。
  * Zustand：儲存 UI 狀態（目前查詢、選中節點、視圖設定）。
* UI：

  * 可選 Tailwind CSS + Headless UI 或 Chakra UI（開源 UI 套件）；
  * 視覺化圖表可用 Recharts / D3.js / vis-network（人物關係、KG 視圖）。

### 5.2 後端

* 語言與框架：Python 3.11+、FastAPI
* 伺服器：Uvicorn / Gunicorn（本地開發直接使用 Uvicorn 即可）。
* 背景批次：

  * 以 CLI / 管線腳本為主（單人 side project 無需完整任務佇列）。

### 5.3 模型與 NLP

* LLM 推論：

  * Ollama（本地安裝），預設支持如 `llama3`, `qwen2` 等開源模型。
  * 後端透過 HTTP（`/api/chat` 或 `/api/generate`）與 Ollama 溝通。

* Embeddings：

  * FlagEmbedding 套件，使用 `BAAI/bge-m3` 模型。
  * 替代方案：Hugging Face transformers 直接載入 `BAAI/bge-m3`，但 FlagEmbedding 對該模型支援較完整。

### 5.4 資料儲存

* PostgreSQL：

  * 儲存書卷、章、節、段落、主題、查詢 log 等結構化資料。
  * 利用 PostgreSQL full-text search 作為 BM25 類型之稀疏檢索。

* pgvector：

  * 於 PostgreSQL 中安裝 extension，儲存 bge-m3 向量。
  * 支援 inner product / cosine distance / L2 distance 查詢。

* Neo4j：

  * 儲存 Bible Knowledge Graph：

    * Node：Book, Chapter, Pericope, Verse, Person, Place, Group, Event, Topic。
    * Relationship：CONTAINS, MENTIONS, PART_OF, RELATED_TO, QUOTES, PROPHECY_FULFILLED_IN 等。

### 5.5 部署與開發環境

* Docker + Docker Compose：

  * 服務：`frontend`, `backend`, `postgres`, `neo4j`, `ollama`（視需要可分別啟動）。
* 開發工具：

  * VS Code / JetBrains IDE。
  * `make` 或 `taskfile` 管理常用指令（啟動、初始化、索引）。

---

## 6. 資料模型設計

### 6.1 PostgreSQL Schema（關聯式資料）

#### 6.1.1 `books` 表

* `id` (PK, serial)
* `name_zh` (text)：中文書名（例：創世記）。
* `abbrev_zh` (text)：縮寫（例：創）。
* `testament` (enum: `OT`, `NT`)
* `order_index` (int)：正典順序。

#### 6.1.2 `chapters` 表

* `id` (PK)
* `book_id` (FK -> books.id)
* `number` (int)：章號。

#### 6.1.3 `pericopes` 表（段落）

* `id` (PK)
* `book_id` (FK)
* `chapter_start` (int)
* `verse_start` (int)
* `chapter_end` (int)
* `verse_end` (int)
* `title` (text)：段落標題。
* `summary` (text)：段落摘要（由 LLM 產生）。
* `embedding` (vector)：bge-m3 embedding。

#### 6.1.4 `verses` 表（經文節）

* `id` (PK)
* `book_id` (FK)
* `chapter` (int)
* `verse` (int)
* `text` (text)
* `pericope_id` (FK -> pericopes.id)
* `tsv` (tsvector)：用於 full-text search。

#### 6.1.5 `topics` 表（主題與概念）

* `id` (PK)
* `name` (text)：主題名稱（例：饒恕、信心、恩典）。
* `type` (enum: `DOCTRINE`, `MORAL`, `HISTORICAL`, `OTHER`)
* `description` (text, nullable)

#### 6.1.6 `verse_topics` 表（經文與主題關聯）

* `verse_id` (FK -> verses.id)
* `topic_id` (FK -> topics.id)
* `weight` (float)：關聯強度（0~1）。
* PK：複合鍵 (`verse_id`, `topic_id`)

#### 6.1.7 `entities` 表（可選，與 Neo4j 重疊但方便查詢）

* `id` (PK)
* `name` (text)
* `type` (enum: `PERSON`, `PLACE`, `GROUP`, `EVENT`)

#### 6.1.8 `verse_entities` 表

* `verse_id` (FK)
* `entity_id` (FK)
* `role` (text, nullable)：例如主角、配角、地點。

#### 6.1.9 `query_logs` 表（可選）

* `id` (PK)
* `created_at` (timestamp)
* `query_text` (text)
* `classified_type` (text)：主題查詢 / 人物查詢 / 事件查詢等。

### 6.2 pgvector 設計

* 使用 `vector` 型別存儲 bge-m3 向量（長度以模型維度為準，如 1024）。
* 主要用於：

  * `pericopes.embedding`
  * 可選：`verses.embedding`（若需要更細粒度向量）。
* 索引：

  * 建立 `ivfflat` 或 `hnsw`（視 pgvector 版本）索引，以 inner product 或 cosine 相似度進行近似最近鄰檢索。

### 6.3 Neo4j Schema（知識圖譜）

#### 6.3.1 Node Labels

* `Book {id, name_zh, order_index}`
* `Chapter {number}`
* `Pericope {id, title}`
* `Verse {id, book_id, chapter, verse}`
* `Person {name}`
* `Place {name}`
* `Group {name}`
* `Event {name}`
* `Topic {name, type}`

#### 6.3.2 Relationships

* 結構：

  * `(Book)-[:HAS_CHAPTER]->(Chapter)`
  * `(Chapter)-[:HAS_PERICOPE]->(Pericope)`
  * `(Pericope)-[:HAS_VERSE]->(Verse)`

* 實體關聯：

  * `(Verse)-[:MENTIONS_PERSON]->(Person)`
  * `(Verse)-[:MENTIONS_PLACE]->(Place)`
  * `(Verse)-[:MENTIONS_EVENT]->(Event)`
  * `(Verse)-[:MENTIONS_TOPIC]->(Topic)`

* 聖經特有連結：

  * `(Verse)-[:QUOTES]->(Verse)`
  * `(Verse)-[:ALLUDES_TO]->(Verse)`
  * `(Verse)-[:PROPHECY_FULFILLED_IN]->(Verse)`
  * `(Pericope)-[:PARALLEL_WITH]->(Pericope)`（福音書平行經文）

* 主題關聯：

  * `(Topic)-[:RELATED_TO]->(Topic)`

---

## 7. 檢索與 RAG 流程設計

### 7.1 查詢前處理

1. 接收前端查詢請求（JSON）：

   * `query`: 使用者自然語言問題（繁體中文）。
   * `mode`: 可選，如 `auto` / `verse_lookup` / `topic` / `person`（前端可允許使用者指定）。

2. 前處理步驟：

   * 正規化（去除多餘空白、標點簡化）。
   * 偵測是否為明確經文查詢（regex: 書名 + 章:節）。
   * 使用小型 LLM prompt（經由 Ollama）進行查詢分類：

     * 類型：`VERSE_LOOKUP`, `TOPIC_QUESTION`, `PERSON_QUESTION`, `EVENT_QUESTION`, `GENERAL_BIBLE_QUESTION`。

### 7.2 檢索子系統

#### 7.2.1 稀疏檢索（PostgreSQL full-text）

* 對 `verses.tsv` 進行全文索引。
* 查詢方式：

  * 將使用者 query 轉為 `plainto_tsquery`（或自訂字典）。
  * 回傳前 N 節經文，包含：`verse_id`, `rank`。

#### 7.2.2 稠密檢索（pgvector + bge-m3）

* 將 query 以 bge-m3 轉為 embedding。
* 在 `pericopes.embedding` 上進行近似最近鄰檢索：

  * 以 inner product / cosine 相似度排序。
  * 回傳前 N 個 pericope，包含 `pericope_id`, `distance`。

#### 7.2.3 圖檢索（Neo4j）

* 根據查詢類型執行不同的 Cypher：

  * 人物查詢：先用 LLM 解析出姓名 → 找 `(p:Person {name: $name})` → 擴展 1~2 跳取得相關 `Verse` / `Pericope`。
  * 主題查詢：由 LLM 將問題 map 至一組 `Topic` 節點 → 取得關聯 `Verse` / `Pericope`。
  * 事件查詢：類似人物，但聚焦 `Event` 節點。
* 將圖檢索結果轉為候選 `pericope_id` 或 `verse_id` 列表，附加一個基礎分數（例如依 hop 數給分）。

### 7.3 RRF（Reciprocal Rank Fusion）

使用 RRF 將三種檢索結果融合，提升整體召回與準確度。

假設有三個檢索器：

* `L1`: 稀疏檢索（verses → 再映射至 pericopes）
* `L2`: 稠密檢索（pericopes）
* `L3`: 圖檢索（pericopes）

對於每個候選文件 d，其最終分數定義為：

[ score(d) = \sum_{i} \frac{1}{k + rank_i(d)} ]

* `rank_i(d)`: 文件 d 在第 i 個檢索結果中的排名（從 1 開始）。
* `k`: 平滑常數，建議 `k = 60`（可於設定檔中調整）。

實作方式：

* 將三個結果列表轉為 `{doc_id -> rank}` map。
* 依公式計算分數，排序取前 K 個 pericope 作為最終候選。

### 7.4 Context 構建

1. 對於前 K 個 pericope：

   * 取得 pericope 內所有 verses。
   * 視 context 長度，可能只截取與 query 最相關的 verse 子集。

2. Context 打包策略：

   * 將每個 pericope 包成一個 block：

     * 段落標題
     * 書卷+章節範圍
     * 節文內容
   * 控制總 token 不超過 LLM 上限（例如 4k tokens）：

     * 優先保留高分 pericope。

### 7.5 回答生成

1. System Prompt 設計：

   * 指示 LLM：

     * 僅使用提供的聖經段落作為主要依據。
     * 回答以繁體中文輸出。
     * 清楚標出引用經文的卷章節。
     * 避免給出與聖經無關的個人意見。

2. User Prompt：

   * 放入原始使用者問題。

3. Context（檢索結果）：

   * 以結構化格式（如 markdown）提供給 LLM。

4. LLM 輸出：

   * 回答摘要（1~3 段）。
   * 相關經文列表（可供前端呈現為可點擊引用）。
   * 若為人物或事件問題，可要求生成 timeline / 列表型輸出。

---

## 8. 前端應用設計

### 8.1 主要畫面

1. **搜尋頁（Search View）**

   * 元件：

     * Query 輸入框。
     * 查詢類型選擇（自動 / 經文 / 主題 / 人物）。
     * 搜尋結果區域（RAG 回答 + 相關經文列表）。
   * 功能：

     * TanStack Query 呼叫 `/api/query`。
     * 顯示 LLM 回答、相關經文卡片（可展開上下文）。

2. **經文細節頁（Verse / Pericope Detail View）**

   * 顯示單一 pericope 或 verse 詳細內容。
   * 顯示該段落關聯人物、主題。

3. **圖譜視圖（Graph View）**

   * 人物關係圖：可選人名，顯示與其有關的人物與關係。
   * 主題–書卷熱力圖：矩陣式視圖。

4. **設定與索引狀態頁（Admin/Status View）**（可簡化為文字顯示）

   * 顯示索引建立狀態、資料量統計。

### 8.2 狀態管理（TanStack Query + Zustand）

* TanStack Query：

  * 查詢結果、經文細節、圖譜資料，皆以 Query Key 管理快取。

* Zustand Store：

  * `currentQuery`: 當前查詢文字。
  * `selectedView`: `search` / `graph` / `detail`。
  * `selectedEntity`: 當前選中人物或主題。
  * `uiPreferences`: 顯示語言、主題（light/dark）等。

### 8.3 與後端 API 介接

* `/api/query`：透過 TanStack Query 封裝，一般使用 `useQuery` 或 `useMutation`。
* `/api/verses/:id`、`/api/pericopes/:id`：用於細節視圖。
* `/api/graph/entity/:id`：載入圖譜資料，透過圖形視覺化元件呈現。

---

## 9. 後端 API 設計

### 9.1 REST API 概述

Base URL：`/api`

#### 9.1.1 `POST /api/query`

* 說明：

  * 主查詢端點，執行 RAG pipeline。
* Request Body（JSON）：

  * `query` (string, required)
  * `mode` (string, optional) – `auto` | `verse` | `topic` | `person` | `event`
* Response Body（JSON）：

  * `answer` (string)：LLM 生成回答（markdown）。
  * `segments` (array)：RAG 使用之 pericope/verse 資訊：

    * `id`, `book`, `chapter_start`, `verse_start`, `chapter_end`, `verse_end`, `text_excerpt`
  * `meta`：

    * `query_type`: 系統判定之類型
    * `used_retrievers`: `['bm25', 'dense', 'graph']`

#### 9.1.2 `GET /api/books`

* 回傳所有書卷資訊。

#### 9.1.3 `GET /api/pericopes/:id`

* 回傳某段落之詳細內容及關聯主題、人物。

#### 9.1.4 `GET /api/verses/:id`

* 回傳單一經文節詳細內容。

#### 9.1.5 `GET /api/graph/entity/:id`

* 說明：

  * 供前端圖譜視圖使用，拉取指定 entity（Person/Place/Topic/Event）周圍 1~2 跳的圖資料。
* Response：

  * `nodes`: 節點列表（id, type, label）。
  * `edges`: 關係列表（sourceId, targetId, type）。

#### 9.1.6 `POST /api/admin/reindex`（可選）

* 重新建立索引（僅限本機開發者使用，可透過環境變數保護）。

### 9.2 錯誤處理

* 所有錯誤皆回傳 JSON：

  * `error_code` (string)
  * `message` (string)
* 常見錯誤：

  * `INVALID_QUERY`
  * `LLM_FAILURE`
  * `RETRIEVAL_FAILURE`

---

## 10. PDF 解析與索引建置流程

### 10.1 PDF 解析

1. 工具：

   * `pdfplumber` 或 `PyMuPDF`（Python 開源套件）。

2. 流程：

   * 讀入 PDF 每頁文字。
   * 透過規則辨識：

     * 書卷標題行。
     * 章節起始行（如「第 X 章」或類似格式）。
     * 經文節號（如「1  起初，神創造天地。」中的「1」）。
     * 段落小標題（字體或排版特徵）。

3. 解析結果輸出為中介 JSON 結構：

   * `books[] -> chapters[] -> pericopes[] -> verses[]`。

### 10.2 實體與主題標註

1. 初始階段：

   * 以 LLM（Ollama）為主，針對 pericope 文本批次執行：

     * 抽取主要人物、人群、地點。
     * 標記主題（從預先定義之主題列表中選取）。

2. 將結果寫入：

   * PostgreSQL：`topics`, `verse_topics`, `entities`, `verse_entities`。
   * Neo4j：對應建立 Person, Place, Topic, Event 節點與關係。

### 10.3 Embedding 建置

1. 使用 FlagEmbedding（bge-m3）：

   * 對每個 pericope 文本產生 embedding。
   * 可選：對 verse 文本產生 embedding，供細粒度檢索。

2. 寫入 PostgreSQL：

   * 更新 `pericopes.embedding` 欄位。
   * 建立 pgvector 索引。

### 10.4 索引重建策略

* 索引建立流程以 CLI 方式提供，例如：

  * `python -m scripts.build_index --pdf bible.pdf`
* 流程包含：

  1. 清空或更新 PostgreSQL 表格。
  2. 重建 Neo4j 圖譜。
  3. 重新運行實體與主題標註。
  4. 重新產生 embeddings 與 pgvector 索引。

---

## 11. 部署與執行環境

### 11.1 本地部署架構

* 使用 Docker Compose 启动：

  * `frontend`: Node 18 + Vite build / dev server。
  * `backend`: Python 3.11 + FastAPI + Uvicorn。
  * `postgres`: 含 pgvector extension。
  * `neo4j`: 社群版。
  * `ollama`: 本地模型服務。

### 11.2 環境變數

* `POSTGRES_URL`：PostgreSQL 連線字串。
* `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`：Neo4j 連線資訊。
* `OLLAMA_BASE_URL`：Ollama HTTP endpoint。
* `EMBED_MODEL_NAME`：例如 `BAAI/bge-m3`。
* `RRF_K`：RRF 參數（預設 60）。

---

## 12. 非功能性需求

### 12.1 效能

* 聖經資料量有限（約 31k 節經文），對 PostgreSQL 與 Neo4j 負載低。
* 主要延遲來自：

  * 向量檢索（pgvector，預期 <100ms）。
  * LLM 推論（Ollama，依硬體與模型而定）。
* 目標：
  -單次查詢在本機一般硬體上整體回應時間 3–10 秒級（視模型而定）。

### 12.2 可維護性

* 後端以分層架構實作：

  * `api`：路由與序列化。
  * `services`：RAG pipeline 邏輯。
  * `repositories`：資料庫與圖資料庫存取。
  * `models`：Pydantic 模型與 ORM 模型。

### 12.3 可測試性

* 單元測試：

  * 查詢分類、RRF 套用、資料庫查詢。
* 整合測試：

  * 模擬 `/api/query` 全流程，但可以 stub 模擬 LLM 回應。

---
