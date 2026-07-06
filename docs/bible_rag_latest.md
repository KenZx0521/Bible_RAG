# Bible_RAG 最新架構說明

> **文件版本**：2026-05-17 ｜ 對應分支：`main` ｜ 最新提交：`703c45e 拉高coverage max_token`
> 本文件依據當前程式碼與線上執行中容器（5/5 healthy）實測撰寫，描述系統「目前實際運作」的架構。
> **⚠️ 落後提醒**：本文停在 `703c45e`，未涵蓋其後的 entity_query 路由、KG P0 資料修復、TSK 串珠匯入與排序融合層（`fused=(1−α)·rerank+α·weight`, α=0.3）等變更；各階段現況見 [kg_optimization_progress.md](kg_optimization_progress.md)。

---

## 1. 系統概覽

Bible_RAG 是一套**繁體中文聖經 GraphRAG 問答系統**。它把整本聖經（66 卷）拆解為結構化資料，同時建立向量索引與知識圖譜，並以「意圖偵測 → 6 路由多策略檢索 → 重排序 → LLM 生成」的管線回答使用者問題。

核心設計理念：

- **三資料源互補**：PostgreSQL（結構化內容）、Qdrant（語意/混合向量）、Neo4j（知識圖譜），各補對方的盲點。
- **訊號驅動路由**：依問題特徵（經文引用 / 章節 / 多人物 / 事件 / 多書卷 / 地名）走不同檢索組合，而非單一 semantic search。
- **重排序後的「釘選」(pin) 機制**：補救 BGE-reranker 把關鍵章節擠出 top-5 的問題。
- **請求層 A/B 開關**：`use_graph`、`semantic_only` 可逐請求覆寫，評估「有/無圖譜」「純語意 baseline」時**不需重啟容器**。

```
                            ┌─────────────────────────────────────────┐
   使用者問題                │            FastAPI Backend                │
        │                   │                                           │
        ▼                   │  ① 經文引用偵測 (regex)                   │
  POST /api/v1/query  ─────▶ │  ② 意圖分類 (LLM)                         │
                            │  ③ 訊號偵測 → 6 路由決策                  │
                            │  ④ 多策略並行檢索 ──┐                     │
                            │  ⑤ 融合去重 + 重排序 + 3 道 pin           │
                            │  ⑥ 上下文組裝                             │
                            │  ⑦ LLM 生成回答                           │
                            └───────┬──────────┬──────────┬────────────┘
                                    │          │          │
                          ┌─────────▼──┐  ┌────▼─────┐  ┌─▼──────────┐
                          │ PostgreSQL │  │  Qdrant  │  │   Neo4j    │
                          │ + pgvector │  │ 3 向量集 │  │  知識圖譜  │
                          └────────────┘  └──────────┘  └────────────┘
                                    │          │          │
                                    └──────────┴────┬─────┘
                                                    ▼
                                          ┌──────────────────┐
                                          │  Ollama (LLM)    │
                                          │  意圖分類 + 生成 │
                                          └──────────────────┘
```

---

## 2. 部署架構（Docker Compose）

整個系統由 `docker-compose.yml` 定義的 **5 個服務**組成，全部以容器執行：

| 容器 | Image | 對外埠 | 角色 |
|------|-------|--------|------|
| `bible_rag_backend` | 本地 build（`Dockerfile`） | 8000 | FastAPI RAG API |
| `bible_rag_postgres` | `pgvector/pgvector:pg15` | 5432 | 結構化資料 + pgvector |
| `bible_rag_qdrant` | `qdrant/qdrant:v1.13.2` | 6333 / 6334 | 向量資料庫 |
| `bible_rag_neo4j` | `neo4j:5.15-community`（含 APOC） | 7474 / 7687 | 知識圖譜 |
| `bible_rag_ollama` | `ollama/ollama:latest` | 11434 | LLM 推論（GPU） |

要點：

- backend 透過 `depends_on` + healthcheck 等待三個資料庫與 ollama 就緒後才啟動。
- backend 容器內主機名由 compose 覆寫為服務名（`postgres` / `qdrant` / `neo4j:7687` / `ollama:11434`），`.env` 中的 `localhost` 設定僅供 host 端腳本使用。
- ollama 透過 `deploy.resources` 取得所有 NVIDIA GPU。
- **backend 沒有掛載原始碼 volume**：`/app/backend/` 是 build 時烤進 image 的。修改 `backend/` 任何檔案後**必須** `docker compose up -d --build backend`，只 `restart` 會跑到舊版程式碼（詳見 §17 維運注意事項）。
- backend 唯一掛載的程式相關 volume 是唯讀的 `output/bm25_vocabulary.json`（混合檢索的 BM25 詞表）與 `model_cache`（HuggingFace 模型快取）。

