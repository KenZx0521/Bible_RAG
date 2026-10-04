# KG 資料層修復第 0 批：執行結果（R0 備份、R1 staging 重建、R2 等價驗證）

- **日期**：2026-10-04
- **依據**：[2026-10-04_kg_data_layer_fix_plan.md](2026-10-04_kg_data_layer_fix_plan.md) §4 第 0 批；流程見 [../staging_promotion.md](../staging_promotion.md)「Staging 與升版流程」（2026-10-04 自 build_database.md 拆出）
- **程式**：860a51d（第 0 批骨架）、7526e12（NER 決定性修正）；git tag `kg-pre-batch0`
- **證據**：`2026-10-04_kg_fix/batch0_p1/`（各步 log、validate_kg 結果、diff_kg JSON、replay 報告）
- **本批不升版**：正式三庫與 backend 都沒有改動；線上預設路徑（event_registry 靜態檔）不受影響。

## 結論

- **等價重建通過。** 在全部修正關閉的狀態下，staging 從 JSONL 加上凍結產物重建，和 live 的 Neo4j 比對：
  - labels、各關係總數、MENTIONS、交叉引用、實體 id、**描述逐字**、aliases、registry 全部相同；
  - 唯一的差異是 4 條 SON_OF 邊的出處標記（邊集合相同），已列入允許清單並寫明原因。
- **三個重建地雷已排除，並有實證：**
  - EV-06：registry 在 staging 上維持 33 個事件，與 `backend/data/event_registry.json` 逐位元相同；
  - Step 7 描述：從快取重放 7,946 條，stale 0、missing 0；
  - `--ner-only`：已加防護，必須帶 `--force`。
- **新發現並已修正：NER 不是決定性的。** 計畫原本以為可重現，實際上換個 hash seed 輸出就不同。已在 7526e12 修正。
- **新發現：live 的 NER 半邊早於 2026-05-15 的字典修改。** 重抽時「流珥」會併入葉忒羅。這屬於第 1C 批的預期差異，本批的等價重建因此沿用現行 entities.jsonl，沒有跑 merge。

## R0 備份

`bak/20261004/`（614 MB，`sha256sum -c SHA256SUMS` 通過）：

| 項目 | 內容 |
|---|---|
| PostgreSQL | bible_rag.dump、globals.sql、entity_tables.sql（R5 換表用） |
| Qdrant | bible_embeddings 34,072、bible_entities 9,124、bible_embeddings_hybrid 34,072 points 的 snapshot |
| Neo4j | neo4j.dump；停機約 8 秒，前後皆 13,589 nodes / 319,988 rels |
| output 產物 | llm_artifacts.tgz + MANIFEST.sha256（22 個檔案）：relations*、entities/mentions、TSK、K0 五檔、frozen/、NER 半邊 |

只存在 live 的狀態已匯出到 `output/frozen/live_state/20261004/`（描述 7,946、實體 9,124、curated MENTIONS 162），並 `--promote` 成正式描述快取。grounded 半邊已凍結（4,897 個實體、20,458 筆提及，round-trip 驗證通過）。

## NER 的兩項發現

1. **不決定性（已修正）。** 以 PYTHONHASHSEED=1 與 2 各跑 `--stage ner --sample 400`，ner_*.jsonl 逐位元不同。內容相同，但 1,863 筆中有 269 筆 mention_id 重新編號，提及數相同的實體順序也互換。
   - 根因：`get_all_*_names()` 回傳 set，字典比對時同長度名稱的嘗試順序隨 hash 改變。同長度名稱在文中重疊時，連保留哪一個都會變。
   - 修正：排序鍵改為 (-len, name)，見 `scripts/tests/test_ner_determinism.py`。修正後兩個 seed 的輸出逐位元相同。
2. **live 的 NER 落後於現行字典。** 用 860a51d 全量重跑 NER（34 分鐘）後，和凍結版本在內容層面的差異只有一組：
   - `person:liuer`（流珥，10 筆）消失，`person:yeteluo`（葉忒羅）由 30 筆變 51 筆；
   - 原因是 4c0a60e（2026-05-15）把「流珥」加為葉忒羅的別名，live 的 NER 從未用新字典重跑；
   - 其餘約 2.3 萬筆差異只是 mention_id 編號。
   
   因此本批的 P1 沿用現行 entities.jsonl（跳過 Step 1 merge）。split→merge 的逐位元等價已由測試以真實檔案驗證。第 1C 批重跑 NER 時，這一組會成為預期差異。

