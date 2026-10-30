# Bible RAG Evaluation System

針對 Bible GraphRAG 系統的完整評估框架，結合 RAGAS 與自訂指標，使用 Claude API 作為 LLM 評估模型。

## 架構

```
evaluation/
├── run_eval.py                  # CLI 入口(完整管線:收集 → 評估 → 視覺化)
├── quick_retrieval_eval.py      # 快速檢索評估迴圈(retrieval-only,無生成/RAGAS)
├── ab_compare.py                # 兩個 quick eval 結果的配對 A/B / --require-identical 一致性檢查
├── quick_faithfulness_eval.py   # 快速 faithfulness 重判迴圈(只跑兩個 faithfulness judge)
├── experiments/                 # 各實驗的事前登記、題號檔與腳本
│   ├── 2026-10-03_event_registry/   # event_registry 附加槽的檢索 A/B、AA 校準與答案端探針
│   ├── 2026-10-08_r1/           # R1 評估的事前登記與凍結(freeze_r1.py、frozen_r1.json)
│   └── 2026-10-09_r2/           # R2 評估的事前登記與凍結(freeze_r2.py)
├── src/
│   ├── config.py                # 讀取 ../.env(共用)+ ./.env(eval 專屬,優先)
│   ├── models.py                # Pydantic 資料模型
│   ├── data_loader.py           # 依 --gt v1|v2 載入 GT(v2 經 gt_v2 雜湊與凍結檢查)
│   ├── gt_v2.py                 # 只載入凍結的 ground_truth.v2.json(refs、gold_slots)
│   ├── reference_parser.py      # 解析中文經文引用(ragcommon.refs strict)
│   ├── book_names.py            # 來源書名 → book_id(ragcommon.books)
│   ├── slot_coverage.py         # GT v2 節位覆蓋量尺(slot_universe、兩臂來源 → slot)
│   ├── provenance.py            # 結果 meta:data_build_id、gt_version、gt_sha、編碼指紋;run_meta.json 讀寫
│   ├── run_record.py            # run_meta.json v2:收集紀錄、eval 程式 git 狀態、backend 容器快照(白名單 env)
│   ├── result_audit.py          # evaluation_results.json 稽核 meta:invalid_counts/ids、eval_run、run_meta
│   ├── relevance_judge.py       # 檢索相關性判斷
│   ├── rag_client.py            # httpx 呼叫 RAG API
│   ├── context_blocks.py        # 生成器同款 context 區塊格式 + 經節/pericope id 判別
│   ├── content_fetcher.py       # asyncpg 重建生成器同款 context(舊後端 / 舊 checkpoint)
│   ├── collector.py             # 回應收集(每次從頭收集、逐題落檔;沒有續收)
│   ├── evaluator.py             # 主要協調器
│   ├── visualizer.py            # Plotly 視覺化
│   ├── llm/served_models.py     # judge API 實際回報的模型名稱計數
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
├── results_quick/               # quick_retrieval_eval.py / quick_faithfulness_eval.py 輸出
└── archive/round3_2026-09/      # Round 3 三組態 500 題存檔(legacy build;d248f18)
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
> R1/R2 的 backend 只有 `event_registry` 這一條圖譜策略:`--graph-strategies event_registry` 指定它,只寫 `--graph-strategies` 不帶值 = 全關;`all`、`graph_event` 等舊策略會被拒絕。Round 3 的三組態存檔(全開,2026-09)已搬到 `archive/round3_2026-09/`,只能用 legacy 映像重現。
> 輸出目錄裡若有 2026-10 前的存檔(記錄沒有 `graph_strategies` 欄位),collector 會拒絕覆寫,請先移走或 commit。
> 每筆 `raw_responses.json` 記錄另帶 `graph_strategies`(backend 實際生效的策略;缺欄位 = 舊版全開)。

兩種模式的輸出會自動分到不同目錄，方便對照比較:

```bash
# 比較兩組 CSV
diff <(cut -d, -f1-10 results_graph/evaluation_results.csv) \
     <(cut -d, -f1-10 results_no_graph/evaluation_results.csv)

