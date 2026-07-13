# 500 題評估結果與 RAG 架構完整分析報告

> **日期**:2026-07-13
> **分析對象**:`evaluation/results_graph/`(2026-07-12 22:25 完成之 500 題全量評估,use_graph=true、top_k=5)
> **方法**:4 個並行分析 agents(指標定義 / 結果解剖 / 檢索架構 / 生成端),均以 live backend 實打 + 數據重算驗證,非純讀碼推斷。全程只讀,未修改任何專案檔案。
> **可重算腳本**:session scratchpad 之 `analyze.py`、`anchor_recall.py`、`verse_cov2.py`、`cases.py`(核心邏輯:用 `output/chapters.jsonl` 每章節數重算經節級覆蓋)。

---

## 總結(TLDR)

1. **「RAG 都有檢索到對的內容」這個前提需要修正** — `hit_rate 0.944` 是量尺灌水造成的假象。評估程式把「馬太福音 5-7 章」這種章範圍當成 **1 個相關單位**,命中其中任一節就算 recall=1.0。用每章真實節數重算,**真實經節覆蓋率只有 0.75**,低分題中有 **53% 是檢索端就失敗**(內容根本不在 context 裡),不是被擠掉、也不是生成沒答好。
2. 低分題(165/500)的失分歸因三桶:**檢索端 53.3%、生成端 29.1%、評分端(量尺)17.6%**。
3. 生成端問題確認屬實且機制明確:prompt 是「忠實度最大化器」——**5 條禁令、0 條完整性要求**,faithfulness 0.925 / coverage 0.674 的剪刀差正是 prompt 被精準執行的結果。
4. **度量陷阱**:`answer_coverage` 與 `ragas_answer_correctness` 對答案長度的偏好**相反**,修 prompt 要求完整列舉會讓 coverage 上升、correctness 下降。動手改之前必須先決定以哪個指標為準。

### 本次整體數字

| 指標 | Overall | EVENT | GENERAL | PERSON | TOPIC | VERSE |
|---|---|---|---|---|---|---|
| answer_coverage | 0.6738 | 0.6797 | 0.5298 | 0.5718 | 0.6959 | 0.8917 |
| ragas_answer_correctness | 0.6260 | 0.6326 | 0.5358 | 0.5497 | 0.6068 | 0.8052 |
| hit_rate | 0.9440 | 0.9600 | 0.9100 | 0.9100 | 0.9800 | 0.9600 |
| recall_at_k | 0.8388 | 0.9067 | 0.6512 | 0.7545 | 0.9218 | 0.9600 |
| ragas_context_recall | 0.7906 | 0.7954 | 0.6604 | 0.7159 | 0.8594 | 0.9217 |
| ragas_faithfulness | 0.9250 | 0.9698 | 0.8699 | 0.9546 | 0.9733 | 0.8567 |

---

## 一、answer_coverage 指標的用意

**實作**(`evaluation/src/metrics/coverage_eval.py`):LLM judge(gemma4:26b,temperature 0.0)對 GT 的每一條 `expected_answer_points` 判定回答是 covered(1.0)/ partial(0.5)/ missing(0.0),取平均後再對題做 macro 平均(2 要點題與 6 要點題同權)。它**只吃要點清單**,不碰 `reference_answer` 也不碰經文範圍 `reference`。

**設計用意**(docstring `coverage_eval.py:1-16` + 論文 `paper/latex/sec5_evaluation.tex:48-52` 均有明文):RAGAS 的 answer_correctness 是 **F1**,回答中每一句 reference_answer 沒有的內容都被當 false positive 扣分——回答越詳盡分數越低。coverage 刻意設計成**純 recall:只問「該講的講了沒」,冗長永不扣分**,judge prompt 裡明寫「不要因為回答比重點更詳盡而扣分」。幻覺風險則交給 faithfulness 把關。三者構成互補三角:**correctness 管精確、coverage 管完整、faithfulness 管不亂編**。

### 兩指標的量尺性質差異(比較絕對值前必須知道)

