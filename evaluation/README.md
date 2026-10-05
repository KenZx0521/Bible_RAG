# Bible RAG Evaluation System

針對 Bible GraphRAG 系統的完整評估框架，結合 RAGAS 與自訂指標，使用 Claude API 作為 LLM 評估模型。

## 架構

```
evaluation/
├── run_eval.py                  # CLI 入口(完整管線:收集 → 評估 → 視覺化)
├── quick_retrieval_eval.py      # 快速檢索評估迴圈(retrieval-only,無生成/RAGAS)
├── ab_compare.py                # 兩個 quick eval 結果的配對 A/B / --require-identical 一致性檢查
├── d3_gate.py                   # D3 非劣閘門(兩個 backend 跑 500 題 → 一致性 + 路由殘差判定)
├── xref_ab_slice.py             # opt-in xref A/B 的 touched 題數與 kg_xref 切片(W1,只報告;見 docs/staging_promotion.md)
├── quick_faithfulness_eval.py   # 快速 faithfulness 重判迴圈(只跑兩個 faithfulness judge)
├── apply_coverage.py            # 答案要點覆蓋率離線補算
├── experiments/                 # 各實驗的事前登記、題號檔與腳本
│   ├── 2026-10-03_event_registry/   # event_registry 附加槽的檢索 A/B、AA 校準與答案端探針
│   └── 2026-10-05_kg_w1/        # W1 升版第 1 步的 20 題煙霧測試題號檔
├── src/
│   ├── config.py                # 讀取 ../.env(共用)+ ./.env(eval 專屬,優先)
│   ├── models.py                # Pydantic 資料模型
│   ├── data_loader.py           # 載入 ground_truth.json
│   ├── reference_parser.py      # 解析中文經文引用
│   ├── relevance_judge.py       # 檢索相關性判斷
│   ├── rag_client.py            # httpx 呼叫 RAG API
│   ├── context_blocks.py        # 生成器同款 context 區塊格式 + 經節/pericope id 判別
│   ├── content_fetcher.py       # asyncpg 重建生成器同款 context(舊後端 / 舊 checkpoint)
│   ├── collector.py             # 回應收集 (支援中斷續傳)
│   ├── evaluator.py             # 主要協調器
│   ├── visualizer.py            # Plotly 視覺化
│   └── metrics/
│       ├── retrieval.py         # 7 個檢索指標
│       ├── ragas_eval.py        # RAGAS 框架指標
│       ├── faithfulness_zh.py   # zh / strict 兩個 faithfulness judge(共用陳述拆解)
│       ├── coverage_eval.py     # 答案要點覆蓋率
│       └── semantic_similarity.py
├── templates/
│   └── dashboard.html.j2       # 儀表板模板
├── tests/                       # pytest(uv run python -m pytest tests -q)
├── results/                     # 預設輸出目錄(無 --graph/--no-graph)
├── results_graph/               # --graph 模式輸出(--no-graph → results_no_graph/)
├── results_*_answer/            # 生成端 LLM 對照組(claude/gemma × graph/semantic)
└── results_quick/               # quick_retrieval_eval.py / quick_faithfulness_eval.py 輸出
```

## 前置條件

1. **後端服務運行中**：
   ```bash
   # 在專案根目錄
   docker compose up -d
   ```
2. **`.env` 設定正確**（兩層）：
   - 專案根目錄 `.env`：共用基礎設施 — `ANTHROPIC_API_KEY`、PostgreSQL 連線、`OLLAMA_BASE_URL`
   - `evaluation/.env`：eval 專屬參數 — `EVAL_LLM_PROVIDER`、`EVAL_*_MODEL`、`BACKEND_URL`、`TOP_K`、`REQUEST_DELAY`、`EVAL_RAGAS_*`、`EVAL_FAITHFULNESS_STRICT`（範本：`evaluation/.env.example`；同名變數以此檔為準）
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

# 舊 checkpoint(2026-09 前收集,sources 沒有 context 區塊)要重判 faithfulness 時,
# 用資料庫重建生成器同款「標頭 + 經文」context,否則出處句會被 judge 判為無支持
uv run python run_eval.py --eval-only --rebuild-contexts
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