# 確認模式正確標記(mode = 收集時的 CLI 旗標,是權威的臂標記)
jq '[.[] | .mode] | unique' results_graph/raw_responses.json     # → ["graph"]
jq '[.[] | .mode] | unique' results_no_graph/raw_responses.json  # → ["no_graph"]
jq '[.[] | .mode] | unique' results_semantic/raw_responses.json  # → ["semantic"]
jq '.collection.mode' results_graph/run_meta.json                 # → "graph"
```

> `use_graph` 是 backend 回報的 per-request graph 開關,不是臂標記:`--semantic` 的請求不帶 `use_graph`,backend 就回報 `RAG_USE_GRAPH`(true),所以不論新舊 checkpoint,semantic 臂的 `use_graph` 都是 true(10-26 的 `results_semantic` 500/500 為 true),不能拿來分臂。分臂一律看 `mode`;2026-10-28 前的 checkpoint 沒有 `mode`,只能靠輸出目錄分臂。

**閘道規則**(`--no-graph` 時跳過):
- R3 person → 略過 `graph_person`，保留 semantic + SQL supplement
- R4 event → 略過 `graph_event`
- R5 cross-ref → 略過 `cross_reference` 與 `graph`(以及 `graph_event`)
- R3/R4/R5/R6 的 `entity_path`、`cross_ref_expand`、`entity_query` 也一併略過
- R6 place → 略過 `graph_place`
- R1/R2/fallback 不受影響(本來就沒用 Neo4j)

每筆 `raw_responses.json` 記錄帶 `mode`(graph / no_graph / semantic / default,依 CLI 旗標)標記這次收集的臂,`use_graph` 則是 backend 回報的值(見下節「事後稽核紀錄」)。

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

**GT 版本與 build。** `--gt v1|v2` 選 GT(預設讀設定 `EVAL_GT_VERSION`,未設為 v2;v1 只能評 legacy-20261004);v2 一律經 `gt_v2.py` 的 sha256 與 `config/gold/gt_v2_freeze.json` 檢查。backend 的 `/api/v1/health` 決定受測 build:沒回 `build_id` 的就是 `legacy-20261004`,編碼指紋取 health 的 `encoder`(沒有記 null)。legacy 以外的 build 只能用 `--gt v2`。GT v2 下 `verse_recall_at_k` / `anchor_coverage_at_k` 改在 GT 檔頭的 `slot_universe` 上算:gold 直接讀 `gold_slots`(缺號槽不算 gold),兩臂都以實際節位集合計算;legacy 來源依舊編號對到節位(幽靈節落在缺號槽),新 build 的來源讀 `$RAG_STORE/contracts/<build_id>/verse_index.json`(`--contracts-dir` 可指定,manifest 的 build_id 與 sha256 須相符),有 `start_key`/`end_key` 就依序取區間,合併節整個 unit 計入。`--contracts-dir` 只有在 `/health` 完全沒回 `build_id` 時才能替 run 命名 build;`/health` 或 checkpoint 的 `run_meta.json` 已寫明 build(包括明確的 `legacy-20261004`)時,指到別的 build 一律拒絕。兩臂互不收對方的來源:標成 legacy 的 run 遇到新 build 形狀的來源(有 `kind`、`start_key`/`end_key` 或合乎 ragcommon.ids 的 id)會報錯,標成新 build 的 run 遇到 legacy 形狀的來源也會報錯(多半是 `BACKEND_URL` 還指著 legacy prod);hit_rate、MRR 等單位指標與 `source_detail` 的 `gold` 也改為「來源含 gold 節位」(NDCG 的分級仍依 reference)。每份輸出的 `meta` 記 `data_build_id`、`gt_version`、`gt_sha`、`encoder_fingerprint`;`--from-raw` 從 checkpoint 旁的 `run_meta.json` 讀 build(沒有此檔即 legacy)。完整管線 `run_eval.py` 也有 `--gt` / `--contracts-dir`,收集時寫 `run_meta.json`,`evaluation_results.json` 的 meta 記同樣四個欄位。

```bash
# legacy 在 GT v2 量尺下的基線
uv run python quick_retrieval_eval.py --gt v2 --top-k 5 --metric-k 6 --label legacy_gtv2
```

輸出存至 `results_quick/<label>.json`，含 overall / by_type 聚合與逐題明細（route、strategies、sources、rerank/fused 分數）。每段 `source_detail` 另記 `found_by`(所有找到它的策略)與 `gold`(是否與 reference 經文重疊);基礎設施失敗(0 source 且有 strategy_errors)標 `invalid`,不進平均。`--metric-k N` 以前 N 段計分(預設 = `--top-k`),`--ids-file` 只跑指定題號。

`--include-context` 會在請求帶 `include_context=true`,把生成器實際讀到的 context 區塊(標頭 + 經文)做 sha256:每段 `source_detail` 記 `context_sha256`,每題記 `context_sha`(全部區塊依序以空行串接,即生成器看到的整段文字)。`config.include_context` 記錄有沒有開。backend 若沒回 context(舊 image)會直接報錯,不會記成空字串的雜湊。

#### 配對 A/B 比較（ab_compare.py）

逐題配對比較兩個 quick eval 結果(同路由題):主檢定 sign-flip permutation,並列精確符號檢定(勝負題數)、95% bootstrap CI、指標族 Holm 校正;分全體 / 被改動題 / 原 100 / 擴充 400 報告;列出每個指標變差的題與改動帳本(identical / order_only / nongold_swap / gold_in / gold_out / gold_swap)。所有比較的檔案必須以同一個 metric k、同一個 metric_version 計分,且 meta 的 `gt_version`、`gt_sha` 相同(沒有 meta 的舊檔只能和同樣沒有 meta 的檔比),否則直接拒絕;`data_build_id` 不同是允許的(R1 就是比不同 build),報告的 `builds` 與輸出第一行列出兩臂的 build。

附加軌(`event_registry`)會在 top-5 後多附加一段,被附加的題必須和**獨立的 top_k=6 請求**比(chapter-pin 依 top_k 運作,k=7 結果的前綴不等於 k=6):

```bash
uv run python quick_retrieval_eval.py --graph-strategies event_registry --metric-k 6 --label aux
uv run python quick_retrieval_eval.py --no-use-graph --metric-k 6 --label dense5
# touched.txt = aux 中 sources 超過 5 段的題號
uv run python quick_retrieval_eval.py --no-use-graph --top-k 6 --metric-k 6 --ids-file touched.txt --label dense6
uv run python ab_compare.py results_quick/dense5.json results_quick/aux.json --control-ext results_quick/dense6.json --label aux_vs_dense
```

`--require-identical` 改跑一致性檢查(不出統計報告):同路由題的 core(前 top_k 段)、附加段落(超過 top_k 的段落)與 `context_sha` 必須全部相同,兩邊逐題與整體的 `graph_strategies_applied` 也必須相同;invalid 題、只出現在一邊的題同樣算失敗。任何不同都列出明細並以結束碼 1 結束。路由不同的題另外列出,不判失敗:這時 PASS 會註明有幾題沒判(`identity: PASS (N route mismatches not judged; re-ask them)`),要先用 `--ids-file` 重問這些題,才能把 PASS 當成「完全相同」。沒有 `context_sha` 的舊檔(沒用 `--include-context` 跑的)直接拒絕。

```bash
uv run python ab_compare.py results_quick/control.json results_quick/treatment.json --require-identical
```

### 快速 faithfulness 重判迴圈（quick_faithfulness_eval.py）

只跑兩個 faithfulness judge(zh + strict),不跑其他 RAGAS 指標與 coverage;用來重判既有答案、A/B judge prompt 或 context 格式。每題逐句的 statement / verdict / reason 都寫進輸出,可直接審計:

```bash
# 對 run of record 重判(舊 checkpoint 會自動用 DB 重建含標頭 context)
uv run python quick_faithfulness_eval.py --results-dir results_graph --out results_quick/faith_metric_validation.json

