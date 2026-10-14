# 單發圖譜檢索 GD（2026-10-14）

唯一規格是 `prereg.md`（登記 commit 9495073），文中 § 都指它。原始輸出寫在 store `reports/graph_gd_20261014/`（下稱 G；N＝G/new82），摘要、驗收結果與報告寫在本目錄。一律讀 store，不讀 /tmp。指令都在本目錄下以 `../../.venv/bin/python -B` 執行；錯誤一律單行、退出碼 2。

## 檔案
| 檔 | 用途 |
|---|---|
| `gd_common.py`（`_gd_store.py`、`_gd_sets.py`、`_gd_pool.py`、`_gd_gtv2.py`） | 層、題集（含 GT v2）與封存檔的釘值；§4 gold；§3 清單形狀；確認集守門；§10 指紋與 meta |
| `arms.py`（`_gd_lex.py`）、`accept_a.py` | §3 dense、R20、bip 圖、PPR、六臂 extra → lists.json（`--set new82\|old31\|ho\|gtv2`）；驗收 A |
| `encode_stdin.py`、`rerank_stdin.py`、`rerank_w_stdin.py` | 容器內 stdin 腳本，不寫檔；由 score.py 在前面加上 PAYLOAD_B64 |
| `score.py`（`_score_io.py`、`_score_w.py`） | encode、rerank（`--arms C,GD` 只打這些臂的池）、rerank-w（§3 W）、refpairs；可續跑，每次結尾重打 §10 的 32 個參考對 |
| `evaluate.py`（`_eval_*.py`） | report（`--scores-w` 加 W 敏感度；E2 必帶）、v1、units、build-ref、accept-b |
| `e3_raw.py`（`_e3_build.py`、`_e3_run.py`、`_e3_gates.py`） | §8 E3：build（top-k → raw_responses.json）、run（quick_retrieval_eval，輸出移到 e3/）、gates |
| `v1_power.py` | 附錄 A：單位層級 V1 操作特性與程序檢定力（移植 R/review_stats/s2_power.py，先重現封存值） |
| `ho_tools/` | §7 HO 盲出題：bt 工具、headless 出題與稽核、機械稽核、Kay 抽查、凍結；見 `ho_tools/README.md` |
| `accept/`、`new82_report.json` | 驗收 A、B 的結果；NEW82 探索性報告 |

測試：在 `evaluation/` 下執行 `.venv/bin/python -B -m pytest tests/test_graph_gd_*.py -q -p no:cacheprovider`。只用合成資料與 NEW82；store 未掛載時相關測試 skip；確認集守門在測試裏也不打開。

## 守門與來源（§2、§10）
- `gd.assert_set_allowed`：OLD31、GT v2 要附錄 A 有內容，HO 另要附錄 B；`accept/accept_a.json`、`accept_b.json` 都要 passed、pinned，且 lists_sha256 相同。`evaluate.py units` 與 `v1_power.py` 只讀題目與 gold，不受守門；units 拒收 gtv2（沒有跳）。
- lists 綁題集、層、向量與自身內容雜湊。scores 的每個 meta 行綁 reranker 指紋、執行設定（CPU、batch 16、12 threads）、同一份 lists 與同一組腳本，分數行之後要有通過的 refcheck。W 檔另綁整段分數的內容雜湊，單窗段必須等於整段分數。`--allow-unpinned` 只給 NEW82 鏈路核對與 e3/ 以外的合成核對。
- 分數檔缺某臂池的分數（例如只打 `--arms C,GD`）時，report 與 accept-b 都以「題號 / 臂: …」的單行錯誤停止。

## 三個附加部分
- **W（§3 逐窗重排，敏感度）**：只算 C、GD 的池。多窗段取逐窗最大分，windows()／score() 與 WF/exp/rr_probe_in_container.py 的 AST 相同；單窗段沿用同一份 lists 的整段分數。rerank 打完後跑 `score.py rerank-w`，再在 `evaluate.py report` 加 `--scores-w`。報 GD_W−C_W 的單位 W:L、CI，以及 C_W、GD_W 的 top-k 切點最小間隔與 <1e−5 的邊界題（§10；W 混用兩次執行的分數），不改判定。E2（`--set old31+ho`）缺 `--scores-w` 就拒跑（§5 必報）。耗時：NEW82 實測 0.348 秒/窗、每題約 49 窗；E2 兩集合計約 45 分鐘（OLD31 約 9、HO 約 34 分鐘）。
- **E3（§8 傷害檢查；附錄 A 之後，可與 V1、HO 並行）**：
  1. `score.py encode --set gtv2 --out G/gtv2/encode.jsonl`
  2. `arms.py --set gtv2 --vectors G/gtv2/encode.jsonl --out G/gtv2/lists.json`
  3. `score.py rerank --lists G/gtv2/lists.json --arms C,GD --out G/gtv2/scores.jsonl`（約 2.2 小時；Kay 2026-10-14 裁決只打 C∪GD，見附錄 A 待辦 6）
  4. 對 A∈{C,GD}、K∈{5,10}：`e3_raw.py build --lists G/gtv2/lists.json --scores G/gtv2/scores.jsonl --k K --arm A --out G/gtv2/raw_A_kK`，再 `e3_raw.py run --raw G/gtv2/raw_A_kK --k K --arm A`（輸出到 e3/A_kK/）。run 之間以 evaluation/ 目錄的 flock 互斥，可同時下指令，會依序執行；自己的輸出一律先移出 results_quick，失敗或有他人新檔時留在 `e3/A_kK/failed/`，不算數，results_quick 不留檔。
  5. `e3_raw.py gates --c5 e3/C_k5 --gd5 e3/GD_k5 --c10 e3/C_k10 --gd10 e3/GD_k10`：先核對本行程的 metric_version＝4d0826bb8d14（閘門 3 用本行程的 ruler）；退出碼 0 過、1 不過、2 錯誤；k=10 只報告
