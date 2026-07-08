# 發現要點紀錄:KG 優化三輪證據鏈(P0 → 診斷 → 排序融合)

**日期**:2026-07-06
**性質**:論文寫作素材 — 發現(findings)層級的整理,每條附證據出處與文獻掛鉤;非執行紀錄
**證據鏈源文件**:
1. `docs/records/2026-07-05_kg_optimization_analysis.md`(缺口體檢、chunking→KG 因果鏈、路線圖、文獻驗證)
2. `docs/records/2026-07-06_kg_p0_execution.md`(P0 六項資料修復)
3. `docs/records/2026-07-06_kg_p0_eval_p1_decision.md`(negative result 與機制診斷)
4. `docs/records/2026-07-06_kg_fixes_execution.md`(排序融合三修復 + α 消融)
5. `docs/kg_optimization_progress.md`(狀態總覽)

**評估數據目錄**:`evaluation/results_graph_gemma_answer/`(P0 前 5/16)、`evaluation/results_graph_p0_after/`(P0 後)、`evaluation/results_graph/`(修復後)、`evaluation/results_quick/`(α 消融四組)

---

## 發現總表(F1–F9)

| # | 發現(一句話) | 建議章節 |
|---|---|---|
| F1 | KG 缺口的根因是「為 embedding 設計的粒度結構被抽取/匯入/檢索三層直接繼承」,而非 chunk 參數本身 | 系統分析/建置 |
| F2 | KG 完整性大修(anchor +14.4pt、串珠 ×273)在頭部實體 benchmark 上檢索指標零受益甚至微降 — negative result | 實驗結果(核心) |
| F3 | 主題性串珠(TSK votes)對主題彙總題是紅利、對事件敘事題是噪音 — 圖譜訊號的價值題型敏感 | 實驗結果/討論 |
| F4 | 最終排序 100% 由 reranker 字面分數決定時,建圖端的改善與副作用都無法正確透出 — last-mile 瓶頸在排序層 | 實驗結果(核心) |
| F5 | 線性排序融合(α=0.3)+ 離散資料修補即收復並超越:hit 由離散修復飽和、recall 長尾由連續融合補 — 互補結構 | 實驗結果 + 消融 |
| F6 | pin 式離散補救在連續融合上線後由淨正轉淨負 — 補救機制須隨排序架構演進而退役 | 討論 |
| F7 | 跨卷雙錨題:正解串珠邊全在圖裡但 seed 錯章到不了 —「資料在圖、價值卡在檢索端」第三輪獨立證據 | 討論/未來工作 |
| F8 | 檢索→答案傳導衰減:ctx_recall=1.0 的題 correctness 僅 0.17,增益穿過小模型生成端後所剩無幾 | 討論/限制 |
| F9 | 頭部 benchmark 飽和(97/100)後,P1/P2/P3 任何工程在此量尺上讀數趨零 — 評估設計是所有後續優化的前置 | 討論/評估方法論 |

---

## F1|粒度錯配是缺口根因(建置面體檢)

**主張**:傷害 KG 品質的不是 chunk 參數(512/768/overlap 1),而是為 BGE-M3 embedding 設計的粒度結構被抽取、匯入、檢索三層無條件繼承(六機制 M1–M6)。

**關鍵量化證據**(全部 live 覆核,見分析報告 §1–2):
- verse 級 mention **97,235 條(55.9%)匯入時靜默丟棄**(無 Verse 節點,MATCH 落空不報錯,計數器謊報)
- 失明實體 1,474 個(16%);被切塊 pericope 169 個(18.3% 文字量)對檢索與關係抽取**雙重失明**
- 回填精算:100% 可 strip `:v:N` 還原,+5,853 對錨點、活化 1,310 實體(89%)— 最大宗傷害的修復近零成本
- 對照評估面:PERSON 是 graph 唯一輸 semantic 的題型(0.95 vs 1.00)、EVENT ctx_recall 0.608 墊底

**文獻掛鉤**:GraphRAG(arXiv:2404.16130,600 vs 2400 token → 實體引用近 2 倍)+ DocRED(ACL 2019,40.7% 關係需跨句、17.6% 需共指)+ CORE-KG/LINK-KG(coref 去重 −28%~−45%,長文放大)。引用鏈:「粒度錯配傷 KG」從文獻到本地數據閉環。

