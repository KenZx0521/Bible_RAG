# plan_v1 → plan_final 審查意見處理（2026-10-15）

編號規則：S＝stats，V＝validity，E＝engineering。「§」指 plan_final.md 的章節。

本次新增一份模擬，用來支撐 §7 的操作特性表：
- `scratchpad/ba/final/oc_sim.py`、`oc_out.json`；
- 比較 R=9 用的 `oc_sim_r9.py`、`oc_r9_out.json`。

模擬設定：
- 雜訊池：eval3c 39 題 full−nokg 的逐題差，coverage 與 strict 聯合抽樣；
- 兩種雜訊模型：E（可交換）與 Q（題內）；
- 3000 次模擬；
- t-CI 和 sign-flip 的做法與正式分析相同。

## Major

| # | 意見 | 處理 | 改了什麼（理由） |
|---|---|---|---|
| S1／V1 | G1 未校準，「不過」直接判成傷害 | 採納 | 不劣界改為 −0.04：sim4 校準，虛無下 n=20 通過率 0.90–0.93、n=39 ≥ 0.99。另加絕對門檻：500 題換算 strict ≥ 0.97。「傷害」只用在 Holm 調整後顯著為負；CI 太寬就判「無法判定」。§7 補上整套 `verdict()` 的操作特性表，在 Δ=0、+0.03、−0.05、−0.08 以及 Δstrict=−0.04 下，列出 P(可改)、P(傷害)、P(無法判定)。§5、§7、§8 |
| S2 | nopin 檢定力不足；「5 次生成是唯一手段」與「之後加跑算新登記」有 optional stopping 的問題 | 採納（改成全臂加次數） | coverage 在所有臂、整個 U 上都生成 6 次；strict 仍只判前 3 次；多出的次數只判 coverage（新增 `ba_cov.py`）。之所以不只在 D_nopin 加：off:nopin 的增量檢定和自然進榜那一層也需要檢定力。R=6 下 n=20 的 P(可改\|Δ=0) 為 0.75–0.93，R=3 只有 0.52–0.81。R=9 只再多 0.02–0.08，卻要多 1.2–1.7 小時，因為 n≈20 時卡住的是 strict（R=3）那一關。原兩句已刪，改寫成「無法判定就維持現行；之後重測視為新的一次登記，用新的生成，不和本次資料合併」。不採兩階段設計，因為只跑一次更精簡。§2、§7、§8 |
| S3／V2 | off 的遮蔽效應；決策表第 2 列自相矛盾；0.02 點估計差等於讓雜訊決定 | 採納（V2 改用單一增量檢定實作） | 新增 off:nopin 配對，在 U 上套用同一個 `verdict()`。採 off 的條件改為：off:ctrl 可改、off:nopin 可改，且 nopin 沒有判傷害。nopin 判傷害時，off 也不採。刪除點估計差 0.02 的規則，改成「兩者都可改時，off:nopin 的 cov 97.5% 上界 < 0 才改採 nopin」。也刪除「檢定力高所以偏好 off」這句理由。不採 V2 的 (b)(c) 分層檢定：off:nopin 在 U 上量到的正好就是 off 特有的機制（在 D_nopin 上兩臂都不釘，其餘題 nopin 等於 ctrl），拆成兩層只會讓每層的 n 減半。兩層的結果改成描述性報告，附 MDE。§3、§5、§8 |
| S4 | G2 用 percentile CI，Δvrec 稀疏，會產生假顯著 | 採納 | G2 改成：Holm 調整後的 sign-flip p < 0.05 且 Δ̄ < 0 才判傷害。percentile CI 只作描述，水準統一。gold_out 逐題列出。不設單題否決：答案層的 coverage 本來就在量這類損失；事後再加單題否決，等於引入事後規則。§5、§8 |
| V3／E2 | 生成時沒有驗證 context 就是檢索時算 ctx_sha 的那份 | 採納 | 新增 I7（停線）：generate 在呼叫 LLM 前，先從存下的完整 results 字典重算 ctx_sha，不符就 exit 3。gen.jsonl 記錄 ctx_sha，以及實際送出的 messages 的 sha（由 `get_llm_client` 的 proxy 取得）。export-ans 再驗一次。test_ba_io 測 JSON 來回轉換，以及「欄位改名後 sha 不符」。§6、§10 |
| E1 | 執行緒前提寫錯（prod 是 24，不是 12）；I1 要到最後才檢查 | 採納 (a)，並加早期關卡 | 不設定執行緒數，用 torch 預設的 24，與 prod 一致；§12 的上線比對也是同一前提。I1 另外報告共有 id 的 max\|Δscore\|。檢索拆成 A 批（eval3c 43 題＋換路由題＋40 題隨機非 C）與其餘；A 批跑完先做 `check --partial`（I0–I4），不過就停。§6、§9 |

