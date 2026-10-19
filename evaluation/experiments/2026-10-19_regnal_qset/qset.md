# 問法集：年表卡在真實問法下的觸發召回（prereg）

> **正式 prereg（2026-10-19 主 session 審過，§12 已決定）。** 本版 commit 之後才跑 `run_q.py gen／refill／label`；`score_q.py score` 要等 §10-5 把 r4 層 sha 寫進 `q_common.SCORE_LAYER_SHA256` 之後。

標記：「實測」是用 CPU 或已跑的 probe 量到的數；「推估」是推算。公開 repo：本文不引經文，不引任何題目原文（王名、經節 key、題號可以）。

## 0. 狀態與範圍

- **目的**：量年表卡（`backend/utils/regnal/`）在真實問法下多常被觸發（R_trig），以及觸發後規則種子與卡片能不能接上（R_seed、R_card）。
- **不量**：答案品質；gemma 備援的種子（不叫 Ollama）。
- **出題分工**：寫手只負責措辭，不查經、不給答案。gold 全部由程式從參考層算出，所以沒有稽核、修題迴圈或人工抽查頁。
- **已做**（2026-10-19）：
  - 工具與測試（本目錄、`evaluation/tests/test_regnal_qset.py`，commit 08c117e）；
  - `spec.json` 寫入 store；
  - 2 次 probe 與釘版（§8）。帳本 0.039748 USD（實測）。
- **還沒做**：正式出題（gen、label）、任何計分。
- **預算**：Kay 2026-10-19 授權 ≤10 USD（§7-4），P1 召回 < 0.70 才放寬觸發。

## 1. 母體

**參考層**：store `reports/regnal_fix_20261019/ref_layer_v2.json`，sha `e39e04f2…`（實測）。

- 它和程式在記憶體從實驗 A 的凍結檔 `79d57efe…` 推導的結果逐位元相同（實測）。推導規則：刪所羅門（J00），羅波安（J01）改成 founder。
- 原檔從不寫回。檔案不存在時，`spec_q.load_ref` 就用記憶體推導，並驗原檔 sha 與推導後的 sha。

**慣例**：
- 亞她利雅算一位猶大王；所羅門不在鏈上（Kay 2026-10-19 裁決）。
- 亞她利雅的邊型別是 `queen_usurp`，不計入「第 n 個篡位者」：引擎只數 `usurp`，不改（主 session 預設）。
- 鏈長：以色列 19、猶大 20（實測）。

**題型格**（實測，`spec_q.cells`）：

| 題型 | 定義 | 格數 |
|---|---|---|
| S1a | 起點王之後／之前第 k 位，k ∈ {±2, ±3} | 136 |
| S1b | 同國兩王相隔 2–4 位，答案＝交接次數 | 99 |
| S1c | 起點王之後第 n 個篡位者，+3 以內、至少 2 次交接；只有以色列（猶大鏈沒有 `usurp` 邊） | 13 |
| S4 | 猶大王出生時在位的猶大王 | 13 |

S4 用寬的 13 位：
- 有登基年歲、往回累加（引擎慣例甲：在位年數首尾相接）落在某位王、邊距 > 0；
- 排除亞哈謝（J06）與約雅斤（J19），因為列王紀與歷代志記的年歲不同。

## 2. 切分與配額

**切分**：
- 同一主名的王併成一個單位，共 34 個單位（實測）。
- 依「有 S4 起點／有 S1c 起點／國別」分層，每層用種子 `20261019` 打亂，跨層交替發給 P1、P2。
- 結果（實測）：

  | | 王 | S1a 格 | S1b 對 | S1c 格 | S4 起點 |
  |---|---|---|---|---|---|
  | P1 | 21 | 73 | 28 | 8 | 6 |
  | P2 | 18 | 63 | 21 | 5 | 7 |

- 判一格屬於哪一邊，只看題目會點名的王：起點王，S1b 另加另一端。答案王不寫進題目，所以可以在另一邊。

**配額**：

| | S1a | S1b | S1c | S4 | N1 | N2 | N3 | N4 | N5 | 合計 |
|---|---|---|---|---|---|---|---|---|---|---|
| P1 | 28 | 12 | 10 | 10 | 4 | 4 | 3 | 2 | 2 | 75 |
| P2 | 24 | 10 | 8 | 8 | 3 | 3 | 3 | 2 | 2 | 63 |