| | answer_coverage | ragas_answer_correctness |
|---|---|---|
| 公式 | 純 recall(要點覆蓋率) | **0.75×F1(TP/FP/FN statement) + 0.25×cosine**(bge-m3;RAGAS 0.4.3 legacy API 預設權重未覆寫) |
| Judge | gemma4:26b,temp **0.0** | gemma4:26b,temp **0.3**(兩者不一致,correctness 複跑抖動較大) |
| 最低分 | 可歸零(本次 30 題 = 0) | **有 ~0.12 硬地板**(cosine 項),本次 0 題為 0、最低 0.1196 |
| 對詳盡回答 | 不罰 | **系統性懲罰**:好答案(cov≥0.8)中答案長度與 ac 的相關 r = **−0.477**;0-300 字組 ac 0.826 vs 900-1200 字組 0.553 |
| 對拒答 | 給 0 且計入分母 | 整題**剔出分母**(`ragas_eval.py:139`)——處置方向相反 |
| 實測天花板 | — | **~0.78**(檢索、生成雙優的 189 題 ac 也只有 0.778) |

所以 **0.6738 vs 0.6260 的絕對值不能直接互比**;ac 要按 ~0.78 天花板讀(0.626/0.78 ≈ 80%)。

**修正一個誤傳**:「RAGAS 對拒答(noncommittal)硬扣 0」的規則在 **answer_relevancy**(`ragas/metrics/_answer_relevance.py:119,127`;本次 22 題 relevancy=0),correctness 沒有這條規則,只有 F1 歸零後剩 cosine 地板的「軟抑制」。

### 評分端鐵證案例

- `TOPIC_QUESTION_008`(希伯來書 11 信心人物):答案完整正確(亞伯/以諾/挪亞/亞伯拉罕/撒拉/摩西/喇合全列),cov 0.875、faithfulness 1.0、relevancy 0.999,**ac 只有 0.332**——RAGAS 把 reference_answer 摘要沒寫到的正確陳述全判 FP。
- `TOPIC_QUESTION_023`(拿細耳人條例):cov **1.00** / ac **0.441**,答案 1,162 字 vs reference_answer 90 字(12.9 倍)。

---

## 二、最重要發現:檢索指標系統性灌水

`evaluation/src/relevance_judge.py:140` 的 `estimate_total_relevant()` 把整段章範圍算作 **1 個相關單位**。

**鐵證 `EVENT_QUESTION_011`**(登山寶訓,GT 要馬太 5-7 章共 111 節):實際只檢索到 6 節(太 5:1-2、5:13-16),另 3 塊 context 是希伯來書、詩篇、啟示錄——**官方 hit_rate=1.0、recall_at_k=1.0**,而 answer_coverage=0.0、ac=0.162。

用 `output/chapters.jsonl` 的真實每章節數重算(確定性計算,無 LLM):

| 指標 | 數值 |
|---|---|
| 官方 hit_rate | 0.9440 |
| 官方 recall_at_k | 0.8388 |
| **真實經節覆蓋率(verse_cov)** | **0.7499** |
| ragas_context_recall(參考) | 0.7906 |

**40 題(8%)官方 recall=1.0 但真實覆蓋 <50%**。最極端 `PERSON_QUESTION_001`:創 12-35 章共 742 節只拿到 8 節(verse_cov=0.011),官方仍算滿分。

這也回答了一個歷史懸案:**07-06 P0 之後「檢索指標零受益」的真因是指標早已飽和在假滿分上**,任何檢索改進都量不出來。修對量尺之前,任何檢索優化都看不出效果。

---

## 三、失分歸因:低分題的三桶拆解

低分題(ac<0.5 或 cov<0.5)共 **165/500 題(33%)**,用真實經節覆蓋(而非灌水的 hit_rate)做四象限歸因:

| 類別 | 題數 | 佔低分題 | 平均 ac | 平均 cov | 平均 verse_cov |
|---|---|---|---|---|---|
| A. 檢索完全失敗(verse_cov=0) | 27 | 16.4% | 0.210 | 0.057 | 0.00 |
| B. 檢索部分失敗(0<verse_cov<0.5) | 61 | 37.0% | 0.407 | 0.377 | 0.23 |
| **A+B 小計:檢索端** | 88 | **53.3%** | | | |
| C. 檢索 OK 但生成沒挖乾淨(verse_cov≥0.5, cov<0.5) | 48 | **29.1%** | 0.499 | 0.299 | 0.85 |
| D. 生成也 OK 但 RAGAS ac 扣分(cov≥0.5, ac<0.5) | 29 | **17.6%** | 0.435 | 0.753 | 0.86 |

門檻敏感度(誠實揭露):「檢索 OK」門檻取 verse_cov≥0.5 / 0.7 / 0.9,檢索端占比分別為 53% / 66% / 74%——**無論哪個門檻,檢索端都是最大的桶**。

⚠️ 若照 `hit_rate==1` 的天真定義會得出「83.6% 是生成端問題」——**這正是被灌水指標騙出來的錯誤結論**(先前 07-13 的「生成端 91.5%」分析即由此而來,本次推翻)。

