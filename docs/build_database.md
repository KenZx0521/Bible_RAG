# Bible RAG 建庫管線（Step 1–10）

## 環境設定

使用 uv 管理 scripts 的 Python 依賴：
```bash
# 在專案根目錄執行，安裝所有 scripts 依賴
uv sync --project scripts
```

## 目前完成

- [x] Hierarchical Chunking（Book → Chapter → Pericope → Chunk）
- [x] JSONL 輸出（7 個檔案）
### 指令
uv run --project scripts python scripts/process_bible.py --input-dir bible_md --output-dir output
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

### 指令
```bash
# NER-only (無 API 成本)
uv run --project scripts python scripts/extract_entities.py --ner-only

# 完整抽取 (需設定 API key)
uv run --project scripts python scripts/extract_entities.py
```

### 輸出
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

---

## Step 2: Embeddings 生成 ✅

### 輸入
- `output/embedding_queue.jsonl`（34,072 筆：pericope 2,610 + chunk 431 + verse 31,031）

### 模型
- BGE-M3（BAAI/bge-m3）
- 維度：1024
- 最大 tokens：8192

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
- `output/books.jsonl`
- `output/chapters.jsonl`
- `output/pericopes.jsonl`
- `output/chunks.jsonl`
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`

### 指令
```bash
uv run --project scripts python scripts/import_postgres.py
```

### 結果
- books: 66 records
- chapters: 1,189 records
- pericopes: 2,779 records
- chunks: 431 records
- entities: 9,120 records
- entity_mentions: 173,896 records
- **總計: 187,481 records**

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

## Step 7: Entity 描述補完

### 說明
Person/Place/Group 三類 entity 中有 ~4,223 個 `description` 欄位空白（Object/Event/Theme 已有 description）。使用較小的 `gemma4:e4b-it-q8_0` 模型（11GB，描述生成不需要 31B）為這些 entity 從其 mentioning pericope titles 推導 ≤80 字 grounded description。

### 前提
- Step 5 完成
- Ollama 已 pull `gemma4:e4b-it-q8_0`

### 指令
```bash
# 預設處理 Person、Place、Group
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
- 失敗者跳過（log warning），不阻擋整體流程

---

## Step 8: Entity 向量化

### 說明
為每個 Entity 生成 BGE-M3 1024 維向量，寫入新 Qdrant collection `bible_entities`，啟用模糊實體查詢（例：「亞伯拉罕的兒子」→ 命中 Isaac entity）。文字組合 `{name}({aliases})。{description}。常見於：{titles}`，截斷 200 字以避免 text embedding collapse。

### 前提
- Step 5 完成
- **建議先跑 Step 7**（Person/Place/Group 若 description 為空會降低嵌入質量）

### Collection 設計
- `bible_entities`（1024 維 BGE-M3，COSINE distance）
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
將 Treasury of Scripture Knowledge（19 世紀公版串珠註解）的 verse 級交叉引用映射到 Pericope 層，匯入 Neo4j `CROSS_REFERENCES` 邊，串珠規模 916 → 250,418 條。每條邊帶 `votes`（社群投票數）與 `source: 'tsk'`，與手工 markdown 邊（哨兵值 votes=999）區分 — 檢索端的 TSK 分權（手工 0.75/0.55 vs TSK 0.60/0.50）依賴此欄位。

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
- 回滾：`MATCH ()-[r:CROSS_REFERENCES {source: 'tsk'}]->() DELETE r`

---

## Step 10: KG 修復與 curated 資料重放（重建後必跑）

### 說明
P0（2026-07-06）與排序層修復產生的 curated 資料**不在 Step 1–9 的 JSONL 產物中**：字典 aliases、噪音清理、共現關係搶救、18 個頭部 Event 節點、106 條手動 MENTIONS 邊。任何全量重建（重灌三庫）後若不重放此鏈，圖譜停在 P0 前狀態，檢索端依賴的資料（alias 查詢、curated Event 錨點、keyword-exact pin 的橋）會缺失。

**不需重跑**：`backfill_verse_mentions.py` — 其 verse→pericope remap 已內建於 `import_neo4j.py`（Step 5 匯入時自動處理）。

### 前提
- Step 1–9 全部完成；`bible_entities` collection 已建（10.2/10.4/10.5 會對 Qdrant 同步或重嵌）
- `output/relations_unclassified.jsonl` 存在（Step 6 產物，10.3 的輸入）
- `config/curated/manual_graph_patches.jsonl`（git-tracked，106 邊/6 節點快照，10.5 的輸入）

### 指令（依序執行；每個腳本支援 `--dry-run` 預檢）
```bash
# 10.1 字典 aliases 直灌（38 節點；原生 LIST，backend alias 查詢的前提）
uv run --project scripts python scripts/backfill_aliases.py

# 10.2 噪音清理（「但」子字串誤命中 gate、16 泛名詞 Event 刪除、耶和華 Group→Person；三庫同步）
uv run --project scripts python scripts/cleanup_noise_entities.py

# 10.3 未分類關係搶救（relations_unclassified.jsonl → +5,641 PARTICIPATED_IN、+3,419 OCCURRED_IN）
uv run --project scripts python scripts/backfill_event_relations.py

# 10.4 頭部 Event curated 補灌（11 個既有 Event 灌問法別名 + 18 curated 節點/56 邊；三庫同步）
uv run --project scripts python scripts/backfill_head_events.py

# 10.5 手動圖邊 patch 重放（106 MENTIONS 邊 + 受難週/大使命節點；三庫同步）
uv run --project scripts python scripts/backfill_manual_patches.py --apply
```

### 順序依據
10.2 在 10.3 之前（泛名詞 Event 先刪，搶救邊不會 MERGE 到將刪節點）；10.4/10.5 依賴 `bible_entities` collection（Step 8）與 PG entities 表（Step 3）；10.5 放最後 — 其快照導出自 10.4 之後的線上狀態。

### 註記
- 若重跑過 `extract_entities.py`（重抽而非重灌既有 JSONL），`pericope_miner.py` 的 `GENERIC_TITLE_STOPLIST` 已防泛名詞 Event 再犯，但 10.2 的 dan/yehehua 兩動作與其餘步驟仍必要。
- 各步驟的執行細節、發現與回滾指令：[records/2026-07-06_kg_p0_execution.md](records/2026-07-06_kg_p0_execution.md)（10.1–10.3）、[records/2026-07-06_kg_fixes_execution.md](records/2026-07-06_kg_fixes_execution.md)（10.4）、`scripts/backfill_manual_patches.py` docstring（10.5）。

---

## 資料庫啟動指令

```bash
# 啟動所有資料庫
docker compose up -d

# 停止資料庫
docker compose down
```

### 服務端點
| 服務 | 端點 |
|------|------|
| PostgreSQL | localhost:5432 |
| Qdrant | http://localhost:6333/dashboard |
| Neo4j | http://localhost:7474 |
