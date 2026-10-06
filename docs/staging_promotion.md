# Staging 與升版流程

> 從 [build_database.md](build_database.md) 拆出（2026-10-04，內容未刪減）。建庫各步驟（Step 0–10）、「執行順序」的重灌鏈與 Step 10.6 品質閘門都在該檔；本檔是 staging 建置與升版（R0–R5）的流程。文中的「計畫」指 [records/2026-10-04_kg_data_layer_fix_plan.md](records/2026-10-04_kg_data_layer_fix_plan.md)。

> 依據：[records/2026-10-04_kg_data_layer_fix_plan.md](records/2026-10-04_kg_data_layer_fix_plan.md) §3.5、§3.7（D1：staging 全量重建後升版，不做線上增量補丁）。每批升版都走 R0 → R1 → R2 → R3 → R4，出事走 R5。**第 0 批只做 R0、R1、R2**（在 staging 上做等價重建並列出 diff），不升版。

## 拓撲

| 庫 | production | staging | 隔離方式 |
|---|---|---|---|
| Neo4j | `bible_rag_neo4j`，bolt 7687／http 7474，volume `bible_rag_neo4j_data` | `bible_rag_neo4j_staging`，bolt 7688／http 7475，volume `bible_rag_neo4j_staging_data` | 另起容器（Neo4j community 只有單一使用者資料庫） |
| PostgreSQL | 資料庫 `bible_rag` | 資料庫 `bible_rag_staging`（同一個 `bible_rag_postgres` 容器） | 資料庫名 |
| Qdrant | entity collection `bible_entities` | `bible_entities_vN`（第 0 批用 `bible_entities_v2`；第 1 批 W1 用 `bible_entities_v3`，建議，待 Kay 確認，見 R0 第 8 項） | collection 名。段落 collection（`bible_embeddings`、`bible_embeddings_hybrid`）共用，不重建 |
| backend | `bible_rag_backend`，port 8000 | `bible_rag_backend_staging`，port 8001（R2 才起） | 另起容器，用現有 image |

`docker-compose.staging.yml` 定義 `neo4j-staging` 與 `backend-staging`：
- 一律疊在 docker-compose.yml 上，並且指名服務啟動：`docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d neo4j-staging`。
- 兩者都掛 `staging` profile，沒有指名服務的 `up -d` 不會帶起它們。
- 兩者都是 `pull_policy: never`，image 必須已在本機（`neo4j:5.15-community`，與正式版同一個 image；`bible_rag-backend:latest`）。
- neo4j-staging 的 APOC、帳密、記憶體設定與正式版相同，所以 staging 的 dump 可以原樣載入正式版（R3）。image 內建 `labs/apoc-5.15.0-core.jar`，啟動時不需下載。
- 可用環境變數改 port：`NEO4J_STAGING_BOLT_PORT`、`NEO4J_STAGING_HTTP_PORT`、`BACKEND_STAGING_PORT`。backend-staging 的 env_file 是 `.env` 加 `scripts/tools/staging.env`，PG 資料庫與 entity collection 和腳本讀同一份值；每批只在 staging.env 遞增 `bible_entities_vN`。neo4j-staging 要從 source 過 staging.env 的 shell 啟動（見該檔）。

## 環境變數契約

所有會連資料庫的腳本只從環境變數讀連線設定。`.env` 由 python-dotenv 載入，而且不覆寫已經存在的環境變數（`override=False`），所以在 shell 裡 `export` 的值優先於 `.env`。staging 就靠這一點：不改 `.env`，只在執行腳本的 shell 裡 `source scripts/tools/staging.env`（見「執行前檢查」）。

| 變數 | production（`.env`） | staging（`scripts/tools/staging.env`） | 備註 |
|---|---|---|---|
| `KG_TARGET` | 未設（等同 `prod`） | `staging` | 寫入型腳本的連線前防護（`scripts/kg_target.py`），見「執行前檢查」 |
| `NEO4J_URI` | `bolt://localhost:7687` | `bolt://localhost:7688` | |
| `NEO4J_USER`、`NEO4J_PASSWORD` | `.env` | 不變 | staging 容器的 `NEO4J_AUTH` 用同一組 |
| `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD` | `.env` | 不變 | 同一個 PG 容器 |
| `POSTGRES_DB` | `bible_rag` | `bible_rag_staging` | |
| `QDRANT_HOST` | `localhost` | 不變 | |
| `QDRANT_PORT` | 未設 | 不變 | 有設就優先於 `QDRANT_HTTP_PORT`（`.env` 與 compose 用的名稱）；兩者都沒設時用 6333 |
| `QDRANT_ENTITY_COLLECTION` | `bible_entities` | `bible_entities_v2`（之後各批：`bible_entities_vN`；W1 的 R0 遞增為 `bible_entities_v3`，待 Kay 確認） | |
| `QDRANT_COLLECTION`、`QDRANT_HYBRID_COLLECTION` | `bible_embeddings`、`bible_embeddings_hybrid` | 不設 | 只有 Step 4／4.1 讀；staging 不跑這兩步（`KG_TARGET=staging` 時兩者直接拒絕） |

程式碼裡其餘的值都只是變數沒設時的 fallback，與 docker-compose.yml 的預設值相同（localhost、5432、bible_rag、bible、bible_password、bolt://localhost:7687、neo4j、neo4j_password、6333）。

**盤點表**（2026-10-04；第 1A 批的列 2026-10-05 補上。✓ 表示該庫的連線設定全部讀環境變數；— 表示不連該庫）

| 腳本（scripts/ 下） | 步驟 | Neo4j：URI/USER/PASSWORD | PG：HOST/PORT/DB/USER/PASSWORD | Qdrant | 寫死與備註 |
|---|---|---|---|---|---|
| process_bible.py、validate_output.py、tools/check_step0.py | 0 | — | — | — | 不連資料庫 |
| extract_entities.py | 1 | — | — | — | 不連資料庫（LLM 走 `ENTITY_EXTRACT_*`） |
| generate_embeddings.py、generate_sparse_vectors.py | 2、2.1 | — | — | — | 不連資料庫 |
| import_postgres.py | 3 | — | ✓ | — | 無。會 TRUNCATE 六張表 |
| import_qdrant.py | 4 | — | — | HOST、PORT→HTTP_PORT、`QDRANT_COLLECTION` | 已修正：collection 原本寫死 `bible_embeddings`；port 原本只認 `QDRANT_HTTP_PORT`。預設刪除後重建 |
| import_qdrant_hybrid.py | 4.1 | — | — | HOST、PORT→HTTP_PORT、`QDRANT_HYBRID_COLLECTION` | 已修正 port。預設刪除後重建 |
| import_neo4j.py | 5 | ✓ | — | — | 無。預設清空整個資料庫 |
| relation_extraction/extract_relations.py（Neo4j 經 config.py 的 `Neo4jConfig.from_env`） | 6 | ✓ | ✓ | — | 無 |
| relation_extraction/relation_postprocess.py | 6.05 | — | — | — | 第 1A 批新增。離線，不連資料庫、不看 `KG_TARGET`：relations.jsonl → relations_clean.jsonl 加報告；`--rules none` 是 K8 的 staging-P1 對照組 |
| import_relations_neo4j.py | 6.1 | ✓ | — | — | 第 1A 批起只收 6.05 的 relations_clean.jsonl 與報告（sha256、列數、pp_version 不符就在連線前結束碼 2）；語意層已有邊就拒絕（結束碼 1）；`--replace` 只限 `KG_TARGET=staging`（`kg_target.require_staging`），整層刪除與寫入在同一個交易 |
| relation_extraction/desc_generator.py | 7 | ✓（`Neo4jConfig.from_env`） | — | — | 無。產生與 replay 都在連線前呼叫 `kg_target.assert_target("neo4j")` |
| embed_entities.py | 8 | ✓ | — | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 已修正 port。`--qdrant-host`、`--qdrant-port` 可再覆寫 |
| import_tsk_crossrefs.py | 9 | ✓ | — | — | 無 |
| backfill_aliases.py | 10.1 | ✓ | — | — | 無（只寫 Neo4j） |
| cleanup_noise_entities.py | 10.2 | ✓ | ✓ | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 已修正 port，以及 PG 的 user/password fallback：原本是 `postgres`／空字串，沒有 .env 時連不上，而連不上時只印警告、靜默跳過 PG 同步 |
| backfill_event_relations.py | 10.3（legacy） | ✓ | — | — | 第 1A 批退出預設鏈：沒有 `--legacy-cooccurrence` 時結束碼 2、不連庫；只有 K8 的 staging-P1 對照組與重現論文數字才跑 |
| backfill_head_events.py | 10.4 | ✓ | ✓ | HOST、PORT→HTTP_PORT（`qdrant_endpoint`）；collection 取自 embed_entities（`QDRANT_ENTITY_COLLECTION`） | 無 |
| backfill_manual_patches.py | 10.5 | 經 backfill_head_events | 經 backfill_head_events | 經 backfill_head_events（`get_qdrant`、`reembed_qdrant`） | 無 |
| export_event_registry.py | 10.6、export | 經 backfill_head_events.get_neo4j | — | — | 無。輸出檔固定為 backend/data/event_registry.json（git 追蹤的檔案，不是資料庫） |
| backfill_verse_mentions.py | 退役 | ✓ | — | — | 不在鏈中 |
| tools/export_live_state.py | R0 | ✓（`Neo4jConfig.from_env`；只用 read 交易） | — | — | 無（第 0 批新增）。`--promote` 不連庫 |
| check_identity.py | 10.6、R4 | ✓ | ✓ | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 第 0 批新增，唯讀。`--target staging` 只讀 shell 變數（預設 bolt://localhost:7688、bible_rag_staging；Qdrant 沒有預設），解析到 production 會拒絕；`--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、值與 .env 不同、7688、bible_rag_staging）時拒絕 |
| validate_kg.py | 10.6、R4 | 經 check_identity 的 `--target` 解析 | 同左 | 同左 | 第 0 批新增，唯讀；兩個方向的守門同 check_identity |
| tools/diff_kg.py | R2 | `--a`、`--b` 各選 prod／staging（預設 `--a prod --b staging`），經 check_identity 的 `--target` 解析 | — | — | 第 0 批新增，唯讀，只比 Neo4j；`--allow` 讀允許清單，`--fail-on-unused`（第 1B 批新增）讓沒用到的條目也算失敗。`--merge-out`（第 1B 批新增）把多個 `--allow` 片段合成一份允許清單，不連庫；`--sha-out` 另把合併檔的 sha256 寫成 sha256sum 格式的登記檔。prod 端會拒絕 staging 的 shell，只能在乾淨的 shell 跑，staging 端此時用預設的 bolt://localhost:7688（改過 `NEO4J_STAGING_BOLT_PORT` 時無法指定） |
| tools/xref_probe.py | R2、R3、R4 | `predict`、`fingerprint` 的 `--target` 經 check_identity 解析（READ session）；`allow` 固定讀 prod | — | — | 第 1B 批新增，唯讀。`deploy-guard` 只對 backend 容器做 `docker exec … cat`；`seeds`、`expect`、`compare` 不連庫 |
| tools/check_merged_inputs.py | W1 鏈（取代 1） | — | — | — | 第 1A 批新增，不連資料庫：output/ 兩個實體檔的 sha256 對 `output/frozen/grounded_manifest.json` |
| tools/check_w1_registration.py | W1 鏈（6.05 之後、3 之前） | — | — | — | 第 1A 批新增，不連資料庫，只讀檔案與 git：登記檔都已 commit 且未改動，三個期望檔的內容是各自工具寫出的格式（residuals_expected.json 經 residuals_expect 自己的載入檢查，要有 `mentions_props` 與兩邊的逐邊摘要，否則 INVALID）、合併允許清單的 sha256 等於登記值、6.05 的輸出是登記的那一份；不過就停，不跑 Step 3 |
| tools/check_edge_set.py | 10.6、R2、R4 | `--target` 經 check_identity 解析（READ） | — | — | 第 1A 批新增，唯讀：語意層對 6.05 報告扣掉 10.2，`--expect` 再對登記的期望檔 |
| tools/kin_review.py | K9（W1 第 2 步之前） | — | — | — | 第 1A 批新增，不連資料庫：讀 relations_clean 與 output/ 的實體、提及、段落、描述快取 |
| tools/relations_expect.py | E1（W1 第 2 步之前） | `--a`（預設 prod）經 check_identity 解析（READ） | — | — | 第 1A 批新增，唯讀，寫期望檔與允許清單片段。prod 端會拒絕 staging 的 shell，在乾淨的 shell 跑 |
| tools/residuals_expect.py | E1（W1 第 2 步之前）、R2（`--check`） | `--a`、`--b` 經 check_identity 解析（READ） | — | — | 第 1A 批新增，唯讀。產生期望檔時 b 必須仍是第 0 批的 staging（有帶 source 的語意邊就拒絕）；`--check` 只讀兩邊的 MENTIONS，兩邊的逐邊摘要與逐屬性條數都要等於登記檔，不寫檔。都在乾淨的 shell 跑 |

