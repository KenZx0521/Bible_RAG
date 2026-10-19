# 年表卡「規則種子」的樣本內回歸（prereg）

> **草稿，待主 session 審；正式版 commit 前不准叫 Ollama**
>
> `run_rs.py run` 會檢查本檔：還有這行草稿標記、還有層 sha 的佔位字、§1「王朝層」那一列沒寫 `--layer` 檔案的 sha256、「routing lexicon」那一列沒寫 `--lexicon` 檔案的 sha256、§1 backend 表任一列不是本 checkout 該檔的 sha256，或本檔沒 commit／commit 後又改過、harness 目錄（本目錄）有未 commit 的修改或未追蹤的檔，就在任何 Ollama 呼叫前拒跑（`test_regnal_seed_guards.py` 逐項測）。

## 0. 裁決與定位

- Kay §7-3（2026-10-19 晚）裁決：年表卡種子改成**規則優先、gemma 備援**（`backend/utils/regnal/seeds.rule_seeds`，棄權才叫 gemma 種子呼叫）。這算**處理方式變更**，用**樣本內回歸**驗收，**點估計門檻先寫死**（§6）。
- 結果一律標「**樣本內**」：規則是讀過實驗 A 的 62 題（確認集 32、dev 30）之後寫的（`seeds.py` docstring），兩組都不是盲集。
- 這**不是非劣性檢定**。門檻 −0.05 在這個題數下只抓得到約 ≥0.10–0.15 的破壞；不能寫「不劣於」。
- H1／H2 的措辭（「顯著優於正典經文窗與層列平鋪」）**只屬於舊版本**：層 932d2242＋gemma 種子＋無 S4 守門。本回歸過了也不延伸到規則種子版本。

## 1. 釘版

| 項目 | 值 |
|---|---|
| 王朝層（`--layer`） | `<r4 層 sha，待主 session 填>`（dry run 用的候選層見 §9，不是正式值） |
| routing lexicon（`--lexicon`） | `contracts/b20261019_18aa84ad/routing_lexicon.json`，sha256 `2a172575e3d474ee22c099fcc99fda9f11eeaeba14aa69cde8bf53d9e65b991e`（＝`layers/route/route@c31c88e4681e`） |
| backend 程式 | 本分支 `feat/regnal-seed-regress`（基於 int/regnal-r4 的 e3fa8be）的 checkout，執行時記錄 7 檔 sha（下表） |
| 實驗 A 程式 | 只 import、不改；`cards_common.py` ae9dc16c…（＝confirm_A.md §0 凍結值），`run_rs.py` 跑前呼叫 `c_common.frozen_mismatches()`，有不符就拒跑 |
| 模型 | `gemma4:e4b-it-q8_0`，digest `9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923`（A_confirm/night_run.log 跑前跑後 /api/ps） |
| 生成參數 | temperature 0.1、num_predict 10000、num_ctx 131072（`c_common.OPTIONS`） |
| 計分用參考層 | 實驗 A 的 `A/ref_layer.json`（79d57efe…，與 G-auto 計分同一份；**不**換 `regnal_fix_20261019/ref_layer_v2.json`，否則計分器重現不了 scores.json） |

backend 檔案 sha256（e3fa8be，本分支未改 backend）：

| 檔案 | sha256 |
|---|---|
| backend/utils/regnal/card.py | f6f463ef149554ac98b110d066fcc198092736bc5fc473a993cfbde2f1632247 |
| backend/utils/regnal/engine.py | a04d58774ee4fabbf4278f19f175d53eabfcb9e314cbdfe6363e9921e4864a95 |
| backend/utils/regnal/layer.py | e293e1f324f67eae4dc9dba17e65aeeaee3d207c1458171a27668f20aa26bf82 |
| backend/utils/regnal/seeds.py | c574d76d55f5b351b4ddb4cef4eb972ca6a304639f476be093843e25eec8bb87 |
| backend/utils/regnal/trigger.py | 90e6b528dc86d616a01c113025fc49803e72d41f7783f0caa76b24784b845cd0 |
| packages/ragcommon/regnal.py | dbcbfeb1780f7f2f055a699a3d8609df617d5428e4994ba1efb7c9a0be74ea02 |
| packages/ragcommon/routing.py | dfffe5f424c8643aa7bd7f7851534bf25e3d91b9c52e5eaa5cc331b2a4d95490 |

