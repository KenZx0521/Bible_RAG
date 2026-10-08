# 重建管線：從 66 卷 PDF 到 release、載入與驗證

新管線的唯一入口文件。設計依據：`/mnt/ollama-data/bible_rag_store/reference/DESIGN.md`（§4 DAG、§7 loader、§8 閘門）。舊管線（`docs/build_database.md` Step 0–10、`scripts/` 的建庫程式、`bible_chunking/`）已刪除，要看請用 R1 的 commit（1618cbd）。

## 1. 前置環境

- 工具：`mutool` 1.23.10、`pdftotext` 24.02.0（G-TOOL 逐一比對版本）。
- Python：只用 `scripts/.venv` 跑 ragdata。管線不跑 backend，也不需要 backend 的 venv。
- 模型一律離線：BGE-M3 在 `HF_HOME=/mnt/ollama-data/huggingface`，reranker tokenizer 在 `/mnt/ollama-data/bible_rag_store/models/`。建議有 GPU（emb 編碼與 G-ENC 全量重編碼）。
- repo 內的輸入：`bible_pdf/`（66 卷）、`config/registries/`（K0 註冊表；K1 讀 `events.yaml` v2；K4 另讀 `query_aliases.yaml`）、`ragdata/src/ragdata/contract/expectations/`、`ground_truth.json`（GT v1，G-GT 核對 GT v2 變更紀錄用）。
  - R1 的 `config/registries/routing_lexicon.legacy.json` 與 `backend/data/event_registry.json` 已刪除（R2 管線與 backend 都不讀）；要重現 R1，從 R1 的 commit（1618cbd）跑。
- store `reference/` 的輸入：舊系統留下的唯讀副本。bible_md、legacy_output 兩個目錄各有 `SHA256SUMS`，讀取端逐檔核對，任何一檔不符就停，不會默默換掉某一層。
  - `reference/bible_md/`：66 卷 md，只做 G-DIFF 對帳。text 層 `diff_summary.json` 的 `inputs.bible_md` 記著它的摘要。
  - `reference/audit_prototypes/gap_pdf_canonical/canonical_full.jsonl`：只做 G-DIFF 對帳。稽核時就放在這裡，沒有 `SHA256SUMS`；它的 sha 記在 `diff_summary.json` 的 `inputs.canonical_full`，內容一變，text 層就換版本。
  - `reference/legacy_output/`：舊 `output/` 的五個檔。
    - `pericopes.jsonl`、`chunks.jsonl`：struct 的 legacy id 對照。
    - `embedding_queue.jsonl`、`embeddings.jsonl`：G-ENC 的相容抽樣。
    - `chapters.jsonl`：ragdata 不讀。evaluation 的 GT v1 路徑（`evaluation/src/verse_coverage.py`）目前仍讀 repo 的 `output/chapters.jsonl`，清理 `output/` 前要改指向這份。
    - 2026-10-08 從主 checkout 的 `output/` 複製，與 `/mnt/ollama-data/bible_rag_bak/20261007/output/` 逐位元相同。
  - `reference/route_live/`：只是 R1 的產物（R1 的 G-ROUTE 拿舊 backend 的凍結比對結果對帳）。R2 的 route 層沒有 live 比對，管線不讀它；要重驗 R1 的 route 層，從 R1 的 commit（e7b1173）跑。
