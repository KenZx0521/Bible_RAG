# 知識圖譜建置優化分析報告

**日期**：2026-07-05
**方法**：所有數據為當日 live 覆核（Neo4j Cypher 直查 + `output/*.jsonl` 精算 + 建置程式碼逐行驗證）；所有論文經 arXiv / ar5iv / ACL Anthology / 官方 repo 原始頁面抓取驗證，無法驗證者明確標注。

---

## 0. 結論摘要

「KG 品質與最初 chunking 方式有關」的假設**成立，但需精確化**：

1. 傷害 KG 品質的不是切塊參數（512/768/overlap 1）本身，而是**抽取、匯入、檢索三層都直接繼承了為 BGE-M3 embedding 設計的粒度結構**（粒度錯配）。
2. 三個最重的傷全由粒度錯配造成：**56% mention 匯入時靜默丟棄**、**169 個被切塊 pericope 對檢索與關係抽取雙重失明**、**跨粒度重複實體**。
3. 另一批大缺陷（aliases 空、無共指消解、無實體消解、事件層空殼）是**抽取管線缺功能**，與 chunking 無關——但 chunk 邊界會放大 coref 缺失。
4. 文獻與八大 GraphRAG 系統的共同結論：**512–768 token 已在抽取 recall 甜區，優化重點是 entity resolution + gleaning 補抽 + coreference，不是調 chunk size**。
5. 最大宗傷害的修復幾乎零成本：verse mention 回填一次可補 **+5,853 對錨點、活化 1,310 個失明實體**。

---

## 1. 現況缺口體檢（live 數據）

### 1.1 圖譜規模

| 項目 | 數值 |
|---|---|
| 實體 | 9,122（Person 2,418 / Object 2,200 / Event 1,712 / Place 1,299 / Theme 987 / Group 506）|
| 結構節點 | Pericope 2,779 / Chunk 431（**無 Verse 節點**）|
| MENTIONS 邊 | 41,140（Pericope→Entity 36,471 + Chunk→Entity 4,669）|
| 語意關係邊 | 6,958（37 種型別；top：PARTICIPATED_IN 1,521 / OCCURRED_IN 919 / SON_OF 659 / FATHER_OF 647 / POSSESSED 551）|
| 串珠 | CROSS_REFERENCES 916 |

### 1.2 八大缺口（全部有量化證據）

| # | 缺口 | Live 證據 |
|---|---|---|
| 1 | **aliases 空** | 9,122 實體僅 35 個有別名（0.38%）。live 全為原生 LIST，但 `import_neo4j.py:191` 現行碼寫 `json.dumps` 字串 → **重跑匯入會讓現有 Cypher 查詢失效（重建陷阱）** |
| 2 | **mention 大量流失** | 產出 173,896 條：verse 級 **97,235（55.9%）匯入時靜默丟棄**（無 Verse 節點，`import_neo4j.py:268` MATCH 落空 → MERGE 不執行、不報錯），計數器（L251,257）照加 → log 謊報「Imported 173,896」 |
| 3 | **失明實體 1,474 個（16%）** | 零錨點 1,030（Person 474 / Place 405 / Group 151）+ 僅錨 Chunk 444（Person 224 / Place 132 / Group 88）；`entity_path_retriever.py:39` 只認 `(Pericope)-[:MENTIONS]` → 對 R3/R6 檢索不可見 |
| 4 | **重名分裂** | 878 個名字 / 1,900 個節點（**全為跨型別分裂**，如約櫃 = Group+Object+Person+Place 四節點）；`EntityNormalizer._should_merge`（entity_normalizer.py:99-120）靠 aliases 比對，aliases 空 → 形同虛設 |
| 5 | **事件層空殼** | 1,712 個 Event：**96.2% 無時序因果邊**（PRECEDED_BY 24 + CAUSED 14 + SUCCEEDED_BY 7，共 45 條）、67.9% 無地點、47.8% 無參與者 |
| 6 | **關係匯入率 8.1%** | 85,439 候選 → 6,958 進圖；**77,953 條未分類**躺在 `relations_unclassified.jsonl`（Object-Person 20,690 / Group-Person 17,640 / Group-Place 11,861 / Person-Place 7,884 / **Event 相關 10,647**：Event-Person 6,419 + Event-Place 3,951 + Event-Event 277），每條都帶 `source_pericope_id`，是修事件層的現成素材 |
| 7 | **噪音實體** | Place「但」錨 685 來源（連接詞誤抓）；耶和華被分類為 Group（deg 2,455）；`event:rizi`「日子」mc=413（`pericope_miner.py:74-75` 標題預設全歸 EVENT）；以色列(Place, 753) vs 以色列人(Group, 549) 分裂 |
| 8 | **抽取品質上游** | 實體抽取 LLM 僅 **gemma3:4b**（entity_extraction/config.py:66-67）；STOPWORDS 把「神/靈/主」等 33 個單字詞全濾掉（pos_extractor.py:34-39）+ 所有單字實體被 `len<=1` 濾除；description 只是 100 字經文片段（extract_entities.py:174），NER 型實體 46% 無 description → 污染 entity 向量，是 reranker 擠出 entity_query 的上游共因 |