七檔合併 sha（`rs_common.backend().sha256`）：`e5fffc0adfd6b1568573db4ae9387e18aec6adbfc6f8d5ab59945230ec8747a6`。

## 2. 記錄的種子：檔案格式（實查）

參考臂一律**重放記錄的 gemma 種子**，不重新叫 gemma 出種子。

| 組 | 檔案（store，唯讀） | 格式 | 重放入口 |
|---|---|---|---|
| (a) | `kg_cards_20261018/A_confirm/gen_seed.jsonl` | `cards_common.run_jobs` 的 answer 行（job_id `A|題號|seed|1`）；`content` 是 gemma 種子呼叫的**原始輸出**（「國別｜王名」行，未解析，最多 4 行）。32 行，done_reason 全為 stop | `card.card_from_seeds(layer, question, content)`（＝`parse_seeds`＋`engine.resolve`） |
| (b) | `regnal_card_20261019/a4/responses.jsonl` | `a4_staging.py` 的輸出，每題一行 `{item, elapsed_s, error, answer, aux_card, sources, build_id, route}`；`aux_card.seeds` 是 r3 backend（b20261019_18aa84ad、層 932d2242、gemma 種子）把種子呼叫輸出 `parse_seeds` **之後**的結果，寫成「國別｜王名」字串（1–2 個，含沒 resolve 到的）；**沒有原始輸出**，也沒有 `seed_source` 欄 | 拆成 (國別碼, 王名) → `card.card_from_parsed(layer, question, pairs)` |
| (c) | `regnal_card_20261019/a4_r3b/responses.jsonl` | 同 (b)；32/32 有 aux_card | 同 (b) |
| dev | `kg_cards_20261018/A/gen_seed.jsonl` | 同 (a)，30 行，done_reason 全為 stop | 同 (a) |

- 截斷的種子呼叫（done_reason length）當作沒有種子（實驗 A `run_a.seed_texts` 的規則）；這四份檔案都是 0 題。
- (b) 的 QI1s2a1 沒有 aux_card（error 也是 null：那次的 backend 沒做出卡），原始輸出沒記，**無法重放**，當作沒有種子 → 參考臂該組無卡。
- (b)(c) 的 32 題，staging 檢索到的來源 id 與 G-auto 的 context 相同（32/32；內容沒有比對）。這裡只借它們的種子，prompt 的 context 一律用 G-auto 的（§4）。

## 3. 卡片建構（CPU，0 Ollama）

全部走本 checkout 的 backend 程式，不重寫 engine：`layer.parse_layer`＋`layer.with_lexicon`、`trigger.trigger`、`seeds.rule_seeds`、`card.card_from_rule`／`card_from_parsed`／`card_from_seeds`、`engine.cards`（S4 守門用預設＝開）。

1. **觸發**：`trigger.trigger(question, layer.names, layer.blockers)`（含擋字）。不觸發的題兩臂都無卡（backend 也不做卡）。確認集 32 題全收；dev 只收觸發的題（題數由程式算並記錄）。
2. **規則臂**：每題 `rule_seeds` → `card_from_rule`，3 個 rep 同一張卡。規則棄權的題用 gemma 備援＝**該 rep 的參考臂卡**（同一張，見下）；`rule_seeds` 有種子但 engine 寫不出推導行，就無卡（backend 這時不退回 gemma）。
3. **gemma 參考臂**：rep r 用第 r 組記錄的種子（確認集 rep 1/2/3 ＝ (a)/(b)/(c)；dev 三個 rep 都是 dev 組）在 `--layer` 上重放成卡。
4. **無卡**的 slot，prompt 用 `cards_common.build_user(context, question, None)`（實驗 A 的 B0 組法，仍要求「答案：」行），**不**套實驗 A 給 G 臂棄權用的 T-rows 替代——那不是 backend 的行為。
5. 每個 slot（題、臂、rep）記：題號、臂、種子來源（`rule`／`gemma:a|b|c|dev`）、規則種子 ids 與棄權理由、卡的 kings（層節點 id）與 seeds（「國別｜王名」）、卡片文字 sha256、字數、推導行數、被守門擋掉 born 行的種子（`guard_blocked`）、cap 截掉的列數（`rows_dropped`）、層 sha、lexicon sha、backend 七檔合併 sha。**卡片文字只寫進 store 的 cards.json**，jobs 只帶 sha。

