# P0 修復後評估結果與 P1 決策分析

**日期**:2026-07-06
**依據**:[2026-07-05_kg_optimization_analysis.md](2026-07-05_kg_optimization_analysis.md) 第 3 節路線圖、[2026-07-06_kg_p0_execution.md](2026-07-06_kg_p0_execution.md) 殘餘問題 7(100 題 A/B 重跑驗證)
**方法**:P0 執行完畢後全量重跑 100 題 graph eval,與 5/16 基線逐題對比;所有退步/持平題逐題查 raw sources 與程式碼驗證機制,非統計推測。

---

## 0. 結論摘要

**P1 全量重抽建議「暫緩」。**

1. P0(anchor coverage 83.8%→98.2%、串珠 916→250,418)在 100 題 eval 上**檢索指標零受益甚至微降**(hit_rate 0.95→0.93),answer 端僅雜訊級微升。
2. 三個機制解釋此結果:**TSK votes 排序在事件敘事題引入主題性噪音**(EVENT hit −0.10)、**最終排序 100% 由 BGE-reranker 字面分數決定**(圖譜訊號在 last-mile 全部丟失)、**benchmark 只問頭部實體**(P0 活化的 1,310 個長尾實體讀數為零)。
3. 排序融合層才是結構性瓶頸——與 5 月「reranker 擠出 entity_query」是同一瓶頸的第二輪獨立證據。P1 繼續投建圖品質,增益會同樣被排序層吃掉。
4. 改為先做三件天級修復:**修 TSK cross_ref 融合副作用、頭部 Event aliases 補灌 + EQ 重啟(即 P1 第 4/5 項輕量版)、排序融合(原 P3 提前)**。
5. 論文價值:此 negative result(「KG 完整性大修在頭部 benchmark 檢索指標不動,瓶頸在排序融合層」)直接呼應 BRINK 與 Unbiased GraphRAG eval,比「全面提升」更有洞察。

---

## 1. 評估執行條件(可比性驗證)

| 項目 | 本次(P0 後) | 5/16 基線(P0 前) | 相同? |
|---|---|---|---|
| RAG 回答模型 | `gemma4:e4b-it-q8_0`(backend env + 實測 ollama 載入驗證) | 同(git 63c133e 文檔記載) | ✅ |
| Judge 模型 | `gemma4:26b-a4b-it-q8_0`(RAGAS + coverage 兩路徑確認) | 同 | ✅ |
| entity_query | `RAG_USE_ENTITY_QUERY=false` | off(舊 raw_responses 無 EQ strategy) | ✅ |
| 路由分布 | R1=20 R2=25 R3=21 R4=18 R5=10 R6=4 fallback=2 | 完全相同 | ✅ |
| backend image | 含 P0 檢索端修復(image 10:39 build > neo4j_db.py 10:37) | — | — |
| 圖譜狀態 | CROSS_REFERENCES 250,418 / PARTICIPATED_IN 7,130 / 回填 MENTIONS 5,782(live 查核) | P0 前圖譜 | **唯一系統差異** |

- 執行耗時:收集 36 分(100/100,無 strategy error)+ RAGAS 1h42m(400 metric 步,ollama 串行)+ coverage 13 分 ≈ **2.5 小時**。
- 輸出:`evaluation/results_graph/`(evaluation_results.json / .csv / dashboard.html / raw_responses.json)。
- 100 題 = VERSE_LOOKUP / TOPIC / PERSON / EVENT / GENERAL 各 20。

---

## 2. 結果:P0 前後對比

### 2.1 Overall

