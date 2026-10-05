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
| tools/diff_kg.py | R2 | `--a`、`--b` 各選 prod／staging（預設 `--a prod --b staging`），經 check_identity 的 `--target` 解析 | — | — | 第 0 批新增，唯讀，只比 Neo4j；`--allow` 讀允許清單，`--fail-on-unused`（第 1B 批新增）讓沒用到的條目也算失敗。`--merge-out`（第 1B 批新增）把多個 `--allow` 片段合成一份允許清單，不連庫。prod 端會拒絕 staging 的 shell，只能在乾淨的 shell 跑，staging 端此時用預設的 bolt://localhost:7688（改過 `NEO4J_STAGING_BOLT_PORT` 時無法指定） |
| tools/xref_probe.py | R2、R3、R4 | `predict`、`fingerprint` 的 `--target` 經 check_identity 解析（READ session）；`allow` 固定讀 prod | — | — | 第 1B 批新增，唯讀。`deploy-guard` 只對 backend 容器做 `docker exec … cat`；`seeds`、`expect`、`compare` 不連庫 |

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
7. backend 的回滾 image 不能只靠 `docker tag`：沒有容器引用的 image，即使有 tag 也會被 `docker image prune -a` 刪掉（2026-10-05 已發生過，見 W1 交接紀錄 `docs/records/2026-10-05_kg_w1_handoff.md` §4）。第 1 批 W1 在「W1 升版第 1 步」換 image 之前做：記下 prod 正在跑的 image id、打 tag、用一個停著的容器釘住、`docker save` 到 `bak/$D/images/`，sha256 補進 `bak/$D/SHA256SUMS`。

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
   # 第 0 批（歷史紀錄，見下方「歷史允許清單」）
   uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch0.yaml --json
   # 第 1 批 W1：一份合併的允許清單，沒用到的條目也算失敗
   uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch1w1.yaml --fail-on-unused --json
   ```
   - `--a`、`--b` 各選 prod 或 staging（預設就是 prod 對 staging），只比 Neo4j：labels、relationships、ee_edges（`TYPE phase=P source=S`）、mentions、xrefs、xref_provenance（`source=S curated=C tsk=T` 的邊數，第 1B 批新增）、entity_ids、descriptions（逐字）、aliases（集合）、mention_count（逐實體，第 1B 批新增）、registry。prod 端的守門會拒絕還帶著 staging 設定的 shell（結束碼 1，安全的失敗）。
   - **歷史允許清單不能再當閘門重跑**：`kg_diff_allow_batch0.yaml` 與更早的清單早於 xref_provenance、mention_count 兩段。現在用 batch-0 的清單重跑上面第一行，會因為 mention_count 的 4 筆 K10 殘差不在清單內而結束碼 1；這些檔案只記錄當時的判定。
   - W1 的合併清單 `config/kg_diff_allow_batch1w1.yaml` 由工具產生的片段合成，不手抄：1A 的 `relations_allow.yaml`、`residuals_allow.yaml` 與 1B 的 `xref_allow.yaml`，都在 `config/kg_expect/batch1_w1/`。合併在 YAML 層做，不可用 `cat` 串接：每個片段都是完整的 YAML 文件，各有 `version: 1` 與 `allow:`，串起來後一般的 YAML 載入只留最後一個 `allow:`，其他片段無聲消失（diff_kg 現在遇到重複的鍵直接報錯）。用 `--merge-out` 合併：逐一載入片段，把各自的 `allow` 依序接在同一個 `version: 1` 底下，跨片段重複的 section 與 key 直接報錯，核對合併後的條數等於各片段之和，最後印出合併檔的 sha256。不連庫，任何 shell 都可以跑：
     ```bash
     uv run --project scripts python scripts/tools/diff_kg.py --merge-out config/kg_diff_allow_batch1w1.yaml \
       --allow config/kg_expect/batch1_w1/relations_allow.yaml --allow config/kg_expect/batch1_w1/residuals_allow.yaml \
       --allow config/kg_expect/batch1_w1/xref_allow.yaml
     ```
     合併檔在 [第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §1「W1 步驟」第 2 步（staging 重建）之前組好，印出的 sha256 記進 W1 紀錄；R2 用它跑，第 4 步經 Kay 核可，R4 之後與 ratchet 放同一個 commit；看過 staging 的 diff 之後不可再改（計畫 §3）。一筆差異只會記在第一個比對到的條目上，被前面條目遮住的條目在 `--fail-on-unused` 下也算沒用到，所以片段不可重疊。1B 的片段由下方「W1 的交叉引用檢查」第 1 步的 `xref_probe.py allow` 從期望檔與 prod 的 profile 算出，只含 relationships `CROSS_REFERENCES`、xrefs、xref_provenance 三段，每個不同的鍵一條 exact `delta`。mention_count 段的 4 筆 K10 殘差（第 0 批就有，加了這一段才看得到）只來自 1A 的 `residuals_allow.yaml`，1B 的片段不含。
   - 允許清單放 `config/kg_diff_allow_<批次>.yaml`（git 追蹤）。第 0 批是在 R2 依實際 diff 建立、與該批紀錄一起 commit；第 1 批起預先登錄，不依 R2 的 diff 建立（見上一項）。檔案只有 `version: 1` 與 `allow` 清單；每條要有 section、key（glob）、reason，計數類最多再加一個 `delta`（b − a）或 `max_abs_delta`；未知欄位（例如拼錯的 bound）或型別不對直接報錯，同一個 section 下逐字相同的 key 出現兩次（不論 bound）也直接報錯，片段間的重複在 `--merge-out` 合併時就擋下，不會拖到 R2 才以沒用到的條目出現（只擋逐字重複，互相涵蓋的 glob 仍要人工確認）；同一個 mapping 裡重複的鍵（同一條寫了兩個 `delta`，或 `cat` 串起來的兩個 `allow:`）也直接報錯。格式見 `diff_kg.py --help`。不在清單內的差異結束碼 1；沒用到的條目會列出，要刪。第 0 批不可放行 descriptions：stale 必須是 0。

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
   - backend-staging 用現有 image。要測新的 backend 程式碼，先建 image：`docker compose build backend` 只更新 image，不動正在跑的 production 容器，但會覆寫 production 用的 `latest`，之後任何對 production 的 `up -d` 都會換上新 image。所以第 1 批起改建另一個 tag，做法見下方「W1 的交叉引用檢查」第 3 項。
   - 驗完停掉：`docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging`。

### W1 的交叉引用檢查（第 1B 批）
「模擬等於實測」：`xref_probe.py` 離線算出 backend 應該回傳的 xref 候選，每列是 [id, hop, curated, weight]；backend 容器內的 `probes.xref_measure` 經真正的 retriever 量出同一批種子的結果，兩者逐列比對。種子是 2,779 個段落各當一次單一種子（多跳與 legacy 一跳），加上 262 題的代理種子集，共 5,820 個 key。compare 另外檢查 12 條哨兵：votes ≥ 999 的 3 對 TSK 邊，兩個方向都必須是 curated false、權重 0.60。產物放 `bak/$D/xref_probe/`（`D` 沿用 R0 的日期，每個檔約 2 MB），sha256 記進 W1 紀錄。規劃時的獨立 oracle 見 [w1_1B 歸檔](records/2026-10-04_kg_fix/batch1/w1_1B/README.md)，大檔在 `bak/20261005_w1_1b_evidence/`。本節與 R3、R4、R5 的 W1 段落裡，「第 1 批計畫」指 [records/2026-10-04_kg_batch1_plan.md](records/2026-10-04_kg_batch1_plan.md)。

1. **建置之前**：Step 0、check_step0、validate_output 都通過後，在 Step 5 之前，由新的 Step 0 輸出產生期望檔，也就是離線重放 Step 5 與 Step 9 會建出的 CROSS_REFERENCES。期望檔不可事後回填（第 1 批計畫 §3）：
   ```bash
   mkdir -p bak/$D/xref_probe config/kg_expect/batch1_w1
   uv run --project scripts python scripts/tools/xref_probe.py expect --output-dir output --tsk output/cross_references_tsk.txt \
     --out config/kg_expect/batch1_w1/xref.json --edges-out bak/$D/xref_probe/expected_edges.jsonl
   uv run --project scripts python scripts/tools/xref_probe.py seeds --pericopes output/pericopes.jsonl \
     --questions docs/records/2026-10-04_kg_fix/batch1/inputs/bench/questions_table.json --out bak/$D/xref_probe/seeds.json
   uv run --project scripts python scripts/tools/xref_probe.py predict --seeds bak/$D/xref_probe/seeds.json \
     --edges bak/$D/xref_probe/expected_edges.jsonl --out bak/$D/xref_probe/pred_new.json
   uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_new.json \
     --measured bak/20261005_w1_1b_evidence/pred_new.json
   ```
   預期（2026-10-05 以 W1 的 Step 0 實跑）：expect 印出 `curated_rows 932, attached 924, curated_without_tsk 8, pure_tsk 249,434, total 250,366, votes_edges 250,358` 與 `fingerprint e522411e13c8e867cad36190c9002813b3da9a7d165ef5435d5cc161eff3775f`；seeds 為 5,820 keys（sha256 `674537f3…`）；pred_new 與歸檔的 oracle 比對結束碼 0。期望檔到第 1 批計畫 §1「W1 步驟」第 4 步經 Kay 核可才 commit。

   接著由期望檔產生 1B 的允許清單片段（R2 第 2 項合併清單的一部分）。`allow` 唯讀 prod，跟 diff_kg 一樣要在**乾淨的 shell** 跑：
   ```bash
   uv run --project scripts python scripts/tools/xref_probe.py allow --expect config/kg_expect/batch1_w1/xref.json \
     --out config/kg_expect/batch1_w1/xref_allow.yaml
   ```
   預期（2026-10-05 以同一份期望檔對 prod 實跑）：10 條，relationships `CROSS_REFERENCES` 1 條、xrefs 2 條、xref_provenance 7 條，沒有 mention_count。片段開頭的註解記下期望檔的 sha256 與 fingerprint（不記路徑，同一份期望檔與 prod 重跑得到相同的位元組）；要改就重跑，不手改。與 1A 片段的合併見 R2 第 2 項。
2. **Step 9 連跑兩次**（staging 的 shell，見 [build_database.md](build_database.md) Step 9）：兩次都印出同一個 `fingerprint:`，第二次是 `created 0`。接著對 staging 比對期望檔，結束碼必須是 0（指紋與 xref_provenance 計數都要相同）：
   ```bash
   uv run --project scripts python scripts/tools/xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json
   ```
3. **backend-staging 換成 W1 HEAD 建的 image**（D3 也在這個 image 上跑）。W1 HEAD 建成另一個 tag，不覆寫 production 正在用的 `bible_rag-backend:latest`（W0 紀錄的做法），用一個不進 git 的 compose override 指定 tag。deploy-guard 比對的是本 checkout 在 HEAD 已提交的檔案（`git show HEAD:`，不看工作目錄），所以要在建 image 的同一個 checkout 跑，而且先 commit 再建 image（沒提交的改動即使建進 image 也會被擋下）：
   ```bash
   printf 'services:\n  backend:\n    image: bible_rag-backend:w1\n  backend-staging:\n    image: bible_rag-backend:w1\n' > /tmp/w1_image.yml
   docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml build backend
   mkdir -p bak/$D/images
   docker image inspect -f '{{.Id}}' bible_rag-backend:w1 > bak/$D/images/backend_w1.id
   docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml up -d backend-staging
   test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$(cat bak/$D/images/backend_w1.id)" && echo 'staging runs :w1'
   uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend_staging
   docker exec -i bible_rag_backend_staging .venv/bin/python -m probes.xref_measure \
     < bak/$D/xref_probe/seeds.json > bak/$D/xref_probe/measured_staging.json
   uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_new.json \
     --measured bak/$D/xref_probe/measured_staging.json
   ```
   `backend_w1.id` 是這個 image 的 id，記進 W1 紀錄：D3 與這裡的量測都在它上面跑，升版第 1 步上線的必須是同一個 id（不重建）。沒有印出 `staging runs :w1` 就停。deploy-guard 結束碼 0：容器裡的 `database/neo4j_db.py`、`utils/retrieval/cross_ref_retriever.py`、`probes/xref_measure.py` 與本 checkout 的 HEAD 逐位元相同，讀 `r.curated`，沒有 999 哨兵。compare 結束碼 0：5,820 個 key 0 列不同，哨兵 12/12。

## R3 升版（第 0 批不做）
順序規則：backend 程式碼的變更要向前相容，先部署 backend，再升資料（例如第 1B 批）；一個缺陷項目一個 commit，各自附探針，validate 失敗時才分得出是哪一項造成。

第 1 批 W1 不照下面 1–4 的順序，改照下方「W1 升版第 1 步」「W1 升版第 2 步」：第 1 步只換 backend image，第 2 步才做這裡的第 1 步（Neo4j）。W1 的 PG、Qdrant、.env 都不動，所以不做第 2、3 步；第 4 步已在 W1 升版第 1 步完成。
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
gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part | tar -tf - >/dev/null
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
  && uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/smoke20_ids.txt --label w1_step1_smoke \
  && python3 -c "import json; d = json.load(open('results_quick/w1_step1_smoke.json')); print(d['n'], d['n_invalid'], sorted(q for q, e in d['per_question'].items() if e['strategy_errors']))")
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
- **第一段只做一次**：prod 已經在跑 `:w1`，或 id 檔、存檔已經存在（`noclobber` 拒絕覆寫）時就停。所以第一段重跑時，不會把 W1 的 image 記成回滾 image，不會覆寫存檔，也不會在 SHA256SUMS 多補一行。第一段中途失敗時 prod 還沒換 image：查明原因後 `docker rm bible_rag_backend_kg_pre_batch1_w1`，刪掉 `backend_kg-pre-batch1-w1.id` 與 `.tar.gz.part`，再重跑第一段。
- **回滾 image 在換 image 之前保住**（R0 第 7 項）：停著的容器 `bible_rag_backend_kg_pre_batch1_w1` 讓 `docker image prune -a` 刪不掉它；`docker system prune` 會先刪停著的容器，所以還要 `docker save`。`pipefail` 讓 save 中斷時整段失敗；先寫到 `.part`，`tar -tf` 從頭讀到尾沒有錯誤才改名、記 sha256，所以正式檔名只會是完整的存檔。image 的內容約 7 GB，存檔與核對要幾分鐘，prod 照常服務。這個容器留到下一批 R0 之後才 `docker rm`。
- **上線的是 R2 測過的 image，不重建**：第 1 批計畫 §1「W1 升版」第 1 步原寫 `up -d --build backend`，改為把 R2 建的 `bible_rag-backend:w1` 改 tag 成 `latest`。第二段先確認第一段做完（SHA256SUMS 有存檔那一行、停著的容器還釘著回滾 image），而且 `:w1` 仍是 R2 記下的 `backend_w1.id`，才改 tag、`up`。`--no-build`：image 不在就失敗，不會在 prod 上重建；`--no-deps`：只動 backend（理由見 R5 開頭）；`--wait`：等 healthcheck 通過才返回（start_period 120 秒），unhealthy 或超過 300 秒時結束碼不是 0，整段就停。最後確認 prod 容器跑的是 `backend_w1.id`。
- **煙霧測試**：20 題預設檢索（只有 event_registry），通過條件是印出 `20 0 []`（見[題號檔 README](../evaluation/experiments/2026-10-05_kg_w1/README.md)）。先刪掉上一次的結果檔，執行與檢查用 `&&` 串起來，舊檔不會讓檢查假性通過。
- **deploy-guard** 結束碼 0。不是 0 就先查 image，不往下做。
- **唯一的閘門是精確比對**：兩個 compare 結束碼都是 0。第一個是 prod 的實測對預測：5,820 個 key 0 列不同，哨兵 12/12；第二個是 `pred_prod_step1.json` 對規劃時歸檔的 `bak/20261005_w1_1b_evidence/pred_trans.json`（2026-10-05 對當時的 prod 已驗證 0/5,820）。這個 image 帶上了 087ab0d（W1-0 的 md5 平手，prod 現行的 9bc112a6 還沒有）、1B-C1（讀 `r.curated`，刪除 999 哨兵）、`backend/probes/`，以及兩個串流的全部 scripts/ 與 bible_chunking/ 改動（都 COPY 進 image）。所以**不要拿 opt-in 的線上行為與 9bc112a6 比**：光是 md5 平手就讓約 1,279/2,779 個單一種子、57/262 個代理種子集的 id 集合改變；相對於 087ab0d 的 Cypher，C1 本身只改 5 個單一種子（只有權重）與 1/262 個種子集。
- W1 紀錄要寫明：第 1 步上線的是 087ab0d 加 C1，判準是這裡的精確比對；並記下 R2 的 `backend_w1.id`、第 1 步之後 prod 容器的 image id（兩者必須相同）、回滾 image 的 id（`backend_kg-pre-batch1-w1.id`，升版前是 9bc112a6…），以及回滾存檔的 sha256。

### W1 升版第 1、2 步之間：opt-in xref A/B（只報告）
第 1 批計畫 §5.2：同一個 W1 image 分別接舊資料（prod，第 1 步之後）與新資料（backend-staging），各跑一次 500 題，兩邊參數完全相同。kg_xref 的 68 題要在 500 題裡才算得到：
```bash
cd evaluation
uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_old_w1
BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_new_w1
uv run python xref_ab_slice.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json --label w1_xref
```
- 結束碼 2 是防呆（兩邊的策略、top_k、metric_k、metric_version 不同，或段落沒有 gold、found_by），不存報告。
- 結束碼 3 是 touched 題數超過 `--max-touched`（預設 34）：先停下來查，再決定要不要做第 2 步。預期 touched 約 17 題以下；kg_xref「只經 xref 到達 gold」預期沒有增益（模擬 14 → 14）。這不是閘門。
- touched 的題先用同樣條件重問，排除 LLM 取樣雜訊：W0 的 legacy-100 有 1 題（GENERAL_BIBLE_QUESTION_016）只因 intent LLM 取樣就換了 top-5（第 1 批計畫 §9）。

### W1 升版第 2 步：載入資料，第一個指令是 deploy-guard
```bash
uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend
```
- 結束碼不是 0 就停，不載入 dump：prod 容器跑的不是本 checkout HEAD 建的、讀 `r.curated` 的 image（例如第 1 步之後被重建或退回過），新資料會被舊規則排序（第 1 批計畫 §2.2 的風險；部署順序顛倒的影響見 R5）。
- 每個 `docker exec`、`git show` 最多等 30 秒。docker daemon 或容器沒有回應時，印出 `timed out after 30 s` 並以結束碼 1 結束，不會卡住：先查 daemon 與容器，同樣不載入。
- 第 1、2 步可能相隔數小時，所以即使第 1 步剛跑過也要重跑。
- 通過後才做上面 R3 第 1 步（Neo4j dump／load，停機約 1 分鐘）。載入資料之後不要再建 image；image 一有任何變動，先重跑 deploy-guard 再碰資料。

## R4 升版後檢查
- 在 production 上執行 `validate_kg.py --live --target prod`、`export_event_registry.py --check`、`check_identity.py --target prod`。要在沒有 source staging.env 的新 shell 執行：validate_kg 與 check_identity 的 `--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、store 變數與 .env 不同、Neo4j 7688、bible_rag_staging）時會拒絕並結束碼 1，不會把 staging 當成 prod 報告；export_event_registry 沒有這層防護，只讀 `NEO4J_URI`，在 staging 的 shell 會默默檢查 staging 圖。
- 抽查 /api/v1/entity（計畫 §6.4 列出各批的探針）。

