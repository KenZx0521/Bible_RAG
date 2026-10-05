# W1 1B 規劃證據

[第 1 批計畫](../../../2026-10-04_kg_batch1_plan.md) W1 的 1B 串流（cross-reference 來源旗標、經文座標、C1 後端排序）規劃時寫的模擬器、獨立預測 oracle 與小型產物。規劃當下（2026-10-05）它們只在工作階段 scratchpad；1B-A0 先把它們歸檔，1B-T1、1B-T3 的驗收才有不在 /tmp 的對照基準。這裡只放程式碼和小檔，大檔在 `$W1_1B_EVIDENCE`（預設 `bak/20261005_w1_1b_evidence/`，gitignored），sha256 見下表與該目錄的 `SHA256SUMS`。

## 路徑參數

沿用[上層 README](../../README.md) 的 `BIBLE_RAG_ROOT`、`KGFIX_SP`，另加一個：

| 變數 | 預設 | 意義 |
|---|---|---|
| `W1_1B_EVIDENCE` | `$BIBLE_RAG_ROOT/bak/20261005_w1_1b_evidence` | 大型輸入與輸出：1B 前的 relationships 副本、投影邊表、預測與量測 |

改寫照 W0 第 1 步的機械式規則（以根路徑開頭的字串常值改成參數，docstring 不動），另有四處：

- `sim_w1_1b.py`、`sim_states.py`、`golden.py` 不再 import `bible_chunking.nt_cross_references`（1B-C3c 會把它改寫成經文座標），改讀凍結檔 `xref/supp_defs_a32fbea.json`（1B-C3a），載入成 `SimpleNamespace` 後屬性相同；`scripts/tests/test_supp_defs_frozen.py` 守住這三支不再 import live 模組。
- `sim_w1_1b.py`、`sim_states.py` 改讀 `$W1_1B_EVIDENCE/neo4j_relationships_pre1b.jsonl`，不讀 `output/neo4j_relationships.jsonl`（W1 Step 0 會覆寫它），並 assert 它的 sha256 是 `15ed2505…`。
- 大型輸出（`xref_new_w1.json`、`pred_*.json`、`meas_*.json`）寫到 `$W1_1B_EVIDENCE`；小檔照舊寫在腳本旁。`golden.py`、`sup_*.py`、`ro_mc.py` 讀寫的是目前目錄，`ro_old_probe.py` 從目前目錄 exec `sim_backend_w1.py`，所以要在本目錄的複本裡執行。
- `sup_s3.py` 原本在 scratchpad 的 `critic/` 子目錄讀 `../golden_s3.json`；歸檔後與 `golden_s3.json` 同層，改讀 `golden_s3.json`。

這幾支只用 `scripts/import_tsk_crossrefs.py` 的四個名字：`build_verse_map`、`parse_ref`、`expand_to_range`、`MAX_RANGE_VERSES`（`sim_w1_1b.py` 用前三個，`expand_to_range` 內部用第四個；`sup_*.py` 用 `parse_ref` 與 `MAX_RANGE_VERSES`）。1B-C6a 改 Step 9 時保留這四個名字與語意，重放才成立。

## 檔案

離線腳本（只讀 `output/` 與歸檔輸入，可重放）：

| 腳本 | 內容 |
|---|---|
| `sim_w1_1b.py` | 離線重算 1B Step 0 與 Step 9：161 筆定義機械式轉座標、XREF-2 刪 2 筆、X2(a) 改錨為 rev 19:16>dan 2:47、跨段落展開（每筆至多 3 錨）、markdown 與 supplementary 依 (start, end) 聚合、TSK 依 `import_tsk_crossrefs` 聚合、SET 語意。印出錨 162、curated 932、attached 924、curated 無 TSK 8、總邊 250,366、fingerprint `e522411e…`、對 2026-10-04 prod 的轉移（淨 −52）。寫出 `xref_new_w1.json`、`supp_expected_pairs.json`、`supp_defs_a32fbea_coords.json` |
| `sim_states.py` | Step 0 各 commit 的中間狀態：S3（座標、未刪）錨 164／相異對 160 → C5a（刪 2 筆）162／158 → C5b（X2 a）162／158 |
| `golden.py` | 黃金錨表 `golden_s3.json`（164 錨、160 對）與 `golden_final.json`（162 錨、158 對）。腳本只印 sha256 前 16 碼；compact 排序 JSON 的完整 sha256 見下方重放 |
| `sup_cap.py` | final 162 錨的 verse-level TSK 支持（套用 60 節上限）：`anchors 162 fwd 162 rev-only 0 none 0` |
| `sup_s3.py` | 同上，S3 的 164 錨：`anchors 164 fwd 161 rev-only 0 none 3`，三筆無支持正是 XREF-2 刪的兩筆與改錨前的 rev 19:11-16>dan 7:13-14 |
| `sim_backend_w1.py` | C1 後端 xref 排序（過渡 `coalesce(r.curated, source IN md/supp)` 加 087ab0d 的 md5 平手）的離線移植。STEP1（部署：087ab0d Cypher → C1，live 資料）單 seed 5/2,779 只變權重、proxy 題組 1/262；STEP2（資料：C1 live → C1 W1 邊表）單 seed 147（100 換集合、47 只變權重）、題組 17/262。寫出 `pred_trans.json`、`pred_new.json`、`step2_questions_changed.json` |

