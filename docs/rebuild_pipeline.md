# 重建管線：從 66 卷 PDF 到 release、載入與驗證

新管線的唯一入口文件。設計依據：`/mnt/ollama-data/bible_rag_store/reference/DESIGN.md`（§4 DAG、§7 loader、§8 閘門）。舊的 `docs/build_database.md`（Step 0–10）已被取代。

## 1. 前置環境

- 工具：`mutool` 1.23.10、`pdftotext` 24.02.0（G-TOOL 逐一比對版本）。
- Python：只用 `scripts/.venv` 跑 ragdata。管線不跑 backend，也不需要 backend 的 venv。
- 模型一律離線：BGE-M3 在 `HF_HOME=/mnt/ollama-data/huggingface`，reranker tokenizer 在 `/mnt/ollama-data/bible_rag_store/models/`。建議有 GPU（emb 編碼與 G-ENC 全量重編碼）。
- repo 內的輸入：`bible_pdf/`（66 卷）、`config/registries/`、`ragdata/src/ragdata/contract/expectations/`、`ground_truth.json`（G-ROUTE 探針的 500 題）、`backend/data/event_registry.json`（K1 的 legacy 事件註冊表）。
- store `reference/` 的輸入：舊系統留下的唯讀副本。bible_md、legacy_output、route_live 三個目錄各有 `SHA256SUMS`，讀取端逐檔核對，任何一檔不符就停，不會默默換掉某一層。
  - `reference/bible_md/`：66 卷 md，只做 G-DIFF 對帳。text 層 `diff_summary.json` 的 `inputs.bible_md` 記著它的摘要。
  - `reference/audit_prototypes/gap_pdf_canonical/canonical_full.jsonl`：只做 G-DIFF 對帳。稽核時就放在這裡，沒有 `SHA256SUMS`；它的 sha 記在 `diff_summary.json` 的 `inputs.canonical_full`，內容一變，text 層就換版本。
  - `reference/legacy_output/`：舊 `output/` 的五個檔。
    - `pericopes.jsonl`、`chunks.jsonl`：struct 的 legacy id 對照。
    - `embedding_queue.jsonl`、`embeddings.jsonl`：G-ENC 的相容抽樣。
    - `chapters.jsonl`：ragdata 不讀。evaluation 的 GT v1 路徑（`evaluation/src/verse_coverage.py`）目前仍讀 repo 的 `output/chapters.jsonl`，清理 `output/` 前要改指向這份。
    - 2026-10-08 從主 checkout 的 `output/` 複製，與 `/mnt/ollama-data/bible_rag_bak/20261007/output/` 逐位元相同。
  - `reference/route_live/{探針 sha256}/live.json`：舊 backend（`entity_dicts`）在 G-ROUTE 探針文字上的比對結果。探針文字是 GT 500 題、全部節與全部標題。
    - K4 build 與 G-ROUTE 只在兩個條件都成立時使用它：探針文字的 sha256 相同，而且 `frozen_from` 等於 `routing_lexicon.legacy.json` 的 `header.frozen_from`。否則停在 route，並印出重產指令。
    - 現有一份：`32a5196c…`，34,124 段，出自 text@247eafe44b02。
- Store：`/mnt/ollama-data/bible_rag_store/`，底下 `layers/`、`releases/`、`contracts/`、`reference/`。
- `--load`／`--verify` 讀 repo 的 `.env`（`POSTGRES_*`、`QDRANT_*`）。

```bash
export HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAGDATA="env PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python -m ragdata"
```

重產 route_live：只有節文字、標題文字或 `ground_truth.json` 的題目改變時才需要。
- 舊 backend 已從 rebuild/main 移除（78b8abf），所以要從還有 `backend/utils/entity_dicts.py` 的 checkout 跑。f9ad4d3 的四個來源檔就是凍結版。
- `freeze probe` 比對的是舊 backend 在 venv 裡實際 import 的四個檔（各模組的 `__file__`），不是 `--backend-dir` 旁邊同名路徑的檔。四個 sha 要等於凍結詞表的 `header.frozen_from`，不符就拒絕，什麼都不寫；任何一個模組不是從檔案 import 的也拒絕。`freeze route` 寫進 `frozen_from` 的也是實際 import 的檔。
- 結果寫進新目錄 `{探針 sha256}/`；既有目錄永不覆寫，內容相同時什麼都不做。
- `--backend-python` 要能 import 舊 backend，例如主 checkout 的 `backend/.venv`。

