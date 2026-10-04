# Bible RAG 建庫管線（Step 0–10）

## 環境設定

使用 uv 管理 scripts 的 Python 依賴：
```bash
# 在專案根目錄執行，安裝所有 scripts 依賴
uv sync --project scripts
```

### scripts 測試

scripts/ 的測試放在 `scripts/tests/`，以 `scripts/tests/run.sh` 執行。它用 scripts 的 venv，pytest 借自 evaluation 的 venv（scripts 的 venv 沒有 pytest，加進去就得重鎖 scripts/uv.lock）：
```bash
scripts/tests/run.sh               # 全部
scripts/tests/run.sh -q -k step0   # 其餘參數照傳給 pytest
```
backend 與 evaluation 的測試各自在 `backend/tests/`、`evaluation/tests/`，不由這支執行。

## 從零重建 Checklist（fresh clone）

在全新機器 clone 後、跑 Step 0–10 之前，依序完成本節。**現機重灌**（`output/` JSONL 俱在）只需確認 0.2/0.3，然後走本節末「執行順序」的重灌鏈。

### 0.1 Git 內已備，不需重跑

- `bible_md/`（66 卷）與 `bible_pdf/`（66 卷）皆已 git-tracked —— **不需**跑 `scripts/convert_bible_pdf.py`（其輸入/輸出路徑 hardcode 在 repo 外，屬歷史工具）
- `config/relations/*.yaml`、`config/curated/manual_graph_patches.jsonl`、`config/step0_sha.json`（Step 0 sha 基準）、`scripts/uv.lock` 皆已 git-tracked
- `output/` 整個被 gitignore：所有 JSONL 產物需由管線重新產生。LLM 產物（`output/frozen/`、relations*.jsonl、entities／mentions、checkpoint、TSK 原始檔）重跑必有漂移，只能從備份還原（「Staging 與升版流程」R0 的 `llm_artifacts.tgz`）

### 0.2 建立 .env（不進 git；組態即建庫結果的一部分）

```bash
cp .env.example .env   # 再填入 ANTHROPIC_API_KEY 等秘密值
```

對建庫結果有決定性影響、且與程式碼 fallback **不同**的 key（`.env.example` 已含，勿刪）：

| Key | 值 | 影響 |
|-----|-----|------|
| `ENTITY_EXTRACT_OLLAMA_MODEL` | `gemma4:31b-it-q8_0` | Step 1 Phase 4；code fallback 是 `gemma3:4b`，漏設會用小一個量級的模型抽實體 |
| `DESC_OLLAMA_MODEL` | `gemma4:26b-a4b-it-q8_0` | Step 7；code fallback 是 `gemma4:e4b-it-q8_0` |
| `HYBRID_SEARCH_ENABLED` | `true` | 查詢期走 hybrid collection；backend code 預設 `false` |

### 0.3 啟動資料庫服務（⚠ 不要一次 up 全部）

```bash
docker compose up -d postgres qdrant neo4j ollama
```

**backend 必須留到管線跑完最後**才 `docker compose up -d --build backend`：backend 服務 bind-mount `./output/bm25_vocabulary.json`，檔案尚不存在時先起 backend，Docker 會在 host 建出同名**目錄**，Step 2.1 寫檔會直接失敗。

- PG volume 為空時 `scripts/db/schema.sql` 自動建表（docker-entrypoint-initdb.d）
- Neo4j APOC 已由 compose 配置（`NEO4J_PLUGINS: ["apoc"]`），Step 6.1 與 Step 10 重放鏈依賴它
- compose 的 ollama 服務要求 NVIDIA container runtime；無 GPU 機器 `up` 會直接失敗

### 0.4 Ollama 模型（不會自動 pull，volume 是空的）

```bash
docker exec ollama ollama pull gemma4:31b-it-q8_0      # Step 1 Phase 4 + Step 6 R4
docker exec ollama ollama pull gemma4:26b-a4b-it-q8_0  # Step 7
```

### 0.5 Python 環境

```bash
uv sync --project scripts   # BGE-M3 / CKIP 權重於首次執行時自動從 HuggingFace 下載
```

### 0.6 外部資料

- Step 9 的 `output/cross_references_tsk.txt` 需自行下載（來源與授權見 Step 9 前提）

### 執行順序

- **從零**（沒有 staging 的機器）：`process_bible.py` → `check_step0.py`（Step 0 是決定性的，fresh clone 重跑應與 git 追蹤的基準逐位元相同；不符就先查原因）→（選）`validate_output.py` → Step 1 → 2 / 2.1 → 3 → 4 / 4.1 → 5 → 6 → 6.1 → 8a → 9 → 10.1–10.5 → 7 → 8b → 10.6（改用 `--target prod`）→ `export_event_registry.py --check` → `docker compose up -d --build backend`。若能從 R0 的 `llm_artifacts.tgz` 還原 `output/frozen/` 與 NER 半邊（`ner_*.jsonl` 加 `ner_manifest.json`），Step 1 改走 `--stage merge`（缺 NER 半邊時先跑 `--stage ner`）、Step 7 改走 `--replay --fail-on-stale`，就與重灌鏈相同、不必重跑 LLM。
- **重灌**（JSONL 與 `output/frozen/` 俱在；一律先建在 staging，見「Staging 與升版流程」）：

  **0 → 1(merge) → 3 → 4（sha 未變就跳過）→ 5 → 6.1 → 8a(embed) → 9 → 10.1–10.5 → 7(replay --fail-on-stale) → 8b(embed --recreate) → 10.6 → export_event_registry --check**

  | 順序 | 指令（前綴 `uv run --project scripts python`） | 說明 |
  |---|---|---|
  | 0 | `scripts/process_bible.py --input-dir bible_md --output-dir output`，再 `scripts/tools/check_step0.py` | 閘門結束碼不是 0 就停（見 Step 0） |
  | 1 | `scripts/extract_entities.py --stage merge` | NER 半邊＋凍結的 grounded 半邊。merge 要讀 `output/ner_*.jsonl` 與 `ner_manifest.json`：凍結後的第一次、ner_* 沒有 manifest（第 0 批之前產生的），或 NER 程式、字典、embedding_queue 有改時，先跑 `--stage ner`（拒絕條件見 Step 1） |
  | 3 | `scripts/import_postgres.py` | 六張表 |
  | 4 / 4.1 | （跳過） | 閘門通過＝embedding_queue 未變，段落向量與 BM25 都不必重建，Step 2 / 2.1 也不跑。閘門沒過而且是刻意變更時，才重跑 2 / 2.1 / 4 / 4.1 |
  | 5 | `scripts/import_neo4j.py` | 先清空目標 Neo4j 再重建 |
  | 6.1 | `scripts/import_relations_neo4j.py output/relations.jsonl` | 沿用既有 relations.jsonl，不重跑 Step 6 的 LLM |
  | 8a | `scripts/embed_entities.py --recreate` | 只為了讓 10.x 有 collection 可寫：沒有它，10.2（staging 下）刪點、10.4 upsert 都會失敗，10.5 找不到 extracted 點會 SystemExit。這時 P/P/G 描述還是空的，8b 會整個取代 |
  | 9 | `scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt` | |
  | 10.1–10.5 | 見 Step 10 | 10.3 將在第 1A 批退場 |
  | 7 | `-m scripts.relation_extraction.desc_generator --replay --fail-on-stale` | 從正式快取 `output/frozen/descriptions.jsonl` 重放，不呼叫 LLM。必須在 10.5 之後：種子的 titles_sha 是用 live（10.x 之後）的 MENTIONS 算的。stale 或 missing 不是 0 就停（見 Step 7） |
  | 8b | `scripts/embed_entities.py --recreate` | 用最終的描述、aliases、MENTIONS 重嵌。10.2/10.4/10.5 寫進 Qdrant 的都是它們在 Neo4j 寫下的狀態的投影，8b 從 Neo4j 重讀，全部涵蓋 |
  | 10.6 | `scripts/validate_kg.py --live --target staging`、`scripts/check_identity.py --target staging --fail-on id` | 判準見 Step 10.6 |
  | export | `scripts/export_event_registry.py --check` | 結束碼 0 才算建完。只有刻意改 registry 的批次才不帶 `--check` 重寫，並人工審 diff |

