# Bible RAG Evaluation System

針對 Bible GraphRAG 系統的完整評估框架，結合 RAGAS 與自訂指標，使用 Claude API 作為 LLM 評估模型。

## 架構

```
evaluation/
├── run_eval.py                  # CLI 入口(完整管線:收集 → 評估 → 視覺化)
├── quick_retrieval_eval.py      # 快速檢索評估迴圈(retrieval-only,無生成/RAGAS)
├── apply_coverage.py            # 答案要點覆蓋率離線補算
├── src/
│   ├── config.py                # 讀取 ../.env(共用)+ ./.env(eval 專屬,優先)
│   ├── models.py                # Pydantic 資料模型
│   ├── data_loader.py           # 載入 ground_truth.json
│   ├── reference_parser.py      # 解析中文經文引用
│   ├── relevance_judge.py       # 檢索相關性判斷
│   ├── rag_client.py            # httpx 呼叫 RAG API
│   ├── content_fetcher.py       # asyncpg 取得 context
│   ├── collector.py             # 回應收集 (支援中斷續傳)
│   ├── evaluator.py             # 主要協調器
│   ├── visualizer.py            # Plotly 視覺化
│   └── metrics/
│       ├── retrieval.py         # 7 個檢索指標
│       ├── ragas_eval.py        # RAGAS 框架指標
│       ├── coverage_eval.py     # 答案要點覆蓋率
│       └── semantic_similarity.py
├── templates/
│   └── dashboard.html.j2       # 儀表板模板
├── results/                     # 預設輸出目錄(無 --graph/--no-graph)
├── results_graph/               # --graph 模式輸出(--no-graph → results_no_graph/)
├── results_*_answer/            # 生成端 LLM 對照組(claude/gemma × graph/semantic)
└── results_quick/               # quick_retrieval_eval.py 輸出(<label>.json)
```

## 前置條件

1. **後端服務運行中**：
   ```bash
   # 在專案根目錄
   docker compose up -d
   ```
2. **`.env` 設定正確**（兩層）：
   - 專案根目錄 `.env`：共用基礎設施 — `ANTHROPIC_API_KEY`、PostgreSQL 連線、`OLLAMA_BASE_URL`
   - `evaluation/.env`：eval 專屬參數 — `EVAL_LLM_PROVIDER`、`EVAL_*_MODEL`、`BACKEND_URL`、`TOP_K`、`REQUEST_DELAY`、`EVAL_RAGAS_*`（範本：`evaluation/.env.example`；同名變數以此檔為準）
3. **(可選) Graph 檢索預設值**：在根目錄 `.env` 設定 `RAG_USE_GRAPH=true/false`，作為 backend 預設行為(CLI 未指定時生效)

## 安裝

```bash
cd evaluation
uv sync
```

## 使用

```bash
# 完整評估（收集 → 評估 → 視覺化）
uv run python run_eval.py

# 分步執行
uv run python run_eval.py --collect-only      # 只收集 RAG 回應
uv run python run_eval.py --eval-only         # 只跑評估（需先收集）
uv run python run_eval.py --visualize-only    # 只產生視覺化（需先評估）
```

### Graph 檢索 A/B 比較

支援透過 CLI 旗標切換「有/無 Graph 檢索」模式，**不需要重啟或重建 docker container**(透過 per-request HTTP payload 覆寫實現):

```bash
# 跑「有 Graph」模式 → results_graph/
uv run python run_eval.py --graph

# 跑「無 Graph」模式 → results_no_graph/
uv run python run_eval.py --no-graph

# 不指定 → results/，沿用 backend RAG_USE_GRAPH 預設
uv run python run_eval.py
```

兩種模式的輸出會自動分到不同目錄，方便對照比較:

