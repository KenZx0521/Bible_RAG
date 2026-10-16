# book_anchor 消融執行計畫（事前登記定稿 v2，2026-10-15）

設計：workflow wf_0a62cda4-605（3 位讀者、設計、3 位對抗審查、定稿；審查處理見同目錄 plan_changes.md）。主控在登記前加了 §0.1 的兩處修改。

## 0. 摘要

**要回答的決策**：prod 的 book_anchor 該怎麼處理，三選一：
- 維持現行；
- **nopin**：取消單書的無條件釘選，多書「缺席書」釘選保留；
- **off**：整個刪除，不收候選、不加 0.9 先驗、不做 cap、不釘選。

**做法**：
- 用現有映像 `bible_rag-backend:r2` 起一次性批次容器：`docker compose run --rm`，用 backend-stg 的服務定義，加上 `RAG_ENV=prod`。
- 容器裡跑一支已 commit 的 driver。不碰 prod 容器、不建映像、不起 server、不改 prod 程式。
- 每題只做一次 intent 分類，三臂共用；三臂的差別只來自 driver 行程內兩處名稱替換。
- 生成在同一行程內呼叫 backend 的 `generate_answer`。

**受影響子集**：依本次檢索的 ctx_sha 機械決定，在生成之前凍結。預期 D_nopin 約 19 題、D_off 約 39 題。

**指標**：
- 主要：子集上 coverage 的配對差，每臂每題生成 6 次後取平均。
- 守門：strict faithfulness（只判前 3 次）、vrec@5。
- 描述：全 500 題的檢索指標。

**判定**：
- coverage 和 strict 用 t-CI 做不劣檢定，界線分別是 −0.05 與 −0.04；另用 Holm 校正的 sign-flip 做傷害檢定。
- 採 off 時，還要求「off 對 nopin」的增量也不劣。
- 真實效果為 0 時，P(可改) 在 n≈20 為 0.75–0.93，n=39 為 0.98–0.99（§7）。

**時間**：
- 寫程式約 3–4 小時，smoke 20 分鐘；
- `run_ba.sh` 約 7–10 小時，可以一夜跑完。

**由誰執行**：由 Claude 執行；docker 指令若被權限擋下，再請 Kay 執行（§0.1 M2）。

相對 v1 的改動逐條列在 plan_changes.md。

## 0.1 登記前的修改（主控，2026-10-15）

- **M1 只在可能受影響的題跑變體臂**：ctrl 檢索時記錄 `routes._book_anchor` 有沒有被呼叫。沒被呼叫的題，nopin 與 off 依構造必然等於 ctrl：off 替換的函式沒有執行；pin 在沒有 book_anchor 候選時原樣回傳 ranked，nopin 也是。這類題不跑 nopin、off，retrieval.jsonl 記 `arms_skipped: "book_anchor_not_invoked"`，匯出時直接沿用 ctrl。例外：batch_a 的隨機 40 題非 C 與 smoke 的 R1 題，仍然三臂都跑，作為 I2 的實測抽查。§6 的 I2 因此改成：在有跑三臂的非 C 題上，nopin、off 的 top-k id、順序與 ctx_sha 都必須等於 ctrl；跳過的題由構造保證。C 的定義不變。
- **M2 執行者**：smoke 與 run_ba.sh 由 Claude 執行；docker 指令被權限擋下時，再交給 Kay。步驟 0 的檢查也由 Claude 做。

## 0.2 實作偏離與 smoke（commit ① 之前，2026-10-15）

以下都在看到任何正式資料之前決定，優先於其餘段落的字面。

**實作偏離**
1. retrieve 多一個 `--force-ids`，用來指定 M1 要強制三臂的題（batch_a 的 40 題非 C、smoke 的 R1 題）。
2. `compose.ba.yml` 另加 `ports: !reset []`，`run_ba.sh` 固定 `STG_IMAGE=bible_rag-backend:r2`。
3. M1 的「有呼叫」指 ctrl 至少呼叫過一次 `routes._book_anchor`；沒偵測到書而回傳空清單也算。R3–R6 與 fallback 的題因此都跑三臂，只多花檢索時間，不影響結果。
4. intent 重試條件是 `_extract_json` 回傳空值（None 或 `{}`），對齊 `_llm_intent` 自己的 `if not parsed`。
5. batch_a 的隨機 40 題非 C，從 eval3c 43 題以外抽，並排除 GBQ_073、EVENT_QUESTION_098 與 R1 題。
6. I0 另檢查 `handshake.ok`、`env.RAG_ENV=prod`、各 meta 行的 mode 一致。meta 的 encoder_fingerprint 改用 /health 的 {embedder, reranker} 鍵名，`main.load_models()` 的原值另存 `load_models_fingerprint`。握手或 LLM 健康檢查失敗時，不寫任何行就 exit 2；沒有待跑項目時也不寫任何行。
7. I4 另做逐題的實際設定檢查：use_graph、graph_strategies、fusion_alpha（R1 必須是 None）。正式 `check` 另要求 500 題都有檢索紀錄。
8. smoke 的 I0 比對工作樹的 `/exp` sha，正式跑比對 HEAD。
9. prod 動作照 §8 表由上往下判。只有輪到的那一條需要用到「無效」配對時，才回傳「先補跑」；例如 nopin:ctrl 有效且為傷害，就照第 1 條維持現行。
10. I6 的「剔除超過 2 題」以 cov 與 strict 剔除題的聯集計算，vrec 不計入。
11. generate 多一個 `--retry-failed`，用於 I6 只補跑失敗的 (q, arm, rep)；匯出時取每個 key 最新一筆。export-ans 遇到 messages sha 不符就拒絕匯出。
12. 判分的跳過條件比 §9 嚴格：輸出非空，而且 `<out>.src_sha` 等於現在 `ans/<d>/raw_responses.json` 的 sha。I6 補跑後，該目錄整個重判。report 拒收沒有 `.src_sha` 或 sha 不符的判分檔。
13. 報告組裝拆到 `_ba_report.py`；另加 `test_ba_driver.py`、`test_ba_cov.py`、`test_ba_analyze.py`。

**smoke 結果**（store `smoke/`）
- I0–I4 與 §6 的預期值全部通過。6 題三臂的 top-5 逐一人工對照 §6 表，也都相符。
- GBQ_024 三臂各生成 1 次，messages sha 全部吻合。strict 判 1 個目錄、coverage 判 3 個目錄，流程都正常。
- e4b 與 26b 的 size_vram 都等於 size。

**環境**
- GPU 上另有他人的 vLLM，約佔 38 GB，10-13 起執行，eval3c 時已經在跑。只影響速度。
- `tests/test_ba_*.py` 187 passed。全 evaluation 套件唯一的失敗是 `test_idlint`，指向 HEAD 中 GD 實驗的 `ho_tools/annotate.py:62` 與 `mech_check.py:159`，與本實驗無關，這次不修。

---

## 1. 背景（數字已更正）

