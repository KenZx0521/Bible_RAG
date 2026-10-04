# Staging 與升版流程

> 從 [build_database.md](build_database.md) 拆出（2026-10-04，內容未刪減）。建庫各步驟（Step 0–10）、「執行順序」的重灌鏈與 Step 10.6 品質閘門都在該檔；本檔是 staging 建置與升版（R0–R5）的流程。文中的「計畫」指 [records/2026-10-04_kg_data_layer_fix_plan.md](records/2026-10-04_kg_data_layer_fix_plan.md)。

> 依據：[records/2026-10-04_kg_data_layer_fix_plan.md](records/2026-10-04_kg_data_layer_fix_plan.md) §3.5、§3.7（D1：staging 全量重建後升版，不做線上增量補丁）。每批升版都走 R0 → R1 → R2 → R3 → R4，出事走 R5。**第 0 批只做 R0、R1、R2**（在 staging 上做等價重建並列出 diff），不升版。

## 拓撲

| 庫 | production | staging | 隔離方式 |
|---|---|---|---|
| Neo4j | `bible_rag_neo4j`，bolt 7687／http 7474，volume `bible_rag_neo4j_data` | `bible_rag_neo4j_staging`，bolt 7688／http 7475，volume `bible_rag_neo4j_staging_data` | 另起容器（Neo4j community 只有單一使用者資料庫） |
| PostgreSQL | 資料庫 `bible_rag` | 資料庫 `bible_rag_staging`（同一個 `bible_rag_postgres` 容器） | 資料庫名 |
| Qdrant | entity collection `bible_entities` | `bible_entities_vN`（第 0 批用 `bible_entities_v2`） | collection 名。段落 collection（`bible_embeddings`、`bible_embeddings_hybrid`）共用，不重建 |
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
| `QDRANT_ENTITY_COLLECTION` | `bible_entities` | `bible_entities_v2`（之後各批：`bible_entities_vN`） | |
| `QDRANT_COLLECTION`、`QDRANT_HYBRID_COLLECTION` | `bible_embeddings`、`bible_embeddings_hybrid` | 不設 | 只有 Step 4／4.1 讀；staging 不跑這兩步（`KG_TARGET=staging` 時兩者直接拒絕） |

程式碼裡其餘的值都只是變數沒設時的 fallback，與 docker-compose.yml 的預設值相同（localhost、5432、bible_rag、bible、bible_password、bolt://localhost:7687、neo4j、neo4j_password、6333）。

**盤點表**（2026-10-04。✓ 表示該庫的連線設定全部讀環境變數；— 表示不連該庫）

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
| import_relations_neo4j.py | 6.1 | ✓ | — | — | 無 |
| relation_extraction/desc_generator.py | 7 | ✓（`Neo4jConfig.from_env`） | — | — | 無。產生與 replay 都在連線前呼叫 `kg_target.assert_target("neo4j")` |
| embed_entities.py | 8 | ✓ | — | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 已修正 port。`--qdrant-host`、`--qdrant-port` 可再覆寫 |
| import_tsk_crossrefs.py | 9 | ✓ | — | — | 無 |
| backfill_aliases.py | 10.1 | ✓ | — | — | 無（只寫 Neo4j） |
| cleanup_noise_entities.py | 10.2 | ✓ | ✓ | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 已修正 port，以及 PG 的 user/password fallback：原本是 `postgres`／空字串，沒有 .env 時連不上，而連不上時只印警告、靜默跳過 PG 同步 |
| backfill_event_relations.py | 10.3 | ✓ | — | — | 無（第 1A 批退場） |
| backfill_head_events.py | 10.4 | ✓ | ✓ | HOST、PORT→HTTP_PORT（`qdrant_endpoint`）；collection 取自 embed_entities（`QDRANT_ENTITY_COLLECTION`） | 無 |
| backfill_manual_patches.py | 10.5 | 經 backfill_head_events | 經 backfill_head_events | 經 backfill_head_events（`get_qdrant`、`reembed_qdrant`） | 無 |
| export_event_registry.py | 10.6、export | 經 backfill_head_events.get_neo4j | — | — | 無。輸出檔固定為 backend/data/event_registry.json（git 追蹤的檔案，不是資料庫） |
| backfill_verse_mentions.py | 退役 | ✓ | — | — | 不在鏈中 |
| tools/export_live_state.py | R0 | ✓（`Neo4jConfig.from_env`；只用 read 交易） | — | — | 無（第 0 批新增）。`--promote` 不連庫 |
| check_identity.py | 10.6、R4 | ✓ | ✓ | HOST、PORT→HTTP_PORT、`QDRANT_ENTITY_COLLECTION` | 第 0 批新增，唯讀。`--target staging` 只讀 shell 變數（預設 bolt://localhost:7688、bible_rag_staging；Qdrant 沒有預設），解析到 production 會拒絕；`--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、值與 .env 不同、7688、bible_rag_staging）時拒絕 |
| validate_kg.py | 10.6、R4 | 經 check_identity 的 `--target` 解析 | 同左 | 同左 | 第 0 批新增，唯讀；兩個方向的守門同 check_identity |
| tools/diff_kg.py | R2 | `--a`、`--b` 各選 prod／staging（預設 `--a prod --b staging`），經 check_identity 的 `--target` 解析 | — | — | 第 0 批新增，唯讀，只比 Neo4j；`--allow` 讀允許清單。prod 端會拒絕 staging 的 shell，只能在乾淨的 shell 跑，staging 端此時用預設的 bolt://localhost:7688（改過 `NEO4J_STAGING_BOLT_PORT` 時無法指定） |

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
1. `git tag kg-pre-<批次>`（例：`kg-pre-batch0`）作為 run-of-record。
2. 三庫備份：照 [bak/README.md](../bak/README.md)「重新備份」建 `bak/<日期>/`。PG 做 `pg_dump -Fc` 加 globals；Qdrant 三個 collection 各做 snapshot；Neo4j 先 `docker stop -t 60`，再 `neo4j-admin database dump`（停機約 1 分鐘）。
3. 另存 PG 兩張實體表的 plain SQL，R5 換表回滾時使用：
   ```bash
   D=$(date +%Y%m%d)
   docker exec bible_rag_postgres pg_dump -U bible -d bible_rag -t entities -t entity_mentions \
     > bak/$D/postgres/entity_tables.sql
   ```
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

