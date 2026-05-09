# 📚 論文 vs Bible_RAG 知識圖譜建構比對報告

> - **論文**：Peng et al., *Graph Retrieval-Augmented Generation: A Survey*, ACM Trans. Inf. Syst. 44(2), Article 35 (2026)
> - **對照**：Bible_RAG 現行 KG（Neo4j 即時查詢驗證,2026-05-09)

---

## 一句話定位

論文把 KG 建構分成 4 種策略;Bible_RAG 採用的是「**Heterogeneous Graph 外殼 + 退化版 KG(NER-only,沒做 RE) + 領域特化 Document Graph 邊**」的混合做法。

結構工程紮實,但 KG「關係事實」這層幾乎沒做 — 整個圖譜本質上是「**實體出現索引 + 階層導航 + 跨段落引用**」三合一,不是論文意義上的「事實知識圖譜」。

---

## 第一部分:論文是怎麼建知識圖譜的

論文 Section 5「G-Indexing」是 KG 建構的權威章節。核心內容如下。

### 1.1 兩大資料來源(Section 5.1)

```
                    ┌─────────────────────────────────────┐
                    │  Self-Constructed Graph Data        │
                    │  ──────────────────────────────     │
                    │  從原始文本/表格/網頁構建            │
   Graph Data ─────►│  常用於專有/領域知識                 │
                    └─────────────────────────────────────┘
                    ┌─────────────────────────────────────┐
                    │  Open KGs                           │
                    │  ──────────────────────────────     │
                    │  General KG  : Wikidata, Freebase,  │
                    │                DBpedia, YAGO,       │
                    │                ConceptNet, ATOMIC   │
                    │  Domain KG   : CMeKG, CPubMed-KG,   │
                    │                Wiki-Movies          │
                    └─────────────────────────────────────┘
```

### 1.2 四種圖譜建構策略(Table 2,論文 p.12)

| 圖譜類型 | 節點 | 邊 | 關鍵技術 | 代表系統 |
|---|---|---|---|---|
| **Tree Structures** | 葉=文本塊;內節點=語意摘要 | 階層關係 | text chunk embedding + recursive clustering + LLM summary | RAPTOR, SiReRAG |
| **Document Graphs** | 文檔/段落 | 文檔間相似性、共享 metadata(keywords/citations) | 規則式(similarity/metadata)或 GNN | ATLANTIC, KGP, GNN-Net, R⁴ |
| **KGs** | 實體 | 關係事實(subject-predicate-object 三元組) | NER + RE + textual enrichment + community detection | DALK, HippoRAG, REANO, LightRAG, TCR-QF, TEMPLE-MQA, Microsoft GraphRAG |
| **Heterogeneous Graphs** | 多型節點(entities/documents/summaries) | 多型邊 | 定義 meta-schema + 規則或學習填邊 | GRAFT-Net, NodeRAG, KG-Retriever, Ra-Sim, HippoRAG2 |

### 1.3 KG 構建的標準流程(論文 p.13 重點段落原文)

> "KGs represent entities as nodes and relationships as edges, forming a semantic network that structures factual knowledge extracted from text. Typical construction begins with Named Entity Recognition (NER) and Relation Extraction (RE) models to extract triples from unstructured text. An important extension is the textual KG, where nodes and edges are enriched with additional textual information."

可拆解為三個層次:

1. **基礎**:NER + RE → `(head, relation, tail)` 三元組
2. **進階(Textual KG)**:在實體/關係上掛 description / attributes(LightRAG, HippoRAG)
3. **頂層(Microsoft GraphRAG)**:text clustering + LLM summarization → community-level structured global summaries(解決 QFS 問題)

### 1.4 三種索引方式(Section 5.2)

| 索引類型 | 做法 | 優勢 | 代表 |
|---|---|---|---|
| **Graph Indexing** | 保留圖結構,BFS/DFS traversal | 鄰居查詢便捷、保留階層 | RAPTOR, SiReRAG, KG-Retriever |
| **Text Indexing** | 把圖數據轉成自然語言(template per triple, 或 community summary)→ 進文本檢索器 | 可用 BM25 / sparse retrieval | Li et al., Edge et al. |
| **Vector Indexing** | 節點/邊向量化,Entity Linking + LSH | 模糊語意匹配 | G-Retriever, GRAG, SEPTA |
| **Hybrid** | 三者混用 | 互補;NodeRAG 是經典 | HybridRAG, EWEK-QA, NodeRAG |