- Store：`/mnt/ollama-data/bible_rag_store/`，底下 `layers/`、`releases/`、`contracts/`、`reference/`。
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
| src＋text（S0–S4） | PDF、errata／normalization／versification 註冊表；G-DIFF 另讀 `reference/bible_md/` 與 canonical_full | src：source_manifest、逐卷 extract；text：12 種記錄、xcheck／overlay／diff 報告 | G-TOOL、G-SRC、G-CONSERVE、G-COUNT、G-REFINT、G-TEXT、G-XCHECK、G-DIFF | G-SCHEMA、G-REF（G-CONSERVE 重讀 src、G-XCHECK 重讀 PDF） |
| struct（S5） | text、BGE-M3 tokenizer、`reference/legacy_output/` | pericopes、passages、chunks、verse_index、legacy_ids | G-SCHEMA、G-COUNT、G-REFINT、G-STRUCT | 同左 |
| emb（S6–S7） | struct、text、BGE-M3＋reranker tokenizer；G-ENC 另讀 `reference/legacy_output/` | embedding_records、指紋；向量是 `.vectors` 附件 | G-SCHEMA、G-COUNT、G-EMB、G-ENC（抽樣） | G-ENC 全量重編碼 |
| kg0（K0） | text、struct、K0 註冊表、`kg0_counts.yaml` | names、extra_spans、parallel_links | G-SCHEMA、G-REFINT、G-KG0、G-PROV | 同左 |
| events（K1） | text、struct、`events.yaml`（R2 人工註冊表，以 pericope 宣告錨點） | events、event_registry_v2.json、events_report.json | G-SCHEMA、G-COUNT、G-REFINT、G-EVENT、G-PROV | 同左 |
| route（K4） | text、kg0、events、kg0 綁定的 `divine_refs`／`name_normalization`、`query_aliases.yaml`、`ragcommon` 書名 | routing_terms、routing_lexicon.json（v2）、query_aliases.json、route_report.json | G-SCHEMA、G-COUNT、G-ROUTE、G-PROV | 同左 |

R2 的事件與路由層（R1 的轉換路徑已移除）：
- **K1**：`events.yaml` v2 是人工註冊表本體，不再從舊 backend 的事件註冊表轉換。錨點以 pericope 宣告，建置時展開成它的全部 passage，證據取 pericope 標題；觸發詞只有 `pdf_terms`（附 PDF 位置）與 `external_aliases`；併掉的 id 列在 `retired`（`merged_into`）。契約只剩一份 `event_registry.json`（variant R2）。
- **K4**：詞表是 PDF 各層與註冊表的聯集（kg0 名與省略「‧」的寫法、divine_refs、查詢別名、事件觸發詞、書名）。每個詞帶全部候選目標、route 型別、可否路由與其規則、來源。
- **G-ROUTE**：從 text、kg0、events 與註冊表重編一次詞表，逐位元比對，並要求 `ragcommon.routing` 接受詞表與 `query_aliases.json`。它不跟舊 backend 比對（R2 沒有 live 比對），release 組裝時也會跑。
- **比對器**：只有 `ragcommon.routing` 一份，K4 閘門與 backend 共用。先遮全書名；其他書名寫法與詞一起掃。每個出現處都是候選，排除表否決的除外。由最長的先取，同長取最左，不與已取的重疊。
- **契約握手**：R2 的 backend 映像不接受 R1 build（詞表 v1、registry variant R1、沒有 `query_aliases.json`）。R1 映像也讀不了 v2 詞表。

之後：
- **release（S12）**：寫 `releases/{build_id}.json`（唯讀，同內容重寫是 no-op）；組裝時各層記錄閘門再跑一次（重讀 PDF 的 G-CONSERVE、G-XCHECK 與要 GPU 的 G-ENC 除外）。
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

`rag_meta.serving` 決定 backend 服務哪個 (build_id, 映像 digest)；backend 只在啟動時讀一次，改了要重啟才生效。

```bash
DIGEST=$(docker image inspect --format '{{.Id}}' bible_rag-backend:r1)
$RAGDATA promote --env staging --build <build_id> --image "$DIGEST"   # 印出新配對與先前配對
$RAGDATA promote --env staging --rollback                             # 回到上一筆
```