```bash
git worktree add <暫存目錄> f9ad4d3      # 或直接用主 checkout /home/kenzx0521/Bible_RAG
$RAGDATA freeze probe --text /mnt/ollama-data/bible_rag_store/layers/text/<text 層版本> \
  --backend-python /home/kenzx0521/Bible_RAG/backend/.venv/bin/python \
  --backend-dir <暫存目錄>/backend
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
| src＋text（S0–S4） | PDF、errata／normalization／versification 註冊表；G-DIFF 另讀 `reference/bible_md/` 與 canonical_full | src：source_manifest、逐卷 extract；text：12 種記錄、xcheck／overlay／diff 報告 | G-TOOL、G-SRC、G-CONSERVE、G-COUNT、G-REFINT、G-TEXT、G-XCHECK、G-DIFF | G-SCHEMA、G-REF（G-CONSERVE 重讀 src、G-XCHECK 重讀 PDF） |
| struct（S5） | text、BGE-M3 tokenizer、`reference/legacy_output/` | pericopes、passages、chunks、verse_index、legacy_ids | G-SCHEMA、G-COUNT、G-REFINT、G-STRUCT | 同左 |
| emb（S6–S7） | struct、text、BGE-M3＋reranker tokenizer；G-ENC 另讀 `reference/legacy_output/` | embedding_records、指紋；向量是 `.vectors` 附件 | G-SCHEMA、G-COUNT、G-EMB、G-ENC（抽樣） | G-ENC 全量重編碼 |
| kg0（K0） | text、struct、K0 註冊表、`kg0_counts.yaml` | names、extra_spans、parallel_links | G-SCHEMA、G-REFINT、G-KG0、G-PROV | 同左 |
| events（K1） | text、struct、`events.yaml`、legacy 事件註冊表 | events、anchor_changes、兩份事件契約 | G-SCHEMA、G-COUNT、G-REFINT、G-EVENT、G-PROV | 同左 |
| route（K4） | text、`routing_lexicon.legacy.json`、`ground_truth.json`、`reference/route_live/` | routing_terms、routing_lexicon.json | G-SCHEMA、G-COUNT、G-ROUTE、G-PROV | 同左 |

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

節或標題的文字一變，G-ROUTE 的探針 sha256 也跟著變。管線會停在 route，並印出 `freeze probe` 指令；照 §1 的「重產 route_live」跑完，再跑一次 `pipeline run`。route_live 在 store，不必 commit。

## 5. 重跑、重用與 G-DET

- store 以內容定址：同樣輸入建出同樣位元組，就是同一個版本，報告標 `reused: true`；release 與 build_id 也相同。
- 報告保存每層的檔案 sha256（emb 另含向量附件），兩次執行的報告逐檔比對即是 G-DET 的記錄檔部分。
- 向量不要求逐位元相同：重建既有的 emb 版本時，沿用已存的向量，並要求本次向量與之 cos ≥ 0.99999、top-20 相同，否則停止。
- 要在不碰正式 store 的情況下比對兩次建置，用 `--store <暫存目錄> --releases <暫存目錄>` 各跑一次，再 `$RAGDATA det <A 層目錄> <B 層目錄>`。

## 6. promote 與回滾

`rag_meta.serving` 決定 backend 服務哪個 (build_id, 映像 digest)；backend 只在啟動時讀一次，改了要重啟才生效。

```bash
DIGEST=$(docker image inspect --format '{{.Id}}' bible_rag-backend:r1)
$RAGDATA promote --env staging --build <build_id> --image "$DIGEST"   # 印出新配對與先前配對
$RAGDATA promote --env staging --rollback                             # 回到上一筆
```

- 每次 promote 在同一交易內附加一筆到 `rag_meta.serving_history`（第一次 promote 時建表）；配對與目前相同時什麼都不寫。
- `--rollback`：把該 env 最新一筆未回滾的紀錄標為已回滾，serving 改回它的前一筆；再跑一次就再退一筆。最新一筆和 serving 不一致時拒絕，不做任何修改。
- 第一次 promote 的回滾（沒有前一筆）會刪掉該 env 的 serving 列，回到「沒有 build 在服務」；之後即可 unload 該 build。prod 另要把 backend 容器切回舊映像 `bible_rag-backend:latest`（讀 `public` 與舊 collection，不看 `rag_meta.serving`），切回時不要重建這個映像。
- `--env prod` 一律要加 `--yes-prod`，否則拒絕（promote 與 `--rollback` 都是）。
- 目前 prod 沒有 serving 列，線上 backend 仍讀 `public` schema 與舊 collection。`public`、`bible_embeddings*`、`bible_entities` 是 R1 上線前的回滾基準，**不可刪**。
- R1 staging backend（:8002）的啟動與驗證見 `docker-compose.staging.yml` 的 `backend-r1`。它的 restart 是 `"no"`：握手不符就停在 exited，不會反覆重載模型；主機重開機後要重跑該檔開頭的 `up` 指令。

## 7. 清理被取代的 build

1. 確認它不在 `rag_meta.serving`，也不是回滾或比較的基準。
2. `$RAGDATA unload <build_id>`：只刪該 build 的 schema、`rag_meta.builds` 列、Qdrant collection 與 `contracts/<build_id>/`；serving 中的 build 一律拒絕，重跑可完成中斷的 unload。
3. 刪 `releases/<build_id>.json`，再刪 store 裡沒有任何剩餘 release 引用的層版本（連同 `.vectors` 附件目錄）。
4. 永不刪：`reference/`、`models/`、`tools/`、`/mnt/ollama-data/bible_rag_bak/`，以及上述 legacy 資料。

## 8. 測試

四套測試都在 repo 根目錄跑。scripts 與 backend 的 venv 沒有 pytest，借 evaluation venv 的 pytest：
- `/mnt/ollama-data/bible_rag_store/tools/pytest_shim` 只放 pytest 相關套件的 symlink；
- `scripts/tests/run.sh` 自己建暫存 shim。

```bash
# ragdata＋packages：2,385 passed、5 skipped（PG 整合測試，要設 RAGDATA_TEST_PG_DSN），約 1.5 分鐘
env HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  scripts/.venv/bin/python -m pytest ragdata/tests packages/ragcommon/tests -q
# backend：186 passed
PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  backend/.venv/bin/python -m pytest backend/tests -q
# scripts：1,588 passed、1 skipped
scripts/tests/run.sh -q
# evaluation：加入 R1 評估工具後收集到 493 項（之前 380 passed）
evaluation/.venv/bin/python -m pytest evaluation/tests -q
```

- 上面的數字是 2026-10-08 的結果。
- ragdata 的測試會讀 store 的 `reference/`（bible_md、canonical_full）、repo 的 6 卷 PDF，以及離線的 BGE-M3 tokenizer。
- route 的測試用假 backend，不需要舊 backend。
