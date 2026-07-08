# 知識圖譜優化進度總覽

**最後更新**:2026-07-06(排序融合層上線後)
**性質**:活文件 — 各階段狀態的單一入口;細節見各執行紀錄

**文件鏈**(執行/決策紀錄已歸檔於 `records/`):
1. [records/2026-07-05_kg_optimization_analysis.md](records/2026-07-05_kg_optimization_analysis.md) — 缺口體檢、chunking→KG 因果鏈、P0–P3 路線圖、文獻
2. [records/2026-07-06_kg_p0_execution.md](records/2026-07-06_kg_p0_execution.md) — P0 六項資料修復執行紀錄
3. [records/2026-07-06_kg_p0_eval_p1_decision.md](records/2026-07-06_kg_p0_eval_p1_decision.md) — P0 後評估(negative result)與 P1 暫緩決策
4. [records/2026-07-06_kg_fixes_execution.md](records/2026-07-06_kg_fixes_execution.md) — 排序融合層三修復 + 連鎖修復執行紀錄

---

## 1. 一頁式狀態

### P0 — 資料修補,不重抽 ✅ 全部完成(2026-07-06,commit `7ae55d7`)

| 項目 | 狀態 | 成果 |
|---|---|---|
| verse mention 回填 | ✅ | +5,853 Pericope 錨點;失明實體 1,474 → 164;anchor coverage 83.8% → 98.2% |
| 修匯入靜默丟棄 | ✅ | verse remap + 誠實計數器(防再犯) |
| aliases 字典直灌 | ✅ | 38 節點(字典可覆蓋上限) |
| 噪音 gate | ✅ | 「但」錨點 759→26(發現子字串誤命中 399 條)、16 泛名詞 Event 刪除、耶和華 Group→Person |
| 未分類關係搶救 | ✅ | +5,641 PARTICIPATED_IN、+3,419 OCCURRED_IN;Event 參與者 34%→84%、地點 32%→75% |
| TSK 串珠匯入 | ✅ | CROSS_REFERENCES 916 → 250,418;檢索端 votes 排序連動修復 |

### P0 後評估 → 決策 ✅ 完成(2026-07-06)

100 題 A/B:檢索指標零受益甚至微降(hit 0.95→0.93、EVENT −0.10)。三機制:TSK votes 主題噪音擠敘事段、最終排序 100% 由 BGE-reranker 字面分數決定、benchmark 只問頭部實體。**結論:P1 全量重抽暫緩,先修排序層** — 此 negative result 為論文素材(呼應 BRINK、Unbiased GraphRAG eval)。

### 排序層三修復 + 連鎖修復 ✅ 全部完成(2026-07-06,commit `046040a`)

| # | 修復 | 路線圖出處 | 狀態 |
|---|---|---|---|
| 1 | TSK cross_ref 抑噪(cap 30→10、votes 分權:手工邊 0.75 / TSK 邊 0.60) | P0 第 6 項副作用修正(路線圖外) | ✅ |
| 2 | 頭部 Event 補灌(11 alias + 18 curated 節點/56 邊、三庫同步)+ EQ 重啟 | **P1 第 4/5 項輕量版**(curated 人工版,非全量 ER) | ✅ |
| 3 | 排序融合 `fused=(1−α)·rerank+α·weight`,α=0.3(消融定案) | **P3 提前**(圖/向量分數融合) | ✅ |
| 4a | chunk→pericope Cypher remap(五查詢;chunk 雙席 bug + chunk-only 實體檢索端可見) | 連鎖修復(round-1 逐題查因) | ✅ |
| 4b | 融合模式汰換舊 EQ-pin / graph uncertainty pin(融合下只剩誤傷) | 連鎖修復 | ✅ |
| 4c | keyword-exact event pin(詞典 keyword == alias 完全相等 → 無條件 pin;救「掃羅 vs 保羅歸主」表面形式斷裂) | 連鎖修復 | ✅ |

### P1 — 管線修復後全量重抽 ⏸ 暫緩(依決策)