## R1 staging 建置
1. 起 staging Neo4j（第一次會建立空的 volume），並確認 APOC 可用（Step 6.1 與 10.x 依賴它）：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d neo4j-staging
   docker exec bible_rag_neo4j_staging bash -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#*/}" "RETURN apoc.version()"'
   ```
2. 建 PG staging 資料庫。schema 用 scripts/db/schema.sql（2026-10-04 已比對，entities 與 entity_mentions 的定義與 production 相同）：
   ```bash
   docker exec bible_rag_postgres createdb -U bible bible_rag_staging
   docker exec -i bible_rag_postgres psql -U bible -d bible_rag_staging -v ON_ERROR_STOP=1 < scripts/db/schema.sql
   ```
   若已有上一次的 staging 庫，先執行 `docker exec bible_rag_postgres dropdb -U bible --if-exists bible_rag_staging`。**只對 staging 執行。**
3. Qdrant 不需事先建立：8a 的 `embed_entities.py --recreate` 會建出 `bible_entities_vN`；同一個 vN 重跑時，`--recreate` 會清掉上一次 staging 的點。
4. `source scripts/tools/staging.env`，並通過執行前檢查。
5. 依 [build_database.md](build_database.md)「執行順序」的重灌鏈逐步執行（Step 4／4.1 跳過）。
6. 第一次 staging 重建要實測各步耗時並填入下表；目前的耗時都是推論（計畫 §8）：

   | 步驟 | 實測耗時 |
   |---|---|
   | 0、1(merge)、3、5、6.1、8a、9、10.1–10.5、7(replay)、8b、10.6、export --check | 2026-10-04 第 0 批實測：0=5s、3=5s、5=28s、6.1=1s、8a=26s、9=6s、10.1–10.5=19s、7=1s、8b=24s、10.6=6s，合計約 2 分鐘；`--stage ner` 另需 34 分鐘（1(merge) 本身 <10s） |

## R2 驗證
1. 10.6 依該批的判準通過（見 [build_database.md](build_database.md) Step 10.6），而且 `export_event_registry.py --check` 結束碼 0。
2. 通過該批的驗證門檻（計畫 §4；第 1 批起見 [records/2026-10-04_kg_data_layer_fix_plan_batches.md](records/2026-10-04_kg_data_layer_fix_plan_batches.md)）。與 live 的 diff 要逐項列出並解釋（預期中的差異見 [build_database.md](build_database.md) Step 10.6）。staging 對 live 的比對用 diff_kg，在**沒有 source staging.env 的乾淨 shell**（新開的終端機）跑；10.6 的兩項則要在 staging 的 shell 跑：
   ```bash
   uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch0.yaml --json
   ```
   - `--a`、`--b` 各選 prod 或 staging（預設就是 prod 對 staging），只比 Neo4j：labels、relationships、ee_edges（`TYPE phase=P source=S`）、mentions、xrefs、entity_ids、descriptions（逐字）、aliases（集合）、registry。prod 端的守門會拒絕還帶著 staging 設定的 shell（結束碼 1，安全的失敗）。
   - 允許清單放 `config/kg_diff_allow_<批次>.yaml`（git 追蹤，R2 時依實際 diff 建立，與該批紀錄一起 commit）。檔案只有 `version: 1` 與 `allow` 清單；每條要有 section、key（glob）、reason，計數類最多再加一個 `delta`（b − a）或 `max_abs_delta`；未知欄位（例如拼錯的 bound）或型別不對直接報錯，格式見 `diff_kg.py --help`。不在清單內的差異結束碼 1；沒用到的條目會列出，要刪。第 0 批不可放行 descriptions：stale 必須是 0。

   第 0 批的門檻：
   - registry 是 33 個事件；
   - 三庫的 id 集合差為 0（`check_identity --target staging --fail-on id`）；
   - E–E 各 phase 的邊數與 live 相同（diff_kg；允許的差異逐項列出）；
   - 描述 replay 後，staging 與 live 逐字相同（Step 7 報告的 stale、missing 為 0，且 diff_kg 的描述逐字比對無差異）；
   - H1、H2、H7 通過。
3. 起指向 staging 的 backend，跑評估。backend-staging 只依賴 neo4j-staging，postgres、qdrant、ollama 用正在跑的 production 服務：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d backend-staging
   curl -f http://localhost:8001/api/v1/health
   ```
   - evaluation 端把 `BACKEND_URL` 設成 `http://localhost:8001`（環境變數優先於 evaluation/.env）。先跑 quick_retrieval_eval（100 題），有差異再跑 500 題（計畫 §6）。
   - 第 0、1 批的 registry 與字典都不變，硬閘門是：預設組態 500 題的 sources 與 prompt 逐位相同（計畫 §6.3）。
   - backend pytest（含 test_event_registry）照常在 host 的 backend venv 跑，不依賴 staging。
   - backend-staging 用現有 image。要測新的 backend 程式碼，先 `docker compose build backend`，它只更新 image，不動正在跑的 production 容器；但在 R3 之前不要對 production 執行 `up -d`，否則 production 會換上新 image。
   - 驗完停掉：`docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging`。