## 4. 生成 jobs

- prompt 照 G-auto：`cards_common.SYSTEM_PROMPT`＋`cards_common.build_user(context, question, 卡片文字)`；context＝該題 items.json 的 `sources` 經 `cards_common.build_context`（＝G-auto 用的那份）。store 測試實測：在實驗 A 的層（932d2242）、守門關時，參考臂 (a) 組的 system／user prompt 與 A_confirm 記錄的 G-auto rep 1 **逐字相同（32/32）**。
- 次數：確認集規則臂每題 3 次、參考臂三組卡各 1 次＝32×3＋32×3＝**192**；dev 觸發題兩臂各 3 次＝觸發題數×6（候選層上 27 題＝**162**）。
- 同場配對：順序 rep → 集（確認集、dev）→ 題 → 臂，同一題兩臂相鄰、先後隨題序交替，不先跑完一臂。job id `RS|集|題號|臂|rep`。
- 跑前：`/api/ps`（模型沒載入就 `/api/tags`）核對 digest＝§1 的值，不符或查不到就拒跑；跑完再查一次，全部記在 run_meta.json 的 `digest_checks`。digest 狀態（`rs_run.digest_state`）：ok；mismatch（有一次查到別的 digest）；unknown（最後的跑後檢查 Ollama 沒回）；unfinished（上次開始後還沒做跑後檢查：中斷、連續錯誤停下）。
- 呼叫：`cards_common.chat`（照 `cards_common.run_jobs` 的 fork：chat 由呼叫端給、沒有重試輪）。Ollama 例外或回應讀不出來（URL／連線／HTTP 錯誤，含 `http.client` 的 IncompleteRead、BadStatusLine，與 JSON 解析錯誤）寫一行 error，**最終結果、不再跑**；連續 3 個錯誤就停。
- 續跑：已有 answer 或 error 行的 job 略過。同一個輸出目錄只能對同一份 jobs、同一種跑法：run_meta.json 的 jobs_sha256、options、模型、pins（層、lexicon、backend、harness 檔的 sha）不符就拒跑；dry run 的目錄不接正式跑，正式跑的目錄也不接 dry run；有 gen.jsonl 沒 run_meta 也拒跑。unfinished、unknown 的跑在**原目錄**續跑（unknown 續跑時 0 次呼叫、重查 digest）。
- 正式跑只開一次：同一份 jobs 或同一個層，在 store `reports/regnal_seed_20261019/`（任何深度）或新目錄的上一層已有正式跑（不論完成與否），新目錄就拒跑；唯一例外是 §6 的 `--rerun-of`。命令列的 `--out` 一律要在 `reports/regnal_seed_20261019/` 下（`repro` 可寫在該目錄本身），repo 裡一律不寫。
- 每次正式跑把 harness 的 git HEAD、是否有未 commit 修改、各檔 sha256 記進 run_meta.json，`score` 也記進 verdict.json（`harness_same_as_run`）；命令列的 `score` 在 harness 有未 commit 修改時拒跑。
- 預估 Ollama 時間（**推估**）：A_confirm 的 run_meta_arms.json 477 次 3452 秒＝7.24 秒／次，A 的 270 次 1558 秒＝5.77 秒／次；192×7.24＋162×5.77 ≈ 2324 秒 ≈ **39 分鐘**。這是全部臂的牆鐘平均（T-canon、B0 的 prompt 較長、較慢），偏高；只算帶卡的 G-auto／G-ref 每次呼叫的 elapsed_s（確認集 5.92、dev 5.21 秒，不含呼叫間空檔）是下界 ≈ 1980 秒 ≈ **33 分鐘**（也是推估）。

## 5. 計分