### 家族分解(結果 JSON 無 family 欄位,需手動 join GT)

注意:`family` 欄位被評估管線的 pydantic `extra='ignore'` 靜默丟棄(`evaluation/src/models.py:9-16`),`evaluation_results.json` 裡沒有 family;且原始 100 題根本沒標 family(metadata 宣稱 legacy_head 但未兌現)。

最差 6 個家族:

| family | n | ac | cov | 真實 verse_cov | 官方 recall(灌水幅度) |
|---|---|---|---|---|---|
| disambiguation | 12 | 0.448 | 0.385 | 0.440 | 0.465(+0.03) |
| trajectory | 18 | 0.474 | 0.411 | 0.350 | 0.604(**+0.25**) |
| multi_chapter | 25 | 0.477 | 0.433 | 0.374 | 0.687(**+0.31**) |
| nt_quotes_ot | 16 | 0.479 | 0.430 | 0.591 | 0.471(−0.12) |
| prophecy_fulfillment | 26 | 0.514 | 0.525 | 0.683 | 0.647(−0.04) |
| temporal | 16 | 0.527 | 0.481 | 0.419 | 0.604(+0.19) |

最好:longtail_book 0.843(verse_cov=1.0)、head_cold 0.776、parable 0.756。

**結論:長尾知識不是問題(單錨家族真實覆蓋全 ≥0.86),跨章/跨卷多錨彙總才是**——trajectory / multi_chapter / temporal 的真實檢索覆蓋只有 0.35-0.42,而且正是這些家族的官方 recall 灌水最兇(+0.19 ~ +0.31)。

### Route 表現

R1 **0.833** > R6 0.610 ≈ R2 0.609 ≈ fallback 0.605 > R4 0.560 > **R3 0.546(101 題,verse_cov 僅 0.588,最大問題 route)** > R5 0.519。檢索完全落空的 28 題中,fallback 15 題 + R3 8 題佔 82%。

典型病灶「實體錨定壓過經文語意」:

- `PERSON_QUESTION_090`:問「約書亞」,檢索回**約西亞**(王下 22 猶大王)——一字之差人名混淆,模型誠實拒答。
- `VERSE_LOOKUP_099`(paraphrase 家族):腓 4:13「凡事都能做」不給出處 → 觸發不了 R1 → fallback 錨定「保羅」→ top-5 全是使徒行傳敘事,目標經文一塊沒進來。
- `EVENT_QUESTION_083`:「肉體的一根刺」(林後 12)→ 同模式,全回使徒行傳。

### 與 07-06 P0 後的配對比較(同 legacy 100 題)

| metric | 07-06(P0 後) | 07-12(本次) | Δ |
|---|---|---|---|
| ragas_answer_correctness | 0.5960 | 0.6136 | +0.018 |
| answer_coverage | 0.7253 | 0.7588 | +0.034 |
| ragas_context_recall | 0.7767 | 0.8247 | +0.048 |

淨小幅正向;逐題:進步>0.05 者 27 題、退步>0.05 者 24 題。注意 500 題整體 ac(0.626)高於 legacy 子集(0.614)是**題目組成效應**(新增單錨長尾家族拉高平均),不代表系統變強。

---

## 四、RAG 架構現狀與「擠出」機制

### 管線全貌

```
POST /api/v1/query (routers/query.py:25)
  → 意圖分類 + 經文引用偵測 (intent_classifier.py / verse_parser.py)
  → 訊號偵測 (signal_detector.py:50,字典 substring match)
  → 路由決策 (signal_detector.py:146-160,規則樹先中先贏):
      書卷+章+節 → R1(無條件搶佔)
      章+多書卷 → R5;章 → R2;多書卷/cross_ref → R5
      多人物 → R3;事件詞 → R4;地點 → R6;否則 fallback
  → 各路由建候選池(R1 只跑 verse_direct;其餘 semantic/graph/cross_ref/entity_query/sql 組合)
  → _dedup (router.py:249,只比字串 id)
  → BGE-reranker-v2-m3 全池重排 (reranker.py,輸入截斷 max_length=512)
  → 融合 fused = 0.7×rerank + 0.3×weight (router.py:259-276,α=0.3)
  → pin 層(chapter/book_anchor/keyword_event,各自 prepend 後截斷)
  → top_k=5 截斷 → 組 context (generator.py:32-50) → LLM 生成
```