# 只重判幾題(除錯 judge)
uv run python quick_faithfulness_eval.py --results-dir results_graph --out results_quick/faith_smoke.json --ids VERSE_LOOKUP_017,VERSE_LOOKUP_067
```

輸出含 `stored_faithfulness`(該目錄 evaluation_results.json 裡的舊值,只在新 judge 有效評分的題目上配對平均)方便看修前修後差異;`meta.context_format` 記錄 judge 看到的 context 形式。

build 取自 checkpoint 旁的 `run_meta.json`(沒有此檔即 legacy);新 build 的 checkpoint 只能用 `--gt v2` 重判(`--contracts-dir` 規則同上)。`meta` 記 `data_build_id`、`gt_version`、`gt_sha`、`encoder_fingerprint`。

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
| verse_recall_at_k | gold 經節(GT v2:gold_slots)被前 k 段覆蓋的比例 |
| anchor_coverage_at_k | 逐章 anchor 至少中一節的比例 |

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
- `raw_responses.json` — RAG 原始回應(含 `mode` 臂標記、intent、檢索統計、收集時間與耗時)
- `run_meta.json` — 這次收集的紀錄(build、編碼指紋;v2 起另有收集參數、程式版本、backend 容器快照)
- `evaluation_results.json` — 完整評估結果
- `evaluation_results.csv` — 每題逐筆指標(可用試算表打開)
- `dashboard.html` — 互動式視覺化儀表板

開啟 `<輸出目錄>/dashboard.html` 查看互動式報告。

## 事後稽核紀錄（2026-10-28 起）

目標:每次 run 事後不靠 `docker inspect`、容器 log 或 git 考古就能還原「用什麼系統、什麼設定、judge 怎麼判」。舊 checkpoint 一律照讀,新欄位都是選填(沒有就記 null),`--eval-only` 不會因此被擋。

### raw_responses.json 每題新增欄位

| 欄位 | 來源 | 說明 |
|------|------|------|
| `mode` | CLI 旗標 | `graph` / `no_graph` / `semantic` / `default`;**權威的臂標記** |
| `use_graph` | backend `retrieval_stats.use_graph` | 原樣記錄,缺欄位記 null(不再預設 true);請求失敗的題記 null。**semantic 臂會是 true**(請求不帶 `use_graph`,backend 回報 `RAG_USE_GRAPH`),不能分臂 |
| `intent` | backend `intent` | `{type, entities, verse_refs, rejected_refs}` 原樣 |
| `fusion_alpha`、`total_candidates`、`reranked_top_k`、`event_registry_events` | backend `retrieval_stats` | 原樣,缺欄位記 null |
| `collected_at` | collector | ISO 8601,含時區 |
| `latency_ms` | collector | 該題請求耗時(含重試與重試間的等待) |
| `request_attempts` | collector | 第幾次請求成功(失敗題 = 3) |

### run_meta.json v2

既有的 `data_build_id`、`encoder_fingerprint` 語意不變。收集開始時寫一次(`finished_at` 為 null),結束時補 `finished_at` 與題數;中途中斷時至少 `started_at` 已落檔。寫檔走暫存檔再 rename,不會留下半個檔。

| 欄位 | 說明 |
|------|------|
| `run_meta_version` | 2 |
| `collection` | `started_at`、`finished_at`、`mode`、`argv`、`top_k`、`graph_strategies_requested`、`ids_file` 與 `ids_file_sha256`、`n_questions`、`n_collected`、`n_request_failures`、`resumed`(collector 每次從頭收集,沒有續收,恆為 `[]`) |
| `eval_code` | `git_head`、`git_dirty`、`dirty_paths`(`git status --porcelain` 在 evaluation/ 底下的路徑,最多 50 條)、`n_dirty_paths`;未追蹤的 `results*/` 輸出目錄會列出但不算 dirty |
| `backend_runtime` | `docker inspect`(唯讀)backend 容器:`container`、`container_from`(容器名從哪來:`BACKEND_URL` 或 `EVAL_BACKEND_CONTAINER`)、`image`(Config.Image)、`image_id`、`started_at`、`env`(白名單,見下) |
| `generator` | `provider`、`model`;`LLM_PROVIDER=ollama` 時另查 `OLLAMA_BASE_URL/api/tags` 記 `digest`、`size`(回應形狀不對時記 error) |
| `backend_health` | `/health` 的 `status`、`services` 與 handshake 摘要 `ok`、`strict`、`mismatches` |

每個探測都是盡力而為:docker 不可用、容器不存在、逾時(5 秒)、Ollama 不通或回應形狀不對、不是 git checkout,或任何預期外的例外時,該段記 `{"error": "..."}` 並記 warning,收集照常進行。容器名用 `EVAL_BACKEND_CONTAINER`;沒設時(預設)取本機正在發布 `BACKEND_URL` 那個 port 的容器(`docker ps --filter publish=<port>`,唯讀),所以收 staging(`BACKEND_URL=http://localhost:8002`)會記到 staging 容器。找不到或不只一個、或 `BACKEND_URL` 不在本機時記 error。2026-10-29 前預設寫死 `bible_rag_backend`,收 staging 的 run_meta 會記成 prod 容器。