讀 live 資料庫的腳本（READ session；重跑得到當下狀態，不是 2026-10-05 的狀態）：

| 腳本 | 內容 |
|---|---|
| `ro_c1_probe.py` | 在 prod（7687）與 staging（7688）跑計畫的 C1 Cypher，涵蓋 2,779 單 seed、2,779 legacy、262 proxy 題組，共 5,820 keys，與 `pred_trans.json` 比對；寫出 `meas_trans_{prod,staging}.json` |
| `ro_old_probe.py` | 087ab0d 的 one-hop／fallback Cypher 在 prod 上對照 OLD 模式移植，驗證 STEP1 的差異數字 |
| `ro_staging.py` | staging 的 xref 來源分布與 K10 五個實體的 mention_count |
| `ro_mc.py` | prod 與 staging 逐實體 mention_count 差異 → `mc_diff_prod_vs_stg0.json`（4 筆，K10 殘差） |

小型產物：`golden_s3.json`、`golden_final.json`、`supp_defs_a32fbea_coords.json`（161 筆定義的座標）、`supp_expected_pairs.json`（158 對與各自的錨字串）、`step2_questions_changed.json`（STEP2 權重或集合有變的 17 題）、`mc_diff_prod_vs_stg0.json`。

## 大檔（`$W1_1B_EVIDENCE`）

檔案設為唯讀。預設的 `W1_1B_EVIDENCE` 指向這裡，所以重放要另設暫存目錄，否則腳本寫檔時會因權限而停。

| 檔案 | sha256 | 證明什麼 |
|---|---|---|
| `xref_new_w1.json` | `2fb46ac1b4e874a5adc52f1692e1c8b0304a5db566f0383f39e19dd3289c3045` | `sim_w1_1b.py` 投影的 W1 CROSS_REFERENCES 邊表：250,366 邊，每列 `[a, b, curated, votes, tsk, curated_sources, source]`。1B-T3 的 expect 對它比對 |
| `pred_trans.json` | `3b1df1243d6c57a9f9074b18e297aa4fa9abd88a4a586ea2ec5dd3b6b2ca9aaf` | 移植對 C1 程式碼在 live 資料上的預測（5,820 keys）。它與 prod、staging 上真實 C1 Cypher 的量測 0/5,820 不符，所以是獨立 oracle；1B-T1 的 `predict --target` 對它比對 |
| `pred_new.json` | `40108c1b983b2085e5b47b6e385cbc927d8937f505f7093d4d1ba96d9f461a7b` | 同一移植在投影 W1 邊表上的預測（5,820 keys，與 `pred_trans.json` 有 577 個 key 不同）。1B-T3 的 `predict --edges` 對它比對 |
| `meas_trans_prod.json` | `6503ec1ed7fb5ba0ee18d7c3243ed2fba66cee4874196b250625c71b4599774e` | `ro_c1_probe.py` 在 prod 的量測（2026-10-05） |
| `meas_trans_staging.json` | `6503ec1ed7fb5ba0ee18d7c3243ed2fba66cee4874196b250625c71b4599774e` | 同上，staging（第 0 批資料）。與 prod 逐位元相同：md5 平手讓結果不受存放順序影響 |
| `neo4j_relationships_pre1b.jsonl` | `15ed25053c6cd299546ec234b59d281a9f5f48c48c52e1d4a0f16176a77fc166` | 1B 前（a32fbea 起）的 `output/neo4j_relationships.jsonl` 副本：8,358 列，CROSS_REFERENCES 為 markdown 774、supplementary 145 |