| 項目 | 狀態 |
|---|---|
| 1. 抽取輸入與 embedding 佇列解耦 | ⏸ 暫緩 |
| 2. coref pass(LINK-KG 配方) | ⏸ 暫緩 |
| 3. gleanings 多輪補抽(nano-graphrag 迴圈) | ⏸ 暫緩 |
| 4. post-hoc entity resolution(merge 寫 aliases、型別多數決) | ⏸ 暫緩(**輕量 curated 版已做**:頭部 29 節點) |
| 5. description 重生成 | ⏸ 暫緩(EQ 已重啟,head event 的 curated description 已補) |
| 6. 抽取模型升級 + STOPWORDS 重審 | ⏸ 暫緩 |

**重啟條件**(決策 §4.3):先改評估設計 — 長尾敏感題(chunk-only 實體題)、BRINK 式缺陷注入、或擴 ground truth 至被切塊 pericope 的人物×事件題;否則 P1 做完在現 100 題上讀數仍為零。本輪結果反向印證:不動抽取管線、只修排序層,EVENT 即 0.80→1.00。

### P2 — 事件層(ATOM/E²RAG 時序因果) ⬜ 未開始

Event–Event 時序邊仍 45+277 條級;P0 已把參與者/地點補到 84%/75%,時序建模待 P2。

### P3 — 階層與檢索融合 ◐ 部分提前

- 分數融合:✅ 已以排序融合層提前落地
- Leiden 社群摘要 / RAPTOR 跨章彙總:⬜ 未開始(PERSON_004 型跨章彙總題的對症)

---

## 2. 指標演進(100 題,graph 模式;檢索指標程式決定性計算,三時點同一套代碼)

| 指標 | P0 前(5/16) | P0 後 | **排序修復後** | 修復 Δ |
|---|---|---|---|---|
| hit_rate | 0.9500 | 0.9300 | **0.9700** | +0.0400 |
| recall@5 | 0.8892 | 0.8658 | **0.9058** | +0.0400 |
| ndcg@5 | 0.8563 | 0.8496 | 0.8653 | +0.0157 |
| mrr | 0.8020 | 0.7978 | 0.8335 | +0.0357 |
| ragas_context_recall | 0.7908 | 0.7767 | **0.8297** | +0.0530 |
| answer_coverage | 0.7223 | 0.7253 | **0.7664** | +0.0411 |
| ragas_answer_correctness | 0.5874 | 0.5960 | 0.6173 | +0.0213(雜訊邊緣) |
| ragas_faithfulness | 0.9513 | 0.9564 | 0.9495 | −0.0069(雜訊) |

分題型關鍵訊號:

| 訊號 | P0 前 | P0 後 | 修復後 | 備註 |
|---|---|---|---|---|
| EVENT hit / recall | 0.90 / 0.875 | 0.80 / 0.775 | **1.00 / 0.975** | TSK 副作用五題全回收並超越 P0 前 |
| EVENT ctx_recall | 0.608 | 0.546(墊底) | **0.728** | 決策文件盯的訊號 #1 |
| PERSON hit | 0.95 | 0.95 | 0.95 | 長尾盲點(P1 範疇);ctx_recall 0.683→0.745 |
| TOPIC / VERSE | 1.00 | 1.00 | 1.00 | 零退步;TOPIC mrr +0.133 |
| vs semantic 基線 | hit +0.14 | +0.12 | **+0.16** | 差距擴大 |

α 消融(`results_quick/`):α=0 已飽和 hit(0.97);α=0.3 貢獻尾部錨點覆蓋(EVENT recall +0.025、TOPIC mrr +0.133),代價 top-5 內部排位 ndcg −0.02 → 定案 0.3。

---

## 3. 目前系統開關狀態(.env)