## 執行前檢查（每次在 staging 跑寫入步驟之前）
Step 3 會 TRUNCATE、Step 5 會清庫、8a／8b 的 `--recreate` 會刪 collection；變數沒指對，被清掉的就是 production。staging 的變數一律 source 現成的檔案，不要手打：
```bash
source scripts/tools/staging.env   # 設好 KG_TARGET=staging 與上表 staging 欄的全部變數
uv run --project scripts python scripts/kg_target.py --require-staging neo4j postgres qdrant   # 結束碼 0 才往下走
```
- 程式端防護 `scripts/kg_target.py`：寫入型腳本在連線前呼叫 `kg_target.assert_target(<要寫的庫>)`。`KG_TARGET=staging` 時，只要有一個要寫的庫的設定沒設（腳本會退回 `.env` 的 production 值），或解析到 production（Neo4j port 7687，沒寫 port 也算；`bible_rag`；`bible_entities`；以及 `.env` 寫的值），就在連線前 SystemExit。`KG_TARGET` 沒設時行為與以前相同，所以沒有 source staging.env 的 shell 不受保護。
- 第二行的 `--require-staging` 做同一組三庫檢查，另外要求 `KG_TARGET=staging`：新開的終端機忘了 source、或任一庫沒有隔離時結束碼 1；通過時結束碼 0，並印出腳本實際會寫入的三個端點（Neo4j URI、PG 主機與資料庫、Qdrant 主機與 collection），要逐一看過。舊版文件的 `python -c '…assert_target(…)'` 在沒 source 的 shell 會假性通過（`KG_TARGET` 沒設時 assert_target 不檢查、直接回傳 prod），不要再用。
- staging 的變數只放在跑腳本的 shell，**不要在這個 shell 裡對 production 服務下 `docker compose up`**：docker-compose.yml 會把 `${POSTGRES_DB}` 插值進 production 的 postgres 服務，帶著 `POSTGRES_DB=bible_rag_staging` 去 `up` 它，compose 會判定設定已變而重建 production 的 postgres 容器。指名 `neo4j-staging`、`backend-staging` 不受影響（backend-staging 刻意只依賴 neo4j-staging）。

## R0 備份（每批升版前；第 0 批也要做）
0. **第 1 批 W1：先把兩條線合進主 checkout。** 1A、1B 在兩個 worktree 實作，`w1/1b` 已合併進 `w1/1a`；R0–R5 則全部在主 checkout `/home/kenzx0521/Bible_RAG` 執行：compose 的專案名取自目錄名，只有這裡的 image 與 volume 是 production 的，deploy-guard 與 check_w1_registration 比對的也是這個 checkout 的 HEAD。所以 R0 的第一件事，是在主 checkout 目前的 branch `feat/graph-strategy-gating` 上合併 `w1/1a`。`git tag kg-pre-batch1-w1` 打在合併前的 commit 上，也就是合併 commit 的第一個 parent（2026-10-06 是 `f06cc7b`，W1 交接紀錄那一個；之前若又有 commit，就是當時的 HEAD）。第一段只做一次（tag 已存在就停）；合併有衝突時，解決並 commit 之後直接跑第二段：
   ```bash
   cd /home/kenzx0521/Bible_RAG
   (
   set -eu -o pipefail
   test "$(git rev-parse --show-toplevel)" = /home/kenzx0521/Bible_RAG
   test "$(git branch --show-current)" = feat/graph-strategy-gating
   PRE=$(git rev-parse HEAD)
   git tag kg-pre-batch1-w1 "$PRE"
   git merge --no-ff --no-edit w1/1a
   echo "kg-pre-batch1-w1 = $PRE, merged at $(git rev-parse HEAD)"
   )
   ```
   第二段可以重跑：確認合併 commit 帶著 `w1/1b`、第一個 parent 就是 tag，跑三套測試，最後 `git status --porcelain` 必須是空的，唯一允許的是 `?? docker-compose.yml.bak-20260730-160725`（2026-07-30 的手動備份，與 W1 無關）。backend 的 venv 沒有 pytest，與 `scripts/tests/run.sh` 一樣借 evaluation 的：
   ```bash
   (
   set -eu -o pipefail
   test "$(git rev-parse --show-toplevel)" = /home/kenzx0521/Bible_RAG
   git merge-base --is-ancestor w1/1b HEAD
   test "$(git rev-parse kg-pre-batch1-w1)" = "$(git rev-parse HEAD^1)"
   scripts/tests/run.sh -q
   SHIM=$(mktemp -d)
   trap 'rm -rf "$SHIM"' EXIT
   for p in pytest _pytest pluggy iniconfig pygments py.py; do ln -s "$PWD/evaluation/.venv/lib/python3.12/site-packages/$p" "$SHIM/$p"; done
   PYTHONPATH=$SHIM backend/.venv/bin/python -m pytest backend/tests -q
   (cd evaluation && uv run --offline python -m pytest tests -q)
   S=$(git status --porcelain)
   case "$S" in ''|'?? docker-compose.yml.bak-20260730-160725') ;; *) printf '%s\n' "$S"; exit 1;; esac
   echo "W1 checkout ready at $(git rev-parse HEAD)"
   )
   ```
   印出最後一行才往下。之後 R0–R5 都在這個 checkout、從這個合併 commit 起跑，不在 worktree 裡跑任何一步；同一個 branch 上只再多出本文要求的 commit（例如第 8 項的 staging.env、R2 的事前登記檔、R4 之後的 ratchet）。W1 紀錄記下 tag 與合併 commit 的 sha，以及三個時點的 `git rev-parse HEAD`：事前登記的檔 commit 之後（R2「W1 的交叉引用檢查」第 1 項）、重建開始時（R1 第 5 項）、R2 建 `:w1` image 時（同一節第 3 項寫進 `bak/$D/images/backend_w1.head`）。
1. `git tag kg-pre-<批次>`（例：`kg-pre-batch0`）作為 run-of-record。第 1 批 W1 的 tag 已在第 0 項打在合併前的 commit 上，這裡不再打。
2. 三庫備份：照 [bak/README.md](../bak/README.md)「重新備份」建 `bak/<日期>/`。PG 做 `pg_dump -Fc` 加 globals；Qdrant 三個 collection 各做 snapshot；Neo4j 先 `docker stop -t 60`，再 `neo4j-admin database dump`（停機約 1 分鐘）。
3. 另存 PG 兩張實體表的 plain SQL，R5 換表回滾時使用：
   ```bash
   D=$(date +%Y%m%d)
   docker exec bible_rag_postgres pg_dump -U bible -d bible_rag -t entities -t entity_mentions \
     > bak/$D/postgres/entity_tables.sql
   ```
   `D` 是 R0 的日期，之後各步都沿用：每開一個 shell（staging 的與乾淨的都一樣）先 `export D=<R0 的日期>`，不要再以 `$(date +%Y%m%d)` 重算，隔天重算會把證據分散到兩個目錄。失敗即停的區塊開頭的 `${D:?}` 只擋沒設，擋不了設錯。
4. 第 0 批一次性（在沒有 source staging.env 的 shell 執行，讀的是 production）。要在第 0 批程式碼 commit 之後做，manifest 記錄的 commit 才對得上程式碼：
   - 把只存在 live 的狀態匯出到 `output/frozen/live_state/<YYYYMMDD>/`：descriptions.jsonl（描述快取的種子）、entities.jsonl（labels、canonical、aliases）、curated_mentions.jsonl、manifest.json，查詢都在 read 交易內。再以 `--promote` 把種子複製成正式快取 `output/frozen/descriptions.jsonl`（不連庫；先比對 manifest 的 sha256 與快取格式；已存在時沒有 `--force` 就拒絕）。之後每次重灌的 Step 7 都 replay 這一份：
     ```bash
     uv run --project scripts python scripts/tools/export_live_state.py --dry-run
     uv run --project scripts python scripts/tools/export_live_state.py
     uv run --project scripts python scripts/tools/export_live_state.py --promote --out-dir output/frozen/live_state/<YYYYMMDD>
     ```
   - 以 `extract_entities.py --stage freeze-grounded` 凍結 grounded 半邊，再跑 `--stage ner`（約 30 分鐘）產生帶 manifest 的 NER 半邊，最後 `--stage merge --dry-run` 確認 log 是「NER half identical」（見 [build_database.md](build_database.md) Step 1）。
5. 打包 LLM 產物、K0 的 5 個產物、NER 半邊與 `output/frozen/`。output/ 被 gitignore，bak/20260715 也沒有收這些，現在磁碟上只有一份（計畫 §3.5.1）。K0 檔也要收：重灌鏈的 Step 0 會先覆寫它們才跑 sha 閘門，閘門報漂移時要有原檔可比。ner_* 要連同 `ner_manifest.json` 一起收：merge 會拒絕沒有 manifest 的 NER 半邊：
   ```bash
   FILES="relations.jsonl relations_checkpoint.jsonl relations_unclassified.jsonl entities.jsonl entity_mentions.jsonl cross_references_tsk.txt"
   FILES="$FILES books.jsonl chapters.jsonl pericopes.jsonl chunks.jsonl embedding_queue.jsonl frozen"
   FILES="$FILES ner_entities.jsonl ner_mentions.jsonl ner_manifest.json"
   mkdir -p bak/$D/output
   (cd output && find $FILES -type f -print0 | sort -z | xargs -0 sha256sum) > bak/$D/output/MANIFEST.sha256
   tar -C output -czf bak/$D/output/llm_artifacts.tgz $FILES
   ```
6. 最後照 bak/README.md 重新產生 `bak/$D/SHA256SUMS`。bak/README.md 目前還沒有第 3、5 項，以本節為準。
7. backend 的回滾 image 不能只靠 `docker tag`：沒有容器引用的 image，即使有 tag 也會被 `docker image prune -a` 刪掉（2026-10-05 已發生過，見 W1 交接紀錄 `docs/records/2026-10-05_kg_w1_handoff.md` §4）。第 1 批 W1 在「W1 升版第 1 步」換 image 之前做：記下 prod 正在跑的 image id、打 tag、用一個停著的容器釘住、`docker save` 到 `bak/$D/images/`，sha256 補進 `bak/$D/SHA256SUMS`。
8. 第 1 批 W1 的 staging entity collection（決定 O7，建議，待 Kay 確認）：在 E1（R2「W1 的關係層檢查」第 2 項的兩次 validate_kg 與 residuals_expect）跑完之後，把 `scripts/tools/staging.env` 的 `QDRANT_ENTITY_COLLECTION` 從 `bible_entities_v2` 遞增到 `bible_entities_v3` 並 commit（每批遞增 vN）。v2 是第 0 批的 staging 建置，留給 W2 當第 0 批的對照；W1 重建的 8a、8b `--recreate` 只動 v3，W2 順延用 v4。W1 升版不動 prod 的 Qdrant 與 `.env`。v3 建好後要與 `bible_entities_detB` 逐點相同，見 R2「W1 的關係層檢查」第 4 項。

## R1 staging 建置
1. 起 staging Neo4j（第一次會建立空的 volume），並確認 APOC 可用（Step 6.1 與 10.x 依賴它）：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d neo4j-staging
   docker exec bible_rag_neo4j_staging bash -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#*/}" "RETURN apoc.version()"'
   ```
2. 建 PG staging 資料庫。schema 用 scripts/db/schema.sql（2026-10-04 已比對，entities 與 entity_mentions 的定義與 production 相同）。`dropdb --if-exists` 清掉上一次的 staging 庫，**只對 staging 執行**；在那之前先停掉 backend-staging：它連著 bible_rag_staging（例如 W1-0 起的 w1det），沒停時 dropdb 會以「being accessed by other users」失敗：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging
   docker exec bible_rag_postgres dropdb -U bible --if-exists bible_rag_staging
   docker exec bible_rag_postgres createdb -U bible bible_rag_staging
   docker exec -i bible_rag_postgres psql -U bible -d bible_rag_staging -v ON_ERROR_STOP=1 < scripts/db/schema.sql
   ```
   第 1 批 W1：這一項排在 E1 之後（R2「W1 的關係層檢查」第 2 項）。
3. Qdrant 不需事先建立：8a 的 `embed_entities.py --recreate` 會建出 `bible_entities_vN`；同一個 vN 重跑時，`--recreate` 會清掉上一次 staging 的點。
4. `source scripts/tools/staging.env`，並通過執行前檢查。
5. 依 [build_database.md](build_database.md)「執行順序」的重灌鏈逐步執行（Step 4／4.1 跳過）。第 1 批 W1：開始之前要先完成事前登記，也就是 R2「W1 的交叉引用檢查」第 1 項的期望檔與片段、R2 第 2 項的合併允許清單（與 `--sha-out` 寫出的 sha256 檔），以及 R2「W1 的關係層檢查」第 1、2 項的 K9 標註與 1A 的期望檔、片段（residuals_expect 要趁 7688 還是第 0 批的建置時讀；E1 還要排在 R0 第 8 項與本節第 2 項之前）。開始重建時把 `git rev-parse HEAD` 記進 W1 紀錄（R0 第 0 項）。關卡是重灌鏈在 6.05 之後、Step 3 之前跑的 `scripts/tools/check_w1_registration.py`：登記檔都已 commit 且沒有改動、三個期望檔的內容是各自工具寫出的格式（例如 `residuals_expected.json` 要有 `mentions_props` 與兩邊的逐邊摘要，否則 R2 的 `--check` 結束碼 2）、合併檔的 sha256 等於登記值、6.05 的輸出就是登記的那一份，結束碼不是 0 就停。這一關不能跳過：Step 5 清空 7688 之後，residuals_expect 拒讀，殘差期望檔再也產生不出來。重建時 validate_output 之後的 `xref_probe expect`（R2 該項的最後一段）只重算比對，不重新登記；6.1 之後加跑兩次 `--replace`（「W1 的關係層檢查」第 3 項）。K8 的 staging-P1 對照組不在這裡建，R4 之後才建（R4「W1 的 K8 對照組」）。
6. 每一批第一次 staging 重建都要實測各步耗時並填入下表（計畫 §8）：

   | 步驟 | 實測耗時 |
   |---|---|
   | 第 0 批：0、1(merge)、3、5、6.1、8a、9、10.1–10.5、7(replay)、8b、10.6、export --check | 2026-10-04 第 0 批實測：0=5s、3=5s、5=28s、6.1=1s、8a=26s、9=6s、10.1–10.5=19s、7=1s、8b=24s、10.6=6s，合計約 2 分鐘；`--stage ner` 另需 34 分鐘（1(merge) 本身 <10s） |
   | 第 1 批 W1：0（含 check_step0、validate_output）、xref_probe expect、check_merged_inputs、6.05（兩次）、check_w1_registration、3、5、6.1（再加 `--replace` 兩次）、8a、9（兩次）、10.1、10.2、10.4、10.5、7(replay)、8b、10.6、export --check | W1 第 2 步實測後填入，並記進 W1 紀錄 |