論文特別警告:Vector Indexing 有 **text embedding collapse** 風險(長描述向量化時語意塌縮),需謹慎處理。

---

## 第二部分:Bible_RAG 是怎麼建知識圖譜的

從 `scripts/process_bible.py`、`scripts/extract_entities.py`、`scripts/import_neo4j.py`、`bible_chunking/` 模組與 Neo4j 即時 schema 反推。

### 2.1 三階段管線

```
┌───────────────┐     ┌────────────────┐     ┌──────────────┐
│ Stage 1       │     │ Stage 2        │     │ Stage 3      │
│ 解析與分塊    │ ──► │ 實體抽取       │ ──► │ 匯入 Neo4j   │
│ process_bible │     │ extract_entities│     │ import_neo4j │
└───────────────┘     └────────────────┘     └──────────────┘
```

### 2.2 Stage 1 — Bible 階層解析(`process_bible.py`,567 行)

- 解析 66 卷 markdown → 4 層階層 **Book / Chapter / Pericope / Chunk**
- BGE-M3 token 計數;token > 768 才切塊(沿 verse 邊界,target=512,overlap=1 verse)
- `CrossRefParser`:用正則解析 H3 標題的 `(可1‧9-11;路3‧21-22)` 格式
- `CROSS_REFERENCES` 雙來源:markdown 標註(774 條)+ supplementary NT→OT 人工清單(142 條)
- 用 `verse_lookup` 把章節級引用解析到 pericope 層級

### 2.3 Stage 2 — Grounded 4-Phase Pipeline(`extract_entities.py`,468 行)

| 階段 | 動作 |
|---|---|
| **Phase 1** Pericope Title Mining | 從 H3 標題挖 Event/Theme 候選 |
| **Phase 2** CKIP POS Tagging | 中文詞性標注,抽 freq ≥ min_freq 的名詞 |
| **Phase 3** Rule-based Classification | 字典/規則分類為 Event/Object/Theme |
| **Phase 4** LLM-as-Classifier | 對未分類者,限 LLM 在候選池內分類(grounding 防 hallucination) |

獨立 NER:CKIP NER + `entity_dict.py` 字典查詢 → Person/Place/Group

> **LLM 角色:Classifier,不是 Extractor**。這是與論文典型做法最大的方法論差異。

### 2.4 Stage 3 — Neo4j 匯入(`import_neo4j.py`,429 行)

10 個唯一性約束、MERGE 冪等、批次(節點 500 / 關係 1000 / MENTIONS 2000)。

### 2.5 實際 KG Schema(MCP 即時查詢)

**節點(23,490 總計,含雙標籤)**:

```
Bible 階層 (4,465):Book 66 / Chapter 1,189 / Pericope 2,779 / Chunk 431
Entity (9,120)    :Person 2,418 / Object 2,200 / Event 1,710 /
                    Place 1,299 / Theme 987 / Group 506
```

**關係(49,389 總計)**:

```
MENTIONS         41,034   Pericope/Chunk → Entity
CONTAINS          4,399   Book→Chapter→Pericope→Chunk
NEXT              2,975   章內順序
CROSS_REFERENCES    916   Pericope → Pericope(96.1% 跨書卷)
NEXT_BOOK            65   Book→Book
─────────────────────────────────────────────────
Entity → Entity       0   ← 完全沒有實體間關係
```

### 2.6 與論文對照後的圖譜本質

Bible_RAG 並不是單一論文類型,而是 **三種類型的混合**:

| 圖譜層次 | 對應論文類型 | 實作 |
|---|---|---|
| Bible 階層 | Tree Structures(但無 LLM 摘要節點,只是結構容器) | Book/Chapter/Pericope/Chunk + CONTAINS/NEXT |
| 跨段落網絡 | Document Graphs(但是手工/人工標註,不是相似度自動算) | CROSS_REFERENCES |
| 實體網絡 | KGs 退化版(只做 NER,沒做 RE) | Pericope-MENTIONS→Entity,無 Entity↔Entity |
| 整體 | Heterogeneous Graphs | 多型節點(Bible/Entity)+ 多型邊(5 種) |

---

## 第三部分:核心差異比對表 + 缺口分析

