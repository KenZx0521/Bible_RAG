# KG 資料層修復：證據腳本歸檔

[總計畫](../2026-10-04_kg_data_layer_fix_plan.md)、[第 1 批計畫](../2026-10-04_kg_batch1_plan.md) 與 [第 0 批結果](../2026-10-04_kg_batch0_results.md) 引用的調查與模擬腳本、小型產物。這裡只放程式碼和小檔；大型中間檔（pickle、xref dump 等）在 `bak/20261004_kgfix_evidence/` 的兩個 tarball 裡（gitignored，sha256 見該目錄的 `SHA256SUMS`）。

## 路徑參數

腳本原本寫死 repo 路徑和工作階段的 scratchpad 路徑。W0 第 1 步改成兩個環境變數，其餘程式碼逐字未動：

| 變數 | 預設 | 意義 |
|---|---|---|
| `BIBLE_RAG_ROOT` | `/home/kenzx0521/Bible_RAG` | repo 根目錄（讀 `output/`、`config/`、`scripts/`、`.env`） |
| `KGFIX_SP` | `$BIBLE_RAG_ROOT/bak/20261004_kgfix_evidence/scratchpad` | 原 scratchpad 的版面：`kgfix/`、`batch1plan/`、`bench/`、`kg_xref/` |

改寫是機械式的：只拆開「以根路徑開頭的字串常值」，docstring 不動。把參數代回原路徑後，110 個檔與改寫前逐字相同。

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