**backend env 的秘密白名單規則**(`src/run_record.py` `safe_env`):名稱一律轉大寫再比對(backend 的 pydantic settings 讀 env 不分大小寫),只記
1. 明列的名稱:`LLM_PROVIDER`、`OLLAMA_MODEL`、`CLAUDE_MODEL`、`OPENAI_MODEL`、`GEMINI_MODEL`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`RAG_RANK_FUSION_ALPHA`、`RAG_USE_GRAPH`、`RAG_GRAPH_STRATEGIES`、`RAG_ENTITY_QUERY_TOP_K`、`STRICT_BUILD_CHECK`、`HYBRID_SEARCH_ENABLED`、`HYBRID_FUSION_METHOD`、`HYBRID_PREFETCH_LIMIT`;
2. 其他 `RAG_` 開頭、且名稱不含 `KEY`/`SECRET`/`TOKEN`/`PASSWORD`/`PASS`/`PWD`/`AUTH`/`CRED`/`DSN`/`PRIVATE`/`CERT` 的變數。

其餘一律不記(API key、`POSTGRES_PASSWORD`、`NEO4J_PASSWORD`、`GPG_KEY`、`PATH` …)。留下的值再遮兩層:含帳密的 URL(`scheme://user:pass@host`)把 `://` 到最後一個 `@` 之間改成 `***`(密碼含 `/`、`@` 也遮得到);值本身像金鑰(`sk-`、`ghp_`、`github_pat_`、`AKIA`、`AIza`、`xoxb-`、`hf_` 等開頭,或 24 字元以上、字母數字混合、無分隔的字串,例如 hex digest、base64)時整個改成 `***`。新增白名單名稱前先確認它不可能放秘密(`tests/test_run_record.py` 驗證含 `ANTHROPIC_API_KEY`、`POSTGRES_PASSWORD` 的 env 不會進 run_meta)。

