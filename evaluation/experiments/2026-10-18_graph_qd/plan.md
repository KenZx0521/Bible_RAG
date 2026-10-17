# 圖譜最後一夜（QD+G）與多錨 QD：事前登記（2026-10-18）

依據：記憶 project_kg_strategy_redesign_2026-10-18（5 提案×2 審查×3 評審）。本檔 commit 後才跑；看結果後不改判定。程式只修基礎設施錯誤，修了就記在文末「執行紀錄」。

## 0. Kay 2026-10-18 裁決（照建議）

1. 授權一晚、0 USD 的圖譜量測。
2. GD 結案條款（`2026-10-14_graph_gd/prereg.md` §6、§10）只禁「單發圖譜變體」。以已選 context 為種子、經查詢端的臂（QD+G、IT-GD）不在禁區。本次 G 規則沒過，就以實測結案**現況圖譜層**（L0 名稱、L1 事件登錄表、kin 表層三元組）上的所有檢索變體。
3. 歸因：LLM 子查詢本身不算圖譜；圖譜臂必須同時贏 DEEP@6 與非圖譜雙胞胎 QD+N；PPR 或兩跳以上才算圖譜操作，一跳查表只描述。

## 1. 步驟 1：題集與基底

- NEW82（82 題、223 跳、缺跳 102／63 題，GD `gd.load_new82()` 釘值）。這是看過的開發集：結果一律是**探索性**，過關也不是證據。NEW82 的 gold 經節多含名稱，對名稱法有利。
- C5＝GD 封存 `graph_gd_20261014/new82/{lists.json, scores.jsonl}` 的 C 池依 (−score, pid) 前 5（同 new82_ans `it_host.c_top`）。
- 每臂在 C5 後**附加 1 段**（不在 C5 內），k=6 對齊。

## 2. 步驟 1：臂

共同的 decomposer：iterq `decomposer_prompt.txt`（sha256 `170dc208…`），容器內 prod LLM `gemma4:e4b-it-q8_0`（Ollama digest `9dcc35808b42…`），T=0、max_tokens 10000，解析失敗重試 1 次、仍失敗退回原題（iterq `decompose` 原碼，AST 抽取）。context＝C5 經 `build_context_blocks`。

共同的取段：子查詢 s → 容器 encode → 主機 D(s)（GD §3：float64 精確 cosine、段取記錄最大值、stable 排序）→ 池＝D(s) 中不在 C5 的前 20 段（同 IT-D）→ prod reranker 以 s 打分（cpu、batch 16、12 threads）→ 取 (−score, pid) 第一段。每個 QD 類臂跑 3 次（r1–r3，今晚全部重跑，不沿用 10-14 的 dec_t1）。

| 臂 | 定義 |
|---|---|
| DEEP@6 | D(題目)[0:50] 中不在 C5 的段，reranker 以題目打分取第一（今晚全部重打）。不用 LLM |
| QD | 原 prompt |
| QD+G（主圖譜臂） | prompt 在 `{context}` 與 `---` 之間插一行「可能相關名稱：n1、n2、…」。名稱取自**圖譜排名**：在 L0 名稱–段落二部圖（GD `arms.load_context().graph`，16,616 邊）跑 PPR，種子＝C5 段節點、權重 1/名次（1..5），α 0.5、40 次，依 GD §3 PPR 順序排段（GD `arms.ppr`／`ppr_order` 原碼）；再套下方共用名稱公式。C5→名稱→段，是兩跳以上的圖譜操作 |
| QD+N（非圖譜雙胞胎） | 同模板。名稱取自**題目的 dense 排名** D30（GD lists），C5 移到最前（C5＋D30∖C5），套同一條名稱公式。一跳查表 |
| QD+ORACLE（診斷） | questions_v5 `bridge` 欄經 GD 名稱連結器，**只保留 G／N 能輸出的名稱**（同一套合格規則），依連結順序前 5。由讀 gold 的獨立程序產生。`bridge` 常含答案，只當診斷 |
| IT-D、IT-GD | new82_ans 原設計續跑（還原其 plan.md，sha256 `d79099740d…`），C5＋2 步＝@7 |