## R2 驗證
1. 10.6 依該批的判準通過（見 [build_database.md](build_database.md) Step 10.6），而且 `export_event_registry.py --check` 結束碼 0。
2. 通過該批的驗證門檻（計畫 §4；第 1 批起見 [records/2026-10-04_kg_data_layer_fix_plan_batches.md](records/2026-10-04_kg_data_layer_fix_plan_batches.md)）。與 live 的 diff 要逐項列出並解釋（預期中的差異見 [build_database.md](build_database.md) Step 10.6）。staging 對 live 的比對用 diff_kg，在**沒有 source staging.env 的乾淨 shell**（新開的終端機）跑；10.6 的三項（validate_kg、check_identity、第 1A 批起的 check_edge_set）則要在 staging 的 shell 跑：
   ```bash
   # 第 0 批（歷史紀錄，見下方「歷史允許清單」）
   uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch0.yaml --json
   # 第 1 批 W1：一份合併的允許清單，沒用到的條目也算失敗
   sha256sum -c config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256   # 事前登記的 sha256；結束碼 0 才跑下一行
   uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch1w1.yaml --fail-on-unused --json
   ```
   - `--a`、`--b` 各選 prod 或 staging（預設就是 prod 對 staging），只比 Neo4j：labels、relationships、ee_edges（`TYPE phase=P source=S`）、mentions、xrefs、xref_provenance（`source=S curated=C tsk=T` 的邊數，第 1B 批新增）、entity_ids、descriptions（逐字）、aliases（集合）、mention_count（逐實體，第 1B 批新增）、registry。prod 端的守門會拒絕還帶著 staging 設定的 shell（結束碼 1，安全的失敗）。
   - **歷史允許清單不能再當閘門重跑**：`kg_diff_allow_batch0.yaml` 與更早的清單早於 xref_provenance、mention_count 兩段。現在用 batch-0 的清單重跑上面第一行，會因為 mention_count 的 4 筆 K10 殘差不在清單內而結束碼 1；這些檔案只記錄當時的判定。
   - W1 的合併清單 `config/kg_diff_allow_batch1w1.yaml` 由工具產生的片段合成，不手抄：1A 的 `relations_allow.yaml`、`residuals_allow.yaml` 與 1B 的 `xref_allow.yaml`，都在 `config/kg_expect/batch1_w1/`。合併在 YAML 層做，不可用 `cat` 串接：每個片段都是完整的 YAML 文件，各有 `version: 1` 與 `allow:`，串起來後一般的 YAML 載入只留最後一個 `allow:`，其他片段無聲消失（diff_kg 現在遇到重複的鍵直接報錯）。用 `--merge-out` 合併：逐一載入片段，把各自的 `allow` 依序接在同一個 `version: 1` 底下，跨片段重複的 section 與 key 直接報錯，核對合併後的條數等於各片段之和，最後印出合併檔的 sha256。不連庫，任何 shell 都可以跑：
     ```bash
     uv run --project scripts python scripts/tools/diff_kg.py --merge-out config/kg_diff_allow_batch1w1.yaml \
       --sha-out config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256 \
       --allow config/kg_expect/batch1_w1/relations_allow.yaml --allow config/kg_expect/batch1_w1/residuals_allow.yaml \
       --allow config/kg_expect/batch1_w1/xref_allow.yaml
     ```
     合併檔在 [第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §1「W1 步驟」第 2 步（staging 重建）之前組好，印出的 sha256 記進 W1 紀錄。合併檔本身 R4 之後才與 ratchet 放同一個 commit，所以事前登記的是它的 sha256：`--sha-out` 把印出的那一行寫成 `config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256`（sha256sum 格式），與期望檔、片段一起在第 2 步之前 commit；重灌鏈的 check_w1_registration 在 Step 3 之前核對它，也核對合併檔就是這三個片段依序合併的結果。R2 用它跑（先以 `sha256sum -c config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256` 核對），第 4 步經 Kay 核可；看過 staging 的 diff 之後不可再改（計畫 §3）。一筆差異只會記在第一個比對到的條目上，被前面條目遮住的條目在 `--fail-on-unused` 下也算沒用到，所以片段不可重疊。1B 的片段由下方「W1 的交叉引用檢查」第 1 步的 `xref_probe.py allow` 從期望檔與 prod 的 profile 算出，只含 relationships `CROSS_REFERENCES`、xrefs、xref_provenance 三段，每個不同的鍵一條 exact `delta`。mention_count 段的 4 筆 K10 殘差（第 0 批就有，加了這一段才看得到）只來自 1A 的 `residuals_allow.yaml`，1B 的片段不含。1A 的兩個片段由下方「W1 的關係層檢查」第 2 項的 relations_expect、residuals_expect 產生。
   - 允許清單放 `config/kg_diff_allow_<批次>.yaml`（git 追蹤）。第 0 批是在 R2 依實際 diff 建立、與該批紀錄一起 commit；第 1 批起預先登錄，不依 R2 的 diff 建立（見上一項）。檔案只有 `version: 1` 與 `allow` 清單；每條要有 section、key（glob）、reason，計數類與 mention_count 最多再加一個 `delta`（b − a）或 `max_abs_delta`（其他段加 bound 直接報錯）；未知欄位（例如拼錯的 bound）或型別不對直接報錯，同一個 section 下逐字相同的 key 出現兩次（不論 bound）也直接報錯，片段間的重複在 `--merge-out` 合併時就擋下，不會拖到 R2 才以沒用到的條目出現（只擋逐字重複，互相涵蓋的 glob 仍要人工確認）；同一個 mapping 裡重複的鍵（同一條寫了兩個 `delta`，或 `cat` 串起來的兩個 `allow:`）也直接報錯。格式見 `diff_kg.py --help`。不在清單內的差異結束碼 1；沒用到的條目會列出，要刪。第 0 批不可放行 descriptions：stale 必須是 0。

   第 0 批的門檻：
   - registry 是 33 個事件；
   - 三庫的 id 集合差為 0（`check_identity --target staging --fail-on id`）；
   - E–E 各 phase 的邊數與 live 相同（diff_kg；允許的差異逐項列出）；
   - 描述 replay 後，staging 與 live 逐字相同（Step 7 報告的 stale、missing 為 0，且 diff_kg 的描述逐字比對無差異）；
   - H1、H2、H7 通過。

   第 1 批 W1 的門檻見下方「W1 的交叉引用檢查」（1B）與「W1 的關係層檢查」（1A）。
3. 起指向 staging 的 backend，跑評估。backend-staging 只依賴 neo4j-staging，postgres、qdrant、ollama 用正在跑的 production 服務。加 `--no-deps`：compose 只動 backend-staging，不去收斂它依賴的 neo4j-staging（R1 已經起好；理由見 R5 開頭）；`--wait` 等 healthcheck 通過（start_period 120 秒）才返回，沒起來就結束碼不是 0，評估不會打到還沒好的 backend；`--no-build` 不建 image：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging
   curl -f http://localhost:8001/api/v1/health
   ```
   - evaluation 端在每個指令前面加 `BACKEND_URL=http://localhost:8001`（環境變數優先於 evaluation/.env），不要 `export`：shell 裡留著 8001 時，之後沒寫 BACKEND_URL 的指令（例如 A/B 的對照組）會默默打到 :8001，兩邊又是同一個 image，xref_ab_slice 也看不出來。W1 的每個 quick_retrieval_eval 都寫明 BACKEND_URL，對照組與煙霧測試是 `http://localhost:8000`。先跑 quick_retrieval_eval（100 題），有差異再跑 500 題（計畫 §6）。
   - 第 0、1 批的 registry 與字典都不變，硬閘門是：預設組態 500 題的 sources 與 prompt 逐位相同（計畫 §6.3）。
   - backend pytest（含 test_event_registry）照常在 host 的 backend venv 跑，不依賴 staging。
   - backend-staging 用現有 image。要測新的 backend 程式碼，先建 image：`docker compose build backend` 只更新 image，不動正在跑的 production 容器，但會覆寫 production 用的 `latest`，之後任何對 production 的 `up -d` 都會換上新 image。所以第 1 批起改建另一個 tag，做法見下方「W1 的交叉引用檢查」第 3 項。
   - 驗完停掉：`docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging`。

### W1 的交叉引用檢查（第 1B 批）
「模擬等於實測」：`xref_probe.py` 離線算出 backend 應該回傳的 xref 候選，每列是 [id, hop, curated, weight]；backend 容器內的 `probes.xref_measure` 經真正的 retriever 量出同一批種子的結果，兩者逐列比對。種子是 2,779 個段落各當一次單一種子（多跳與 legacy 一跳），加上 262 題的代理種子集，共 5,820 個 key。compare 另外檢查 12 條哨兵：votes ≥ 999 的 3 對 TSK 邊，兩個方向都必須是 curated false、權重 0.60。產物放 `bak/$D/xref_probe/`（`D` 沿用 R0 的日期；pred／measured 每個約 2 MB，expected_edges.jsonl 約 20 MB），sha256 記進 W1 紀錄。規劃時的獨立 oracle 見 [w1_1B 歸檔](records/2026-10-04_kg_fix/batch1/w1_1B/README.md)，大檔在 `bak/20261005_w1_1b_evidence/`。本節與 R3、R4、R5 的 W1 段落裡，「第 1 批計畫」指 [records/2026-10-04_kg_batch1_plan.md](records/2026-10-04_kg_batch1_plan.md)。

1. **事前登記（第 1 批計畫 §1「W1 步驟」第 2 步（staging 重建）之前）**：期望檔是離線重放 Step 5 與 Step 9 會建出的 CROSS_REFERENCES，輸入只有 Step 0 的輸出與 TSK 檔，不連庫。先照 [build_database.md](build_database.md) Step 0 跑 process_bible、check_step0、validate_output（都不寫庫），三者結束碼都是 0 之後才產生期望檔。期望檔不可事後回填，看過 staging 的 diff 之後也不可再改（第 1 批計畫 §3）：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   mkdir -p bak/$D/xref_probe config/kg_expect/batch1_w1
   uv run --project scripts python scripts/tools/xref_probe.py expect --output-dir output --tsk output/cross_references_tsk.txt \
     --out config/kg_expect/batch1_w1/xref.json --edges-out bak/$D/xref_probe/expected_edges.jsonl
   uv run --project scripts python scripts/tools/xref_probe.py seeds --pericopes output/pericopes.jsonl \
     --questions docs/records/2026-10-04_kg_fix/batch1/inputs/bench/questions_table.json --out bak/$D/xref_probe/seeds.json
   uv run --project scripts python scripts/tools/xref_probe.py predict --seeds bak/$D/xref_probe/seeds.json \
     --edges bak/$D/xref_probe/expected_edges.jsonl --out bak/$D/xref_probe/pred_new.json
   uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_new.json \
     --measured bak/20261005_w1_1b_evidence/pred_new.json
   echo 'xref expectation and oracle compare ok'
   )
   ```
   預期（2026-10-05 以 W1 的 Step 0 實跑）：expect 印出 `curated_rows 932, attached 924, curated_without_tsk 8, pure_tsk 249,434, total 250,366, votes_edges 250,358` 與 `fingerprint e522411e13c8e867cad36190c9002813b3da9a7d165ef5435d5cc161eff3775f`；seeds 為 5,820 keys（sha256 `674537f3…`）；pred_new 與歸檔的 oracle 比對結束碼 0。

   接著由期望檔產生 1B 的允許清單片段（R2 第 2 項合併清單的一部分）。`allow` 唯讀 prod，跟 diff_kg 一樣要在**乾淨的 shell** 跑：
   ```bash
   uv run --project scripts python scripts/tools/xref_probe.py allow --expect config/kg_expect/batch1_w1/xref.json \
     --out config/kg_expect/batch1_w1/xref_allow.yaml
   ```
   預期（2026-10-05 以同一份期望檔對 prod 實跑）：10 條，relationships `CROSS_REFERENCES` 1 條、xrefs 2 條、xref_provenance 7 條，沒有 mention_count。片段開頭的註解記下期望檔的 sha256 與 fingerprint（不記路徑，同一份期望檔與 prod 重跑得到相同的位元組）；要改就重跑，不手改。與 1A 片段的合併見 R2 第 2 項。

   期望檔與片段跟 1A 的期望檔一樣，在第 2 步之前 commit，commit 之後的 `git rev-parse HEAD` 記進 W1 紀錄（R0 第 0 項）。`xref.json`、`xref_allow.yaml` 與合併檔的 sha256 都記進 W1 紀錄；合併檔要到 R4 之後才 commit，事前登記的是 `--sha-out` 寫出的 sha256 檔（R2 第 2 項）。第 4 步經 Kay 核可的就是這些已登記的檔，不是看過 staging 之後重產的版本。

   重建時（第 2 步）Step 0 會再跑一次。Step 0、check_step0、validate_output 都通過後、Step 5 之前，把期望檔重算到 `bak/`，再與登記的那份逐位元比對。expect 對同一份輸入的輸出逐位元相同（2026-10-05 重跑兩次），所以不同就表示 Step 0 的輸出或 TSK 檔變了：停下來查，不可覆寫登記的期望檔：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   uv run --project scripts python scripts/tools/xref_probe.py expect --output-dir output --tsk output/cross_references_tsk.txt \
     --out bak/$D/xref_probe/xref_rebuild.json
   cmp bak/$D/xref_probe/xref_rebuild.json config/kg_expect/batch1_w1/xref.json
   echo 'xref expectation unchanged'
   )
   ```