> **2026-10 起 `--graph` 不再等於「全部圖譜策略」**:backend 預設 `RAG_GRAPH_STRATEGIES=["event_registry"]`(2026-10-04 起;只在 top-k 後附加 curated 事件錨點,之前是 `["graph_event"]`)。附加軌會讓部分題的 sources 多一段,檢索指標要用 `--metric-k 6` 並以 `ab_compare.py --control-ext` 對 k 對齊的 dense 比較。
> 要重現 Round 3 的 `results_graph/`(全開),加 `--graph-strategies all`;
> `--graph-strategies graph_event graph_person` 指定子集,只寫 `--graph-strategies` 不帶值 = 全關。
> 輸出目錄裡若有 2026-10 前的存檔(記錄沒有 `graph_strategies` 欄位),collector 會拒絕覆寫,請先移走或 commit。
> 每筆 `raw_responses.json` 記錄另帶 `graph_strategies`(backend 實際生效的策略;缺欄位 = 舊版全開)。

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
- R5 cross-ref → 略過 `cross_reference` 與 `graph`(以及 `graph_event`)
- R3/R4/R5/R6 的 `entity_path`、`cross_ref_expand`、`entity_query` 也一併略過
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

輸出存至 `results_quick/<label>.json`，含 overall / by_type 聚合與逐題明細（route、strategies、sources、rerank/fused 分數）。每段 `source_detail` 另記 `found_by`(所有找到它的策略)與 `gold`(是否與 reference 經文重疊);基礎設施失敗(0 source 且有 strategy_errors)標 `invalid`,不進平均。`--metric-k N` 以前 N 段計分(預設 = `--top-k`),`--ids-file` 只跑指定題號。

`--include-context` 會在請求帶 `include_context=true`,把生成器實際讀到的 context 區塊(標頭 + 經文)做 sha256:每段 `source_detail` 記 `context_sha256`,每題記 `context_sha`(全部區塊依序以空行串接,即生成器看到的整段文字)。`config.include_context` 記錄有沒有開。backend 若沒回 context(舊 image)會直接報錯,不會記成空字串的雜湊。

#### 配對 A/B 比較（ab_compare.py）

逐題配對比較兩個 quick eval 結果(同路由題):主檢定 sign-flip permutation,並列精確符號檢定(勝負題數)、95% bootstrap CI、指標族 Holm 校正;分全體 / 被改動題 / 原 100 / 擴充 400 報告;列出每個指標變差的題與改動帳本(identical / order_only / nongold_swap / gold_in / gold_out / gold_swap)。所有比較的檔案必須以同一個 metric k 計分,否則直接拒絕。

附加軌(`event_registry`)會在 top-5 後多附加一段,被附加的題必須和**獨立的 top_k=6 請求**比(chapter-pin 依 top_k 運作,k=7 結果的前綴不等於 k=6):

```bash
uv run python quick_retrieval_eval.py --graph-strategies event_registry --metric-k 6 --label aux
uv run python quick_retrieval_eval.py --no-use-graph --metric-k 6 --label dense5
# touched.txt = aux 中 sources 超過 5 段的題號
uv run python quick_retrieval_eval.py --no-use-graph --top-k 6 --metric-k 6 --ids-file touched.txt --label dense6
uv run python ab_compare.py results_quick/dense5.json results_quick/aux.json --control-ext results_quick/dense6.json --label aux_vs_dense
```

`--require-identical` 改跑一致性檢查(不出統計報告):同路由題的 core(前 top_k 段)、附加段落(超過 top_k 的段落)與 `context_sha` 必須全部相同,兩邊逐題與整體的 `graph_strategies_applied` 也必須相同;invalid 題、只出現在一邊的題同樣算失敗。任何不同都列出明細並以結束碼 1 結束。路由不同的題另外列出,不判失敗:這時 PASS 會註明有幾題沒判(`identity: PASS (N route mismatches not judged; run d3_gate.py)`),重問與路由殘差 ≤ r0 的判定只有 `d3_gate.py` 會做,所以 D3 閘門一律跑 `d3_gate.py`,`--require-identical` 只當診斷用。沒有 `context_sha` 的舊檔(沒用 `--include-context` 跑的)直接拒絕。

