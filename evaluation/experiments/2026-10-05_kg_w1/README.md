# W1 升版的題號檔

兩份題號檔，都是一行一題，`quick_retrieval_eval.py --ids-file` 直接讀：

| 檔案 | 用在 | 判準 |
|---|---|---|
| `smoke20_ids.txt` | 升版第 1 步的 20 題煙霧測試 | 印出 `20 0 []` |
| `graph_event_k10_ids.txt` | 升版第 1、2 步之間的 graph_event 抽查（K10） | 只報告 |

## 20 題煙霧測試（升版第 1 步）

- **用途**：`docs/records/2026-10-04_kg_batch1_plan.md` §1「W1 升版」第 1 步。先換上 R2 測過的 1B 過渡版 backend（`bible_rag-backend:w1` 改 tag 為 `latest`，不重建，見 `docs/staging_promotion.md`「W1 升版第 1 步」；資料仍是舊的），等 healthcheck 通過，再跑 20 題預設檢索。這只確認新 image 在各路由都能跑完，不量價值。
- **題號檔**：`smoke20_ids.txt`。

### 選題規則

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

### 跑法與通過條件

在 evaluation/ 下執行。不加 `--graph-strategies`，用 backend 的預設策略（event_registry）：

```bash
rm -f results_quick/w1_step1_smoke.json \
  && uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/smoke20_ids.txt --label w1_step1_smoke \
  && python3 -c "import json; d = json.load(open('results_quick/w1_step1_smoke.json')); print(d['n'], d['n_invalid'], sorted(q for q, e in d['per_question'].items() if e['strategy_errors']))"
```

通過條件是印出 `20 0 []`，也就是 n=20、n_invalid=0、沒有任何一題帶 strategy_errors。先刪上一次的結果檔，三段用 `&&` 串起來：收集中途失敗時，不會讀到舊檔而假性通過。

2026-10-05 曾對升版前的 prod backend（:8000）試跑同一條指令：n=20、n_invalid=0、strategy_errors 0 題；20 題都套用了 event_registry，實際路由為 R1 3、R2 3、R3 4、R4 4、R5 3、R6 3。

## graph_event 抽查（升版第 1、2 步之間，K10）

- **用途**：第 1 批計畫 §7 的 K10「W1 先 accept 並抽查 graph_event」，以及 §5.2 的 W1 列「graph_event｜抽查保羅歸主、山上寶訓的題目（受 mention_count 殘差影響）」。在 `docs/staging_promotion.md`「W1 升版第 1、2 步之間」的 opt-in 視窗裡，同一個 `:w1` image 分別接舊資料（prod，:8000）與新資料（backend-staging，:8001），各跑一次 `--graph-strategies graph_event`，再以 ab_compare 比較。只報告，不設門檻；結果記進 W1 紀錄，放在 K10 的 accept 旁邊。
- **題號檔**：`graph_event_k10_ids.txt`。

### 選題規則

選題於 2026-10-06 計算，來源是專案根目錄的 `ground_truth.json`（500 題，sha256 `e4336ddd…`）與 `backend/data/event_registry.json`。

K10 的 mention_count 殘差（第 0 批遺留，W1 照原樣上線）有 4 個實體，其中 3 個是 Event：`event:shanshangbaoxun`、`event:baoluoxushuguizhudejingguo`、`event:baoluoxushuguizhujingguo`。第 4 個 `person:yeteluo` 不是 Event，graph_event 碰不到。這 3 個事件在 event_registry 的觸發詞是保羅歸主、八福、山上寶訓、登山寶訓，四個也都在 backend 的事件關鍵字字典裡。選的是題目文字（`question`）含有任一觸發詞的題，依 GT 的順序：

```bash
jq -r '.questions[] | select(.question | test("保羅歸主|八福|山上寶訓|登山寶訓")) | .question_id' ../ground_truth.json
```

共 6 題：

| 觸發詞 | 題號 |
|---|---|
| 保羅歸主 | EVENT_QUESTION_019、EVENT_QUESTION_067 |
| 登山寶訓 | VERSE_LOOKUP_006、EVENT_QUESTION_011、GENERAL_BIBLE_QUESTION_054、GENERAL_BIBLE_QUESTION_055 |

GT 寫的是「登山寶訓」，圖上的事件名是「山上寶訓」；沒有題目用「八福」或「山上寶訓」。VERSE_LOOKUP_006、EVENT_QUESTION_011、EVENT_QUESTION_019 屬於 legacy-100，其餘 3 題是擴充題。GT 或 event_registry 有變動時，`scripts/tests/test_docs_alignment_w1.py` 會失敗，題號檔要照上面的規則重算。

### 為什麼受 mention_count 影響

graph_event 對每個事件關鍵字取 mention_count 最高的 3 個事件（`find_events_by_keyword`），pin 的先後也依 mention_count（`_pin_keyword_event_candidates`）。2026-10-06 對 prod（7687）與仍是第 0 批建置的 staging（7688）唯讀查同一個 Cypher：

- 保羅歸主：prod 依序是 event:baoluoxushuguizhudejingguo、event:baoluoxushuguizhujingguo（mention_count 各 4）、event:saoluodezhuanbian（1）；staging 三個都是 1，順序改由 md5 平手決定（event:baoluoxushuguizhudejingguo、event:saoluodezhuanbian、event:baoluoxushuguizhujingguo）。
- 登山寶訓、山上寶訓、八福：兩邊都只對到 event:shanshangbaoxun，mention_count 從 23 變成 1。

W1 不改實體與 MENTIONS，所以 W1 的 staging 帶著同樣的殘差（R2 的 `residuals_expect.py --check` 核對）。

### 跑法

指令在 `docs/staging_promotion.md`「W1 升版第 1、2 步之間」：兩邊各跑一次 `quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt --graph-strategies graph_event --top-k 5 --metric-k 6`，再跑 `ab_compare.py`。參數與 2026-10-03 的 graph_event 單一策略量測（`results_quick/s2_graph_event_20261003.json`）相同；那一次 VERSE_LOOKUP_006 走 R1（只有 verse_direct 的 1 段），其餘 5 題的前 5 段裡各有 1–4 段來自 graph_event。