- S1a：國別、方向各半，|k|=2 與 3 約 2:1；不重抽。
- S1b：國別各半，距離 2／3／4 平均。
- S1c、S4：每格最多出 2 次，全部格先各出一次才出第二次。
- 近似題（不該觸發），王也屬於該邊：
  - N1：單一屬性（在位多久、登基年歲、母親、父親）；
  - N2：事件（怎麼死、怎麼得位、做了什麼、哪位先知）；
  - N3：跨國同步紀年，兩王都在同一邊；
  - N4：同時代的王；
  - N5：家譜（猶大王：從大衛到他幾代；以色列王：祖父是誰）。

**job 組成**：
- 每個 job 恰好 1 題 S1a；S1b、S1c、S4、近似題每種最多 1 題，共 2–5 題。
- 同一格出兩次時，必須在不同 job、不同 persona。
- 題位用不透明代號 q1… 並打亂順序。寫手看不出哪題是近似題，也看不出題號、P1／P2。
- 實測結果：
  - P1：28 個 job、75 題（2 題的 9 個、3 題的 19 個）；
  - P2：24 個 job、63 題（2 題的 9 個、3 題的 15 個）。
- 寫手模型：opus／sonnet 各半（P1 14／14、P2 12／12）。persona 5 種，各 4–6 個 job。
- 執行順序：P1、P2 的 job 交錯（`spec.order`）。
- spec sha（canonical）`ef7ee499…`（實測）；`spec_q.py check` 重建結果相同。

## 3. 寫手與盲化

**寫手看到的**：
- `prompts_q.md` 的 system 與 task_gen；
- persona 一句（中文）；
- 每個題位：intent、一行英文 definition、王名（含可用的又名）與國別、k／n／另一端的王／aspect；
- 同名王的 note。

寫手看不到答案王。

**定義用英文**：中文定義為了避開線索詞，只能改用 regex 沒收的同義詞，召回會被低估；直接用線索詞，召回又會被高估。

**又名**：只給不和其他鏈上王同名的又名。例如亞哈謝的「約哈斯」「亞撒利雅」不給，約哈斯（猶大）的「沙龍」不給。

**輸入端 banned**（`banned_q.check_prompt_text`；渲染後的 system、user、schema 每一段都要過，否則拒跑）：
1. `trigger.py` 的 CUES 直接 import，對 NFKC 文字 search，必須 0 命中。
2. 線索字面清單：之後、之前、以後、以前、往前數、往後數、接續、作王、繼位、交接、相隔、篡、出生時、出生的時、出生那年、在位。
   - 測試對每個 CUES 分支各造一個標準例子，斷言例子含清單裡的詞，而且把那個詞換掉後該分支就不再命中。CUES 改了而清單沒跟上，測試就會失敗。
3. HO `banned.py`（sha `d2226711…`）與 A `banned_a.py`（sha `54669928…`）的 PROMPT_TERMS，用 sha 釘住、以檔案路徑載入，不改原檔；再加本實驗的目的詞。
4. MEMORY_MARKERS：HO＋A，加上本實驗的程式形態標記：trigger.py、trigger.CUES、_KTH、utils.regnal、regnal_layer、aux_card、use_regnal_card、年表卡、ref_layer、layer_auto、regnal_qset 等。
   - regnal、cues 是一般英文（regnal year），寫手的英文 thinking 會自然用到，所以只放在輸入端的目的詞：prompt 一律禁用，但 transcript 出現不算 t_memory（審查 2026-10-19）。

**輸出端不限詞**：寫手寫出線索詞不是污染，不記任何違規。transcript 規則（`transcript_q`）只有這些：
- t_init：cwd `/srv`、模型、tools ⊆ {StructuredOutput}、無 MCP、dontAsk；
- t_tool；
- t_memory：任何可見文字，含寫手輸出；
- t_banned：只查 prompt；
- t_result。

任一盲化錯誤，該 job 的輸出作廢，進補出輪。