2. **Step 9 連跑兩次**：兩次都在重建時跑，第二次緊接著第一次、在 10.1 之前（staging 的 shell；[build_database.md](build_database.md) 重灌鏈第 9 列與 Step 9）。R2 不再跑 Step 9，只核對重建時 `tee` 下來的兩次輸出（`bak/$D/step9_run1.log`、`bak/$D/step9_run2.log`，指令見 [build_database.md](build_database.md) Step 9，同樣的檢查重建時已跑過一次）：第二次是 `created 0`，兩次同一個 `fingerprint:`。接著對 staging 比對期望檔（唯讀），結束碼必須是 0（指紋與 xref_provenance 計數都要相同）。沒有印出最後一行就停：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   grep -q '^After: created 0,' bak/$D/step9_run2.log
   F=$(grep '^fingerprint: ' bak/$D/step9_run1.log)
   grep -qxF "$F" bak/$D/step9_run2.log
   uv run --project scripts python scripts/tools/xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json
   echo 'step 9: created 0, same fingerprint, expect matched'
   )
   ```
3. **backend-staging 換成 W1 HEAD 建的 image**（D3 也在這個 image 上跑）。W1 HEAD 建成另一個 tag，不覆寫 production 正在用的 `bible_rag-backend:latest`（W0 紀錄的做法），用一個不進 git 的 compose override 指定 tag。deploy-guard 比對的是本 checkout 在 HEAD 已提交的檔案（`git show HEAD:`，不看工作目錄），所以要在建 image 的同一個 checkout 跑，而且先 commit 再建 image（GUARD_FILES 這三個檔沒提交的改動即使建進 image 也會被擋下；其他檔的改動 deploy-guard 看不到，所以建 image 前工作目錄要乾淨）。第一段建 image、記下 id 並換上 backend-staging，是子 shell 加 `set -e`（同升版第 1 步）：`D` 沒設、`:w1` 不存在（id 檔是空的）、healthcheck 沒在 300 秒內通過（`--wait`，D3 與 ep_w1 緊接著打這個容器）或 staging 容器跑的不是這個 id，都在印出最後一行之前停下：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   printf 'services:\n  backend:\n    image: bible_rag-backend:w1\n  backend-staging:\n    image: bible_rag-backend:w1\n' > /tmp/w1_image.yml
   docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml build backend
   mkdir -p bak/$D/images
   docker image inspect -f '{{.Id}}' bible_rag-backend:w1 > bak/$D/images/backend_w1.id
   test -s bak/$D/images/backend_w1.id
   git rev-parse HEAD > bak/$D/images/backend_w1.head
   docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging
   test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$(cat bak/$D/images/backend_w1.id)"
   echo 'staging runs :w1'
   )
   ```
   沒有印出 `staging runs :w1` 就停，不跑下面的量測：
   ```bash
   uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend_staging
   docker exec -i bible_rag_backend_staging .venv/bin/python -m probes.xref_measure \
     < bak/$D/xref_probe/seeds.json > bak/$D/xref_probe/measured_staging.json
   uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_new.json \
     --measured bak/$D/xref_probe/measured_staging.json
   ```
   `backend_w1.id` 是這個 image 的 id，`backend_w1.head` 是建 image 時的 HEAD，兩者都記進 W1 紀錄：D3 與這裡的量測都在它上面跑，升版第 1 步上線的必須是同一個 id（不重建）。deploy-guard 結束碼 0：容器裡的 `database/neo4j_db.py`、`utils/retrieval/cross_ref_retriever.py`、`probes/xref_measure.py` 與本 checkout 的 HEAD 逐位元相同，讀 `r.curated`，沒有 999 哨兵。compare 結束碼 0：5,820 個 key 0 列不同，哨兵 12/12。

### W1 的關係層檢查（第 1A 批）
1A 的語意邊全部由 6.1 從 6.05 的 relations_clean.jsonl 匯入（[build_database.md](build_database.md) Step 6.05、6.1）。期望檔有兩份：`relations_expected.json` 是 6.05 報告扣掉 10.2 之後的邊集合，`residuals_expected.json` 是第 0 批遺留的 mention_count、MENTIONS 屬性與 R1 殘差（K10、第 1 批計畫 §2.1）。兩者與 1A 的兩個允許清單片段，都在第 1 批計畫 §1「W1 步驟」第 2 步（staging 重建）之前產生並 commit，sha256 記進 W1 紀錄，看過 staging 的 diff 之後不可再改（第 1 批計畫 §3）。K9 沒過時的退路會改變 6.05 的輸出，所以順序是 K9 → 期望檔 → 重建。`D` 沿用 R0 的日期。

1. **K9 親屬邊抽樣（事前登記：以下在開始標註之前寫定，之後不改）**。先照 [build_database.md](build_database.md) Step 6.05 在 output/ 跑出 relations_clean.jsonl 與報告（連跑兩次 cmp）。三個樣本都抽自這一份檔，sample 檔的 meta 記下它的 sha256。
   - 抽樣：anchored_rule n = 60、seed 20261007；llm n = 30、同一個 seed；prior 全部 30 列（`--all`，seed 只決定順序）。2026-10-05 以現在的 6.05 輸出（`1c0cf064…`）計算，三個池子是 319、160、30 列。規劃時的試標用 seed 20261005，不是閘門樣本；試標的標註留在 bak/，不給標註者看。
   - 判準（同一份 rubric，寫在 sample 檔裡）：text_correct 是經文明說這兩個名字之間有這種關係，方向也對；id_correct 是 text_correct 成立，而且兩端節點的主要指涉（description、最常出現的段落標題、提及的書卷）就是經文裡的那個人。
   - 標註：兩個互不知情的 AI session，各在一個只放了 sample 檔的空目錄裡標（看不到 repo、程式、句型與試標）；第三個 session 只裁決兩者不一致的項目；最後 Kay 抽查全部裁決項目，另加至少 10 項。報告標明「非人工」（kin_review 自動寫入）。
   - 閘門（決定 Q1）：anchored 的 text_correct，Wilson 下界 ≥ 0.85，也就是 60 項至少 57 項正確（57/60 的下界是 0.863，56/60 是 0.841）。id_correct 一律只報告，是延後-A 的基準（anchored 60、llm 30、prior 30）；llm、prior 兩個樣本整個只報告。
   - 沒過時的唯一退路：`config/relations/anchored_rules.yaml` 改 `enabled: false`，重跑 6.05（圖上 5,297 條，sha256 `bbc5c830…`）。探針照 C8g 的做法調整：kin-david-son-of-jesse 改寫成 prior 邊 `person:yexi FATHER_OF person:dawei`，撤掉 kin-esau-father-of-jalam。同一個 commit 改 `scripts/tests/test_validate_kg_shipped.py` 的 PROBES_1A、W1_EDGES；`scripts/tests/test_relation_postprocess_output.py::test_final_edge_set` 釘的值（列數、by_source、collapsed_keys、FINAL_EDGE_SET_SHA256、FINAL_AFTER_10_2_SHA256、KINSHIP 與 16 個探針）與同檔其他釘 anchored 數字的測試（test_stamps 的 anchored 列數與 ee 鍵條數 anchored 4／319、test_rule_drops_and_anchored_counts 的 anchored 統計），依退路重跑的 6.05 輸出重釘，能比的都要等於 `sim2_no_anchored.json`（10.2 之後 5,297 條、`bbc5c830…`）；以及同檔 test_batch0_graph_r6_and_failing_probes 的第 0 批圖上失敗的探針清單（拿掉 kin-esau-father-of-jalam）。第 2 項的期望檔改用 `sim2_no_anchored.json` 的 sha。不重抽，也不換 seed、欄位或門檻。
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   K=bak/$D/k9
   mkdir -p $K
   uv run --project scripts python scripts/tools/kin_review.py --mode sample --source anchored_rule --n 60 --seed 20261007 --out $K/anchored.json
   uv run --project scripts python scripts/tools/kin_review.py --mode sample --source llm --n 30 --seed 20261007 --out $K/llm.json
   uv run --project scripts python scripts/tools/kin_review.py --mode sample --source prior --all --seed 20261007 --out $K/prior.json
   echo 'K9 samples drawn'
   )
   ```
   每個樣本兩份 AI 標註（a、b），兩者不一致的項目由第三個 session 裁決（adj），anchored 另有 Kay 的抽查（kay）。標註檔是 JSONL，每列 `{item_id, text_correct, id_correct, annotator, note}`：兩個欄位是 true／false（id_correct 為 true 時 text_correct 也必須是 true），一份檔只有一個 annotator；AI 寫 `ai:<session>`，a、b、adj 是三個不同的 session，Kay 的抽查不可用 `ai:` 開頭。某個樣本的兩份標註沒有不一致時，裁決檔建成空檔（例如 `: > $K/llm_adj.jsonl`）：kin_review 接受空的裁決檔，檔案不存在則結束碼 2。標完之後先跑閘門：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   K=bak/$D/k9
   uv run --project scripts python scripts/tools/kin_review.py --mode score --sample $K/anchored.json \
     --labels $K/anchored_a.jsonl --labels $K/anchored_b.jsonl --adjudication $K/anchored_adj.jsonl \
     --spotcheck $K/anchored_kay.jsonl --out $K/anchored_report.json
   jq -e --slurpfile kay $K/anchored_kay.jsonl '([.disagreements[].item_id] - [$kay[].item_id] == []) and (([$kay[].item_id] | unique | length) >= (.disagreements | length) + 10)' $K/anchored_report.json
   echo 'K9 anchored passed'
   )
   ```
   anchored 那一行不帶 `--gate-field`、`--min-lb`：預設就是 text_correct 與 0.85。kin_review 結束碼 0 才算通過，1 就走上面的退路。接著的 jq 確認 Kay 的抽查涵蓋全部裁決項目，另加至少 10 項（kin_review 只報告抽查，不擋）；不過就補齊抽查，再重跑這一段。llm、prior 只報告，不論閘門的結果都要跑：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   K=bak/$D/k9
   for s in llm prior; do
     uv run --project scripts python scripts/tools/kin_review.py --mode score --sample $K/$s.json \
       --labels $K/${s}_a.jsonl --labels $K/${s}_b.jsonl --adjudication $K/${s}_adj.jsonl --report-only --out $K/${s}_report.json
   done
   echo 'K9 llm and prior reported'
   )
   ```
   三份 sample、全部標註與報告的 sha256 記進 W1 紀錄。
2. **期望檔與片段（K9 之後、第 2 步之前）**。relations_expect 讀 6.05 的報告與 prod，邊集合的 sha256 取自獨立的模擬（`sim2_final.json`，`661cfc62…`；K9 退路時改用 `sim2_no_anchored.json`，`bbc5c830…`），不取報告自己的值。全部在**乾淨的 shell** 跑：
   ```bash
   uv run --project scripts python scripts/tools/relations_expect.py \
     --expect-edge-set-sha "$(jq -r .after_10_2_sha256 docs/records/2026-10-04_kg_fix/batch1/w1_1A/sim2_final.json)" \
     --out config/kg_expect/batch1_w1/relations_expected.json --allow-out config/kg_expect/batch1_w1/relations_allow.yaml
   ```
   E1（下面這一段：兩次 validate_kg 與 residuals_expect）讀 prod 與 staging，不依賴 K9，可以先跑。7688 必須仍是第 0 批的建置，所以要在任何 W1 重建之前跑（residuals_expect 看到帶 source 的語意邊就拒絕）；而且要排在 R0 第 8 項（staging.env 遞增到 `bible_entities_v3`）與 R1 第 2 項（重建 PG staging 庫）之前：之後 staging 的 validate_kg 讀到的是還沒建的 v3（H5 報 collection 不存在）與空的 bible_rag_staging，validate_staging.json 就不再是第 0 批的報告（R1 與片段不變）。兩邊的 validate_kg 在 W1 之前都是結束碼 1（過不了 1A、1B 的硬門檻），這裡只取 R1，所以 0、1 都接受，其他就停。staging 的 validate_kg 放在 source 過 staging.env 的子 shell，輸出的導向寫在子 shell 外：source 失敗時留下空檔，residuals_expect 就拒讀：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   mkdir -p bak/$D/e1
   uv run --project scripts python scripts/validate_kg.py --live --target prod --json > bak/$D/e1/validate_prod.json || test $? -eq 1
   (source scripts/tools/staging.env && uv run --project scripts python scripts/validate_kg.py --live --target staging --json) > bak/$D/e1/validate_staging.json || test $? -eq 1
   uv run --project scripts python scripts/tools/residuals_expect.py --a prod --b staging \
     --validate-a bak/$D/e1/validate_prod.json --validate-b bak/$D/e1/validate_staging.json \
     --out config/kg_expect/batch1_w1/residuals_expected.json --allow-out config/kg_expect/batch1_w1/residuals_allow.yaml
   echo 'E1 read the batch-0 staging'
   )
   ```
   預期（2026-10-05 以同樣的參數寫到 scratch 的候選檔）：relations_expected 是 5,616 條、`661cfc62…`，output sha256 `1c0cf064…`；relations_allow 90 條（relationships 28、ee_edges 62）；residuals_allow 4 條，都在 mention_count；residuals_expected 的 R1 是 prod 1,938、staging 2,124，`mentions_props` 的逐屬性條數與兩邊的逐邊摘要見第 4 項（2026-10-06 補上，片段不變）。片段開頭的註解記下來源，要改就重跑，不手改。6.05 的報告記下自己的 `--out` 路徑（output.path），所以 report_sha256（relations_expected.json 與 relations_allow.yaml 開頭的註解都記它）取決於 6.05 寫到哪裡：relations_expect 要照上面的指令，讀預設路徑 output/relations_clean.report.json 的報告；寫到 scratch 的候選檔只供核對條目（除了這個 sha256 都相同），不可 commit。重灌鏈的 check_w1_registration 也比 report_sha256，所以重建時的 6.05 同樣寫到預設路徑；output_sha256 與 edge_set_sha256 與路徑無關。這四個檔與 1B 的 `xref.json`、`xref_allow.yaml` 一起在第 2 步之前 commit；三個片段以 R2 第 2 項的 `--merge-out` 合成 `config/kg_diff_allow_batch1w1.yaml`（不可 `cat`；預期 104 條：90＋4＋1B 的 10），`--sha-out` 寫出的 sha256 檔與這六個檔一起 commit，合併檔到 R4 之後才 commit。第 4 步經 Kay 核可的就是這些已登記的檔。