**eval3c 的事後證據**
- 39 題的 full−sem coverage 是 −0.082 [−0.144, −0.023]。這是 full 對 sem，不是消融，而且 full 那次生成剛好落在偏差的一側。
- (full+nokg)/2−sem 為 −0.063 [−0.115, −0.015]；nokg−sem 為 −0.044（p 0.107）。

**兩個傷害機制**
- **釘選**，20 題：
  - 單書 19 題：R5 18 題，加上 fallback 的 VERSE_LOOKUP_097；
  - 多書 1 題：GBQ_096。
- **0.9 先驗讓段落自然進榜**，19 題：多書 15 題、單書 4 題。
- 含 gold 的比例：被釘段 2/34，自然進榜段 3/35，同一批題的其他段 60/146。

**離線檢索結果**：單書不釘時，在釘選題上 ΔMRR@5 +0.451（19:1）、Δvrec@5 +0.077；唯一的輸家是 GBQ_050。

**「measured neutral」沒有根據**：pins.py 這樣寫，但從未做過開／關比較。bugA v2 的三個版本都有釘選。

**路由與決定性**
- intent 用 LLM 判定，temperature 0.1、沒有 seed。
- 四次送題中，29/500 題路由不一致；43 題 book_anchor 題裡只有 GBQ_073 換過路由。
- intent 固定時，檢索是決定性的（486/486）。

**實測耗時**：eval3c 收集 20–27 秒／題，判分約 25 秒／題。

**生成雜訊**：39 題單次生成的配對差 SD，coverage 0.146（釘選 20 題為 0.131），strict 0.079（釘選 20 題為 0.089）。

## 2. 執行方式

| | 三臂同路由、同候選池 | 測到的是不是將來上線的程式 | 對 prod 的影響 | 能否記錄 pinned 與候選池 |
|---|---|---|---|---|
| A：加請求參數，起 staging 打 API | 否：每臂重抽 intent，約 2.8% 換路由 | 是 | 要建映像，有 prune 風險；prod 程式會留下消融旋鈕 | 否 |
| B：在 prod 容器內 exec | 是 | 替換 | 在 prod 容器裡跑數小時，權限也會擋 | 是 |
| **C1：一次性批次容器＋行程內替換（採用）** | 是：共用 intent；nopin 直接重用 ctrl 的 gather | 替換；上線後用 500 題逐位比對補上（§12） | 不碰 prod 容器；PG、Qdrant 唯讀共用；Ollama 排隊；共用 CPU | 是 |
| C2：用 k=20 結果離線重組，在 host 生成 | 部分 | 模擬；章節 pin 與附加槽只能近似 | 最小 | 部分 |

**選 C1 的理由**
1. 只有共用 intent，三臂才真正同路由。
2. 完全不碰 prod 容器。
3. 不在 prod 程式留旋鈕。若決定改，改法是刪程式碼，由 §12 驗證「上線的程式就是測過的臂」。

**生成的不決定性**
- 沿用 prod 的生成設定：temperature 0.1、num_predict 10000、不設 seed。
- 每臂每題生成 6 次（R=6），coverage 用 6 次的平均，strict 只判前 3 次。
- 生成順序以「題 × 次」為區塊打亂（seed 20261015），區塊內的臂序也打亂。
- 不採用共同隨機數（CRN）。兩臂的 context 不同，token 序列很快就會分岔，相關性很低；Ollama 在批次處理下也不保證同一個 seed 能重現。

## 3. 臂

| 臂 | 在 driver 行程內的替換（`ba_arms.arm()`） | 行為 | 上線時對應的程式改動 |
|---|---|---|---|
| **ctrl** | 不改行為，只包記錄器：`router._gather` 回傳時先 deepcopy 一份快照，並保留原物件的參考；`router.pin_book_anchor_candidates` 記錄 `book_gate` 與被釘的 id | 現行 | — |
| **nopin** | `router.pin_book_anchor_candidates` 換成：`book_gate` 為 False 時直接回傳 `ranked`，為 True 時原樣呼叫原函式。`router._gather` 換成回傳同一題 ctrl 快照的 deepcopy | 單書不釘。候選、0.9 先驗、cap、多書缺席書釘選都照舊 | `router._pin` 只在 `g.multi_book` 時呼叫 book_anchor 釘選。`pins.pin_book_anchor_candidates` 刪掉單書分支，`_book_anchor_order` 只保留每書 1 段的邏輯，並改對應測試 |
| **off** | `routes._book_anchor` 換成一個 async 函式，回傳 `[]` | 沒有 book_anchor 候選，先驗、cap、釘選自動失效 | 刪除 `routes._book_anchor`、`_book_anchor_hits` 及其 3 個呼叫點；刪除 `pins.pin_book_anchor_candidates`、`_book_anchor_order`、`cap_book_anchor_entries` 及 router 的呼叫點；刪除對應測試 |

**替換的規則**
- **import 綁定**：router 是用 from-import 取得這些名稱，所以必須替換 `router.` 底下的名稱；`routes._book_anchor` 是在模組內用全域名稱呼叫，可以直接替換。
- **不可重入**：`arm()` 進入時取得一個行程級的不可重入鎖，重入就 raise；離開時在 finally 裡還原。
- **嚴格循序**：每一題依 ctrl → nopin → off 的順序執行，題與題之間也循序，不用 asyncio.gather。
- **nopin 必須有快照**：nopin 開始前若沒有同題 ctrl 的 gather 快照，driver 就停止。

**巢狀關係**：預期 D_nopin ⊆ D_off。off−nopin 包含兩部分：
- off 特有的機制：拿掉候選與 0.9 先驗、cap，以及 GBQ_096 這類多書釘選；
- 連帶效果：`_supplement` 的變化、rerank 批次大小改變造成的浮點差、章節 pin 的資格、附加槽重選。

這些在真正刪除功能時一樣會發生，所以不影響決策，只影響「機制」的解讀（§4 會標記）。

**不跑的臂**

| 臂 | 不跑的理由 |
|---|---|
| tail（釘到尾端） | top-k 的集合與 ctrl 相同，測不到「擠掉第 k−1、k 名」這個主要機制。改用 ctrl 的 top-k 重排，算出描述性的 MRR，回答 Kay「改到尾端」的問題。 |
| noprior | book_anchor 段的 rr 中位數只有 0.004，權重降到 dense 水準後，在這份 GT 上幾乎等於 off；還會多出一個逐路由的旋鈕。 |
| absent（單書也只補缺席的書） | 約 15/20 題中，被點名的書已經在自然前 5 名，這些題等於 nopin。其餘題每書只釘 1 段、只擠掉第 k 名，既不等於 ctrl 也不等於 nopin，本實驗推不出它的答案層效果。 |
| 消融 B | 由 nopin，加上 off 的單書／多書分層描述來涵蓋。 |

## 4. 受影響子集（機械定義，生成前凍結）

全部取自本次的 `retrieval.jsonl`。