### evaluation_results.json / .csv

`meta` 新增:

| 欄位 | 說明 |
|------|------|
| `invalid_counts` / `invalid_ids` | 每個指標的無效題數與題號(經過與平均相同的 infra 失敗處理);原因在各題的 `rationale.errors`(RAGAS)、`rationale.coverage_error`(coverage)、`strategy_errors`(基礎設施)。這次應評的指標(RAGAS 各指標與 `answer_coverage`)即使沒有任何分數也會列出 |
| `unscored_ids` | 每個指標「完全沒有分數」的題號(既非有效也非無效):RAGAS 會跳過沒有答案或沒有 contexts 的題,整個 RAGAS run 失敗時則全部沒有分數(原因在 `rationale.errors.ragas`)。該指標的實際分母 = 題數 − `unscored_ids` − `invalid_ids` |
| `eval_run` | `started_at`、`finished_at`、`argv`、`git_head`、`git_dirty`、`dirty_paths`(取不到 git 時另有 `git_error`) |
| `run_meta` | checkpoint 旁 run_meta.json 的 v2 各段原樣嵌入(`run_meta_version`、`collection`、`eval_code`、`backend_runtime`、`generator`、`backend_health`);沒有 run_meta.json 記 null,舊版檔各段記 null |
| `judge_served_models` | judge API 回覆裡實際寫的模型名稱與次數(coverage 的 `judge_completion` 與 RAGAS 經 LangChain 的呼叫都算);沒有任何回覆帶模型名稱時不加這欄 |

