# 事前登記：R2（事件註冊表修正版＋PDF 版路由詞表）的檢索非劣性（G-NONINF）、答案端守門（G-ANS）與 held-out 事件題（G-HELDOUT）

- **登記時間**：2026-10-09。本檔、`heldout_gate.py`、`src/heldout.py`、`freeze_r2.py`、`src/r2_frozen.py` 與 `r1_gate.py --prereg r2` 在同一個 commit，早於 R2 臂的任何結果。`frozen_r2.json` 在 R2 build 建好之後、R2 臂任何結果之前產生，同時把 sha256 釘進 `src/r2_frozen.py`（見「路由改變切片」）。
- **依據**：設計書 v1.1 §8 G-NONINF、G-ANS、G-HELDOUT，§13 P6；`reports/r2prep/plan.md` DOC 1 §3 與「Kay 裁決（2026-10-08）」（R2 路由改變切片當 hard 閘門）；R1 預登記 `experiments/2026-10-08_r1/prereg.md`（本檔沒寫的統計細節一律照它）。
- **重跑上限**：任一臂最多重跑 2 次，而且只限基礎設施失敗（invalid、HTTP 錯誤、judge 失敗）。看到 R2 結果後不改門檻、不換對照、不加減題、不改評分器與 id 對照。

## 臂與共同設定

| 臂 | 位置 | 映像 | 資料 |
|---|---|---|---|
| 對照 R1 | :8002 `bible_rag_backend_r1` | `bible_rag-backend:r1` | `b20261008_6daa4f31` |
| 處理 R2 | staging 非服務槽（埠於開跑前寫入本表） | `bible_rag-backend:r2`（開跑前記下 digest） | R2 build（id 於開跑前寫入本表） |

- 上表的 R2 埠、映像 digest 與 build id 由整合階段在建置後、任何 R2 結果之前填入；填入不改變任何定義。
- GT v2（`ground_truth.v2.json`，sha `7280bb42…`，slot_universe `text@247eafe44b02`）。兩臂都用 GT v2 凍結的節位宇集計分。
- backend 預設設定（不覆寫 graph 策略、α），`retrieval_only`，top-k 5，metric-k 6，concurrency 3。
- 兩臂共用同一個 Ollama（intent 與生成），各臂依序跑，不並行。
- 計分程式要與 L1 相同：`r1_gate.py` 會拒絕 metric_version 不同的結果，所以 L2 與 R2 臂要用 metric 程式（`src/` 的 reference_parser、verse_coverage、relevance_judge、slot_coverage、book_names、metrics/retrieval，與 ragcommon 的 refs、books、ids、versification 及其資料檔）與 L1 逐位相同的 checkout 跑。
- 配對單位是題。任一臂 invalid 的題從配對中剔除並列出；剔除後少於 495 題，該臂重跑。
- bootstrap：以題重抽，percentile 95% CI，B=10,000，種子 20261008（與 R1 相同）。

## 檢索（G-NONINF，500 題）

1. **A/A 在 R1 臂**：
   - **L1** = R1 評估（2026-10-08）的 R1 臂檢索結果，也就是 R1 的 `gate_retrieval.json` 中 `inputs.R` 那一份。它早於本登記，但它是對照臂，不是處理臂。
   - **L2** = 在 R1 臂再跑一次，與 R2 臂之前完成。
   - 雜訊帶 B、δ = max(0.02, 2B)：定義與 R1 預登記相同。
   - MRR 的雜訊帶 B_mrr = max(|下界|, |上界|)，取 ΔMRR（L2 − L1）平均的 95% CI。**δ_mrr = max(0.02, 2·B_mrr)**。R1 預登記的 B_wl、δ_wl 不再使用。