### W1 的交叉引用檢查（第 1B 批）
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
  寫入 `config/kg_quality_baseline/`。1B 移動的指標：`--ratchet` 的 H8.no_provenance 916 → 0、H8.unflagged 250,418 → 0、R4.misaligned 59 → 0、R4.misaligned_any_verse 62 → 0，以及 `--accept` 的 R11（249,502 → 250,358）；W、R1 屬 1A。同一個 commit 裡，PROBES 的 failing 名單拿掉 `xref-heb1-0-not-curated-psa2` 與 `xref-rev20-not-curated-isa65`，新的 xref 探針不可留在 failing 裡。
- **R4 之後的文件更新（U3）**，行號以 2026-10-05 為準。現行圖譜的數字與機制改成 250,418 → 250,366、supplementary 142 → 158、curated 由 `r.curated` 旗標判別：
  - 文件：docs/ARCHITECTURE.md :328、:336；docs/kg_construction_overview.md :108、:186；evaluation/README.md :269（curated 條數）。
  - 論文中描述現行圖譜的地方：paper/latex/sec3_kg.tex :199、:210-212、:263、:268、:290、:308；sec4_retrieval.tex :234、:287-292；main.tex :62；sec1_intro.tex :62；appendix.tex :147-150（回滾說「每種邊用一個謂詞就能刪」，但 curated 邊現在也帶 tsk 與 votes，已不成立）。
  - 實驗當時的數值保留，加註資料版本：sec6_experiments.tex :114、:317、:481。

