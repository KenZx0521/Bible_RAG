# KG 資料層修復：證據腳本歸檔

[總計畫](../2026-10-04_kg_data_layer_fix_plan.md)、[第 1 批計畫](../2026-10-04_kg_batch1_plan.md) 與 [第 0 批結果](../2026-10-04_kg_batch0_results.md) 引用的調查與模擬腳本、小型產物。這裡只放程式碼和小檔；大型中間檔（pickle、xref dump 等）在 `bak/20261004_kgfix_evidence/` 的兩個 tarball 裡（gitignored，sha256 見該目錄的 `SHA256SUMS`）。

## 路徑參數

腳本原本寫死 repo 路徑和工作階段的 scratchpad 路徑。W0 第 1 步改成兩個環境變數，其餘程式碼逐字未動：

| 變數 | 預設 | 意義 |
|---|---|---|
| `BIBLE_RAG_ROOT` | `/home/kenzx0521/Bible_RAG` | repo 根目錄（讀 `output/`、`config/`、`scripts/`、`.env`） |
| `KGFIX_SP` | `$BIBLE_RAG_ROOT/bak/20261004_kgfix_evidence/scratchpad` | 原 scratchpad 的版面：`kgfix/`、`batch1plan/`、`bench/`、`kg_xref/` |
| `W1_1B_EVIDENCE` | `$BIBLE_RAG_ROOT/bak/20261005_w1_1b_evidence` | W1 1B 規劃證據的大檔（1B 前的 relationships 副本、投影邊表、預測與量測，唯讀）；只有 `batch1/w1_1B/` 用，見[該目錄 README](batch1/w1_1B/README.md) |

改寫是機械式的：只拆開「以根路徑開頭的字串常值」，docstring 不動。把參數代回原路徑後，110 個檔與改寫前逐字相同。

自 1B 起，量測舊 supplementary 定義的四支腳本（`xref/supp.py`、`verifier_xref/mdpairs.py`、`batch1/1B/sim_supp.py`、`batch1/1B-reviewer/r1_supp.py`）不再 import `bible_chunking.nt_cross_references`（1B 把它改寫成經文座標），改讀凍結檔 `xref/supp_defs_a32fbea.json`：a32fbea 的 161 筆定義依原順序、每筆 6 個欄位，載入成 `SimpleNamespace` 後屬性與原 dataclass 相同。這四支只把那一行 import 換成讀凍結檔（上段「逐字未動」的唯一例外，變數名照舊），所以定義在任何 HEAD 都能重放。資料端照舊讀 `BIBLE_RAG_ROOT/output/`：`output/neo4j_relationships.jsonl` 要是 1B 之前的版本（sha256 `15ed2505…`，副本是 `$W1_1B_EVIDENCE/neo4j_relationships_pre1b.jsonl`），W1 Step 0 覆寫它之後 supplementary 從 145 列變成 158 列，`xref/supp.py` 的 `assert len(kept)==len(supp)` 就會失敗；`verifier_xref/mdpairs.py` 也仍 import live 的 `CROSS_REF_ABBREV`（`bible_chunking.config`）。已驗證（2026-10-05）拿掉 `nt_cross_references.py` 後四支重跑，`supp_sim.json`、`supp_edges.json`、`supp_rows.json`、`r1_supp.json` 與 stdout 都和改前逐位元相同。`scripts/tests/test_supp_defs_frozen.py` 守住凍結檔的筆數與欄位；這四支加上 `batch1/w1_1B/` 的 `sim_w1_1b.py`、`sim_states.py`、`golden.py`（共 7 支，即測試裡的 `ARCHIVED`）不再 import live 模組；`test_definition_ledger` 確認 live 定義等於凍結檔的機械式轉換，扣掉 XREF-2 刪的 2 筆、加上 X2 的改錨。

`batch1/inputs/` 是原本只在 scratchpad 的兩份輸入：`bench/questions_table.json`（500 題逐題表）與 `kg_xref/`（2026-10-03 審查的 kg_xref 68 題）。

## 重放

多數腳本把中間檔寫在自己旁邊（`OUT = Path(__file__).parent`），所以要在還原後的 scratchpad 版面裡執行：