### 1.3 評估面對應（graph vs semantic，claude answer，100 題）

| 題型 | hit_rate | recall@k | nDCG | ctx_recall | coverage | correctness |
|---|---|---|---|---|---|---|
| VERSE_LOOKUP | 1.00 / 0.75 | 1.00 / 0.75 | 1.00 / 0.64 | 1.00 / 0.85 | 1.00 / 0.75 | 0.86 / 0.66 |
| TOPIC | 1.00 / 0.75 | 1.00 / 0.75 | 0.88 / 0.59 | 0.96 / 0.71 | 0.90 / 0.66 | 0.68 / 0.50 |
| GENERAL | 0.95 / 0.75 | 0.66 / 0.57 | 0.83 / 0.65 | 0.73 / 0.62 | 0.60 / 0.47 | 0.54 / 0.50 |
| **PERSON** | **0.95 / 1.00** | **0.92 / 0.97** | **0.90 / 0.92** | 0.69 / 0.65 | 0.64 / 0.62 | 0.49 / 0.50 |
| EVENT | 0.90 / 0.80 | 0.85 / 0.75 | 0.69 / 0.62 | **0.60** / 0.58 | 0.61 / 0.58 | 0.53 / 0.49 |
| **OVERALL** | 0.96 / 0.81 | 0.89 / 0.76 | 0.86 / 0.69 | 0.80 / 0.68 | 0.75 / 0.62 | 0.62 / 0.53 |

兩個關鍵訊號，與缺口一一對應：

- **PERSON 是 graph 唯一輸給 semantic 的題型** — Person 正是被粒度錯配（56% mention 丟棄集中在 NER 型）+ 無 coref + 重名分裂傷最重的實體型別。
- **EVENT ctx_recall 0.60 墊底** — 對應事件層空殼（96.2% 無時序）。

---

## 2. Chunking → KG 品質影響鏈（核心分析）

### 2.1 Chunking 現況事實（程式碼逐行驗證）

- 觸發門檻是 **max 768 tokens**（`hierarchical_chunker.py:58`），非 target 512；512 只是打包目標，另有 min 128、overlap 1 節（config.py:22-26）
- tokenizer 為 **BGE-M3**（tokenizer_wrapper.py:33-35），即切塊完全是為 embedding 模型設計
- chunk id 格式 `{pericope_id}:{n}`（hierarchical_chunker.py:161），如 `gen:1:0:0`
- 被切塊 pericope **169 個**（6%），集中於舊約敘事書卷（lev 13 / jdg 12 / 1sa 12 / gen 11 / num 11 / jos 10 / deu 9 / 2sa 9），佔全文字量 **18.3%**（243,773 / 1,329,046 字）
- 長度分布：pericope 中位 388 字 / p90 931 / max 3,544；**被切塊 pericope 中位 1,353 字 / max 3,544**；chunk 中位 644 / max 796 字

### 2.2 六個影響機制（按傷害排序）

**M1（結構性根因）：抽取餵料 = embedding 佇列。**
CKIP NER 的輸入直接是 `embedding_queue.jsonl`（extract_entities.py:48-57）= 2,610 pericope + 431 chunk + 31,031 verse。此佇列的粒度是為「檢索」設計的（process_bible.py:344-401：被切塊的 pericope 只入 chunk 級、不入 pericope 級；所有 verse 逐節入列），抽取管線無條件繼承。後面所有問題由此流下。