## R5 回滾
本節的 `docker compose` 一律在**主 checkout、沒有 source staging.env 的乾淨 shell** 執行（在 worktree 裡，compose 的專案名會變成 worktree 的目錄名，image 與 volume 都不是 production 的），而且加 `--no-deps`：staging 的 shell 帶著 `POSTGRES_DB=bible_rag_staging`，compose 收斂 backend 的依賴時會把它插值進 production 的 postgres 服務並重建該容器（見「執行前檢查」；docker-compose.staging.yml 也有同樣的警告）。`--no-deps` 讓 compose 只動 backend。
- Neo4j：照 bak/README.md 的「還原指令」，載回 `bak/<日期>/neo4j/neo4j.dump`（停機約 1 分鐘）。
- PG：用 R0 存的 `bak/<日期>/postgres/entity_tables.sql` 換回兩張表，指令同 R3 第 2 步。
- Qdrant：把 `QDRANT_ENTITY_COLLECTION` 切回上一個 collection 名，再重新建立 backend 容器。
- 程式碼與 registry：`git revert`，再 `docker compose up -d --no-deps --build backend`。
- **第 1 批 W1：image 不可先於資料回滾。** 資料可以單獨回滾，因為 W1 升版第 1 步的 image 新舊資料都能正確排序（過渡的 coalesce）。image 退回 `kg-pre-batch1-w1` 只能與資料回滾一起做，或在資料回滾之後做，不能在資料之前。順序顛倒時，舊 image 讀新資料：924 條帶 votes 的 curated 邊會被舊的 999 規則當成 TSK，影響 760/2,779 個單一種子、86/262 個代理種子集。image 有任何變動（重建、退回 tag）之後，碰資料之前都要先重跑 deploy-guard；退回舊 image 之後 deploy-guard 必然失敗，這時只能載入 W1 之前的 dump。退回 image：
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