| 指標 | P0 前 graph | P0 後 graph | Δ | semantic 基線 |
|---|---|---|---|---|
| hit_rate | 0.9500 | 0.9300 | **−0.0200** | 0.8100 |
| recall@5 | 0.8892 | 0.8658 | −0.0234 | 0.7575 |
| ndcg@5 | 0.8563 | 0.8496 | −0.0067 | 0.6863 |
| mrr | 0.8020 | 0.7978 | −0.0042 | 0.6472 |
| ragas_context_recall | 0.7908 | 0.7767 | −0.0141 | 0.6767 |
| answer_coverage | 0.7223 | 0.7253 | +0.0030 | 0.6278 |
| ragas_answer_correctness | 0.5874 | 0.5960 | +0.0086 | 0.5130 |
| ragas_faithfulness | 0.9513 | 0.9564 | +0.0051 | 0.9030 |
| semantic_similarity | 0.7802 | 0.7808 | +0.0006 | 0.7453 |

**淨效應 ≈ 0**:檢索端微降(全部可歸因於 §3.1 的 TSK 副作用)、answer 端微升(雜訊範圍內)。graph 對 semantic 的整體優勢維持(hit +0.12、recall +0.11)。

### 2.2 分題型(檢索指標為主)

| 題型 | hit(前→後) | recall@5(前→後) | ctx_recall(前→後) | 備註 |
|---|---|---|---|---|
| VERSE_LOOKUP | 1.00 → 1.00 | 1.000 → 1.000 | 1.000 → 1.000 | R1 不經圖,零變化 |
| TOPIC | 1.00 → 1.00 | 1.000 → 1.000 | 0.963 → 0.963 | 檢索零變化;**coverage +0.031**(0.856→0.888) |
| PERSON | 0.95 → 0.95 | 0.917 → 0.917 | 0.667 → 0.683 | **逐題一致,唯一 miss 仍是 PERSON_004;仍輸 semantic(1.00/0.967)** |
| EVENT | **0.90 → 0.80** | **0.875 → 0.775** | **0.608 → 0.546** | 退步集中三題,見 §3.1 |
| GENERAL | 0.90 → 0.90 | 0.654 → 0.638 | 0.717 → 0.692 | GENERAL_013 同 §3.1 機制 |

分析報告 §3 驗收方式指定盯的兩個訊號,**雙雙未達預期**:PERSON 檢索未回升(長尾盲點,§3.3)、EVENT ctx_recall 不升反降(TSK 副作用,§3.1)。

### 2.3 Answer 端正向小訊號(雜訊範圍內,列供參考)

- PERSON:coverage +0.033、correctness +0.023、ctx_recall +0.017
- TOPIC:coverage +0.031
- overall faithfulness +0.005

judge 單題雜訊 ±0.4(前輪已記載)、by-type 僅 20 題 → ±0.05 級別不具顯著性。retrieval 指標為程式對 ground truth 計算,逐題可復現,可信。

---

## 3. 機制診斷(逐題查證)

### 3.1 TSK votes 排序是雙面刃 —— EVENT 退步的直接原因

P0 把串珠從 916 條手工邊擴到 250,418 條 + 檢索端改 votes 排序後,cross_ref_expand / cross_reference(R5)從「多數題無鄰居、擴展空手」變成「任何 seed 都有 ~180 個 1-hop 鄰居、必然灌入 top-30 高 votes 候選」。**votes 高 = 神學主題強關聯,但不等於同一事件敘事**:

| 題 | P0 前 sources(正確) | P0 後 sources(被擠) | 擠入者的串珠邏輯 |
|---|---|---|---|
| EVENT_019 保羅歸主 | `act:9:0`(大馬士革)、`act:22:1`、`act:26:1`(自述)全中 | 全滅,換入 `act:13`×2、`act:28:2`、`rom:1:0` | 保羅宣教主題串珠(P0 前此題 cross_ref_expand 空手,P0 後必然觸發) |
| EVENT_017 復活當天 | `luk:24:0`(以馬忤斯)、`mrk:16:0` | 換入 `mrk:9:1`、`mat:17:0`(登山變像) | 「人子從死裡復活」預言串珠 |
| EVENT_015 客西馬尼 | `luk:22:6` | 換入 `rom:8:0`、`eph:6:2` | 「禱告」主題串珠 |
| PERSON_011 以利亞以利沙 | `1ki:19:1`(呼召) | 換入 `mat:27:6` | 十架旁「看以利亞來不來」串珠(ndcg −0.33) |
| GENERAL_013 林前15 vs 創世記 | `1co:15:1`、`isa:49:1` | 換入 `act:2:1`、`rom:6:0`、`rev:21:0` | 復活/死亡主題串珠(R5 cross_reference 同機制) |