| 集合 | 定義 |
|---|---|
| C | ctrl 候選池中至少有 1 個 `source_strategy=="book_anchor"` 的題 |
| P_s | ctrl 記錄器記到 `book_gate=False`，而且有被釘 id 的題 |
| P_m | 同上，但 `book_gate=True`（預期只有 GBQ_096） |
| **D_nopin** | ctx_sha(nopin) ≠ ctx_sha(ctrl) 的題 |
| **D_off** | ctx_sha(off) ≠ ctx_sha(ctrl) 的題 |
| U | D_nopin ∪ D_off |

**ctx_sha** 的定義是 `sha256("\n\n".join(build_context_blocks(results)))`，其中 results 包含事件附加段。

**D_off 的機制標記**（可以多選）：
- (i) ctrl 的 top-k 裡有 book_anchor 段被移除；
- (ii) 只有非 anchor 段之間換了順序；
- (iii) supplement 改變，也就是 off 的池裡出現 ctrl 池沒有的 id；
- (iv) 附加槽改變。

另外記錄共有段的 max|rr_off − rr_ctrl|。只帶 (ii) 標記的題要逐題列出，並在報告中另外分層。

**凍結**：`check` 會寫出 `checks/subsets.json`、`gen_plan.json`、`judge_ids_{arm}.json`、`judge_order.json`，並把各檔的 sha256 記進 `checks/freeze.json`。`report` 會先驗證這些 sha 沒有變。

**與 eval3c 的重疊**（要報告）：
- |D_x ∩ eval3c 39 題|、|D_nopin ∩ 單書釘選 19 題|，以及只出現在一邊的題號與原因；
- C 與 eval3c 43 題的聯集；
- 本次與 eval3c 路由不同的題，以及它們在另一條路由下是否也屬於 C。

**不重用 eval3c 的答案**。

## 5. 指標

**配對**

| 配對 | 母體 | 說明 |
|---|---|---|
| nopin:ctrl | D_nopin | |
| off:ctrl | D_off | |
| off:nopin | U | 在 U∖D_nopin 上，nopin 的答案直接取 ctrl 的答案（context 相同） |

**主要指標：coverage**
- 逐題算 Δ_q = c̄_x(q) − c̄_y(q)，其中 c̄ 是 r1–r6 中有效次數的平均。
- 報告：Δ̄、97.5% 與 95% t-CI、Holm 校正後的 sign-flip p、W:L；另附換算到 U 與 500 題的值（Δ̄·|D|/500）。

**守門 G1：strict**
- s̄ 是 r1–r3 中有效次數的平均，配對方式同上。
- x 對 ctrl 時另算 500 題換算值：(Σ_{q∉D_x} eval3c full 的 strict ＋ Σ_{q∈D_x} s̄_x(q)) / 有效題數。

**守門 G2：vrec@5**
- 逐題的檢索結果是決定性的，在同一個母體上配對，用 Holm 校正的 sign-flip 檢定。
- percentile CI 只作描述。

**描述性指標**（一律不改變 §8 的判定；子集結果都附 MDE）
- 全 500 題每臂的 vrec@5、vrec@6、MRR@5。用 `quick_retrieval_eval --from-raw`，metric_version 必須是 4d0826bb8d14。
- `ab_stats.ledger_entry` 的異動分類；每臂的 gold_out 清單（例如 GBQ_050、GBQ_009）。不設單題否決。
- 每臂在 D_x 上「題目點名的書出現在 top-k」的比例。
- 拒答與含糊回答：用凍結的 eval3c `refusal_v2.py`（sha ea3060c6…），`is_strict_refusal` 算拒答、`is_refusal` 算含糊或拒答。逐臂計次，並對逐題次數差做符號檢定。
- 分層：單書／多書、釘選／自然進榜、legacy_head／擴充家族、D_nopin 與 D_off∖D_nopin 兩層。
- 具名個案：GBQ_008、024、040、050、071、096。
- tail 的描述性 MRR。
- judge 決定性：ctrl_r1 的 coverage 重判一次，報告逐題相同的比例。

**解讀**：在這批題上，Δcov 等於「gold 經文經過生成器之後的召回」。39 題中 38 題恰好有 5 個要點，多數屬於擴充家族。

**量尺**
- GT v2；judge 為 gemma4:26b-a4b-it-q8_0。
- 每份判分的 meta 必須是 `context_format == generator_blocks`，`context_sources` 全部為 `backend`，否則拒收。
- coverage 由 `ba_cov.py` 判分，逐要點的判定寫進 JSON；strict 的 log 以 `COLUMNS=1000` 保存。

**有效次數規則**：judge 失敗、生成失敗或 coverage 為 None，該次即無效並剔除。coverage 至少要 4/6 次有效，strict 至少要 2/3 次有效；不足時，該題從該配對、該指標中剔除，並逐題列出。

## 6. 不變量

除了標明「只報告」的，任一條失敗都停線。

**I0 環境與程式身分**
- driver 的 meta 行必須符合：
  - build_id 為 `b20261008_e05d3e55`；
  - encoder_fingerprint 等於 eval3c `full/run_meta.json`；
  - α 0.3、fusion 開、top_k 5、use_graph True、graph_strategies `["event_registry"]`；
  - 生成模型 gemma4:e4b-it-q8_0、temperature 0.1、max_tokens 10000；
  - 記錄 `torch.get_num_threads()`：不設定，預期是 24，與 prod 相同。
- 下列 18 個檔的 sha256 必須等於 repo HEAD 的版本：
  - backend/utils/retrieval/{routes,router,pins,dense,candidates,event_registry}.py
  - backend/utils/{signal_detector,intent_classifier,generator,reranker,embedder}.py
  - backend/routers/query.py
  - backend/models/{request,response}.py
  - backend/config.py、backend/main.py、backend/utils/llm/ollama_client.py、backend/serving/startup.py
- `/exp/*.py` 的 sha 必須等於 HEAD。
- `exp_meta.json` 中，映像 ID 必須以 `sha256:c79266296cb0` 開頭；e4b 與 26b 的 Ollama digest 要記錄下來。

**I1 ctrl 等於 prod**
- 與 eval3c full 同路由的題，top-5 加附加槽的 id 序列必須 100% 相同。
- 另外報告共有 id 的 max|Δscore|，預期 ≤ 1e−5。不一致時，用這個值判斷是近同分的數值漂移，還是程式不同。
- 路由不同的題只列出，不算失敗。

**I2 實作與決定性檢查**：所有不在 C 的題，nopin 與 off 的 top-k id、順序與 ctx_sha 都必須與 ctrl 相同。這只能證明替換正確、結果決定性，不能證明「其他題沒有傷害」；傷害面見 §5 與 §13。

**I3**：D_nopin 必須等於 P_s。D_nopin ⊆ D_off 與 P_m ⊆ D_off 只報告，例外逐題列出。