**M2：匯入層粒度不匹配 → 56% mention 蒸發。**
verse 級 mention 在 Neo4j 沒有對應節點 → 靜默丟棄 97,235 條。精算結果：verse source_id **100% 可 strip `:v:N` 還原 pericope id**（0 條失敗，含 `1-2` 範圍節號）；回填可新增 **5,853 對** unique (entity, pericope) 錨點（現有 Pericope 邊 +16%），**1,474 個失明實體活化 1,310 個（89%）**：person 613 / place 482 / group 215，僅殘 164 個 chunk-only。

**M3：雙層錯位 → 18.3% 文字雙重失明。**
被切塊 pericope 的 Person/Place/Group（NER 型）只錨在 Chunk/verse 層（live 證據：Chunk 節點的 MENTIONS **只有** Person 633 / Place 283 / Group 171 三型）；Event/Object/Theme（LLM 型，跑 pericope 全文）全錨 pericope 層。而 **`entity_path_retriever.py:39`（R3/R6 檢索）和 `pair_miner.py:21-22`（關係抽取 pair 挖掘）都只認 `(Pericope)-[:MENTIONS]`** → 這批舊約敘事段落的人物**既檢索不到、也從不參與關係抽取** — 正是「人物×事件」類問題的主戰場。

**M4：chunk 邊界 × 無 coref。**
全 repo 零共指消解（grep coref = 0），mention 靠 `text.find()` 字面比對（llm_extractor.py:351-352、ner_extractor.py:235）；overlap 只有 1 節，「岳父/他」的先行詞常在前一 chunk 之外（葉忒羅 exo:18 鐵證）。文獻量化：DocRED 顯示 **40.7% 關係事實必須跨句抽取、17.6% 需共指推理** — 這是切碎 + 無 coref 管線的結構性上限。

**M5：混合粒度 → 重複與漏抽不一致。**
GraphRAG 原論文實測：600 vs 2400 token chunk，實體引用數差**近 2 倍** — 粒度直接決定抽取密度。同一段文字以三種粒度各抽一次，同實體在細粒度抽到、粗粒度漏掉，僅靠 surface-form pinyin 當 id 去重（`lazy_pinyin` 無音調，另有**同音碰撞誤併**的反向風險）。

**M6：512/768 本來就不是為抽取設的。**
被切塊的 169 個 pericope 中位 1,353 字、最長 3,544 字 — 對 LLM 抽取全部塞得進 context（Lost in the Middle 的退化區間遠在其上）。「為 embedding 切、拿去抽取」是根本錯配：**抽取應該用 pericope 全文，chunk 只該是檢索/儲存單位**（Neo4j LLM KG Builder 的 `chunks_to_combine` 即此設計：儲存單位 ≠ 抽取單位）。

### 2.3 缺陷歸因表

| 缺陷 | chunking/粒度直接造成 | 管線缺功能 | 交互放大 |
|---|:---:|:---:|:---:|
| 56% mention 丟棄、1,474 失明實體 | ✅ M1+M2 | | |
| 切塊 pericope 檢索+RE 雙盲 | ✅ M3 | | |
| 跨粒度重複/漏抽 | ✅ M5 | | ✅ × 無 ER |
| 重名分裂 878 名、aliases 空 | | ✅ | ✅ × M5 |
| 共指遺漏（岳父/他） | | ✅ 無 coref | ✅ × M4 邊界 |
| 事件層空殼、關係 8% 匯入率 | | ✅ | ✅ × M3（RE 只看 Pericope）|
| description 片段、噪音實體 | | ✅ | |

**精確結論**：chunking 的「參數」大致無罪；chunking 的「粒度結構被下游三層直接繼承」有大罪。

---

## 3. 優化路線圖

### P0 — 資料修補，不重抽（天級，先做）

| 項目 | 做法 | 預期效益 |
|---|---|---|
| verse mention 回填 | 匯入時 strip `:v:N` 還原 pericope id | **+5,853 對錨點、1,310 實體活化**（零成本，100% 可解析已精算）|
| 修靜默丟棄 | MATCH 落空要 log、計數器誠實 | 杜絕「173,896 imported」假象 |
| aliases 字典直灌 | `entity_dicts.py` 126+84+61 條寫回圖譜（**注意寫原生 LIST**，避開 json.dumps 陷阱）| R3-R6 同義詞 fallback 生效 |
| 噪音 gate | 「但」語境過濾、泛名詞 stoplist（日子/兒子/時候）、耶和華型別修正、標題預設 EVENT 規則收緊 | 消除 deg 685/2,455 級污染源 |
| 未分類關係搶救 | 77,953 條中 Event 相關 10,647 條先重分類匯入 | 直接補事件層參與者/地點 |
| TSK 串珠匯入 | scrollmapper/bible_databases | 916 → 34 萬候選 |