- **確認集**：實驗 A confirm 的 `score_c.score_items`（陷阱規則 chain，不改），規則臂當它的 G-auto、參考臂當 G-ref 餵進去（各 3 rep；`arms_meta` 兩臂都標 fired，不做替代）。題值＝該臂 3 次的平均；單位值 v_u＝`analyze_c.unit_values`（單位內各題差的不加權平均，單位照 items.json 的 `unit`，14 個）；Δ̄＝14 個 v_u 的平均（v_u＝0 的單位也算）。
- **dev**：`keys_a.item_ctx`＋`score_a.score_record`（stage-0 規則）；題值＝3 次平均；Δ̄＝觸發題各題差的平均。
- 截斷的呼叫照 `score_a` 記 0 分（格式失敗）。
- **計分器接線（實測）**：`run_rs.py repro` 在 store 既有記錄上重算——A_confirm 32 題用 `score_c.score_items`、A 的 30 題用 `score_a.arm_rep_scores`，G-auto 每次呼叫的計分紀錄與各臂平均都和 scores.json **完全相同**（G-auto 題平均：確認集 0.802、dev 0.767）。結果在 store `reports/regnal_seed_20261019/repro.json`。

## 6. 門檻（點估計，寫死）

| 規則 | 條件 |
|---|---|
| R1 | 確認集單位層 Δ̄＝規則臂平均－gemma 參考臂平均 **≥ −0.05**（規則臂每題 3 次平均；參考臂每題三組卡各 1 次的平均） |
| R2 | dev 觸發題題層 Δ̄ **≥ −0.05**（兩臂各 3 次平均） |
| R3 | 截斷 0、錯誤 0。截斷＝done_reason 為 length，或輸出達 num_predict（eval_count ≥ 10000），或 prompt＋輸出達 num_ctx；錯誤＝HTTP／解析錯誤（error 行） |

- 邊界 −0.05 算過（浮點容差 1e-9）。三條都過才算過。
- 判定的先後：digest mismatch →「作廢」；unknown →「未判」，原目錄續跑補查 digest；已有錯誤或截斷 → R3 已確定不過（就算還有 job 沒跑，也判「未過」，R1／R2 不判）；有 job 沒跑（沒有 answer 也沒有 error 行）或還沒做跑後檢查 →「未完成」，原目錄續跑後再判，不算過也不算不過；其餘照 R1、R2、R3。
- **重跑**：最多 1 次，而且只在 digest 不符（mismatch）時（跑前不符直接拒跑；跑後不符→判「作廢」，可在新目錄 `--rerun-of` 重跑同一份 jobs 一次，舊目錄在新跑通過跑前 digest 檢查後才記 `rerun_by`）；其他情況（中斷、錯誤、截斷、digest 查不到、分數不好）**不重跑**，也不能換目錄重開（§4）。
- dry run（假 chat）的判定一律是 `dry_run`，`pass` 為 false，措辭以「（假 chat，分數無意義）」開頭；流程上會得到的結果只放在 `dry_judgment`。
- **不過就停**，逐題看（verdict.json 有每題每臂的分數，只有題號與數字），**不改門檻**。
- 結果一律標「樣本內」；報告要寫：此門檻只抓得到約 ≥0.10–0.15 的破壞，不能宣稱非劣性；H1／H2 的措辭只屬於舊版本（932d2242＋gemma 種子＋無守門）。

## 7. 描述（不判）

兩臂卡片相同的題數（每組、三組都同）、規則卡平均字數、cap 截列數、守門擋 born 行的卡數、規則棄權題與理由、不觸發題、每臂每單位分數、每臂每題分數、格式失敗與陷阱次數。

## 8. A4′ 卡片逐字核對（`a4_card_check.py`）

讀 staging A4′ 的 responses.jsonl（`2026-10-19_regnal_card/a4_staging.py` 產出，格式同 §2 (b)，新版多 `aux_card.seed_source`），對確認集 32 題用本 checkout 的規則種子在 `--layer`＋`--lexicon` 上算 CPU 規則卡，檢查：0 錯誤；CPU 有卡的題必須有 aux_card、`aux_card.text` 與 CPU 卡逐字相同、`seed_source`＝"rule"；規則棄權的題 `seed_source` 應為 "gemma"（文字不比）；CPU 無卡的題不該有卡；`aux_card.layer_sha256`（若有）＝層 sha。輸出 JSON 到 `--out`（一律要在 store 的 `reports/regnal_seed_20261019/` 下），stdout 只印題號、sha 與計數，不印卡片文字。格式自測（實測）：拿舊版 a4_r3b 的記錄跑，32 題都報 seed_source 缺、層 sha 不同、31 題文字不同——預期中的不過，表示讀檔與比對有在動（`a4_check_selftest_r3b.json`）。