**引用陷阱**(分析報告 §G,寫作時務必避開):
1. gleanings 出處是論文 arXiv:2404.16130,勿引官方文件頁(文件只寫單輪);
2. 「2412.07189 的 chunk size 消融」是搜尋引擎合成幻覺,不存在;
3. overlap 大小影響抽取**無同行評審量化數字**,用 DocRED 40.7% 跨句作間接證據;
4. arXiv:2410.13070(semantic chunking 不值得)僅測 retrieval 下游,不可推到 KG 建構。

---

## F2|Negative result:建圖大修在頭部 benchmark 讀數為零(論文核心發現之一)

**主張**:anchor coverage 83.8%→98.2%、Event 參與者 34%→84%/地點 32%→75%、串珠 916→250,418(×273)的 KG 完整性大修,在 100 題頭部實體 benchmark 上:hit 0.95→0.93、EVENT hit −0.10、PERSON 逐題完全一致;answer 端僅雜訊級微升。

**三機制解釋**(決策文件 §3,逐題查證非統計推測):
1. TSK votes 排序在事件敘事題引入主題性噪音(→F3);
2. 最終排序 100% 由 BGE-reranker 字面分數決定,圖譜訊號 last-mile 全丟(→F4);
3. benchmark 只問頭部實體,P0 活化的 1,310 個長尾實體讀數為零 — **建圖端量變在頭部量尺上已飽和**。

**可比性保證**(審稿防線):answer/judge 模型、路由分布(R1=20…fallback=2)、EQ 開關三時點一致;唯一系統差異是圖譜狀態;檢索指標為程式對 ground truth 決定性計算,逐題可復現。

**文獻掛鉤**:BRINK(arXiv:2508.08344,KG 缺陷→答案品質非線性)、Unbiased GraphRAG eval(arXiv:2506.06331,去偏後 LightRAG 勝率 −27.64pt)。本結果比「全面提升」更有洞察:**KG 建置品質與檢索讀數之間隔著排序層與量尺兩道衰減**。

---

## F3|圖譜訊號的價值題型敏感:同一機制既是紅利也是噪音

**主張**:votes 高 = 神學主題強關聯 ≠ 同一事件敘事。TSK 串珠 votes 排序讓主題彙總題受益(TOPIC coverage +0.031;mat:5→luk:6 平原寶訓正例),同時讓事件敘事題退步(EVENT hit −0.10;保羅歸主被「保羅宣教主題」串珠擠掉、復活當天被「人子復活預言」串珠擠掉)。

**鐵證五題**(決策文件 §3.1 表):EVENT_019/017/015、PERSON_011、GENERAL_013 — 擠入者的串珠邏輯全部是主題關聯而非敘事同一性。

**論文用法**:修復方向必須題型敏感,不能一刀切回滾 — 對應修復是分權(手工邊 0.75/TSK 邊 0.60)+ cap(30→10),而非拔除資料。

---

## F4|Last-mile 瓶頸:reranker 字面分數壟斷最終排序

**主張**:`ranked = sorted(passages, key=rerank_score)` 之下,strategy weight 與 votes 只決定誰進 pre-rerank 池,不參與最終排序 → 建圖改善(正確錨點進池)字面分不敵噪音就進不了 top-5;建圖副作用(主題噪音字面全中)直接擠掉正解。

**兩輪獨立證據**:2026-05「BGE-reranker 字面 surface match 擠出 entity_query」+ 本輪 TSK 候選擠敘事段 — 同一瓶頸,不同入口。(F7 提供第三輪。)

**代表個案**(寫作可用的具體例子):「最後的晚餐」— 現代問法詞彙不存在於和合本經文(圖譜實體名「逾越節筵席」),正解錨點 rerank_score≈0.001,純字面排序下永不可見;靠 graph prior 0.85 融合進 top-5。「保羅歸主」— act:9 通篇稱「掃羅」,問法用「保羅」,rr=0.074 排第 7,字面高分的 act:18 佔 top1 — 敘事表面形式斷裂的極端案。