### P1 — 管線修復後重抽（週級，根治 M1–M6）

1. **抽取輸入與 embedding 佇列解耦**：抽取一律用 pericope 全文（169 個長 pericope 也塞得下），mention 用 `start_pos` 映射回 chunk — 儲存/檢索單位與抽取單位分離（Neo4j Builder 模式）。
2. **coref pass**：pericope 全文為作用域 + 章級上下文，LINK-KG 三階段配方（type-specific prompt cache）；文獻預期 node dup −28%~−45%。
3. **gleanings 多輪補抽**：GraphRAG 機制（logit_bias=100 強制 Y/N「是否漏抽」+「MANY entities were missed」續抽），`max_gleanings=1` 即有效；**照抄 nano-graphrag 的真迴圈實作**（現行 LightRAG main 已退化成單次 gated pass）。
4. **post-hoc entity resolution**：抄 Neo4j Builder 雙訊號配方 — 同 type 才比，`Levenshtein<3 OR substring OR cosine>0.9~0.97` 判同一實體；**merge 時把被併掉的 surface form 寫進 aliases**（一次解決 aliases 空 + 字典↔圖譜命名不一致）；**entity_type 用 LightRAG 多數決**（治約櫃四型別分裂）；「只提議、人工確認再 merge」避免誤併聖經人物；同步處理 pinyin 同音碰撞（id 加型別+消歧尾碼）。搭配 STEPBible TIPNR / ACAI 別名資源對齊。
5. **description 重生成**：LightRAG 配方 — 合併時 descriptions 串接、累積 ≥8 段或 >1200 tok 才 LLM summarize → 連帶修 entity_query 向量品質（reranker 擠出 EQ 的上游）。
6. **抽取模型升級**：STOPWORDS 重審（神/靈/主 不該全濾）+ RE `max_pairs_per_pericope=80` 截斷放寬（pair_miner.py:149）。

### P2 — 事件層（週–月級）

- ATOM 的 atomic facts + dual-time 建模、E²RAG 的 entity 子圖 + event 子圖雙圖範式；時序因果邊從 45 條做到千級。
- RE pair mining 解除 Pericope-only 限制（M3 修復後自動受益）。

### P3 — 階層與檢索融合（月級）

- **Leiden 社群摘要**（GraphRAG global search）或 **RAPTOR collapsed tree**（2000 token 預算攤平選節點，QuALITY +20%）：補主題級錨點，治 EVENT_011 型彙總題（recall@k=1.0 但 coverage=0）與 reranker 字面匹配壓過 entity 錨點的瓶頸。
- RAKG 式 pre-entity 回檢補全跨 chunk 上下文。
- 圖/向量分數校準融合（PhaseGraph PIT）。

### 驗收方式

- 每步用 BRINK 式「缺陷 → 答案品質」量測；A/B 評估注意 Unbiased GraphRAG eval 的警告（position bias 可造 >30%、length bias >50% 勝率差；呼應本專案已知的 RAGAS noncommittal 假象）。
- 建置期 KG 品質 CI 三指標：**anchor coverage**（實體有 Pericope 錨點比例）、**duplicate rate**（同名跨型別節點數）、**alias coverage**。
- Eval 盯 PERSON（目前唯一輸 semantic 的題型）與 EVENT ctx_recall 是否回升。

---

## 4. GraphRAG 家族系統工程參考（全部讀原始碼/官方文件驗證）