---

## 3. 資料層 — 三大資料庫

### 3.1 PostgreSQL + pgvector

權威結構化資料來源，schema 定義於 `scripts/db/schema.sql`，啟動時自動套用。

| 資料表 | 內容 | 線上規模 |
|--------|------|----------|
| `books` | 書卷（卷名、約別、分類、章節數統計） | 66 |
| `chapters` | 章（含 metadata、footnotes） | 1,189 |
| `pericopes` | 段落（標題、`content`、`content_for_embedding`、`cross_references`、`verses`） | 2,779 |
| `chunks` | 過長段落再切分的子塊 | 431 |
| `entities` | 抽取出的實體（`canonical_name`、`aliases`、`type`、`mention_count`） | 9,120 |
| `entity_mentions` | 實體在文本中的每一次出現（`source_id`、`text_span`、位置） | 數萬筆 |

- 階層結構：`books → chapters → pericopes → chunks`，外鍵 `ON DELETE CASCADE`。
- **Pericope ID 格式**：`{book_id}:{chapter}:{pericope_index}`（例：`eph:6:2`）；verse 級為 `{book_id}:{chapter}:{verse}`，verse range 為 `{book_id}:{chapter}:{start}-{end}`。
- 檢索流程中，所有策略只回傳 ID，**完整內文一律由 PostgreSQL `get_content_by_id()` 補齊**（向量庫 payload 只當 fallback）。

### 3.2 Qdrant（向量資料庫）

線上有 **3 個 collection**：

| Collection | 向量 | Points | 用途 |
|------------|------|--------|------|
| `bible_embeddings` | dense（BGE-M3 1024 維） | 34,072 | 純語意檢索（`semantic_only` 模式、book-anchor） |
| `bible_embeddings_hybrid` | dense + sparse（BM25） | 34,072 | 混合檢索（RRF 融合），預設啟用 |
| `bible_entities` | dense（實體名/描述的 embedding） | 9,120 | entity_query 檢索（query→實體→Neo4j MENTIONS） |

> 34,072 points = pericope 級 + chunk 級 + verse 級的混合粒度索引。

### 3.3 Neo4j（知識圖譜）

社群版 5.15 + APOC。線上節點 **13,597 個**、關係數十萬條。

**節點標籤（線上實測）**：

| 標籤 | 數量 | 標籤 | 數量 |
|------|------|------|------|
| Pericope | 2,779 | Chapter | 1,189 |
| Person | 2,418 | Theme | 987 |
| Object | 2,200 | Group | 506 |
| Event | 1,712 | Chunk | 431 |
| Place | 1,299 | Book | 66 |

**關係類型（線上實測，取前段）**：

| 關係 | 數量 | 性質 |
|------|------|------|
| `MENTIONS` | 41,140 | 實體 → Pericope/Chunk（檢索核心邊） |
| `CONTAINS` | 4,399 | 結構：Book→Chapter→Pericope→Chunk |
| `NEXT` | 2,975 | 結構：章節順序 |
| `PARTICIPATED_IN` | 1,521 | 實體↔實體（人物參與事件） |
| `OCCURRED_IN` | 919 | 事件↔地點 |
| `CROSS_REFERENCES` | 916 | **段落↔段落，人工策劃的跨書卷對照邊** |
| `SON_OF` / `FATHER_OF` | 659 / 647 | 親屬關係 |
| `POSSESSED` / `INITIATED` / `MEMBER_OF` / `VISITED` … | — | 關係抽取管線產出的事實級邊 |

- **結構邊**（`CONTAINS` / `NEXT` / `MENTIONS` / `CROSS_REFERENCES`）：建庫時產生。
- **實體↔實體邊**（`FATHER_OF`、`RULED`、`PARTICIPATED_IN` …）：由 `scripts/relation_extraction/` 的關係抽取管線產出後匯入，供 entity_path 多跳推理使用。
- 實體節點屬性用 `canonical_name`（非 `name`）；Pericope 另有 `title`、`verse_range`、`book_name`、`chapter_num`。

---