2. **R2 對 L1**（對照固定用 L1）。三條全部成立才通過：
   - **C1**：Δvrec@6（R2 − L1）的 95% CI 下界 > −δ。
   - **C2（ΔMRR，P1）**：逐題 ΔMRR = MRR_R2 − MRR_L1，平均的配對 bootstrap 95% CI 下界 > −δ_mrr（嚴格大於；下界等於門檻算不通過）。A/A 與 R2 的 CI 都用上面的 bootstrap：以題重抽，B=10,000，種子 20261008，percentile；每個統計量都從這個種子重新開始。mean(sign(ΔMRR)) 與其 CI、勝/敗/平題數、精確 sign test p 只報告，不影響判定。
     - 改用 P1 的原因：R1 預登記的 C2（mean sign 對 −δ_wl）經 R1 診斷是定義錯誤（變動約 34 題的中性改版約 60% 會失敗；mean sign 只落在 1/500 的格點上，判定隨種子而變；見 `reports/r1eval/c2_diagnosis/README.md`、`stats_audit.md`），Kay 2026-10-08 裁決 R2 的 C2 改為 P1。
     - ΔMRR 平均的格點比 mean sign 細得多，但仍有格點：逐題 MRR 是 1/名次（名次 1–6，沒命中為 0），1、1/2、…、1/6 都是 1/60 的整數倍，所以逐題 ΔMRR 是 1/60 的整數倍（存檔取小數 4 位，只多出小於 10⁻⁴ 的捨入餘數），平均落在 1/(60n) 的格點上（n = 500 時約 3.3×10⁻⁵），比 mean sign 的 1/500 細約 600 倍。
     - −0.02 本身也是格點（−600/(60·500)），所以下界恰好落在門檻上仍可能發生，照上面的嚴格大於算不通過；判定直接用存檔值計算，不另設容差。實際上很少見：以 R1 資料試算（R1 − legacy L1 的 ΔMRR），10,000 個 bootstrap 平均只落在 778 個格點上，下界所在的格點只有 5 個重抽。
   - **C3（路由改變切片，hard，Kay 2026-10-08）**：`frozen_r2.json` 路由改變切片的平均 Δvrec@6 ≥ 0，並報告 CI 與三個子切片。
3. **只報告**：題型、family、legacy_head 與擴充題分層（含 disambiguation 家族 12 題與 EVENT_QUESTION）；anchor_coverage、hit；兩臂路由不同的題數（A/A 與 R2 各報）；Δvrec@6 ≤ −0.3 的題逐一列出。
4. 工具：`r1_gate.py retrieval --prereg r2 --aa <L1> <L2> --treatment <R2> --frozen experiments/2026-10-09_r2/frozen_r2.json`。每份預登記都固定對照臂的 build：`--prereg r2` 的對照（L1、A1）不是 `b20261008_6daa4f31` 就拒絕判定；漏打 `--prereg r2` 時用的是 R1 預登記，它要求 legacy-20261004 對照，所以 R2 的結果同樣會被拒絕（結束碼 2），不會被舊的 C2 判定。

## 路由改變切片（凍結於 `frozen_r2.json`）

由 `freeze_r2.py` 離線模擬 GT v2 全部 500 題的路由，不讀任何檢索指標：

- **R1 側**：R1 commit `e7b1173` 的程式（`git show`：ragcommon.routing v1、signal_detector、event_registry），讀 R1 build 的契約（`routing_lexicon.json`、`event_registry.json`）。
- **R2 側**：R2 commit 的程式（R2 映像建置用的同一份：ragcommon.routing v2、signal_detector、event_registry），讀 R2 build 的契約。
- 兩側共用同一個 verse parser；腳本會檢查它與 R1 時逐位相同。
- **intent LLM 的貢獻**：LLM 的輸出沒有存檔，所以照 `reports/r2prep/sim_routes.py` 的做法推斷。
  - 只讀 L1、L2 每題的 `route` 欄，取眾數（同票取 L1）。
  - 若單一貢獻（cross_reference → R5、兩個以上人名 → R3、事件 → R4、地名 → R6）能把 R1 的純問句路由變成觀察到的路由，R1 路由就取觀察值，R2 路由取「R2 純問句訊號＋同一貢獻」。
  - 其他情況（無法解釋、沒有觀察值），兩側都用純問句路由，並列在 `unexplained`。
