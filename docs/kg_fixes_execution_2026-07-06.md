# P0-Eval 三修復執行紀錄(排序融合層)

**日期**:2026-07-06
**依據**:[kg_p0_eval_p1_decision_2026-07-06.md](kg_p0_eval_p1_decision_2026-07-06.md) §4.2 三件天級修復(1 → 2 → 3)
**性質**:檢索端程式碼修復 + 資料修補(不重抽);P1 全量重抽依決策維持暫緩

---

## 執行結果總覽

| # | 決策文件事項 | 實作 | 對症驗證 |
|---|---|---|---|
| 1 | 修 TSK cross_ref 融合副作用 | expand limit 30→10;TSK 邊(votes<999)hop weight 0.60/0.50(壓到 semantic 0.7 之下),手工 markdown 邊(votes=999)維持 0.75/0.55;R5 停止 blanket 抬升 expand 候選至 0.85;候選帶 `votes`/`seed_support` | EVENT_017/PERSON_011/GENERAL_013 的 cross_ref 竄位候選讓位 |
| 2 | 頭部 Event aliases 補灌 + EQ 重啟 | `scripts/backfill_head_events.py`:11 個既有 Event 灌問法別名 + **18 個 curated Event 節點/56 條 MENTIONS 邊**(錨點全部 live 驗證);三庫同步(Neo4j+PG+Qdrant 29 實體重嵌入);`RAG_USE_ENTITY_QUERY=true`;EVENT_KEYWORDS 新增「客西馬尼禱告」 | EVENT_008 王國分裂→1ki:12:0、EVENT_014 最後的晚餐→jhn:13/luk:22(graph_event 從空手到滿榜) |
| 3 | 排序融合(原 P3 提前) | `fused = (1-α)·rerank_score + α·strategy_weight`,α=0.3;全池打分後融合排序;per-request `fusion_alpha` 覆寫供 sweep | rr≈0.001 的正解錨點(最後的晚餐 vs 古文無此詞)靠 prior 0.85 進 top-5 |

### 第二輪連鎖修復(round-1 全量 eval 逐題查因後)

| 問題(round-1 數據) | 根因 | 修復 |
|---|---|---|
| GENERAL_005 hit 1→0:`exo:29:0` 與 chunk `exo:29:0:0` 同內容佔兩席,擠掉 GT heb:7:0 | graph/EQ 檢索返回 chunk 級錨點,`_dedup` 按 id 無法識別粒度重複(M3 雙層錯位的檢索端殘留) | neo4j_db 五個查詢 Cypher 級 **chunk→parent Pericope remap**(431/431 chunk 有 CONTAINS parent);附帶紅利:164 個 chunk-only 失明實體獲得 pericope 級檢索可見性 |
| GENERAL_003/020 ndcg/mrr 大跌:rr≈0.002 的 EQ 雜訊(ezk:25:0、zec:3:0)被 pin 到第 1 | EQ-pin/graph uncertainty pin 是融合層之前的舊設計;融合已把 EQ/graph 訊號連續透出,pin 只剩誤傷 | 融合啟用時**停用 EQ-pin 與 graph uncertainty pin**(book_anchor pin 與 chapter-pin 保留);legacy(fusion off)路徑不變 |
| EVENT_019 仍 miss:act:9:0 排第 7(rr=0.074,act:9 通篇稱「掃羅」,問法是「保羅歸主」;top1 為字面高分的 act:18) | 字面斷裂 + uncertainty gate 被字面高分噪音關閉 | 新增 **keyword-exact event pin**:詞典 event keyword 與實體 name/alias 完全相等(curated 橋)→ 無條件 pin 該事件第一錨點;非 hub(mc≤25)、每事件 1 錨、至多 2 個 — 與 book_anchor pin 同一「使用者字面指名」邏輯 |

## 檢索指標(quick eval,與正式管線同一指標程式碼;基線 = 以同工具重算 P0 後 raw_responses,與發布數字 bit-exact)

100 題,`evaluation/results_quick/{p0_baseline,fixes_alpha03,fixes_r2_alpha03}.json`:

| 題型 hit_rate | P0 前 | P0 後(基線) | 三修復後(round-2) | Δ vs 基線 |
|---|---|---|---|---|
| EVENT | 0.90 | 0.80 | **1.00** | **+0.20** |
| PERSON | 0.95 | 0.95 | 0.95 | 0 |
| GENERAL | 0.90 | 0.90 | 0.90 | 0 |
| TOPIC | 1.00 | 1.00 | 1.00 | 0 |
| VERSE_LOOKUP | 1.00 | 1.00 | 1.00 | 0 |
| **OVERALL** | 0.95 | 0.93 | **0.97** | **+0.04** |

其他 overall 指標(P0 後 → 修復後):recall@5 0.866→**0.906**(+0.040)、ndcg@5 0.850→0.865(+0.016)、mrr 0.798→0.834(+0.036)、precision@5 0.352→0.370。EVENT recall@5 0.775→**0.975**(+0.20)、EVENT mrr +0.114;TOPIC mrr +0.133(sql_chapter 融合紅利)。

- hit 翻正四題:EVENT_008(王國分裂,aliases+EQ)、EVENT_014(最後的晚餐,curated 節點+融合)、EVENT_017(復活當天,TSK 降權)、EVENT_019(保羅歸主,keyword-exact pin)— **TSK 副作用五題全數回收,且 EVENT 超越 P0 前水準(0.90→1.00)**
- EVENT_015 recall 0.5→1.0、mrr→1.0(mat:26:6 top1 + luk:22:6 回榜)
- GENERAL ndcg 殘餘 -0.08:逐題查證為 P0 時代 chapter-pin 人工置頂 vs 融合自然排位的 artifact(GENERAL_007/019:正解 rr 僅 0.267,P0 的 mrr=1.0 靠 pin 撿救置頂;現在自然排第 4,hit 不變)+ GENERAL_013 的 act:2:1(五旬節復活講道,語意相關但 GT 未列)
- PERSON_004(三兄妹)維持 miss — 決策文件既判的 P3 層級(跨章彙總),非本輪 scope
- round-1(僅修復 1+2+3)→ round-2(+ chunk remap、pin 汰換、keyword pin)增量:EVENT +0.05、GENERAL hit +0.05、GENERAL ndcg 0.681→0.724