3. **重建時（第 2 步，staging 的 shell）**。6.05 照 [build_database.md](build_database.md) Step 6.05 連跑兩次並 `cmp`，而且輸出必須是登記的那一份（K9 通過時，也等於 `bak/$D/k9/anchored.json` 的 meta.clean_sha256）：重灌鏈接著跑的 check_w1_registration 比對報告、輸出與 10.2 後邊集合的 sha256 和 `relations_expected.json` 記的值，結束碼 0 才進 Step 3。6.1 照常不帶 `--replace` 匯入之後、8a 之前（也就是 10.2 之前：10.2 刪掉 16 個泛名詞 Event 之後，6.1 的端點檢查會先拒絕），再以 `--replace` 重匯兩次。三次讀到的語意層 (key, props) 摘要必須相同，都是 5,696 條：整組 SET 覆寫是冪等的，`--replace` 重建出的層也與標準鏈逐屬性相同（1A-C5d）。摘要是唯讀的 Cypher，語意層的定義與 6.1 相同：
   6.05 連跑兩次並 cmp 之後、Step 3 之前，結束碼不是 0 就停：
   ```bash
   uv run --project scripts python scripts/tools/check_w1_registration.py
   ```
   Step 3、5、6.1 照重灌鏈跑完之後、8a 之前：
   ```bash
   (
   set -eu -o pipefail
   : "${D:?set D to the W1 R0 date}"
   Q="MATCH (h:Entity)-[r]->(t:Entity) WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']
     WITH h.entity_id AS h, type(r) AS ty, t.entity_id AS t, apoc.convert.toJson(apoc.map.sortedProperties(properties(r))) AS p
     ORDER BY h, ty, t, p
     RETURN count(*) AS edges, apoc.util.sha256([apoc.convert.toJson(collect([h, ty, t, p]))]) AS props_sha"
   props_sha() { docker exec bible_rag_neo4j_staging bash -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#*/}" --format plain "$1"' _ "$Q"; }
   props_sha > bak/$D/props_0.txt
   uv run --project scripts python scripts/import_relations_neo4j.py --replace
   props_sha > bak/$D/props_1.txt
   uv run --project scripts python scripts/import_relations_neo4j.py --replace
   props_sha > bak/$D/props_2.txt
   cmp bak/$D/props_0.txt bak/$D/props_1.txt
   cmp bak/$D/props_1.txt bak/$D/props_2.txt
   grep '^5696, "' bak/$D/props_2.txt
   echo 'props identical'
   )
   ```
   grep 印出 `5696, "<sha256>"`；沒有印出最後一行就停（兩個 cmp 各占一行：`&&` 串起來時，前一個 cmp 失敗不會讓 `set -e` 停下）。K9 走退路時 6.05 的輸出是 5,377 列（`sim2_no_anchored.json` 的 final_by_source 合計），grep 改成 `'^5377, "'`。三個檔與這個 sha256 記進 W1 紀錄。2026-10-05 對第 0 批的 staging 連讀兩次，結果相同（15,926 條）；同樣邊數的 prod 讀到另一個值（phase 等屬性不同）。
4. **R2 閘門**（第 2 步之後；「W1 的交叉引用檢查」第 3 項讓 backend-staging 跑 `:w1` 之後，R2 第 3 項停掉它之前）：
   - 6.05 兩次逐位元相同、check_w1_registration 結束碼 0（輸出等於登記值），三次 props 摘要相同（第 3 項）。
   - Step 10.6 的 1A 判準全過（指令在 [build_database.md](build_database.md) Step 10.6）：validate_kg 沒有失敗、退步只有 R1，而且 R1 等於 `residuals_expected.json` 的 2,124；check_edge_set `--expect` 結束碼 0（5,616 條、`661cfc62…`）；check_identity `--fail-on id` 結束碼 0（JSON 存在 `bak/$D/check_identity_staging_w1.json`）。PROBES 另外確認 1A 修好的 4 個探針在 fixed 裡，而且 failing 剩 7 個 id（基準的 13 個扣掉 1A 的 4 個與 1B 的 2 個）：
     ```bash
     jq -e '["edge-no-dan-orphan-nehemiah-wall", "kin-leah-not-father-of-isaac", "kin-leah-not-father-of-reuben", "kin-lot-not-father-of-terah"] - .checks.PROBES.metrics.failing.fixed == [] and (.checks.PROBES.metrics.failing.value | length) == 7' bak/$D/validate_staging_w1.json
     ```
   - MENTIONS 屬性的第 0 批殘差（第 1 批計畫 §2.1）：diff_kg 只數 MENTIONS 的條數、不比屬性。W1 不改 MENTIONS，所以兩邊的 MENTIONS 都要與登記時逐邊、逐值相同。第 2 項登記的 `mentions_props` 除了 W1 staging 對 prod 逐屬性的差異條數，還有兩邊各一個逐邊摘要 `sha256.a`、`sha256.b`：每條邊的（來源 label、來源 id、entity_id）加上依名稱排序的全部屬性值，依邊排序後以正規化 JSON 算 sha256，與讀取順序無關。只比條數，看不到只落在本來就不同的邊或屬性上的改動（例如一條 start_pos 本來就不同的邊又換了 start_pos，條數不變）；兩個摘要相同，W1 staging 的 MENTIONS 就與第 0 批的 staging 相同，prod 那一邊也沒變。`--check` 只讀兩邊的 MENTIONS、不寫檔；在**乾淨的 shell** 跑（`--a prod` 讀 .env，帶著 staging 設定的 shell 會被拒絕），staging 照工具的慣例解析成預設的 bolt://localhost:7688，與登記檔 basis 記的端點不同就不讀庫、結束碼 2：
     ```bash
     uv run --project scripts python scripts/tools/residuals_expect.py --a prod --b staging \
       --check config/kg_expect/batch1_w1/residuals_expected.json
     ```
     結束碼 0 才算通過：兩個摘要與每一項條數都等於登記值。1 是有摘要或條數與登記不同（逐項印出 registered 與 now；摘要那一行標明 `sha256.a` 或 `sha256.b`，也就是 prod 或 staging 哪一邊變了）；2 是登記檔不對（例如沒有摘要的舊格式：重灌鏈的 check_w1_registration 在 Step 3 之前就會擋下）或讀不到庫。登記值（2026-10-06 趁 7688 還是第 0 批時讀的候選檔）：兩邊各 46,205 條、只在一邊的 0 條；兩邊都有的邊裡，source_granularity 40,261 條不同，start_pos、end_pos、backfilled、verse_mention_freq 各 5,782 條，created_from 106 條（手動補丁的 MENTIONS：prod 沒有這個屬性，staging 是 `manual_patch`）；`sha256.a` 是 `cd458a0bf253…`，`sha256.b` 是 `17eefb2751e5…`（產生時與緊接著的 `--check` 兩次讀到相同的值）。印出的結果與這些條數、摘要記進 W1 紀錄，作為 accept 的依據。
   - entity collection（決定 O7，建議，待 Kay 確認）：W1 不改實體、MENTIONS 與描述，所以 8b 寫出的 `bible_entities_v3` 要與 W1-0 用同一份 embed 程式建的 `bible_entities_detB` 逐點相同（point id、向量、payload）。兩個 collection 各 scroll 一次（9,124 點一頁讀完，還有下一頁就報錯），依 id 排序後算 sha256：
     ```bash
     (
     set -eu -o pipefail
     : "${D:?set D to the W1 R0 date}"
     for c in bible_entities_v3 bible_entities_detB; do
       curl -sf -X POST "http://localhost:6333/collections/$c/points/scroll" -H 'Content-Type: application/json' \
         -d '{"limit": 20000, "with_payload": true, "with_vector": true}' \
         | jq -cS 'if .result.next_page_offset then error("more pages") else .result.points | sort_by(.id) end' \
         | sha256sum | cut -d' ' -f1 > bak/$D/qdrant_$c.sha256
     done
     cmp bak/$D/qdrant_bible_entities_v3.sha256 bak/$D/qdrant_bible_entities_detB.sha256
     echo 'v3 == detB'
     )
     ```
     2026-10-05 對 detB 連讀兩次，sha256 相同（`7f0ad9f6…`）；第 0 批的 v2 是另一個值（舊的 embed 程式）。沒有印出最後一行就停。通過後 detB 可以照「收尾」刪除。
   - diff_kg 以合併清單 `config/kg_diff_allow_batch1w1.yaml` 加 `--fail-on-unused`，結束碼 0（R2 第 2 項）。
   - D3：backend-staging 跑 `backend_w1.id`，prod 照舊；r0 是 W0 量到的 0（第 1 批計畫 §5.1）。結束碼 0 才算通過：
     ```bash
     (cd evaluation && uv run python d3_gate.py --label w1 --control-url http://localhost:8000 --treatment-url http://localhost:8001 --route-residual-max 0)
     ```
   - K8 的實驗組：在同一個 backend-staging 量 entity_path 500 題，只報告。對照組 R4 之後才建（R4「W1 的 K8 對照組」）：
     ```bash
     (cd evaluation && rm -f results_quick/ep_w1.json \
       && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_w1)
     ```
   - 以上全部通過之後，把 10.6 的閘門報告 `bak/$D/validate_staging_w1.json` 與 check_identity 的輸出（計畫 §5.4 要保留）的 sha256 補進 `bak/$D/SHA256SUMS`，只補一次。R4 之後 K8 的 P1 重建把自己的報告寫到 `bak/$D/k8/`（R4「W1 的 K8 對照組」），之後仍可用 `(cd bak/$D && grep -F ' ./validate_staging_w1.json' SHA256SUMS | sha256sum -c -)` 核對 R2 的報告沒被改過：
     ```bash
     (cd bak/$D && sha256sum ./validate_staging_w1.json >> SHA256SUMS)
     (cd bak/$D && sha256sum ./check_identity_staging_w1.json >> SHA256SUMS)
     ```

## R3 升版（第 0 批不做）
順序規則：backend 程式碼的變更要向前相容，先部署 backend，再升資料（例如第 1B 批）；一個缺陷項目一個 commit，各自附探針，validate 失敗時才分得出是哪一項造成。

第 1 批 W1 不照下面 1–4 的順序，改照下方「W1 升版第 1 步」「W1 升版第 2 步」：第 1 步只換 backend image，第 2 步才載入 Neo4j，而且用該節自己的失敗即停區塊（同這裡第 1 步的 dump／load，另加 deploy-guard、staging 唯讀再驗、dump 完整性與 sha256），不貼這裡第 1 步的指令。W1 的 PG、Qdrant、.env 都不動，所以不做第 2、3 步；第 4 步已在 W1 升版第 1 步完成。下面 1–4 仍是其他批次的通用做法。
1. Neo4j：從 staging dump，再載入正式 volume。停機約 1 分鐘，期間 /api/v1/entity 會出錯：
   ```bash
   mkdir -p bak/$D/promote
   docker stop -t 60 bible_rag_neo4j_staging
   docker run --rm --user 7474:7474 --entrypoint neo4j-admin \
     -v bible_rag_neo4j_staging_data:/data neo4j:5.15-community \
     database dump neo4j --to-stdout > bak/$D/promote/neo4j_staging.dump

   docker stop -t 60 bible_rag_neo4j
   docker run --rm -i --user 7474:7474 --entrypoint neo4j-admin \
     -v bible_rag_neo4j_data:/data neo4j:5.15-community \
     database load neo4j --from-stdin --overwrite-destination=true < bak/$D/promote/neo4j_staging.dump
   docker start bible_rag_neo4j
   ```
   dump 前停掉 staging 是因為 community 版只能對停機的資料庫做 dump；之後還要用 staging 時再 `docker start bible_rag_neo4j_staging`。另一個做法是把 backend 的 `NEO4J_URI` 改指 staging，但 backend 容器的環境變數是啟動時的快照，必須重新建立容器才會生效。計畫 D15 建議用 dump/load。
2. PG：從 staging 匯出 entities 與 entity_mentions，在一個 transaction 內換表：
   ```bash
   docker exec bible_rag_postgres pg_dump -U bible -d bible_rag_staging -t entities -t entity_mentions \
     > bak/$D/promote/entity_tables_staging.sql
   { echo 'DROP TABLE IF EXISTS public.entity_mentions, public.entities;'; cat bak/$D/promote/entity_tables_staging.sql; } \
     | docker exec -i bible_rag_postgres psql -U bible -d bible_rag --single-transaction -v ON_ERROR_STOP=1
   ```
   plain dump 內含兩張表的定義、主鍵、索引、外鍵與資料。DROP 沒有加 CASCADE：若還有別的物件依賴這兩張表，整個 transaction 會失敗並回滾，production 不受影響。
3. Qdrant：把 `.env` 的 `QDRANT_ENTITY_COLLECTION` 改成 `bible_entities_vN`（backend 設定 `qdrant_entity_collection`，見 backend/config.py；scripts 也讀同一個變數），再重新建立 backend 容器（第 4 步會一併完成）。舊 collection 留到下一批 R0 之後再刪。另一個做法是一次性改用 Qdrant alias；alias 不能與現有 collection 同名，所以 backend 要改指新的 alias 名。
4. 程式碼、registry、字典隨 image 上線：在沒有 source staging.env 的乾淨 shell 執行 `docker compose up -d --no-deps --build backend`（理由見 R5 開頭）。backend 沒有 volume mount，只 restart 會跑舊 image；建置要走 uv 快取（README「Docker 建置快取」）。

### W1 升版第 1 步：backend 先上，資料不動
在主 checkout、沒有 source staging.env 的乾淨 shell 執行：這裡要對 production 做 `up`，而 `--target prod` 會拒絕 staging 的 shell；compose 的專案名取自目錄名，只有主 checkout 的 backend image 是 `bible_rag-backend:latest`。先把 `D` 設成 W1 R0 的日期（每段開頭的 `${D:?}` 沒設就停）。種子與期望檔沿用 R2「W1 的交叉引用檢查」的 `bak/$D/xref_probe/`。