## 4. 模型層

| 模型 | 名稱 | 載入時機 | 用途 |
|------|------|----------|------|
| Embedding | `BAAI/bge-m3`（1024 維，normalize） | backend 啟動 | query 與文本向量化 |
| Reranker | `BAAI/bge-reranker-v2-m3`（cross-encoder） | backend 啟動 | 候選池重排序 |
| Sparse | BM25 + CKIP 斷詞（`bert-base`） | 啟用混合檢索時 | sparse 向量（query 端 IDF 加權） |
| LLM | 由 `LLM_PROVIDER` 決定 | 每次請求 | 意圖分類 + 回答生成 |

- Embedding / Reranker 偵測 CUDA，有 GPU 走 `float16`，無則 CPU `float32`。
- Reranker 把 cross-encoder logit 經 `sigmoid` 正規化到 `[0,1]`，`max_length=512`。
- Sparse encoder 載入 `output/bm25_vocabulary.json`（k1=1.5, b=0.75），query 端用「出現即加 IDF 權重」。
- **LLM provider 可插拔**：`backend/utils/llm/factory.py` 支援 `ollama` / `claude` / `openai` / `gemini` 四種，singleton 化。

> **目前線上設定（容器實測）**：
> `LLM_PROVIDER=ollama`，`OLLAMA_MODEL=gemma4:e4b-it-q8_0`。
> 亦即 RAG 的意圖分類與回答生成目前都打 **本地 Ollama**，並非 Claude API。
> （`.env` 仍保留 `CLAUDE_MODEL=claude-haiku-4-5` 等設定，切換 provider 只需改 `.env` 並 rebuild backend。）

---

## 5. 查詢管線（POST /api/v1/query）

進入點：`backend/routers/query.py` → `rag_query()`。完整 7 步：

```
問題
 │
 ├─① 經文引用偵測   verse_parser.parse_verse_references()  ── regex，解析「羅馬書3:23」「創世記第1章」
 │
 ├─② 意圖分類       intent_classifier.classify_intent()    ── LLM 回 JSON：intent / entities / keywords
 │     （semantic_only 模式跳過 ①②，省一次 LLM 呼叫）
 │
 ├─③ 訊號偵測       signal_detector.detect_signals()       ── 產生布林訊號 → select_route() 選路
 │
 ├─④ 路由檢索       router._route_rN()                     ── 各路並行跑多策略，回傳候選池
 │
 ├─⑤ 融合 + 重排序  _dedup() → reranker.rerank(top_k=5)     ── 之後再跑 3 道 pin
 │
 ├─⑥ 上下文組裝     generator._build_context()             ── 把 top-5 段落編號排版
 │
 └─⑦ 回答生成       generator.generate_answer()            ── LLM 嚴格依據 context 作答
```

回應 `QueryResponse` 含：`answer`、`sources[]`、`intent`、`retrieval_stats`（`route_used` / `strategies_used` / `strategy_errors` / `use_graph` / 候選數）。

### 請求參數（`QueryRequest`）

| 欄位 | 預設 | 說明 |
|------|------|------|
| `question` | — | 使用者問題（1–500 字） |
| `top_k` | 5 | 回傳結果數 |
| `include_sources` | true | 是否附來源 |
| `use_graph` | `null` | 覆寫 `RAG_USE_GRAPH`；`null`=沿用 backend 設定 |
| `semantic_only` | false | 繞過 R1–R6 路由 / SQL / graph / cross-ref，只跑純語意檢索 |

---

## 6. 訊號偵測與 6 路由系統

### 6.1 訊號偵測（`signal_detector.py`）

結合「LLM 抽出的 entities/keywords」與「字典子字串比對」（`entity_dicts.py`），偵測 6 種布林訊號：

| 訊號 | 觸發條件 |
|------|----------|
| `has_book_chapter_verse` | 偵測到「書+章+節」精確引用 |
| `has_book_chapter` | 偵測到「書+章」（無節） |
| `has_multi_book` | 提到 ≥2 個書卷名 |
| `has_multi_person` | 偵測到 ≥2 個人物實體 |
| `has_event_keyword` | 命中事件關鍵詞（~50 詞，如「王國分裂」「登山寶訓」） |
| `has_place` | 命中地名 |

### 6.2 路由決策樹（`select_route()`）

優先序：**R1 > R5(多書+章) > R2 > R5(預設) > R3 > R4 > R6 > fallback**