### α 消融(`fixes_r2_alpha0.json`,per-request fusion_alpha=0 = 純 reranker 排序,其餘修復不變)

α=0 已達 overall hit 0.97 / EVENT 1.00(資料修補 + keyword-exact pin 飽和了 hit);α=0.3 的連續融合項貢獻在**尾部錨點覆蓋**:EVENT recall +0.025(EVENT_014 的多福音平行錨 rr≈0.01-0.02,純字面排序下只有 pin 保的 1 條存活)與 TOPIC mrr +0.133,代價是 top-5 內部排位 ndcg −0.02(高 prior 低字面候選前移)。對 answer 端(top-5 全數進 context)recall 權重高於內部排位 → **定案 α=0.3**。論文可引的互補結構:hit 由離散修復(curated 資料 + 字典 pin)飽和,recall 長尾由連續融合補;二者對 BGE 字面排序的替代機制不同層。

## 新工具

- **`evaluation/quick_retrieval_eval.py`**:retrieval-only 快速迴路(backend 新 flag `retrieval_only` 跳過答案生成),100 題檢索指標 ~15 分鐘(vs 全管線 2.5h);`--from-raw` 重算既有 raw_responses、`--compare` 出 Δ 表與 hit 翻轉清單;per-question `source_detail` 含 strategy/fused/rerank 三欄
- **Source schema 增強**:`strategy`(來源策略)與 `rerank_score`(原始 reranker 分)寫入 API 回應 — 逐題查因不再需要反推
- **`fusion_alpha` per-request 覆寫**:alpha sweep 不需重啟 backend

> 目錄註記:P0 後全管線輸出 `evaluation/results_graph/`(決策文件所引)已改名 `evaluation/results_graph_p0_after/`;修復後的全管線重跑寫入新的 `results_graph/`。

## 全管線正式跑(collect + RAGAS + coverage,2026-07-06 16:43–19:07,條件與 P0 後基線一致:answer=gemma4:e4b、judge=gemma4:26b)

Overall(P0 後 → 修復後):

| 指標 | P0 後 | 修復後 | Δ |
|---|---|---|---|
| hit_rate | 0.9300 | **0.9700** | +0.0400 |
| recall@5 | 0.8658 | **0.9058** | +0.0400 |
| ndcg@5 | 0.8496 | 0.8653 | +0.0157 |
| mrr | 0.7978 | 0.8335 | +0.0357 |
| ragas_context_recall | 0.7767 | **0.8297** | **+0.0530** |
| answer_coverage | 0.7253 | **0.7664** | +0.0411 |
| ragas_answer_correctness | 0.5960 | 0.6173 | +0.0213 |
| ragas_faithfulness | 0.9564 | 0.9495 | −0.0069(雜訊級) |
| semantic_similarity | 0.7808 | 0.7888 | +0.0080 |

決策文件 §3 指定盯的兩個訊號雙雙回收:

- **EVENT ctx_recall 0.546 → 0.728(+0.182)** — 不只收復 TSK 副作用(P0 前 0.608),直接超越;EVENT coverage +0.092、correctness +0.071
- **PERSON ctx_recall 0.683 → 0.745(+0.062)**、coverage +0.023(hit 維持 0.95,長尾盲點如前)
- 其他:GENERAL coverage +0.041、TOPIC coverage +0.025、VERSE_LOOKUP coverage 0.975→1.000
- 檢索指標與 quick eval 完全一致(hit 0.97 / recall 0.906)— retrieval-only 快速迴路的可信度得到全管線覆核

與 semantic 基線(0.81/0.7575)的差距擴大到 hit +0.16、recall +0.148。answer 端全面上揚而 faithfulness 持平,表示增益來自「更對的 context」而非生成端波動。

## 回滾

| 項目 | 方式 |
|---|---|
| curated Event 節點 | `MATCH (e:Event {source:'head_event_backfill'}) DETACH DELETE e` + PG DELETE + Qdrant delete |
| alias 補灌 | `output/backups/head_events_20260706_152318.json` 內 before 快照 |
| 排序融合 | `.env RAG_RANK_FUSION_ENABLED=false`(完整 legacy 行為含三 pin) |
| TSK 降權/cap | `.env RAG_CROSS_REF_EXPAND_LIMIT=30` + revert cross_ref_retriever |

## 論文素材(接 P0-eval negative result 的正面收尾)

P0 建圖大修在頭部 benchmark 讀數為零的癥結被第三輪證據鏈閉環:**last-mile 是排序融合層**。α=0.3 的線性融合讓「rr≈0.001 但 graph prior 0.85」的正解(最後的晚餐 — 現代問法詞彙不存在於古譯本經文)進入 top-5;keyword-exact pin 處理融合也救不了的「敘事表面形式斷裂」極端案(act:9 通篇「掃羅」vs 問法「保羅」,rr=0.074)。與 BRINK(KG 缺陷→答案品質非線性)+ Unbiased GraphRAG eval(排序偏差)的呼應維持成立;新增可引用的機制級 negative finding:**pin 式離散補救在連續融合上線後由淨正轉淨負**(GENERAL_003/020 EQ-pin 竄位),補救機制需隨排序架構演進而退役。