三段依序貼上。前兩段是子 shell 加 `set -e`，任何一行失敗整段就停；沒有印出最後一行的訊息，就不要貼下一段。第一段保存回滾 image，只做一次：
```bash
(
set -eu -o pipefail -o noclobber
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
PROD=$(docker inspect -f '{{.Image}}' bible_rag_backend)
test "$PROD" != "$W1"
test ! -e bak/$D/images/backend_kg-pre-batch1-w1.tar.gz
echo "$PROD" > bak/$D/images/backend_kg-pre-batch1-w1.id
docker tag "$PROD" bible_rag-backend:kg-pre-batch1-w1
docker create --name bible_rag_backend_kg_pre_batch1_w1 bible_rag-backend:kg-pre-batch1-w1
docker save bible_rag-backend:kg-pre-batch1-w1 | gzip > bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part
gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part | tar -tf - | grep -Ex "(\./)?blobs/sha256/${PROD#sha256:}" >/dev/null
mv bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part bak/$D/images/backend_kg-pre-batch1-w1.tar.gz
(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)
echo 'rollback image saved'
)
```
第二段換成 R2 測過的 image，可以重跑：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
PRE=$(cat bak/$D/images/backend_kg-pre-batch1-w1.id)
P=$(docker inspect -f '{{.Image}}' bible_rag_backend)
case "$P" in "$PRE"|"$W1") ;; *) echo "prod runs $P, neither the recorded rollback image nor :w1" >&2; exit 1;; esac
grep -qF ' ./images/backend_kg-pre-batch1-w1.tar.gz' bak/$D/SHA256SUMS
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_kg_pre_batch1_w1)" = "$PRE"
test "$(docker image inspect -f '{{.Id}}' bible_rag-backend:w1)" = "$W1"
docker tag bible_rag-backend:w1 bible_rag-backend:latest
docker compose up -d --no-deps --no-build --wait --wait-timeout 300 backend
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
echo 'prod runs :w1'
)
```
第三段驗證：
```bash
(cd evaluation && rm -f results_quick/w1_step1_smoke.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/smoke20_ids.txt --label w1_step1_smoke \
  && python3 -c "import json; d = json.load(open('results_quick/w1_step1_smoke.json')); r = (d['n'], d['n_invalid'], sorted(q for q, e in d['per_question'].items() if e['strategy_errors']), d['config']['graph_strategies_applied']); print(*r); raise SystemExit(0 if r == (20, 0, [], {'event_registry': 20}) else 1)")
uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend
docker exec -i bible_rag_backend .venv/bin/python -m probes.xref_measure \
  < bak/$D/xref_probe/seeds.json > bak/$D/xref_probe/measured_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py predict --seeds bak/$D/xref_probe/seeds.json \
  --target prod --out bak/$D/xref_probe/pred_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_step1.json \
  --measured bak/$D/xref_probe/measured_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_step1.json \
  --measured bak/20261005_w1_1b_evidence/pred_trans.json
```
- **回滾 image 取自 prod 容器正在跑的 image**（升版前是 9bc112a6），不取 `latest`：`latest` 若在 R2 被重建過，已經是 W1 的 image。它的 id 記在 `backend_kg-pre-batch1-w1.id`，R5 依這個 id 退回，不依 tag。R0 若已打過這個 tag，第一段會把它改指到記下的 id。
- **第一段只做一次**：prod 已經在跑 `:w1`，或 id 檔、存檔已經存在（`noclobber` 拒絕覆寫）時就停。所以第一段重跑時，不會把 W1 的 image 記成回滾 image，不會覆寫存檔，也不會在 SHA256SUMS 多補一行。第一段中途失敗時 prod 還沒換 image：查明原因後 `docker rm bible_rag_backend_kg_pre_batch1_w1`，刪掉 `backend_kg-pre-batch1-w1.id` 與 `.tar.gz.part`，再重跑第一段。只有最後補 sha256 的那一行失敗時（`.tar.gz` 已在，SHA256SUMS 沒有它），不要照上面清理，也不要重跑第一段（`test ! -e` 會擋，第二段也會停在 SHA256SUMS 那一行）：先核對存檔，`(set -o pipefail; gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz | tar -tf - | grep -Ex "(\./)?blobs/sha256/$(cut -d: -f2 bak/$D/images/backend_kg-pre-batch1-w1.id)")` 要結束碼 0 並印出那個 blob，再手動跑 `(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)`，然後貼第二段。
- **回滾 image 在換 image 之前保住**（R0 第 7 項）：停著的容器 `bible_rag_backend_kg_pre_batch1_w1` 讓 `docker image prune -a` 刪不掉它；`docker system prune` 會先刪停著的容器，所以還要 `docker save`。`pipefail` 讓 save 中斷時整段失敗；先寫到 `.part`，`tar -tf` 從頭讀到尾沒有錯誤、而且清單裡有 prod image id 的 blob（`blobs/sha256/<id>`；containerd store 下這個 id 是 index digest，R5 依它從存檔載回）才改名、記 sha256，所以正式檔名只會是完整、帶著這個 id 的存檔。grep 不加 `-q`：讀完整份清單，tar 不會被 SIGPIPE 中斷而讓 `pipefail` 誤判失敗。存檔裡沒有這個 blob 就停：prod 還沒換 image，先查 `docker load` 能不能還原同一個 id，再決定怎麼保存回滾 image。image 的內容約 7 GB，存檔與核對要幾分鐘，prod 照常服務。這個容器留到下一批 R0 之後才 `docker rm`。
- **上線的是 R2 測過的 image，不重建**：第 1 批計畫 §1「W1 升版」第 1 步原寫 `up -d --build backend`，改為把 R2 建的 `bible_rag-backend:w1` 改 tag 成 `latest`。第二段先確認第一段做完（SHA256SUMS 有存檔那一行、停著的容器還釘著回滾 image），而且 `:w1` 仍是 R2 記下的 `backend_w1.id`，才改 tag、`up`。第二段也確認 prod 仍是第一段記下的 id（重跑時已是 `backend_w1.id`）：兩者都不是，表示 prod 在第一段之後被換過（例如無關的 `up -d --build`），記下的回滾 image 就不是 W1 取代的那一個，整段就停。`--no-build`：image 不在就失敗，不會在 prod 上重建；`--no-deps`：只動 backend（理由見 R5 開頭）；`--wait`：等 healthcheck 通過才返回（start_period 120 秒），unhealthy 或超過 300 秒時結束碼不是 0，整段就停。最後確認 prod 容器跑的是 `backend_w1.id`。
- **煙霧測試**：20 題預設檢索（只有 event_registry），通過條件是印出 `20 0 [] {'event_registry': 20}`（見[題號檔 README](../evaluation/experiments/2026-10-05_kg_w1/README.md)）：最後一項是 backend 回報套用的圖譜策略計數（quick_retrieval_eval 記在 `config.graph_strategies_applied`），新 image 的預設路徑仍只套用 event_registry。先刪掉上一次的結果檔，執行與檢查用 `&&` 串起來，舊檔不會讓檢查假性通過；印出的不是這一行時，檢查的結束碼是 1。
- **deploy-guard** 結束碼 0。不是 0 就先查 image，不往下做。
- **C1 的判準是精確比對**：兩個 compare 結束碼都是 0（煙霧測試與 deploy-guard 不過同樣要停，見上兩項）。第一個是 prod 的實測對預測：5,820 個 key 0 列不同，哨兵 12/12；第二個是 `pred_prod_step1.json` 對規劃時歸檔的 `bak/20261005_w1_1b_evidence/pred_trans.json`（2026-10-05 對當時的 prod 已驗證 0/5,820）。這個 image 帶上了 087ab0d（W1-0 的 md5 平手，prod 現行的 9bc112a6 還沒有）、1B-C1（讀 `r.curated`，刪除 999 哨兵）、`backend/probes/`，以及兩個串流的全部 scripts/ 與 bible_chunking/ 改動（都 COPY 進 image）。所以**不要拿 opt-in 的線上行為與 9bc112a6 比**：光是 md5 平手就讓約 1,279/2,779 個單一種子、57/262 個代理種子集的 id 集合改變；相對於 087ab0d 的 Cypher，C1 本身只改 5 個單一種子（只有權重）與 1/262 個種子集。
- W1 紀錄要寫明：第 1 步上線的是 087ab0d 加 C1，判準是這裡的精確比對；並記下 R2 的 `backend_w1.id`、第 1 步之後 prod 容器的 image id（兩者必須相同）、回滾 image 的 id（`backend_kg-pre-batch1-w1.id`，升版前是 9bc112a6…），以及回滾存檔的 sha256。
- 第三段通過之後，接著跑下方「W1 的 /api/v1/entity 比對」第一段（擷取 before，只做一次），再進入 opt-in A/B。

### W1 的 /api/v1/entity 比對（第 1A 批）
第 1 批計畫 §1 的 W1 驗收「/api 的 W1 清單與 prod 完全相同」，id 是 §5.3 的 7 個。比的是 prod 自己在第 2 步前後：同一個 W1 image、同一個 PG，只有 Neo4j 換成 W1 的資料。/api/v1/entity 的欄位來自 PG（type、canonical_name、aliases、description、mention_count）與 MENTIONS（related_passages、related_entities，見 `backend/database/neo4j_db.py` 的 get_entity_related_pericopes、find_related_entities），W1 兩者都不改，所以正規化之後必須逐位元相同。
- **不在 R2 拿 :8000 比 :8001**：R2 時 prod 還是 9bc112a6，沒有 087ab0d 的 md5 平手；7 個 id 有 5 個的相關段落超過 10 個，同樣的資料在 LIMIT 10 會取到不同的集合。jq 的 sort_by 只固定順序，不固定取到哪些。2026-10-05 實測：prod（9bc112a6）對 backend-staging（w1det，有 087ab0d），7 個 id 的 related_* 全部不同；改用 087ab0d 的兩個查詢直接讀 prod 的 7687，7 個 id 都與 backend-staging 從 7688 讀到的相同。
- 三段都在主 checkout 的乾淨 shell 跑（同第 1 步）。第一段在第 1 步第三段通過之後、opt-in A/B 之前跑，只做一次：`noclobber` 讓重跑在第一個已存在的檔就停，不會把第 2 步之後的回應記成 before。中途失敗時刪掉 `bak/$D/api/before` 再跑。

```bash
(
set -eu -o pipefail -o noclobber
: "${D:?set D to the W1 R0 date}"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$(cat bak/$D/images/backend_w1.id)"
mkdir -p bak/$D/api/before
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  curl -sf "http://localhost:8000/api/v1/entity/$id" \
    | jq -S '.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)' > "bak/$D/api/before/$id.json"
done
echo 'api before captured'
)
```
第二段可選，只是提早示警，不是閘門：在下方 A/B 視窗裡 backend-staging 也跑 `:w1` 的時候，拿 :8000 比 :8001。兩邊的 PG 不同（bible_rag 對 bible_rag_staging），person:yeteluo 與 event:shanshangbaoxun 的 aliases 只因 PG 的資料就不同（2026-10-05 實測：prod 兩個都是 `[]`，staging 分別是 `["流珥"]` 與 `["登山寶訓", "八福"]`），所以只有這兩個 id 不比 aliases。印出 `DIFF` 的 id 先查清楚，再做第 2 步：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$W1"
mkdir -p bak/$D/api/early
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  f='.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)'
  case $id in person:yeteluo|event:shanshangbaoxun) f="$f | del(.aliases)";; esac
  for port in 8000 8001; do
    curl -sf "http://localhost:$port/api/v1/entity/$id" | jq -S "$f" > "bak/$D/api/early/$port-$id.json"
  done
  cmp -s "bak/$D/api/early/8000-$id.json" "bak/$D/api/early/8001-$id.json" || echo "DIFF $id"
done
echo 'early compare done'
)
```
第三段是閘門：第 2 步載入、`docker start bible_rag_neo4j` 之後、R4 之前跑。7 個 id 都 `cmp` 相同才印出最後一行；不同就停下來查：不做 R4 的 ratchet，也不自動走 R5。prod 這時是 W1 的資料加 W1 的 image，W1 image 新舊資料都能正確排序，留在這個狀態查是安全的；要不要 R5 由 Kay 決定，回滾時照 R5 先資料、後 image。可以重跑（Neo4j 剛起來時 curl 可能失敗）。before、after 兩組檔的 sha256 記進 W1 紀錄：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$(cat bak/$D/images/backend_w1.id)"
test "$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j)" = healthy
mkdir -p bak/$D/api/after
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  curl -sf "http://localhost:8000/api/v1/entity/$id" \
    | jq -S '.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)' > "bak/$D/api/after/$id.json"
  cmp "bak/$D/api/before/$id.json" "bak/$D/api/after/$id.json"
done
echo 'api identical'
)
```

### W1 升版第 1、2 步之間：opt-in A/B（xref、graph_event，只報告）
第 1 批計畫 §5.2 在這裡量 W1 的兩項 opt-in：同一個 W1 image 分別接舊資料（prod，第 1 步之後）與新資料（backend-staging），兩邊參數完全相同。xref 各跑一次 500 題（kg_xref 的 68 題要在 500 題裡才算得到）；graph_event 只抽查 K10 的題（下方）。R2 第 3 項驗完已停掉 backend-staging，所以先在第 1 步的同一個 shell 用 R2 的 override 重新啟動它，等 healthcheck 通過，並確認兩邊跑的都是 `backend_w1.id`：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j_staging)" = healthy
printf 'services:\n  backend:\n    image: bible_rag-backend:w1\n  backend-staging:\n    image: bible_rag-backend:w1\n' > /tmp/w1_image.yml
docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$W1"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
echo 'both arms run :w1'
)
```
沒有印出最後一行就不要往下。neo4j-staging 必須仍是 W1 重建的資料而且 healthy（停了就 `docker start bible_rag_neo4j_staging`）；`--no-deps` 不碰它，`--no-build` 不重建 image。接著量測。評估指令都包在子 shell 裡，跑完仍在專案根目錄，第 2 步的相對路徑才對：
```bash
(cd evaluation && rm -f results_quick/xref_old_w1.json results_quick/xref_new_w1.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_old_w1 \
  && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_new_w1)
(cd evaluation && uv run python xref_ab_slice.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json --label w1_xref)
(cd evaluation && uv run python ab_compare.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json --label w1_xref)
```
- 先刪上一次的結果檔，兩次收集用 `&&` 串起來：中途失敗時，後面的報告讀不到舊檔。
- xref_ab_slice 結束碼 2 是防呆（兩邊的策略、top_k、metric_k、metric_version 不同，或段落沒有 gold、found_by，或 `--ids` 檔不是 qid 清單，或 kg_xref 切片在兩邊都沒有有效題），不存報告：空切片會印出「0 → 0」，看起來就像預期的沒有增益。切片只有部分題目有效時印 `warning:`，結束碼不變。只在一邊出現的題列在 `unpaired`。
- xref_ab_slice 結束碼 3 是 touched 題數超過 `--max-touched`（預設 34）：先停下來查，再決定要不要做第 2 步。預期 touched 約 17 題以下；kg_xref「只經 xref 到達 gold」預期沒有增益（模擬 14 → 14）。這不是閘門。
- ab_compare 補上 §5.2 要求的其餘數字：每段印出各指標的平均 Δ、95% CI（bootstrap）與勝負題數 W/L，Δvrec 是 `verse_recall_at_k` 那一列。`[legacy]`（legacy-100，樣本內）與 `[expanded]`（擴充的 400 題；1B 設計時用過的 kg_xref 68 題都在這一段，所以不是乾淨的 held-out，kg_xref 由 xref_ab_slice 另報）兩段分開記進 W1 紀錄，`[all]` 一併記；要乾淨的 held-out 數字，從兩份結果檔的 per_question 扣掉這 68 題另算，同樣只報告。它的 `touched (passages appended)` 是指附加在 top-k 之後的段落，兩個 xref 策略不附加，所以是 0；touched 題數以 xref_ab_slice 為準。只報告，不設門檻。
- touched 的題先用同樣條件重問，排除 LLM 取樣雜訊：W0 的 legacy-100 有 1 題（GENERAL_BIBLE_QUESTION_016）只因 intent LLM 取樣就換了 top-5（[W0 紀錄](records/2026-10-05_kg_batch1_w0_results.md)「補記：W1-0 opt-in 決定性」）。