### 3.1 關鍵差異一覽

| 維度 | 論文典型做法 | Bible_RAG 現況 | 落差 |
|---|---|---|---|
| 資料來源 | Open KG ⊕ Self-Constructed | 100% Self-Constructed | 沒整合 Wikidata 等開放 KG |
| NER | NER 模型抽 mention | CKIP NER + 字典 + 4-phase pipeline | ✓ 比論文嚴謹 |
| RE(關係抽取) | RE 模型抽 (s, p, o) 三元組 | 完全沒做 | 🔴 **最大缺口** |
| Entity 屬性 | LLM 生成豐富 description | description 多為空、aliases 是 JSON 字串 | 🟡 Textual KG 強度不足 |
| 三元組 | 是 KG 的核心;用於多跳推理 | 0 條 | 🔴 多跳推理能力受限 |
| 全局摘要 | community detection + LLM summary(GraphRAG) | 無;title 充當粗摘要 | 🟡 QFS 能力受限 |
| 跨文件邊 | citation/similarity 自動計算 | 領域語意手工 + markdown | ✅ 領域差異化資產 |
| 階層粒度 | 通常單層或 RAPTOR 樹 | 4 層硬階層 | ✅ 對 Bible 領域更合語意 |
| LLM 角色 | Extractor + Summarizer + Linker | Classifier-only(grounded) | 保守,避免幻覺,但失去抽 triples 的能力 |
| Graph Indexing | BFS/DFS、鄰居遍歷 | ✓ Neo4j 原生支援 | OK |
| Text Indexing | 圖→自然語言模板 → BM25 | 在 PostgreSQL FTS,但與 Neo4j 分離 | 🟡 沒整合 |
| Vector Indexing | 實體嵌入 + Entity Linking + LSH | Entity 沒有向量 | 🔴 模糊查實體會失敗 |
| 檢索範式 | Once / Iterative / Multi-Stage | Once + 1-hop expand only | 🟡 沒走 CROSS_REFERENCES! |
| 冪等 / 批次 | 一般沒提;通常重建 | MERGE + batch | ✅ 工程實踐優於論文 |

### 3.2 五大關鍵缺口(依嚴重性排序)

#### 🔴 缺口 1 — 沒有實體間關係(無 Relation Extraction)

- **現況**:Entity↔Entity 邊 = 0
- **論文要求**:典型 KG 必須有 `(subject, predicate, object)` 三元組
- **影響**:「亞伯拉罕生以撒」、「保羅去大馬色」這類事實級多跳推理走不通
- 與上次 session 的失敗案例直接相關:找到單一實體後沒有 entity-path 可走

#### 🔴 缺口 2 — Entity 沒有向量索引

- **現況**:Qdrant 中只有 pericope/chunk/verse 的向量;Entity 節點完全沒嵌入
- **論文要求**:Section 5.2.3「Entity Linking + 向量化」是 Vector Indexing 的核心
- **影響**:查「亞伯拉罕的兒子」時,無法從查詢嵌入直接命中 Isaac entity,必須先做精確 name match

#### 🟡 缺口 3 — 沒有全局摘要 / Community Detection

- **現況**:圖譜上沒有任何 LLM 生成的摘要節點
- **論文要求**:Microsoft GraphRAG 用 community detection + LLM summary 解決 QFS(Query-Focused Summarization)
- **影響**:問「整本約翰福音講什麼」、「保羅書信的核心神學」這類全局型問題很難回答

#### 🟡 缺口 4 — Entity 描述貧乏

- **現況**:`description` 欄位多為空;`canonical_name` + `aliases` 但無百科級資訊
- **論文要求**:LightRAG / HippoRAG 用 LLM 生成豐富的 entity description
- **影響**:返回實體時可解釋性弱;無法支援 entity-only 的回答

#### 🟡 缺口 5 — Retriever 沒走 CROSS_REFERENCES

- **現況**:`graph_retriever.py` 三個函式都只走 1-hop MENTIONS
- **論文要求**:Section 6.3.3 Path / 6.3.4 Subgraphs granularity
- **影響**:花了人力標註的 916 條跨書卷邊,在預設檢索路徑上完全沒被利用

### 3.3 Bible_RAG 比論文做得更好的地方

公平地講,Bible_RAG 有幾項是論文 SOTA 沒提到的優勢:

