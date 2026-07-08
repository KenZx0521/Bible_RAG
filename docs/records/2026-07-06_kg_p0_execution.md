# KG P0 優化執行紀錄

**日期**:2026-07-06
**依據**:[2026-07-05_kg_optimization_analysis.md](2026-07-05_kg_optimization_analysis.md) 第 3 節 P0 路線圖
**性質**:資料修補,不重抽(live 圖譜直接修復 + 匯入程式碼防再犯)

---

## 執行結果總覽

| # | 項目 | 結果 | 與預測對比 |
|---|---|---|---|
| 1 | verse mention 回填 | **+5,853 條 Pericope 錨點**,失明實體 1,474 → 164 | 精算預測 +5,853 / 活化 1,310,**完全吻合** |
| 2 | 修靜默丟棄 | `import_neo4j.py` 重寫 mention 匯入:verse remap + 誠實計數器 | 未來全量重匯不再丟 56% |
| 3 | aliases 字典直灌 | 38 節點寫入原生 LIST(耶和華 7 別名、彼得 3、耶路撒冷 2...) | 字典可覆蓋上限;大量 alias 靠 P1 ER |
| 4 | 噪音 gate | 「但」錨點 759→26;16 個泛名詞 Event 刪除(三庫同步);耶和華 Group→Person | 超出預期:發現「撒但/拿但業/底但」子字串誤命中 |
| 5 | 未分類關係搶救 | +5,641 PARTICIPATED_IN、+3,419 OCCURRED_IN(conf 0.35 標記) | 事件層參與者 34%→**84%**、地點 32%→**75%** |
| 6 | TSK 串珠匯入 | CROSS_REFERENCES 916 → **250,418**(0 落空) | 31,102 節 100% 映射;檢索端同步改 votes 排序 |

## CI 三指標(修復前 → 後)

| 指標 | Before | After |
|---|---|---|
| anchor coverage(實體有 Pericope 錨點) | 83.8%(7,648/9,122) | **98.2%**(8,942/9,106) |
| Pericope-level MENTIONS 邊 | 36,471 | 41,580 |
| 語意關係邊 | 6,958 | 15,926 |
| Event 有參與者 / 有地點 | 34.4% / 31.8% | 84.0% / 75.5% |
| CROSS_REFERENCES | 916 | 250,418 |
| alias coverage | 35 節點 | 43 節點(P1 ER 才會放大) |

## 逐項細節

### 1+2. verse mention 回填與匯入修復

- `scripts/import_neo4j.py`:
  - L191 `json.dumps(aliases)` → 原生 LIST(backend `any(a IN e.aliases ...)` 查詢才吃得到;舊寫法重匯會炸掉 alias 查詢)
  - `import_entity_mentions()` 重寫:verse 級 source_id(`gen:1:0:v:3`)strip `:v:N` remap 到 pericope;MATCH 落空計入 `skipped_missing` 並 log(不再謊報 "Imported 173,896");Pericope/Chunk 分流帶 label 查詢(索引生效)
- `scripts/backfill_verse_mentions.py`(新):97,235 條 verse mention → 24,782 unique 對 → MERGE 5,853 條新邊,`backfilled: true, source_granularity: 'verse'` 可稽核/回滾

### 3. aliases 直灌

- `scripts/backfill_aliases.py`(新):`entity_dict.py` 三字典 → 同型別 canonical_name 精確匹配寫入(tier1),歧義 alias(西門/約瑟/雅各)跳過並記錄
- 值得記錄的發現:Person「猶大」「路得」「但」在圖譜無節點(重名塌縮,P1 ER 素材)

### 4. 噪音 gate

- `scripts/cleanup_noise_entities.py`(新,三動作皆備份至 `output/backups/`):
  - **dan**:1,882 條 mention 分類 = geo 44 / 連接詞 1,439 / **子字串誤命中 399**(撒但 135、拿但業 22、底但 19、亞比但 18、米但 8 — `text.find()` 字面比對的直接證據,可入論文);白名單規則(從/到/往/至/在 + 命名 + 頓號列表 + 別是巴)驗證後保留 26 sources
  - **generic-events**:16 節點(日子 mc=413、長子、結局、問候...)DETACH DELETE + Qdrant 16 points + PG 16 entities/128 mentions
  - **yehehua**:Neo4j label Group→Person + PG type + Qdrant payload 三庫同步(entity_id 不變)