- 每次 promote 在同一交易內附加一筆到 `rag_meta.serving_history`（第一次 promote 時建表）；配對與目前相同時什麼都不寫。
- `--rollback`：把該 env 最新一筆未回滾的紀錄標為已回滾，serving 改回它的前一筆；再跑一次就再退一筆。最新一筆和 serving 不一致時拒絕，不做任何修改。
- 第一次 promote 的回滾（沒有前一筆）會刪掉該 env 的 serving 列，回到「沒有 build 在服務」；之後即可 unload 該 build。
- `--env prod` 一律要加 `--yes-prod`，否則拒絕（promote 與 `--rollback` 都是）。
- 2026-10-08 起 prod 服務 R1（`b20261008_6daa4f31`，映像 `bible_rag-backend:r1`）。legacy 已刪除，回滾只能翻回前一個 serving 配對。
- **換 prod 容器**（promote 之後；只動 backend，不碰 postgres、qdrant、ollama）：先把 `docker-compose.yml` 的 `image` 改成要服務的 tag，再
  ```bash
  docker compose -p bible_rag -f docker-compose.yml up -d --no-deps --no-build --pull never --wait --wait-timeout 300 backend
  curl -s localhost:8000/api/v1/health      # build_id 與 handshake.ok
  PYTHONPATH=packages scripts/.venv/bin/python evaluation/experiments/2026-10-08_r1/smoke20.py \
    http://localhost:8000 <build_id> ground_truth.v2.json <報告.json>
  ```
  回滾：`$RAGDATA promote --env prod --rollback --yes-prod`，把 `image` 改回前一個 tag，再跑同一個 `up`。不要 `docker compose build backend`、不要 `down`、不要 `--remove-orphans`。
- staging backend（:8002）見 `docker-compose.staging.yml` 的 `backend-stg`，映像由 `STG_IMAGE` 指定。它的 restart 是 `"no"`：握手不符就停在 exited，不會反覆重載模型；主機重開機後要重跑該檔開頭的 `up` 指令。

## 7. 清理被取代的 build

1. 確認它不在 `rag_meta.serving`，也不是回滾或比較的基準。
2. `$RAGDATA unload <build_id>`：只刪該 build 的 schema、`rag_meta.builds` 列、Qdrant collection 與 `contracts/<build_id>/`；serving 中的 build 一律拒絕，重跑可完成中斷的 unload。
3. 刪 `releases/<build_id>.json`，再刪 store 裡沒有任何剩餘 release 引用的層版本（連同 `.vectors` 附件目錄）。
4. 永不刪：`reference/`、`models/`、`tools/`、`/mnt/ollama-data/bible_rag_bak/`，以及 serving 中的 build 與它前一個配對（回滾用）。

## 8. 測試

四套測試都在 repo 根目錄跑。scripts 與 backend 的 venv 沒有 pytest，借 evaluation venv 的 pytest：
- `/mnt/ollama-data/bible_rag_store/tools/pytest_shim` 只放 pytest 相關套件的 symlink；
- `scripts/tests/run.sh` 自己建暫存 shim。

```bash
# ragdata＋packages：2,485 passed、5 skipped（PG 整合測試，要設 RAGDATA_TEST_PG_DSN），約 1.5 分鐘
env HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  scripts/.venv/bin/python -m pytest ragdata/tests packages/ragcommon/tests -q
# backend：219 passed（含 test_integration：暫時 PG 容器、資料目錄用 tmpfs）
PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  backend/.venv/bin/python -m pytest backend/tests -q
# scripts：12 passed（只剩 derive_ragcommon_data 與 harness）
scripts/tests/run.sh -q
# evaluation：482 passed
evaluation/.venv/bin/python -m pytest evaluation/tests -q
```

- 上面的數字是 2026-10-08 的結果。
- ragdata 的測試會讀 store 的 `reference/`（bible_md、canonical_full）、repo 的 6 卷 PDF，以及離線的 BGE-M3 tokenizer。
- backend 的 `test_integration.py` 用本機 `pgvector/pgvector:pg15` 映像起一個用完即刪的 PG（資料目錄是 tmpfs，不留匿名 volume；沒有映像就整檔 skip），載入 `backend/tests/fixtures/mini_build/`。這份 build 由 `backend/tests/fixtures/make_mini_build.py` 從 ragdata 的 mini release 產生；契約一變就要重產，否則 ragdata 的 `test_backend_mini_build.py` 會失敗。
- `test_staging_compose_restart.py`（staging compose 的 backend 服務一律 restart "no"）在 backend 套件裡。
- `test_routing_golden.py` 在 `backend/tests/fixtures/routing_r2_gt.json` 凍結、且 store 有它指名的 route 層之前一律 skip。route 層進 store 後，照 `make_routing_golden.py` 開頭的指令凍結。