- **一致性**：結構層（Step 0，已驗證逐位元相同）、NER 半邊（600 筆樣本重跑 2,830/2,830 相同）、TSK、curated 層都是決定性的。LLM 產物（Step 1 Phase 4 的 grounded 半邊、Step 6 R4、Step 7 描述，temperature=0.2）重跑必有漂移，所以重灌鏈一律重用凍結產物：grounded 半邊與描述在 `output/frozen/`，關係沿用 relations.jsonl。只有刻意重跑 LLM 的批次（2A、2B、延後-B/C）才會讓這些層變動。
- ⚠ Step 6 長跑注意（已驗證，比舊說法嚴重）：checkpoint 是在配對**送進 R4 之前**逐對寫入的，所以 R4 中途崩潰後 `--resume` 會把整批配對當成已處理，產出 0 條 LLM 邊；`--no-llm` 與 `--pericope-id` 都以覆寫模式改寫 `relations.jsonl` 與 `relations_unclassified.jsonl`（extract_relations.py:117-128、171-235）。第 2A 批修好之前，不要對既有產物重跑 Step 6；試跑時用 `RE_OUTPUT_PATH`、`RE_CHECKPOINT_PATH`、`RE_UNCLASSIFIED_PATH` 導到別的檔案，跑完比對量級（歷史 run 約 6,958 條）。

## Step 0: 經文切分與 sha 閘門

### 說明
- Hierarchical Chunking（Book → Chapter → Pericope → Chunk）
- JSONL 輸出（7 個檔案）：books、chapters、pericopes、chunks、embedding_queue、neo4j_nodes、neo4j_relationships
- 決定性：2026-10-04 重跑，7 個檔案逐位元相同

### 指令
```bash
uv run --project scripts python scripts/process_bible.py --input-dir bible_md --output-dir output

# sha 閘門：結束碼 0 才可往下走
uv run --project scripts python scripts/tools/check_step0.py
```

### sha 閘門（`scripts/tools/check_step0.py`）
- 計算 output/ 中 5 個檔案（books、chapters、pericopes、chunks、embedding_queue）的 sha256，與 git 追蹤的 `config/step0_sha.json` 比對。這 5 個檔案是重灌時**不重建**的幾層的輸入：PG 的四張結構表（Step 3）、段落向量（Step 2 → 4 / 4.1）、BM25 詞表（Step 2.1）。neo4j_*.jsonl 不在閘門內，因為它們只餵 Step 5，而 Step 5 每次都清庫重建；第 1B 批也會刻意改動其中的交叉引用。
- 結束碼：0 表示 5 個檔案全部相符；1 表示有檔案改變或缺檔，逐檔列出 expected 與 actual 的 sha、行數、位元組數；2 表示無法檢查（沒有基準檔，或 `--record` 時 output/ 缺檔）。
- 基準於 2026-10-04 由現行 output/ 記錄：embedding_queue.jsonl 34,072 行，sha256 `5d2ac0e5460c…`，與計畫 §1.2 的 run-of-record 相同。
- 不一致時先停下來查原因（bible_md/、bible_chunking/、process_bible.py 是否有改）。若是刻意的變更（例如第 1B、2D 批會改 pericopes.jsonl 的 cross_references 欄位）：
  1. 若 embedding_queue.jsonl 也變了，要重跑 Step 2 / 2.1 / 4 / 4.1（段落向量與 BM25 會變，這次就不再是「重灌」），Step 1 也要先重跑 `--stage ner`（merge 會拒絕抽自舊 queue 的 NER 半邊）；
  2. 先 `check_step0.py --record --dry-run` 預覽，再 `--record` 寫入新基準；
  3. 新基準與造成變更的程式碼放在同一個 commit。
- 重錄時若 5 個檔案逐位元未變，基準檔不會被改寫，不會產生只改了 recorded_at 的 diff。

---

## Step 1: 實體抽取

### 輸入
- `output/embedding_queue.jsonl`（34,072 筆：pericope 2,610 + chunk 431 + verse 31,031）

### 待抽取實體類型
| 類型 | 說明 |
|------|------|
| Person | 人物（亞伯拉罕、摩西、耶穌） |
| Place | 地點（耶路撒冷、埃及、加利利） |
| Group | 群體（以色列人、法利賽人） |
| Event | 事件（出埃及、復活） |
| Object | 物件（約櫃、會幕） |
| Theme | 主題（救贖、恩典、信心） |

### 兩個半邊（第 0 批起）
| 半邊 | 型別 | 來源 | 重跑 |
|---|---|---|---|
| NER 半邊 | Person / Place / Group | 字典＋CKIP，決定性（600 筆樣本重跑 2,830/2,830 相同） | 約 30 分鐘，不需 LLM |
| grounded 半邊 | Event / Object / Theme | pericope 標題探勘＋CKIP POS＋Phase 4 LLM 判決 | 需 LLM 數小時；Phase 4 沒有逐候選快取，重跑必有漂移 |

grounded 半邊凍結在 `output/frozen/`，重建時只重跑 NER 半邊，再與凍結檔合併。