| 開關 | 值 | 備註 |
|---|---|---|
| RAG_USE_GRAPH | true | per-request 可覆寫 |
| RAG_USE_CROSS_REF_EXPAND / LIMIT | true / **10** | 30→10(TSK 抑噪) |
| RAG_USE_ENTITY_QUERY | **true** | 2026-05 因 reranker 擠出而停用 → 融合層上線後重啟 |
| RAG_RANK_FUSION_ENABLED / ALPHA | **true / 0.3** | false = 完整 legacy(含三舊 pin) |
| pins(融合模式) | chapter-pin、book_anchor pin、keyword-exact event pin | EQ-pin / graph uncertainty pin 已汰換(legacy 路徑保留) |

---

## 4. 殘餘問題清單(彙整自各紀錄)

| # | 問題 | 對症層級 |
|---|---|---|
| 1 | 164 個 chunk-only 失明實體 — 檢索端已由 remap 恢復可見,**圖譜層**仍缺 Pericope MENTIONS | P1 抽取解耦 |
| 2 | alias coverage 仍 ~0.8%(43+29 節點)— 字典與 curated 已榨乾,量產靠 ER merge 寫回 | P1 第 4 項 |
| 3 | 67,306 條未分類關係(Object-Person 20,690 / Group-Person 17,640 / …) | P1 LLM 重分類 |
| 4 | Event–Event 時序邊僅 45+277 候選 | P2 |
| 5 | description 品質(NER 型 46% 無 description;EQ via_entity 雜訊如 act:18↔保羅歸主) | P1 第 5 項 |
| 6 | 重名分裂:猶大/路得缺節點、以色列(Place)/以色列人(Group) | P1 ER |
| 7 | PERSON_004 三兄妹跨章彙總題(唯一 hit=0) | P3(RAPTOR/社群摘要) |
| 8 | GENERAL ndcg −0.08 vs P0 後 — 查證為 P0 pin 人工置頂 artifact,正解均在 top-5 | 記錄,無行動 |
| 9 | correctness 增益微弱(+0.02,雜訊邊緣)— 檢索改善傳導到 judge 分數有衰減 | 生成/評估端(換 answer 模型或人工評閱) |

---

## 5. 工具與可復現性

- **quick eval 快速迴路**:`evaluation/quick_retrieval_eval.py` — retrieval-only 100 題 ~15 分鐘(全管線 2.5h);`--from-raw` 重算任意 raw_responses(vs 發布數字 bit-exact)、`--compare` Δ 表 + hit 翻轉清單、`--alpha` sweep 不需重啟 backend。已由全管線覆核(檢索指標完全一致)
- **API 觀測欄位**:Source.strategy / Source.rerank_score(fused 與 raw 並列)、stats.fusion_alpha、`retrieval_only` flag
- **評估結果目錄**:`results_graph/`(修復後全管線)、`results_graph_p0_after/`(P0 後基線)、`results_graph_gemma_answer/`(P0 前 5/16)、`results_quick/`(四組對照含 α 消融)
- **回滾**:curated 節點 `MATCH (e:Event {source:'head_event_backfill'}) DETACH DELETE e`;aliases 快照 `output/backups/head_events_20260706_152318.json`;融合 `RAG_RANK_FUSION_ENABLED=false`;TSK 邊 `MATCH ()-[r:CROSS_REFERENCES {source:'tsk'}]->() DELETE r`

## 6. 下一步選項(依優先序)

1. **論文寫作**:三輪證據鏈已閉環(P0 negative result → 排序層診斷 → 修復驗證 +α 消融),素材見各紀錄「論文素材」節
2. **長尾敏感評估設計**(P1 重啟的前置):chunk-only 實體題、BRINK 缺陷注入、被切塊 pericope 的人物×事件題
3. **P2 事件層**:Event–Event 時序(ATOM dual-time / E²RAG 雙圖)— P0 已備妥參與者/地點基礎
4. **P3 跨章彙總**:RAPTOR collapsed tree 或 Leiden 社群摘要 — PERSON_004 型的對症
5. **生成端**:correctness 瓶頸已移到 answer 模型(gemma4:e4b)與 judge — 可 A/B claude answer(注意 RAGAS noncommittal 拒答假象)