關鍵參數(容器 env 實測):top_k=5、初始檢索候選 20、α=0.3、use_graph=true、hybrid=true、embedding=bge-m3、reranker=bge-reranker-v2-m3、生成 LLM=gemma4:e4b-it-q8_0(temp 0.1、num_predict 10000)。

**評估管線與線上完全一致**:`run_eval.py` 打 `POST /api/v1/query`(`rag_client.py:55`),同路徑、同 prompt。評估結果反映的就是線上系統。(但 `--semantic` 消融走 dense-only 的 `bible_embeddings` collection,與主線 hybrid collection 不同,**不是 BM25 的乾淨 ablation**——論文寫消融要講清楚。)

### 「正確內容被擠掉」的實測機制

1. **reranker 字面 match(鐵證)**:「保羅歸主」→ 真答案 `act:9:0` rerank 0.018(排第 4),字面含「保羅」的 `act:18:0` 拿 0.658 奪冠;「登山寶訓」→ `mat:5:*` rerank ≈ 0.000(現代詞不在古經文中),全靠 α 權重項 0.3×0.85 撐住。另 reranker 輸入截斷 512 token,長 pericope 後段對 rerank 隱形;reranker 也看不到 book/chapter metadata。
2. **BUG A(新發現):book_anchor 對跨卷題靜默失效** — `_expand_via_book_anchor` docstring 說 per-book 各自貢獻種子(`router.py:1226-1229`),實作卻是單次 MatchAny OR-filter(`router.py:708`)。實測 R5「耶利米書新約預言在希伯來書應驗」:耶利米書吃光 10 筆、**希伯來書 0 筆**(per-book 重放可撈回 heb 候選),且 new_candidates=[] 時連 strategies 都不記錄,完全靜默。跨卷雙錨家族(GENERAL_006/008)病灶即此。
3. **BUG B(新發現):chunk 與 parent pericope 不摺疊** — `semantic_retriever.py:44-55` 只把 type=verse 摺回 parent,type=chunk(4 段式 id)不摺。實測同一段落(耶 26)以 `jer:26:0` / `:0:0` / `:0:1` 三種粒度吃掉 5 個 slot 中的 3 個。但量化後總體傷害不顯著(有重複題 ac 0.583 vs 無重複 0.579),屬低優先回收(81 題 130 槽)。
4. **BM25 對最終排序貢獻恰為 0(再次實錘)**:RRF 分數(`hybrid_score`)只在 `hybrid_retriever.py:111` 寫入、全庫無人讀;hybrid 候選拿扁平 weight。BM25 只影響誰進 top-20 候選池。
5. **R1 搶佔需要重新評價(推翻先前認知)**:R1 觸發的 90 題(只回 1 塊 context)其實是**全 route 表現最好的**(ac 0.833、verse_cov 0.982)——單錨題單塊剛好夠用。真正受害僅 2 題(`GENERAL_042`/`060`,多錨題被劫持;GENERAL_042 實測候選池=1、回傳=1,「新約哪些經文呼應創 3:15」根本無法回答)。**R1 真正的問題是反向的:該觸發卻觸發不了**——paraphrase 家族 18 題(引句不帶出處)全掉 fallback,4 題全空;走 R1 的 VERSE_LOOKUP ac 0.854 vs 沒走的 0.599。

### 營運陷阱(順帶發現)

容器的 env 是 **create 時快照**:`.dockerignore:22` 排除 `.env` → 容器內無 `/app/.env`,pydantic env_file 在容器內是 no-op,所有設定來自 docker-compose `env_file:` 在 **create 時**注入的 os.environ。**改 `.env` 後 `docker restart` 不會生效,必須 `docker compose up -d --force-recreate backend`**。實測目前容器(07-06 create)與現行 `.env` 的檢索參數一致(近期 commit 只動了 `.env.example` 與 docs),無實害,但這是雷。

另:Qdrant collection 實名為 `bible_embeddings`(34,072,含 pericope 2,610 / chunk 431 / verse 31,031 混同一 collection)/ `bible_embeddings_hybrid`(34,072)/ `bible_entities`(9,124)。

---

## 五、生成端確認結果

### Prompt 全文(唯一一種,`backend/utils/generator.py:13-29`)

```
你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」中的資訊來回答，禁止使用經文以外的任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）
3. 將相關經文內容整理成連貫的回答
4. 不要加入經文中沒有提到的推論、解讀或額外資訊
5. 回答使用繁體中文
```