**I4 路由與錯誤**
- 每一題三臂的 intent 與 route_used 都相同。
- driver 重試之後，strategy_errors 必須都是空的。重試方式：該題三臂整組重跑，最多 2 次。
- intent 包一層 `intent_classifier._llm_intent`：遇到例外，或 `_extract_json` 回傳 None，就重試，最多 2 次。記錄 `intent_ok` 與嘗試次數。`intent_ok=False` 的題只列出，不停線。

**I5（只報告）**：C 裡的每一題，off 的池應該等於 ctrl 的池扣掉 book_anchor 候選（id 與 weight 都相同）。例外附上 §4 的機制標記。

**I6 生成失敗**
- 答案以「生成回答時發生錯誤」開頭或為空，就重試，最多 2 次。
- 仍然失敗的照原樣寫出，判分會標成 invalid。
- 任一配對剔除超過 2 題，就判為無效；只補跑那些失敗的 (q, arm, rep)。

**I7 context 一致**
- generate 在呼叫 LLM 之前，先從存下的 results 重算 ctx_sha，必須等於 retrieval 記錄的值；不等就 exit 3，不送出生成。
- gen.jsonl 記錄 ctx_sha，以及實際送出的 messages 的 sha256（由 `generator.get_llm_client` 的 proxy 取得）。
- export-ans 寫 contexts 時再驗一次 sha。

**smoke 預期值**（id 省略 `ps:` 前綴；ctrl 一律等於 eval3c full）

| 題 | 預期 |
|---|---|
| GBQ_024 | nopin = mrk.1.1, mat.3.1, luk.3.1, jhn.1.19, isa.40.1；off = mrk.1.1, mat.3.1, luk.3.1, jhn.1.19, mat.11.2 |
| GBQ_096（多書） | nopin = ctrl；off = exo.40.34, 2ch.5.11, ezk.43.1, exo.16.1, isa.4.2 |
| GBQ_001（自然進榜） | nopin = ctrl；off 去掉 isa.30.19，前 4 名不變 |
| GBQ_050 | nopin = off = mat.22.23, mrk.12.18, luk.20.27, jhn.12.12, mat.16.21 |
| GBQ_013（多書，章節 pin） | 三臂第 1–3 名都是 1co.15.12, 1co.15.35, 1co.15.1；nopin = ctrl；off 去掉 gen.15.1，第 4 名是 2co.6.14，第 5 名不是 book_anchor |
| eval3c full 中第一個 R1 題（依 id 排序） | 三臂相同 |

## 7. 統計與操作特性

**方法**

| 項目 | 做法 |
|---|---|
| 決策用 CI | 雙尾 t-CI，97.5%（兩臂 Bonferroni）；另報 95% |
| 描述用 CI | percentile bootstrap，`ab_stats.bootstrap_ci`，B=10,000，seed 20261015 |
| p 值 | `ab_stats.sign_flip_p`，雙尾；非零差 ≤16 個時精確列舉，否則 20,000 次，seed 20261015 |
| 多重比較 | `ab_stats.holm`；每個指標（cov、strict、vrec@5）各一個家族，各含 {nopin:ctrl, off:ctrl, off:nopin} 三個比較 |

**操作特性**
- 由 `oc_sim.py` 模擬，結果寫在 `oc_out.json`；兩者都在 scratchpad/ba/final/，會複製進實驗目錄。
- 雜訊池：eval3c 39 題的 full−nokg 逐題差，coverage 與 strict 聯合抽樣並中心化。
- 兩種雜訊模型：E（可交換）與 Q（題內，代表雜訊下限）。
- 3000 次模擬；coverage 用 R=6，strict 用 R=3；Holm 取最嚴的一步 α/3。

| n | 真 Δcov | 真 Δstrict | P(可改) | P(傷害) | P(無法判定) |
|---|---|---|---|---|---|
| 19–20 | 0 | 0 | 0.75–0.93 | ≤0.01 | 0.07–0.24 |
| 19–20 | +0.03 | 0 | 0.87–0.95 | ≤0.003 | 0.05–0.13 |
| 19–20 | −0.05 | 0 | ≤0.011 | 0.87–0.95 | 0.05–0.12 |
| 19–20 | −0.08 | 0 | 0 | ≥0.997 | ≤0.003 |
| 19–20 | 0 | −0.04 | ≤0.011 | 0.87–0.95 | 0.05–0.12 |
| 39 | 0 | 0 | 0.98–0.99 | ≤0.011 | ≤0.008 |
| 39 | −0.05 | 0 | ≤0.001 | ≥0.998 | ≤0.001 |
| 39 | 0 | −0.04 | ≤0.001 | ≥0.997 | ≤0.002 |

**從模擬讀出的重點**
- **型一錯誤**：真 Δ 正好在界線 −0.05 時，P(可改) ≤ 0.011，名目值是 0.0125。
- **off 的整體機率**：三個效果都為 0 時，off 被採用的機率約 0.95（off:ctrl 與 off:nopin 都可改，且 nopin 不判傷害）。
- **對 SD 的敏感度**（E 模型、R=6、Δ=0 時的 P(可改)）：

  | coverage 單次配對差 SD | 0.12 | 0.146 | 0.19 |
  |---|---|---|---|
  | n=20 | 0.85 | 0.79 | 0.58 |
  | n=39 | 0.98 | 0.98 | 0.93 |

- **為什麼選 R=6**：在 n=20、Δ=0 下，R=3 的 P(可改) 只有 0.52–0.81；R=9 是 0.86–0.94，只比 R=6 多 0.02–0.08，卻要多花 1.2–1.7 小時。n≈20 時真正卡住的是 strict 那一關（R=3）。

**界線的意義**
- **coverage δ = −0.05**：約等於每 4 題中有 1 題少覆蓋 1 個要點；換算到 500 題 ≤ 0.004。
- **strict −0.04**：用同一個雜訊池校準。在虛無下單關通過率為 n=20 時 0.90–0.93、n=39 時 ≥ 0.99。另有 500 題換算後 ≥ 0.97 的絕對門檻。

## 8. 決策規則（寫死）

**`verdict(配對)`**：依序判定，第一個成立的就是結果。
1. **無效**：I0–I4、I7 任一條失敗，或該配對剔除超過 2 題。此時不判定，先補跑。
2. **傷害**：cov、strict、vrec@5 三項中，任一項 Holm 調整後 p < 0.05 且 Δ̄ < 0。
3. **可改**：以下全部成立：
   - 不屬於傷害；
   - cov 的 97.5% t-CI 下界 > −0.05；
   - strict 的 97.5% t-CI 下界 > −0.04；
   - 若是 x 對 ctrl，500 題換算 strict ≥ 0.97。

   若同時 cov 的 Holm p < 0.05 且 Δ̄ > 0，另標「顯著改善」。這不是可改的必要條件。
4. **無法判定**：其餘情況。

**prod 動作**：依序判定，取第一條成立的。

