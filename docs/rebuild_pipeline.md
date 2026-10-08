# 重建管線：從 66 卷 PDF 到 release、載入與驗證

新管線的唯一入口文件。設計依據：`/mnt/ollama-data/bible_rag_store/reference/DESIGN.md`（§4 DAG、§7 loader、§8 閘門）。舊的 `docs/build_database.md`（Step 0–10）已被取代。

## 1. 前置環境

- 工具：`mutool` 1.23.10、`pdftotext` 24.02.0（G-TOOL 逐一比對版本）。
- Python：`scripts/.venv` 跑 ragdata；`backend/.venv` 只給 G-ROUTE 的 live 比對器用。
- 模型一律離線：BGE-M3 在 `HF_HOME=/mnt/ollama-data/huggingface`，reranker tokenizer 在 `/mnt/ollama-data/bible_rag_store/models/`。建議有 GPU（emb 編碼與 G-ENC 全量重編碼）。
- 輸入：`bible_pdf/`（66 卷）、`config/registries/`、`ragdata/src/ragdata/contract/expectations/`、舊 `output/`（legacy id 對照、G-ENC 相容抽樣）、`bible_md/` 與 canonical_full（只做 G-DIFF 對帳）。
- Store：`/mnt/ollama-data/bible_rag_store/`，底下 `layers/`、`releases/`、`contracts/`。
- `--load`／`--verify` 讀 repo 的 `.env`（`POSTGRES_*`、`QDRANT_*`）。

```bash
export HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAGDATA="env PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python -m ragdata"
```

## 2. 一個指令

```bash
$RAGDATA pipeline run [--date YYYYMMDD] [--load] [--verify] [--report pipeline.json]
```

- 依序：text（含 src）→ struct →〔推導檔檢查、G-GT〕→ emb → kg0 → events → route → release →（`--load`）→（`--verify`）。
- 每層先跑 build 閘門，全綠才寫入 store；寫入後立刻用該層**全部** required 閘門再驗一次。
- 任何紅燈立即停止：stderr 印出停在哪一層（含版本）、哪個閘門與前幾筆細節；stdout／`--report` 是完整 JSON 報告。
- 結束碼：0 全綠；1 硬閘門紅燈；2 輸入錯誤或推導檔過期；3 程式錯誤（附 traceback，不寫報告）。
- `--date` 預設是 HEAD 的 commit 日期；`build_id = b{date}_{release_sha 前 8 碼}`。
- 單步指令（`build`、`gate`、`det`、`release`、`load`、`verify`、`unload`）仍在，只供除錯；見 `$RAGDATA --help`。

## 3. 各層產出與閘門

| 層 | 主要輸入 | 產出 | build 閘門 | 入庫後加驗 |
|---|---|---|---|---|
| src＋text（S0–S4） | PDF、errata／normalization／versification 註冊表 | src：source_manifest、逐卷 extract；text：12 種記錄、xcheck／overlay／diff 報告 | G-TOOL、G-SRC、G-CONSERVE、G-COUNT、G-REFINT、G-TEXT、G-XCHECK、G-DIFF | G-SCHEMA、G-REF（G-CONSERVE 重讀 src、G-XCHECK 重讀 PDF） |
| struct（S5） | text、BGE-M3 tokenizer、`output/` | pericopes、passages、chunks、verse_index、legacy_ids | G-SCHEMA、G-COUNT、G-REFINT、G-STRUCT | 同左 |
| emb（S6–S7） | struct、text、BGE-M3＋reranker tokenizer | embedding_records、指紋；向量是 `.vectors` 附件 | G-SCHEMA、G-COUNT、G-EMB、G-ENC（抽樣） | G-ENC 全量重編碼 |
| kg0（K0） | text、struct、K0 註冊表、`kg0_counts.yaml` | names、extra_spans、parallel_links | G-SCHEMA、G-REFINT、G-KG0、G-PROV | 同左 |
| events（K1） | text、struct、`events.yaml`、legacy 事件註冊表 | events、anchor_changes、兩份事件契約 | G-SCHEMA、G-COUNT、G-REFINT、G-EVENT、G-PROV | 同左 |
| route（K4） | text、`routing_lexicon.legacy.json`、`ground_truth.json`、backend venv | routing_terms、routing_lexicon.json | G-SCHEMA、G-COUNT、G-ROUTE、G-PROV | 同左 |