- **共用名稱公式**：排名一律寫成 C5＋(排名∖C5)（C5 在 PPR 排名本來就是前 5），所以兩臂非 C5 段的權重都是 1/6…1/30。排名的前 30 段中不在 C5 的段 p，名稱 n 的分數＝ln(2773/df(n))·Σ_p 1/(名次+1)（名次 0 起算、df＝二部圖度數），依 (−round(分數,12), norm_key) 取合格名稱前 5。G 與 N 只差排名來源（C5 種子的 PPR vs 題目的 dense）。
- **設計更正（看過名稱輸出、尚未有任何結果時）**：原規格「依 PPR 名稱節點分數取前 5」試算後幾乎都挑到以法蓮、撒母耳、約旦河等中高頻名稱（PPR 的度數偏差），而 N 有 IDF，兩臂的差會變成「有沒有 IDF」而非「圖譜 vs dense」，所以改成上面的共用公式。
- **合格名稱**（G、N 共用）：在 kg0、長度 ≥2、不是 hub（kg0 `body_occurrences`>300，14 個）、不在題目名稱（GD 連結器）、不在 C5 任何段的 body 名稱。也就是只提供 context 裏還沒有的名字。
- 名稱為空的臂：prompt 與 QD 相同，直接沿用同題同次 QD 的拆解（不另拆，避免拆解器雜訊）。G、N 82 題都有 5 個名稱；ORACLE 只有部分題有合格名稱。
- **看名稱的範圍**：只看過前 6 題（N_BRL_01–06）的 G／N 名稱清單；沒有算任何 f(q)，沒有對照 bridge 或 gold。
- **開跑前審查更正（未看任何結果）**：(1) N 原本直接用 D30 名次，C5 散在 D30 裏使 N 的權重從 1/2 起算，與 G 的 1/6 起算形狀不同，改成 C5 在前；(2) ORACLE 原本保留 hub 與 C5 名稱，178 個名稱中 136 個本來就在 context 裏，和 G 測的不是同一件事，改套同一套合格規則；(3) G 規則加 G3（見 §4）。

## 3. 步驟 1：指標

f(q)@6＝GD prereg §4 的全跳覆蓋率；QD 類臂每題取 3 次平均（Fraction）。用 `_eval_report.compare`：40 個群聚單位（§5 union-find）的單位 W:L、Δ̄、bootstrap 95% CI（10000 次、seed 20261014）、精確 sign-flip p（只描述）。另報缺跳命中 /102（相對 D5≈）、題層 W:L。

## 4. 步驟 1：判定（寫死）

- **G（圖譜主規則）**：QD+G−QD+N（G1）與 QD+G−DEEP@6（G2）**兩項都**單位 W≥2L、W−L≥4、Δ̄>0，而且 QD+G−QD（G3）Δ̄>0、W>L → 記「開發集探索性陽性」，盲集確認另議（要 Kay）。否則依 §0-2 結案，措辭：「依事先規則停止，不構成無效證據」，附上界與下表。G3 是開跑前審查加的：G2 含 LLM 子查詢本身的效果，QD 贏 DEEP 時 G2 幾乎必過。
- **O（歸因診斷）**：QD+ORACLE−QD 沒過與 G 相同的單項門檻（W≥2L、W−L≥4、Δ̄>0）→ 寫「依事先規則未過，不構成無效證據：合格的 gold 橋接名寫進查詢也沒過門檻」；ORACLE 過而 G 未過 → 寫「現況 KG 挑不出名字」。ORACLE 有名稱的題少，檢定力低。
- **I（E4／IT-GD）**：IT-GD−IT-D @7 單位 Δ̄≤0 或 W≤L → 以實測結案 E4 與 IT-GD。這是本檔新訂的檢索層規則，不是 new82_ans plan 原本的答案層主比較。eval_iter 指標自檢沒過，或 IT 的拆解有 Ollama 例外造成的退回、退回超過 5%，I 記作廢。
- **M（多跳 QD，非圖譜）**：QD−DEEP@6 方向為正、單尾 sign-flip p<0.10（＝`_eval_stats.sign_flip` 雙尾 p<0.20）且單位 W≥2L、W>0 → 列為盲集候選。
- **K（基礎設施）**：任一臂 fallback 或空子查詢超過 5%，或 refpairs 漂移 >1e−5，該臂作廢、只准重跑一次；牽涉作廢臂的判定記「作廢」，不寫過或未過。Ollama 例外（逾時、連線）造成的退回不算結果，自動重做（最多 3 輪）。refpairs：開跑前（before）漂移就停；步驟 1 後（mid）與步驟 2 後（after）漂移記入 K。