| # | 條件 | 動作 |
|---|---|---|
| 1 | V(nopin:ctrl) = 傷害 | 維持現行。off 包含 nopin 的改動，所以也不採 off |
| 2 | V(off:ctrl) = 可改，且 V(off:nopin) = 可改 | 採 off（刪除整個功能）。例外：若 V(nopin:ctrl) = 可改，且 off:nopin 的 cov 97.5% t-CI 上界 < 0，改採 nopin |
| 3 | V(nopin:ctrl) = 可改 | 採 nopin（只刪單書釘選，多書缺席書釘選保留） |
| 4 | 其餘 | 維持現行 |

**補充規則**
- 「無法判定」一律維持現行，不加跑、不延長。之後若要再測，視為新的一次登記，用新的生成，不和本次資料合併。
- 報告要寫明結論範圍（§13）。
  - 採 off 時另外寫明：R3、R4、R6 在這份 GT 上從未產生 book_anchor 候選，fallback 也只有 1–2 題，這些路由的效果沒有量到，屬於接受的風險。
  - 採 nopin 時另外寫明：多書釘選只有 GBQ_096 一題，n=1，沒有量測，所以保留。
- Kay 若推翻判定，記為偏離登記。

## 9. 步驟、指令、時間

```bash
REPO=/home/kenzx0521/Bible_RAG
EXP=$REPO/evaluation/experiments/2026-10-15_book_anchor
OUT=/mnt/ollama-data/bible_rag_store/reports/ba_ablation_20261015
PY=$REPO/evaluation/.venv/bin/python
BA_RUN=(docker compose --project-directory $REPO
  -f $REPO/docker-compose.yml -f $REPO/docker-compose.staging.yml -f $EXP/compose.ba.yml
  run --rm --no-deps -T --name bible_rag_ba
  -e RAG_ENV=prod -e RAG_BUILD_ID=b20261008_e05d3e55
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app/packages:/app/backend
  -v $EXP:/exp:ro -v $OUT:/in:ro
  backend-stg /app/backend/.venv/bin/python -B /exp/ba_driver.py)
```

`compose.ba.yml` 只有一件事：把 `services.backend-stg.healthcheck.test` 設成 `["NONE"]`，避免一次性容器被標成 unhealthy 而觸發告警。

**容器的約定**
- 容器不寫任何檔案：資料走 stdout（JSONL，每行都有 `kind` 欄位），log 走 stderr，由 host 端導出。
- `run` 不發布埠；`RAG_ENV=prod` 只會讀 prod 的 serving 列。
- 禁止使用 `up`、`down` 和 `--remove-orphans`。

| # | 步驟 | 指令或內容 | 時間 |
|---|---|---|---|
| 0 | 前置（Kay） | `curl -s localhost:11434/api/ps` 確認 e4b 的 size_vram 等於 size；`nvidia-smi`；確認沒有其他評估在跑；`docker compose … -f $EXP/compose.ba.yml config backend-stg`，確認 healthcheck 是 NONE、沒有 ports | 5 分 |
| 1 | 寫程式（先寫測試） | `cd $REPO/evaluation && .venv/bin/python -B -m pytest tests/test_ba_*.py -q -p no:cacheprovider` | 3–4 小時 |
| 2 | smoke（Kay） | 見下方 | 20 分 |
| — | **commit ①** | 見 §10 | — |
| 3 | 正式跑（Kay） | `mkdir -p $OUT/logs && nohup bash $EXP/run_ba.sh > $OUT/logs/run_ba.log 2>&1 &` | 7–10 小時 |

**smoke（步驟 2）**
1. `$PY -B $EXP/ba_prep.py --out $OUT/smoke --smoke`
2. `"${BA_RUN[@]}" retrieve --questions /in/smoke/questions.json > $OUT/smoke/retrieval.jsonl 2> $OUT/smoke/retrieve.log`
3. `$PY -B $EXP/ba_analyze.py smoke --out $OUT/smoke`：比對 §6 的預期值，並寫出 GBQ_024 三臂各 1 次的 gen_plan。
4. `"${BA_RUN[@]}" generate --plan /in/smoke/gen_plan.json --retrieval /in/smoke/retrieval.jsonl > $OUT/smoke/gen.jsonl`
5. 執行 `export-ans`，判 strict 1 個目錄，用 `ba_cov.py` 判 3 個目錄。

**`run_ba.sh` 的內容**
- `set -euo pipefail`。
- 每次續跑前，先把 JSONL 截到最後一個換行。
- 已經存在且非空的判分輸出直接跳過。

| # | 階段 | 指令或內容 | 時間 |
|---|---|---|---|
| 3.0 | 開跑斷言 | `ba_prep.py --out $OUT`：斷言 `git diff --quiet HEAD -- $EXP evaluation/tests/test_ba_*.py`，且這兩處沒有未追蹤檔。記錄 HEAD、porcelain、映像 ID、兩個模型的 Ollama digest、refusal_v2 的 sha；寫出 questions.json 與 batch_a.json | 1 分 |
| 3.1 | 檢索 A 批（早期關卡） | batch_a = eval3c 的 43 題 ∪ {GBQ_073, EVENT_QUESTION_098} ∪ 隨機 40 題非 C（seed 20261015）∪ smoke 的 R1 題。<br>`"${BA_RUN[@]}" retrieve --questions /in/questions.json --ids-file /in/batch_a.json --resume /in/retrieval.jsonl >> $OUT/retrieval.jsonl 2>> $OUT/logs/retrieve.log`<br>接著 `ba_analyze.py check --out $OUT --partial`（I0–I4），不過就停 | 25–45 分 |
| 3.2 | 檢索其餘題 | 同一條 retrieve 指令，不帶 `--ids-file` | 1.5–3 小時 |
| 3.3 | 驗證與凍結 | `ba_analyze.py check --out $OUT`：I0–I5、子集、機制標記、gen_plan、judge_ids、judge_order、overlap、freeze.json | 2 分 |
| 3.4 | 檢索指標 | 先 `export-retr`。再對每個 arm 與 k∈{5,6}，在 evaluation/ 目錄下執行：<br>`$PY -B quick_retrieval_eval.py --from-raw $OUT/retr/$arm/raw_responses.json --gt v2 --top-k 5 --metric-k $k --label $OUT/retr/$arm.k$k` | 15 分 |
| 3.5 | 生成 | `"${BA_RUN[@]}" generate --plan /in/checks/gen_plan.json --retrieval /in/retrieval.jsonl --resume /in/gen.jsonl >> $OUT/gen.jsonl 2>> $OUT/logs/generate.log`<br>約 582 次：ctrl 39×6、nopin 19×6、off 39×6。generate 模式不載入嵌入與 rerank 模型 | 2.4–3.4 小時 |
| 3.6 | 匯出答案 | `export-ans` 寫出 `ans/{arm}_r{1..6}/`，包含所有 (q, arm, rep)，失敗的答案也照寫 | 1 分 |
| 3.7 | strict 判分 | 依 judge_order 跑 9 個目錄（r1 的三臂、r2、r3，臂序依 seed 打亂）。每個目錄開始前，先把 `curl -s localhost:11434/api/ps` 附加到 `judge/logs/ollama_ps.log`。<br>在 evaluation/ 下執行：`COLUMNS=1000 $PY -B quick_faithfulness_eval.py --results-dir $OUT/ans/$d --ids-file $OUT/checks/judge_ids_$arm.json --gt v2 --no-rebuild --out $OUT/judge/$d.faith.json > $OUT/judge/logs/$d.log 2>&1` | 1.8–2.1 小時 |
| 3.8 | coverage 判分 | 依 judge_order 跑 18 個目錄：`$PY -B $EXP/ba_cov.py --results-dir $OUT/ans/$d --ids-file … --gt v2 --out $OUT/judge/$d.cov.json`；最後再重判一次 ctrl_r1，存成 `ctrl_r1.cov_rep.json` | 30 分 |
| 3.9 | 報告 | `ba_analyze.py report --out $OUT` 寫出 `report/report.json` 與 `report.md`，內容含判定、prod 動作、§5 全部項目與重疊 | 5 分 |
| — | **commit ②** | 見 §10 | — |