**graph_event 抽查（K10，只報告）**。K10 決定「W1 先 accept 並抽查 graph_event」，第 1 批計畫 §5.2 的 W1 列是「抽查保羅歸主、山上寶訓的題目（受 mention_count 殘差影響）」。第 0 批遺留的 mention_count 殘差有 3 個實體是 Event：event:shanshangbaoxun（山上寶訓）與兩個保羅敘述歸主的事件。graph_event 每個事件關鍵字取 mention_count 最高的 3 個事件，pin 的先後也依 mention_count，所以這些題挑到的事件與段落可能改變。題號檔 `evaluation/experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt` 是 GT 裡題目文字含有這 3 個事件在 event_registry 的觸發詞（保羅歸主、八福、山上寶訓、登山寶訓）的題，選題規則見[題號檔 README](../evaluation/experiments/2026-10-05_kg_w1/README.md)。同一個視窗、同一組參數（與上面的 xref 量測相同的 `--top-k 5 --metric-k 6`），只換資料：
```bash
(cd evaluation && rm -f results_quick/ge_old_w1.json results_quick/ge_new_w1.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt --graph-strategies graph_event --top-k 5 --metric-k 6 --label ge_old_w1 \
  && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt --graph-strategies graph_event --top-k 5 --metric-k 6 --label ge_new_w1)
(cd evaluation && uv run python ab_compare.py results_quick/ge_old_w1.json results_quick/ge_new_w1.json --label w1_graph_event)
```
- ab_compare 的 core top-5 identical／mismatch、改動帳本（identical、order_only、nongold_swap、gold_in、gold_out、gold_swap）與各指標的 Δ、W/L 都記進 W1 紀錄，放在 K10 的 accept（`residuals_allow.yaml` 的 4 筆 mention_count）旁邊。有變動的題先用同樣條件重問，排除 intent LLM 的取樣雜訊（同上）。只報告，不設門檻，不擋第 2 步。
- **答案端（第 1 批計畫 §5.2）**：xref 與 graph_event 都一樣，只在檢索結果有實質差異時才跑。coverage 是主要指標，faithfulness strict ≥ 0.97 守門，逐題的 |Δcoverage| 與雜訊地板 0.060（同一份 context 的 coverage |Δ| 平均）比較。跑不跑、依據哪些數字，都記進 W1 紀錄。
- 兩項都量完，照 R2 第 3 項停掉 backend-staging。

### W1 升版第 2 步：載入資料，第一個指令是 deploy-guard
這是 W1 唯一寫入 prod 資料的一步，所以不貼上面 R3 第 1 步的通用指令，改貼下面這一整段（Neo4j 停機約 1 分鐘）。在主 checkout、沒有 source staging.env 的乾淨 shell 執行，同第 1 步：deploy-guard 比對的是本 checkout 的 HEAD，`--a prod` 會拒絕帶著 staging 設定的 shell，`--target staging` 在乾淨的 shell 解析成預設的 bolt://localhost:7688。整段是子 shell 加 `set -e`，任何一行失敗就停；沒有印出最後一行，就是沒有載入完成：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
uv run --project scripts python scripts/tools/xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json
uv run --project scripts python scripts/tools/check_edge_set.py --target staging \
  --expect config/kg_expect/batch1_w1/relations_expected.json
uv run --project scripts python scripts/tools/residuals_expect.py --a prod --b staging \
  --check config/kg_expect/batch1_w1/residuals_expected.json
mkdir -p bak/$D/promote
test ! -e bak/$D/promote/neo4j_staging.dump
docker stop -t 60 bible_rag_neo4j_staging
docker run --rm --user 7474:7474 --entrypoint neo4j-admin \
  -v bible_rag_neo4j_staging_data:/data neo4j:5.15-community \
  database dump neo4j --to-stdout > bak/$D/promote/neo4j_staging.dump.part
test -s bak/$D/promote/neo4j_staging.dump.part
mv bak/$D/promote/neo4j_staging.dump.part bak/$D/promote/neo4j_staging.dump
(cd bak/$D && sha256sum ./promote/neo4j_staging.dump >> SHA256SUMS)
docker stop -t 60 bible_rag_neo4j
docker run --rm -i --user 7474:7474 --entrypoint neo4j-admin \
  -v bible_rag_neo4j_data:/data neo4j:5.15-community \
  database load neo4j --from-stdin --overwrite-destination=true < bak/$D/promote/neo4j_staging.dump
docker start bible_rag_neo4j
echo 'prod neo4j loaded'
)
```
- **deploy-guard 是第一個指令**：結束碼不是 0 就停，不載入 dump：prod 容器跑的不是本 checkout HEAD 建的、讀 `r.curated` 的 image（例如第 1 步之後被重建或退回過），新資料會被舊規則排序（第 1 批計畫 §2.2 的風險；部署順序顛倒的影響見 R5）。下一行再確認 prod 跑的仍是 R2 記下的 `backend_w1.id`。
- 每個 `docker exec`、`git show` 最多等 30 秒。docker daemon 或容器沒有回應時，印出 `timed out after 30 s` 並以結束碼 1 結束，不會卡住：先查 daemon 與容器，同樣不載入。
- 第 1、2 步可能相隔數小時，deploy-guard 放在這一段裡，所以每次都會重跑。載入資料之後不要再建 image；image 一有任何變動，先重跑 deploy-guard 再碰資料。
- **staging 唯讀再驗一次**：dump 出去的必須是 R2 驗過、第 4 步經 Kay 核可的那份資料，而 staging 從 R2 到這裡一直開著。三項都對已登記的檔、判準與 R2 相同：xref 的指紋與 xref_provenance（「W1 的交叉引用檢查」第 2 項）、語意層的邊集合（「W1 的關係層檢查」第 4 項的 check_edge_set）、MENTIONS 的逐邊摘要與屬性的第 0 批殘差（同一項的 `residuals_expect.py --check`，本來就要在乾淨的 shell 跑）。任何一項結束碼不是 0 就停，這時 prod 還沒動。
- **dump 完整才停 prod**：dump 先寫到 `.part`，neo4j-admin 失敗時整段就停；`test -s` 擋掉空檔；之後才改名，sha256 補進 `bak/$D/SHA256SUMS`（同第 1 步的回滾存檔）。prod 的 `docker stop` 排在這些之後。`test ! -e` 讓 dump 只做一次，SHA256SUMS 不會多補一行。
- 中途失敗時，先看停在哪一行：
  - SHA256SUMS 補上之前：prod 沒動。staging 已停就 `docker start bible_rag_neo4j_staging`，等它 healthy；刪掉 `.part`，以及已改名、但還沒補進 SHA256SUMS 的 dump，再重跑整段。
  - SHA256SUMS 補上之後（例如載入失敗）：dump 已完整並記下 sha256，不要重跑整段（`test ! -e` 會擋，staging 也已停）。查明原因後，先以 `(cd bak/$D && grep -F ' ./promote/neo4j_staging.dump' SHA256SUMS | sha256sum -c -)` 核對 dump，再從 prod 的 `docker stop` 那一行起逐行執行；或照 R5 載回 R0 的 dump。
- staging 停在 dump 時的狀態；之後要用（R4 之後的 K8 對照組）時再 `docker start bible_rag_neo4j_staging`。
- 載入、`docker start bible_rag_neo4j` 之後，先跑上面「W1 的 /api/v1/entity 比對」第三段（它會確認 prod 的 Neo4j 已 healthy，可以重跑），相同才做 R4。

## R4 升版後檢查
- 在 production 上執行 `validate_kg.py --live --target prod`、`export_event_registry.py --check`、`check_identity.py --target prod --fail-on id`（第 1D 批之前都用 `--fail-on id`：prod 的 Qdrant aliases 還是 JSON 字串，9,093 筆，預設的全部種類必然結束碼 1，見 [build_database.md](build_database.md) Step 10.6）。要在沒有 source staging.env 的新 shell 執行：validate_kg 與 check_identity 的 `--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、store 變數與 .env 不同、Neo4j 7688、bible_rag_staging）時會拒絕並結束碼 1，不會把 staging 當成 prod 報告；export_event_registry 沒有這層防護，只讀 `NEO4J_URI`，在 staging 的 shell 會默默檢查 staging 圖。
- 抽查 /api/v1/entity（計畫 §6.4 列出各批的探針）。

### W1 的關係層升版後檢查（第 1A 批）
在 R4 的同一個乾淨 shell、下方 1B 的檢查與 ratchet 之前執行，判準與 staging 相同（[build_database.md](build_database.md) Step 10.6）：
```bash
uv run --project scripts python scripts/validate_kg.py --live --target prod --json > bak/$D/validate_prod_w1.json
jq -e '.failures == [] and .regressions - ["R1"] == []' bak/$D/validate_prod_w1.json
jq -e --slurpfile e config/kg_expect/batch1_w1/residuals_expected.json \
  '.checks.R1.metrics.book_region_mentions.value == $e[0].validate_kg.R1.b' bak/$D/validate_prod_w1.json
jq -e '["edge-no-dan-orphan-nehemiah-wall", "kin-leah-not-father-of-isaac", "kin-leah-not-father-of-reuben", "kin-lot-not-father-of-terah"] - .checks.PROBES.metrics.failing.fixed == [] and (.checks.PROBES.metrics.failing.value | length) == 7' bak/$D/validate_prod_w1.json
uv run --project scripts python scripts/tools/check_edge_set.py --target prod --expect config/kg_expect/batch1_w1/relations_expected.json
uv run --project scripts python scripts/check_identity.py --target prod --fail-on id --json > bak/$D/check_identity_prod_w1.json
```
- 全部結束碼 0：hard 全過（1A 的 H3、H9、H11、R6，第 0 批的 H1、H2、H7、D1，1B 的 H8、R4、R11）；退步只有 R1，而且等於登記的 2,124；PROBES 的 failing 剩 7 個 id；prod 的語意層等於 `relations_expected.json`（5,616 條、`661cfc62…`）；三庫的 id 集合差為 0（check_identity 的 aliases 等差異到第 1D 批前都屬正常，只報告）。升版前 prod 的 H1 因為缺 `:Entity(entity_id)` 唯一性約束而不過（missing_constraint 1）；staging 有這個約束，dump 會一起帶過來，所以載入之後預期是 0。全部通過之後執行 `(cd bak/$D && sha256sum ./validate_prod_w1.json ./check_identity_prod_w1.json >> SHA256SUMS)`（計畫 §5.4：保留輸出與 sha），只補一次。
- check_edge_set 的 `--report` 預設讀 output/relations_clean.report.json，就是 6.1 匯入的那一份；output/ 在升版前後都不要動。
- /api/v1/entity 的 7 個 id 已在第 2 步之後比對過（R3「W1 的 /api/v1/entity 比對」第三段）。