每題 `samples[]` 新增 `intent`、`mode`(從 raw 讀,舊 checkpoint 為 null),`strategy_errors` 改為帶入該題實際值;`rationale` 新增:

- `coverage_points`:`[{index, point, verdict, reason}]`,每個應涵蓋重點的 judge 判定(`verdict` 為 null = judge 沒給合法判定)。
- `coverage_error`:coverage 無效的原因 —— `no_expected_points`、`unparseable`、`incomplete_verdicts: ...`(列出缺判定的重點與回覆的毛病)、`judge_error: <例外>`、`internal_error: <例外>`(該題處理時的預期外錯誤;只有該題無效,其他題照常計分)。
- `coverage_raw`:無效時,或雖然計分但回覆有毛病時(`coverage_problems` 非空),judge 的最後一次原始回覆(截斷 8000 字元);乾淨的有效回覆記 null。
- `coverage_attempts`:judge 呼叫次數(0 = 沒送 judge:沒有重點或空答案)。
- `coverage_problems`:最後一次回覆的毛病,計分的題也記(同一 index 出現兩次、以後者為準;多出超出範圍的項目;壞 JSON 改用樣式讀取……)。
- `coverage_salvaged`:最後一次回覆是壞 JSON、逐項用樣式讀出 index 與 verdict。
- `coverage_retry`:有重問時 `{why, same_reply}`:第一次回覆為何要重問,以及重問拿到的回覆是否與第一次一字不差(`same_reply` 為 null = 重問那次丟例外)。
- `errors`:RAGAS 指標無效的原因 `{"ragas_<指標>": "TimeoutError: ..."}`(沒有例外卻是 NaN 也會註明);整個 RAGAS run 失敗時是 `{"ragas": "evaluate() failed: ..."}`。

**coverage 判定規則**:judge 回覆若有任何重點沒有合法判定(缺 index、index 不是整數或超出範圍、判定不是 covered/partial/missing),或整段無法解析,先重問一次;重問的 prompt 會在最後附上「上一次缺第幾點/不是合法 JSON,請輸出全部 N 項」,避免 temperature 0 的 judge(例如本機 gemma)原樣重複同一段回覆。重問後仍不完整,該題 coverage 記無效並保存原始回覆,不再把缺的重點默默當 missing 計 0。judge 呼叫丟例外則直接記無效並保存例外訊息。壞 JSON 時逐項(`{` 到 `{`)用樣式讀 index 與 verdict 配對,判定掛在 judge 寫的 index 上,不再依出現順序;沒有自己 index 的 verdict 不填任何重點 —— 和合法 JSON 缺 index 的處理一致。完整、合法的回覆計分與過去完全相同(covered 1 / partial 0.5 / missing 0 平均,四捨五入到 4 位)。`quick_faithfulness_eval.py --coverage` 的每列也有同樣的 `coverage_*` 欄位;qfe 每列另有 `judge_errors`(faithfulness judge 失敗的原因,同 `rationale.errors`)。

`src/metrics/coverage_eval.py` 的 `_parse_verdicts` 保留 2026-10-28 前的回傳形狀(`list[str]`,缺的重點補 `missing`),只給 store 封存的重判腳本重現舊分數用;評估管線改用 `_read_verdicts`。

`evaluation_results.csv` 在最後加 `intent_type`、`mode` 兩欄,原有欄位順序不變。

## 結果解讀

- **Hit Rate > 0.8**: 檢索系統基本可靠(章範圍題會灌水,以 verse_recall_at_k 為準)
- **Faithfulness**: 主讀數看 `ragas_faithfulness`(2026-07-15 run 重判 0.987);`ragas_faithfulness_strict` 作守門,run 平均 ≥ 0.97、題型 ≥ 0.95(實測 0.981,`results_quick/faith_metric_validation.json`);舊版(無標頭 judge,0.912)數字不可與新數字互比
- **Answer Point Coverage > 0.6**: 回答涵蓋了大部分關鍵要點
- **Semantic Similarity > 0.7**: 回答與參考答案語意接近
- 比較不同 Question Type 的表現差異，找出系統弱點
- 比較 `--graph` vs `--no-graph` 結果可量化 Neo4j 知識圖譜對檢索品質的貢獻