## Minor

| # | 意見 | 處理 | 改了什麼（理由） |
|---|---|---|---|
| S5 | 小樣本時 percentile 偏寬鬆；MDE 用 t 分布、分析卻用 percentile，不一致 | 採納 | 決策一律用 t-CI，percentile 只描述。操作特性改用同一套模擬，並附 SD 0.12／0.146／0.19 的敏感度。界線處的型一錯誤 ≤ 0.011（名目 0.0125）。§7 |
| S6／V10／E8 | 判分依臂分塊，可能和臂混淆；judge 決定性未驗 | 採納 | 依 `judge_order.json` 按次數交錯（r1 的三臂、r2……，臂序依 seed 打亂），續跑時沿用同一順序。每個目錄開始前記錄 `/api/ps`。ctrl_r1 的 coverage 重判一次，作描述性的決定性檢查。§5、§9 |
| S7 | 沒有報拒答數 | 採納 | 用凍結的 eval3c `refusal_v2.py`（sha ea3060c6…）：`is_strict_refusal` 與 `is_refusal` 逐臂計次，並做符號檢定。只作描述，不改判定。§5 |
| S8 | 分層與具名個案沒聲明只作描述 | 採納 | §5 明寫：一律不改變 §8 的判定，子集結果都附 MDE |
| S9 | 「固定 seed 會改變生成分布」的理由不對 | 採納 | 理由改成：兩臂 context 不同，token 序列很快分岔，CRN 的相關性很低；Ollama 批次處理下 seed 也不保證能重現。§2 |
| V4 | I2 說成「傷害面硬驗證」太強 | 採納 | 改名為「實作與決定性檢查」。傷害面另外報告：gold_out 清單、C 與 eval3c 43 題的聯集、換路由題在另一條路由下是否也屬於 C、測不到的路由。§4、§5、§6、§13 |
| V5 | off 有連帶效果，會混淆機制解讀 | 採納 | D_off 逐題加上機制標記 (i)–(iv)，並記錄 max\|Δrr\|；只有換序的題另外分層。off−nopin 的解讀明寫包含這些連帶效果。§3、§4 |
| V6 | coverage 在這批題上約等於 gold 召回，量不到「讓書出現」 | 採納 | 新增描述指標：「點名的書出現在 top-k」的比例、含糊／拒答率、legacy_head 與擴充家族分層。Δcov 解讀為「gold 經文經過生成器之後的召回」。§5、§13 |
| V7 | nopin 會用 1 題的證據刪掉多書釘選 | 採納（比建議更進一步） | nopin 直接定義成「只取消單書釘選，多書缺席書釘選保留」。這樣測的臂就是上線的程式，不需要衍生臂。GBQ_096 只歸 off。I3 改為 D_nopin = P_s。§3、§4、§8 |
| V8／E14 | fallback 的事實陳述有誤；absent 的描述不準 | 採納 | 改寫為：R3、R4、R6 從未產生候選；fallback 有 1–2 題（VERSE_LOOKUP_097、GBQ_073）。absent 改寫為：約 15/20 題等於 nopin，其餘每書釘 1 段，本實驗推不出它的效果。§3、§8、§13 |
| V9／E7 | 替換的是模組全域變數，並行會互相汙染；順序沒寫 | 採納 | `arm()` 加不可重入的行程鎖，重入就 raise。題與臂都循序，順序固定為 ctrl→nopin→off，不用 asyncio.gather。nopin 開始前若沒有快照就停止。測試涵蓋巢狀與並行。§3、§10 |
| V10（其餘） | G2 水準不一致；None 處理沒規定；絕對 strict 門檻被拿掉 | 採納 | G2 改用 Holm 檢定，水準與其他檢定一致。有效次數規則：coverage 至少 4/6、strict 至少 2/3 次有效，否則該題剔除並列出。加回 500 題換算 strict ≥ 0.97。§5、§8 |
| V11 | I0 沒有核對程式身分 | 採納 | meta 行加上 18 個 backend 檔的 sha256，與 repo HEAD 比對；exp_meta 記錄映像 ID（須以 c79266296cb0 開頭）與 Ollama digest。§6 |
| V12 | 能推廣到 prod 的範圍有限 | 採納 | §13 寫明結論範圍、沒有 holdout、家族集中。執行緒問題已隨 E1 消除 |
| E3 | judge_ids 在生成前凍結，與 I6 剔除互相衝突 | 採納 | export-ans 一律寫出所有 (q, arm, rep)，失敗的答案保留錯誤字串，由 `validity.answer_failure` 標成 invalid。§6、§9 |
| E4 | intent 失敗會靜默退回 topic；一次暫時性的 strategy_errors 就讓整夜白跑 | 採納 | 包一層 `_llm_intent`（遇到例外或 `_extract_json` 回 None 就重試，最多 2 次），記錄 intent_ok。strategy_errors 由 driver 整組重跑三臂，最多 2 次；重試後仍失敗才停線。報告附重試次數。§6 |
| E5 | 續跑時 `>>` 半行會讓前後兩筆紀錄損毀 | 採納 | run_ba.sh 續跑前先截到最後一個換行。每行都帶 kind 欄位，check 遇到壞行就停。§9、§10 |
| E6 | exp_meta 寫在 commit 之前，對不上 | 採納 | 開跑時才寫 exp_meta，並斷言實驗檔與測試在 HEAD 無差異、無未追蹤檔；driver 的 meta 行記錄 /exp 各檔的 sha。§6、§9 |
| E9 | GBQ_050、013 沒有 smoke 預期值 | 採納 | 補上兩題的預期值：GBQ_050 取自 live k=20 重建的自然排序；GBQ_013 是 3 段章節 pin 加上 off 去掉 gen.15.1。§6 |
| E10 | 執行方式可能被權限擋 | 採納 | smoke 與 run_ba.sh 由 Kay 執行。步驟 0 的檢查（含 compose config）也由 Kay 做。§0、§9 |
| E11 | 一次性容器會繼承 healthcheck，被標成 unhealthy | 採納（改用 override 檔） | 加 `compose.ba.yml`，把 healthcheck 的 test 設成 `["NONE"]`；步驟 0 用 `compose config` 確認。不改用 `docker run`，以免手動重組 env 與網路設定。§9 |
| E12 | 依賴 staging 的 serving 列，可能被別人改動 | 採納 | 加 `-e RAG_ENV=prod`（唯讀解析 prod 的 serving 列），並保留 `RAG_BUILD_ID` 防呆。§9 |
| E13 | §12 打算完整重建映像（要連網），執行緒前提也不一致 | 採納 | 改用衍生映像 `FROM bible_rag-backend:r2` 加上 `COPY backend/`。執行緒兩邊都用預設 24；比對不一致時附 \|Δscore\|。§12 |
| E15 | 「覆蓋率 ≥80%」沒有量測工具 | 採納 | 刪掉數字門檻，改為「§8 每條判定路徑、I0–I7 每個失敗分支都有測試」。§10 |

## 未採納與保留的部分

| 項目 | 處理 | 理由 |
|---|---|---|
| S2 的兩階段設計 | 不採 | 改用一次跑 R=6，較精簡，也沒有合併資料的問題 |
| V2 的分層 (b)(c) 作為判定門檻 | 不採 | 已由 off:nopin 的增量檢定涵蓋，兩層改為描述 |
| S4 的單題否決規則 | 不採 | 理由見 S4 列 |
| u_code 建議的 noprior、absent 臂 | 維持不跑 | 理由見 §3 |
| 時間 | 從 6–8.5 小時增為 7–10 小時 | 生成從 294 次增為約 582 次，換取 n≈20 時的檢定力 |