| 系統 | 抽取單位 | Overlap | 多輪補抽 | Entity dedup / resolution | 備註 |
|---|---|---|---|---|---|
| MS GraphRAG | token chunk **1200**（論文實驗 600）| 100 | gleanings max=1（logit_bias=100 + "MANY missed"）| **exact (title,type)** 分組 → desc 交 LLM summarize；關係重複 → edge weight | 600 vs 2400 → **≈2× 實體引用**；Leiden max_cluster_size=10 |
| LightRAG | token chunk 1200 | 100 | gleaning max=1（單次 gated，非迴圈）| **同名 merge**；type 多數決；desc ≥8 段才 summarize；weight 相加 | `FORCE_LLM_SUMMARY_ON_MERGE=8` |
| nano-graphrag | token chunk 1200 | 100 | gleaning=1（**真迴圈**，照抄首選）| 同名 merge + Leiden community | insert 會重算 community |
| fast-graphrag | token chunk **800**（char 切）| 100 | **0（關閉）** | **大寫正規化 name 當 key**；edge 用 LLM 語意合併；desc>512 chars 才 summarize | 檢索用 Personalized PageRank |
| Neo4j LLM KG Builder | token chunk **100** | 20 | 無（`chunks_to_combine` 抽取前合併相鄰 chunk）| post-hoc ER：同 label + `cosine>0.97 OR Levenshtein<3 OR substring`，**只提議、人工觸發 merge** | 儲存單位≠抽取單位；Leiden 3 層 |
| LazyGraphRAG | **名詞片語 concept**（index 無 LLM）| — | 無（延到 query）| 共現圖，query 時 resolve | index 成本 = vector RAG = GraphRAG 的 **0.1%** |
| KAG | **semantic chunk**（prompt 驅動）| — | schema-constrained IE | synonym 集預測 → fuse；concept linking | `supporting_chunks` 實體↔chunk 雙向索引 |
| iText2KG | semantic blocks | — | 逐 block 增量 | **embedding cosine**：paper 0.7 / code `ent_threshold=0.8`（name_weight 0.8）| 增量式，無需 ontology |
| RAPTOR | 句完整 leaf **100 tok** | — | 遞迴 cluster+summarize | UMAP + GMM soft cluster（均 6.7 節點/群）| **collapsed tree @2000 tok 最佳**，QuALITY +20% |

**跨系統規律**：
(a) index 期一律 exact-name 分組，近似 ER 全放 post-hoc/增量，清一色「字面距離 + embedding 相似度」雙訊號；
(b) merge 時把被併 surface form 寫入 aliases = aliases 的正確生成機制；
(c) 多輪 gleaning 僅 GraphRAG 系有，成本敏感者（LazyGraphRAG / fast-graphrag）不 glean；
(d) **主流用單一統一抽取粒度** — 本專案三粒度並存且無 resolution 縫合，是碎裂主因。

---

## 5. 論文清單（全部經原始頁面驗證）

### A. 粒度 ↔ 抽取品質（支撐第 2 節因果鏈）

| 論文 | 出處 | 已驗證量化發現 | 對映本專案 |
|---|---|---|---|
| **From Local to Global: A GraphRAG Approach to Query-Focused Summarization** | arXiv:2404.16130（Microsoft, 2024）| "GPT-4 extracted **almost twice as many entity references** when the chunk size was 600 tokens than when it was 2400"（逐字）；gleanings = logit_bias 100 強制 Y/N + "MANY entities were missed" 續抽；論文實驗 600/100，軟體預設 1200/100 | 粒度→抽取密度的最直接證據；M5 混粒度重複/漏抽 |
| **DocRED: A Large-Scale Document-Level Relation Extraction Dataset** | ACL 2019, arXiv:1906.06127 | "at least **40.7%** relational facts can only be extracted from multiple sentences"；61.1% 需推理（**coreference 17.6%** / logical 26.6% / common-sense 16.6%）| 切碎 + 無 coref 的結構性上限；「岳父/他」kinship 遺漏的權威數字 |
| **CrossAug: Beyond Chunk-Local Extraction** | arXiv:2605.28004（2026-05）| 點名「chunk-local extraction 使跨 chunk 關係系統性缺失」；GNN 引導找缺失子圖 + 選擇性 LLM 補全，3 框架 × 4 benchmark 一致提升 | M3/M4 跨段關係缺失的補救範式 |
| **Lost in the Middle: How Language Models Use Long Contexts** | TACL 2023, arXiv:2307.03172 | GPT-3.5 相關資訊在開頭 75.8% → 中段 ~53.8%（**>20pt 落差**），最差低於 closed-book 56.1% | 整卷丟入抽取的上界警告；本專案 max 3,544 字遠低於退化區間 |
| **ATOM: AdapTive and OptiMized dynamic Temporal KG Construction** | arXiv:2510.22590, EACL 2026 Findings | atomic facts + dual-time（observation/validity）→ fact coverage **+18%**、跨次一致性 **+33%**、latency −90% | 粒度分解證明比大 chunk 抽得更全 + 事件時間層建模範本 |