```bash
# 比較兩組 CSV
diff <(cut -d, -f1-10 results_graph/evaluation_results.csv) \
     <(cut -d, -f1-10 results_no_graph/evaluation_results.csv)

# 確認模式正確標記
jq '[.[] | .use_graph] | unique' results_graph/raw_responses.json    # → [true]
jq '[.[] | .use_graph] | unique' results_no_graph/raw_responses.json # → [false]
```

**閘道規則**(`--no-graph` 時跳過):
- R3 person → 略過 `graph_person`，保留 semantic + SQL supplement
- R4 event → 略過 `graph_event`
- R5 cross-ref → 略過 `cross_reference` 與 `graph`
- R6 place → 略過 `graph_place`
- R1/R2/fallback 不受影響(本來就沒用 Neo4j)

每筆 `raw_responses.json` 記錄會帶 `use_graph: bool` 欄位標記實際執行模式。

> **首次部署**：backend 需要重建一次以載入 `use_graph` payload 處理邏輯：
> `docker compose up -d --build backend`
> 之後切換 `--graph / --no-graph` 完全不需要動 container。

### 快速檢索評估迴圈（quick_retrieval_eval.py）

跳過答案生成與 RAGAS，只跑檢索 + 7 個檢索指標（與完整管線同一套 `src/metrics/retrieval.py` 計分碼，數字直接可比）。100 題約幾分鐘，是消融實驗的主力工具：

```bash
# 現場收集(backend 需在跑)
uv run python quick_retrieval_eval.py --label fixes_a03

# α sweep 單點 / graph off / 題型子集
uv run python quick_retrieval_eval.py --alpha 0.0 --label alpha0
uv run python quick_retrieval_eval.py --no-use-graph --label nograph
uv run python quick_retrieval_eval.py --only EVENT PERSON --label ev_only

# 用舊 raw_responses.json 以 byte-identical 指標碼重算(建基線)
uv run python quick_retrieval_eval.py --from-raw results_graph/raw_responses.json --label p0_baseline

# 差異比較:逐題型 Δ + hit_rate 翻轉題清單
uv run python quick_retrieval_eval.py --compare results_quick/a.json results_quick/b.json
```

輸出存至 `results_quick/<label>.json`，含 overall / by_type 聚合與逐題明細（route、strategies、sources、rerank/fused 分數）。

## 消融實驗因子總覽

2026-07 盤點：檢索管線中所有可操縱的實驗因子，按操縱成本分四級。論文 §6 的 α ablation（α ∈ {0, 0.3}）只掃了其中一軸。

### 第一級：per-request 參數（改 CLI 即可，不動 backend）

已接到 `/api/v1/query` payload，透過 `quick_retrieval_eval.py` 或 `run_eval.py` 旗標控制：

| 因子 | 現值 | 可掃範圍 | 工具旗標 |
|------|------|----------|----------|
| `fusion_alpha` | 0.3 | 0 ~ 1.0 連續（0 = 純 reranker） | `--alpha` |
| `use_graph` | on | on/off（一鍵關 graph + cross_ref + EQ + entity_path） | `--use-graph / --no-use-graph` |
| `semantic_only` | off | 純語意基線，連 6 路由都繞過 | `run_eval.py --semantic`（quick 工具尚未接此欄位，加一行 payload 即可） |
| `top_k` | 5 | 3 / 5 / 10（@k 截斷） | `--top-k` |
| 題型子集 | 全 100 題 | EVENT / PERSON / … 前綴過濾 | `--only` |

### 第二級：`.env` 覆蓋（改完 `docker compose up -d backend` 即生效）

`backend/config.py` 為 pydantic-settings，backend 走 `env_file: .env` 掛載——改 `.env` 只需 recreate container，**不用** `--build`（改 backend/ 程式碼才要）。

**組件開關**（leave-one-out 消融的直接素材）：