### W1 的交叉引用升版後檢查（第 1B 批）
在同一個乾淨的 shell 執行。`pred_new.json` 是 R2 用 `predict --edges expected_edges.jsonl` 算出的預測，等於歸檔的 oracle：
```bash
uv run --project scripts python scripts/tools/xref_probe.py fingerprint --target prod --expect config/kg_expect/batch1_w1/xref.json
docker exec -i bible_rag_backend .venv/bin/python -m probes.xref_measure \
  < bak/$D/xref_probe/seeds.json > bak/$D/xref_probe/measured_prod_r4.json
uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_new.json \
  --measured bak/$D/xref_probe/measured_prod_r4.json
```
- fingerprint 結束碼 0（`e522411e…`，xref_provenance 四個鍵與期望檔相同）；compare 結束碼 0，5,820 個 key 0 列不同，哨兵 12/12。
- `validate_kg.py --live --target prod` 的 H8、R4、R11 三項 hard 全過，值見 [build_database.md](build_database.md) Step 10.6。
- **R4 之後只做一個 commit**，與 W1 的合併允許清單 `config/kg_diff_allow_batch1w1.yaml` 放在一起（第 1 批計畫 §3）。整波只跑一次 ratchet，1A、1B 共用這一行，在同一個乾淨的 shell、上面的檢查都通過之後執行，結束碼要是 0：
  ```bash
  uv run --project scripts python scripts/validate_kg.py --live --target prod --ratchet --accept W,R1,R11
  ```
  寫入 `config/kg_quality_baseline/`。結束碼不是 0 時，基準檔也已經寫入（validate_kg 先 ratchet、寫檔，之後才判定結束碼）：`git checkout -- config/kg_quality_baseline/` 還原，不 commit，先查原因。1B 移動的指標：`--ratchet` 的 H8.no_provenance 916 → 0、H8.unflagged 250,418 → 0、R4.misaligned 59 → 0、R4.misaligned_any_verse 62 → 0，以及 `--accept` 的 R11（249,502 → 250,358）。同一個 commit 裡，PROBES 的 failing 名單拿掉 `xref-heb1-0-not-curated-psa2` 與 `xref-rev20-not-curated-isa65`，新的 xref 探針不可留在 failing 裡。
  1A 移動的指標：`--accept` 的 W（Entity–Entity 語意邊 15,926 → 5,616、35 種型別，例如 PARTICIPATED_IN 7,130 → 1,489、OCCURRED_IN 4,313 → 894、FATHER_OF 647 → 50、SON_OF 659 → 335，CAUSED 與 PRECEDED_BY 歸零；labels 與 MENTIONS 的條數不變，MENTIONS 的屬性帶著已 accept 的第 0 批殘差：source_granularity 40,261 條，start_pos、end_pos、backfilled、verse_mention_freq 各 5,782 條，created_from 106 條，由 R2 的 `residuals_expect.py --check` 比對（兩邊的逐邊摘要也等於登記值：W1 沒有改動任何 MENTIONS），W1 紀錄要列出這些條數與摘要；CROSS_REFERENCES 屬 1B）與 R1（1,938 → 2,124，第 0 批的殘差，等於 `residuals_expected.json` 的 b）；`--ratchet` 的 H3 374 → 0、H9 14 → 0、H11（source_null 15,926、inverse_edges 756、cooccurrence_edges 9,060、rule_edges 771、llm_event_event_edges 26、unflagged_id_order_edges 81、undirected_pair_duplicates 6，全部 → 0）、R6 的 contradictions 25 → 0、female_head 42 → 0、functional_violation_rate 0.5357 → 0.0638、children_with_2plus_nonfemale_parents 135 → 8、children_with_gt2_parents 87 → 1；第 0 批的 H1.missing_constraint 也會跟著從 1 變 0（dump 帶來的約束）。同一個 commit 裡，PROBES 的 failing 名單另拿掉 1A 修好的 `edge-no-dan-orphan-nehemiah-wall`、`kin-lot-not-father-of-terah`、`kin-leah-not-father-of-isaac`、`kin-leah-not-father-of-reuben`，兩批合計剩 7 個 id（`alias-matthew-not-levi`、`alias-paul-not-saul`、`book-region-egypt`、`book-region-mark`、`book-region-matthew`、`mention-not-elijah-in-eleazar`、`mention-not-mary-in-samaria`）；R6 的 failing_probes 從 3 個 id 變成 `[]`；1A 新增的親屬、出處探針同樣不可留在 failing 裡。
- **R4 之後的文件更新（U3）**，行號以 2026-10-05 為準。現行圖譜的數字與機制改成 250,418 → 250,366、supplementary 142 → 158、curated 916 → 932、curated 由 `r.curated` 旗標判別；總關係數 319,988 也會變（1A 同時改語意邊），以 R4 時 prod 的實數為準：
  - 文件不靠行號，用 grep 找（1A 的文件改動會讓行號移動）：
    ```bash
    grep -n '250,418\|319,988\|142 條\|916 條' README.md evaluation/README.md docs/*.md
    ```
    描述現行圖譜的要改：docs/ARCHITECTURE.md :141、:328、:336、:344、:346；docs/kg_construction_overview.md :8、:38、:102、:108、:186、:187、:399（末段「圖譜數字時點」：日期與 319,988 一起改成 R4 時 prod 的實數）；README.md :224；evaluation/README.md :273（curated 條數）。記錄 P0 歷史的保留原值：docs/ARCHITECTURE.md :287、:398；docs/kg_construction_overview.md :316；docs/kg_optimization_progress.md :25。docs/build_database.md 與 docs/staging_promotion.md 的命中是 W1 前後的對照值，不改。
  - 論文中描述現行圖譜的地方：paper/latex/sec3_kg.tex :164-185（1A：不再以 R2、R5 補反向邊，先經 Step 6.05 後處理；語意邊帶 source、run_id 與 `confidence_raw`，不再帶 `confidence`；772 條規則邊、752 條反向邊的計數）、:199、:210-212、:263、:268、:290、:308；sec7_discussion.tex :316（事件層覆蓋率 84%／75.5%：10.3 退場後約 34.0%／31.4%，2A 補回之前）；sec4_retrieval.tex :234、:287-292；main.tex :62；sec1_intro.tex :62；appendix.tex :147-150（回滾說「每種邊用一個謂詞就能刪」，但 curated 邊現在也帶 tsk 與 votes，已不成立）。
  - 實驗當時的數值保留，加註資料版本：sec6_experiments.tex :114、:312-316（1A：P0 的共現搶救，10.3 已退出預設鏈）、:317、:481。

### W1 的 K8 對照組：entity_path（第 1A 批，R4 之後，只報告）
第 1 批計畫 §5.2 與 K8：entity_path 的對照組是 staging-P1（6.05 `--rules none`，仍跑 10.3），實驗組是 1A 的建置，也就是 R2 量的 `ep_w1`。P1 重建兩次，兩次之間的差就是雜訊地板。事前登記：500 題 Δvrec ≥ −0.005，只報告；沒達到也不讓 10.3 回到預設鏈，事件層由 2A 補。
- **為什麼排在 R4 之後**：staging 只有一個，P1 會整個覆寫它。排在第 2 步之前，會毀掉 residuals_expect 要讀的第 0 批 staging，而兩組要用同一個 `:w1` image（`backend_w1.id`），它要到 R2 才建；排在 R2 與升版之間，則要再重建一次 1A 才能升版。R4 之後 staging 的 1A 圖已經用不到，升版用的 dump 在 `bak/$D/promote/`。
- **P1 的建置**（staging 的 shell、主 checkout，照「執行前檢查」）：照 [build_database.md](build_database.md) 的 W1 重灌鏈整條重建，只換四處：6.05 改跑 `--rules none`、寫到另一組檔（不覆寫登記的 relations_clean）；6.1 改匯入那一組檔，之後的兩次 `--replace` 與 props 摘要不跑（那是 W1 的冪等檢查：不帶檔名的 `--replace` 會改匯入登記的 relations_clean，摘要也會覆寫 R2 的 `bak/$D/props_*.txt`）；10.2 之後、10.4 之前加跑 10.3；10.6 不當閘門（P1 本來就過不了 H3、H11），validate_kg 的報告寫到 `bak/$D/k8/`（第二次是 `validate_p1b.json`），不可覆寫 R2 的 `bak/$D/validate_staging_w1.json`（R2 已把它的 sha256 補進 SHA256SUMS），接在後面的 `jq -e` 也不跑。
  ```bash
  uv run --project scripts python -m scripts.relation_extraction.relation_postprocess --rules none \
    --out output/relations_p1.jsonl --report output/relations_p1.report.json
  uv run --project scripts python scripts/import_relations_neo4j.py output/relations_p1.jsonl
  uv run --project scripts python scripts/backfill_event_relations.py --legacy-cooccurrence
  mkdir -p bak/$D/k8
  uv run --project scripts python scripts/validate_kg.py --live --target staging --json > bak/$D/k8/validate_p1a.json   # 10.6；第二次 P1 改寫 validate_p1b.json
  ```
- **量測**：第一次 P1 建好之後，照「W1 升版第 1、2 步之間」第一段啟動 backend-staging（印出 `both arms run :w1` 才往下），量 `ep_p1a`；第二次 P1 建好之後量 `ep_p1b`。兩次之間 backend-staging 不必重啟：backend 只快取 event_registry，讀的是 image 裡的靜態檔。參數與 `ep_w1` 完全相同，第二行要等第二次 P1 建好才跑：
  ```bash
  (cd evaluation && rm -f results_quick/ep_p1a.json \
    && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_p1a)
  (cd evaluation && rm -f results_quick/ep_p1b.json \
    && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_p1b)
  (cd evaluation && uv run python ab_compare.py results_quick/ep_p1a.json results_quick/ep_p1b.json --label w1_ep_floor)
  (cd evaluation && uv run python ab_compare.py results_quick/ep_p1a.json results_quick/ep_w1.json --label w1_ep_p1a)
  (cd evaluation && uv run python ab_compare.py results_quick/ep_p1b.json results_quick/ep_w1.json --label w1_ep_p1b)
  ```
- **報告**（記進 W1 紀錄）：Δvrec（`verse_recall_at_k` 那一列）的平均、95% CI 與勝負題數 W/L，`[legacy]`、`[expanded]`、`[all]` 分開記；1A 對兩次 P1 的 Δ 與雜訊地板（P1 對 P1）並列。touched 的題先用同樣條件重問，排除 intent LLM 的取樣雜訊（W0 的 GENERAL_BIBLE_QUESTION_016）。量完照 R2 第 3 項停掉 backend-staging；staging 留在 P1 的狀態，W2 的重建會整個取代它。

## R5 回滾
本節的 `docker compose` 一律在**主 checkout、沒有 source staging.env 的乾淨 shell** 執行（在 worktree 裡，compose 的專案名會變成 worktree 的目錄名，image 與 volume 都不是 production 的），而且加 `--no-deps`：staging 的 shell 帶著 `POSTGRES_DB=bible_rag_staging`，compose 收斂 backend 的依賴時會把它插值進 production 的 postgres 服務並重建該容器（見「執行前檢查」；docker-compose.staging.yml 也有同樣的警告）。`--no-deps` 讓 compose 只動 backend。
- Neo4j：照 bak/README.md 的「還原指令」，載回 `bak/<日期>/neo4j/neo4j.dump`（停機約 1 分鐘）。
- PG：用 R0 存的 `bak/<日期>/postgres/entity_tables.sql` 換回兩張表，指令同 R3 第 2 步。
- Qdrant：把 `QDRANT_ENTITY_COLLECTION` 切回上一個 collection 名，再重新建立 backend 容器。
- 程式碼與 registry：`git revert`，再 `docker compose up -d --no-deps --build backend`。
- **第 1 批 W1：image 不可先於資料回滾。** 資料可以單獨回滾，因為 W1 升版第 1 步的 image 新舊資料都能正確排序（過渡的 coalesce）。image 退回 `kg-pre-batch1-w1` 只能與資料回滾一起做，或在資料回滾之後做，不能在資料之前。順序顛倒時，舊 image 讀新資料：924 條帶 votes 的 curated 邊會被舊的 999 規則當成 TSK，影響 760/2,779 個單一種子、86/262 個代理種子集。image 有任何變動（重建、退回 tag）之後，碰資料之前都要先重跑 deploy-guard；退回舊 image 之後 deploy-guard 必然失敗，這時只能載入 W1 之前的 dump。
  資料回滾（上面 Neo4j 那一項載回 R0 的 dump）之後、退回 image 之前，先在同一個乾淨的 shell 確認 prod 的資料回到 R0：xref 的預測要再等於規劃時對升版前 prod 驗過的 `pred_trans.json`（同升版第 1 步第三段），節點與關係數要等於 R0 備份時的 13,589／319,988（[bak/README.md](../bak/README.md) 的還原後驗證）。沒有印出最後一行就停，不退 image：
  ```bash
  (
  set -eu -o pipefail
  : "${D:?set D to the W1 R0 date}"
  test "$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j)" = healthy
  uv run --project scripts python scripts/tools/xref_probe.py predict --target prod --seeds bak/$D/xref_probe/seeds.json --out bak/$D/xref_probe/pred_prod_r5.json
  uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_r5.json \
    --measured bak/20261005_w1_1b_evidence/pred_trans.json
  docker exec bible_rag_neo4j bash -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#*/}" --format plain "MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() RETURN nodes, count(r)"' > bak/$D/r5_counts.txt
  grep -x '13589, 319988' bak/$D/r5_counts.txt
  echo 'prod data back to R0'
  )
  ```
  R4 之後才回滾時，另 `git revert` R4 的 ratchet 與合併允許清單那個 commit（「W1 的交叉引用升版後檢查」），基準檔才回到升版前。退回 image：
  ```bash
  (
  set -eu -o pipefail
  : "${D:?set D to the W1 R0 date}"
  PRE=$(cat bak/$D/images/backend_kg-pre-batch1-w1.id)
  docker image inspect "$PRE" >/dev/null || gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz | docker load
  docker tag "$PRE" bible_rag-backend:kg-pre-batch1-w1
  docker tag bible_rag-backend:kg-pre-batch1-w1 bible_rag-backend:latest
  docker compose up -d --no-deps --no-build --wait --wait-timeout 300 backend
  test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$PRE"
  echo 'prod runs kg-pre-batch1-w1'
  )
  ```
  `D` 是 W1 R0 的日期；與第 1 步一樣，任何一行失敗整段就停，沒有印出最後一行就是沒有退回。退回的對象是第 1 步記下的 id，不是 tag：image 已被清掉時從存檔載回（`docker load` 連 tag 一起還原；載入前可用 `bak/$D/SHA256SUMS` 核對），接著把 tag 改指回這個 id，所以 tag 被改指過也退回對的 image。載回之後仍找不到這個 id，`docker tag` 會失敗：停下來查，不要改用現有的 tag。`--no-build`，不加 `--build`，才會用剛退回的 tag；最後確認 prod 跑的是這個 id。
- 第 1D 批起有了編譯快照（`output/kg_snapshots/<ts>/`）：回滾等於重新載入上一份快照，比還原 dump 快，而且三庫一定一致。

## 收尾
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging neo4j-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml rm -f backend-staging neo4j-staging
docker exec bible_rag_postgres dropdb -U bible bible_rag_staging
docker volume rm bible_rag_neo4j_staging_data bible_rag_neo4j_staging_logs   # 確定不再需要時
```
- 已升版的 `bible_entities_vN` 就是 production 的 entity collection，不要刪。沒有升版的 staging collection 用 `curl -X DELETE http://localhost:6333/collections/<名稱>` 刪除，刪之前確認它不是 `.env` 正在用的名稱。