**模型改派**：出現 `model_refusal_fallback`，或 modelUsage 有 job 模型以外的模型，算基礎設施失敗：重跑，最多 2 次，該次輸出不用。

## 4. 機械檢查與標註

**有效性**（不合格就剔除，題位補出一輪，同 persona、同寫手；剔除的題不進任何分母）：
- v_slot：題位與題數相符、非空、≤200 字；
- v_simplified：沒有簡體專用字；
- v_duplicate：同一邊內文字重複，NFKC 後去空白比對；
- v_answer：S1a、S1c、S4 題點名答案王。和起點王共用的名字不算；起點王的**父名標記**裡的名字也不算（偵察 §2.6 的例外，見下）。

**父名標記**：同名王的 note 要求寫手分清是哪一位，最自然的寫法就是寫父名，而起點王的父親有時正好是答案王（實測：S1a:I09-2、S1a:J08-2、S4:J17 三格，其中 S1a:J08-2、S4:J17 在 P1）。
- 認定：F 是端點王 X 參考層父親的名字之一，寫成「F(王)的兒子X」「F(王)之子X」「X(F(王)的兒子)」「X(父親(是)F)」「X,父親(是)F」「X是F的兒子」（NFKC 後比對；形式取自規則種子的父名標記）。
- 答案王只出現在父名標記裡：有效，記旗標 f_father_is_answer，留在分母另報。
- 父名標記裡的中間王不記 f_between。

**旗標**（只記錄，題目留在分母）：
- f_start_unnamed：沒點名起點王；S1b 是沒點名兩端。
- f_between：點名了中間的王（父名標記裡的不算）。
- f_father_is_answer：答案王只出現在起點王的父名標記裡。

**標註器**（opus、effort high、每批 10 題、同一邊內依種子打亂）：
- 只看題目文字。
- 輸出：intent（9 類＋other）、起點王、國別、k、n、另一端的王。
- 一致的條件：
  - 正例：intent、起點王、國別（或「不明」）、k（offset）、n（usurper_n）、兩端（handovers）都相符；
  - 近似題：標註器沒有把它讀成 4 種正例 intent 之一。
- 不一致的題不剔除，另外報。

## 5. 量測定義（`score_q.py`，CPU）

逐題累積，後一階段要前一階段成立：
- **R_trig**：`trigger(question, layer.names[, layer.blockers])` 觸發。失敗分三類：king_miss（沒找到鏈上的王）、cue_miss（有王、沒線索）、king_and_cue_miss。
  - 層照 backend 的方式建：`parse_layer` 之後，本 checkout 的 layer 模組有 `with_lexicon`（規則種子那個改動）時，就像 `make_active` 一樣掛上 build 的 routing lexicon（`--lexicon`，預設是 `--layer` 旁邊的 routing_lexicon.json；找不到就拒跑），trigger 收 blockers 參數時就傳 `layer.blockers`。
  - 實測（scratch 解出 feat/regnal-rule-seeds 的碼）：b20261019_18aa84ad 的詞庫給 28 個 blockers；1062 筆（兩版 GT＋開發集＋確認集）裡 6 筆的 kings 會因此不同（PERSON_QUESTION_010、015、027，v1、v2 各一），現行線索下觸發差 0。
- **R_seed**：`seeds.rule_seeds(layer, question)` 的節點包含 gold 起點王；S1b 要包含兩端。
  - gold 從參考層 id 對到計分層 id，依國別、名字、同名順序。
  - backend 還沒有 `rule_seeds` 時記 n/a。
  - 介面預期 `rule_seeds(layer, question)` 回傳帶 `.ids` 的物件，或節點 id 序列。
- **R_card**：`engine.cards` 用那組種子做出的卡裡，有被問的那一行（succ k、usurper n、born、gap），而且 payload 等於參考層 gold（王名；S1b 是交接次數）。
- **R_card_oracle**（描述）：已觸發的題改用 gold 種子組卡，只檢驗層與引擎本身。

**分母**＝全部有效正例。標註不一致、未標註、有旗標的題都留在分母，另外再報（依挑錯報告更正）。
- 另報：依題型、國別、寫手模型、persona 拆分；標註一致／不一致兩組；三種旗標（f_start_unnamed、f_between、f_father_is_answer）。
- 95% CI 用 Wilson。

