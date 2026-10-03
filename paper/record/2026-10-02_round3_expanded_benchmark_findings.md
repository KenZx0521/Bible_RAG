# 發現要點紀錄:Round 3 —— 500 題三組態消融(graph / no_graph / semantic)

**日期**:2026-10-02
**性質**:論文寫作素材 — 發現層級整理(延續 F1–F9 編號);已寫進 `paper/latex/sec6b_round3.tex` 並同步修訂各節
**評估數據目錄**:`evaluation/results_graph/`(2026-09-29)、`evaluation/results_no_graph/`(09-29)、`evaluation/results_semantic/`(09-30);answer = gemma4:e4b-it-q8_0(temp 0.1)、judge = gemma4:26b-a4b-it-q8_0、top-5、RAGAS 0.4.3、每組態各跑一次
**重算工具**:`python3 paper/tools/round3_stats.py [--json out.json]` 重算三個 Round 3 結果檔衍生的所有數字(先斷言聚合值與結果檔 overall/by_type/by_family 逐位一致,bootstrap B=10,000、seed 20260930;表格採四捨五入 half-up);`python3 paper/tools/replay_routes.py` 重現 classifier 路由重放與 07-15 對照
**對照用的舊憑證**(工作區已刪、git HEAD 仍在):`results_graph_gemma_answer/`(Round 0)、`results_graph_p0_after/`(Round 1)、`d85c7eb:evaluation/results_graph/`(Round 2)、`5a45393:evaluation/results_graph/`(2026-07-15 的 500 題 run)、`results_quick/faith_metric_validation.json`

輪次命名(論文已在 intro 定義):Round 0 = 5 月架構對照;Round 1 = P0;Round 2 = 排序融合;Round 3 = 本輪。

---

## 發現總表(F10–F18)

| # | 發現(一句話) | 論文位置 |
|---|---|---|
| F10 | 頭部結果重現:原 100 題 graph hit 0.97、領先 semantic +0.16,與 Round 2 完全一致 | §XI-B |
| F11 | +0.16 的約五分之四屬於訊號路由(no_graph 已 +0.13),graph 只占 +0.03 且集中在人工整理過錨點的頭部事件 | §XI-B、摘要、結論 |
| F12 | 修復從沒見過的 400 題上,graph 中性偏負(anchor coverage −0.012,CI 不含 0),損失集中在 R3 人物路由 | §XI-B |
| F13 | 機制:錯的圖譜錨點穿過排序層 —— 多數是「注入」(graph 把離題段落塞進候選池,reranker 本身就偏好),少數由融合先驗決定 | §XI-C、討論第四事件 |
| F14 | 修好的 judge 下 faithfulness 三組態都 ≈0.98、無顯著差異 → Round 0「檢索品質傳導到 faithfulness 0.90→0.95」未獲證實 | §XI-D、Round 0 註記 |
| F15 | 雜訊地板實測:296 題 context 逐字相同,coverage 仍平均差 0.060 | §XI-D |
| F16 | intent classifier 在 Rounds 0–2 的所有 Gemma run 都靜默失效,路由只靠正規式+字典;路由重放逐題重現 | §XI-A、§V-C、附錄 |
| F17 | 舊論文小錯:Round 2 的路由分佈其實是 R4=19/R6=3(融合輪新增「客西馬尼禱告」關鍵字) | 表 V 註、附錄 |
| F18 | EVENT_005 的「完美檢索」是 unit-level 假象:民 13 章從未被檢回(verse recall 0.29) | 討論 §XII-C |

---

## F10|頭部結果重現

- 原 100 題(legacy_head):graph hit **0.970** / no_graph 0.940 / semantic **0.810** → 領先 **+0.16**(Round 2 論文值同為 0.97、+0.16)。
- 漏題組成改變:graph 漏 PERSON_004、EVENT_020、GENERAL_006;GENERAL_008 現在命中(classifier 修好後改走 R5,新啟用的實體遍歷 `graph` 策略拿到 mat:21:0),EVENT_020 新漏(見 F13)。
- 對照 07-15 的 500 題 graph run(classifier 仍壞):classifier 修好讓 114/500 題改路由,但 graph 組態檢索幾乎不變(verse recall 0.751→0.749、anchor 0.785→0.781、hit 0.946→0.944,後者含一題基礎設施失敗)。

## F11|路由才是主力

配對差異(排除 VERSE_LOOKUP_035,95% bootstrap CI):

| 對比 | 子集 | hit | verse recall | anchor cov. | coverage |
|---|---|---|---|---|---|
| no_graph − semantic | 原 100 | +0.130 [+0.070, +0.200] | +0.132 | +0.120 | +0.099 [+0.039, +0.164] |
| no_graph − semantic | 全 499 | +0.050 [+0.030, +0.070] | +0.040 | +0.043 | +0.031 [+0.012, +0.051] |
| graph − no_graph | 原 100 | +0.030 [−0.020, +0.080] | +0.002 | +0.026 | −0.006 |