- **檢索可能改變的三種原因**，各成一個子切片：
  - **route**：路由的處理器不同。R1、R2、R5、fallback 各自一類；R3、R4、R6 是同一個處理器、同一組權重，算一類。
  - **books**：偵測到的書卷不同（影響 book anchor 與多書卷 pin）。
  - **lane**：事件附加槽的錨點偏好不同。在 R4/R5 上，觸發事件依 match_events 排序、錨點串接後去重，也就是單一附加槽（`rag_event_registry_slots=1`）會依序挑的段；其他路由為空。R1 的事件 id 經 id 對照換成 R2 的 ev id 後才比。
- **C3 切片** = route ∪ books ∪ lane，排除 VERSE_LOOKUP_035、TOPIC_QUESTION_034（R1 的新 verse parser 已經改變它們的路由；它們仍在 C1/C2 的 500 題裏）。
- **另列（只報告）**：disambiguation 家族 12 題，附兩側模擬路由。
- **G-ANS 子集**：照抄 `frozen_r1.json` 的 200 題，並記錄它的 sha256。
- `frozen_r2.json` 是決定性的（排序鍵、排序清單、無時間戳），記錄每個輸入的 sha256（兩側契約、R2 程式檔、L1/L2、GT、本腳本）。寫出後把 sha256 釘進 `src/r2_frozen.py` 的 `FROZEN_R2_SHA256`；未釘之前 `load_frozen` 一律拒絕。
- 以 2026-10-08 的 K1/K4 暫存建置試跑（非正式、未凍結；觀察路由暫用 legacy A/A 第一輪代替 L1）：切片約 34 題，與 DOC 1 估計的 25–35 題加 5–6 題相符。正式數字以凍結檔為準，寫入 G-NONINF 報告。

## 答案端（G-ANS，200 題子集）

- **子集**：`frozen_r1.json` 的 200 題（經 `frozen_r2.json` 讀入）。
- **A/A 在 R1 臂**：
  - **A1** = R1 評估（2026-10-08）的 R1 臂 G-ANS 收集與判分，也就是 R1 的 `gate_answer.json` 中 `inputs.R` 那一份。
  - **A2** = 在 R1 臂再收一次、判一次。
- **處理臂**：R2 收一次、判一次。
- 收集、生成模型、judge（`quick_faithfulness_eval.py`，ollama `gemma4:26b-a4b-it-q8_0`，zh 與 strict）都與 R1 預登記相同。
- **判準**：δ_ans = max(0.01, 2·B_ans)，B_ans 取 Δstrict（A2 − A1）的 95% CI；通過條件是 Δstrict（R2 − A1）的 95% CI 下界 > −δ_ans，而且三份 n_invalid 都是 0。
- 只報告：strict 絕對值（參考線 0.97）、zh faithfulness、coverage（雜訊地板 |Δ| 0.060）。
- 工具：`r1_gate.py answer --prereg r2 …`。

## Held-out 事件題（G-HELDOUT）

- **題目**：`config/gold/heldout_events_r2.json`。1a0d514 在觸發詞修改前凍結，sha256 `c2bd965c…`，釘在 `src/heldout.py`。
  - 61 題：43 正例（32 個事件）、18 近似負例。
  - `tuned_on=true` 的題不進 G-HELDOUT（本檔目前 0 題）。設計書說的 GT v2 中 36 題觸發詞命中題與調參用過的 legacy EVENT 題在 GT v2 裏，不在這份檔，仍留在 G-NONINF 的 500 題。
- **收集**：`heldout_gate.py collect`，兩臂各一次。
  - 預設設定、`retrieval_only`、top-k 5。
  - 每題記錄 `route_used`、`event_registry_events`、intent、sources（id、passage_id、strategy），以及 /health 的 build id（必須等於 `--build`）。
  - 有 invalid（HTTP 錯誤、基礎設施失敗）就重收該臂。