| 環境變數 | 預設 | 控制內容 |
|----------|------|----------|
| `RAG_USE_GRAPH` | true | 全域 graph 總開關（per-request `use_graph` 的 fallback 預設） |
| `RAG_RANK_FUSION_ENABLED` | true | 排序融合層；關閉退回 legacy 純 reranker 路徑（注意：EQ pin 與 graph uncertainty pin 會隨之復活，不是純減法） |
| `RAG_USE_CROSS_REF_EXPAND` | true | CROSS_REFERENCES N-hop 擴展（916 curated + TSK 邊） |
| `RAG_USE_ENTITY_PATH` | true | Entity-Entity 邊多跳（FATHER_OF、RULED…） |
| `RAG_USE_ENTITY_QUERY` | true | EQ 補充（BGE-M3 → bible_entities → Neo4j MENTIONS） |
| `HYBRID_SEARCH_ENABLED` | false | dense+BM25 RRF hybrid 取代純 dense semantic |

**結構超參數**：

| 環境變數 | 預設 | 說明 |
|----------|------|------|
| `RAG_RANK_FUSION_ALPHA` | 0.3 | `fused = (1-α)·rerank_score + α·weight` |
| `RAG_CROSS_REF_MAX_HOPS` | 2 | cross-ref 擴展跳數 |
| `RAG_CROSS_REF_TOP_SEEDS` | 5 | 擴展種子數（round-robin 跨策略選取） |
| `RAG_CROSS_REF_EXPAND_LIMIT` | 10 | 擴展候選上限（2026-07-06 由 30 降 10，eval 有紀錄） |
| `RAG_ENTITY_PATH_MAX_HOPS` / `_LIMIT` | 2 / 15 | entity-path 跳數與候選上限 |
| `RAG_ENTITY_QUERY_TOP_K` | 8 | EQ 取前 K 實體 |
| `RAG_ENTITY_QUERY_SCORE_THRESHOLD` | 0.4 | 實體向量分數門檻 |
| `RAG_ENTITY_QUERY_HUB_THRESHOLD` | 50 | mention 數 ≥ 此值視為 hub 實體 |
| `RAG_ENTITY_QUERY_PERICOPES_PER_ENTITY_NORMAL` / `_HUB` | 5 / 3 | 每實體取錨數 |
| `RAG_ENTITY_QUERY_SUPPLEMENT_CAP` | 5 | EQ 補充候選上限 |
| `SEMANTIC_SEARCH_TOP_K` | 20 | 語意檢索候選池大小（rerank 前） |
| `ROUTE_WEIGHTS` | dict | 每路由每策略先驗（graph 0.85–0.9 / semantic 0.65–0.7 / EQ 0.6 / sql 0.4–0.5），env 以 JSON 字串覆蓋。fusion 公式第二項的來源——α 消融只掃融合比例，weight 間距本身是另一條未掃過的軸 |

### 第三級：程式碼內常數（改 code + `docker compose up -d --build backend`）

| 位置 | 因子 | 現值 |
|------|------|------|
| `backend/utils/retrieval/cross_ref_retriever.py` | curated 邊 hop-decay `_HOP_WEIGHT` | {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30} |
| 同上 | TSK 邊 hop-decay `_TSK_HOP_WEIGHT` | {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30} |
| 同上 | curated/TSK 判別線 `_CURATED_VOTES` | votes ≥ 999 |
| `backend/utils/retrieval/router.py` | chapter-pin | `min_pins=2`、weight ≥ 0.85 門檻 |
| 同上 | EQ pin（僅 fusion off 生效） | `score_threshold=0.5`、confidence gate 0.3、`max_pins=2` |
| 同上 | book_anchor pin（無條件）+ graph uncertainty pin（僅 fusion off） | `max_pins=2`、gate 0.3 |
| 同上 | keyword-exact event pin（僅 fusion on 生效） | `hub_cap=25`、`max_pins=2`、只取 `anchor_rank==0` |
| 同上 | book_anchor 檢索 | weight 0.9、top_k 10 |
| `backend/utils/reranker.py` | cross-encoder 截斷 | `max_length=512` |