### 指令
```bash
# 一次性：從現行 entities.jsonl / entity_mentions.jsonl 依型別拆出 grounded 半邊，凍結成
# output/frozen/grounded_entities.jsonl、grounded_mentions.jsonl、grounded_manifest.json。
# 凍結檔已存在時拒絕覆寫（要覆寫須加 --force）；--dry-run 只驗證並報告
uv run --project scripts python scripts/extract_entities.py --stage freeze-grounded

# NER 半邊（P/P/G，CKIP，無 LLM，約 30 分鐘）→ output/ner_entities.jsonl、ner_mentions.jsonl，最後寫 ner_manifest.json
uv run --project scripts python scripts/extract_entities.py --stage ner

# 合併 NER 半邊與凍結的 grounded 半邊 → output/entities.jsonl、output/entity_mentions.jsonl（拒絕條件見下）；--dry-run 只驗證
uv run --project scripts python scripts/extract_entities.py --stage merge
```

- 第一次：`freeze-grounded` → `ner` → `merge`。merge 要讀 `output/ner_entities.jsonl`、`ner_mentions.jsonl`、`ner_manifest.json`，而 freeze-grounded 不會寫出它們，所以凍結後第一次 merge 之前**必須先跑過一次 `--stage ner`**（約 30 分鐘；第 0 批之前產生的 ner_* 沒有 manifest，同樣要重跑；`merge --dry-run` 的 log 會說 NER 半邊與凍結時是否相同，等於順便驗證 NER 能完整重現）。之後重灌鏈只跑 `merge`；NER 程式、字典、embedding_queue 有改時才重跑 `--stage ner`。凍結的 manifest 是 `output/frozen/grounded_manifest.json`（不是 manifest.json：`output/frozen/` 還放描述快取等其他凍結檔）。等價要求：兩個半邊都沒改時，merge 的結果必須與現行 entities.jsonl、entity_mentions.jsonl 逐位元相同。
- **NER 半邊的來歷**：`--stage ner` 先刪掉舊的 `output/ner_manifest.json`，兩個 ner 檔寫完才寫新的，記錄兩檔的 sha256 與行數、`sampled`／`sample`、輸入檔（embedding_queue）的路徑與 sha256、git commit。merge 遇到下列任一情況就拒絕（結束碼 1，什麼都不寫，`--dry-run` 也一樣）：沒有 manifest、讀不到或欄位格式不對；manifest 標成 sampled（`--sample N` 的結果；只有明寫 `"sampled": false` 才算完整）；ner 檔與 manifest 記的 sha 不符（跑完後被改過）；manifest 記的輸入 sha256 與目前 `-i`（預設 `output/embedding_queue.jsonl`）的內容不符，或該檔不存在（NER 半邊抽自另一份 queue，例如 Step 0 重錄之後；比的是內容不是路徑）。加 `--force` 才放行，每個被放行的問題記一行 WARNING。凍結檔與 grounded_manifest 不符、grounded_manifest 讀不到或格式不對，則連 `--force` 也拒絕。
- **grounded 半邊的防護**：freeze 遇到空的 grounded 半邊、或缺 Event／Object／Theme 任一型別時拒絕（`--dry-run` 也檢查），`--force` 放行。重新凍結本來就要 `--force`，所以另設 `--accept-grounded-drift`：新半邊的實體或 mention 行數相對於被取代的快照變動超過 5%（舊 manifest 不見時改比現存凍結檔的行數；manifest 讀不到、或連凍結檔也不齊時一律要這個旗標）時，沒有它就拒絕，以免 `--sample`、`--phase`、`--ner-only --force` 留下的殘缺 build 蓋掉唯一一份 Phase 4 產物。merge 遇到凍結快照是空的、或現行 entities.jsonl 一個 E/O/T 都沒有（多半是被清掉了）時拒絕；查明原因後加 `--force` 會以凍結檔還原。
- **「NER half differs」WARNING**：merge 把 NER 半邊與 grounded_manifest 的 `ner_half`（凍結時那次 build 的 NER 半邊）比對，不同時照樣寫出，但記一行 WARNING：`NER half differs from the frozen build's: entities a -> b (±n), mentions …; by type: …`；相同時只記 INFO（`NER half identical …`）。一般重灌出現它代表 NER 沒有重現，要查。第 1C 批刻意改 NER，必然出現：核對各型別的增減與該批預期相符、記進該批紀錄後，跑一次 `--stage freeze-grounded --force` 把 `ner_half` 重設成新基準（grounded 沒變，漂移為 0，不需 `--accept-grounded-drift`），否則之後每次 merge 都會出現這個 WARNING，久了就沒人看。
- `--ner-only`（舊介面）會用只有 P/P/G 的結果覆寫 entities.jsonl 與 entity_mentions.jsonl，丟掉 E/O/T 共 4,897 個實體、20,458 筆 mention，而 registry 的錨點就在其中。現在沒有 `--force` 會拒絕執行；請改用 `--stage ner` 加 `--stage merge`。
- 完整抽取（含 Phase 4 LLM，需 `ENTITY_EXTRACT_*` 設定）只在兩種情況使用：fresh clone 拿不到凍結檔，或刻意重抽 grounded 半邊（延後-B）。它會覆寫兩個輸出檔：
  ```bash
  uv run --project scripts python scripts/extract_entities.py
  ```

### 輸出
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`
- `output/ner_entities.jsonl`、`output/ner_mentions.jsonl`、`output/ner_manifest.json`（`--stage ner`）
- `output/frozen/grounded_entities.jsonl`、`grounded_mentions.jsonl`、`grounded_manifest.json`（`--stage freeze-grounded`）

---

## Step 2: Embeddings 生成 ✅

### 輸入
- `output/embedding_queue.jsonl`（34,072 筆：pericope 2,610 + chunk 431 + verse 31,031）

### 模型
- BGE-M3（BAAI/bge-m3），1024 維，最大 8192 tokens

### 指令
```bash
uv run --project scripts python scripts/generate_embeddings.py --batch-size 32
```

### 輸出
- `output/embeddings.jsonl`（34,072 筆，每筆 1024 維向量）

---

## Step 2.1: Sparse Vectors 生成（Hybrid Search）

### 說明
為 Hybrid Search 生成 BM25-based sparse vectors，使用 CKIP 進行中文斷詞。

### 輸入
- `output/embedding_queue.jsonl`

### 指令
```bash
uv run --project scripts python scripts/generate_sparse_vectors.py --batch-size 32