```bash
uv run python ab_compare.py results_quick/d3_prod_w1.json results_quick/d3_stg_w1.json --require-identical
```

#### D3 非劣閘門（d3_gate.py）

KG 資料層修復第 1 批的硬門檻(`docs/records/2026-10-04_kg_batch1_plan.md` §5.1):prod 與 backend-staging 各跑一次 500 題(`quick_retrieval_eval.py --top-k 5 --metric-k 6 --include-context`,以 `BACKEND_URL` 指向各自的 backend),再做 `--require-identical` 比對。路由不同的題兩邊各重問(`--ids-file`),最多 2 輪,重問結果要和原檔的 top_k / metric_k / metric_version / include_context 等設定相同、題號完全對上才併回去。判定:

- 兩邊的 `graph_strategies_applied` 相同;
- 同路由題 100% 相同;
- invalid 為 0;
- 重問後仍路由不同的題數(路由殘差)≤ r0(`--route-residual-max`)。r0 由 W0 的 AA 演練用 `--calibrate` 量出,這時只記錄殘差、不判這一條。

```bash
# W0 AA:量 r0
.venv/bin/python d3_gate.py --label w0_aa --control-url http://localhost:8000 --treatment-url http://localhost:8001 --calibrate
# W1 / W2 閘門
.venv/bin/python d3_gate.py --label w1 --control-url http://localhost:8000 --treatment-url http://localhost:8001 --route-residual-max <r0>
# 只重判 live 閘門存下的合併結果檔(不重跑查詢、不重問)
.venv/bin/python d3_gate.py --label w1_files --control-file results_quick/d3_prod_w1_merged.json --treatment-file results_quick/d3_stg_w1_merged.json --route-residual-max <r0>
```

兩邊的結果檔是 `results_quick/d3_prod_<label>.json`、`d3_stg_<label>.json`(重問為 `..._retry1/2.json`,名稱可用 `--control-name` / `--treatment-name` 改);這兩個原始檔保留第一次的回答,併入重問結果後的最終版另存為 `d3_prod_<label>_merged.json`、`d3_stg_<label>_merged.json`,對它們跑檔案模式才會重現 live 的判定(對原始檔跑,有重問過的題仍會算成路由殘差)。完整報告(各輪重問、判定項、所有差異明細、`merged_runs` 路徑)寫到 `results_quick/d3_<label>.json`;通過結束碼 0,否則 1。這些檔案已存在時拒絕執行,要覆寫請加 `--overwrite`(檔案模式只檢查報告檔);報告路徑若就是 `--control-file` / `--treatment-file` 之一(例如 `--label prod_s1` 配 `d3_prod_s1.json`),加 `--overwrite` 也一律拒絕。staging 端必須跑「由該波 HEAD 建出的 image」。

### 快速 faithfulness 重判迴圈（quick_faithfulness_eval.py）

只跑兩個 faithfulness judge(zh + strict),不跑其他 RAGAS 指標與 coverage;用來重判既有答案、A/B judge prompt 或 context 格式。每題逐句的 statement / verdict / reason 都寫進輸出,可直接審計:

```bash
# 對 run of record 重判(舊 checkpoint 會自動用 DB 重建含標頭 context)
uv run python quick_faithfulness_eval.py --results-dir results_graph --out results_quick/faith_metric_validation.json

# 只重判幾題(除錯 judge)
uv run python quick_faithfulness_eval.py --results-dir results_graph --out results_quick/faith_smoke.json --ids VERSE_LOOKUP_017,VERSE_LOOKUP_067
```