```
has_book_chapter_verse ───────────────▶ R1   精確經文
has_book_chapter & has_multi_book ─────▶ R5   （多書卷且指定章 → 走 cross-ref 而非 R2）
has_book_chapter ──────────────────────▶ R2   章節 + 語意
has_multi_book | intent=cross_reference▶ R5   跨書卷對照
has_multi_person ──────────────────────▶ R3   人物圖譜
has_event_keyword ─────────────────────▶ R4   事件
has_place ─────────────────────────────▶ R6   地點
（皆無）───────────────────────────────▶ fallback  純語意 + book-anchor
```

### 6.3 各路檢索策略組合

每個 route handler 回傳 `(candidates, strategies_used, strategy_errors)` 三元組。`use_graph=False` 時所有 Neo4j 相關策略被閘道掉。

| 路由 | 主策略 | 補充策略 | 重排序 |
|------|--------|----------|--------|
| **R1** 精確經文 | `verse_direct`（SQL 直查，weight 1.0） | 空則 fallback 到 R2 | **跳過**（直接回精確匹配） |
| **R2** 章節+語意 | `sql_chapter`(0.9) + `semantic`(0.6) | — | 有 |
| **R3** 人物圖譜 | `graph_person`(0.9) + `semantic`(0.7) | `book_anchor` + `entity_path` + `cross_ref_expand` + `entity_query`(0.6) + `sql_supplement`(0.5) | 有 |
| **R4** 事件 | `graph_event`(0.85) + `semantic`(0.7) | `book_anchor` + `cross_ref_expand` + `entity_query`(0.6) + `sql_supplement` | 有 |
| **R5** 跨書卷對照 | `semantic`(0.65) + `sql_chapter`(0.85) ∥ `cross_reference`(0.85) ∥ `graph`(0.75) ∥ `graph_event` | `book_anchor` + `entity_query`(0.6) + `sql_supplement`(0.4) | 有 |
| **R6** 地點 | `graph_place`(0.85) + `semantic`(0.7) | `book_anchor` + `entity_path` + `cross_ref_expand` + `entity_query`(0.6) + `sql_supplement` | 有 |
| **fallback** | `semantic`／`hybrid` | `book_anchor`（若有提到書卷） | 有 |

權重定義於 `config.py:route_weights`。weight 只影響 pre-rerank 去重時的取捨，**不影響 reranker 排序**（reranker 純看 cross-encoder logit）。

---

## 7. 檢索策略清單

`backend/utils/retrieval/` 下各 retriever：

| 策略 | 檔案 | 機制 |
|------|------|------|
| `semantic` | `semantic_retriever.py` | BGE-M3 query → Qdrant `bible_embeddings` → PostgreSQL 補內文。支援 `book_filter`。 |
| `hybrid` | `hybrid_retriever.py` | dense + sparse 雙路 → Qdrant RRF 融合（`bible_embeddings_hybrid`）。sparse 不可用時自動降級 dense-only。 |
| `verse_direct` | `verse_retriever.py` | 依 VerseRef 從 PostgreSQL 取 verse range / 單節 / 整章。 |
| `graph_person/event/place` | `graph_retriever.py` | Neo4j 找實體 → 走 `MENTIONS` → 取相關 Pericope。多人物另查「共同出現段落」。 |
| `cross_reference` | `cross_ref_retriever.py` | 1-hop `CROSS_REFERENCES`（R5 legacy seed 展開）。 |
| `cross_ref_expand` | `cross_ref_retriever.py` | N-hop（預設 2）`CROSS_REFERENCES` 展開，啟用 916 條人工跨書卷對照邊；權重隨跳數衰減。 |
| `entity_path` | `entity_path_retriever.py` | 走實體↔實體邊（`FATHER_OF`/`RULED`…）做多跳事實推理 → `MENTIONS` → Pericope。 |
| `entity_query` | `entity_path_retriever.py` | query → `bible_entities` 向量比對找實體 → Neo4j `MENTIONS`（hub-aware 限流）。**目前以開關停用，見 §10**。 |
| `book_anchor` | `router.py:_expand_via_book_anchor` | 問題點名某書卷時，做 `book_name` 過濾的語意檢索，確保該書卷一定有 seed。 |
| `sql_supplement` | `router.py:_sql_supplement` | 從候選命中的章補抓同章其他段落。 |