### B. Coreference / Entity Resolution（去重證據鏈）

| 論文 | 出處 | 已驗證量化發現 | 對映本專案 |
|---|---|---|---|
| **CORE-KG: An LLM-Driven KG Construction Framework** | arXiv:2506.21607（2025）| type-aware coref + 結構化提示 → node duplication **−33.28%**、noise **−38.37%** vs GraphRAG baseline | 「多種指稱 → 單一 canonical node」正是字面錨定做不到的 |
| **Inside CORE-KG**（ablation 續作）| arXiv:2510.26512 | **單移 coref → dup +28.25%**、noise +4.32%；移結構化提示 → dup 僅 +4.29% 但 noise +73.33% | 乾淨 ablation：**coref 主導去重、prompt 主導去噪** |
| **LINK-KG: LLM-Driven Coreference-Resolved KGs** | arXiv:2510.26486（2025）| 三階段 LLM coref + type-specific prompt cache → dup **−45.21%**、noisy **−32.22%**；**效益隨文件變長放大**（長文 dup 36.01%→17.78%）| 越長的 pericope（被切塊者）越需要 coref；方法可移植 |
| **Better Later Than Sooner: Ontology-grounded Post-extraction Correction** | arXiv:2605.29168（2026-05）| open extraction → embedding canonicalization → ontology 違規靶向 LLM 修正；「延後修正」比抽取時驗證省 token | 對治 noisy entities + 空 aliases 的事後修正路線，比重抽便宜 |
| **LLM-empowered KG Construction: A Survey** | arXiv:2510.20345（2025）| schema-based vs schema-free 兩範式；knowledge fusion（entity alignment/去重/衝突解消）章節 | related work 傘狀引用 |

### C. 事件層 / 架構範式

| 論文 | 出處 | 已驗證量化發現 | 對映本專案 |
|---|---|---|---|
| **E²RAG（ChronoQA）: Entity-Event KGs for RAG** | arXiv:2506.05939（2025）| dual-graph（entity 子圖 + event 子圖，bipartite 相連）；點名「傳統 KG-RAG 把同一 entity 所有 mention 塌縮成單一節點，喪失演變脈絡」 | 敘事文本的 entity+event 雙層建模範式，對照空事件層 |
| **RAKG: Document-level Retrieval Augmented KG Construction** | arXiv:2504.09823（2025）| pre-entity 當 query 回檢跨 chunk 上下文，MINE **95.91% vs GraphRAG 89.71%**；明言「降低 coref 複雜度」 | 架構層面繞開跨 chunk coref 遺失的改造方向 |
| **TCR-QF: Triple Context Restoration and Query-driven Feedback** | arXiv:2501.15378（2025）| text→triples 剝離上下文 → "incomplete and isolated triples"；triple 回指原文修復（內文精確數字未逐字取得，主張已驗證）| 對應「mention 靜默丟棄/三元組脫離原文」；保留 triple↔pericope 回指 |
| **DyG-RAG: Dynamic Graph RAG**（前輪已驗證）| arXiv:2507.13396 | dynamic event units + 時序遊走 | 事件時序層參考（GitHub RingBDStack）|

### D. 評估方法論

| 論文 | 出處 | 已驗證量化發現 | 對映本專案 |
|---|---|---|---|
| **BRINK: What Breaks Knowledge Graph-based RAG?** | arXiv:2508.08344（2025）| KG 不完整時 6 個 KG-RAG 方法全數明顯下滑；揭露「靠內部記憶而非結構推理」 | 「缺邊 → 答案退化」的 benchmark 化，驗收方法可借鏡 |
| **How Significant Are the Real Performance Gains? Unbiased GraphRAG Eval** | arXiv:2506.06331（2025）| 去偏後 **LightRAG 勝率 66.70% → 39.06%（−27.64pt）**；position bias 單獨 >30%、length bias（差 25 token）>50% 勝率差 | LLM-judge A/B 的去偏方法論；呼應 RAGAS noncommittal 假象 |
| GraphRAG-Bench: When to use Graphs in RAG | arXiv:2506.05690（2025，marginal）| 「GraphRAG 效益視任務型態」 | context 引用 |
| Systematic Investigation of Document Chunking & Embedding Sensitivity | arXiv:2603.06976（2026-03，marginal）| paragraph-group chunking nDCG@5≈0.459 vs fixed-size <0.244（近 2×）| **僅 retrieval 下游**，粒度證據可引不宜當主力 |