1. **結構元數據驅動的種子集**:H3 段落標題 + markdown 引用括號,等於免費的人工標註,論文中許多 self-constructed KG 都是從零開始抽取,沒有這種預先結構。
2. **聖經學共識性引用(CROSS_REFERENCES + supplementary)**:是領域專家知識,遠勝 ATLANTIC 那種「文獻引用」的 Document Graph 邊。
3. **Pericope 作為核心單位**:對齊聖經學的詮釋傳統,比論文常用的固定大小 chunking 更合語意。
4. **MERGE 冪等 + 批次匯入**:工程穩健性勝過論文(論文重點在演算法,不在工程)。
5. **Grounded LLM Classifier**:用 LLM 但限制在候選池內,幾乎完全消除幻覺風險,這對權威語料(聖經)特別重要 — 論文中 LightRAG/HippoRAG 用 LLM 抽 triples 的做法在嚴謹語料上反而是劣勢。

---

## 改進建議(對應論文方法的具體升級路徑)

如果要把 Bible_RAG 推向論文意義上的「真正 KG」,按優先順序:

| 優先級 | 動作 | 對應論文方法 | 預期效益 |
|---|---|---|---|
| **P1** | 補 Entity↔Entity 邊:用 LLM 對「同一段落內 Person×Person、Person×Place」抽聖經學關係(FATHER_OF, WIFE_OF, RULED, BORN_IN, RECEIVED_FROM…) | LightRAG / HippoRAG 的 RE 流程 + 領域 schema | 開啟多跳推理 |
| **P1** | Retriever 加上 2-hop expansion 走 CROSS_REFERENCES | Section 6.3.3 Path granularity | 直接修復目前 graph 路由失敗案例 |
| **P2** | Entity 嵌入到 Qdrant(用 canonical_name + aliases + description) | Section 5.2.3 Vector Indexing + EL | 模糊實體查詢 |
| **P2** | 用 LLM 補 Entity description(離線批次,grounded 在該實體所有 mentions 上) | Textual KG enrichment | 提升可解釋性 + Vector Index 質量 |
| **P3** | 在 Book / Chapter 層加 LLM 摘要節點(offline,每章一段 ~300 tokens) | Microsoft GraphRAG community summary | QFS 能力 |
| **P3** | 引入 Wikidata 作為輔助 Open KG(Q9077 Abraham, Q43964 Jesus 等) | Section 5.1.1 Open KG hybrid | 補出生年代、家族樹等結構屬性 |

---

## 總結

論文把 KG 建構視為一條從 **NER+RE 開始、向 textual enrichment 與 community summary 逐步豐富** 的路徑;Bible_RAG 走的是從 **結構化 markdown 開始、靠手工標註與字典完成最關鍵 80%、再以 grounded LLM 補餘下 20%** 的反向路徑。

兩者哲學不同:

- **論文** 押注 LLM 能力,相信能從文字中抽出豐富結構(成本高、可能幻覺)
- **Bible_RAG** 押注領域結構(markdown + 字典 + 神學專家),LLM 只當分類器(成本低、零幻覺)

對「繁體中文 + 權威封閉語料 + 高可信度要求」的聖經應用,Bible_RAG 的選擇在抽取階段是合理的,但**沒做 RE 的代價是檢索階段被綁死在 1-hop**,這是目前 graph 路由失敗案例的結構性根因。

下一步如果要動手修復 graph 路由失敗案例,**最低成本切入點是 P1 的第二項:讓 retriever 走 CROSS_REFERENCES**(不需要重建 KG,只改 Cypher 與 retriever 邏輯,直接打開 916 條既有邊的價值)。

- 比對報告已完成。要點：論文走「NER+RE+LLM enrichment+community summary」豐富路徑；Bible_RAG 走「結構化 markdown+字典+grounded LLM classifier」保守路徑。最大缺口是沒做 Relation Extraction（Entity↔Entity 邊 = 0），其次是沒走 CROSS_REFERENCES 的檢索（916 條邊閒置）。後者是修復 graph 失敗案例的最低成本切入點。

※ recap: 最大缺口是沒做 Relation Extraction，且既有 916 條 CROSS_REFERENCES 邊在檢索時未被利用。下一步可改 graph_retriever.py 走 2-hop CROSS_REFERENCES。 (disable recaps in /config)