---

## F5|修復結構:hit 由離散修復飽和、recall 長尾由連續融合補(α 消融)

**主張**:`fused = (1−α)·rerank + α·strategy_weight`(α=0.3)+ 資料修補(11 aliases + 18 curated Event)+ keyword-exact pin,三者對「BGE 字面排序」的替代機制不同層、互補:

- α=0(其餘修復不變)已飽和 hit(0.97/EVENT 1.00)— 離散修復(curated 資料 + 字典 pin)負責 hit;
- α=0.3 貢獻**尾部錨點覆蓋**:EVENT recall +0.025(多福音平行錨 rr≈0.01–0.02 只有融合救得回)、TOPIC mrr +0.133;代價 ndcg −0.02(top-5 內部排位);
- top-5 全數進 answer context → recall 權重高於內部排位 → 定案 α=0.3。

**修復後指標**(全管線,vs P0 後):hit 0.93→**0.97**、recall@5 0.866→**0.906**、ctx_recall 0.777→**0.830**、coverage 0.725→**0.766**;EVENT hit 0.80→**1.00**(超越 P0 前 0.90)、EVENT ctx_recall 0.546→**0.728**(超越 P0 前 0.608);vs semantic 基線差距擴大到 hit +0.16/recall +0.148。TSK 副作用五題全數回收。

**三時點總表**(論文附錄用,`docs/kg_optimization_progress.md` §2 有完整版):

| 指標 | P0 前(5/16) | P0 後 | 排序修復後 |
|---|---|---|---|
| hit_rate | 0.9500 | 0.9300 | **0.9700** |
| recall@5 | 0.8892 | 0.8658 | **0.9058** |
| ragas_context_recall | 0.7908 | 0.7767 | **0.8297** |
| answer_coverage | 0.7223 | 0.7253 | **0.7664** |
| EVENT hit / ctx_recall | 0.90 / 0.608 | 0.80 / 0.546 | **1.00 / 0.728** |

---

## F6|機制級 finding:pin 式補救隨排序架構演進由淨正轉淨負

**主張**:EQ-pin / graph uncertainty pin 是「融合層之前」的離散補救設計;連續融合把 EQ/graph 訊號透出後,pin 只剩誤傷(GENERAL_003/020:rr≈0.002 的 EQ 雜訊被 pin 到第 1)。融合啟用時退役兩 pin,保留與融合正交的「使用者字面指名」類 pin(chapter-pin、book_anchor、keyword-exact)。

**論文用法**:補救機制有架構適用期;排序架構升級時必須重新審計既有補丁,否則昨日的修復是今日的 bug。GENERAL ndcg −0.08 的表面退步逐題查證為 P0 pin 人工置頂 artifact(正解均在 top-5),是「指標表面退步實為架構自然化」的教學案例。

---

## F7|(本輪新發現)跨卷雙錨題:資料在圖裡、seed 錯章到不了 — 第三輪獨立證據

**主張**:修復後仍 miss 的 GENERAL_006/008 是同一失敗家族 —「跨卷預言—應驗」雙錨合取查詢(需同時命中預言源頭與應驗處兩組錨點),從 P0 前就持續失敗,先前三份文件均未逐題診斷。

**逐題事實**(`evaluation/results_graph/raw_responses.json`):
- GENERAL_006「耶利米書的新約預言如何在希伯來書得到應用?」GT=jer:31:31-34 + heb:8。檢索 seed 全錯章:jer:26/28/29(「預言」字面撞假先知衝突章),heb 完全缺席;correctness 0.127,全場最低。
- GENERAL_008「撒迦利亞書的預言如何在受難週應驗?」GT=zec:9:9; 11:12-13; 12:10 + mat:21/27。seed 撞 zec:4(所羅巴伯);correctness 0.137,全場次低。

**關鍵驗證**(Neo4j live,2026-07-06):正解的 CROSS_REFERENCES 邊**全部存在** — jer:31↔heb:8 共 3 條、zec:9↔mat:21 共 2 條、zec:11↔mat:27 共 5 條、zec:12↔jhn:19 共 2 條。即 P0 灌入的 250,418 條 TSK 邊含有這兩題的完整正解路徑,而 TSK 正是為預言—應驗設計的資源;失敗不在資料,在「1-hop 擴展依賴 seed 正確」的機制。