- graph 在原 100 題的淨貢獻來自 EVENT(0.95 vs 0.80):EVENT_008/011/014/019 四題得分(其中 008/014/019 是 Round 2 的四個翻轉題中的三個)、EVENT_020 一題失分;另 GENERAL_008 +1、PERSON_004 −1 互抵。
- 路由收益的來源:semantic 在原 100 題漏的 VERSE 5 題、TOPIC 5 題靠 R1 精確經節/R2 整章修好,GENERAL 修 3 題。

## F12|擴充 400 題:graph 中性偏負

graph − no_graph(399 題):anchor coverage **−0.012 [−0.023, −0.003]**、context recall −0.012 [−0.023, −0.003]、MRR −0.015 [−0.028, −0.002]、verse recall −0.009 [−0.019, +0.001]、coverage −0.014 [−0.029, +0.001]。
- 對 semantic 的優勢只剩 hit(+0.025 [+0.005, +0.048])和 MRR;verse recall/anchor/coverage 統計上持平。
- 集中在 R3:擴充題兩邊都走 R3 的 55 題,開 graph 讓 verse recall 0.692→0.627、coverage 0.606→0.567。
- 家族:title_coref −0.120、multi_chapter −0.049、nt_quotes_ot −0.031 最傷;typology +0.117(n=12)唯一明顯得分。
- R1/R2/fallback 不呼叫 Neo4j:這些路由上兩組態檢索逐位相同(唯一例外是 VERSE_LOOKUP_035 的 ConnectTimeout)。

## F13|機制:錯錨穿過排序層(注入為主、先驗為輔)

- 算式:fused=(1−α)·rr+α·w,α=0.3;typed graph 先驗 0.85–0.9、semantic 0.65–0.7 → semantic 候選要贏,reranker 分數得高出約 0.06–0.11。
- 依 graph 策略占 top-5 的槽數分桶(兩邊同走 R3–R6 的 253 題):3 槽 hit +0.116(原 100 題 +0.250);**5 槽全占 hit −0.103、verse recall −0.099、coverage −0.112**(擴充題 −0.133/−0.130/−0.182);0 槽檢索相同,coverage +0.034 純屬雜訊。
- 注意:分桶依據是 graph run 的結果(處理後變數),只能當描述性分解,不是因果劑量反應。
- **注入 vs 先驗(2026-10-02 審核後更正)**:同一段落兩邊 run 的 reranker 分數相同,可由 fused 與先驗反解 rr。兩邊同路由且 graph 掉 hit 或 verse recall 的 30 題中,16–21 題(視少數策略的確切先驗而定)reranker 單獨就偏好每個 graph 段落勝過每個被擠掉的段落 → 主因是**注入**;只有 9 題先驗對至少一次擠位有決定性。原本寫的「先驗壟斷/融合傳錯錨」是錯的,論文已改寫。
- 三個實例:EVENT_020(浪子的比喻)被修好的 classifier 送進 R4,graph_event 注入凶惡園戶(路20/太21/可12)與撒種的比喻(路8)塞滿五槽,fused 0.48–0.57;正確的路15 在 no_graph run 是 0.38,但 reranker 本身就偏好入侵者(rr 0.32–0.44 vs 0.24,先驗只加 0.045)→ 注入;Round 2 時它掉 fallback 反而命中。GENERAL_048(愛人如己)同為注入(R5 新啟用的實體遍歷塞進保羅的使徒行傳段落,rr 就勝過羅13)。PERSON_066(提摩太的外祖母和母親)是先驗案例:最弱的徒20(rr 0.073)與 gold 提後1(0.077)幾乎同分,先驗決定。PERSON_004 也是先驗案例(graph_person 用族譜/名冊塞滿五槽,擠掉 no_graph 拿到的出6–7)。
- 原 100 題 graph 的 verse recall 勝 17 敗 9(勝的都在 PERSON/EVENT,外加 GENERAL_008);擴充題敗多於勝 22 比 13。

## F14|faithfulness 修判後無差異

- zh 0.980–0.981、strict 0.979–0.980;三組態全過守門(strict run ≥0.97、題型 ≥0.95);所有配對 CI 含 0;全體 no_graph − semantic +0.001 [−0.008, +0.010];原 100 題 +0.022 [−0.001, +0.052] 剛好含 0 —— 只能說「未獲證實」,不能說「不成立」(區間仍容得下 Round 0 那麼大的差)。
- 檢索品質改反映在 coverage:原 100 題 semantic 0.636 → no_graph 0.735 → graph 0.729。

## F15|雜訊地板實測