**時程**：步驟 0–2 白天完成；步驟 3 可以從下午開始跑。判分不和生成同時跑。

**資源**
- 批次容器多佔約 5–6 GB RAM。
- torch 用預設的 24 執行緒，夜間會和 prod 的 rerank 搶 CPU。
- PG 連線 2–10 條。
- Ollama 和他人的 vLLM 共用 GPU，26b 判分時合計約 85 GB。
- 跑實驗期間 prod 的回答會變慢。開跑前通知 Kay 一次即可，不需要其他簽核。

## 10. 程式、測試、commit

程式放在 `$EXP`。檔名不可與 backend 的頂層模組（config、utils、serving、database、models、routers、main）重名。

| 檔 | 內容 | 約行數 |
|---|---|---|
| `prereg.md` | 本計畫定稿；跑完後追加執行紀錄 | — |
| `compose.ba.yml` | backend-stg 的 healthcheck 改成 NONE | 4 |
| `oc_sim.py`、`oc_out.json` | §7 的模擬，從 scratchpad/ba/final/ 複製 | 90 |
| `_ba_io.py` | JSONL 讀寫：每行帶 kind，遇到壞行就 raise；截到最後一個換行；續跑鍵；`ctx_sha(results, build_blocks)` | 70 |
| `ba_arms.py` | ARMS、`arm()`（不可重入鎖、finally 還原）、gather 快照、pin 記錄器、nopin 與 off 的替換；要替換的模組由參數注入 | 110 |
| `ba_driver.py` | 容器入口。`retrieve`：照 main.py 的 lifespan 初始化、輸出 meta 行、包裝並重試 intent、每題依序跑 ctrl→nopin→off、重試 strategy_errors、輸出完整 results 字典、池摘要（id、strategy、weight、semantic_score、rerank_score）、pinned、ctx_sha。`generate`：做 I7 檢查、呼叫 `generate_answer`、記錄 messages 的 sha、失敗重試 | 250 |
| `ba_prep.py` | 產生 questions.json、batch_a.json、exp_meta.json，含 git 斷言、映像 ID、Ollama digest；`--smoke` 模式 | 90 |
| `_ba_checks.py` | I0–I5、子集、機制標記、gen_plan、judge_ids、judge_order、overlap；附凍結的 `eval3c_ref.json`（43、39、20 題，以及單書釘選 19 題） | 230 |
| `_ba_export.py` | 依 collector 格式寫 raw_responses.json 與 run_meta.json。sources 的欄位映射照 routers/query.py 的 `_source`；寫 contexts 時再驗一次 sha | 110 |
| `ba_cov.py` | 只判 coverage：用和 `quick_faithfulness_eval._load` 相同的方式載入，再呼叫它的 `_coverage`；用 logging handler 收下逐要點判定寫進 JSON | 50 |
| `_ba_stats.py` | 有效次數規則、t-CI、sign-flip、Holm（沿用 src/ab_stats）、500 題換算、`verdict()`、`prod_action()`、各項描述指標 | 200 |
| `ba_analyze.py` | CLI 子命令：smoke、check [--partial]、export-retr、export-ans、judge-order、report | 150 |
| `run_ba.sh`、`README.md` | 步驟 3 的串接腳本與使用說明 | 110 |

**測試**（`evaluation/tests/test_ba_*.py`，先寫測試）

不設覆蓋率數字，因為 venv 裡沒有 pytest-cov。改為要求：§8 每一條判定路徑、I0–I7 每一個失敗分支，都至少有一個測試。

- **test_ba_arms.py**
  - 替換後會還原，例外路徑也會還原；
  - 巢狀或並行進入時 raise；
  - nopin 拿到的是 ctrl 快照的深拷貝，不受 ctrl 之後就地改寫影響；
  - 沒有快照時 nopin 會 raise；
  - nopin 的 pin 替換在 book_gate=False 時回傳原本的 ranked，True 時把參數原樣傳給原函式；
  - off 回傳 `[]`；
  - 記錄器記下的 id 與 book_gate 正確；
  - 實驗模組名稱沒有和 backend 衝突。
- **test_ba_io.py**
  - 半行會被截掉；沒有 kind 或格式壞掉的行會 raise；
  - 續跑鍵正確；
  - ctx_sha 與 `evaluation/src/context_blocks.format_context_block` 組出的內容一致；
  - JSON 來回轉換後 sha 不變；
  - 欄位改名（例如 book_name→book）時 sha 不符。
- **test_ba_checks.py**
  - 合成資料全部通過；
  - I0–I4 各自的失敗都能偵測到；
  - 子集、sha、gen_plan 的打亂與 judge_order 都是決定性的；
  - context 相同的臂不排進生成；
  - 四種機制標記正確；
  - 重疊計算正確。
- **test_ba_export.py**
  - 匯出的檔案能被 `quick_retrieval_eval.samples_from_raw`、`provenance.read_run_meta`、`evaluator.load_samples_from_checkpoint` 讀回；
  - context_format 是 generator_blocks；
  - 失敗的答案照寫，且 `validity.answer_failure` 判為 generation；
  - contexts 的 sha 不符時 raise。
- **test_ba_stats.py**
  - 決策表每一格都有案例：三種傷害成因、可改、顯著改善、無法判定、無效、nopin 傷害時擋下 off、off:nopin 不過時改採 nopin、上界 < 0 時改採 nopin；
  - 有效次數規則；
  - t-CI 與 scipy 的結果一致；
  - Holm；
  - 500 題換算。

driver 只在容器內跑，靠 smoke、I0–I4 與 I7 驗證。

**commit**：只加上述路徑。不碰工作樹裡的 `test_graph_gd_ho_order.py` 修改，也不碰 compose 的 .bak 檔。
- **①** smoke 通過後、正式跑之前：`feat(evaluation): book_anchor 消融 driver、分析與事前登記`。
- **②** 結果出來後：`docs(evaluation): book_anchor 消融結果與判定`。內容是 prereg 的執行紀錄與 `report.md` 的副本；原始檔留在 store。
- **③** 只在判定要改時做，另起一件工作，見 §12。