`pred_trans.json` 與兩份 `meas_trans_*.json` 以 `json.load` 讀入後相等（5,820 keys 全同）；檔案 sha256 不同只因 key 順序。

未歸檔、只記 sha256 的輸入（重放前比對，不同就表示輸入已漂移）：

| 輸入 | sha256 |
|---|---|
| `output/pericopes.jsonl` | `2e46fea4817c538ae4b5b4c6535491277674dc140c8b81dbf2fec8235a038c2c` |
| `output/embedding_queue.jsonl` | `5d2ac0e5460c4d58f4c52e1073986da0bbfabd80ee8c3f3aa6f83030086a198b` |
| `output/cross_references_tsk.txt` | `452b263f657d3e721d20341b6b82f1196fc98882d685bd4ef9050ae17f033f82` |
| `$KGFIX_SP/batch1plan/1B/xref_prod.json`（2026-10-04 prod xref dump，在 `batch1plan_scratchpad.tgz`） | `410223731eb07fe2eb22eda896d2e70a96cb6afec9f0ada4c500d891eb7e68e4` |
| `batch1/inputs/bench/questions_table.json` | `5b207bf90bcabaaff2ebb668ea83b58992d6aa993fe90cee5370b7a1f6134295` |
| `xref/supp_defs_a32fbea.json` | `aa1d76c058031726c0672d81f77b5c5f4123411f2e4d27ed2ef530119d9de9ea` |

## 重放

在 repo 根目錄執行（`KGFIX_SP` 依上層 README 還原；這裡用 scripts 的 venv，不用 `uv run`）：

```bash
export BIBLE_RAG_ROOT=$PWD
(cd bak/20261005_w1_1b_evidence && sha256sum -c SHA256SUMS)
export W1_1B_EVIDENCE=$(mktemp -d)
cp bak/20261005_w1_1b_evidence/neo4j_relationships_pre1b.jsonl $W1_1B_EVIDENCE/
R=$(mktemp -d) && cp docs/records/2026-10-04_kg_fix/batch1/w1_1B/* $R/ && cd $R
PY=$BIBLE_RAG_ROOT/scripts/.venv/bin/python
for s in sim_w1_1b sim_states golden sim_backend_w1 sup_cap sup_s3; do $PY $s.py > $s.out || break; done
(cd $W1_1B_EVIDENCE && sha256sum xref_new_w1.json pred_trans.json pred_new.json)   # 對照上表
for f in golden_s3.json golden_final.json supp_defs_a32fbea_coords.json supp_expected_pairs.json step2_questions_changed.json; do
  cmp $f $BIBLE_RAG_ROOT/docs/records/2026-10-04_kg_fix/batch1/w1_1B/$f
done
$PY -c "import hashlib, json; [print(f, hashlib.sha256(json.dumps(json.load(open(f)), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()) for f in ('golden_s3.json', 'golden_final.json')]"
```

最後一行印出 golden 表 compact 排序 JSON 的 sha256：`golden_s3.json` 是 `99887e9a3ed94239351049c441456f33060d137c6c8b26e844781d1475aa5bfa`，`golden_final.json` 是 `c1da4fbbcb436b6f0efd34051759efc8e3583fdfd4049146a2a6f54f27e590a8`。

已驗證（2026-10-05）：以模擬 1B 之後的根目錄重放（拿掉 `bible_chunking/nt_cross_references.py`、覆寫 `output/neo4j_relationships.jsonl`），六支離線腳本的 stdout 與規劃時逐位元相同；`xref_new_w1.json`、`pred_trans.json`、`pred_new.json` 與上表 sha256 相同；五個小檔與本目錄逐位元相同；`neo4j_relationships_pre1b.jsonl` 多一個位元組時 `sim_w1_1b.py`、`sim_states.py` 都以 AssertionError 停下。同日以改寫後的 `ro_*.py` 重跑（READ）：`ro_c1_probe.py` 在 prod 與 staging 都是 0/5,820 不符，兩份 `meas_trans_*.json` 的 sha256 與上表相同；`ro_old_probe.py` 0/2,779；`ro_mc.py` 的 `mc_diff_prod_vs_stg0.json` 與本目錄逐位元相同。