**誤觸**：
- 近似題逐族計數；標註器讀成正例的近似題（灰區）另報。
- 500 題 GT v1、v2（repo 根目錄）逐題列出觸發的 question_id。

**回歸**（樣本內，只看觸發）：實驗 A 的開發集 30 題、確認集 32 題，列出沒觸發的題號。

**計分層**：P1、P2 都用層修正後的 r4 層計分。
- `score`、`gt`、`regress` 都必須給 `--layer`，沒有預設層：`gt`、`regress` 也是放寬的採用門檻，層的名單不同結果就不同（實測：點名鏈上王的 GT 題，prod 層 21 題、候選層 1789c0de 15 題）。
- r4 的 sha 在正式 prereg 時寫進 `q_common.SCORE_LAYER_SHA256`（§12-5）。`score`：
  - 一律拒絕修正前的 prod 層 `932d2242…`（`contracts/b20261019_18aa84ad/regnal_layer.json`，只能用 `gt`、`regress` 描述）；
  - 釘了之後，sha 不符就拒跑；
  - 沒釘之前，P2 拒跑（P2 只跑一次，必須在事先登記的層上）。
- 每次結果都記：
  - 層 sha 與角色（score_pin／pre_fix／unpinned）；
  - 詞庫的路徑、sha 與 blockers 數（沒有 `with_lexicon` 時記 null），trigger 有沒有收 blockers；
  - 從本 checkout import 的 trigger.py、seeds.py、engine.py、layer.py、ragcommon/regnal.py、ragcommon/routing.py 的 sha；
  - spec 與 items 的 sha；
  - `rule_seeds` 有沒有。

**基線**（現行 trigger.py `161a5a98…`，prod 層 `932d2242…`）：
- 500 題 v1 觸發 0/500、v2 觸發 0/500（實測）；
- 開發集 27/30，沒觸發的是 N_KIN_14、N_SUC_01、SUC_01（實測，樣本內）；
- 確認集 32/32（實測，樣本內）。

**層的上限**（gold 種子，所有格都用模板種子組卡，不經觸發；實測）：
- 修正候選層 `1789c0de…`：261/261。
- prod 層 `932d2242…`：233/261。
  - 分題型：S1a 122/136、S1b 87/99、S1c 11/13、S4 13/13。
  - 有 10 格因為層裡沒有亞她利雅而對不上；其餘 18 格是 payload 錯或缺行。

## 6. 門檻與放寬規則（看結果前寫死，用點估計）

1. P1 的 R_trig（分母見 §5）< 0.70 才放寬觸發規則。
   - 放寬時只能看 P1 與開發集沒觸發的題。不看確認集，不看 P2。
2. P1 R_trig ≥ 0.70：不放寬。P2 照樣跑一次，當樣本外的描述數字。
3. 放寬後要**全部**成立才採用：
   - 500 題 v1、v2 觸發仍是 0；
   - P1、P2 的近似題各誤觸 ≤1 題，而且 P2 上新規則的誤觸不多於舊規則；
   - P2 上 R_trig 新 ≥ 舊（同一批題配對，`--compare-trigger` 舊 trigger.py）；
   - 開發集 ≥27/30、確認集 32/32。
4. 任一條不成立：不採用放寬，維持舊規則，並照實記錄。

統計限制：
- P2 正例 50 題、p＝0.7 時，95% CI 是 [0.562, 0.809]（Wilson 公式計算）。
- 近似題 0/13 的單側 95% 上界是 0.206。近似題只能當煙霧偵測器，不能證明誤觸率很低。
- 500 題在放寬之前沒有誤觸資訊：現行規則的 CUES 在 500 題上 0 命中。

## 7. P2 協定

- P2 的題目、transcript、標註只放 store（`reports/regnal_qset_20261019/p2/`）。repo 只記 sha 與計數。
- `run_q.py` 對 P2 不印題目、王名、標註，`show` 只印 P1。`status` 只給計數。
- `score_q.py score --set p2` 只輸出彙總（計數、比例、Wilson CI、近似題誤觸），不輸出題號或題目。
  - 每跑一次附加一行到 `p2_runs.jsonl`，記錄規則 sha 與層 sha。
  - 第二次要加 `--again`，而且必須在報告揭露。