**cross-ref 展開的種子挑選**採 round-robin：跨 `source_strategy` 輪流取種子，避免單一高權重策略壟斷所有種子槽（對跨書卷題很關鍵）。

---

## 8. 融合、重排序與 3 道 Pin 機制

### 8.1 融合去重

`_dedup()`：依 ID 去重，**保留 weight 最高者**（strict-greater，平手保留先到者）。

### 8.2 重排序

`reranker.rerank(query, candidates, top_k=5)`：BGE-reranker-v2-m3 cross-encoder 對 `(query, content)` 算分，sigmoid 後降序取 top-5。R1 跳過重排序。

### 8.3 重排序後的 3 道 Pin（`router.py`）

reranker 是「字面語意 surface matcher」，現代中文題目詞彙（「登山寶訓」「王國分裂」）不出現在古文聖經內文時，會把對的章節擠出 top-5。三道 pin 依序補救（R1 / `semantic_only` 模式跳過）：

| Pin | 函式 | 觸發 | 合成分數 |
|-----|------|------|----------|
| **章節 pin** | `_pin_chapter_candidates` | 使用者指定「某書N章」，保證該章 ≥2 段落留在 top-k（weight≥0.85 才合格） | base + 0.01（最高優先） |
| **entity_query pin** | `_pin_entity_query_candidates` | 高信心 EQ 候選（`via_entity_score>0.5`、Event/Person 型）；**僅當 reranker 不確定（top1 < 0.3）時才 pin** | base + 0.005 |
| **graph / book-anchor pin** | `_pin_graph_candidates` | `book_anchor` 候選**無條件** pin；`graph_*` 候選僅 top1<0.3 時 pin | book_anchor +0.004 / graph +0.003 |

「reranker 信心閘」（top1≥0.3 就跳過 EQ/graph pin）是 2026-05-15 加入的：100 題 eval 顯示無閘的 pin 淨負面（reranker 已確定卻被 pin 的題目 mean AC 0.497 vs 未 pin 0.703）。

---

## 9. 回答生成（`generator.py`）

- `_build_context()`：把 top-5 段落排版成 `[1] 書名 第N章 - 標題 (節數)\n內文` 形式。
- `SYSTEM_PROMPT` 嚴格約束：**只能用提供的段落作答、必須引用出處、不得加入經文外知識、繁體中文**。
- 呼叫 `LLM_PROVIDER` 指定的 client，`temperature=0.1`、`max_tokens=LLM_MAX_TOKENS`（目前 10000）。
- 無檢索結果時直接回「找不到相關的經文內容來回答這個問題。」

---

## 10. 檢索功能開關（Feature Flags）

由 `.env` 控制，`config.py` 讀入。**以下為目前線上容器實測值**：

| 旗標 | 線上值 | 作用 |
|------|--------|------|
| `RAG_USE_GRAPH` | `true` | 總開關：關閉則 R3/R4/R5/R6 跳過所有 Neo4j 檢索 |
| `HYBRID_SEARCH_ENABLED` | `true` | semantic 策略改走 `bible_embeddings_hybrid` 的 dense+sparse RRF |
| `RAG_USE_CROSS_REF_EXPAND` | `true` | 啟用 N-hop cross-ref 展開（`max_hops=2`, `top_seeds=5`, `expand_limit=30`） |
| `RAG_USE_ENTITY_PATH` | `true` | 啟用實體↔實體多跳推理（`max_hops=2`, `limit=15`） |
| `RAG_USE_ENTITY_QUERY` | **`false`** | **entity_query 補充檢索目前停用** ⚠️ |
| `LLM_MAX_TOKENS` | `10000` | 生成回答的 token 上限 |

> ⚠️ **`RAG_USE_ENTITY_QUERY=false`（重要現況）**
> `entity_query` 策略與 `bible_entities` collection（9,120 points）都已實作完成並接上 R3/R4/R5/R6，但目前以 `.env` 旗標**關閉**（程式碼預設值為 `True`，被 `.env` 覆寫）。
> 因此目前線上 RAG 的候選池**不含 entity_query 補充**，第 2 道「entity_query pin」也無候選可釘。
> 此策略歷史上會被 reranker 擠出且對「同主角不同事件」誤判，是當前刻意停用的取捨。

---

## 11. A/B 評估開關

兩個請求層開關，讓評估比較**不必重建容器**（一次性部署後即可逐請求覆寫）：