### E. 前輪 roadmap 已驗證論文（2026-07-05 第一輪體檢）

- **EDC: Extract-Define-Canonicalize** — arXiv:2404.03868（GitHub clear-nus/edc）：開放抽取後 canonicalize 範式
- **DEG-RAG** — arXiv:2510.14271：entity resolution 使 KG 縮 40% 反升下游效果
- **HippoRAG2** — arXiv:2502.14802（ICML 2025）：PPR 檢索 + passage 節點
- **PhaseGraph** — arXiv:2603.28886：圖/向量分數 PIT 校準融合
- **ArchRAG** — arXiv:2502.09891：屬性社群 + 階層檢索

### F. 領域資料資源（前輪已驗證授權）

| 資源 | 授權 | 用途 |
|---|---|---|
| STEPBible TIPNR | CC BY 4.0 | 人名 + 親屬關係 + 所有經文參照（aliases/實體消解 ground truth）|
| ACAI / BibleAquifer | CC BY-SA | `referred_to_as` 別名結構 |
| MACULA | CC BY 4.0 | 原文級 participant referents（可當 coref ground truth）|
| Treasury of Scripture Knowledge（scrollmapper/bible_databases）| public domain | 34 萬條串珠 |

### G. ⚠️ 查證過不可引用的說法

1. **「GraphRAG 官方文件描述 gleanings」** — 官方 `default_dataflow` 文件頁只寫單輪抽取；gleanings 正確出處是論文 arXiv:2404.16130，勿引文件頁。
2. **「2412.07189 做了 500/1000/1500/2000 token chunk 消融」** — 實抓 PDF 無此實驗，判為搜尋引擎合成幻覺；「chunk 越小抽越多實體」一律引 GraphRAG 論文（600 vs 2400）。
3. **Overlap 大小對抽取影響的量化數字** — 僅部落格/文件層級經驗值，**無同行評審論文**；需論證「1 節 overlap 太小」時，改引 DocRED 40.7% 跨句作間接證據。
4. **「Semantic chunking 值得/不值得」**（arXiv:2410.13070：不值得）— 該文僅測 **retrieval** 下游，不可推到 extraction/KG 建構；且本專案 pericope 切分屬「結構感知」，非其批判的純語義相似度切分。

### 給論文的最強引用鏈

**GraphRAG（600 vs 2400 → 2× 實體）+ DocRED（40.7% 跨句 / 17.6% 需共指）+ CORE-KG 系列（coref 去重 −28%~−45%，長文放大）**，配本專案實測（56% mention 丟棄 / +5,853 回填 / 1,310 實體活化 / PERSON 題型 graph 唯一輸）— 「粒度錯配傷 KG」從文獻到本地數據閉環。

---

## 附錄：驗證方法與資料來源

- **Neo4j live 查詢**：實體/型別統計、aliases valueType 檢查（9,122 全原生 LIST）、MENTIONS 來源分布、零錨點/chunk-only 統計、事件層完整度、重名分裂、關係型別計數
- **檔案精算**：`output/entity_mentions.jsonl`（173,896 條逐條分類 + 回填模擬）、`embedding_queue.jsonl`（34,072 組成）、`relations_unclassified.jsonl`（77,953 型別配對）、`pericopes.jsonl` / `chunks.jsonl`（長度分布）
- **程式碼逐行驗證**（file:line 均為實際行號）：`bible_chunking/`（config.py / hierarchical_chunker.py / tokenizer_wrapper.py / markdown_parser.py / models.py）、`scripts/`（process_bible.py / extract_entities.py / ner_extractor.py / llm_extractor.py / pos_extractor.py / pericope_miner.py / entity_normalizer.py / entity_dict.py / import_neo4j.py / embed_entities.py / relation_extraction/*）、`backend/utils/retrieval/entity_path_retriever.py`
- **評估數據**：`evaluation/results_graph_claude_answer/evaluation_results.json` vs `results_semantic_claude_answer/`（100 題，overall + by_type）
- **論文驗證**：每篇經 WebFetch 抓取 arXiv abstract / ar5iv HTML / ACL Anthology / 官方 GitHub repo 原始碼 / 官方 blog 確認存在性與引用數字；GraphRAG 論文 PDF 下載後 pdftotext 逐字比對