```bash
D=bak/20261004_kgfix_evidence
mkdir -p $D/scratchpad
tar xzf $D/kgfix_scratchpad.tgz -C $D/scratchpad
tar xzf $D/batch1plan_scratchpad.tgz -C $D/scratchpad
cp -r docs/records/2026-10-04_kg_fix/batch1/inputs/. $D/scratchpad/
# tarball 裡是改寫前的腳本：用這裡的版本覆蓋，例如 1B
cp docs/records/2026-10-04_kg_fix/batch1/1B/*.py $D/scratchpad/batch1plan/1B/
cd $D/scratchpad/batch1plan/1B && uv run --project "$OLDPWD/scripts" python sim_kgxref.py
```

已驗證（2026-10-04）：

- `batch1/1B/sim_kgxref.py` 重跑後 `kgxref_reach.json` 與本目錄的檔逐位元相同；
- `batch1/planner_1A/sim_1a.py --begot gei --surface declared` 重跑後 `sim_1a_gei_declared.json` 逐位元相同，`relations_clean_sim_gei_declared.jsonl` 的 sha256 與 `sha1.txt` 相同。

讀 live 資料庫的腳本（`*ro.py`、`live_*`、`dump*.py`）重跑會得到當下的狀態，不是 2026-10-04 的狀態。

## a32fbea 上才能跑的兩支（第 1A 批之後）

`relations/sim.py` 與 `relverify/exactsim.py` import `scripts.relation_extraction.rule_classifier.classify_by_rules`。第 1A 批的 9c1c6c3（C6b）把 R2 連同這個模組刪掉，之後的 HEAD 上兩支都停在 `ModuleNotFoundError`。它們從 `BIBLE_RAG_ROOT` 讀程式、`config/` 與 `output/`，所以把 a32fbea 的 `scripts/`、`config/` 匯出到暫存目錄、再把 `output/` 連過去就能重跑，不必動 git worktree（`D` 同上一節）：

```bash
A32=$(mktemp -d)
git archive a32fbea scripts config | tar -x -C $A32
ln -s "$PWD/output" $A32/output
cd $D/scratchpad/kgfix/relations && BIBLE_RAG_ROOT=$A32 "$OLDPWD/scripts/.venv/bin/python" "$OLDPWD/docs/records/2026-10-04_kg_fix/relations/sim.py"
```

`exactsim.py` 改在 `$D/scratchpad/kgfix/relverify` 下同樣執行。已驗證（2026-10-06）：兩支在 a32fbea 的匯出上結束碼 0（`sim.py` 印出 rule_hit 1,113、llm_pairs 89,033；`exactsim.py` 印出 rule_hits_resim 898），在 HEAD 上都是 `ModuleNotFoundError`。

其他歸檔腳本都不 import 這個模組。1A 的兩支模擬器（`batch1/planner_1A/sim_1a.py`、`batch1/w1_1A/sim_1a_w1.py`）在 HEAD 照常重放：同一天在 4a8e826 之上重跑，`relations_clean_sim_gei_declared.jsonl` 的 sha256 仍是 `b564a2a8…`，三份 sim2 的 `after_10_2_sha256` 與 `anchored_key_sha` 都與下一節的表相同；JSON 只多了 26bc252 新增探針的欄位（下一節末段說明過 `config/kg_probes.yaml` 只影響這些欄位）。

## W1 1A 重算（`batch1/w1_1A/`）

[第 1 批計畫](../2026-10-04_kg_batch1_plan.md) 1A 各列的重算數字出自這組腳本。原檔在 W1 工作階段 scratchpad 的 `w1/1A/`。歸檔時改了這幾處：路徑參數（下述）；`anchored_v2` → `anchored_w1` 的 import 名稱；`gen_fixture.py`、`r4_final.py`、`multi_parent.py` 加上 argparse（`gen_fixture.py` 是 `--out`，另兩支是 `--out-dir`，`multi_parent.py` 的 clean2 檔名改成位置參數），`sim_1a_w1.py` 原本就有 argparse，只加 `--out-dir`；`sim_1a_w1.py`、`gen_fixture.py` 把 `../planner_1A` 加進 `sys.path`；`sim_1a_w1.py`、`gen_fixture.py`、`r4_final.py` 的 docstring 加長，`multi_parent.py` 新增 docstring（`sim_1a_w1.py` 原本的 Usage 行換成一段歸檔說明）。計算邏輯逐字未動，可與 `bak/20261005_w1_1A_evidence/` 的原檔 diff 驗證。