- `scripts/entity_extraction/pericope_miner.py`:`GENERIC_TITLE_STOPLIST`(24 詞)在 EVENT 預設前攔截,防重抽再犯

### 5. 未分類關係搶救

- `scripts/backfill_event_relations.py`(新):`relations_unclassified.jsonl` 中 Event–Person 6,419 條(去重 5,946)→ `(Person)-[:PARTICIPATED_IN]->(Event)`;Event–Place 3,951(去重 3,616)→ `(Event)-[:OCCURRED_IN]->(Place)`
- 邊屬性:`confidence: 0.35, extraction_phase: 5, notes: 'cooccurrence-backfill', evidence_count`(共現 pericope 數)— 與 LLM 抽取邊可區分,未來可過濾
- MERGE ON CREATE:既有分類器產出邊零污染;skipped 426 對 = 節點已刪(泛名詞 Event 先清理的紅利)
- Event–Event 277 條**未搶救**(共現推不出時序方向,P2 處理)

### 6. TSK 串珠

- `scripts/import_tsk_crossrefs.py`(新):openbible.info CC-BY 資料(scrollmapper/bible_databases,copy 存 `output/cross_references_tsk.txt`)
- 344,799 行 → 負 votes 過濾 1,166、自環剔除 9,811 → **250,358 unique pericope 對**,僅 7 條 unmapped
- verse→pericope 映射自 `embedding_queue.jsonl`(31,102 節全蓋,`1-2` 範圍節號展開)
- **檢索端連動修復**(`backend/database/neo4j_db.py`):TSK 後串珠圖變稠密(單 seed 2-hop 可達 97.7% 全庫、1-hop 平均 ~180 鄰居),原 `ORDER BY hop_distance LIMIT 30` 淪為隨機取樣 → 改為 **seed_support(多 seed 交集)+ votes 排序**,markdown 手工邊視為最高可信(999);2+ hop 只在 1-hop 補不滿 limit 時 fallback。驗證:mat:5 seeds 的 top1 = luk:6「論福和禍」(平原寶訓)✓

## 備份與回滾

| 檔案 | 內容 |
|---|---|
| `output/backups/dan_mentions_20260706_102830.jsonl` | 刪除的 733 條 place:dan MENTIONS 邊 |
| `output/backups/generic_events_20260706_102830.jsonl` | 16 個泛名詞 Event 節點(含全部邊) |
| verse 回填回滾 | `MATCH (:Pericope)-[r:MENTIONS {backfilled: true}]->() DELETE r` |
| 關係搶救回滾 | `MATCH ()-[r]->() WHERE r.notes = 'cooccurrence-backfill' DELETE r` |
| TSK 回滾 | `MATCH ()-[r:CROSS_REFERENCES {source: 'tsk'}]->() DELETE r` |

## 殘餘問題(P1+ 範疇)

1. **164 個 chunk-only 失明實體**(Person 85/Place 55/Group 24)— M3 雙層錯位,需 P1 抽取輸入解耦
2. **alias coverage 仍 0.5%** — 字典已榨乾;量產靠 P1 post-hoc ER merge 時把被併 surface form 寫入 aliases
3. **未分類關係其餘 67,306 條**(Object-Person 20,690 / Group-Person 17,640 / ...)待 P1 LLM 升級後重分類
4. Event–Event 277 條時序邊(P2 ATOM/E²RAG 範式)
5. place:dan 在 Qdrant 的向量仍基於舊 description(P1 description 重生成一併處理)
6. Person「猶大」「路得」缺節點、以色列(Place)/以色列人(Group)分裂(P1 ER)
7. `evaluation/` 100 題 A/B 重跑驗證檢索指標(建議先跑 graph vs semantic 對照,盯 PERSON hit_rate 與 EVENT ctx_recall)