之後：
- **release（S12）**：寫 `releases/{build_id}.json`（唯讀，同內容重寫是 no-op）；組裝時各層記錄閘門再跑一次。
- **load（S13）**：寫入新命名空間——PG schema `b{build_id}`、`rag_meta.builds` 一列、Qdrant `passages__{build_id}`、`contracts/{build_id}/`。目標已存在就拒絕；同一份 release 已登記則標 `reused`，不重載。
- **verify（S14）**：G-PROJ C1–C6 與 G-SCHEMA.pg，全部從三庫讀回比對；C6 要求凍結的 GT v2 指向本 release 的文字層。

## 4. 文字層改變時：推導檔

三個 commit 進 repo 的檔案記著它們出自哪個文字層。build 不寫 config/ 與 expectations（G-IMPORT），所以管線不會自動改寫它們，而是在 struct 之後檢查，不符就停在 `derived`，並依序印出要跑的指令（本 repo 的實際順序）：

1. `scripts/.venv/bin/python scripts/derive_ragcommon_data.py versification --text-layer <text 層目錄>`，然後 commit `packages/ragcommon/data`（`gt build` 拒絕未 commit 的產生器）。
2. `$RAGDATA expect kg0 --text <text> --struct <struct>`；看 diff，只該動本次改變造成的部分。
3. `$RAGDATA gt build --text-layer <text>`：重建 `ground_truth.v2.json`、`config/gold/gt_v2_changes.jsonl` 並重新凍結 `gt_v2_freeze.json`（slot_universe 指向新文字層）。
4. commit 上述檔案，再跑一次 `pipeline run`；已完成的層會直接重用。

GT v2 的人工判斷寫在 `config/gold/gt_v2_curated.yaml`；errata 的字形裁決寫在 `config/registries/errata.yaml`（套用者 `decided_by: kay`）。改了這些檔，就照上面的順序重來。

## 5. 重跑、重用與 G-DET

- store 以內容定址：同樣輸入建出同樣位元組，就是同一個版本，報告標 `reused: true`；release 與 build_id 也相同。
- 報告保存每層的檔案 sha256（emb 另含向量附件），兩次執行的報告逐檔比對即是 G-DET 的記錄檔部分。
- 向量不要求逐位元相同：重建既有的 emb 版本時，沿用已存的向量，並要求本次向量與之 cos ≥ 0.99999、top-20 相同，否則停止。
- 要在不碰正式 store 的情況下比對兩次建置，用 `--store <暫存目錄> --releases <暫存目錄>` 各跑一次，再 `$RAGDATA det <A 層目錄> <B 層目錄>`。

## 6. promote 與回滾

`rag_meta.serving` 決定 backend 服務哪個 (build_id, 映像 digest)。promote 是函式，不是指令，由操作者執行：

```bash
env PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python - <<'EOF'
from ragdata import paths
from ragdata.loader import cli, promote
pg, qdrant = cli.connect(cli.environment(paths.REPO / ".env"))
print(promote.promote(pg, "staging", "<build_id>", "sha256:<映像 digest>"))   # 回傳先前的配對
EOF
```

- 回滾：以 promote 回傳的先前配對再 promote 一次。
- 目前 `rag_meta.serving` 是空的，線上 backend 仍讀 `public` schema 與舊 collection。`public`、`bible_embeddings*`、`bible_entities` 是 R1 上線前的回滾基準，**不可刪**。

## 7. 清理被取代的 build

1. 確認它不在 `rag_meta.serving`，也不是回滾或比較的基準。
2. `$RAGDATA unload <build_id>`：只刪該 build 的 schema、`rag_meta.builds` 列、Qdrant collection 與 `contracts/<build_id>/`；serving 中的 build 一律拒絕，重跑可完成中斷的 unload。
3. 刪 `releases/<build_id>.json`，再刪 store 裡沒有任何剩餘 release 引用的層版本（連同 `.vectors` 附件目錄）。
4. 永不刪：`reference/`、`models/`、`tools/`、`/mnt/ollama-data/bible_rag_bak/`，以及上述 legacy 資料。