| 開關 | 端對端路徑 | 效果 |
|------|-----------|------|
| `use_graph` | CLI `--graph`/`--no-graph` → payload → `effective_use_graph` → 各 route handler 閘道 Neo4j 呼叫 | 比較「有/無知識圖譜」 |
| `semantic_only` | CLI `--semantic` → payload → 繞過訊號偵測與路由 | 純語意 baseline |

- backend 重載 BGE-M3 + reranker 約需 30–60 秒，故設計成 per-request payload 覆寫，避免每次切模式都重啟。
- `.env` 的 `RAG_USE_GRAPH` 僅作為「請求未帶 `use_graph` 時」的預設值（safety net）。
- 回應 `retrieval_stats.use_graph` 會標記該請求實際執行的模式。

---

## 12. 資料建構管線（`scripts/`）

從聖經 markdown 到三資料庫的離線建庫流程（host 端執行，用 `scripts/pyproject.toml` 的依賴）：

```
bible_md/ (聖經 markdown)
   │
   ├─ process_bible.py ──────────▶ output/{books,chapters,pericopes,chunks}.jsonl
   │                               output/{embedding_queue,neo4j_nodes,neo4j_relationships}.jsonl
   │
   ├─ generate_embeddings.py ────▶ output/embeddings.jsonl        (BGE-M3 dense)
   ├─ generate_sparse_vectors.py ▶ output/sparse_vectors.jsonl    (BM25 + CKIP)
   │                               output/bm25_vocabulary.json
   │
   ├─ extract_entities.py ───────▶ output/entities.jsonl          (grounded 實體抽取管線)
   │     └ entity_extraction/：CKIP POS 候選 → 規則分類器 → LLM 分類器（信心門檻 escalate）
   │
   ├─ extract_relations / relation_extraction/ ▶ output/relations.jsonl  (實體↔實體關係抽取)
   │
   ├─ embed_entities.py ─────────▶ Qdrant bible_entities          (實體 embedding)
   │
   └─ 匯入：
        import_postgres.py ───────▶ PostgreSQL
        import_qdrant.py ─────────▶ Qdrant bible_embeddings
        import_qdrant_hybrid.py ──▶ Qdrant bible_embeddings_hybrid
        import_neo4j.py ──────────▶ Neo4j（結構節點 + MENTIONS + CROSS_REFERENCES）
        import_relations_neo4j.py ▶ Neo4j（實體↔實體事實邊）
```

- 實體 / 關係抽取的 LLM provider 由 `ENTITY_EXTRACT_LLM_PROVIDER` / `RE_LLM_PROVIDER` 獨立控制（目前皆 `ollama`）。
- 關係抽取的 schema 與先驗定義於 `config/relations/biblical_relations.yaml`、`biblical_priors.yaml`。

---

## 13. 評估系統（`evaluation/`）

獨立的評估框架，host 端執行，透過 HTTP 打 backend。

### 13.1 CLI（`run_eval.py`）

```bash
cd evaluation
uv run python run_eval.py                 # 完整管線（收集→評估→視覺化）
uv run python run_eval.py --collect-only   # 只收集 RAG 回應
uv run python run_eval.py --eval-only      # 只跑批次指標
uv run python run_eval.py --visualize-only # 只產生 dashboard

uv run python run_eval.py --graph          # 強制有圖譜 → results_graph/
uv run python run_eval.py --no-graph       # 強制無圖譜 → results_no_graph/
uv run python run_eval.py --semantic       # 純語意 baseline → results_semantic/
```

輸出目錄依模式切換（`src/config.py:results_dir`），每個目錄產出 `raw_responses.json`、`evaluation_results.json`、`evaluation_results.csv`、`dashboard.html`。

### 13.2 評測資料集

`ground_truth.json`：**100 題**，5 類各 20 題：

| 題型 | 數量 | 題型 | 數量 |
|------|------|------|------|
| `VERSE_LOOKUP` | 20 | `EVENT_QUESTION` | 20 |
| `TOPIC_QUESTION` | 20 | `GENERAL_BIBLE_QUESTION` | 20 |
| `PERSON_QUESTION` | 20 | | |

每題含 `reference`（標準經文出處）、`expected_answer_points`（應涵蓋重點）、`reference_answer`。

### 13.3 評估指標