# 使用 GPU 加速 CKIP
uv run --project scripts python scripts/generate_sparse_vectors.py --batch-size 32 --use-gpu
```

### 輸出
- `output/sparse_vectors.jsonl`（每筆包含 sparse vector indices 和 values）
- `output/bm25_vocabulary.json`（BM25 詞彙表和 IDF 值）

---

## Step 3: 匯入 PostgreSQL ✅

### 匯入資料
- `output/` 的 books、chapters、pericopes、chunks、entities、entity_mentions（各一個 `.jsonl`）

### 指令
```bash
uv run --project scripts python scripts/import_postgres.py
```

### 結果
- books 66、chapters 1,189、pericopes 2,779、chunks 431、entities 9,120、entity_mentions 173,896，**總計 187,481 筆**

> 上列為 JSONL 產物匯入量。Step 10 curated 重放後 live 為 entities 9,122 / entity_mentions 173,768（+18 curated Event、−16 泛名詞 Event、噪音 mention 清理 −128）。

---

## Step 4: 匯入 Qdrant ✅

### 匯入資料
- Embeddings（from Step 2）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings`（pericope + chunk embeddings）

### 指令
```bash
uv run --project scripts python scripts/import_qdrant.py
```

> ⚠ 預設會先刪除再重建目標 collection（`--no-recreate` 可關閉）。collection 名取自 `QDRANT_COLLECTION`（預設 `bible_embeddings`，與 backend 設定 `qdrant_collection` 同名）。staging 不跑這一步：Step 0 閘門通過時段落向量不變，staging 與 production 共用同一個段落 collection。

### 結果
- Vectors: 34,072 (1024 維度)

---

## Step 4.1: 匯入 Qdrant Hybrid Collection

### 說明
建立包含 dense + sparse vectors 的 hybrid collection，支援 RRF 混合檢索。

### 匯入資料
- `output/embeddings.jsonl`（dense vectors）
- `output/sparse_vectors.jsonl`（sparse vectors）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings_hybrid`
  - dense: 1024D BGE-M3 向量（COSINE distance）
  - sparse: BM25-based sparse 向量

### 指令
```bash
uv run --project scripts python scripts/import_qdrant_hybrid.py
```

> ⚠ 與 Step 4 相同：預設刪除後重建（`--no-recreate` 可關閉），collection 名取自 `QDRANT_HYBRID_COLLECTION`；staging 不跑。

### 結果
- Points: 34,072（每個點包含 dense + sparse vectors）

### 啟用 Hybrid Search
在 `.env` 中設定：
```bash
HYBRID_SEARCH_ENABLED=true
```

---

## Step 5: 匯入 Neo4j ✅

### 匯入資料
- `output/neo4j_nodes.jsonl`（4,465 筆）
- `output/neo4j_relationships.jsonl`（8,209 筆）
- 實體節點與關係（from Step 1）

### 節點類型
- Book、Chapter、Pericope、Chunk
- Person、Place、Group、Event、Object、Theme

### 關係類型
- CONTAINS、NEXT、NEXT_BOOK
- CROSS_REFERENCES
- MENTIONS（實體出現）

### 指令
```bash
uv run --project scripts python scripts/import_neo4j.py
```

> ⚠ 預設先清空 `NEO4J_URI` 指向的整個資料庫（`--no-clear` 可關閉）。重建一律對 staging（`bolt://localhost:7688`）執行，跑之前先做「Staging 與升版流程」中的環境變數檢查。

### 結果
- Total nodes: 19,310
- Total relationships: 57,877

> ⚠️ 上列為 2026-05 快照。P0 修復（2026-07-06）後 `import_neo4j.py` 內建 verse→pericope remap 與誠實計數器，重匯的 MENTIONS 會多於舊快照（verse 級 mention 不再靜默丟棄，落空者計入 `skipped_missing`）；live 現況見 [kg_optimization_progress.md](kg_optimization_progress.md)。

---

## Step 6: 關係抽取（Grounded RE）

### 說明
為 Entity 之間補上語意關係邊（FATHER_OF、RULED、BORN_IN 等 37 種），修復對照論文 *Graph RAG Survey* 後發現的「Entity↔Entity 邊 = 0」最大缺口。LLM 受限於 yaml schema 候選池（不能自由生成關係名稱），且 `evidence_span` 必須是上下文子字串才會被接受。

### 前提
- Step 5 完成（Entity / Pericope / MENTIONS 已在 Neo4j）
- Postgres `pericopes.content` 可讀（用於 grounding text）
- Ollama 已 pull `gemma4:31b-it-q8_0`（或加 `--no-llm` 跳過 Phase R4）

### 輸入
- `config/relations/biblical_relations.yaml`（37 個敘事級關係本體）
- `config/relations/biblical_priors.yaml`（~70 條黃金族譜先驗）
- Neo4j（Entity + Pericope + MENTIONS）
- Postgres `pericopes.content`

### Grounded 4-Phase Pipeline
| Phase | 動作 |
|------|------|
| R1 Pair Mining | 同 pericope 共現 entity 對（schema type-allowed 才保留） |
| R2 Rule Classifier | yaml `prompt_signals` regex/keyword 命中（高信心走規則） |
| R3 Domain Priors | yaml priors 直接賦邊（專家共識，bypass LLM） |
| R4 Grounded LLM | gemma4:31b-it-q8_0 從候選池選一個或回 NONE，evidence 必須是子字串 |
| R5 Inverse Materializer | FATHER_OF↔SON_OF 自動雙向 |

### 指令
```bash
# 完整抽取（估 10-20 小時離線；支援 --resume）
uv run --project scripts python -m scripts.relation_extraction.extract_relations --resume

# 規則 + priors only（無 LLM，適合快速驗證）
uv run --project scripts python -m scripts.relation_extraction.extract_relations --no-llm

# 限定 pericope 範圍 debug
uv run --project scripts python -m scripts.relation_extraction.extract_relations --limit-pericopes 30
```

### 輸出
- `output/relations.jsonl`（最終 triples）
- `output/relations_checkpoint.jsonl`（resumable state；`--resume` 讀此檔跳過已處理對）
- `output/relations_unclassified.jsonl`（LLM 回 NONE 的對，事後分析是否擴張 schema）

---

## Step 6.1: 匯入關係到 Neo4j

### 說明
將 Step 6 抽出的 triples MERGE 到 Neo4j（idempotent，可重複執行）。透過 APOC `apoc.merge.relationship` 建立動態邊型（FATHER_OF、RULED 等）。

### 輸入
- `output/relations.jsonl`（from Step 6）

### 邊屬性
- `confidence`、`evidence_span`（截斷 512 字）、`source_pericope_id`、`extraction_phase`、`head_canonical`、`tail_canonical`、`notes`

### 指令
```bash
uv run --project scripts python scripts/import_relations_neo4j.py output/relations.jsonl
```

### 結果（規模視 Step 6 抽取結果而定）
- Entity↔Entity 邊跨 ~37 種關係類型
- 統計輸出：每種 relation 邊數 + Top 25 排行

---

## Step 7: Entity 描述補完（產生與 replay）