- graph 與 no_graph run 中 296 題 context 逐字相同(R1/R2 全部 177、fallback 59、graph 路由 60)。
- 這些題的答案端差異純屬生成取樣+judge 雜訊:coverage 平均 |Δ| 0.060(14% 題移動 ≥0.2 —— 注意 1.0−0.8 浮點不精確,門檻要加容差;平均 Δ −0.002、SD 0.131)、correctness 0.074、faithfulness 0.028、context recall 0.003。
- 推論:兩個 400 題 coverage 平均的配對差,光雜訊就有約 ±0.013(95%)—— 和 F12 的效應同量級,所以一律報配對 CI。

## F16|intent classifier 靜默失效(Rounds 0–2 全部 Gemma run)

- 病因(commit feb79e2,2026-07-31 修):gemma4 *-it 是 reasoning 模型,隱藏 thinking token 吃光 max_tokens=256,content 空字串 → JSON 解析失敗 → 靜默 fallback 成 intent=topic、entities/keywords 皆空。
- **證據**:以「空 classifier 輸出」重放 `detect_signals`,逐題重現 Round 0 Gemma graph(100/100)、Round 1(100/100)、Round 2(100/100)、07-15 的 500 題 run(500/500)的路由紀錄;Round 0–1 重放須拿掉融合輪才加的「客西馬尼禱告」關鍵字。Round 0 Claude graph run 只有 92/100 吻合(Claude 的 classifier 正常,改了 8 題路由)。
- 影響:Rounds 0–2 的 Gemma 路由只靠正規式+字典;只吃 classifier 輸出的策略從沒跑過(R5 的實體遍歷 `graph`:07-15 run 0 次 → Round 3 73 次;graph_event 47 → 104 次)。修好後 114/500 題改路由(48 fallback→R4、27 R3→R5、14 R6→R4、12 fallback→R5、7 R6→R5、6 R4→R5;原 100 題中 7 題)。
- 論文處理:§V-C classifier 條目、Round 0 表註(Gemma 路由只靠字典;Claude 的 classifier 改了 8 題路由)、P0 評估條件、附錄可比性段落都已加註。

## F17|舊論文路由分佈小錯

- 表 V 註與附錄原寫「三個時點路由分佈相同 R4=18/R6=4」;實際上 Round 2 是 **R4=19/R6=3**:融合輪(046040a)新增關鍵字「客西馬尼禱告」,讓 EVENT_015 從 R6 改走 R4。重放驗證:用舊關鍵字集重現 R4=18/R6=4。已更正。

## F18|EVENT_005 的「完美檢索」是 unit-level 假象

- 論文討論用它示範「檢索滿分、答案打折」;但 gold 是民 13–14 章,所有存檔 run(Round 0–3,共 10 個)都沒檢回民 13 章 → run of record 的 anchor coverage 0.5、verse recall 0.29。
- Round 3 中 no_graph 與 semantic 拿到逐字相同的 context,coverage 卻是 0.7 vs 0.4 —— 同時是雜訊示範。討論段已加註。

---

## 論文改動清單(2026-10-02)

| 檔案 | 改動 |
|---|---|
| `main.tex` | 日期註腳、頁眉;摘要加第四輪;`\input{sec6b_round3}` |
| `sec1_intro.tex` | 第四輪一句;貢獻 6→7(新增 Round 3);方法論結論加「消融須在修復沒見過的題上做」;路線圖定義 Round 0–3;related work 加 judge 標頭假象 |
| `sec4_retrieval.tex` | classifier 靜默失效註記;表 V 註路由分佈更正並加 Round 3 分佈 |
| `sec5_evaluation.tex` | benchmark 100→500(新表 + 19 家族說明);指標 13→16(verse recall、anchor coverage、zh/strict);量測陷阱 3→5(unit-level 灌水、judge 無標頭);主指標順位;A/B 基礎設施(semantic_only、include_context、500 題耗時) |
| `sec6_experiments.tex` | Round 0 表註(classifier、faithfulness 低估)、傳導說註記;P0 條件加註;演進表註;融合節末接 Round 3 |
| `sec6b_round3.tex`(新) | Round 3 全節:設定、四張表(總表、配對 CI、家族表、槽數表)、機制、雜訊地板、結論 |
| `sec7_discussion.tex` | 共同決定因素的反向(灌水);三事件→四事件(表與文);雙錨家族擴充結果;EVENT_005 修正;benchmark 處方已執行;限制、未來工作、結論更新 |
| `appendix.tex` | 引用對照表加 §XI;可重現性:路由依 classifier、round3_stats.py、可比性(Round 2 路由、classifier)、Round 3 可比性、500 題耗時 |

## 未做 / 已知限制

1. 每組態只跑一次;生成端取樣變異只用 F15 的同 context 子集估計,沒有多 seed。
2. GT 要點審計未做(313/500 題恰好 5 要點、部分要點寬於題幹)—— coverage 絕對值偏保守,組態間比較不受影響。
3. α 只在原 100 題上選過(0.3),500 題尚未重掃;anchor-confidence gating、slot quota 都還沒實作。
4. BRINK 式缺陷注入仍未做 —— graph-off 只回答「平均有沒有用」,答不了「哪些邊有用」。