User template(`generator.py:22-29`):「以下是提供的經文段落（你只能使用這些內容來回答）：{context} --- 嚴格根據以上經文段落的內容，回答以下問題。不要添加經文中沒有的資訊：{question}」

**Intent 沒有傳進生成端**(`routers/query.py:64` 只傳 question + results)——「十架七言列出七句」和「約 3:16 說什麼」用完全相同的 prompt。R1-R6 路由只影響檢索,不影響生成。

### 批判分析

**5 條禁令、0 條完整性要求。** 沒有任何「列出所有」「完整列舉」「逐段檢視」的指示;唯一的正向指令「整理成**連貫**的回答」是收斂性指示(把材料收攏成流暢短文,與窮盡列舉方向相反)。**faithfulness 0.925 / coverage 0.674 的剪刀差,就是模型精準執行了它被交代的事。**

**乾淨的因果證據**(控制 context 品質:只看要點≥4 的實質回答,各長度組 context_recall 持平 ~0.83):

| 答案長度 | n | coverage | context_recall | 缺口(context 有但沒挖) |
|---|---|---|---|---|
| 0-200 字 | 42 | 0.464 | 0.674 | **+0.210** |
| 200-350 字 | 86 | 0.622 | 0.832 | **+0.210** |
| 350-500 字 | 96 | 0.701 | 0.822 | +0.121 |
| 500-700 字 | 77 | 0.712 | 0.834 | +0.122 |
| 1000+ 字 | 15 | 0.885 | 0.883 | **−0.002** |

答案寫多長,coverage 就跟到哪——內容都在手上,模型提早收工。生成端標準案例 `TOPIC_QUESTION_031`(歷代志上 29):context_recall=1.0、錨點全中,但 5 要點只寫 1 個(cov 0.20)。

**排除的便宜解釋**(均實測證偽):

- ~~max_tokens 截斷~~:500 題 0 題斷在句中,最長 2,433 字 vs num_predict 10,000。
- ~~num_ctx 靜默截斷輸入~~:從容器走產線路徑實打 Ollama,12,000 字輸入 prompt_eval_count 線性成長無截斷(最大真實 context ~5,800 tokens)。但生成端未顯式設 num_ctx、judge 端有設 16384,建議補齊(消除隱式行為依賴,非現行病因)。
- ~~拒答傾向~~:全文拒答僅 17 題(3.4%),其中 11 題 verse_cov=0——**檢索真的沒給料,拒答是正確行為**(這批 faithfulness 0.985)。

**Context 引用位置效應**:全部 context 的被引用率從 [1] 90.7% 單調遞減到 [5] 58.1%,平均只用 3.55/5 條。但 gold context 的引用率 85-96% 且無位置差——後排引用率低主要因為後排常不相關,「模型忽略後段」(primacy bias)的解讀要打折。

---

## 六、提升方向討論(依投報比排序;本次僅分析未動手)

### 第 0 步(先於一切):修量尺

1. **修檢索指標**:`estimate_total_relevant()` 改成經節級(或 pericope 級)召回。這是 P0——hit_rate 假滿分已經騙過一輪歸因(「91.5% 生成端」假說),不修的話下一輪還會再騙。
2. **決定主指標**:coverage 與 ac 對答案長度偏好相反,**不可同時最大化**。建議以 **answer_coverage 為主指標 + faithfulness 守門**,ac 附天花板校正(~0.78)作參考;若要繼續以 ac 為主,得把 GT `reference_answer` 擴寫到與要點等寬(工程量大)。
3. **GT 要點審計**:63% 的題恰好 5 個要點(313/500,機械化生成痕跡);擴充 400 題 coverage(0.6525)比原 100 題(0.7588)低 0.106 但 ac 反而高 0.016——**coverage 絕對值的一大塊下滑是 GT 出題方式**(把 gold 段落拆成要點,而非把「題目的答案」拆成要點,例:`GENERAL_052` 問「哪句話」單一事實、GT 卻期望整段敘事 5 要點,模型精準答對仍 cov 0.2)。約 17.6% 低分題屬評分端假失分。

### 檢索端(最大的桶,53%)

4. **fallback/R3 的實體錨定反噬**:引句/釋義類問題被人名實體淹沒(腓 4:13 → 使徒行傳)。方向:exact-phrase 訊號(79 題引文題中 25 題可被 exact-phrase pin 直接回收)、R3 多錨行為修正(R3 是唯一 verse_cov<0.6 的大 route)。
5. **BUG A 修復**(book_anchor 改 per-book 迴圈各取 top-N):跨卷家族直接受益,改動小。
6. **多錨彙總機制**:trajectory/multi_chapter 真實覆蓋 0.35-0.42,top_k=5 對 4+ 錨題結構性不足(n_refs≥4 的題 verse_cov 僅 0.37)。方向:章範圍展開、動態 k、per-anchor 配額(注意 pin 層在融合後各自截斷,配額要做在 pin 之後)。