EVENT hit=0 的題:P0 前 {008, 014} → P0 後 {008, 014, **017, 019**}。既有失敗未修,新增兩題。

**同一機制對 TOPIC 是紅利**:mat:5 → luk:6(平原寶訓)正是 P0 執行紀錄驗證過的好案例,TOPIC coverage +0.031。主題彙總題受益、事件敘事題受害——修復方向必須題型敏感,不能一刀切回滾。

### 3.2 最終排序 100% 由 reranker 字面分數決定 —— 結構性瓶頸

`backend/utils/reranker.py:79`:`ranked = sorted(passages, key=rerank_score)`。strategy weight(cross_ref_expand 0.75/0.55、semantic 0.7)與 votes **只決定誰進 pre-rerank 池與 seed 選擇,不參與最終排序**。因此:

- 建圖端改善(更多正確錨點進池)若字面分數不敵噪音候選,top-5 不變 → P0 錨點紅利被吃掉;
- 建圖端副作用(主題噪音進池)若字面分數高(「保羅」「復活」「禱告」字面全中),直接擠掉正確答案 → EVENT 退步。

與 5 月「BGE-reranker 字面 surface match 勝過 entity 錨點,擠出 entity_query」為**同一瓶頸的兩輪獨立證據**。

### 3.3 PERSON 零變化 = 長尾盲點

P0 回填活化的 1,310 個實體是「原本只在 verse 級被抽到」的長尾;100 題問的是頭部人物(以利亞、大衛、摩西),Pericope 錨點本來就充足。**建圖端的量變在這套 benchmark 上已飽和** —— 這是預測 P1 效益的關鍵前提。

### 3.4 持續失敗題根因分型(P0 前後都掛的題)

| 題 | 現象 | 根因 | 對症層級 |
|---|---|---|---|
| EVENT_008 王國分裂 | graph_event 空手(strategies 只剩 semantic+sql),semantic 撈到 `dan:11`(「南王北王」字面)、`dan:2/7` | 圖譜 Event 名為「北方的支派反叛」,與問法不匹配、無 aliases;EQ 停用後無實體橋接 | **aliases 補灌 + EQ 重啟**(P1 第 4/5 項輕量版,不需重抽) |
| EVENT_014 最後的晚餐 | graph_event 空手,semantic 撈到 `mrk:6:2`、`jdg:19:0`(利未人與妾) | 「最後的晚餐」不出現在和合本經文與圖譜實體名(「逾越節筵席」);同上 | 同上 |
| PERSON_004 三兄妹角色 | graph_person 撈到 `1ch:6:0` 家譜、`num:2:0` 安營次序、`1ch:24` 祭司班次 | MENTIONS 共現密度偏向名錄/家譜段;答案分散出 2–15 章 + 民 12,top-5 pericope 結構性不足 | **P3 層級**(RAPTOR / 社群摘要跨章彙總),P1 治不了 |

---

## 4. P1 決策建議

### 4.1 暫緩:P1 全量重抽(第 1/2/3/6 項)

抽取輸入解耦、coref pass、gleanings、抽取模型升級 —— 週級重抽工程。理由:

1. 這些項目的增益(mention 完整性、長尾實體活化、去重)集中在長尾,而 **P0 已示範長尾改善在這 100 題上讀數為零**(§3.3);
2. 排序層瓶頸未解前,建圖投資的 eval 可見度會繼續被 reranker 吃掉(§3.2);
3. 殘餘標的已縮小:chunk-only 失明實體僅 164 個(1.8%),P0 回填已救活 89%。