**論文用法**:與 5 月 EQ 被擠、P0 TSK votes 噪音並列 —「圖譜資產的價值受制於檢索端機制」的第三輪獨立證據,三輪入口不同(排序、排序、seed 選擇),結論一致。未來工作:query decomposition(雙錨拆分)或 Theme 級錨定;**先家族化出題再修**(n=2 上調系統即過擬合,呼應 F9)。

---

## F8|檢索→答案傳導衰減:瓶頸移到生成端

**主張**:檢索大幅改善(ctx_recall +0.053)後 correctness 僅 +0.021(雜訊邊緣);逐題有檢索滿分、答案崩壞的乾淨個案 — 增益穿過小模型生成端(gemma4:e4b)後所剩無幾。

**乾淨個案**(修復後全管線逐題):EVENT_005 ctx_recall=1.0、recall@5=1.0,但 coverage 0.4、correctness 0.173;EVENT_011 hit=1 correctness 0.165;GENERAL_013 hit=1 correctness 0.159。faithfulness 三時點持平(0.95 級)→ 增益來自「更對的 context」,損耗發生在答案生成與 judge 兩端。

**論文用法**:限制章節 + 未來工作(answer 模型 A/B)。**警告**:A/B 時必須排除 RAGAS answer_relevancy 的 noncommittal 拒答假象(本專案已記錄:claude 因拒答被硬扣 0,排除後反高於 gemma)— 呼應 Unbiased GraphRAG eval 的評估偏差主題。

---

## F9|Benchmark 飽和與量尺依賴:評估設計是所有後續優化的前置

**主張**:修復後 97/100(VERSE/TOPIC/EVENT hit 全 1.00),剩 3 題各屬需要新架構的家族:PERSON_004(跨章彙總,P3 層)、GENERAL_006/008(跨卷雙錨,F7)。在此量尺上:
- P1(長尾重抽)— 長尾改善已被 P0 證明讀數為零;
- P2(事件時序)— 題庫的因果/順序題(EVENT_001/002/003/005/009)檢索已滿分,效益只能經 F8 的衰減鏈透出;
- P3(RAPTOR/社群摘要)— 對症題 n=1,無統計力。

**結論**:「先改評估設計」從 P1 的重啟條件升格為 P1/P2/P3 共同前置。反向印證:不動抽取管線、只修排序層,EVENT 即 0.80→1.00 — 量尺決定了哪一層的投資可見。

**新量尺設計方向**(四題族 + 一方法):長尾題(chunk-only 實體/被切塊 pericope 人物×事件)、跨事件時序因果題、跨章彙總題擴充、跨卷雙錨題家族化;BRINK 式缺陷注入(拔邊觀察答案退化)作 KG 價值的因果量測。若執行,「換量尺後 P0 價值顯現」可成為第四輪證據,把 negative result 升級為量尺批判。

---

## 建議的論文敘事骨架(三輪證據鏈)

1. **體檢**(F1):量化八缺口,建立「粒度錯配」因果鏈(文獻:GraphRAG/DocRED/CORE-KG);
2. **介入一**(F2):P0 資料大修 → 建置指標達標、檢索讀數為零 — negative result(文獻:BRINK/Unbiased eval);
3. **診斷**(F3/F4):逐題機制查證 → 排序層是 last-mile;
4. **介入二**(F5/F6):排序融合 + 資料修補 → 全面回收超越 + α 消融的互補結構 + pin 退役;
5. **綜合討論**(F7/F8/F9):三輪「資產在圖、價值卡檢索端」證據;傳導衰減;量尺依賴 → 評估先行的方法論主張。

**一句話主結論候選**:GraphRAG 系統中,KG 建置品質、檢索排序機制、評估量尺三者共同決定可觀測效益;在頭部飽和的量尺上,排序層一天的修復勝過建圖層一週的重抽 — 優化順序應由「瓶頸所在層」而非「資料流上游優先」決定。