- **id 對照**：
  - R1 回報拼音 legacy id（如 `event:babieta`），R2 回報 ev id。
  - R1 的 legacy id → ev id：R1 契約 `b20261008_6daa4f31/event_registry.json` 的 `legacy_id`。
  - 再經 R2 契約的 `retired[].merged_into`：ev0003、ev0014 → ev0002。
  - gold 的 `event_id`（events@904becb6ccd9 的 ev id）也走 merged_into。
  - R2 契約的 `legacy_ids` 必須與上面的組合一致，否則拒絕評分。
- **可接受的事件**：gold 事件本身（對照後）。另依題檔的 scoring_notes：
  - gold 為 ev0011、ev0027、ev0033 時，也接受父事件 ev0020（受難週）。
  - 孿生事件 ev0002、ev0003、ev0014 經 merged_into 已是同一個 ev0002。
  - 不接受子事件（gold 為 ev0020 時，ev0027 不算對）。
- **觸發**：`event_registry_events` 不為空。
- **判分的事件**：實際附加了錨點的事件。
  - response 的 sources 不帶事件 id，所以用該臂契約的註冊表，依附加槽的規則（backend `select_aux_anchors`：依觸發順序，每個事件取第一個不在 top-k 的錨點）還原，並核對與實際附加的段相同；不同就拒絕評分。
  - 沒有附加任何段時（觸發事件的錨點都已在 top-k 內），以 `event_registry_events` 的第一個事件判分。
- **觸發正確**：正例、有觸發，而且判分的事件都可接受。近似負例觸發一律算錯；正例觸發到別的事件也算錯。
- **每題得失**：正例＝觸發正確；負例＝沒有觸發。
- **門檻**（n = R2 觸發的題數）：
  - n ≥ 30：精確率點估計（觸發正確 / n）≥ 0.90，而且配對非劣「R2 失、R1 得」−「R2 得、R1 失」≤ 2。兩條都成立為 PASS，否則 FAIL。
  - n < 30：描述性報告，由 Kay 簽核（SIGNOFF）；兩條的數值照樣計算、列出。
- **一定要報告**：
  - 兩臂在 43 個正例上的召回；
  - 兩臂的離線純字串命中：各臂自己的觸發詞在遮掉書名的題目中出現，不經路由；
  - 漏掉的正例逐題歸因：trigger（沒有字串命中）、route（有字串命中但附加槽沒觸發）、wrong_event；
  - R1 的精確率作參考；逐題表。
- 工具：`heldout_gate.py score --r1 <R1 收集> --r2 <R2 收集>`。結束碼 0 PASS、1 FAIL、3 SIGNOFF、2 輸入錯誤。

## 執行順序

1. 建 R2 build、起 R2 staging backend，把上表的 R2 欄位填好。
2. 在 R1 臂跑 L2（檢索）。
3. `freeze_r2.py --r2-contracts <R2 契約> --observed <L1> <L2>`，把 sha256 釘進 `src/r2_frozen.py`，連同本檔的 R2 欄位一起 commit。
4. R2 臂檢索；R1 臂 A2 收集；R2 臂答案收集；依序判 A2、R2。
5. 兩臂 held-out 收集，然後 score。
6. 三個閘門的報告寫到本目錄。

## 決策

- G-EVENT、G-ROUTE（建置時）與 G-NONINF、G-ANS、G-HELDOUT 全部通過（G-HELDOUT 為 SIGNOFF 時要 Kay 簽核）→ Kay 簽 approval 檔，再 `ragdata promote --env prod --yes-prod --build <R2> --image <R2 digest>`，跑 20 題 smoke。
- 任一條不通過 → 不上線。不放寬門檻、不換子集。先跑歸因臂「R2-K1-only」（新事件註冊表加 R1 凍結路由；比照設計書 E0a 的歸因做法）診斷原因，再回報 Kay。