| 類別 | 指標 | 說明 |
|------|------|------|
| 檢索（自訂，無 LLM） | Precision@k、Recall@k、F1@k、MRR、MAP@k、NDCG@k、Hit Rate | 對 `expected reference` 算分 |
| RAGAS（LLM judge） | Faithfulness、Answer Relevancy、Context Recall、Answer Correctness | — |
| 語意 | Semantic Similarity | RAG 回答 vs 參考答案的餘弦相似度 |
| 涵蓋率（LLM judge） | Answer Coverage | 對 `expected_answer_points` 的純召回（covered/partial/missing） |

- judge LLM 由 `EVAL_LLM_PROVIDER` 控制（目前 `ollama`，`EVAL_OLLAMA_MODEL=gemma4:26b-a4b-it-q8_0`）。
- 失敗（如 RAGAS timeout）的指標標記為 `invalid`，聚合時排除而非當 0 拉低平均。

---

## 14. 目前評估結果

最近一輪（2026-05-16）對「**檢索模式（graph vs 純語意）× 回答生成 LLM（Claude vs Gemma）**」做了 2×2 比較。檢索指標在同檢索模式下不受生成 LLM 影響（故 claude/gemma 兩欄相同）：

| 指標 | graph + Claude | graph + Gemma | semantic + Claude | semantic + Gemma |
|------|:---:|:---:|:---:|:---:|
| Hit Rate | 0.96 | 0.95 | 0.81 | 0.81 |
| Recall@5 | 0.886 | 0.889 | 0.758 | 0.758 |
| NDCG@5 | 0.863 | 0.856 | 0.686 | 0.686 |
| MRR | 0.805 | 0.802 | 0.647 | 0.647 |
| RAGAS Faithfulness | 0.957 | 0.951 | 0.899 | 0.903 |
| RAGAS Answer Relevancy | 0.815 | 0.893 | 0.709 | 0.774 |
| RAGAS Context Recall | 0.797 | 0.791 | 0.680 | 0.677 |
| RAGAS Answer Correctness | 0.618 | 0.587 | 0.529 | 0.513 |
| Answer Coverage | 0.750 | 0.722 | 0.618 | 0.628 |
| Semantic Similarity | 0.785 | 0.780 | 0.745 | 0.745 |

對應目錄：`evaluation/results_graph_claude_answer/`、`results_graph_gemma_answer/`、`results_semantic_claude_answer/`、`results_semantic_gemma_answer/`。

**觀察**：

- **圖譜檢索全面優於純語意**：Hit Rate +0.15、Recall@5 +0.13、Answer Coverage 約 +0.12。圖譜對「找對章節」貢獻明確。
- **Answer Correctness 天花板約 0.6**：受三個獨立瓶頸壓制（RAGAS judge 對相同 context 有 ±0.4 雜訊、reranker 擠出問題、chunking 章內事件碎裂）。
- 生成 LLM 換 Claude vs Gemma 對檢索指標無影響，主要差在 RAGAS AC / Coverage（Claude 略高）。

路由分布（100 題，graph 模式）：R2=25、R3=21、R1=20、R4=18、R5=10、R6=4、fallback=2。

---

## 15. 已知問題與限制

| 問題 | 說明 | 影響 |
|------|------|------|
| **reranker 擠出實體錨點** | BGE-reranker 純看字面，現代中文題目詞彙（「登山寶訓」）不在古文內文時，會把對的章節擠出 top-5。3 道 pin 為補救機制但非根治。 | AC 天花板 |
| **字典 ↔ Neo4j 命名不一致** | 字典「登山寶訓」vs 圖譜「山上寶訓」、「保羅歸主」vs「掃羅在大馬士革歸主」等；且圖譜實體 `aliases` 多為空陣列，無同義詞 fallback。 | 部分 R4/R5/R6 圖譜路 miss |
| **MENTIONS 邊漏共指** | 實體抽取未做代名詞/親屬稱謂共指消解；段落只用「岳父/他」指涉時 `MENTIONS` 邊未建（如葉忒羅未連到 出18:13-27）。 | 人物敘事題召回不足 |
| **chunking 章內碎裂** | 一章事件被切成多 chunk，top_k=5 不足以涵蓋整章（如十災只撈到 4 災、登山寶訓只撈到開場兩節）。 | EVENT 題答不完整 |
| **RAGAS judge 雜訊** | 相同 context、近乎相同答案，AC 評分可差 ±0.4。 | 絕對 AC 比較需謹慎 |
| **entity_query 目前停用** | 見 §10。對「同主角不同事件」誤判（hub entity 過廣）是停用主因。 | 部分需實體橋接的題目召回下降 |