- **ho_tools（§7；附錄 A 之後且 V1 未停損）**：`ho_tools/run_gen.py loop --root G/ho --rounds N` → `mech_check.py questions`、`transcripts` → `sample_kay.py draw`、Kay 審題、`apply` → `freeze.py --root G/ho` → 附錄 B。正式根目錄要過守門，且 `v1_old31.json`（`evaluate.py v1` 的預設 `--out`）為 `stop: false`。試跑一律放在 `G/ho/pilot/`，freeze 拒收。每次提交都跑 transcript 規則，盲化違規的題當場刪除、由後續題遞補。

## NEW82（驗收）
1. `score.py encode --set new82 --ids <sorted(id) 前 5> --out N/encode_recheck5.jsonl --ref PN/encode_out.jsonl`（max|Δ|=0）
2. `accept_a.py`：重寫 N/lists*.json 與 `accept/accept_a.json`
3. `score.py rerank --lists N/lists.json --out N/scores.jsonl`（4,936 對）
4. `score.py rerank-w --lists N/lists.json --scores N/scores.jsonl --out N/scores_w.jsonl`
5. `evaluate.py accept-b --lists N/lists.json --scores N/scores.jsonl --ref N/accept_b_reference.json`
6. `evaluate.py report --set new82 --lists N/lists.json --scores N/scores.jsonl --scores-w N/scores_w.jsonl --out new82_report.json`（探索性，不得作證據）

修正輪後重跑（2026-10-14）：A 通過（32/32），lists_sha256 `25b196a2…` 不變；B 820/820，漂移 1.76e−6，邊界題 0；H1 11:0 p=1/1024、H2 8:2 p=69/256、H3 p=13/512（Holm 未過），與先前報告相同。W（N/scores_w.jsonl，4,032 窗，refcheck max|Δ|=0）：GD_W−C_W @10 單位 12:1、Δ̄ 0.059（CI 0.017～0.105），@5 8:2（CI −0.012～0.069）；切點最小間隔 C_W@10 1.06e−5、GD_W@10 5.08e−5、C_W@5 1.95e−4、GD_W@5 3.76e−5，邊界題 0。

## 確認集（附錄 A 之後）
- V1：`score.py encode --set old31 --out G/old31/encode.jsonl` → `arms.py --set old31 …` → `score.py rerank --lists G/old31/lists.json --out G/old31/scores.jsonl` → `evaluate.py v1 --lists … --scores …`（只印停損判定與單位 W:L；用預設 `--out`，HO 執行器讀它）。
- E2（附錄 B 之後）：HO 照同樣三步；兩集各跑 `score.py rerank-w`；`evaluate.py report --set old31+ho --lists L_old31 L_ho --scores S_old31 S_ho --scores-w W_old31 W_ho --out e2_report.json`。

## 附錄 A 待辦（依序；第 1 步之後不再改腳本）
1. commit 全部腳本、測試與本目錄結果，確認工作樹乾淨，記下 `git rev-parse HEAD`。
2. 核對 accept_a、accept_b 與報告 meta 記錄的 sha 等於 commit 內的檔（2026-10-14 修正輪後已重跑，之後沒改腳本就相同）；若不同，在該 commit 上重跑 NEW82 的第 2、5、6 步，再 commit 這三個檔。
3. `evaluate.py units --set old31 --out units_old31.json`：OLD31 群聚表（須 20 單位、最大 9 題）、密度層，以及與 NEW82 共用 gold 的題。
4. `v1_power.py`：寫 `v1_power.json`，內容是單位層級 V1 操作特性與程序檢定力。它會先重現 s2_power.json 與 recheck.json，不符就以退出碼 2 結束。寫附錄 A 前先審它的方法選擇（|d| 取 s1_strata.json 的四位小數、單位大小排序、HO 視為 120 個單題群、r_old 換算、單位層級 OC 用模擬）。
5. sha：`git rev-parse HEAD`；`sha256sum prereg.md ho_tools/gen_prompt.md ho_tools/audit_prompt.md *.py ho_tools/*.py ho_tools/page_template.html`。兩份 prompt 已在修正輪改過（列出所有已用核心），以當時的 sha 為準。
6. Kay 2026-10-14 裁決（寫進附錄 A）：(a) HO agent 的 context 會被注入帳號 email（OAuth 無法關閉），接受並揭露，transcript 看不到注入的 context；(b) Claude Code CLI 釘 2.1.299，`_ho_claude.launch` 版本不符就拒跑（`--thinking-display` 是 --help 未列的選項，換版前要先用 ho/probe 的方法重測）；(c) `/srv` 必須為空，`check_cwd` 已擋；(d) E3 用 `--arms C,GD`（約 2.2 小時；批次組成與 §3「所有臂池的聯集」不同，實測 |Δ| 最大 1.07e−6，封存跨 run 漂移 9.24e−7，驗收 B 漂移 1.76e−6，§10 門檻 1e−5）。
7. 列出偏離 prereg 的事項（含修正輪新增：transcript 只含 API 端 thinking 摘要；禁用字在 agent 自己寫的文字只記 warn、在 system prompt 才是 error；盲化違規在提交時就刪題遞補；agent 看得到所有已用核心與題數、core 的別名異寫由稽核判 major、mech 只 warn；bt_guard 拒絕引號外的萬用字元與 ~，bt 不回顯非經節鍵的參數；E3 run 互斥、失敗輸出留在 failed/；W 報切點間隔；附錄 B 另列 overlap_avoided、transcript_breaches）。
8. 在 prereg.md 檔尾追加附錄 A，然後 commit。
