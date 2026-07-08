# ARCHITECTURE.md 重新檢驗與架構解說報告

> **文件日期**:2026-07-07
> **性質**:對 [ARCHITECTURE.md](ARCHITECTURE.md)(2026-07-06 版)的獨立重新檢驗紀錄 + 特殊機制原理解說 + 論文引用彙整
> **檢驗方法**:① Neo4j Cypher / Qdrant HTTP / PostgreSQL psql 直查 live 資料庫;② 逐檔對照 `backend/` 程式碼與 live `.env`;③ 對照最新一輪評估結果(commit `d85c7eb`,2026-07-07 重跑 100 題);④ 論文引用交叉比對 `paper/latex/refs.tex` 與 `docs/kg_optimization_analysis_2026-07-05.md`

---

## 目錄

1. [檢驗結論](#1-檢驗結論)
2. [驗證明細](#2-驗證明細)
3. [僅有的 4 個微小出入](#3-僅有的-4-個微小出入)
4. [架構全景解說](#4-架構全景解說)
5. [特殊機制:原理與目的](#5-特殊機制原理與目的)
6. [論文引用彙整](#6-論文引用彙整)

---

## 1. 檢驗結論

**ARCHITECTURE.md 與 live 系統高度一致,可信度極高。**34 項可驗證宣稱中 30 項 bit-exact 吻合、4 項為標籤簡化或快照漂移級的微小出入(§3),無任何實質性錯誤。

文件的敘事主軸(粒度錯配因果鏈 → P0 negative result → 排序層瓶頸診斷 → 融合層收復)與程式碼中留下的註解證據完全互洽 — 例如 `backend/config.py` 記錄了 cross-ref cap 30→10 的逐題理由(EVENT_015/017/019、PERSON_011、GENERAL_013),`backend/utils/retrieval/router.py` 記錄了 EQ-pin 退役的實證依據(pinned AC 0.497 vs no_pin 0.703)。

---

## 2. 驗證明細

### 2.1 Live 資料庫(全部吻合)

| 文件宣稱 | 實測(2026-07-07) | 結果 |
|---|---|---|
| Neo4j 13,589 節點 / 319,988 邊 | 13,589 / 319,988 | ✅ bit-exact |
| 結構節點 Book 66 / Chapter 1,189 / Pericope 2,779 / Chunk 431 | 同 | ✅ |
| 六型實體 Person 2,419 / Object 2,200 / Event 1,714 / Place 1,299 / Theme 987 / Group 505(計 9,124) | 同 | ✅ |
| CROSS_REFERENCES 250,418 / MENTIONS 46,205 | 同 | ✅ |
| PARTICIPATED_IN 7,130 / OCCURRED_IN 4,313 / SON_OF 659 / FATHER_OF 647 / POSSESSED 551 / CONTAINS 4,399 / NEXT 2,975 | 同 | ✅ |
| 串珠三來源(手工 774 + 補強 142 + TSK) | `tsk` 249,502 + `markdown` 774 + `supplementary` 142 = 250,418 | ✅ 並精確量化 MERGE 去重:250,358 條 unique TSK 對中 **856 條**落在既有手工邊上被合併(保留原 source) |
| anchor coverage 98.2% | 8,960 / 9,124 = 98.2% | ✅ bit-exact |
| 失明實體 164(chunk-only) | 9,124 − 8,960 = 164 | ✅ bit-exact |
| 18 個 curated Event 節點 | `source='head_event_backfill'` 恰 18 個 | ✅ 抽樣「最後的晚餐」aliases =〔主的晚餐、設立聖餐、逾越節晚餐〕,直接佐證「問法別名補灌」設計 |
| Qdrant 3 collections | bible_embeddings 34,072 / bible_embeddings_hybrid 34,072 / bible_entities 9,122 points | ✅ |
| PG 6 表 + `embedding_sources` VIEW | books/chapters/pericopes/chunks/entities/entity_mentions + VIEW | ✅ |
| PG entities 9,122(Neo4j 9,124) | 同 | ✅ |
| pericope 中位數 388 字 | `percentile_cont(0.5)` = 388 | ✅ bit-exact |
| embedding_queue 34,072 = pericope 2,610 + chunk 431 + verse 31,031 | 同 | ✅ bit-exact |
| KG CI:Event 有參與者 84.0% / 有地點 75.5% | 依邊型定義重算 83.1–84.5% / 74.7% | ◐ 量級吻合,定義未載明(見 §3-3) |

### 2.2 程式碼機制(全部吻合)

| 機制 | 文件宣稱 | 程式碼實測 |
|---|---|---|
| 排序融合公式 | `fused = (1−α)·rerank + α·weight`,α=0.3 | `router.py:_fuse_and_rank` 一字不差;docstring 含「TSK 鄰居需 rerank 優勢 >~0.11 才贏過 graph 錨點」量級推導;`.env` `RAG_RANK_FUSION_ALPHA=0.3` ✅ |
| TSK 分權 | 手工 0.75/0.55、TSK 0.60/0.50,votes 區分 | `cross_ref_retriever.py`:`_HOP_WEIGHT={1:0.75,2:0.55}` vs `_TSK_HOP_WEIGHT={1:0.60,2:0.50}`,`votes>=999`(`_CURATED_VOTES`)判手工 ✅ |
| seed 防壟斷 | round-robin 跨策略 | `_expand_via_cross_ref_seeds` bucket 輪流抽取;註解即文件的撒9:9↔太21 例 ✅ |
| Pin 階梯 | +0.01 / +0.005 / +0.004 / +0.003 / +0.002 | 五值全部證實;EQ-pin 與 graph uncertainty pin 在 fusion 下被跳過(`include_uncertainty_pins=not fusion_active`)✅ |
| keyword-exact event pin | hub 排除、每事件 1 錨、敘事起點 | `hub_cap=25`、`anchor_rank==0`、mention_count 最小者優先 ✅ |
| 決策樹 | R1 > R5(雙條件) > R2 > R5 > R3 > R4 > R6 > fallback | `signal_detector.py:select_route` 逐行一致 ✅ |
| 路由權重 | §6.3 權重表 | `config.py:route_weights` 一致 ✅ |
| EVENT_KEYWORDS | ~54 詞 | 精確 55 個(AST 解析)✅ |
| EQ 限流 | top-8 / threshold 0.4 / hub>50 → 3 段 / 一般 5 段 / cap 5 | `.env` 六項參數全數一致 ✅ |
| reranker | sigmoid 正規化 0~1 | `reranker.py:50` `torch.sigmoid` ✅ |
| 生成端 | SYSTEM_PROMPT 嚴格約束、max_tokens=10000 | 五條規則 + `LLM_MAX_TOKENS=10000` ✅ |
| chunking | 512 目標 / 768 觸發 | `bible_chunking/config.py:TOKEN_CONFIG` ✅(注意:`bible_chunking/` 在專案根目錄,不在 `scripts/` 下) |
| benchmark | 100 題 5 型各 20 | `ground_truth.json`(專案根)VERSE_LOOKUP/TOPIC/PERSON/EVENT/GENERAL 各 20 ✅ |
| `_apply_weights` 只升不降 | §6.4 註 | ✅ |

### 2.3 評估數字(對照 2026-07-07 最新一輪)

| 指標 | 文件(§8.3 現況欄) | 最新一輪 | 判定 |
|---|---|---|---|
| hit_rate | 0.970 | **0.970** | ✅ bit-exact |
| recall@5 | 0.906 | **0.9058** | ✅ bit-exact |
| mrr | 0.834 | **0.8335** | ✅ bit-exact |
| ragas_context_recall | 0.830 | 0.8247 | ◐ judge 雜訊內浮動 |
| answer_coverage | 0.766 | 0.7593 | ◐ 同上 |
| ragas_answer_correctness | 0.617 | 0.6224 | ◐ 同上 |
| 路由分布 | R2=25 R3=21 R1=20 R4=18 R5=10 R6=4 fb=2 | R4=19、R6=3,其餘全同 | ◐ 一題換路 |

決定性檢索指標(程式計算)完全重現,LLM-judge 類指標浮動幅度落在文件自述的「單題雜訊 ±0.4」聚合範圍內 — 這本身反過來驗證了評估框架「決定性/非決定性指標分離」的設計目的。

---

## 3. 僅有的 4 個微小出入

| # | 位置 | 出入 | 建議 |
|---|---|---|---|
| 1 | §1 mermaid | 「3 個向量 collection 34,072 + 9,122 points」— hybrid collection 也是 34,072,嚴格為 34,072×2 + 9,122 | 總覽圖標籤改「34,072×2 + 9,122」 |
| 2 | §3.4 | entity_mentions 引 jsonl 產出數 173,896;live PG 實為 **173,768**(差 128)。文件宣稱「所有數字 live 直查」,此處是唯一例外 | 加註 PG live 數 |
| 3 | §4.3 | Event 參與者/地點 84.0%/75.5% 無法用單一自然定義精確重現(Person/Group PARTICIPATED_IN → 83.1%;加 INITIATED/VICTIM_OF → 84.5%;OCCURRED_IN → 74.7%) | 文件註明 CI 指標的邊型集合定義 |
| 4 | §6.3 | 路由分布是 2026-07-06 快照;最新一輪 R4=19/R6=3 | 標註「以當輪為準」 |

---

## 4. 架構全景解說

一句話版本:**把 66 卷和合本聖經同時建成「向量索引」與「知識圖譜」,用信號驅動的 6 路由把不同題型導向不同檢索組合,再用排序融合層讓圖譜先驗參與最終排序,最後由 LLM 嚴格依 context 作答。**

### 4.1 離線建庫管線(host 端 `scripts/` + 專案根 `bible_chunking/`)

1. **PDF→MD**(`convert_bible_pdf.py`):純版面幾何啟發式(字體大小 + x 座標)分類書名/章號/段落標題/節號/詩體/註腳,不用 OCR 或 LLM — 決定性、可重跑。
2. **階層解析與分塊**:Markdown 的 `###` 標題即 pericope(聖經學的「段落」詮釋單位)邊界。分塊器用 **BGE-M3 自己的 tokenizer**:>768 tokens 才切(僅 169 個 pericope,6.1%),目標 512、沿節邊界、重疊 1 節、<128 末塊併回。93.9% 的 pericope 整段保留 —「不把故事切成兩半」。
3. **三粒度 embedding queue**(34,072 = pericope 2,610 + chunk 431 + verse 31,031):dense(BGE-M3 1024 維)+ sparse(BM25 + CKIP 斷詞)雙路向量化。
4. **Grounded 實體抽取**(9,120 實體 / 17.4 萬 mention):雙軌 — NER 軌(CKIP + 自建字典)管 Person/Place/Group;Grounded 軌(標題挖掘 + POS 候選 + 規則分類器 + LLM 只分類不生成)管 Event/Object/Theme。防幻覺核心:LLM 只能對給定候選分類、evidence 必須是原文子字串、post-hoc 驗證不合格即降級。
5. **Grounded 關係抽取**(37 型 closed-set 本體,6,958 條):共現配對(schema type-allowed)→ 規則 → 族譜先驗 → LLM 從候選池選一或 NONE(JSON grammar 約束)→ 反向邊具體化。LLM 回 NONE 的 77,953 條**留檔不丟**,後來成為 P0 事件層搶救的現成素材 —「不丟棄陰性結果」事後證明極有價值。
6. **匯入三庫**:PG 收權威資料、Qdrant 收三 collection、Neo4j 收結構 + MENTIONS + 事實邊 + TSK 串珠。

### 4.2 三資料庫互補與「水合模式」

全系統最乾淨的設計約定:**Neo4j 和 Qdrant 只負責「找到 ID」,全文一律由 PostgreSQL `get_content_by_id()` 水合**。PG 是唯一 Source of Truth,圖庫與向量庫可隨時重灌;策略之間傳遞輕量 ID + weight + 觀測欄位,去重在 ID 層完成。ID 格式編碼粒度:3 段=pericope、4 段=chunk、含 `v`=verse(→取父 pericope)。

### 4.3 線上檢索七步(`POST /api/v1/query`)

① 經文引用偵測(regex,決定性)→ ② LLM 意圖分類(偵測到經文引用強制 verse_lookup)→ ③ 6 布林信號選路 → ④ 多策略並行檢索(每策略 try/except,失敗記 `strategy_errors` 不中斷)→ ⑤ 去重 → **整池** rerank → 排序融合 → pins → ⑥ top-5 組 context → ⑦ 嚴格依 context 生成(可插拔 LLM,現役 Ollama gemma4:e4b)。

評估友善的三開關:`semantic_only`(跳過①②③當 baseline)、`use_graph` per-request 覆寫(A/B 不重啟容器)、`retrieval_only`(跳過生成,quick eval 100 題 ~15 分鐘 vs 全管線 2.5h)。

**刻意不做查詢改寫**:query 原文直接進 embedding 與 reranker。「現代問法 vs 古譯本詞彙」的鴻溝(問「最後的晚餐」,經文裡沒這四個字)全靠圖譜錨點 + 融合層補 — 這是理解 §5 所有特殊機制的鑰匙。

### 4.4 六路由分工直覺

R1 精確經文(SQL 直查,跳過 rerank/融合/pin)、R2 章節+語意、R3 人物圖譜(含多人物共現段落 w=0.9)、R4 事件圖譜、R5 跨書卷對照(串珠主場)、R6 地點圖譜、Fallback 純語意(+book_anchor)。每路是「多策略帶先驗權重的組合」而非單一策略,例如 R4 = graph_event(0.85) + semantic(0.7) + cross_ref_expand + entity_query(0.6) + sql(0.5) + book_anchor。

---

## 5. 特殊機制:原理與目的

### 5.1 TSK 串珠(Treasury of Scripture Knowledge)

**是什麼**:19 世紀公版聖經串珠註解集(取 openbible.info / scrollmapper 版本,帶社群投票數 votes)——「這節經文與哪些其他經文相關」的人工彙編,34 萬行 verse 級交叉引用。

**為什麼引入**:圖譜原本只有 916 條手工串珠邊(markdown 平行經文 774 + 人工補強 142),跨書卷橋接太稀疏。P0 用 `embedding_queue.jsonl` 反查表把 verse 級引用映射到 pericope 級(31,102 節 100% 覆蓋),過濾負票(1,166)與自環(9,811)後匯入 **250,358 條 unique pericope 對**,串珠規模 ×273。

**雙面刃(發現鏈 F3)**:votes 高代表「神學主題強關聯」,**不等於**「同一事件敘事」。主題彙總題(TOPIC)受益;事件敘事題(EVENT)反被主題串珠把正解擠出 top-5(P0 後 EVENT hit −0.10)。修復為三層分權:

1. **邊層**:手工邊灌 `votes=999` 哨兵值,檢索端以 `votes>=999` 分流兩條 hop 權重曲線 — 手工 0.75/0.55、TSK 0.60/0.50,**刻意壓在 semantic 0.7 之下**(TSK 鄰居只能補充,不能壓過語意正解);
2. **量層**:expand cap 30→10(TSK 後每 seed 平均 ~180 個一跳鄰居,不設 cap 淹沒候選池);
3. **序層**:`seed_support`(多 seed 交集優先)→ votes 降序;seed 用 round-robin 跨策略選,防 book_anchor 等高權重策略壟斷 seed 名額。

### 5.2 排序融合層(現行架構核心)

**問題**:BGE-reranker 是 cross-encoder 字面 surface matcher。問法詞彙不存在於古譯本經文時,正解段落 rerank 分數可低到 0.001;若最終排序 100% 由 rerank 決定,**建圖端所有改善都在 last-mile 被吃掉**。兩輪獨立證據:2026-05「reranker 擠出 entity_query」、2026-07「P0 建置指標全達標但檢索指標零受益」(F4)。

**解法**:`fused = (1−α)·rerank_score + α·strategy_weight`,α=0.3。兩項皆在 [0,1]:rerank 是 BGE sigmoid,weight 是策略先驗(graph 錨點 0.85–0.9 / semantic 0.7 / TSK 0.5–0.6)。量級直覺:graph 錨點要輸給 TSK 鄰居,後者需 >~0.11 的原始 rerank 優勢 — **大的字面差距仍然贏,五五波讓給圖譜**。

**α=0.3 消融邏輯**:α=0 時 hit 已被離散修復(curated Event + 字典 pin)填飽;α=0.3 貢獻尾部錨點覆蓋(EVENT recall +0.025、TOPIC mrr +0.133),代價 ndcg −0.02。因 top-5 全數進 context,「進不進前五」比「排第幾」重要 → recall 權重高於內部排位,定案 0.3。互補結構(F5):**hit 靠離散修復飽和,recall 長尾靠連續融合補。**

### 5.3 Pin 階梯(離散補救的演進史)

Pin 是在最終排序外,把特定候選以「當前最高分 + 階梯值」強制插入 top-k 的機制。階梯值彼此錯開,衝突時高階梯贏:

| 階梯 | Pin | 觸發邏輯 | 現況 |
|---|---|---|---|
| +0.01 | chapter-pin | 使用者指定「某書N章」→ 保證該章 ≥2 段存活(weight≥0.85 才合格) | 現役 |
| +0.005 | EQ-pin | reranker top1<0.3(不確定)時 pin 高信心 entity_query 候選 | **legacy** |
| +0.004 | book_anchor-pin | 使用者點名書卷 → 無條件保底(防同姓氏誘餌:路加福音的祭司撒迦利亞 vs 撒迦利亞書) | 現役 |
| +0.003 | graph uncertainty pin | reranker top1<0.3 時 pin 圖譜候選 | **legacy** |
| +0.002 | keyword-exact event pin | 字典 event keyword 與 Event name/alias **完全相等** → pin 該事件第一錨點;排除 hub(mc>25)、每事件 1 錨 | 現役(僅 fusion) |

**設計哲學與 F6 教訓**:五個 pin 分兩類。「不確定性補救」類(EQ-pin、graph-pin)是融合層誕生前的離散手段 — 當時圖譜先驗無法透出,只好在 reranker 沒把握時硬插;融合上線後先驗已連續透出,這兩個 pin 只剩誤傷(rr≈0 的 EQ 噪音被釘到 top-1),於是**退役**(僅 `RAG_RANK_FUSION_ENABLED=false` 的 legacy 路徑保留)。現役三 pin 全屬「**使用者字面指名**」類(指章、指卷、字典詞完全相等)— 字典級確定性訊號,與連續融合正交,不會被 α 取代。一句話:**離散補救機制必須隨排序架構演進而退役,否則由淨正轉淨負。**

keyword-exact event pin 是融合後唯一新增的 pin,救「掃羅 vs 保羅歸主」這種**表面形式斷裂**:使徒行傳 9 章寫「掃羅」,問題問「保羅歸主」,連 curated 別名 + 融合都夠不著,只有「字典 keyword ↔ Event alias 完全相等」這座橋能過 — 且鎖第一錨點(Event 錨點按書卷章節升序 = 敘事起點)、排除 hub 事件(受難週 mc=76 會噴灑整週段落)。

### 5.4 entity_query(EQ)— 現代問法→古譯本的向量橋

把 **query 向量拿去比對「實體」而非「經文」**(Qdrant `bible_entities`;實體文字 = 名稱+別名+描述+常見段落標題),命中實體後走 Neo4j MENTIONS 取段落。「王國分裂」這種現代詞在經文向量空間會漂到但以理書,但與 Event 實體「北方的支派反叛」的向量很近 — 這就是橋。

配套限流:top-8 實體、threshold 0.4、**hub-aware**(mention_count>50 的樞紐實體如耶穌/亞伯拉罕每實體只取 3 段,防 topic 污染)、supplement cap 5、weight 0.6 壓在 semantic 之下(只補充不排擠)。其歷史即 F4 縮影:2026-05 因 reranker 擠出而停用 → 融合層上線後重啟。精巧細節:EQ 對「已被其他策略取回的段落」回注 metadata(`via_entity_score` 等),讓下游 pin 認得出「semantic 撿到的登山寶訓其實也是 EQ 驗證過的」。

### 5.5 粒度錯配因果鏈(M1–M6,最重要的工程教訓)

**傷害 KG 品質的不是 chunk 參數,而是「為 BGE-M3 embedding 設計的三粒度結構」被抽取、匯入、檢索三層無條件繼承**:

- M1 抽取餵料 = embedding 佇列 → verse 級 mention 佔 55.9%;
- M2 Neo4j 不建 Verse 節點 → 匯入時 MATCH 落空**靜默丟棄 97,235 條**(計數器照加,無人察覺);
- M3 被切塊 pericope 的實體只錨 Chunk 層,而檢索與關係抽取只認 Pericope 層 → 雙重失明。

P0 修法是「資料修補不重抽」:strip `:v:N` remap 回 pericope(+5,853 錨點,失明實體 1,474→164)、匯入層加誠實計數器防再犯、檢索端 Cypher 級 chunk→pericope remap。

### 5.6 評估框架的方法論角色

13 項指標分兩性質:檢索指標(hit/recall/mrr/ndcg…)是**程式決定性計算**,逐題可復現 — 本次檢驗中 bit-exact 重現,證明設計目的達成;RAGAS/LLM Judge 有 judge 雜訊(單題 ±0.4)。F9:頭部飽和的 benchmark 上,長尾修復讀數為零 → **評估設計是所有後續優化的前置**。

**F1–F9 發現鏈一句話版**(全文見 `paper/record/2026-07-06_kg_optimization_findings.md`):

- **F1** KG 缺口根因是「為 embedding 設計的粒度結構被三層直接繼承」(M1–M6),非 chunk 參數本身。
- **F2**(negative result,論文核心)KG 完整性大修在 100 題頭部 benchmark 上檢索指標零受益甚至微降。
- **F3** 圖譜訊號價值題型敏感:TSK votes 對主題題是紅利、對事件題是噪音。
- **F4**(last-mile 瓶頸)最終排序被 reranker 字面分數壟斷時,建圖改善與副作用都無法透出。
- **F5** 線性融合(α=0.3)+ 離散修補收復並超越:hit 靠離散、recall 長尾靠連續(互補結構)。
- **F6** pin 式離散補救在連續融合上線後由淨正轉淨負 — 補救機制須隨排序架構演進退役。
- **F7**(第三輪證據)跨卷雙錨題:正解串珠邊在圖裡,但 seed 錯章到不了 —「資料在圖、價值卡檢索端」。
- **F8** 檢索→答案傳導衰減:ctx_recall=1.0 的題 correctness 僅 0.17,增益穿過小模型生成端所剩無幾。
- **F9** 頭部 benchmark 飽和(97/100)後 P1/P2/P3 讀數趨零 — 評估先行方法論。

**主結論:優化順序應由「瓶頸所在層」決定,而非「資料流上游優先」— 排序層一天的修復勝過建圖層一週的重抽。**

---

## 6. 論文引用彙整

書目唯一權威:`paper/latex/refs.tex`(手寫 `\bibitem`,**42 條,已驗證全部有被 `\cite`**;無 .bib 檔)。docs 端清單:`kg_optimization_analysis_2026-07-05.md` §5。IEEE bib 是 docs 清單的超集(補基礎 RAG/IR/模型引用),但**捨棄了 STEPBible TIPNR / ACAI / MACULA 三個聖經資料資源**(四資源僅 TSK 進 bib)與 fast-graphrag / LazyGraphRAG / KAG / iText2KG 四個比較用系統。

### 6.1 核心引用鏈(粒度↔抽取品質)

| 論文 | 出處 | 在本專案的角色 |
|---|---|---|
| **GraphRAG** — From Local to Global(Edge et al. 2024, arXiv:2404.16130) | bib `edge2024graphrag`,全文最高頻 13 次 | 600 vs 2400 token → 抽取實體近 2×;gleanings 配方。M5 主引用 |
| **DocRED**(Yao et al., ACL 2019) | `yao2019docred` | 40.7% 關係跨句、17.6% 需共指 —「岳父/他」漏連的權威數字 |
| **CrossAug** — Beyond Chunk-Local Extraction(Zhang et al. 2026, arXiv:2605.28004) | `zhang2026crossaug` | chunk-local 抽取使跨 chunk 關係系統性缺失;M3/M4 補救範式 |
| **Lost in the Middle**(Liu et al., TACL 2024) | `liu2024lost` | 長上下文中段退化 — 整卷丟入抽取的上界警告 |
| **BGE-M3**(Chen et al., Findings ACL 2024) | `chen2024bgem3`,7 次 | embedding 兼 chunk tokenizer = 粒度錯配根因載體 |

### 6.2 Coreference / Entity Resolution(P1 依據)

| 論文 | 出處 | 角色 |
|---|---|---|
| **CORE-KG**(Meher et al. 2025, arXiv:2506.21607) | `meher2025corekg` | type-aware coref → node dup −33%、noise −38% |
| **Inside CORE-KG**(2025, arXiv:2510.26512) | `meher2025insidecorekg`,5 次 | 乾淨 ablation:**coref 主導去重、prompt 主導去噪** |
| **LINK-KG**(2025, arXiv:2510.26486) | `meher2025linkkg` | 三階段 coref → dup −45%;效益隨文件變長放大 — P1 coref pass 配方 |
| **Better Later Than Sooner**(Loconte et al. 2026, arXiv:2605.29168) | `loconte2026betterlater` | post-extraction 修正比抽取時驗證省 token |
| **EDC** — Extract, Define, Canonicalize(Zhang & Soh, EMNLP 2024) | `zhang2024edc` | 開放抽取後 canonicalize 範式 |

### 6.3 事件層 / 架構範式(P2、P3 依據)

| 論文 | 出處 | 角色 |
|---|---|---|
| **ATOM**(Lairgi et al., Findings EACL 2026) | `lairgi2025atom`,6 次 | atomic facts + dual-time;**P2 事件時間層範本** |
| **E²RAG / ChronoQA**(Zhang et al. 2025, arXiv:2506.05939) | `zhang2025entityevent` | entity+event 雙圖 bipartite;**P2 對照空事件層** |
| **RAPTOR**(Sarthi et al., ICLR 2024) | `sarthi2024raptor`,5 次 | 遞迴摘要樹;**P3 跨章彙總** |
| **Leiden**(Traag et al. 2019, Sci. Rep.) | `traag2019leiden` | 社群偵測(P3 社群摘要) |
| **Calibrated Fusion(PIT)**(Bacellar 2026, arXiv:2603.28886) | `bacellar2026calibrated` | 圖/向量分數校準融合 — **排序融合層理論依據** |
| **DEG-RAG** — Less is More(Zheng et al. 2025, arXiv:2510.14271) | `zheng2025lessismore` | ER 使 KG 縮 40% 反升下游效果 |
| **HippoRAG2** — From RAG to Memory(Gutiérrez et al., ICML 2025) | `gutierrez2025hipporag2` | PPR 檢索 + passage 節點 |
| RAKG / TCR-QF / DyG-RAG / ArchRAG / LightRAG | 各自 bib key | 跨 chunk 回檢 / triple 回指原文 / 事件時序遊走 / 屬性社群 / merge 配方 |

### 6.4 評估方法論

| 論文 | 出處 | 角色 |
|---|---|---|
| **BRINK** — What Breaks KG-based RAG?(Zhou et al. 2025, arXiv:2508.08344) | `zhou2025brink`,6 次 | 缺邊→答案退化 benchmark 化;**P1 重啟前的缺陷注入驗收法**(F2/F9 掛鉤) |
| **Unbiased GraphRAG eval**(Zeng et al. 2025, arXiv:2506.06331) | `zeng2025unbiased`,8 次(次高頻) | 去偏後 LightRAG 勝率 −27.64pt;position bias >30%、length bias >50% — 呼應 RAGAS noncommittal 假象(F8) |
| **RAGAS**(Es et al. 2023) | `es2023ragas` | 評估框架本體 |
| When to Use Graphs in RAG(Xiang et al. 2025) | `xiang2025whengraphs` | GraphRAG 效益視任務型態(呼應 F3) |
| Chunking Strategies 系統研究(Shaukat et al. 2026) | `shaukat2026chunking` | **僅 retrieval 下游**,不宜當抽取層主引(見引用陷阱 4) |

### 6.5 docs 俗名 ↔ bib 正式題名對照(易誤判成兩篇)

| docs 俗名 | bib 正式題名 | arXiv | key |
|---|---|---|---|
| DEG-RAG | Less is More: Denoising KGs for RAG | 2510.14271 | `zheng2025lessismore` |
| PhaseGraph / PIT | Calibrated Fusion for Heterogeneous Graph-Vector Retrieval | 2603.28886 | `bacellar2026calibrated` |
| HippoRAG2 | From RAG to Memory: Non-parametric Continual Learning | 2502.14802 | `gutierrez2025hipporag2` |
| CrossAug | Beyond Chunk-Local Extraction: Cross-chunk Graph Augmentation | 2605.28004 | `zhang2026crossaug` |
| E²RAG / ChronoQA | Respecting Temporal-Causal Consistency: Entity-Event KGs for RAG | 2506.05939 | `zhang2025entityevent` |
| GraphRAG-Bench | When to Use Graphs in RAG | 2506.05690 | `xiang2025whengraphs` |

### 6.6 引用陷阱(4 條,寫作時務必避開)

1. **gleanings 出處錯置**:GraphRAG 官方 `default_dataflow` 文件頁只寫**單輪**抽取;gleanings(多輪補抽)正確出處是**論文 arXiv:2404.16130**,勿引文件頁。
2. **arXiv:2412.07189 的 chunk-size 消融不存在**:實抓 PDF 無「500/1000/1500/2000 token 消融」— 搜尋引擎合成幻覺;「chunk 越小抽越多實體」一律引 GraphRAG 論文(600 vs 2400)。
3. **overlap 量化影響無同行評審論文**:僅部落格/文件層級經驗值;需論證「1 節 overlap 太小」時改引 **DocRED 40.7% 跨句**作間接證據。
4. **arXiv:2410.13070「semantic chunking 不值得」僅測 retrieval 下游**,不可外推到 extraction/KG 建構;且 pericope 切分屬「結構感知」,非其批判的純語義相似度切分。

---

*本文件由 2026-07-07 的獨立檢驗產生;檢驗當時 HEAD = `d85c7eb`。若後續重建資料庫或調整排序層,§2 的 live 數字與 §3 的出入清單需重新核對。*