| 這裡 | scratchpad 原檔 | 用途 |
|---|---|---|
| `sim_1a_w1.py` | `rev/sim_1a_v3.py` | Step 6.05 離線模擬：`planner_1A/sim_1a.py` 的 v2 改寫，再加 `--disagree`（第二段同名防護）與 `--anchored`（on/off） |
| `anchored_w1.py` | `rev/anchored_v2.py` | anchored_rules 樣式比對，`sim_1a_w1.py` 與 `gen_fixture.py` 共用 |
| `gen_fixture.py` | `sim/gen_fixture.py` | 產生 anchored_rules 回歸 fixture |
| `r4_final.py` | `rev/r4_final_v3.py` | 用 7688 實際的 MENTIONS 與標籤給最終組態算 H3/H9（唯讀） |
| `multi_parent.py` | `rev/multi_parent.py` | 數有 2 個以上非女性父母的子女 |
| `sim2_final.json` | `rev/sim2_gei_declared_ppg_cont_any_hom2_disany.json` | 最終組態的摘要 |
| `sim2_no_disagreement.json` | `rev/sim2_gei_declared_ppg_cont_any_hom2.json` | 關掉第二段防護；等於草稿的 b23efe4d，用來檢查移植忠實 |
| `sim2_no_anchored.json` | `rev/sim2_gei_declared_ppg_cont_any_hom2_disany_noanch.json` | anchored 全關，K9 不過時預先登錄的退路 |

路徑：

- `BIBLE_RAG_ROOT`、`KGFIX_SP` 同上表。`sim_1a_w1.py` 讀 `$KGFIX_SP/kgfix/relverify/edges.json`（2026-10-04 的 live 邊 dump），要先照上一節解開 `kgfix_scratchpad.tgz`。
- 輸出寫到 `--out-dir`（預設是腳本所在的目錄）。`r4_final.py` 和 `multi_parent.py` 的 `--out-dir` 指向 `sim_1a_w1.py` 寫 `clean2_*.jsonl` 的目錄；`gen_fixture.py` 用 `--out` 指定輸出檔。沒指定 `--out-dir`／`--out` 時寫在本目錄的產物（`clean2_*`、`anch2_*`、`sim2_{off,father,gei}_*`、`anchored_regression.jsonl`）由本目錄的 `.gitignore` 排除。
- 重放區塊不設 `BIBLE_RAG_ROOT`，所以讀的是預設的 `/home/kenzx0521/Bible_RAG`（主 checkout）的 `output/`、`config/` 與 `scripts/`。要在 worktree 裡重放、讓它讀 worktree 的 `config/` 與 `scripts/`，先 `export BIBLE_RAG_ROOT=$PWD`：`after_10_2`、10.2 後 sha256 與 anchored key 三欄不變（2026-10-06 在 14e2063 之上重跑三組態），但 sim2 的 `probes` 欄會多出 26bc252 新增探針的分數，所以下面的比對先去掉 `probes` 欄。
- `common.py` 用 `batch1/planner_1A/common.py`：腳本自己把 `../planner_1A` 加到 `sys.path` 尾端（本目錄仍優先），不用設 `PYTHONPATH`。
- `clean2_*.jsonl` 每份約 2.2 MB，不歸檔；重跑一組只要幾秒。

三組態重放（在 repo 根目錄執行）：

```bash
A=docs/records/2026-10-04_kg_fix/batch1/w1_1A
O=$(mktemp -d)
CFG="--begot gei --surface declared --lexicon ppg --stop-de cont --guard any --homonym person:bide,person:yuehan（shitu）"
PYTHONHASHSEED=7 scripts/.venv/bin/python $A/sim_1a_w1.py $CFG --disagree any --out-dir $O/final
PYTHONHASHSEED=7 scripts/.venv/bin/python $A/sim_1a_w1.py $CFG --disagree off --out-dir $O/no_disagreement
PYTHONHASHSEED=7 scripts/.venv/bin/python $A/sim_1a_w1.py $CFG --disagree any --anchored off --out-dir $O/no_anchored
cmp <(jq -S 'del(.probes)' $O/final/sim2_gei_declared_ppg_cont_any_hom2_disany.json) <(jq -S 'del(.probes)' $A/sim2_final.json)
cmp <(jq -S 'del(.probes)' $O/no_disagreement/sim2_gei_declared_ppg_cont_any_hom2.json) <(jq -S 'del(.probes)' $A/sim2_no_disagreement.json)
cmp <(jq -S 'del(.probes)' $O/no_anchored/sim2_gei_declared_ppg_cont_any_hom2_disany_noanch.json) <(jq -S 'del(.probes)' $A/sim2_no_anchored.json)
scripts/.venv/bin/python $A/gen_fixture.py --out $O/anchored_regression.jsonl
scripts/.venv/bin/python $A/multi_parent.py clean2_gei_declared_ppg_cont_any_hom2_disany.jsonl --out-dir $O/final
scripts/.venv/bin/python $A/r4_final.py --out-dir $O/final   # 讀 7688（唯讀）
```

