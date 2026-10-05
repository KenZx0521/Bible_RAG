# W1 升版第 1 步：20 題煙霧測試

- **用途**：`docs/records/2026-10-04_kg_batch1_plan.md` §1「W1 升版」第 1 步。先換上 R2 測過的 1B 過渡版 backend（`bible_rag-backend:w1` 改 tag 為 `latest`，不重建，見 `docs/staging_promotion.md`「W1 升版第 1 步」；資料仍是舊的），等 healthcheck 通過，再跑 20 題預設檢索。這只確認新 image 在各路由都能跑完，不量價值。
- **題號檔**：`smoke20_ids.txt`，一行一題，`quick_retrieval_eval.py --ids-file` 直接讀。

## 選題規則

選題於 2026-10-05 計算，來源是 `docs/records/2026-10-04_kg_fix/batch1/inputs/bench/questions_table.json`（500 題，sha256 `5b207bf9…`），依 `route_nograph` 分組。之後題目表若有變動，本檔不跟著重算。

1. **PERSON_QUESTION_053**：1B-C1 在舊資料上，262 題代理種子集中唯一改變候選集合的一題（R3，截斷處 luk:3:2 與 mat:10:0 互換）。
2. **R1–R6**：每條路由取排序後的前 3 題。R6 只有 10 題。
3. **fallback**：取排序後的第 1 題。

共 20 題，沒有重複。檔案順序就是上述順序。

| 組 | 題號 |
|---|---|
| C1 | PERSON_QUESTION_053 |
| R1 | GENERAL_BIBLE_QUESTION_042、GENERAL_BIBLE_QUESTION_060、TOPIC_QUESTION_083 |
| R2 | GENERAL_BIBLE_QUESTION_007、GENERAL_BIBLE_QUESTION_010、GENERAL_BIBLE_QUESTION_011 |
| R3 | EVENT_QUESTION_021、EVENT_QUESTION_022、EVENT_QUESTION_030 |
| R4 | EVENT_QUESTION_001、EVENT_QUESTION_002、EVENT_QUESTION_003 |
| R5 | EVENT_QUESTION_062、EVENT_QUESTION_064、EVENT_QUESTION_067 |
| R6 | EVENT_QUESTION_074、EVENT_QUESTION_077、GENERAL_BIBLE_QUESTION_014 |
| fallback | EVENT_QUESTION_058 |

預設檢索開著圖譜，所以 EVENT_QUESTION_058 實跑會走 R4，不走 fallback；PERSON_QUESTION_053 也只是一般的 R3 題，因為預設不跑 cross_ref 策略。

## 跑法與通過條件

在 evaluation/ 下執行。不加 `--graph-strategies`，用 backend 的預設策略（event_registry）：

```bash
rm -f results_quick/w1_step1_smoke.json \
  && uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/smoke20_ids.txt --label w1_step1_smoke \
  && python3 -c "import json; d = json.load(open('results_quick/w1_step1_smoke.json')); print(d['n'], d['n_invalid'], sorted(q for q, e in d['per_question'].items() if e['strategy_errors']))"
```

通過條件是印出 `20 0 []`，也就是 n=20、n_invalid=0、沒有任何一題帶 strategy_errors。先刪上一次的結果檔，三段用 `&&` 串起來：收集中途失敗時，不會讀到舊檔而假性通過。

2026-10-05 曾對升版前的 prod backend（:8000）試跑同一條指令：n=20、n_invalid=0、strategy_errors 0 題；20 題都套用了 event_registry，實際路由為 R1 3、R2 3、R3 4、R4 4、R5 3、R6 3。