單項門檻「W≥2L 且 W−L≥4」的通過率（D＝不一致單位數；q＝單位勝率）：

| D | 4 | 6 | 8 | 10 | 12 | 16 | 20 |
|---|---|---|---|---|---|---|---|
| q=0.5（虛無） | .06 | .11 | .15 | .17 | .19 | .11 | .06 |
| q=0.8 | .41 | .66 | .80 | .88 | .93 | .92 | .91 |

QD 明顯贏 DEEP 時 G2 幾乎必過，G 的偽陽性率約等於 G1 單項。V1 前例（4/20 不一致）顯示 D 可能很小，此時檢定力低，所以沒過只能寫「依事先規則停止」。

## 5. 步驟 2：多錨 QD（GT v2，非圖譜）

- 題：GT v2（sha `7280bb42…`）`len(refs)>1` 的 204 題（adj4.py 定義）。
- C5：eval3c nokg `raw_responses.json`（sha `781167d7…`）每題 `sources[:5]`、`contexts[:5]` 原樣；P(C5)＝對到的段（ps 本身、ck→母段、vs／vr→verse_index 的段）。2 題只有 1 段，照算。C5 含 book_anchor（eval3c 當時 prod）。
- 題目向量：容器 encode；dense 用主機 GD §3（和 prod Qdrant 不同）。
- DEEP@6：D(題目)[0:50]∖P(C5)，reranker(題目) 取第一。QD@6：decomposer 讀題目＋`contexts[:5]`，3 次；D(s)∖P(C5) 前 20，reranker(s) 取第一。附加段用 `_e3_build.passage_source`。
- 指標：`quick_retrieval_eval --from-raw --gt v2 --top-k 6 --metric-k 6` 的 `anchor_coverage_at_k`（metric_version `4d0826bb8d14`），QD 取 3 次平均。
- **判定**：QD@6−DEEP@6 逐題配對差的點估計 ≥+0.03 且 bootstrap 95% CI 下界 >0（`src.ab_stats`，10000、seed 20261014）→ 才談步驟 3（答案層非劣性，要 Kay）；否則多錨 QD 線停止。描述：DEEP−C5、QD−C5（k 不對齊）、R1／R2 明寫引用子集、vrec@6。
- 揭露：多錨子群由 eval3c 基線分析選出；QD 從沒在 GT v2 上跑過；prompt 凍結。單錨 296 題傷害檢查不在今晚。

## 6. 執行

- 輸出：store `reports/graph_qd_20261018/`。獨佔 Ollama 與 backend CPU（無 prod 查詢、無其他評估）。每段開始前記 `/api/ps`，核對映像 `c79266…`、build `b20261008_e05d3e55`、Ollama digest。GD `score.py refpairs` 跑三次：開跑前、步驟 1 後、步驟 2 後。
- 預估：步驟 1（含 IT）約 4–6 小時，步驟 2 約 3–4 小時；約 01:30 開跑，08:00–10:30 結束。06:00–07:00 的自動更新可能與步驟 2 的拆解重疊（只有 NVIDIA 使用者層套件，上游版本相同），記入執行紀錄。早上結束前不要用 prod。
- 順序：IT 續跑 → 步驟 1 全部 decompose → encode → rerank → 凍結 lanes → 評估（另一程序讀 gold）→ 步驟 2。
- G／N 名稱只來自題目文字、GD lists／scores（C5、D30）、store 層與 kg0。ORACLE 名稱檔由 bridge 衍生、在獨立程序產生，只進 QD+ORACLE。評估另一程序讀 gold。
- 拆解順序固定（次 → 題 → 臂 QD、QD+G、QD+N、QD+ORACLE）。Ollama 會沿用前一請求的前綴 KV cache，T=0 也不保證逐字重現，所以 3 次可能多半相同、臂之間有數值路徑差異（無方向）；評估報各臂 3 次全同的題數。
- IT 續跑混兩天的資料：t1 的拆解與 encode 是 10-14（當時和 p5_query 共用 Ollama、backend 非獨佔）；rr_t1 有 48 題是 10-14、34 題今晚；t2 與 check_b 今晚。reranker 分數只取決於執行緒設定，不受負載影響。s_1 兩臂共用，IT-GD−IT-D 沒有方向性偏差，但 IT 的絕對數字不能和今晚的 QD 臂直接對照。

## 執行紀錄

（跑完後追加。）