輸出含 `stored_faithfulness`(該目錄 evaluation_results.json 裡的舊值,只在新 judge 有效評分的題目上配對平均)方便看修前修後差異;`meta.context_format` 記錄 judge 看到的 context 形式。

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
| `RAG_USE_CROSS_REF_EXPAND` | true | CROSS_REFERENCES N-hop 擴展（curated（`r.curated`）+ TSK 邊） |
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
| `backend/database/neo4j_db.py` | curated/TSK 判別 `_CURATED_XREF` | `r.curated` 旗標；過渡期無旗標的邊以 `r.source IN ['markdown', 'supplementary']` 推斷 |
| `backend/utils/retrieval/router.py` | chapter-pin | `min_pins=2`、weight ≥ 0.85 門檻 |
| 同上 | EQ pin（僅 fusion off 生效） | `score_threshold=0.5`、confidence gate 0.3、`max_pins=2` |
| 同上 | book_anchor pin（無條件）+ graph uncertainty pin（僅 fusion off） | `max_pins=2`、gate 0.3 |
| 同上 | keyword-exact event pin（僅 fusion on 生效） | `hub_cap=25`、`max_pins=2`、只取 `anchor_rank==0` |
| 同上 | book_anchor 檢索 | weight 0.9、top_k 10 |
| `backend/utils/reranker.py` | cross-encoder 截斷 | `max_length=512` |

注意：四個 pin 目前只隨 `fusion_active` 整組切換，**沒有獨立開關**——要單獨消融（例如量化 keyword pin 對 Acts 9 掃羅題的貢獻）需先加 flag。「no-rerank 純 weight 排序」目前僅是 reranker 失敗時的 fallback，也無開關。

### 第四級：資料與模型層（重建索引或圖譜）

- **TSK 邊**（~25 萬條）：整批 on/off，或按 `votes` 閾值分層過濾消融
- **curated cross-book 邊**（`r.curated = true`；W1 升版前以 source 推斷，916 條）：on/off
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
| Faithfulness (`ragas_faithfulness`) | RAGAS + 本地判準 | 回答是否忠於 context。**主讀數**:繁中 NLI judge,看得到使用者問題與生成器同款的 `[i] 書卷 第N章` 標頭;出處句、問題前提、標題句、題目要求的歸納不算捏造 |
| Faithfulness strict (`ragas_faithfulness_strict`) | RAGAS 預設 NLI prompt | 同一份含標頭 context、同一份繁中陳述拆解,用 RAGAS 0.4.3 原判準判。保守守門值(run ≥ 0.97 / 題型 ≥ 0.95,實測 0.981);`EVAL_FAITHFULNESS_STRICT=false` 可關 |
| Answer Relevancy | RAGAS | 回答是否切題(拒答句式會被硬扣 0,見 docs/records) |
| Context Recall | RAGAS | context 的完整性。**注意**:2026-09-17 起 judge 看到的 context 含標頭,與舊 run 的 context_recall 不可直接互比(`meta.context_format` 區分) |
| Answer Correctness | RAGAS | 綜合正確性(F1 懲罰詳盡,只作天花板參考) |

Faithfulness 的兩個 judge 共用一次陳述拆解;每題所有 statement/verdict/reason 存在 `rationale.faithfulness_statements`。
**judge 拿到的 context 必須與生成器看到的完全相同**(後端 `include_context=true` 回傳;舊 checkpoint 用 `--rebuild-contexts` 重建),否則「根據約翰福音第3章第16節」這類出處句會被判為無支持——2026-07-15 run of record 的 faithfulness 0.912 有約 3/4 的缺口是這個量尺假象(`docs/records/2026-09-10_faithfulness_audit.md`)。
RAGAS 會在每次呼叫時把 judge 溫度覆寫為 ~0.01,`langchain_factory` 的溫度設定對 RAGAS 指標無效。

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

- **Hit Rate > 0.8**: 檢索系統基本可靠(章範圍題會灌水,以 verse_recall_at_k 為準)
- **Faithfulness**: 主讀數看 `ragas_faithfulness`(2026-07-15 run 重判 0.987);`ragas_faithfulness_strict` 作守門,run 平均 ≥ 0.97、題型 ≥ 0.95(實測 0.981,`results_quick/faith_metric_validation.json`);舊版(無標頭 judge,0.912)數字不可與新數字互比
- **Answer Point Coverage > 0.6**: 回答涵蓋了大部分關鍵要點
- **Semantic Similarity > 0.7**: 回答與參考答案語意接近
- 比較不同 Question Type 的表現差異，找出系統弱點
- 比較 `--graph` vs `--no-graph` 結果可量化 Neo4j 知識圖譜對檢索品質的貢獻