### 說明
Person/Place/Group 三類 entity 中有 ~4,223 個 `description` 欄位空白（Object/Event/Theme 的 description 來自 Step 1；Event 的多半只是正文擷取，1,005 個剛好 100 字）。使用較小的 gemma4 系列模型（描述生成不需要 31B）為這些 entity 從其 mentioning pericope titles 推導 ≤80 字 grounded description。模型由 `DESC_OLLAMA_MODEL` 控制：現行 `.env` 為 `gemma4:26b-a4b-it-q8_0`；code fallback 為 `gemma4:e4b-it-q8_0`（11GB，原始 run 所用）。

產生的描述只寫進 Neo4j（Step 8 再帶進 Qdrant payload），不在任何 JSONL；PG 的 `entities.description` 對 P/P/G 是 0/4,223，所以 /api/v1/entity 回傳的描述一律是空字串（PG 同步排在第 1D 批）。Step 5 清庫重建後描述必然消失，因此第 0 批起改成快取：
- 產生模式每接受一條描述，就先附加到 `output/frozen/descriptions.jsonl`，再寫回 Neo4j。每行記錄 entity_id、description、model、temperature（固定 0.2）、prompt_version（prompt 內容雜湊）、titles_sha、quality_flag、git_commit（HEAD，工作樹有改時加 `-dirty`）、generated_at（計畫 §3.1）；
- 快取的種子是 live 現有的描述（3,045 條 P/P/G，加上 E/O/T）：R0 由 `scripts/tools/export_live_state.py`（唯讀）匯出到 `output/frozen/live_state/<YYYYMMDD>/descriptions.jsonl`，再以 `--promote` 複製成正式快取 `output/frozen/descriptions.jsonl`。種子不知道當初的生成參數：temperature 是 null，model、prompt_version、git_commit 是 `live_export_unknown`；
- 重灌鏈用 `--replay` 從正式快取寫回 Neo4j，不呼叫 LLM。快取以 (entity_id, titles_sha) 定址：實體目前的標題集合雜湊對不上任何快取條目時，回報為 stale、不寫回，留到第 2B 批重生。快取裡有、圖裡沒有的實體回報為 missing。
- **replay 排在 10.5 之後**：種子的 titles_sha 是用 live 的 MENTIONS 算的，也就是 10.2 刪掉「但」的誤命中、10.4/10.5 補上 curated 邊之後的狀態。放在 6.1 之後會讓 place:dan、person:yeteluo 判為 stale，而 10.5 對 extracted 節點不寫描述，兩條描述就永久遺失（scripts/tests/test_export_live_state.py 模擬了兩種順序）。
- replay 是閘門：每次都把 written、stale、missing 寫成 JSON 報告（`--report`，預設 `output/frozen/replay_reports/replay_<時間>.json`；stale 附目前的標題與快取裡的 titles_sha），`--fail-on-stale` 在 stale 或 missing 不是 0 時結束碼 1。相符的列照樣寫回（冪等）。
- **會刻意改動 MENTIONS 的批次（1A、1C、1D）**：標題集合變了，stale 是預期的，鏈會停在 Step 7。處理：(1) 讀這次的報告，逐筆確認 stale 與 missing 都落在該批預期改動的實體內（stale 條目附目前的標題與兩個 titles_sha；missing 只能來自刻意的刪除或改 id）；(2) 把清單與報告路徑列進該批紀錄並核可；(3) 確認後不帶 `--fail-on-stale` 重跑 Step 7（相符的列第一次就已寫回，重跑只是讓這一步以結束碼 0 留下報告），再接 8b。stale 的實體保留 Step 5 匯入的描述（P/P/G 是空的），留到 2B 重生；它們與 live 的描述差異逐條列進該批的 diff_kg 允許清單（`config/kg_diff_allow_<批次>.yaml` 的 `descriptions` section，見 R2）。名單外的 stale 一律當退步查。
- 兩種模式在連線前都呼叫 `kg_target.assert_target("neo4j")`（見「執行前檢查」）。

### 前提
- Step 5 完成；重灌鏈中還要 10.1–10.5 完成
- 產生模式：Ollama 已 pull `DESC_OLLAMA_MODEL` 指定的模型（見 Checklist 0.4）；replay 模式：快取檔存在（預設 `output/frozen/descriptions.jsonl`，可用 `--cache` 或 `DESC_CACHE_PATH` 改）

### 指令
```bash
# 重灌：從正式快取 replay（不呼叫 LLM；先加 --dry-run 只分類、只寫報告）
uv run --project scripts python -m scripts.relation_extraction.desc_generator --replay --fail-on-stale

# 產生：預設處理 Person、Place、Group（呼叫 LLM）
uv run --project scripts python -m scripts.relation_extraction.desc_generator

# 限定類型 + dry-run（不寫 Neo4j）
uv run --project scripts python -m scripts.relation_extraction.desc_generator \
  --target-types Person,Place \
  --dry-run

# 限量（debug）
uv run --project scripts python -m scripts.relation_extraction.desc_generator --limit 100
```

### 輸出
- 寫回 Neo4j `Entity.description` 欄位
- 產生模式另寫入 `output/frozen/descriptions.jsonl`；replay 模式寫 `output/frozen/replay_reports/`
- 產生模式的失敗者跳過（log warning），不阻擋整體流程

---

## Step 8: Entity 向量化

### 說明
為每個 Entity 生成 BGE-M3 1024 維向量，寫入新 Qdrant collection `bible_entities`，啟用模糊實體查詢（例：「亞伯拉罕的兒子」→ 命中 Isaac entity）。文字組合 `{name}({aliases})。{description}。常見於：{titles}`，截斷 200 字以避免 text embedding collapse。

### 前提
- Step 5 完成
- **Step 7 要在前面**（Person/Place/Group 若 description 為空會降低嵌入質量）。重灌鏈因此跑兩次：8a 在 10.x 之前（只為建 collection），8b 在 Step 7 之後（最終向量）

### Collection 設計
- `bible_entities`（1024 維 BGE-M3，COSINE distance）；名稱取自 `QDRANT_ENTITY_COLLECTION`，與 backend 設定 `qdrant_entity_collection` 同名。staging 寫入 `bible_entities_vN`（見「Staging 與升版流程」），10.2/10.4/10.5 的 Qdrant 同步也跟著這個變數走
- payload：`{entity_id, type, canonical_name, aliases, description, pericope_titles, pericope_ids}`
- point id：由 `entity_id` 經 UUID5 衍生（idempotent upsert）

### 指令
```bash
# 標準
uv run --project scripts python scripts/embed_entities.py --batch-size 64

# GPU 加速
uv run --project scripts python scripts/embed_entities.py --batch-size 64 --device cuda

# 重建 collection（清掉舊向量）
uv run --project scripts python scripts/embed_entities.py --recreate
```