---

## 16. 專案結構

```
Bible_RAG/
├── docker-compose.yml          5 服務定義
├── Dockerfile                  backend image
├── .env / .env.example         所有設定（DB / LLM / 檢索旗標）
├── ground_truth.json           100 題評測集
│
├── backend/                    FastAPI 後端（容器執行時）
│   ├── main.py                 app + lifespan（初始化 DB / 模型 / LLM）
│   ├── config.py               pydantic-settings 設定
│   ├── pyproject.toml          ← backend 執行時依賴
│   ├── routers/                query / health / verse / entity
│   ├── models/                 request / response（Pydantic v2）
│   ├── database/               postgres / qdrant_db / qdrant_hybrid / neo4j_db
│   └── utils/
│       ├── embedder.py / reranker.py / sparse_encoder.py
│       ├── intent_classifier.py / signal_detector.py / verse_parser.py
│       ├── entity_dicts.py / generator.py
│       ├── llm/                base / factory / ollama / claude / openai / gemini
│       └── retrieval/          router.py（6 路由核心，~1350 行）
│                               semantic / hybrid / graph / cross_ref /
│                               entity_path / verse retriever
│
├── scripts/                    離線資料建構管線（host 端執行）
│   ├── pyproject.toml          ← 資料管線依賴（與 backend 不同步）
│   ├── process_bible.py        markdown → JSONL
│   ├── generate_embeddings.py / generate_sparse_vectors.py / embed_entities.py
│   ├── extract_entities.py / extract_relations.py
│   ├── import_{postgres,qdrant,qdrant_hybrid,neo4j,relations_neo4j}.py
│   ├── db/schema.sql           PostgreSQL schema
│   ├── entity_extraction/      grounded 實體抽取
│   ├── relation_extraction/    關係抽取
│   └── sparse_encoding/        BM25 + CKIP
│
├── evaluation/                 評估框架（host 端執行）
│   ├── pyproject.toml          ← 評估依賴（第三套）
│   ├── run_eval.py             CLI 入口
│   ├── src/                    collector / evaluator / rag_client /
│   │                           metrics/{retrieval,ragas_eval,coverage_eval,
│   │                                    semantic_similarity}
│   └── results_*/              各模式輸出目錄
│
├── bible_chunking/             markdown 解析 + 階層 chunking + BOOK_CONFIG
├── config/relations/           關係抽取 schema / priors（YAML）
├── output/                     建庫管線產出的 JSONL
└── docs/                       建庫與資料庫架構文件
```

**三套 `pyproject.toml`**（重要）：`backend/`（容器執行時）、`scripts/`（資料管線）、`evaluation/`（評估）。三邊依賴集不同步是常見 bug 來源——新增 backend 依賴時務必確認 `backend/pyproject.toml` 有列出。

---

## 17. 維運注意事項

1. **改 backend 程式碼必須 rebuild**
   backend 容器無原始碼 volume mount，`/app/backend/` 是 image baked。
   修改 `backend/` 後 → `docker compose up -d --build backend`（只 `restart` 會跑舊版）。
   `.env` 例外：`env_file` 在啟動時注入，但 `settings = Settings()` 是 module-load 時固定，故改 `.env` 仍需重啟（建議直接 rebuild）。

2. **切換 graph / semantic 模式不用動容器**
   用 evaluation CLI 的 `--graph/--no-graph/--semantic`（per-request payload 覆寫）。

3. **切換 LLM provider**
   改 `.env` 的 `LLM_PROVIDER`（+對應 API key / model）後 rebuild backend。
   目前線上為 `ollama` + `gemma4:e4b-it-q8_0`。

4. **健康檢查**
   `curl http://localhost:8000/api/v1/health` → 回 postgres / qdrant / neo4j / llm 四項布林。

5. **evaluation 端腳本**（`evaluation/src/*.py`）跑在 host，改完不需 rebuild。

6. **建庫腳本與 backend 的命名對齊**
   `process_bible.py` 產生的 `source_id` 必須與 `bible_chunking/config.py:BOOK_CONFIG` 一致，否則 `import_neo4j.py` 的 `MATCH` 會靜默失敗。權威對照表：`output/pericopes.jsonl`。

---

*本文件為當前架構快照（2026-05-17）。實作細節以程式碼為準；記憶體中的舊觀察可能已過時，引用前請對照現行程式碼。*
