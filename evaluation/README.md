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
│       ├── reference_based.py   # BLEU, ROUGE, BERTScore
│       ├── ragas_eval.py        # RAGAS 框架指標
│       ├── llm_judge.py         # 自訂 Answer Point Coverage
│       └── semantic_similarity.py
├── templates/
│   └── dashboard.html.j2       # 儀表板模板
└── results/                     # 輸出目錄
```

## 前置條件

1. **後端服務運行中**：
   ```bash
   # 在專案根目錄
   docker compose up -d
   ```
2. **`.env` 設定正確**：確認 `ANTHROPIC_API_KEY`、PostgreSQL 連線設定

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

### 參考指標（套件）
| 指標 | 說明 |
|------|------|
| BLEU | 基於 n-gram 的翻譯品質 |
| ROUGE-1/2/L | 基於 n-gram 的摘要品質 |
| BERTScore | BERT 嵌入的語意相似度 |

### LLM 評估指標
| 指標 | 框架 | 說明 |
|------|------|------|
| Faithfulness | RAGAS | 回答是否忠於 context |
| Answer Relevancy | RAGAS | 回答是否切題 |
| Context Precision | RAGAS | 相關 context 排序品質 |
| Context Recall | RAGAS | context 的完整性 |
| Answer Correctness | RAGAS | 綜合正確性 |
| Answer Point Coverage | 自訂 | 答案要點覆蓋率 |

### 語意指標
| 指標 | 說明 |
|------|------|
| Semantic Similarity | RAG 回答與參考答案的餘弦相似度 |

## 結果

評估完成後，在 `results/` 目錄下會產生：
- `raw_responses.json` — RAG 原始回應（支援中斷續傳）
- `evaluation_results.json` — 完整評估結果
- `dashboard.html` — 互動式視覺化儀表板

開啟 `results/dashboard.html` 查看互動式報告。

## 結果解讀

- **Hit Rate > 0.8**: 檢索系統基本可靠
- **Faithfulness > 0.7**: 回答忠於檢索內容
- **Answer Point Coverage > 0.6**: 回答涵蓋了大部分關鍵要點
- **Semantic Similarity > 0.7**: 回答與參考答案語意接近
- 比較不同 Question Type 的表現差異，找出系統弱點