## 9. dry run（假 chat，候選層，實測）

候選層 `regnal_fix_20261019/candidate/regnal_layer.json` sha256 `252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11`（2026-10-19 19:24 的版本；這個檔在 dry run 前已改過一次，**不是正式值**）＋§1 的 lexicon，`run_rs.py dry-run` → store `reports/regnal_seed_20261019/dry_run/`（審查意見修正後在 commit 後的程式上重跑，jobs sha 與下表數字和修正前相同）。假 chat 照卡片第一行推導作答，分數無意義，只驗流程。

| 項目 | 值 |
|---|---|
| 確認集 | 32/32 觸發、規則 32/32 有卡、0 棄權 |
| dev | 30 題 27 觸發（不觸發：SUC_01、N_SUC_01、N_KIN_14）；規則棄權 1（N_SUC_05，a referring phrase → gemma 備援） |
| jobs | 354（確認集 規則 96／參考 96，dev 規則 81／參考 81）；jobs sha256 649ef70e… |
| 兩臂卡片相同的題數 | 確認集 (a) 6、(b) 4、(c) 3、三組都同 1（/32）；dev 8/27（含 N_SUC_05 的備援） |
| 規則卡 | 59 張，平均 478 字（規則種子卡 58 張平均 476 字）、平均 6.6 行推導；cap 截列 1 張共 3 列；守門擋 born 行 4 張 |
| gemma 參考卡 | 123 個 slot 中 122 張（無卡 1：(b) 的 QI1s2a1），平均 677 字、11.7 行；cap 截列 23 張共 61 列；守門擋 born 行 11 張 |
| 判定流程 | 14 單位、R1／R2／R3 都算得出、digest 兩次（假）都對；判定 `dry_run`（`dry_judgment` pass，假 chat 的數字無意義） |
| Ollama 時間（推估） | 牆鐘平均 2324 秒 ≈ 39 分；G 臂呼叫時間下界 1980 秒 ≈ 33 分（§4） |

## 10. 執行步驟（主 session）

1. 審本檔；把 §1 的層 sha 換成 r4 層的 sha256，去掉檔頭草稿標記，commit。
2. `python -B run_rs.py build --layer L --lexicon X --out <store>/reports/regnal_seed_20261019/<run>`（CPU，記數；只寫進還沒有 run 的目錄）。
3. `python -B run_rs.py dry-run --layer L --lexicon X`（假 chat，覆寫 dry_run/；dry_run/ 只放 dry run）。
4. Ollama 時窗內：`python -B run_rs.py run --layer L --lexicon X --out <步驟 2 的目錄>`（中斷或停下就對同一目錄再下一次，續跑）。
5. `python -B run_rs.py score --out <同一目錄>` → scores.json、verdict.json（harness 要已 commit）。
6. A4′ staging 跑完後：`python -B a4_card_check.py --responses R --layer L --lexicon X --out <store>/reports/regnal_seed_20261019/a4_check.json`。

## 11. 限制

- 樣本內：規則讀過這 62 題；門檻是點估計，沒有 CI、沒有檢定。
- 參考臂每組卡只生成 1 次：gemma 種子的變異和生成的變異混在一起；規則臂 3 次同一張卡，只有生成變異。
- (b) 的無卡題沒有原始種子可重放（記為無種子）；(b)(c) 只有解析後的種子，`parse_seeds` 之前的原文無法核對。
- 參考臂代表「舊的 gemma 種子在新層＋守門上」的卡，不是當時 staging 實際送出的卡（那是舊層、無守門）。
- dev 的計分規則（stage-0）和確認集的（chain）不同，兩個 Δ̄ 不可互比。