- P2 只跑一次：新、舊規則在同一次用 `--compare-trigger` 一起輸出。
- `score --set p2` 在 `SCORE_LAYER_SHA256` 釘好之前拒跑，層 sha 不符也拒跑（§5），所以漏給或給錯 `--layer` 不會用掉這一次。
- 不加密、不加簽核：這是約定加上「只輸出彙總」的程式。

## 8. CLI 釘版與 probe 結果

**釘版**：
- CLI `2.1.302`，即 `~/.local/share/claude/versions/2.1.302`，sha `60d7eb7f12fbb28a…`（實測；和實驗 A 同版）。
- 每次 launch 先驗 sha，再把它連結成 `<root>/<sub>/clibin/claude`，放在 PATH 最前面，版本檢查和 launch 都看到它。
- child env：去掉 CLAUDE*、`DISABLE_AUTOUPDATER=1`。
- 其他旗標照 A：`--system-prompt`、`--setting-sources local`、`--strict-mcp-config`、`--disable-slash-commands`、`--no-session-persistence`、`--settings` 掛 bt-guard 當保險。bt_guard.py 是 HO 原檔的逐字複本，sha `a81cba6e…`。
- 寫手 `--tools ""`。

**probe**（2 次，合計 0.039748 USD，實測；同一個 P1 job 的 3 題，輸出不進題集）：

| | 模型參數 | 解析出的 id | init tools | 費用 USD | output（thinking） | 第一個請求 | 改派 |
|---|---|---|---|---|---|---|---|
| 1 | claude-opus-5-5 | claude-opus-5-5 | [StructuredOutput] | 0.025108 | 471（226） | 1,962 token | 無 |
| 2 | sonnet | claude-sonnet-5-5 | [StructuredOutput] | 0.014640 | 678（470） | 1,966 token | 無 |

- `--tools ""` 時，`--json-schema` 的 StructuredOutput 還在，兩次都有 structured_output（實測）。
- 第一個請求 < 2,000 token：沒有載入任何說明檔（實測）。
- 兩次 5 條檢查都過（`probe/verdict_1.json`、`verdict_2.json`）。
- `cli_pin.json`：tools_mode none，models {opus: claude-opus-5-5, sonnet: claude-sonnet-5-5}。
- effort：寫手 xhigh、標註 high。

## 9. 費用

- 硬上限 `USD_CAP`＝10 USD。
- 單 job 上限：寫手 0.2、標註 0.2、probe 0.3。
  - probe 上限另有兩條：最多 2 次、合計 ≤0.6。已用完。
  - 寫手上限約是 opus probe 實測的 8 倍。
- 帳本：
  - 每個 run 取 result 的 `total_cost_usd`；沒有 result 的 run 以 launch 前寫的 reserve 上限計。
  - 每次 launch 前先拿鎖，檢查「已花＋本 job 上限 ≤ 10」。
  - 帳本存在 `ledger/`。
- 預估（推估）：
  - 寫手 52 個 job × 0.015–0.025，加補出約 1.0–1.4；
  - 標註約 14 批 × 0.02–0.05，約 0.3–0.7；
  - 合計約 1.5–2.2 USD，加上已花的 0.04。
- 重跑：只有基礎設施失敗才重跑，每 job 最多 2 次。碰到代理上限（預算、structured output 重試）的 job 算數，不重跑。
- 啟動前就停下的 job（預算拒跑；launch 被拒，例如 /srv 不空、CLI sha 或版本不符）不寫 draft、不寫標註檔，下一次 `gen`／`label` 會重跑；唯一一輪補出只留給無效題（審查 2026-10-19）。輸出的 `stopped_why` 列出 job 與原因。

## 10. 執行順序