### 結果
- Points: ~9,120（每個 entity 一個 vector）
- 後續 backend `entity_path_retriever.retrieve_by_entity_query()` 讀此 collection

---

## Step 9: TSK 串珠交叉引用匯入

### 說明
將 Treasury of Scripture Knowledge（19 世紀公版串珠註解）的 verse 級交叉引用映射到 Pericope 層，匯入 Neo4j `CROSS_REFERENCES` 邊，串珠規模 916 → 250,418 條（tsk 249,502、markdown 774、supplementary 142）。TSK 建立的邊帶 `votes`（社群投票數）與 `source: 'tsk'`。

手工 curated 邊（markdown 與 supplementary 共 916 條）在資料中**沒有** `votes` 屬性；999 不是存在資料裡的哨兵值，而是 backend 查詢時以 `coalesce(r.votes, 999)` 補出來的（backend/database/neo4j_db.py:202、239）。檢索端的 TSK 分權（手工 0.75/0.55 vs TSK 0.60/0.50）就靠這個補值判斷是否為 curated，因此 3 條 votes≥999 的 TSK 邊會被誤判成 curated。第 1B 批改成建置時寫入 `r.curated` 旗標，backend 改讀旗標（部署順序：先 backend，後資料）。

### 前提
- Step 5 完成（Pericope 節點已在 Neo4j）
- `output/embedding_queue.jsonl` 存在（verse→pericope 反查表，31,102 節全覆蓋）
- 原始資料 `output/cross_references_tsk.txt`：**不進 git**（`output/` 被 ignore），fresh clone 需自 [scrollmapper/bible_databases](https://github.com/scrollmapper/bible_databases) 下載 openbible.info 的 cross_references.txt（CC-BY）

### 指令
```bash
# 先 dry-run 檢查映射率
uv run --project scripts python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt --dry-run

uv run --project scripts python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt
```

### 結果
- 344,799 行 → 過濾負 votes（1,166）與自環（9,811）→ 250,358 條 unique pericope 對（僅 7 條 unmapped）
- 其中 856 對與既有 curated 邊是同一對段落。匯入只在 ON CREATE 時寫屬性，這 856 對的 votes 沒有寫上，所以 live 的 tsk 邊是 249,502 條（250,358 − 856）。第 1B 批改為無條件 SET，並加計數閘門
- 回滾：`MATCH ()-[r:CROSS_REFERENCES {source: 'tsk'}]->() DELETE r`

---

## Step 10: KG 修復與 curated 資料重放（重建後必跑）

### 說明
P0（2026-07-06）與排序層修復產生的 curated 資料**不在 Step 1–9 的 JSONL 產物中**：字典 aliases、噪音清理、共現關係搶救、18 個頭部 Event 節點、106 條手動 MENTIONS 邊。任何全量重建（重灌三庫）後若不重放此鏈，圖譜停在 P0 前狀態，檢索端依賴的資料（alias 查詢、curated Event 錨點、keyword-exact pin 的橋）會缺失。

**不需重跑**：`backfill_verse_mentions.py` — 其 verse→pericope remap 已內建於 `import_neo4j.py`（Step 5 匯入時自動處理）。

### 前提
- Step 1–6.1、8a、9 完成（Step 7 與 8b 排在 10.5 之後）；`QDRANT_ENTITY_COLLECTION` 指向的 entity collection 已由 8a 建好：10.2（staging 下）刪點、10.4 upsert 對不存在的 collection 都會失敗，10.5 找不到 extracted 點會 SystemExit
- `output/relations_unclassified.jsonl` 存在（Step 6 產物，10.3 的輸入）
- `config/curated/manual_graph_patches.jsonl`（git-tracked，106 邊/6 節點快照，10.5 的輸入）

### 指令（依序執行；每個腳本支援 `--dry-run` 預檢）
```bash
# 10.1 字典 aliases 直灌（38 節點；原生 LIST，backend alias 查詢的前提）
#      只寫 Neo4j
uv run --project scripts python scripts/backfill_aliases.py

# 10.2 噪音清理（「但」子字串誤命中 gate、16 泛名詞 Event 刪除、耶和華 Group→Person）
#      同步範圍不是三庫：「但」只刪 Neo4j 的 MENTIONS（PG entity_mentions 仍有 place:dan 1,882 列，
#      Qdrant 不動）；generic-events 與 yehehua 才同步 PG 與 Qdrant。KG_TARGET=staging 下：碰 Neo4j 之前先確認 PG 兩張表與
#      entity collection 都在，同步失敗就中止，修好後以同一組 --actions 重跑會補完同步；production 照舊只印警告並跳過
uv run --project scripts python scripts/cleanup_noise_entities.py

# 10.3 未分類關係搶救（relations_unclassified.jsonl → +5,641 PARTICIPATED_IN、+3,419 OCCURRED_IN）
#      第 1A 批退場（共現升格，嚴格精確率約 0.2）；之後不在預設鏈中
uv run --project scripts python scripts/backfill_event_relations.py

# 10.4 頭部 Event curated 補灌（11 個既有 Event 灌問法別名 + 18 curated 節點/56 邊；三庫同步）
uv run --project scripts python scripts/backfill_head_events.py

# 10.5 手動圖邊 patch 重放（106 MENTIONS 邊 + 受難週/大使命節點；三庫同步，語意見註記）
uv run --project scripts python scripts/backfill_manual_patches.py --apply
```

### 順序依據
- 10.2 在 10.3 之前：10.3 以 MATCH 找端點，先刪掉的泛名詞 Event 就不會再被接上搶救邊。
- 但這個順序**擋不住**「但」的孤兒邊。10.2 對 place:dan 只刪 MENTIONS，不刪節點，也不刪衍生邊；10.3 讀的是 2026-05 的 relations_unclassified.jsonl 快照，也不查 live MENTIONS，所以照樣產生 370 條 OCCURRED_IN 孤兒邊（同族另有 RULED 3、NEAR 1）。兩步對調結果相同。根治靠 provenance 閘門（第 1A 批的 6.05）與 10.3 退場，不是調整順序（計畫 §3.3）。
- 10.4/10.5 依賴 entity collection（8a）與 PG entities 表（Step 3）；10.5 放最後 — 其快照導出自 10.4 之後的線上狀態。
- Step 7（replay）在 10.5 之後、8b 在 Step 7 之後：理由見「執行順序」與 Step 7。

### 註記
- 若重跑 `extract_entities.py`：`pericope_miner.py` 的 `GENERIC_TITLE_STOPLIST` 只在 pericope 標題候選（Phase 1）生效，而且與 10.2 的 `GENERIC_EVENT_STOPLIST` 是同一組 24 個詞的兩份定義。其他 phase 產生的同名泛名詞 Event 擋不住，所以 10.2 的 generic-events、dan、yehehua 三個動作都仍然必要。另有 37 個非標題來源的泛名詞或地名 Event（瘟疫、瑪拉、瑪撒、米利巴、耶和華曉諭…）兩份停用詞都沒有收，留給第 1D 批。重抽一律走 `--stage ner` 加 `--stage merge`；`--ner-only` 會丟掉整個 grounded 半邊（見 Step 1）。
- 各步驟的執行細節、發現與回滾指令：[records/2026-07-06_kg_p0_execution.md](records/2026-07-06_kg_p0_execution.md)（10.1–10.3）、[records/2026-07-06_kg_fixes_execution.md](records/2026-07-06_kg_fixes_execution.md)（10.4）、`scripts/backfill_manual_patches.py` docstring（10.5）。
- 10.5 的語意（第 0 批起）：
  - 每個節點列都用 `apoc.coll.toSet` 把 patch 的 aliases 合併進節點，排除與 canonical 相同的值（EV-06：山上寶訓與兩個保羅敘述歸主事件的 registry 觸發詞只來自這裡；舊版只在 ON CREATE 寫，重建後 registry 從 33 掉到 31）。
  - 只建 origin=manual 的節點。extracted id 不在圖中時，任何寫入前就硬失敗：這代表抽取改了 id 或丟了節點，要改 patch，不可補建（ID-7）。
  - PG 與 Qdrant：manual 列整列 upsert／重嵌；extracted 列只同步 aliases，不碰 description 與向量。extracted 列在 PG 或 Qdrant 缺席時，同樣在任何寫入前失敗（以 `--skip-pg`／`--skip-qdrant` 略過的庫除外；`--dry-run` 也會檢查）。
  - `--export` 也遵守 `--dry-run`。`--apply` 的備份 `output/backups/manual_patches_<ts>.jsonl` 為每個節點記下執行前的 aliases：Neo4j（`aliases_before`）、PG、Qdrant（原始 payload 值），回滾用。

### 10.6 品質閘門（第 0 批新增）
export_event_registry `--check`（鏈的最後一步）之前的關卡：
```bash
# KG 品質門（計畫 §3.6）：0 通過；1 硬失敗，或有檢查 error／unmeasured（沒跑成的檢查不算通過）；2 ratchet 退步
uv run --project scripts python scripts/validate_kg.py --live --target staging

# 三庫身分一致（id、type、canonical、aliases、description 全部列出）；--fail-on id：只有 id 集合有差、或有庫沒讀到時結束碼 1
uv run --project scripts python scripts/check_identity.py --target staging --fail-on id
```
- 兩項都在 source 過 staging.env 的 shell 跑：`--target staging` 只讀 shell 的變數（不讀 .env），解析到 production 的庫會拒絕；Qdrant 沒有 staging 預設值，沒設 `QDRANT_ENTITY_COLLECTION` 時 H5 判 unmeasured、check_identity 判「庫被略過」，都是結束碼 1。從零鏈（沒有 staging 的機器）兩項都改用 `--target prod`，而且要在乾淨的 shell 跑（見 R4）。
- **第 0 批的判準**。等價重建刻意保留 live 的狀態，所以不會全綠；預期差異要逐項列進該批的紀錄，不可直接 ratchet：
  - validate_kg：hard（H1、H2、H7）全過；結束碼 2 只能來自事先列出的退步。已知 R1 從基準 1,938 升到約 2,124（以 output/ JSONL 投影實測；verse remap 後 start_pos=0 從 1,785 變 1,947）。「但」的 370 條孤兒邊仍會被 10.3 重新產生（H3 到第 1A 批才是硬門檻）；mention_count 也會變。
  - check_identity：`--fail-on id` 結束碼 0，即三庫 id 集合差為 0。其餘欄位的差異在第 1D 批前屬正常：PG 的 P/P/G description 全空（Step 3 早於 Step 7；live 為 3,045 筆）、PG aliases（部分 10.x 補的 aliases 只進了 Neo4j；live 為 14 筆）。staging 的 Qdrant 預期 0 差異（8b 從 Neo4j 重讀，aliases 是原生 list），但 live 的 Qdrant aliases 是 JSON 字串（9,093 筆），所以 staging 對 live 的比對在這裡會不同，同樣屬正常。
- staging 對 live 的等價比對（E–E 各 phase 的邊數、描述逐字比對等）用 `scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_<批次>.yaml`（唯讀），與上面兩項相反，**必須在沒有 source staging.env 的乾淨 shell 跑**，見 R2。

### export_event_registry（registry 匯出）
`scripts/export_event_registry.py` 從 Neo4j 讀 curated 事件（backfill_head_events.py 的 ALIAS_INJECTIONS 與 NEW_EVENTS，以及 manual_graph_patches.jsonl 的 Event 節點）的名稱、aliases 與錨點，寫成 `backend/data/event_registry.json`。線上預設 `graph_strategies=["event_registry"]` 只讀這個燒進 image 的靜態檔，不讀 Neo4j；所以重建只要讓這個檔案的內容變了，線上 QA 就會變。

```bash
uv run --project scripts python scripts/export_event_registry.py --check   # 只比對（重灌鏈最後一步），不寫檔
uv run --project scripts python scripts/export_event_registry.py           # 重寫檔案
```
- 重灌鏈的最後一步：由目標圖重算的 registry（觸發詞、錨點等，generated_at 除外）必須與 backend/data/event_registry.json 相同（現為 33 個事件），結束碼 0 就不必重寫（重寫只會改到 generated_at）。validate_kg 的 D1 也跑同一個 `--check`。
- 只有刻意改 registry 的批次（第 2C 批）才不帶 `--check` 重寫。git diff 必須人工核可；檔案由 Dockerfile COPY 進 image，要 `docker compose up -d --build backend` 才會上線（只 restart 會跑舊檔）。
- 讀 `NEO4J_URI`，對 staging 執行時讀的是 staging 圖；除非該批的目的就是改 registry，否則不要在 staging 上重寫 repo 裡的 registry。不帶 `--check` 時會寫入 git 追蹤的檔案，沒有 `--dry-run`；要預覽就用 `--check`。

---

## Staging 與升版流程

> 依據：[records/2026-10-04_kg_data_layer_fix_plan.md](records/2026-10-04_kg_data_layer_fix_plan.md) §3.5、§3.7（D1：staging 全量重建後升版，不做線上增量補丁）。每批升版都走 R0 → R1 → R2 → R3 → R4，出事走 R5。**第 0 批只做 R0、R1、R2**（在 staging 上做等價重建並列出 diff），不升版。

### 拓撲

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

### 環境變數契約

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

### 執行前檢查（每次在 staging 跑寫入步驟之前）
Step 3 會 TRUNCATE、Step 5 會清庫、8a／8b 的 `--recreate` 會刪 collection；變數沒指對，被清掉的就是 production。staging 的變數一律 source 現成的檔案，不要手打：
```bash
source scripts/tools/staging.env   # 設好 KG_TARGET=staging 與上表 staging 欄的全部變數
uv run --project scripts python scripts/kg_target.py --require-staging neo4j postgres qdrant   # 結束碼 0 才往下走
```
- 程式端防護 `scripts/kg_target.py`：寫入型腳本在連線前呼叫 `kg_target.assert_target(<要寫的庫>)`。`KG_TARGET=staging` 時，只要有一個要寫的庫的設定沒設（腳本會退回 `.env` 的 production 值），或解析到 production（Neo4j port 7687，沒寫 port 也算；`bible_rag`；`bible_entities`；以及 `.env` 寫的值），就在連線前 SystemExit。`KG_TARGET` 沒設時行為與以前相同，所以沒有 source staging.env 的 shell 不受保護。
- 第二行的 `--require-staging` 做同一組三庫檢查，另外要求 `KG_TARGET=staging`：新開的終端機忘了 source、或任一庫沒有隔離時結束碼 1；通過時結束碼 0，並印出腳本實際會寫入的三個端點（Neo4j URI、PG 主機與資料庫、Qdrant 主機與 collection），要逐一看過。舊版文件的 `python -c '…assert_target(…)'` 在沒 source 的 shell 會假性通過（`KG_TARGET` 沒設時 assert_target 不檢查、直接回傳 prod），不要再用。
- staging 的變數只放在跑腳本的 shell，**不要在這個 shell 裡對 production 服務下 `docker compose up`**：docker-compose.yml 會把 `${POSTGRES_DB}` 插值進 production 的 postgres 服務，帶著 `POSTGRES_DB=bible_rag_staging` 去 `up` 它，compose 會判定設定已變而重建 production 的 postgres 容器。指名 `neo4j-staging`、`backend-staging` 不受影響（backend-staging 刻意只依賴 neo4j-staging）。

### R0 備份（每批升版前；第 0 批也要做）
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
   - 以 `extract_entities.py --stage freeze-grounded` 凍結 grounded 半邊，再跑 `--stage ner`（約 30 分鐘）產生帶 manifest 的 NER 半邊，最後 `--stage merge --dry-run` 確認 log 是「NER half identical」（見 Step 1）。
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

### R1 staging 建置
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
5. 依「執行順序」的重灌鏈逐步執行（Step 4／4.1 跳過）。
6. 第一次 staging 重建要實測各步耗時並填入下表；目前的耗時都是推論（計畫 §8）：

   | 步驟 | 實測耗時 |
   |---|---|
   | 0、1(merge)、3、5、6.1、8a、9、10.1–10.5、7(replay)、8b、10.6、export --check | 2026-10-04 第 0 批實測：0=5s、3=5s、5=28s、6.1=1s、8a=26s、9=6s、10.1–10.5=19s、7=1s、8b=24s、10.6=6s，合計約 2 分鐘；`--stage ner` 另需 34 分鐘（1(merge) 本身 <10s） |

### R2 驗證
1. 10.6 依該批的判準通過（見 Step 10.6），而且 `export_event_registry.py --check` 結束碼 0。
2. 通過該批的驗證門檻（計畫 §4）。與 live 的 diff 要逐項列出並解釋（預期中的差異見 Step 10.6）。staging 對 live 的比對用 diff_kg，在**沒有 source staging.env 的乾淨 shell**（新開的終端機）跑；10.6 的兩項則要在 staging 的 shell 跑：
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

### R3 升版（第 0 批不做）
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

### R4 升版後檢查
- 在 production 上執行 `validate_kg.py --live --target prod`、`export_event_registry.py --check`、`check_identity.py --target prod`。要在沒有 source staging.env 的新 shell 執行：validate_kg 與 check_identity 的 `--target prod` 讀 .env，shell 還帶著 staging 設定（`KG_TARGET=staging`、store 變數與 .env 不同、Neo4j 7688、bible_rag_staging）時會拒絕並結束碼 1，不會把 staging 當成 prod 報告；export_event_registry 沒有這層防護，只讀 `NEO4J_URI`，在 staging 的 shell 會默默檢查 staging 圖。
- 抽查 /api/v1/entity（計畫 §6.4 列出各批的探針）。

### R5 回滾
- Neo4j：照 bak/README.md 的「還原指令」，載回 `bak/<日期>/neo4j/neo4j.dump`（停機約 1 分鐘）。
- PG：用 R0 存的 `bak/<日期>/postgres/entity_tables.sql` 換回兩張表，指令同 R3 第 2 步。
- Qdrant：把 `QDRANT_ENTITY_COLLECTION` 切回上一個 collection 名，再重新建立 backend 容器。
- 程式碼與 registry：`git revert`，再 `docker compose up -d --build backend`。
- 第 1D 批起有了編譯快照（`output/kg_snapshots/<ts>/`）：回滾等於重新載入上一份快照，比還原 dump 快，而且三庫一定一致。

### 收尾
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging neo4j-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml rm -f backend-staging neo4j-staging
docker exec bible_rag_postgres dropdb -U bible bible_rag_staging
docker volume rm bible_rag_neo4j_staging_data bible_rag_neo4j_staging_logs   # 確定不再需要時
```
- 已升版的 `bible_entities_vN` 就是 production 的 entity collection，不要刪。沒有升版的 staging collection 用 `curl -X DELETE http://localhost:6333/collections/<名稱>` 刪除，刪之前確認它不是 `.env` 正在用的名稱。

---

## 資料庫啟動指令

> ⚠ fresh clone 首次建庫請改用「從零重建 Checklist」0.3 —— backend 需等管線跑完最後啟動，否則 bind-mount 會把 `output/bm25_vocabulary.json` 建成目錄。

```bash
# 啟動所有資料庫
docker compose up -d

# 停止資料庫
docker compose down
```

staging（見「Staging 與升版流程」）一律指名服務：
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d neo4j-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d backend-staging   # R2 才需要
```

### 服務端點
| 服務 | 端點 |
|------|------|
| PostgreSQL | localhost:5432（staging：同一實例，資料庫 `bible_rag_staging`） |
| Qdrant | http://localhost:6333/dashboard（staging：同一實例，collection `bible_entities_vN`） |
| Neo4j | http://localhost:7474（staging：http://localhost:7475、bolt://localhost:7688） |
| backend | http://localhost:8000（staging：http://localhost:8001） |