注意：四個 pin 目前只隨 `fusion_active` 整組切換，**沒有獨立開關**——要單獨消融（例如量化 keyword pin 對 Acts 9 掃羅題的貢獻）需先加 flag。「no-rerank 純 weight 排序」目前僅是 reranker 失敗時的 fallback，也無開關。

### 第四級：資料與模型層（重建索引或圖譜）

- **TSK 邊**（~25 萬條）：整批 on/off，或按 `votes` 閾值分層過濾消融
- **916 條 curated cross-book 邊**：on/off
- **Data repairs**（18 條 curated Event、aliases 修復等）：論文 α ablation 已聲明全開，拆開可做 discrete-repairs 細粒度歸因
- **生成端 LLM**（`LLM_PROVIDER`）：已有 `results_graph_claude_answer` / `results_graph_gemma_answer` 等現成對照組
- **`EMBEDDING_MODEL`**（BGE-M3）/ **`RERANKER_MODEL`**（bge-reranker-v2-m3）：替換需重建 Qdrant 索引，成本最高

### 建議消融軸（價值排序）

1. **α 細掃**（第一級，零成本）：補 0.1 / 0.2 / 0.5 / 0.7 / 1.0，畫出 TOPIC MRR +0.133 vs NDCG −0.02 的 trade-off 曲線
2. **組件 leave-one-out**（第二級，每 flag 一次 quick eval）：−cross_ref_expand、−EQ、−entity_path、−hybrid、−fusion，回答「每個檢索器貢獻多少」
3. **Additive build-up**：`semantic_only` → +路由/graph → +fusion，與論文三時點演化表互補
4. **Pin 獨立消融**（需加 flag）：量化 curated dictionary bridge 的邊際貢獻
5. **TSK votes 閾值分層**（第四級）：驗證「高 votes = 強主題親和但非同敘事」的假設

## 評估指標

### 檢索指標（自訂）
| 指標 | 說明 |
|------|------|
| Precision@k | 前 k 個結果中相關的比例 |
| Recall@k | 相關結果被檢索到的比例 |
| F1@k | Precision 和 Recall 的調和平均 |
| MRR | 第一個相關結果的排名倒數 |
| MAP@k | 平均精確率 |
| NDCG@k | 歸一化折損累積增益（分級相關性） |
| Hit Rate | 是否至少有一個相關結果 |

### LLM 評估指標
| 指標 | 框架 | 說明 |
|------|------|------|
| Faithfulness | RAGAS | 回答是否忠於 context |
| Answer Relevancy | RAGAS | 回答是否切題 |
| Context Recall | RAGAS | context 的完整性 |
| Answer Correctness | RAGAS | 綜合正確性 |

### 語意指標
| 指標 | 說明 |
|------|------|
| Semantic Similarity | RAG 回答與參考答案的餘弦相似度 |

## 結果

評估完成後，在輸出目錄(預設 `results/`，依 `--graph/--no-graph` 切換為 `results_graph/` 或 `results_no_graph/`)會產生：
- `raw_responses.json` — RAG 原始回應(含 `use_graph` 欄位標記模式)
- `evaluation_results.json` — 完整評估結果
- `evaluation_results.csv` — 每題逐筆指標(可用試算表打開)
- `dashboard.html` — 互動式視覺化儀表板

開啟 `<輸出目錄>/dashboard.html` 查看互動式報告。

## 結果解讀

- **Hit Rate > 0.8**: 檢索系統基本可靠
- **Faithfulness > 0.7**: 回答忠於檢索內容
- **Answer Point Coverage > 0.6**: 回答涵蓋了大部分關鍵要點
- **Semantic Similarity > 0.7**: 回答與參考答案語意接近
- 比較不同 Question Type 的表現差異，找出系統弱點
- 比較 `--graph` vs `--no-graph` 結果可量化 Neo4j 知識圖譜對檢索品質的貢獻