> 注意：`output/ner_*.jsonl` 是由 860a51d 產生的，早於 7526e12 的決定性修正。第 1C 批前要用現行程式重跑 `--stage ner`。

## R1 staging 重建（實測耗時）

| 步驟 | 耗時 | 結果 |
|---|---|---|
| 0 process_bible + check_step0 | 5s + 0s | 5 個 K0 產物與基準逐位元相同 |
| 3 import_postgres | 5s | 187,481 筆 |
| 5 import_neo4j | 28s | |
| 6.1 import_relations_neo4j | 1s | 6,958 條 |
| 8a embed_entities | 26s | |
| 9 import_tsk_crossrefs | 6s | |
| 10.1–10.5 | 19s | |
| 7 desc_generator --replay --fail-on-stale | 1s | 寫入 3,045、未變 4,901、stale 0、missing 0 |
| 8b embed_entities --recreate | 24s | |
| 10.6 | 6s | 見 R2 |

合計約 2 分鐘，不含 `--stage ner` 的 34 分鐘。計畫原本估 1–1.5 小時。

## R2 驗證

| 檢查 | 結果 | 判定 |
|---|---|---|
| validate_kg --live --target staging | 結束碼 2；硬門檻（H1、H2、H7、D1）全過；唯一的退步是 R1 = 2,124（基準 1,938） | 通過。R1 是事先列出的預期差異：verse remap 後 start_pos=0 由 1,785 變 1,947，預測值正是 2,124 |
| check_identity --target staging --fail-on id | 三庫 id 集合差 0（各 9,124）；Qdrant 全部欄位 0 差；PG 描述差 3,045、aliases 差 10 | 通過。PG 漂移是已知項目，留到第 1D 批處理 |
| export_event_registry --check（staging） | 結束碼 0；33 個事件，與 repo 檔逐位元相同 | 通過，EV-06 已排除 |
| diff_kg --a prod --b staging | 只有 3 個差異，都在 ee_edges 的 SON_OF phase 計數（+1／+3／−4，總數同為 659） | 通過，見下 |

**SON_OF 差異的解釋**：兩邊的 659 條 SON_OF 邊（head/tail 配對）完全相同，只有 4 條邊的 extraction_phase 與 source_pericope_id 不同：
- person:yage→person:yisa（gen:28:1）
- person:bianyamin→person:yage（gen:35:1）
- person:bianyamin→person:lajie（gen:35:1）
- person:dawei→person:yexi（1ch:29:2）

每條邊各被兩個 phase 產生一次：一次來自先驗或規則，沒有出處段落；一次來自後續 phase，帶有出處。`apoc.merge.relationship` 只在第一次建立時寫入屬性，所以最先匯入的那一份留下。live 留的是沒出處的那份，staging 留的是有出處的那份。允許清單：`config/kg_diff_allow_batch0.yaml`。這個 onCreate-only 的語意，留到第 1A 批的 Step 6.05 一併處理。

## 環境現況

- staging 仍在運作，第 1 批可直接沿用：
  - 容器 `bible_rag_neo4j_staging`（7688/7475）；
  - PG 資料庫 `bible_rag_staging`；
  - Qdrant collection `bible_entities_v2`。
- 不再需要時：
  - `docker compose -f docker-compose.yml -f docker-compose.staging.yml --profile staging down neo4j-staging`；
  - 刪除 staging 的 PG 資料庫與 Qdrant collection（**只對 staging 執行**）。

## 第 1 批之前

- 第 1C 批：用現行程式重跑 `--stage ner`，並把「流珥併入葉忒羅」列為預期差異。
- 第 1A 批：處理 onCreate-only merge 造成的 phase 歸屬不決定性；同時讓 10.3 退場（Kay 的 D2 決策）。
- 計畫 §8 的工時推論可以下修：重灌鏈本身只要約 2 分鐘，主要成本在 NER（34 分鐘）與人工審查。