## R3 升版（第 0 批不做）
順序規則：backend 程式碼的變更要向前相容，先部署 backend，再升資料（例如第 1B 批）；一個缺陷項目一個 commit，各自附探針，validate 失敗時才分得出是哪一項造成。
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
4. 程式碼、registry、字典隨 image 上線：`docker compose up -d --build backend`。backend 沒有 volume mount，只 restart 會跑舊 image；建置要走 uv 快取（README「Docker 建置快取」）。

## R4 升版後檢查
- 在 production 上執行 `validate_kg.py --live --target prod`、`export_event_registry.py --check`、`check_identity.py --target prod`。要在沒有 source staging.env 的新 shell 執行：validate_kg 與 check_identity 的 `--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、store 變數與 .env 不同、Neo4j 7688、bible_rag_staging）時會拒絕並結束碼 1，不會把 staging 當成 prod 報告；export_event_registry 沒有這層防護，只讀 `NEO4J_URI`，在 staging 的 shell 會默默檢查 staging 圖。
- 抽查 /api/v1/entity（計畫 §6.4 列出各批的探針）。

## R5 回滾
- Neo4j：照 bak/README.md 的「還原指令」，載回 `bak/<日期>/neo4j/neo4j.dump`（停機約 1 分鐘）。
- PG：用 R0 存的 `bak/<日期>/postgres/entity_tables.sql` 換回兩張表，指令同 R3 第 2 步。
- Qdrant：把 `QDRANT_ENTITY_COLLECTION` 切回上一個 collection 名，再重新建立 backend 容器。
- 程式碼與 registry：`git revert`，再 `docker compose up -d --build backend`。
- 第 1D 批起有了編譯快照（`output/kg_snapshots/<ts>/`）：回滾等於重新載入上一份快照，比還原 dump 快，而且三庫一定一致。

## 收尾
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging neo4j-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml rm -f backend-staging neo4j-staging
docker exec bible_rag_postgres dropdb -U bible bible_rag_staging
docker volume rm bible_rag_neo4j_staging_data bible_rag_neo4j_staging_logs   # 確定不再需要時
```
- 已升版的 `bible_entities_vN` 就是 production 的 entity collection，不要刪。沒有升版的 staging collection 用 `curl -X DELETE http://localhost:6333/collections/<名稱>` 刪除，刪之前確認它不是 `.env` 正在用的名稱。