### 生成端(29%,最便宜的單筆改進)

7. **Prompt 加完整性指令**(「逐一檢視所有段落、列出全部相關要點」)+ 軟化「連貫」。以 gold-span 全進 context 的題子集估計,可修天花板 cov ~0.92(現況 0.82)。**注意第 2 點的度量陷阱:cov 會漲、ac 會跌**,先定主指標再動手。
8. **按 intent 分流 prompt**(把已算好的 intent 傳進 `generate_answer`):EVENT/PERSON/TOPIC 用列舉型;VERSE_LOOKUP 現況 0.89 不要動。
9. **R1 反向修復**:讓 paraphrase(引句不帶出處)也能進 R1 精確查找(18 題受害);同時多錨題不讓 R1 獨佔——僅當 verse_refs 是唯一訊號時才搶佔,多訊號時把 verse_direct 當高權重候選(w=1.0)注入其他路由的池(2 題受害)。

---

## 七、對先前結論的修正清單

| 舊結論(07-13 v2 之前) | 本次修正 |
|---|---|
| 生成端失分佔 91.5% | **推翻**:那是用灌水 hit_rate 算的;真實為檢索 53% / 生成 29% / 評分 18%(「91.5%」的原意是「漏點位於已引用 chunk 內」的機制佔比,勿引伸為失分佔比) |
| 單錨 ac 0.974 vs 多錨 0.486 | 0.974 是**檢索召回**(anchor_recall)不是 ac;單錨 296 題 ac 僅 **0.698**(仍有 0.3 空間),多錨 204 題 0.522 |
| R1 搶佔害了 90 題 | R1 組是**全場最佳 route**(ac 0.833);真受害僅 2 題,真問題是 paraphrase 18 題**進不了** R1 |
| answer_correctness 對拒答硬扣 0 | 該規則在 **answer_relevancy**;correctness 只有軟抑制(~0.12 cosine 地板) |
| 改 .env 後 restart 即生效 | **錯**:容器 env 是 create 時快照,必須 `docker compose up -d --force-recreate backend` |
| GT 要點「超出經文範圍」~39% | 修正描述:要點都**在**經文範圍內,錯位是「要點涵蓋範圍**寬於題幹所問**」;量級約 17.6%(評分端假失分) |

## 附:個案速查表

| question_id | 失分類型 | 一句話診斷 |
|---|---|---|
| EVENT_QUESTION_011 | 檢索(指標灌水代表) | 登山寶訓 111 節只拿到 6 節,官方 recall=1.0 |
| PERSON_QUESTION_001 | 檢索 | 創 12-35 共 742 節只拿到 8 節,官方 recall=1.0 |
| PERSON_QUESTION_090 | 檢索(人名混淆) | 問約書亞撈回約西亞,模型誠實拒答 |
| VERSE_LOOKUP_099 | 檢索(實體反噬) | 「凡事都能做」無出處→fallback 錨定保羅→全是使徒行傳 |
| EVENT_QUESTION_083 | 檢索(實體反噬) | 「肉體的一根刺」同上模式 |
| TOPIC_QUESTION_057 | 檢索(多錨) | 馬太五大講論 5 錨只中 1 |
| PERSON_QUESTION_062 | 檢索(BUG B) | 兩個亞比米勒:4/5 slot 是同一士師記 pericope 的 parent+child |
| GENERAL_BIBLE_QUESTION_042 | 檢索(R1 劫持) | 「創 3:15 新約呼應」被 R1 攔截,候選池=1 無法回答 |
| TOPIC_QUESTION_031 | 生成(沒挖乾淨) | 代上 29 錨點全中,5 要點只寫 1(cov 0.2) |
| GENERAL_BIBLE_QUESTION_052 | 評分(GT 錯位) | 問「哪句話」,模型精準答對;GT 期望整段敘事 5 要點 |
| TOPIC_QUESTION_008 | 評分(F1 罰詳盡) | 希伯來書 11 答案完整正確(cov 0.875),ac 僅 0.332 |
| TOPIC_QUESTION_062 | 評分(judge 誤判) | context_recall=1.0 但 context 實際沒有詩 120-134;兩個 judge 互相矛盾 |