**不是否定 P1 的圖譜資產價值**(對論文的建置品質論證、對未來 P2 事件層仍有意義),而是:以 eval 指標為 P1 的執行理由,現階段不成立。

### 4.2 先做:三件天級、eval 可直接驗證的修復

| # | 事項 | 對症 | 預期回收 |
|---|---|---|---|
| 1 | **修 TSK cross_ref 候選融合副作用**:cross_ref_expand / R5 cross_reference 候選降 cap(30→10)或改 supplement-only(仿 EQ 設計:rerank 不足額才補位),或對事件敘事型 route 降權 | §3.1 五題 | EVENT hit +0.10、recall +0.10,GENERAL/PERSON 零星回收 |
| 2 | **頭部 Event aliases 補灌 + EQ 重啟 A/B**:把「最後的晚餐」「王國分裂」等問法別名灌入頭部 Event 實體(P1 第 4/5 項的資料修補版,天級、不需重抽);重開 `RAG_USE_ENTITY_QUERY` 跑對照 | EVENT_008/014 | EVENT hit 最多再 +0.10;同時檢驗 desc 品質是否已足支撐 EQ |
| 3 | **排序融合(原 P3 提前)**:最終排序改為 rerank_score × 圖譜訊號(strategy weight / votes / seed_support)融合分;兩輪獨立證據(5 月 EQ 被擠、本次 TSK 候選擠敘事段)都指向此處 | §3.2 結構性瓶頸 | 讓 #1/#2 與未來所有建圖改善能透出到 top-k |

執行順序建議 1 → 2 → 3(1 最便宜且獨立;3 動融合層,改完需全量重跑驗證)。

### 4.3 若未來要啟動 P1 全量重抽

評估設計必須先改,否則做完一樣讀不到:

- 用**長尾敏感**的評估:chunk-only 實體題、BRINK 式缺陷注入(移除邊觀測答案退化)、或擴 ground truth 至涵蓋被切塊 pericope 的人物×事件題;
- 建置期 CI 三指標(anchor coverage / duplicate rate / alias coverage)照 P0 已建立的量測持續追蹤 —— P1 的直接產出在這裡,不在 100 題 eval。

### 4.4 論文素材

本次結果是可直接入論文的 negative result:**「anchor coverage +14.4pt、串珠 ×273 的 KG 完整性大修,在頭部實體 benchmark 上檢索指標不動(PERSON 逐題一致)、事件敘事題反因主題性串珠噪音退步 —— 檢索品質的 last-mile 瓶頸在排序融合層,而非圖譜完整性」**。呼應:

- BRINK(arXiv:2508.08344):KG 缺陷 → 答案品質的非線性關係;
- Unbiased GraphRAG eval(arXiv:2506.06331):評估方法論警告;
- 本專案 5 月已記錄的 reranker 擠出 EQ 現象(兩輪證據閉環)。

---

## 附錄:驗證方法

- **可比性驗證**:`git show 63c133e:bible_rag_latest.md`(5/17 commit 記載 answer/judge 模型)、舊 raw_responses.json strategies 掃描(無 entity_query)、backend 容器 env 與 image build 時間比對、ollama 載入模型實測(query 前後 `ollama ps`)。
- **圖譜狀態 spot-check**(Neo4j live):CROSS_REFERENCES 250,418、PARTICIPATED_IN 7,130、backfilled MENTIONS 5,782。
- **逐題對比**:`results_graph/raw_responses.json` vs `results_graph_gemma_answer/raw_responses.json` 的 sources/strategies 逐題 diff;per-question metric delta ≥0.25 全數列出並查因。
- **程式碼驗證**:`backend/utils/reranker.py:54-79`(最終排序純 rerank_score)、`backend/utils/retrieval/cross_ref_retriever.py:52-109`(hop weight 與擴展)、`backend/utils/retrieval/router.py:448-520`(seed 選擇與融合)。
- 評估原始輸出:`evaluation/results_graph/`;逐題 CSV 可用於論文附錄。