1. `spec_q.py build`；`spec_q.py check`。已做，sha `ef7ee499…`。
2. probe ×2、`run_q.py pin`。已做。
3. 主 session 審本文，commit 正式 prereg（把「草稿」改掉，記下 commit）。
4. `run_q.py gen`（P1、P2 交錯）→ `mech` → `refill`（一輪）→ `mech` → `label` → `mech`。
5. 層修正上線後，把 r4 的 sha 寫進 `q_common.SCORE_LAYER_SHA256`，用 r4 層：
   - `score_q.py score --set p1 --layer <r4 regnal_layer.json> [--lexicon <r4 routing_lexicon.json>]`；
   - `score_q.py gt --layer <r4> [--lexicon …]` 與 `score_q.py regress --layer <r4> [--lexicon …]`，結果的 `rules.layer.role` 必須是 score_pin。
6. 依 §6 決定放寬與否。放寬的話，改 trigger.py 要另開 commit。
7. `score_q.py score --set p2 --layer <r4> [--lexicon …] [--compare-trigger <舊 trigger.py>]`，只跑一次；放寬時也要用 r4 跑 `gt --compare-trigger` 與 `regress`（§6-3）。
8. 結果寫進 `docs/records/` 與 memory。P2 只記彙總。

## 11. 限制與風險

- **寫手偏差**：觸發規則是在看過 Opus 寫的確認集之後才放寬的；一半 job 改用 Sonnet 只能緩解。所有題都是 Claude 寫的，沒有人類問法錨點。
- **定義誘導**：英文定義仍可能把措辭推向某種說法。只能用 5 種 persona、2 種寫手和分層報告來緩解。
- **job 內相關**：同一 job 的 persona 與 system prompt 相同，總召回的 CI 應該當作有群聚效應來看。
- **P2 的鎖**是約定，不是技術封鎖。
- **計分要等 r4 層**：在 r4 之前計分，跨過亞她利雅的格 R_card 會失敗（§5 上限 233/261）。
- **R_seed 要等 `rule_seeds`**：之前都是 n/a；gemma 備援這次不量。
- **沒涵蓋的輸入**：
  - 簡體字（v_simplified 剔除）；
  - CUV 拼法；
  - 用事蹟描述、不點名的起點王（記 f_start_unnamed，留在分母）。
- **CLI 舊檔可能被清掉**：2.1.302 之後若被自動清掉，要用新版重新 probe，還要重查改派。

## 12. 主 session 的決定（2026-10-19，看任何結果之前）

1. **寫手混用 Sonnet**：維持 spec 的 opus／sonnet 各半。理由：只用一種寫手時，召回會帶著那個模型的措辭習慣；混用是 §11 寫手偏差唯一的緩解。spec sha 不變（`ef7ee499…`）。
2. **只放寬某一題型**：不行，嚴格照 §6-1，只看 P1 總 R_trig。分題型數字照 §5 另報，不當放寬依據（Kay 的裁決是「P1 召回 < 0.7 才放寬」）。
3. **近似題**：維持 P1 15、P2 13 題，門檻維持「各 ≤1 題」。P2 13 題約是 50 題正例的 26%，符合 Kay 授權的「另 25% 近似題」。它只當煙霧偵測器（§6 統計限制），不加題。
4. **人類問法錨點**：不請 Kay 另寫題（精簡流程）。這一條留在 §11 的限制：所有題都是 Claude 寫的。
5. **計分層**：r4 層 sha 等王朝層 K0-1′ 與 Kay 抽查定案、`ragdata build relations` 建出之後，另開一個 commit 寫進本節與 `q_common.SCORE_LAYER_SHA256`，必須在 `score_q.py score --set p1` 之前；`--lexicon` 用 r4 release 的 contract 目錄裡的 routing_lexicon.json，sha 一併寫進本節。
   - **已釘（2026-10-19 晚，Kay 抽查 14 項全部同意之後、`score --set p1` 之前）**：r4 release `b20261019_a86f2b06`；計分層 `contracts/b20261019_a86f2b06/regnal_layer.json`（＝`layers/relations/relations@ee8e78c043d2`），sha256 `252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11`；`--lexicon` 用 `contracts/b20261019_a86f2b06/routing_lexicon.json`，sha256 `2a172575e3d474ee22c099fcc99fda9f11eeaeba14aa69cde8bf53d9e65b991e`（＝`layers/route/route@c31c88e4681e`，和 b20261019_18aa84ad 的同一份）。