## 11. 輸出位置

`/mnt/ollama-data/bible_rag_store/reports/ba_ablation_20261015/`

```
questions.json  batch_a.json  exp_meta.json  retrieval.jsonl  gen.jsonl
smoke/  logs/
checks/  invariants.json subsets.json gen_plan.json judge_ids_{ctrl,nopin,off}.json
         judge_order.json overlap_eval3c.json mechanisms.json freeze.json
retr/    {ctrl,nopin,off}/raw_responses.json+run_meta.json   {arm}.k{5,6}.json
ans/     {ctrl,nopin,off}_r{1..6}/raw_responses.json+run_meta.json
judge/   {arm}_r{1..3}.faith.json  {arm}_r{1..6}.cov.json  ctrl_r1.cov_rep.json  logs/
report/  report.json report.md
```

## 12. 回滾與上線

**實驗本身**
- prod 沒有任何改動。
- 要中止就 `docker stop bible_rag_ba`（容器帶 `--rm`）。
- 不要的輸出直接刪掉 `$OUT`。
- commit ① 可以保留當紀錄，也可以 revert。

**若判定要改**（commit ③，另起一件工作）
1. **改 backend**：照 §3 的「上線對應改動」一欄修改，先在 backend/tests 寫測試。
2. **建映像**：用衍生映像，不重建、不連網。
   - Dockerfile 內容：`FROM bible_rag-backend:r2`、`COPY backend/ ./backend/`；context 用 repo 根目錄，才吃得到 .dockerignore。
   - tag 為 `bible_rag-backend:r2-ba1`，用 `docker save | zstd` 存到 bak。
   - 執行 `docker create --name keep_r2 bible_rag-backend:r2` 釘住 r2，避免被 Komodo prune；確認 bak/20261008/images 的 tar 存在。
3. **切換**：把 compose 的 image 改成新 tag，執行 `docker compose up -d --no-deps --no-build --pull never --wait backend`，再跑 smoke20。
4. **驗證上線的程式就是測過的臂**：
   - 新 prod 跑 500 題 retrieval_only：`--include-context --top-k 5 --metric-k 6`。
   - 和 `retr/{採用的臂}` 比對：路由相同的題，id 序列（含附加槽）必須 100% 相同。
   - 不一致時，附上同 id 的 |Δscore| 來判斷原因；路由不同的題重問一次。
   - 兩邊都用預設的 24 執行緒，前提一致。
5. **回滾**：把 image 改回 r2，執行同一條 `up` 指令，再跑 smoke20。

**若維持現行**：另外把 pins.py 的「measured neutral」改成引用本次結果。這只是一行註解，等下次建映像時一起處理。

## 13. 已知限制與結論範圍

- **結論範圍**：只適用於「GT v2 中走 R5（含 fallback 1–2 題）的跨卷題，並以本次單一 intent 抽樣的路由為條件」。
  - 假說來自同一批 39 題。重新生成只排除了生成雜訊造成的選題偏差，沒有 holdout。
  - 這批題集中在 prophecy_fulfillment、typology 等家族。
- **路由覆蓋**：R3、R4、R6 在這份 GT 上從未產生 book_anchor 候選。fallback 只有 1–2 題：VERSE_LOOKUP_097 有釘選，GBQ_073 走 fallback 時也有。這些路由的效果沒有量到。
- **多書釘選**：只有 GBQ_096，n=1。所以 nopin 保留多書釘選；off 會刪掉它，相關風險見 §8。
- **coverage 的意義**：在這批題上，coverage 幾乎就是 gold 經文的召回，量不到「讓題目點名的書出現」這個原始用途。後者只在描述性指標中報告。
- **判分雜訊**：每份答案只判一次，判分雜訊併入每次生成的變異；judge 決定性只做描述性重判。
- **intent 重試**：intent 失敗時會重試，這與 prod 直接退回 topic 的行為不同。次數會列在報告裡。
- **off−nopin 含連帶效果**：supplement、浮點、章節 pin 資格、附加槽也會跟著變（§3、§4 有標記）。
- **替換不等於最終程式**：由 §12 的 500 題逐位比對補上。

## 執行紀錄（2026-10-16 追加，跑完並讀過報告後）

追加前本檔 sha256 `3b80d81c…`（等於 exp_meta 的登記值），以上各段沒有改動。報告副本是本目錄的 `report.md`，與 store 的 `report/report.md` 逐位相同（sha256 `abeedd24…`）；`report.json` 的 sha256 是 `a7148c41…`。

### 執行紀錄一：暫停、重開機與續跑

- **開跑**：2026-10-15 11:58（UTC+8），HEAD 4510a16，映像 `bible_rag-backend:r2`（sha256:c79266296cb0…），Ollama e4b `9dcc35808b42`、26b `6bfaf9a8cb37`。工作樹只有登記前就有的 test_graph_gd_ho_order.py 修改與 compose .bak（§10，不碰）。
- **3.1**：batch A 85 題（11:58–12:23）。check --partial I0–I4 全過；I1 比對 84 題，id 全同，max|Δscore| 0.0；GBQ_073 路由 R5→fallback，只列出。
- **暫停**：10-15 12:57 依 Kay 要求停在 3.2（先 kill run_ba.sh，再 docker stop bible_rag_ba）。retrieval.jsonl 有 311/500 題（161 題三臂、150 題依 M1 跳過），沒有半行，還沒有任何生成或判分。PERSON_QUESTION_051 的 intent 呼叫已送出但沒寫出紀錄，續跑時重抽一次；兩次都是 R6，不在 C／U。
- **重開機**：主機 10-16 08:27 重開機，prod 三個容器自動重啟。映像、build b20261008_e05d3e55、encoder 指紋、Qdrant 34058 點都和開跑時相同。
- **續跑**：10-16 10:44 依 Kay 要求續跑，用的是 §9 的續跑機制，沒有改程式、資料、子集或樣本。ba_prep 重驗 HEAD、映像、兩個 digest、輸入與程式 sha 都通過；check --partial（311 題）I0–I4 全過；3.2 補完 189 題（10:44–11:34）。三個 retrieve meta 行除了 n_todo、argv、時間、pid 以外完全相同。
- **跨暫停一致性**：C 與 U 全部在暫停前完成的 batch A 裡。續跑段 ctrl 與 eval3c 同路由的 178 題逐位相同（881 個分數，max|Δ| 0.0）。I1 列出的 16 題路由差異有 11 題在續跑段，比例差來自題型組成（只比 EVENT／GBQ／PERSON 時 4/111 對 11/189，p=0.58）；照 §6 只列出，續跑段沒有一題進入 C 或 U。生成與判分全部在重開機之後，三臂條件相同。
- **紀錄缺口**：續跑的 check --partial 覆寫了 checks/invariants_partial.json，10-15 那次 85 題的結果只留在 run_ba.log 與 logs/PAUSED.md。兩次都通過，不影響結果；下次改成分階段存檔。
- **3.3–3.9**：11:34 check 全過並凍結（C 43、P_s 19、P_m 1（GBQ_096）、D_nopin 19、D_off 39、U 39）。生成 582 次（11:34–12:47）全部成功，attempts=1，I7 重試 0。strict 判 9 個目錄（12:47–14:07），coverage 判 18 個目錄並重判 ctrl_r1（14:07–14:31；重判 39/39 題、193/193 個要點相同）。14:31 出報告。I0–I4、I7、complete、I0_generate 全過；I5 例外 2 題（GBQ_094、095）；剔除 0 題；intent 重試 0 次；判分期間 26b digest 不變。