比對先去掉 `probes` 欄：在含 26bc252 的樹上（`BIBLE_RAG_ROOT` 指向 W1 以後的 checkout），三份 sim2 只有 `probes` 欄與本目錄的檔不同（2026-10-06 在 14e2063 之上三組態實測，去掉後逐位元相同）；在 26bc252 之前的樹上（例如 2026-10-06 時仍在 f06cc7b 的主 checkout，即預設的根目錄）直接 `cmp` 也逐位元相同。

預期值（sim2 的 `after_10_2`、`after_10_2_sha256`、`anchored_key_sha` 欄）：

| 組態 | 10.2 後邊數 | 10.2 後 sha256 | anchored key sha256 |
|---|---|---|---|
| 最終（`--disagree any`） | 5,616 | `661cfc6289e2966e71a0c83d974be99d256e04e0f90ac78ae28f8fb518c7bbc1` | `57bf0c82e3cbced99ff07ad55413cacf907bd82d0aead72dcab302dae4723432` |
| 第二段防護關（`--disagree off`） | 5,756 | `b23efe4dc91b654834655430ad7d708281ac05c254a17627d8d8d0678c8d6315` | `fbe95cfb5b84ea276acdc801dad5120f341661f2385edcb00ca741bebf3e21c6` |
| anchored 關（`--anchored off`） | 5,297 | `bbc5c83065dca3d92f6e2f6e03bf57e96e987b70a00e374489600233b0e173ff` | `e3b0c442…`（空集合） |

已驗證（2026-10-05，在 `e5fe097` 之上，`output/` 未動）：

- 三份 sim2 與本目錄的檔逐位元相同，`PYTHONHASHSEED=123` 也一樣；三份 `clean2_*.jsonl` 與 scratchpad 原檔逐位元相同（sha256 依序為 `fb974656…`、`954d3b0d…`、`6da44a76…`）。
- `gen_fixture.py` 產出 46 列，sha256 `17ce5b9babb2e956…`，與 scratchpad 的 `fixtures/anchored_regression.jsonl` 相同。
- `multi_parent.py`：383 個子女中有 8 個有 2 個以上非女性父母。
- `r4_final.py`：H3 = 0、H9 = 0（當時 7688 仍是第 0 批的建置，46,205 條 MENTIONS）。它讀 live 資料庫，重跑會得到當下的狀態。

兩個 sha 只取決於 `output/*.jsonl`、`config/relations/biblical_relations.yaml`、`scripts/relation_extraction/schema_loader.py`、`scripts/cleanup_noise_entities.py` 與它轉出的兩個模組：`scripts/entity_extraction/geo_rules.py`（「但」過濾，7d9e680 從 `cleanup_noise_entities.py` 搬過去）、`scripts/entity_extraction/stoplists.py`（`GENERIC_EVENT_STOPLIST` 只 import、不使用）。`config/kg_probes.yaml` 只影響 sim2 的探針與 R6 欄位：之後改了它，sim2 可能不再逐位元相同，sha 則不變（已用改過 `female_persons` 和探針的副本實測）。

整個 scratchpad `w1/1A/` 樹另存在 `bak/20261005_w1_1A_evidence/`（gitignored，`SHA256SUMS` 可驗），內容包括各組態的 clean2/anch2/sim2、critic 版本、fixture，以及試標用的 `rev/pilot.py` 與 `rev/pilot_labels.json`。正式 K9 的結果報告（C10）出來以前，試標標籤不進 repo，盲標者才看不到。
