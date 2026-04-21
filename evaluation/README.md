# Bible RAG Evaluation System

針對 Bible GraphRAG 系統的完整評估框架，結合 RAGAS 與自訂指標，使用 Claude API 作為 LLM 評估模型。

## 架構

```
evaluation/
├── run_eval.py                  # CLI 入口
├── src/
│   ├── config.py                # 讀取 ../.env 設定
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
│       └── semantic_similarity.py
├── templates/
│   └── dashboard.html.j2       # 儀表板模板
├── results/                     # 預設輸出目錄(無 --graph/--no-graph)
├── results_graph/               # --graph 模式輸出
└── results_no_graph/            # --no-graph 模式輸出
```

## 前置條件

1. **後端服務運行中**：
   ```bash
   # 在專案根目錄
   docker compose up -d
   ```
2. **`.env` 設定正確**：確認 `ANTHROPIC_API_KEY`、PostgreSQL 連線設定
3. **(可選) Graph 檢索預設值**：在 `.env` 設定 `RAG_USE_GRAPH=true/false`，作為 backend 預設行為(CLI 未指定時生效)

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