### 執行紀錄二：結果與判定

| 配對 | n | Δcov [97.5% CI] | Δstrict [97.5% CI] | Δvrec@5 | 判定 |
|---|---|---|---|---|---|
| nopin:ctrl | 19 | +0.003 [−0.051, +0.056] | −0.007 [−0.032, +0.018] | +0.081 | 無法判定 |
| off:ctrl | 39 | +0.016 [−0.029, +0.062] | +0.005 [−0.012, +0.022] | +0.050 | 可改 |
| off:nopin | 39 | +0.015 [−0.028, +0.058] | +0.008 [−0.009, +0.025] | +0.011 | 可改 |

- Holm p 全部 ≥0.45，三個配對都沒有傷害，也沒有顯著改善。500 題換算 strict：nopin 0.9851、off 0.9851。
- **prod 動作：採 off（§8 第 2 條）**。第 1 條不成立，因為 nopin:ctrl 不是傷害。第 2 條的例外也不成立：nopin:ctrl 不是可改，off:nopin 的 cov 上界 +0.058 也不小於 0。
- 採 off 的依據是「不劣，而且程式較簡單」，不是改善。eval3c 事後看到的 full−sem −0.082，在本次迴歸到 +0.016。
- 依 §12，改 prod 是 commit ③，另起一件工作。

### 執行紀錄三：複核與補充揭露（事後補充，不改判定）

- **獨立重算**：五個面向各自重寫程式（不 import _ba_*.py），重算結果與 report.json 的 639 個數值一致，差 ≤1e-6。唯一差異是 cov 的蒙地卡羅 sign-flip p 與精確值差 0.002–0.004，在 MC 誤差內，Holm 後都是 1。子集、.src_sha、判分 meta、凍結 sha、I4 逐題設定、生成順序都核對過；test_ba_*.py 重跑 187 passed。複核腳本與結果在 store 的 `review/`（`review_summary.json`）。
- **判定的穩健性**：off:ctrl 的 cov 下界離門檻 +0.021，逐題剔除沒有一次翻轉；重抽生成時約 0.75–0.90 仍判 off。nopin:ctrl 的下界只差 0.00064（逐題剔除有 4/19 會翻），但它不論判成什麼，prod 動作都是 off。
- **檢定力比登記時假設的低**：
  - 實測逐題 Δcov 的 SD 是 0.095／0.121／0.116，是 §7 規劃值 0.060 的 1.6–2.0 倍，原因是 OC 沒有建模題間的真效果異質。
  - 真 Δ=0 時判「可改」的機率約 0.44（n=19）與 0.60（n=39）。所以 nopin 的「無法判定」主要是檢定力不足，不代表 nopin 有害，也不代表它比 off 差。
  - t-CI 用的是樣本 SD，型一錯誤控制不受影響。strict 的 SD 與規劃相符。
  - 下次登記改用「題間異質＋生成雜訊」的兩層模型。
- **off 的描述性代價**（§5 規定不入判定；report.md 沒有呈現）：
  - **點名書出現率**：點名書全部出現在 top-5 的題數，D_off 上 ctrl 38/39、nopin 34/39、off 19/39；多書題從 15/16 降到 6/16。這是本功能的原始用途，coverage 量不到。
  - **拒答或含糊**：ctrl 13 份、off 28 份（各 234 份），逐題 9:2，sign test p=0.065（未校正）；嚴格拒答從 8 增為 15。機制是點名書從 context 消失後，生成器回答「經文未提及該書」。這部分代價已部分算進 cov；refusal_v2 的計數是下界。report.json 的 refusals.wins 是 x 拒答較多的題數，對 x 不利。
  - **逐題有雙向的真實效果**：生成雜訊只解釋 off:ctrl Δ_q 變異的 33%。
    - 最大損失：GBQ_028 −0.283、GBQ_031 −0.217、GBQ_041 −0.150、GBQ_097 −0.133、VERSE_LOOKUP_097 −0.111。
    - 最大增益：GBQ_095 +0.300、GBQ_090 +0.250、GBQ_099 +0.200、GBQ_089 +0.167、GBQ_040 +0.133。
    - 沒有一題掉超過 0.3。精確檢定加 BH 後穩健退化的約 3 題（031、096、098），39 題做 Holm 後 0 題。
- **§13 限制的實測**：
  - **多書釘選**：唯一實例 GBQ_096 在 off 下 Δcov −0.083，屬探索性結果（n=1）。6 次中 5 次較低、1 次持平，差異全部來自第 4 點由 partial 變 missing。被釘的 rev.21.9 不是 gold（gold 是 rev.21.1–4），vrec5 沒有變；多書分層（n=16）整體 −0.003，屬中性。§13 說這項風險「見 §8」，但 §8 的 off 附註沒有寫，是登記本身的斷鏈。日後若要再測，可以列「off＋保留多書缺席書釘選」這一臂。
  - **路由覆蓋**：報告的範圍句是照 §8 寫死的文字，實測數字以這裡為準。
    - R3 在 GT v2 是 0 題，屬於零曝險，不是量到 0。
    - R4（126 題）與 R6（63 題）都沒有產生新候選（只有 11 題多了 found_by），off 的 ctx_sha 與 ctrl 相同。
    - fallback 45 題中有 2 題產生候選（VERSE_LOOKUP_097、GBQ_073）。
    - D_off 中 VERSE_LOOKUP_097 是單書題，所以「跨卷題」實際是 38/39。
- **其他（low）**：
  - nopin:ctrl 的 strict 與 vrec5 各只有 4 個非零差，所以這兩項的傷害檢定在結構上不可能顯著；strict 靠不劣 CI 守住。
  - 500 題 strict≥0.97 這一關在本設計下沒有鑑別力。
  - off:ctrl 與 off:nopin 有 20/39 題的配對差相同（r=0.85），所以第 2 條的兩個「可改」不是獨立佐證；這是 §5 的設計。
  - mechanisms 對 GBQ_094、095 漏標 (iii)（supplement 換段）。
  - report.md 的 500 題 strict 誤帶正號；表格缺 §5 要求的 W:L:T 與 95% CI，這些在 report.json 裡。
- **偏離登記**：除了 §0.2 的 13 條以外，沒有新的偏離。
- **commit ③**：照 §12 執行。上線後除了 500 題逐位比對，另把 prod 的拒答率列為觀察指標。
