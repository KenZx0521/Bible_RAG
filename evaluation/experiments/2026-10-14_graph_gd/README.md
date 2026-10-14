# 單發圖譜檢索 GD（2026-10-14）

唯一規格是 `prereg.md`（登記 commit 9495073），文中 § 都指它。原始輸出寫在 store `reports/graph_gd_20261014/`（下稱 N＝其下 `new82/`），摘要、驗收結果與報告寫在本目錄。一律讀 store，不讀 /tmp。

## 檔案
| 檔 | 用途 |
|---|---|
| `gd_common.py`（含 `_gd_store.py`、`_gd_sets.py`、`_gd_pool.py`） | 層、題集與封存檔的釘值；§4 gold；§3 清單／池的形狀；確認集守門；§10 指紋、執行設定與 meta |
| `arms.py`（含 `_gd_lex.py`） | §3 dense 排名、R20（§4 D5≈ 的記錄層輸入）、bip 圖、PPR、六臂 extra，輸出 lists.json |
| `accept_a.py` | 驗收 A：以 PYTHONHASHSEED 0／1 與單執行緒各跑一次 arms.py，逐項核對，寫 `accept/accept_a.json` |
| `encode_stdin.py`、`rerank_stdin.py` | 容器內 stdin 腳本，不寫檔；由 score.py 在前面加上 PAYLOAD_B64 |
| `score.py`（含 `_score_io.py`） | host runner：encode、rerank（可續跑，結尾自動重打 §10 的 32 個參考對）、refpairs（單獨重打參考對） |
| `evaluate.py`（含 `_eval_inputs.py`、`_eval_metrics.py`、`_eval_report.py`、`_eval_stats.py`、`_eval_accept.py`） | 輸入來源核對、§4 指標、§5 檢定與把關、§6 V1、驗收 B；子命令 report、v1、units、build-ref、accept-b |
| `accept/` | 驗收 A、B 的結果 JSON |

測試：在 `evaluation/` 下執行 `.venv/bin/python -m pytest tests/test_graph_gd_*.py`。需要 store 的測試在 store 未掛載時自動 skip。

## 執行順序（NEW82，驗收）
1. `score.py encode --set new82 --ids <sorted(id) 前 5> --out N/encode_recheck5.jsonl --ref PN/encode_out.jsonl`：§3 重編檢查（已做，max|Δ|=0）。
2. `accept_a.py`：驗收 A。會以 `--overwrite` 重寫 N/`lists.json`（正式清單）、`lists_hashseed1.json`、`lists_threads1.json`。arms.py 只有在這裏才覆寫原始輸出。
3. `score.py rerank --lists N/lists.json --out N/scores.jsonl`：82 題池聯集共 4,936 對，打完後再開一次容器重打 32 個參考對，寫成檔尾的 refcheck 行（|Δ|>1e−5 即基礎設施失敗，退出碼 2）。中斷後用同一指令續跑：已打完的題會跳過，殘缺的最後一行會丟掉，缺少的 refcheck 也會補打。
4. `evaluate.py accept-b --lists N/lists.json --scores N/scores.jsonl --ref N/accept_b_reference.json`：驗收 B，寫 `accept/accept_b.json`。漂移 >1e−5 直接判失敗，不歸邊界題。
5. `evaluate.py report --set new82 --lists N/lists.json --scores N/scores.jsonl --out new82_report.json`：探索性結果，不得作為證據（§2）。
- 選用：`score.py refpairs --out N/<新檔名>.jsonl` 單獨重打參考對。

## 確認集（附錄 A 之後）
- 守門（`gd.assert_set_allowed`）：OLD31、GT v2 要附錄 A 有內容，HO 另要附錄 B；而且 `accept/accept_a.json` 與 `accept/accept_b.json` 都要 `passed: true`、不是未釘來源的鏈路核對，且兩者記的 `lists_sha256` 相同（B 打的是 A 驗過的清單）。佔位寫法（`待追加`、`- 待追加`、`（待追加）`、`TODO`、程式碼區塊內的字）不算內容。被拒時 arms.py、score.py、evaluate.py 一律單行錯誤、退出碼 2。`evaluate.py units`（只讀題目與 gold）不受守門，§2 允許。
- V1：`evaluate.py v1 --lists <OLD31 lists> --scores <OLD31 scores>` 只印、只寫停損判定與 GD−C@10 的單位 W:L（`v1_old31.json`），不算 p 與 CI。`report` 不接受單獨的 old31 或 ho。
- E2：`evaluate.py report --set old31+ho --lists L_old31 L_ho --scores S_old31 S_ho --out e2_report.json`，在聯集上重做群聚，另報 OLD31／HO 分開、剔除與 NEW82 共用 gold 的 16 題、HO-only 附註，以及排除 [SHORTCUT] 題的 H3。
- 缺跳（§4）：NEW82 用存檔的 missing_rr；OLD31、HO 用 D5≈（lists 的 R20 依重排分數取前 5），OLD31 另附 prod D5 缺跳。

## 來源核對（§10）
- lists.json 的 meta 要對上題集、層版本、向量、build 與自身內容雜湊（`lists_sha256`）。
- scores.jsonl 的每個 meta 行都要過 reranker 指紋與執行設定（CPU、batch 16、12 threads），host 部分要記同一份 lists 的內容雜湊、同一題集、同一組 score.py／_score_io.py／rerank_stdin.py；每行分數之後都要有通過的 refcheck 行。
- `--allow-unpinned` 只給 NEW82 的鏈路核對（例如新 lists 配封存分數），輸出記 `pinned: false`，且不准寫 `accept/accept_b.json`。

## 驗收狀態（2026-10-14）
- **A：通過**，見 `accept/accept_a.json`（檢查程式為本目錄的 `accept_a.py`，sha 記在檔內）。
- **B：通過**，見 `accept/accept_b.json`。正式打分 N/`scores.jsonl` 共 4,936 對，耗時 1,922 秒，refcheck 32 對 max|Δ|=0。逐題 top-k 集合 820/820 相同，實測漂移 1.76e−6，邊界題 0。全跳命中與缺跳命中都等於 §3 的參考值。探索性結果見 `new82_report.json`：H1 為 11:0，p=1/1024。
- **尚未實作**：W 逐窗重排、`e3_raw.py`（含 §8 三道閘門統計）、`ho_tools/`。附錄 A 也還沒寫。
