# 發現要點紀錄:重建系統上的圖譜檢索 —— 未偵測到增益(附上界)與三個失敗機制

**日期**:2026-10-18
**性質**:論文寫作素材 — 發現層級整理(延續 F10–F18,本檔為 F19–F31);供新節 `paper/latex/sec6c_rebuilt_graph.tex`(`sec:rebuiltgraph`)與 abstract、intro、Round 3、討論、附錄的改寫使用,是 .tex 新數字的**唯一**來源。每個數字在撰寫時都開啟 primary 檔逐一核對;只存在於 scratchpad、/tmp 或記憶的數字一律列入文末「引用陷阱」,不進發現。**沒有任何一項是 confirmatory**。
**數據目錄**(archived 位置只有 repo 與 store `/mnt/ollama-data/bible_rag_store`):
- 路徑縮寫:`S`＝store `reports/`;`MK`＝`S/multihop_kg_20261012/session_e73fd5d9`;`GS`＝`S/multihop_kg_20261012/session_15748325_graphsel`;`E3C`＝`S/eval3c_20261014_analysis`;`QDS`＝`S/graph_qd_20261018`;`NA`＝`S/kg_effect_eval_20261014/new82_ans`;`VS`＝`S/tmp_evidence_20261010/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/verify_stats`;`GDX`＝repo `evaluation/experiments/2026-10-14_graph_gd`;`QDX`＝repo `evaluation/experiments/2026-10-18_graph_qd`;`VA`＝repo `docs/records/2026-10-03_graph_benchmark_validity_audit.md`;`KGQ`＝`S/multihop_kg_20261012/prior_sessions/kgq_result_20261007.json`。
- 建置與知識層:store `releases/b20261008_{6daa4f31,e05d3e55}.json`、`contracts/b20261008_e05d3e55/{event_registry,query_aliases}.json`;legacy KG 稽核 store `reference/REPORT.md`(與 repo `bak/20261007_data_kg_audit/REPORT.md` 逐位相同)。
- GD(2026-10-14～15):`GDX/`(prereg.md、new82_report.json、v1_old31.json、v1_power.json、units_old31.json)、`S/graph_gd_20261014/`。
- 圖譜最後一夜(2026-10-18):`QDX/plan.md`(commit 16f9ced 登記、533b4ee 結果)、`QDS/report.json`、`QDS/step2/report2.json`、`NA/retrieval_iter.json`。
- OLD31 realkg／iterq:`MK/realkg/analysis.json`、`MK/iterq/analysis.json`;GN-41:`S/gn41_20261002/`;逐跳探針與池層:`GS/`。
- eval3c 與 Rebuild-2 閘門:`E3C/final_out/analysis.json`、`E3C/{interim,final}_report.md`、`S/r2eval/`、`S/status_audit_20261010/verification_result.json`。
- Round 3 多重比較:`S/analysis_20261010/round3_stats.out`、`VS/{multi.out,c01_03.out,vcommon.py}`。
**重算工具**:`GDX/evaluate.py`(子命令 new82／v1／units → new82_report.json、v1_old31.json、units_old31.json)、`GDX/v1_power.py`;`QDX/qd_eval.py`(report.json)、`QDX/qd_step2.py`(report2.json);`MK/realkg/analyze.py`、`MK/iterq/analyze.py`;`S/gn41_20261002/stats/analyze.py`;`E3C/analyze_eval3c_v2.py`(final_out/analysis.json);`evaluation/r1_gate.py`(R2 閘門);`python3 paper/tools/round3_stats.py`(Round 3 配對 CI;store 的 round3_stats.out 是一次封存輸出)。Round 3 的 Holm 只有輸出 `VS/multi.out` 封存,產生它的 multi.py 沒有封存(檢定函式在 `VS/vcommon.py:18`)。
**證據等級**(brief D3,只用三個標籤):「pre-registered stopping rule」＝GD V1、10-18 規則 G／O／I、多錨 QD 步驟 2;「exploratory (development set)」＝NEW82 上的一切、OLD31 上的 realkg 與 iterq;「descriptive」＝事件登錄表附加槽、逐跳探針。D3 沒涵蓋的三類,本檔的歸類見開放問題 1:GN-41 → exploratory (development set);Rebuild-2 vs Rebuild-1 → descriptive;legacy Round 3 → exploratory (not pre-registered)。凡報停止,一律寫「stopped by the pre-registered rule; this is not evidence of absence」(依事先規則停止,不構成無效證據)。
**命名**(D7):建置寫 Rebuild-1 (b20261008\_6daa4f31)、Rebuild-2 (b20261008\_e05d3e55),不寫 R1／R2(那是路由名)。結案措辭依 D10,寫「the authors' pre-run ruling」,不寫人名。

輪次命名沿用論文:Round 0–3 是 legacy Neo4j 系統;本檔的新實驗都在 Rebuild-2 的資料層上離線進行。

---

## 發現總表(F19–F31)

| # | 發現(一句話) | 論文位置 |
|---|---|---|
| F19 | 重建後知識層只剩 L0 名稱層(2,926 名)與 L1 curated 事件登錄表(31 事件),沒有身分層、關係層與 Neo4j;所有圖譜實驗都在離線檢索階段,以 LLM 撰寫、未經人工審查的多跳題集對 k 對齊非圖譜對照進行,歸因規則開跑前寫定 | `sec:rebuiltsetup`、`sec:limitations`、`app:rebuild` |
| F20 | GD(dense 種子 PPR)只在看過的 NEW82 上 @10 有正向(單位 11:0);prod 的 k=5 未偵測到增益(上界 +0.054) | `sec:rebuiltresults`、`tab:rebuiltgraph` |
| F21 | GD 在 OLD31 的事先登記方向檢查得 2:2(20 單位中不一致 4)→ 依規則停止;分數封存,沒有 Δ̄ 與 CI;停損規則在虛無下的停止機率 0.552 | `sec:rebuiltresults`、`sec:rebuiltclosure`、`tab:rebuiltgraph` |
| F22 | OLD31 上可建的圖譜臂(家譜走訪 KIN、名稱查找 L0、逐跳 IT-L0)對 k 對齊 dense 都未偵測到增益;唯一大的增益(IT-D +0.185)是非圖譜的單步查詢改寫 | `sec:rebuiltresults`、`tab:rebuiltgraph` |
| F23 | GN-41(legacy KG)上 KG 橋接名與 KG 事實對同流程 LLM 改寫都未偵測到增益;停損規則寫於生成之後,只能記 null | `sec:rebuiltresults`、`tab:rebuiltgraph` |
| F24 | 10-18 事前登記:PPR 名稱提示(QD+G)對非圖譜雙胞胎 −0.017(上界 +0.023)、對純 QD −0.019(上界 +0.013),gold 橋接名也無益,IT-GD +0.010(上界 +0.027);規則 G 未過 → 依規則停止並結案 | `sec:rebuiltresults`、`sec:rebuiltclosure`、`tab:rebuiltgraph` |
| F25 | 事件登錄表附加槽是查表、不是圖譜操作:開與關的 coverage 差 +0.0089(上界 +0.021,非 k 對齊,只觸發 23/500 題);Rebuild-2 對 Rebuild-1 沒有可量測增益 | `sec:rebuiltsetup`、`sec:rebuiltresults`(context row) |
| F26 | Round 3 graph−no-graph 經多重比較校正後是「未偵測到增益」:擴充題 anchor coverage −0.012 的未校正 p 0.013,Holm 後 0.107;只有事後選定的 MRR 勝負 12:35 在校正後仍成立 | `sec:round3`、`tab:round3paired` 註、abstract、`sec:intro`、`sec:conclusion` |
| F27 | 機制 (A)(選段):cross-encoder 只拿題目或子查詢打分,圖譜帶進池的橋接段進得了池、留不到 top-k | `sec:rebuiltmech`、`tab:rebuiltmech` |
| F28 | 機制 (B)(沒有身分層與關係層、覆蓋低):名稱合併同名者;legacy 語意邊多數是錯的;legacy KG 只覆蓋 9/104 個所需答案實體組 | `sec:rebuiltmech`、`tab:rebuiltmech`、`sec:kg` 的 legacy 註 |
| F29 | 機制 (C)(圖譜特有空間小、與非圖譜通道重疊、贏家詛咒):102 個缺跳中只有約 6 個只靠圖譜拿得到;含 LLM 改寫的圖譜臂勝過 dense 的部分都由非圖譜雙胞胎重現;設定在看過的開發集上挑出,11:0 → 2:2 | `sec:rebuiltmech`、`sec:rebuiltclosure` |
| F30 | QD(LLM 子查詢改寫)是非圖譜的 context row:NEW82 上 +0.101(探索性);GT v2 多錨 +0.0174 未過事先門檻,該線停止;盲集確認未做 | `sec:rebuiltresults`(context row)、abstract 至多一個子句 |
| F31 | 量測限制:500 題 benchmark 只能測傷害;多跳題集由 LLM 撰寫且未經人工審查;每臂只生成一次;部分 CI 是題層級、未群聚 | `sec:rebuiltsetup`、`sec:limitations` |

---

## F19|重建後的知識層與測試設定

- **主張**:Rebuild-2 的知識層只剩 L0 名稱層與 L1 curated 事件登錄表(無身分層、無關係層、無 Neo4j);新的圖譜檢索實驗全部在離線檢索階段,以 LLM 撰寫的多跳題集對 k 對齊的非圖譜對照比較,「什麼算圖譜操作」在開跑前寫定。
- **證據等級**:descriptive(設定描述)。
- **量化證據**:
  - **建置**:Rebuild-1＝`b20261008_6daa4f31`、Rebuild-2＝`b20261008_e05d3e55`(store `releases/*.json` 的 `build_id`)。兩者 `kg_enabled=false`、`layers.identity=null`、`layers.relations=null`,kg0 同為 `kg0@14e68c8344b1`(同檔 `kg_enabled`、`layers`)。
  - **L0 名稱層**:2,926 個名稱(`releases/b20261008_e05d3e55.json` `counts.names`;Rebuild-1 同)。
  - **L1 事件登錄表**:31 個事件(`counts.events`;Rebuild-1 是 33)。契約檔 `contracts/b20261008_e05d3e55/event_registry.json`:`events` 31 筆、`retired` 2 筆、錨點 179 個(`events[*].anchors` 計數),`provenance_class` 為 `curated_human`。
  - **沒有 Neo4j**:`backend/config.py:11-14`(`GraphStrategyName = Literal["event_registry"]`;註解寫 Neo4j 策略隨重建全數移除);`docs/records/2026-10-09_r1_r2_rollout.md:11`(legacy 資料、容器、Neo4j 全刪)、`:13`(P5 取消:KG 停在 L0＋L1,身分層與關係層不做)。
  - **語料與別名**:2,773 段、34,058 筆 embedding 記錄(`releases/b20261008_e05d3e55.json` `counts.passages`、`counts.embedding_records`);query_aliases 只有 17 條(`contracts/b20261008_e05d3e55/query_aliases.json` `aliases`)。
  - **GD 圖(D7)**:無權二部圖,2,773 個段節點 × 2,929 個本文名稱節點、16,616 條邊,635 段沒有任何名稱(`S/graph_gd_20261014/new82/lists.json` `meta.graph`;old31/lists.json 相同;定義見 `GDX/prereg.md:45`:名稱節點是 `name_spans.jsonl` 中 region＝body 的 norm_key,不連 split_passage_ids)。2,929 與 L0 的 2,926 來源不同(name_spans 的 body norm_key vs kg0 names),寫 GD 圖用 2,929,寫 L0 用 2,926。
  - **檢索階段**:主機 float64 精確 cosine 於 34,058 筆 BGE-M3 記錄,段分數取記錄最大值(`GDX/prereg.md:41`);prod bge-reranker-v2-m3,整段送入、max_length 512,查詢＝題目(GD)或子查詢(QD、IT)(`GDX/prereg.md:43`;`QDX/plan.md:21`);不含 R2 路由、book_anchor、事件槽(`GDX/prereg.md:17,20`)。
  - **歸因規則(D9,開跑前)**:`QDX/plan.md:9`(§0-3)「LLM 子查詢本身不算圖譜;圖譜臂必須同時贏 DEEP@6 與非圖譜雙胞胎 QD+N;PPR 或兩跳以上才算圖譜操作,一跳查表只描述」。plan 先 commit(16f9ced)才開跑(`QDX/plan.md:3,81`)。
  - **題集**:
    - NEW82:90 份草稿保留 82 題(退件 1、去重 7),223 跳(2 跳 36、3 跳 34、4 跳 11、5 跳 1;`MK/README.md:4-5`;`MK/newq/questions_v5.json` 計數),8 類 DIS 14、KIN 13、TO 12、SUC 11、OQ 11、NULL 9、BRL 8、BRP 4(同檔 `questions[*].category` 計數);獨立稽核 ok 33、minor 33、major 11、critical 5(`MK/README.md:4`)。相對 D5≈ 缺跳 102 跳、分布在 63 題;40 個 union-find 單位、最大 12 題(`GDX/new82_report.json` `missing_hops.by_set.new82`、`units`)。
    - OLD31:OLD38 中凍結 prod D5 至少缺一跳的 31 題(`GDX/prereg.md:29`),101 跳、相對 prod D5 缺跳 58、附加段總數 Σm＝49(`MK/realkg/analysis.json` `retrieval_vs_answer.summary.{hops_total, missing_hops_total, appended_total.ORACLE}`);20 個單位、最大 9 題;16/31 題與 NEW82 共用 gold 段(`GDX/units_old31.json` `n_units`、`max_unit`、`shares_gold_with_new82`)。
    - GN-41:legacy Neo4j KG 上的 41 題:title-bridge 13、disambiguation 11、kinship 2-hop 8、aggregation 9(`S/gn41_20261002/gn_dev.json` `category` 計數;`stats/stats.json` `meta.n_items`)。
    - GT v2 多錨:500 題中參考經文 >1 的 204 題(`QDX/plan.md:62`;`QDS/step2/report2.json` `meta.n`)。
  - **指標**:每題全跳覆蓋率 f(q)＝(1/H)·Σ_h 1[gold_h∩top-k≠∅](`GDX/prereg.md:73`);缺跳＝gold 不在 D5≈ 的跳(`GDX/prereg.md:75`);QD 類臂每題取 3 次拆解平均(`QDX/plan.md:41`)。
  - **統計**:群聚單位＝共用 gold 段的 union-find 連通元件,Δ̄＝單位值平均(含 0),精確雙尾群聚 sign-flip,以單位做 percentile bootstrap 10,000 次、seed 20261014(`GDX/prereg.md:80-83`;`QDX/plan.md:41`)。realkg／iterq:題層級 bootstrap 10,000 次(seed 20261013／20261014)、sign test＋精確 Wilcoxon、Holm(`MK/realkg/analysis.json` `meta`;`MK/iterq/analysis.json` `meta`)。GN-41:題層級 paired bootstrap B＝10,000、seed 20260930(`stats.json` `meta`)。eval3c:題層級,sign-flip 20,000＋bootstrap 10,000、seed 20261014,主比較 Holm m＝3(`E3C/final_out/analysis.json` `meta.cfg`、`primary_holm`)。
  - **LLM 撰寫與評分(D13)**:NEW82、OLD31 的母體是「Claude 合成、並經多跳必要性篩選的題」(`GDX/prereg.md:21`)。NEW82 審題頁標「待審」(`MK/README.md:2`);期中報告記錄審題頁 db 的 reviews 集合為 0 筆(`E3C/interim_report.md:331`;本紀錄未重查,需呼叫 HTTP)。GN-41 由 Claude Code session 內的出題代理撰寫(`S/gn41_20261002/author-A/finalize.py:2` 等腳本路徑指向該 session 的 scratchpad)。OLD31 的答案由兩位 Claude 評分者盲評(`E3C/interim_report.md:164`),κ_linear 0.98(`MK/realkg/analysis.json` `reliability.final.kappa_linear`＝0.9815)——這是評分者一致性,不是效度。
  - **生成**:QD 拆解器用 prod LLM `gemma4:e4b-it-q8_0`、T＝0(`QDX/plan.md:19`);realkg／iterq 每(題,臂)生成 3 次 × 2 位評分者取平均(兩份 analysis.json 的 `meta.score`)。
- **注意**:新實驗都是離線檢索階段,絕對水準不是 prod 水準(`GDX/prereg.md:20`);GD 與 QD 只量檢索層,沒有答案層(`GDX/prereg.md:122-125`)。
- **建議章節**:`sec:rebuiltsetup`(設定、題集、指標、歸因規則);`sec:limitations`(LLM 撰寫);`app:rebuild`(知識層計數)。
- **文獻掛鉤**:GD 的 PPR 與 HippoRAG 2(`gutierrez2025hipporag2`)屬同一運算子家族,但不是重現。

## F20|GD 在開發集 NEW82:只有 @10 有正向,prod 的 k=5 未偵測到增益

- **主張**:在看過的開發集 NEW82 上,GD 只在 k=10 對 k 對齊的 dense-30 對照 C 有正向訊號;在 prod 的 k=5 未偵測到增益(上界 +0.054),而且增益依賴 PPR 對名稱密集段的偏好。
- **證據等級**:exploratory (development set)。
- **量化證據**(`GDX/new82_report.json`;82 題、40 單位):
  - 設定:池＝dense 前 20 ＋ 不在其中的 PPR 前 10(種子＝dense 前 10、權重 1/rank、restart 0.5、40 次);C＝dense 前 30;同一 reranker 取 top-k(`S/graph_gd_20261014/new82/lists.json` `meta.params`:n_base 20、n_extra 10、n_seeds 10、ppr_alpha 0.5、ppr_iters 40;`GDX/prereg.md:48-51`)。
  - GD−C@10:單位 11:0,Δ̄ +0.063 [+0.028, +0.104],精確 p＝1/1024(`hypotheses.H1`);平均 f@10 0.712 vs 0.651,缺跳命中 31 vs 17(/102)(`metrics['@10']`)。
  - GD−C@5(prod 的 k):單位 8:2,Δ̄ +0.020 [−0.015, +0.054],p＝69/256(`hypotheses.H2`);平均 f@5 0.603 vs 0.570,缺跳命中 14 vs 7(`metrics['@5']`)。**上界 +0.054**。
  - GD−D20@5(只用 dense 前 20 的池):Δ̄ +0.005 [−0.026, +0.034](`E3C/interim_report.md:78`,T12)。
  - 對字面通道 @10:GD−LEXPRF 10:1、+0.050 [+0.009, +0.094]、p＝13/512;GD−BM25 10:2、+0.052 [+0.010, +0.098]、p＝49/2048;H3 取兩者較大 p＝0.0254>0.025,即使 H1 成立也過不了 Holm(`hypotheses.H3`)。字面通道本身對 C:L−C@10 5:3、+0.011 [−0.021, +0.044];LEXPRF−C@10 5:2、+0.013 [−0.013, +0.043](`descriptive`)。
  - 去掉度數偏好:GD_DEGNORM−C@10 7:4、+0.006 [−0.030, +0.045];@5 7:2、+0.019 [−0.014, +0.053](`descriptive`)。
  - 名稱種子版 G:G−C@10 7:1、+0.024 [−0.006, +0.056];GD−G@10 6:1、+0.039 [+0.007, +0.078](`descriptive`)。
  - 事後挑選與已看過:GD 是從約 10 組設定中事後挑出的(`GS/README.md:10`);NEW82「只當探索集」(`GDX/prereg.md:34`);檢索是決定性的:兩條打分路徑 648 對最大差 9.24e−7(`GS/wf/final_merge/gd_vs_lexprf.json` `determinism['ev~at']`),驗收 B 逐題 top-k 820/820 相同(`GDX/prereg.md:151`)。
- **注意**:依 D5,**不得**把 @10 的 CI [+0.028, +0.104] 當上界(不含 0、又是事後挑選);論文的 GD 上界用 @5 的 +0.054(exploratory)。H2 依 prereg 只在 H1 確認後才檢定,所以 @5 的 p 只作描述。
- **建議章節**:`sec:rebuiltresults`、`tab:rebuiltgraph`。
- **文獻掛鉤**:`gutierrez2025hipporag2`(PPR 選段);`xiang2025whengraphs`(圖譜何時有幫助)。

## F21|GD 的事先登記方向檢查(OLD31 V1):2:2,依規則停止

- **主張**:GD 在 OLD31 上的事先登記方向檢查得到單位 2:2(20 個單位中只有 4 個不一致),觸發停損;依事先規則停止,不構成無效證據;分數依登記封存,沒有 Δ̄ 與 CI。
- **證據等級**:pre-registered stopping rule。
- **量化證據**:
  - V1 結果:`GDX/v1_old31.json` `n_units` 20、`unit_W:L` "2:2"、`discordant_units` 4、`stop` true;規則「20 個單位中不一致 ≥3 且負 ≥勝 → 結案」(同檔 `rule`;`GDX/prereg.md:96`)。
  - 登記措辭:「方向檢查未過,依事先規則停止,不構成無效證據(OLD31 單位 W:L＝2:2)」(`GDX/prereg.md:99,171`)。
  - 停損規則的操作特性(單位層級、不一致率 r＝0.222、200,000 次模擬):P(stop | 單位勝率 0.5)＝0.552,P(stop | 0.7)＝0.190,P(stop | 0.8)＝0.072(`GDX/v1_power.json` `v1_oc['r=0.222,pwin=0.5'|'r=0.222,pwin=0.7'|'r=0.222,pwin=0.8'].unit['P_stop(d>=3,l>=w)']`;`GDX/prereg.md:153`)。
  - 若未停損,計畫中的完整程序(HO 120 題＋OLD31)在單位勝率 0.8 時拒絕虛無的機率 0.825、0.75 時 0.653、虛無下 0.024(`v1_power.json` `procedure['r_ho=0.17,r_old=0.221,pw=0.8'|'…pw=0.75'|'…pw=0.5'].reject`)——沒有執行。
  - 執行品質:31 題、1,847 對重排;結尾 refcheck 32 對 max|Δ| 0;前 18 題重打 1,078 對 max|Δ| 0(`S/graph_gd_20261014/README.md`;`GDX/prereg.md:168-169`)。原始分數依 §6 封存、未讀(`GDX/prereg.md:171`)。
  - 沒做的:HO 0 題、E2 與 E3 未跑,答案層從未量(`GDX/prereg.md:171`;`S/graph_gd_20261014/README.md`;new82_ans 在生成前就停,`E3C/interim_report.md:363-371`)。結案後不再開新的單發圖譜變體(`GDX/prereg.md:171`)。
- **注意**:OLD31 只部分盲——GD 的種子型態是在 OLD31 池層結果出來之後選的(`E3C/interim_report.md:350-352`),16/31 題與 NEW82 共用 gold 段(F19),OLD31 也已用於 realkg、iterq 與逐跳探針。停損在虛無下有 55% 的機率發生,所以 2:2 只是反對「大效果」的弱證據。依 D5,論文**不報** OLD31 的 Δ̄ 或 CI,只報 W:L、不一致數與操作特性。
- **建議章節**:`sec:rebuiltresults`、`sec:rebuiltclosure`、`tab:rebuiltgraph`。

## F22|OLD31 上可建的圖譜臂(KIN、L0、IT-L0)都未偵測到增益

- **主張**:在 OLD31 上,用現況資料可建的圖譜臂(家譜 1–2 跳走訪 KIN、名稱查找 L0、逐跳流程中的名稱層 IT-L0)對 k 對齊的 dense 都未偵測到答案層增益;OLD31 上唯一大的增益來自非圖譜的單步查詢改寫。
- **證據等級**:exploratory (development set)。
- **量化證據**(31 題、題層級;分數＝2 位 Claude 評分者 × 3 次生成的 final_correct 平均;k＝D5＋m):
  - KIN−DK:−0.005 [−0.065, +0.048],W:T:L 3:26:2,sign p 1.0,MDE80 0.085(`MK/realkg/analysis.json` `results.both_raters.primary.KIN_vs_DK`)。
  - L0−DK:+0.016 [−0.065, +0.102],4:24:3,精確 Wilcoxon p 0.828,MDE80 0.121(`…primary.L0_vs_DK`)。
  - 臂平均(各比較的 `mean_x`／`mean_y`,與 `arm_table.*.final` 一致):D5 0.091、DK 0.134、KIN 0.129、L0 0.151、ORACLE 0.481、FACTS 0.637。
  - 上限診斷(不是方法):ORACLE−DK +0.347 [+0.210, +0.497],sign Holm 3.8e−4;FACTS−DK +0.503 [+0.349, +0.645](`…secondary.ORACLE_vs_DK`、`…secondary.FACTS_vs_DK`)。
  - 逐跳 IT-L0−IT-D:−0.105 [−0.234, +0.011],3:18:10,sign p 0.092,精確 Wilcoxon p 0.099,MDE80 0.179;事先規則判 (c),`decision.criteria.primary_IT-L0_lt_IT-D`＝false(`MK/iterq/analysis.json` `results.both_raters.primary['IT-L0_vs_IT-D']`、`decision`)。臂平均 IT-D 0.323、IT-L0 0.218(同欄 `mean_y`、`mean_x`)。**上界 +0.011**。
  - 非圖譜對照:IT-D−DK +0.185 [+0.054, +0.331],11:16:4,精確 Wilcoxon p 0.020、Holm 0.123(`…secondary['IT-D_vs_DK']`);約 80% 來自只需附加 1 段(m＝1)的 18 題,屬依 context 的單步查詢改寫,不是多步迭代,也不是圖譜(`E3C/interim_report.md:89`,T23)。
- **注意**:KIN 的三元組來自 session 原型 `MK/multihop/kin_extract.py`,不是 production 層;L0 對應 production 的 kg0 名稱層。OLD31 以 prod 失敗為入選條件,基線偏低。CI 是題層級,而 OLD31 有一個 9 題的群(`GDX/units_old31.json` `max_unit`),題層級 CI 可能偏窄(群聚重算只存在 scratchpad,見引用陷阱)。IT-L0 寫「null,方向偏負」,不寫「較差」(`E3C/interim_report.md:381`)。
- **建議章節**:`sec:rebuiltresults`、`tab:rebuiltgraph`;IT-D 列見 F30。

## F23|GN-41(legacy KG):KG 橋接與 KG 事實都未勝過同流程 LLM 改寫

- **主張**:在 legacy Neo4j KG 上的 41 題,把 KG 橋接名加進查詢(C3)或把 KG 事實交給生成器(C5),對同一流程的 LLM 查詢改寫(C2)都未偵測到增益;唯一寫有停損規則的檔案晚於生成,所以只能記 null。
- **證據等級**:exploratory (development set)(legacy 系統)。
- **量化證據**(`S/gn41_20261002/stats/stats.json` `paired.*.key_score`;41 題、題層級、key_score;top_k 5 見 `S/gn41_20261002/run/common.py:29`):
  - C3−C2:−0.004 [−0.035, +0.026],W:L:T 2:3:36,p 0.805。**上界 +0.026**。
  - C5−C2:+0.018 [−0.026, +0.081],2:2:37,p 0.532。**上界 +0.081**。兩個主比較的 Holm 調整後 p 都是 1(`holm_primary`)。
  - C1−C0(legacy graph 開 vs 關):−0.024 [−0.073, +0.012](`paired.C1_vs_C0`)。
  - 對照:C4−C2(oracle 名稱)+0.059 [+0.012, +0.112],7:1,p 0.0094(次要、未校正;`paired.C4_vs_C2`)。
  - 飽和:C0 key_score 0.866、keys_in_context 0.959(`means.C0.ALL`)。
  - 停損規則的時序:唯一含規則的 `stats/analyze.py:95-112` 修改於 2026-10-02 21:36:47,晚於 `run/generation.jsonl`(21:26:26)與 `run/progress.log`(21:31:05);`run/plan.json`(20:42:11)沒有任何 stop／go 鍵(檔案 mtime;裁決見 `E3C/interim_report.md:380`)。
- **注意**:legacy 系統。stats.json 雖寫 `decision: "STOP"`,論文寫「null; its stop rule was written after generation」,不寫事先登記的停止。CI 用 95%,不用 Holm 層級的 97.5%(見引用陷阱)。覆蓋數字見 F28。
- **建議章節**:`sec:rebuiltresults`、`tab:rebuiltgraph`(標 legacy KG)。

## F24|2026-10-18 事前登記:QD+G、QD+N、QD+ORACLE、IT-GD

- **主張**:把 L0 圖上 PPR 排出的名稱寫進 LLM 子查詢 prompt(QD+G),對同一 prompt 改用非圖譜名稱的雙胞胎(QD+N)與不加名稱的 QD 都沒有增益、方向偏負;寫進合格的 gold 橋接名也無益;逐跳加 PPR 候選(IT-GD)只有 +0.010;規則 G 未過,依事先規則停止,現況圖譜層的檢索變體結案。
- **證據等級**:pre-registered stopping rule(規則 G／O／I;資料是開發集 NEW82)。
- **量化證據**(`QDS/report.json`;NEW82 82 題、40 單位、最大 12 題;k＝6＝C5＋1 段;QD 類臂 3 次拆解平均):
  - 臂(`QDX/plan.md:23-30`):DEEP@6＝題目的 dense 前 50 中不在 C5 的段,reranker 以題目取第一,不用 LLM;QD＝gemma4 依題目＋C5 寫一個子查詢;QD+G＝prompt 加一行 5 個名稱,名稱由 C5 種子 PPR 在 L0 二部圖上排段後套共用名稱公式;QD+N＝同模板,名稱改由題目的 dense 排名產生(非圖譜雙胞胎);QD+ORACLE＝合格的 gold 橋接名(診斷)。
  - G1 QD+G−QD+N:單位 6:8(不一致 14),−0.017 [−0.060, +0.023],題 W:L 11:15,描述性 p 0.449(`primary.G1`)。**上界 +0.023**。
  - G2 QD+G−DEEP:16:2,+0.082 [+0.038, +0.131](`primary.G2`)——非圖譜雙胞胎 QD+N−DEEP 也是 18:2、+0.099 [+0.050, +0.150](`descriptive['QD+N−DEEP']`)。
  - G3 QD+G−QD:6:10(不一致 16),−0.019 [−0.050, +0.013],描述性 p 0.269(`primary.G3`)。**上界 +0.013**。
  - 規則 G:G1 未過、G2 過、G3 未過 → 未過(`verdicts.G`);依事先規則停止,不構成無效證據(`QDX/plan.md:45,104`)。
  - O QD+ORACLE−QD:5:4,−0.008 [−0.027, +0.008];只有 24/82 題有合格名稱(`primary.O`;`verdicts.O.n_questions_with_oracle_names`)→ 未過。**上界 +0.008**。
  - I IT-GD−IT-D@7(C5＋2 步):單位 2:0,+0.010 [0.000, +0.027];72/82 題最終 context 相同(`NA/retrieval_iter.json` `comparisons['IT-GD−IT-D']`、`subqueries.questions_same_final_context`;`QDS/report.json` `verdicts.I`)。**上界 +0.027**。I 規則本身不觸發結案;依開跑前的 §0-2 裁決一併結案(`QDX/plan.md:106`)。
  - 平均 f(q)@6:C5 0.570、C6 0.594、DEEP 0.581、QD 0.685、QD+G 0.665、QD+N 0.684、QD+ORACLE 0.685(`arms.*.mean_f`);缺跳命中(/102,每次):QD 28/30/30、QD+G 28/26/26、QD+N 27/30/30、QD+ORACLE 31/30/30、DEEP 8、C5 7(`arms.*.missing_hops_hit_per_rep`)。
  - 單項門檻(W≥2L 且 W−L≥4)的通過率:虛無(單位勝率 0.5)下 .06–.19,勝率 0.8 時 .41–.93,依不一致單位數 D 而定(`QDX/plan.md:51-56`);G1 的 D＝14,介於表中 D＝12 與 16 之間(勝率 0.8 時 .93／.92、虛無下 .19／.11),所以 G1 的 W<L 不是「差一點」。G3 不用單項門檻,只要求 Δ̄>0 且 W>L(`QDX/plan.md:45`)。
  - 基礎設施:四臂 fallback 各 0/246、IT 拆解 0/168;refpairs 在開跑前、步驟 1 後、步驟 2 後都是 32 對 max|Δ| 0;無作廢臂(`QDX/plan.md:84-85`;`QDS/report.json` `verdicts.K`、`verdicts.I.K`;`QDS/step2/report2.json` `K`)。3 次拆解完全相同的題:QD 35、QD+G 35、QD+N 37、QD+ORACLE 35(/82)(`verdicts.K.identical_reps`)。
  - 種子(D12):QD+G 以 C5 段為種子(`QDX/plan.md:27`);IT-GD 每步以子查詢 s_t 的 dense 前 10(權重 1/rank)為種子,**不是** C5(`NA/plan.md:20`;`QDX/plan.md:106` 已在工作樹更正,撰寫時尚未 commit)。
- **注意**:NEW82 是看過的開發集,plan 明言即使過關也只算探索性(`QDX/plan.md:13`)。看過 6 題(N_BRL_01–06)的 G／N 名稱清單後改了名稱公式,當時未算任何 f(q)(`QDX/plan.md:33,36`)。結案範圍依 D10:實測的是 L0 名稱–段落圖(GD、QD+G、IT-GD);L1 事件登錄表與 kin 表層三元組先前已量過(eval3c 附加槽、realkg 的 KIN),依作者群的開跑前裁決一併結案(`QDX/plan.md:8`);重開需要新的圖譜層(例如實體身分、可靠的關係)與新的事前登記。
- **建議章節**:`sec:rebuiltresults`、`sec:rebuiltclosure`、`tab:rebuiltgraph`。

## F25|事件登錄表附加槽(查表,非圖譜操作)與 Rebuild-2 vs Rebuild-1

- **主張**:Rebuild-2 線上唯一的知識層觸點是 curated 事件查表附加槽,開與關在 500 題上的 coverage 差未偵測到(上界 +0.021,非 k 對齊,只觸發 23/500 題);Rebuild-2 相對 Rebuild-1 也沒有可量測的檢索或答案增益。
- **證據等級**:descriptive(D8)。
- **量化證據**:
  - 機制:字面觸發詞查表,在已完成的 top-k 之後最多附加 1 個錨點、不參與排序(`backend/config.py:11-14,88-94`);選的是「核心沒有的第一個錨點」,不看題意,eval3c 報告因此把它改名為事件登錄表查表附加槽、不計入圖譜價值(`E3C/final_report.md:155`)。
  - eval3c 三臂(GT v2 500 題、每臂生成一次):平均 coverage full 0.697、nokg 0.688、sem 0.665(`E3C/final_out/analysis.json` `means_common`)。
  - 開 − 關(full−nokg):coverage +0.0089 [−0.0030, +0.0207],W:T:L 118:290:92,sign-flip p 0.137(＝Holm,m＝3),觀察 MDE 0.0168;473/500 題兩臂 context 相同;0.02 的非劣性界成立;觸發題讀 6 段、其餘 5 段,非 k 對齊(`verdicts.KG['KG-ALL']`)。**上界 +0.021**。
  - 觸發:23/500 題(`pairs['full-nokg'].metrics.coverage.members.aux.touched_full`);觸發詞 15 題是外部別名、8 題是 PDF 標題(`E3C/final_sp/adjudicate/trig_out.json` `kind` 計數),15/23 的外部別名是依同一份 GT 調出來的(`E3C/final_report.md:96`)。
  - 觸發的 23 題:coverage +0.053 [−0.040, +0.163],11:6:6,p 0.365,觀察 MDE 0.155(`verdicts.KG['KG-TOUCHED']`)。k 對齊檢索(附加 1 段 vs dense 第 6 段):vrec +0.163 [+0.069, +0.266],12:10:1,KG 族 Holm 0.0049(`verdicts.KG['KG-RETR']`)——樣本內、查表,不是圖譜證據。
  - 需要知識的子集(full−nokg):kg_strong(84 題)+0.008 [−0.019, +0.035];complex_union(51 題)−0.021 [−0.055, +0.013](`pairs['full-nokg'].metrics.coverage.stats.kg_need`)。
  - NEW82:full 與 nokg 的核心 top-k 在 @5、@10 都 82/82 相同,f(q) 差 0;附加槽只觸發 1/82 題(`E3C/mh3/summary.json` `comparisons['full_k5 - nokg_k5']`、`['full_k10 - nokg_k10']`;`E3C/mh3/summary.md:11`)。
  - 對照(非圖譜):管線對 semantic +0.032 [+0.012, +0.053],Holm 0.006,全部來自明寫引用題:R1/R2 路由 179 題 +0.092 [+0.048, +0.138],其餘 321 題 −0.002 [−0.020, +0.017](`verdicts['PIPE:full-sem']`;`pairs['full-sem'].metrics.coverage.stats.route_a`)。
  - 沒看過的事件題(G-HELDOUT):61 題只觸發 13 題,低於登記下限 30,只能描述;精確率 11/13＝0.846、召回 11/43＝0.256(`S/r2eval/gate_heldout.json` `arms.R2`、`criteria`;下限見 `evaluation/experiments/2026-10-09_r2/prereg.md:99-100`)。
  - Rebuild-2 vs Rebuild-1(Rebuild-2＝事件登錄表修正版＋PDF 路由詞表,`evaluation/experiments/2026-10-09_r2/prereg.md:1`;事件 33→31、routing_terms 348→3,298,兩份 releases 的 `counts`):Δvrec@6 +0.0002 [−0.0016, +0.0026]、ΔMRR −0.0012 [−0.0041, +0.0012],非劣性界 −0.02 通過(`S/r2eval/gate_retrieval.json` `criteria.C1`、`criteria.C2`);top-k 只有 24/500 題改變(A/A 4/500)(`S/status_audit_20261010/verification_result.json` EVL-1)。答案層(200 題):coverage +0.0019 [−0.0138, +0.0172],小於 A/A 漂移 +0.0149 [−0.0002, +0.0305];只有 13/200 題的檢索輸入不同(`S/r2eval/gate_answer.json` `report_only.coverage`;EVL-4)。**上界 +0.0026(vrec@6)**。
- **注意**:GT v2 500 題是開發集(觸發詞、路由、融合都在上面調過);沒有答案層 k 對齊比較;CI 只涵蓋題目抽樣,不涵蓋 run 層級漂移(F31)。R2 閘門是事先登記的非劣性,沒有登記優越性。
- **建議章節**:`sec:rebuiltsetup`(L1 的角色)、`sec:rebuiltresults`(context row,不進圖譜演算法列);`app:rebuild`。

## F26|Round 3 的多重比較更正:未偵測到增益,附上界

- **主張**:legacy Round 3 的 graph−no-graph 應寫成「未偵測到增益」並附 CI 上界;擴充題 anchor coverage −0.012 的未校正 p 0.013 在 8 個檢定的 Holm 校正後是 0.107,只檢索重跑也只有 p 0.060;方向一致的傷害只有事後選定的 MRR(第一個 gold 名次)勝負數在校正後仍成立。
- **證據等級**:exploratory (not pre-registered)(legacy;D3 未涵蓋,見開放問題 1)。
- **量化證據**:
  - 設計:擴充題 n＝399(排除 VERSE_LOOKUP_035)、題層級、k＝5、每組態生成一次、bootstrap B＝10,000、seed 20260930(`S/analysis_20261010/round3_stats.out:42`;`paper/record/2026-10-02_round3_expanded_benchmark_findings.md:5`)。
  - 擴充題 graph−no_graph(`round3_stats.out:61-66`):hit −0.005 [−0.018, +0.008];verse recall −0.009 [−0.019, +0.001];anchor coverage@5 −0.012 [−0.023, −0.003];MRR −0.015 [−0.028, −0.002];context recall −0.012 [−0.023, −0.003];answer coverage −0.014 [−0.029, +0.001]。
  - 全體 499 題:hit +0.002 [−0.012, +0.016](`:43`);anchor −0.005 [−0.016, +0.007](`:45`);coverage −0.012 [−0.027, +0.002](`:48`)。原 100 題(樣本內):hit +0.030 [−0.020, +0.080](`:52`)。
  - 上界:擴充 coverage +0.001、擴充 anchor −0.003、擴充 hit +0.008、全體 hit +0.016、原 100 題 hit +0.080(同上各行)。
  - Holm(D4 的家族＝{hit, verse recall, anchor coverage@5, MRR} × {全體 499, 擴充 399} 的 8 個 sign-flip 檢定;100,000 次翻轉、seed 7,`VS/vcommon.py:18`):擴充 anchor 原始 p 0.0134 → Holm 0.107;擴充 MRR 0.026 → 0.1822;擴充 verse recall 0.092 → 0.5523;其餘 Holm 皆為 1(`VS/multi.out:17-25`)。
  - 只檢索重跑(2026-10-03):擴充 anchor −0.0103,W/L 9/18,p 0.060,CI [−0.0215, +0.0001](`VS/multi.out:14`;`VS/c01_03.out:14`)。
  - MRR 勝負(sign test):擴充 12:35,p 0.0011(`VS/multi.out:7`);全體 19:42,p 0.0044(`:3`);重跑擴充 13:32,p 0.0066(`:15`)。依 `multi.out:1-8` 的 sign 欄對同一 8 個檢定做 Holm,兩個 MRR 列仍 <0.05(論文只寫「survives Holm over the same 8 tests」,不寫調整後數值,見引用陷阱)。這個統計量是 2026-10-03 稽核在看過 Round 3 結果之後才選的(Round 3 沒有事先登記;`VA:74,86`),論文要明說。
- **注意**:D4 —— 不加 151 題 context-changed 事後子集;不新增任何 NDCG 引用。Round 3 跑在 legacy Neo4j、serving 端 tokenization 不一致與有損語料轉換之下(論文 `appendix.tex:171,177` 已說明),不能和重建後的數字直接比較。引用 Holm 用 `\cite{holm1979}`(由 orchestrator 加入 refs.tex)。
- **建議章節**:`sec:round3`(結果段與 `tab:round3paired` 註)、abstract、`sec:intro`(貢獻 6)、`sec:conclusion`。
- **文獻掛鉤**:`holm1979`(多重比較);`zeng2025unbiased`(GraphRAG 增益的無偏評估)。

## F27|機制 (A):選段 —— 橋接段進得了池,留不到 top-k

- **主張**:prod cross-encoder 只拿題目或子查詢對段落打分,所以圖譜帶進候選池的橋接段多半分數很低,進得了池卻很少留到 top-k;把圖譜訊號加進選段反而更差。
- **證據等級**:exploratory (development set)(realkg、NEW82 池層);descriptive(逐跳探針)。
- **量化證據**:
  - OLD31 realkg(缺跳 /58):L0 池涵蓋 37 → 選後 8;KIN 池 17 → 選後 6;k 對齊 dense(DK)選後 8(`MK/realkg/analysis.json` `retrieval_vs_answer.summary.missing_hops_hit`)。
  - NEW82 GD(缺跳 /102):GD 池涵蓋 59 vs C 池 35(題 W:L 23:1)(`GS/wf/probe_newq/ppr_sensitivity.json` `['S1 | dense seeds only']`);重排後 @10 31 vs 17、@5 14 vs 7(`GDX/new82_report.json` `metrics['@10'|'@5']`)。
  - OLD31 逐跳探針(49 步、58 缺跳;固定 IT-D 子查詢):所有圖譜擴展池選後命中 21–22/58,同大小 dense 對照也是 21–22;由圖譜擴展帶進、最後被選中的 gold 在所有組態都是 0;IT-D 的 dense 池已涵蓋 37/58 卻只選中 21,同一池完美挑選可達 35(`GS/workflow_result.json` `result.evidence.probe_old31.summary` 第 2、5 點;明細 `GS/wf/probe_old31/report.out`)。
  - 橋接 gold 的 reranker 分數(以子查詢打分):mal.1.1 排 20/20(0.0009)、col.4.7 16/20(0.0049)、luk.1.26 17/19(0.0009)、1ki.16.15 15/21(0.011)(同上 summary 第 2 點)。PPR 帶進的 21 筆橋接 gold(16 步、14 跳)中,只有 1 跳的 gold 分數高過該步最佳 dense 候選(`GS/wf/arch/cf3.json` `summary`);21 筆 gold 分數中位數 0.013、最佳 dense 中位數 0.417、9/21 低於 0.01(本紀錄直接由同檔 `rows[].gold_score`、`rows[].best_dense` 計算)。
  - 把圖譜訊號放進選段:RRF(RR,PPR) 19、RRF(RR,NAMES) 14,都低於只用 reranker 的 21(`GS/workflow_result.json` `result.evidence.probe_old31.summary` 第 3 點)。
  - IT-GD 步驟紀錄(NEW82,164 步):PPR 額外段(共 1,640 段)在 23 步含有 IT-D 池沒有的新跳 gold,但 reranker 只選了 10 次 PPR 段,其中 2 次命中新跳(`NA/retrieval_iter.json` `steps['IT-GD'].all_steps`:`ppr_only_new_hop_gold`、`chosen_from_ppr`、`chosen_from_ppr_hits_new_hop`、`ppr_extra_size_total`)。
- **注意**:分數低的說法限於逐跳子查詢情境,寫「多在 10^−3–10^−2、排在池底附近」,不寫一般性的「≈0.001」(D6)。legacy Round 3 是鏡像:錯的圖譜錨點有字面重疊就被 reranker 放行(F13,2026-10-02 紀錄)。
- **建議章節**:`sec:rebuiltmech`、`tab:rebuiltmech`。
- **文獻掛鉤**:`gutierrez2025hipporag2`(PPR 直接排段,不經題目導向的 cross-encoder 篩選)。

## F28|機制 (B):沒有身分層與關係層,覆蓋低

- **主張**:名稱層把同名的不同人合成一個節點,legacy KG 的語意邊多數是錯的,legacy KG 對所需答案實體的覆蓋也很低,所以圖譜能提供的「正確橋接」本來就少。
- **證據等級**:descriptive。
- **量化證據**:
  - Rebuild-2:`layers.identity=null`、`layers.relations=null`(F19);GD 圖的名稱節點是表層 norm_key,同名者合併(`GDX/prereg.md:45`);query_aliases 只有 17 條(F19)。
  - 在重建文字層上做的家譜原型(範圍 gen、rut、1–2 sa、1–2 ki、1ch 1–9、mat 1、luk 3):622 個有父母的子女中,163 個(26.2%)對到 ≥2 個父親型父母(`MK/multihop/stats.json` `scope.children_with_parent`、`scope.children_with_ge2_fatherlike_parents`、`scope_def`);1,384 條兩跳鏈中 801 條跨段,其中 703 條經過這種多父母的中間節點(`MK/multihop/chains_2hop.json`,以 `local=false` 與 `y_conflict=true` 計數)。KIN 池只涵蓋 17/58 缺跳(F27)。
  - legacy KG:entity_id＝型別＋無聲調拼音,266 個同音碰撞 id(store `reference/REPORT.md:24`);使徒約翰節點 175 條邊只有 29 條真的涉及使徒(`:34`);15,926 條語意邊的嚴格精確率約 0.23–0.28、寬鬆 0.34–0.45(`:26`、`:676`)。
  - legacy KG 對 GT v2 84 題 strong-need 題的實查:完整 25、部分 44、錯 15;identity_disambiguation 13 題中 11 題錯、2 題部分;唯一的 multi_hop 題(PERSON_QUESTION_065)錯(`KGQ` `checks[].kg_answerable` 與 `final[].tests_kg`、`final[].primary` 交叉計數)。
  - GN-41 覆蓋:104 個所需答案實體組中,KG 只給對 9 個(嚴格 3 個);81 次遺漏是 KG 缺資料、14 次是機制;KG 只在 13/41 題產生任何名稱,其餘 28 題 C3 的查詢等於 C0(`S/gn41_20261002/stats/stats.json` `meta.kg_coverage_detail`;`bridge/coverage.json` `by_category.ALL.kg_q_nonempty`)。
- **注意**:9/104 的單位是答案實體組,不是「事實」。家譜原型不是 production 層;它說明的是「沒有身分層時,名稱層上的鏈結會穿過同名節點」。legacy KG 的稽核數字是 legacy 系統的,論文要標 legacy。
- **建議章節**:`sec:rebuiltmech`、`tab:rebuiltmech`;`sec:kg` 開頭的 legacy 註;`app:rebuild`。
- **文獻掛鉤**:`zhou2025brink`(不完整知識下的 KG-RAG)。

## F29|機制 (C):圖譜特有空間小、與非圖譜通道重疊、贏家詛咒

- **主張**:只有約 6/102 個缺跳是只靠圖譜拿得到的;含 LLM 改寫的圖譜臂勝過純 dense 的部分,都被不用圖譜的雙胞胎重現;GD 的單發正向是在看過、名稱密集的開發集上挑出來的,換到 OLD31 就從 11:0 變 2:2。
- **證據等級**:exploratory (development set)(重疊與歸因);贏家詛咒是解讀,不是檢定過的假設。
- **量化證據**:
  - 圖譜特有空間:GD@10 命中、C@10 沒命中的缺跳 14 個(反向 0)(`GS/wf/final_merge/gd_rescued.json` `n_gd_only`、`n_ctrl_only`);扣掉非圖譜通道也拿得到的,只剩約 6/102(`E3C/interim_report.md:77`、`:409`;產生腳本已刪,見引用陷阱)。字面通道:GD 對 BM25、LEXPRF 的優勢過不了 Holm(F20)。
  - 與 LLM 改寫重疊(10-18,NEW82,@6):QD+G−DEEP 16:2、+0.082;QD+N−DEEP 18:2、+0.099;QD−DEEP 19:2、+0.101(`QDS/report.json` `primary.G2`、`descriptive['QD+N−DEEP']`、`primary.M`)。同一 prompt 只換名稱來源的雜訊:QD+N−QD 6:9、−0.002 [−0.037, +0.038](`descriptive['QD+N−QD']`),和 G1、G3 的區間同量級。逐跳:IT-D−C7 15:2、+0.100 [+0.047, +0.155],加 PPR 的 IT-GD−IT-D 只有 2:0、+0.010(`NA/retrieval_iter.json` `comparisons`)。OLD31:非圖譜 IT-D−DK +0.185,約 80% 來自單步改寫(F22)。
  - 贏家詛咒:GD 從約 10 組設定事後挑出(`GS/README.md:10`);NEW82 有 222/223 跳的 gold 段含本文名稱(段層級;OLD31 為 100/101)(`GS/wf/arch/reach.json` `NEW82.gold_names.gold_has_any_name`、`OLD31.gold_names`);GD 的增益依賴 PPR 偏好名稱密集段(GD_DEGNORM−C@10 只有 +0.006,F20);NEW82 @10 單位 11:0 → OLD31 V1 2:2(F20、F21);用 NEW82 參數算的檢定力在登記時就標註有贏家詛咒(`GDX/prereg.md:98`)。
- **注意**:「含 LLM 改寫的圖譜臂的勝出都來自改寫」只適用於 QD+G、IT-GD 這類含拆解器的臂;單發 GD@10 的勝出沒有 LLM,由前兩點(特有空間小＋事後挑選)解釋。11:0 → 2:2 的其他解釋(OLD31 以 prod 失敗入選的母體差異、V1 只有 4 個不一致單位、真實效果較小)沒有被排除;2:2 在虛無下也有 55% 的停止機率(F21)。
- **建議章節**:`sec:rebuiltmech`、`sec:rebuiltclosure`。
- **文獻掛鉤**:`xiang2025whengraphs`(圖譜何時有用);`zeng2025unbiased`(GraphRAG 增益在無偏評估下縮水)。

## F30|QD(LLM 子查詢改寫)是非圖譜的 context row

- **主張**:不用圖譜、依題目＋C5 寫一個子查詢的 QD,在開發集 NEW82 上對 DEEP@6 有 +0.101 的探索性增益;但在 GT v2 的 204 題多錨題上只有 +0.0174,未過事先門檻,多錨 QD 線依規則停止;盲集確認沒有做。
- **證據等級**:exploratory (development set)(NEW82,規則 M);pre-registered stopping rule(GT v2 步驟 2)。
- **量化證據**:
  - NEW82(40 單位,@6):QD−DEEP 單位 19:2,+0.101 [+0.058, +0.147],描述性雙尾 p 3.8e−5(`QDS/report.json` `primary.M`);QD−C6 19:2、+0.099 [+0.058, +0.143];DEEP−C6 1:3、−0.002 [−0.017, +0.015](`descriptive`)——增益來自改寫的查詢,不是多一個槽。
  - GT v2 多錨(204 題、題層級、anchor coverage@6):QD@6−DEEP@6 +0.0174 [−0.0025, +0.0380],題 W:L 29:20;門檻是 ≥+0.03 且 CI 下界 >0 → 未過,多錨 QD 線停止(`QDS/step2/report2.json` `primary_QD−DEEP_anchor@6`、`verdict`;`QDX/plan.md:67,109`)。平均 anchor@6:C5 0.584、DEEP 0.627、QD 0.645(`means`);vrec@6 QD−DEEP +0.015 [−0.005, +0.035](`descriptive['QD−DEEP vrec@6']`)。
  - 拆解器重複性:步驟 2 的 r2 與 r3 子查詢 204/204 全同,3 次實質上約 2 個樣本(`QDX/plan.md:88`)。
  - OLD31 的對應非圖譜訊號:IT-D−DK +0.185 [+0.054, +0.331](F22)。
  - 盲集:store README 只把 QD 列為盲集候選(`QDS/README.md`,M 過);確認沒有執行,是決定(本次改寫 brief D11 記錄,沒有 archived 決策檔)。
- **注意**:多錨子群是用 eval3c 基線分析選的,不是沒看過的題(`QDX/plan.md:68`);步驟 2 的 dense 是主機重實作,不是 prod Qdrant(`QDX/plan.md:64`)。依 D11,這是 context row,不是主線;abstract 至多一個子句(「apparent graph gains were attributable to LLM query rewriting」)。
- **建議章節**:`sec:rebuiltresults`(`tab:rebuiltgraph` 下方的 non-graph context rows)、`sec:rebuiltmech`((C) 引用)、abstract。

## F31|量測限制

- **主張**:500 題 benchmark 只能偵測傷害、測不到小的圖譜增益;多跳題集全由 LLM 撰寫且未經人工審查;每臂只生成一次;部分 CI 是題層級、未群聚,可能偏窄。
- **證據等級**:descriptive。
- **量化證據**:
  - 500 題的效度:275/500 題(55%)是 explicit_citation(167)或 single_anchor_lexical(108),題面就給出答案位置(`VA:313`);kg-yes 為 0 的 family 有 8 個、共 221 題(`VA:342`);重標後只有 1 題 primary＝multi_hop、需要 ≥2 跳的 15 題(`KGQ` `final[].primary`、`final[].hops` 計數:2 跳 14、3 跳 1)。現況 KG 可兌現的非 curated 題全部完美補上的理想上限是 vrec +0.018(最寬 +0.030),約為 S1 型 MDE 0.0146 的 1.2–2 倍(`VA:72-73`、`:391`);單次生成的 coverage MDE 0.0215(`VA:393`)。「500 題能可靠測到的只有傷害」(`VA:74`;但同句的「飽和題 0 勝 10 負」已撤回,見引用陷阱)。
  - LLM 撰寫:NEW82、OLD31、GN-41 都由 Claude 撰寫,沒有人工審查紀錄;OLD31 的答案由兩位 Claude 評分者評分(F19)。OLD31 有 3 題(KIN_05、MH_TO_04、DISAMBIG_MH_01)在包含 FACTS 在內的六個臂都得 0,疑似題目本身有問題(`MK/realkg/analysis.json` `per_question_final`,六臂皆 0 的題計數)。
  - 每臂只生成一次:Round 3(`paper/record/2026-10-02_round3_expanded_benchmark_findings.md:5`;400 題配對差光雜訊約 ±0.013,同檔 `:74`);eval3c(T＝0.1、無 seed、每臂一次,`E3C/final_report.md:204`;三臂依序收集,`:199`)。Rebuild-1 的 A/A coverage 漂移 +0.0149 [−0.0002, +0.0305],題目重抽的 CI 不涵蓋 run 層級漂移(`S/r2eval/gate_answer.json`;`S/status_audit_20261010/verification_result.json` EVL-4)。
  - 題層級 vs 群聚:GD、QD 的 CI 以 40／20 個群聚單位重抽;realkg、iterq、GN-41、eval3c、Round 3 的 CI 是題層級。OLD31 有 20 個共用 gold 的群、最大 9 題(`GDX/units_old31.json`),所以 realkg／iterq 的題層級 CI 可能偏窄。
  - QD 的 3 次拆解不獨立(F24、F30);bootstrap 只重抽單位,不建模拆解器變異。
  - 離線檢索階段與 prod 不同:主機 dense 不是 prod Qdrant,也不含路由與事件槽(`GDX/prereg.md:20`;`QDX/plan.md:64`);GD、QD 沒有答案層量測,prereg §9 的答案層界限從未套用(`GDX/prereg.md:122-125`)。
- **建議章節**:`sec:rebuiltsetup`(測量設計)、`sec:limitations`(D13 的外部效度)。

---

## 總表:no gain detected, with upper bounds(可直接轉成 `tab:rebuiltgraph` 的列)

Δ̄ 是配對差(圖譜臂 − 對照);upper bound 是 95% CI 上端。f(q) 單位是「每題命中跳的比例」,答案層單位見 metric 欄。路徑縮寫見檔頭。

| comparison | question set (n, unit) | metric @k | Δ̄ | 95% CI | upper bound | evidence class | source |
|---|---|---|---|---|---|---|---|
| GD (dense-seeded PPR) − dense-30 (C) | NEW82 (82 q; 40 clusters) | hop coverage f(q)@5 | +0.020 | [−0.015, +0.054] | +0.054 | exploratory (development set) | `GDX/new82_report.json` hypotheses.H2 |
| GD − dense-30 (C), V1 direction check | OLD31 (31 q; 20 clusters) | f(q)@10 | sealed; cluster W:L 2:2 (4/20 discordant) | — | — (P(stop \| null) 0.552) | pre-registered stopping rule | `GDX/v1_old31.json`; `GDX/v1_power.json` v1_oc |
| kinship walk (KIN) − k-aligned dense (DK) | OLD31 (31 q; question) | answer correctness (2 raters × 3 gens) @5+m | −0.005 | [−0.065, +0.048] | +0.048 | exploratory (development set) | `MK/realkg/analysis.json` primary.KIN_vs_DK |
| name-layer lookup (L0) − DK | OLD31 (31 q; question) | answer correctness @5+m | +0.016 | [−0.065, +0.102] | +0.102 | exploratory (development set) | `MK/realkg/analysis.json` primary.L0_vs_DK |
| iterative, name-layer pool (IT-L0) − iterative, dense pool (IT-D) | OLD31 (31 q; question) | answer correctness @5+m | −0.105 | [−0.234, +0.011] | +0.011 | exploratory (development set) | `MK/iterq/analysis.json` primary['IT-L0_vs_IT-D'] |
| legacy KG bridge names (C3) − LLM rewrite (C2) | GN-41 (41 q; question) | answer key score @5 | −0.004 | [−0.035, +0.026] | +0.026 | exploratory (development set) | `S/gn41_20261002/stats/stats.json` paired.C3_vs_C2 |
| legacy KG facts to generator (C5) − LLM rewrite (C2) | GN-41 (41 q; question) | answer key score @5 | +0.018 | [−0.026, +0.081] | +0.081 | exploratory (development set) | `S/gn41_20261002/stats/stats.json` paired.C5_vs_C2 |
| PPR name hints (QD+G) − non-graph twin (QD+N) [rule G1] | NEW82 (82 q; 40 clusters) | f(q)@6 | −0.017 | [−0.060, +0.023] | +0.023 | pre-registered stopping rule | `QDS/report.json` primary.G1 |
| PPR name hints (QD+G) − plain sub-query (QD) [rule G3] | NEW82 (82 q; 40 clusters) | f(q)@6 | −0.019 | [−0.050, +0.013] | +0.013 | pre-registered stopping rule | `QDS/report.json` primary.G3 |
| gold bridge names (QD+ORACLE) − QD [rule O, diagnostic] | NEW82 (82 q; 40 clusters; 24 q with names) | f(q)@6 | −0.008 | [−0.027, +0.008] | +0.008 | pre-registered stopping rule | `QDS/report.json` primary.O |
| iterative + PPR candidates (IT-GD) − IT-D [rule I] | NEW82 (82 q; 40 clusters) | f(q)@7 | +0.010 | [0.000, +0.027] | +0.027 | pre-registered stopping rule | `NA/retrieval_iter.json` comparisons['IT-GD−IT-D'] |
| curated event lookup lane on − off (not k-aligned) | GT v2 (500 q; question) | answer coverage @5 (+≤1 appended) | +0.0089 | [−0.0030, +0.0207] | +0.021 | descriptive | `E3C/final_out/analysis.json` verdicts.KG['KG-ALL'] |
| Rebuild-2 − Rebuild-1 | GT v2 (500 q; question) | verse recall@6 | +0.0002 | [−0.0016, +0.0026] | +0.0026 | descriptive | `S/r2eval/gate_retrieval.json` criteria.C1 |
| legacy Round 3: graph − no-graph | GT v1 expansion (399 q; question) | answer coverage @5 | −0.014 | [−0.029, +0.001] | +0.001 | exploratory (not pre-registered) | `S/analysis_20261010/round3_stats.out:66` |
| legacy Round 3: graph − no-graph | GT v1 expansion (399 q; question) | anchor coverage@5 | −0.012 | [−0.023, −0.003] | −0.003 (Holm-adjusted p 0.107) | exploratory (not pre-registered) | `round3_stats.out:63`; `VS/multi.out:18` |
| legacy Round 3: graph − no-graph | GT v1 all (499 q; question) | hit rate @5 | +0.002 | [−0.012, +0.016] | +0.016 | exploratory (not pre-registered) | `round3_stats.out:43` |
| legacy Round 3: graph − no-graph | GT v1 original (100 q; question; in-sample) | hit rate @5 | +0.030 | [−0.020, +0.080] | +0.080 | exploratory (not pre-registered) | `round3_stats.out:52` |

Non-graph context rows(不是圖譜結果,放在表下或另一個小表;D11):

| comparison | question set (n, unit) | metric @k | Δ̄ | 95% CI | note | evidence class | source |
|---|---|---|---|---|---|---|---|
| LLM sub-query (QD) − deeper dense (DEEP) | NEW82 (82 q; 40 clusters) | f(q)@6 | +0.101 | [+0.058, +0.147] | cluster W:L 19:2 | exploratory (development set) | `QDS/report.json` primary.M |
| QD − DEEP | GT v2 multi-anchor (204 q; question) | anchor coverage@6 | +0.0174 | [−0.0025, +0.0380] | bar ≥+0.03 and CI lower >0 not met → line stopped | pre-registered stopping rule | `QDS/step2/report2.json` |
| context-conditioned sub-query (IT-D) − DK | OLD31 (31 q; question) | answer correctness @5+m | +0.185 | [+0.054, +0.331] | Holm 0.123; ≈80% from one-step questions | exploratory (development set) | `MK/iterq/analysis.json` secondary['IT-D_vs_DK'] |

---

## 引用陷阱(查證過、不可引的說法)

| 不可引的說法 | 為什麼 | 改用 |
|---|---|---|
| 「跨段兩跳鏈約 24% 正確」 | 沒有任何 primary 存判定;只出現在 `MK/reenable_synth.txt`,原文自標未覆核;`MK/multihop/chain_sample.json` 沒有 verdict(D6) | 結構數字 703/801 條跨段鏈經過多父母節點、163/622(26.2%)(F28) |
| 「82.5% 是真同名」、「PARENT_OF 精確率 53/54」、「真實跳抽出 57%」 | `conflict_sample40.json` 沒存判定;同樣只在未覆核的 reenable_synth.txt(D6) | 不引 |
| 「NEW82 有 216/223 跳的 gold 含名稱」 | 經節層級的數字只在 agent 散文,被複核者標為未查(D6) | 段層級 222/223(`GS/wf/arch/reach.json`) |
| 「reranker 給橋接段 ≈0.001」(一般性) | 只有最差的例子是 0.0009;四個例子 0.0009–0.011,21 筆中位數 0.013;單發 NEW82 情境不同(D6) | F27 的例子與中位數,限逐跳子查詢情境 |
| 5 月 EQ 被擠出的分數(EVENT_008 0.085 vs 0.279、EVENT_011 0.010 vs 0.138)、「rr 對入侵段 AUC 0.49–0.56」、信心分桶精確率(0.197／0.913) | 沒有存活的 primary 檔(D6) | 只用 `sec6_experiments.tex` 既有的定性描述 |
| R=9 答案層探針「非 curated 12 題 90% 上界 +0.12」 | 產生腳本已不存在,無法驗證(D6) | 不引;要引就用可重現的擴充 12 題 +0.111,並標 legacy |
| 「hops≥2 子集 full−nokg +0.019 [−0.053, +0.094]」 | 只在 dossier 計算,不在任何 primary(D6) | 不引 |
| GD reranker 閘門「29 個圖譜特有缺跳選中 14@10、8@5,丟掉的中位數 0.0127」 | 只在 scratchpad(D6) | F27 的 archived 計數(池 59 → 選後 31／14) |
| 「注入名稱被寫進子查詢只有 1/246(G)、2/246(N)、0/72(ORACLE)」、「PPR 名稱含 9/42 個 oracle 名稱 vs dense 6/42」、「G 與 N 名稱重疊 52/410」、「ORACLE 限 24 題 −0.0021」 | 只在 scratchpad 的事後計算(D6) | 用 archived 的 QD+N−QD 雜訊地板 −0.002 [−0.037, +0.038](F29) |
| 「GD 池層 53 vs 35」 | 53 是名稱＋dense 種子的 PPR(G 臂);GD 本身是 59 vs 35(D6) | 59 vs 35(F27) |
| GN-41 的 [−0.039, +0.031]、[−0.031, +0.092];「GN-41 事先登記 STOP」 | 前者是 97.5% Holm 層級 CI;停損規則寫於生成之後(D6) | 95% CI [−0.035, +0.026]、[−0.026, +0.081];寫「null; its stop rule was written after generation」 |
| OLD31 群聚 CI(KIN [−0.040, +0.051]、L0 [−0.039, +0.125]、IT-L0 [−0.258, +0.014]) | 只在 scratchpad 重算 | 用登記的題層級 CI,並在 Limitations 註明未群聚 |
| GD V1 的勝率 Clopper–Pearson [0.068, 0.932]、「\|Δ̄\|<0.10」、似然比 ≈2.4 | 由計數推導、沒有 archived;D5 規定 V1 不報 Δ̄／CI | 只報 2:2、4/20、P(stop) 0.552／0.072 |
| 把 NEW82 GD@10 的 [+0.028, +0.104] 當上界 | 不含 0、事後挑選(D5) | @5 上界 +0.054 |
| 「圖譜特有缺跳 3–7／102」、「14 跳中 6 跳字面通道也拿得到」 | 原腳本(SP/GD-inf/verify.py)已刪;scratchpad 重算得 BM25 或 LEXPRF 各自 6、兩者聯集 7、兩者與 dense 前 100 都拿不到的 3,與期中報告的「6/14」不一致 | 依 D2 寫「≈6/102」(`E3C/interim_report.md:77`),並註明產生腳本已刪 |
| Round 3 其他 Holm 家族(0.068、0.109、0.244)與 MRR sign test 的 Holm 數值(0.009、0.031) | scratchpad 重算 | 只引 archived 的 0.107;MRR 只寫「survives Holm over the same 8 tests」 |
| Round 3 的 151 題 context-changed 子集 coverage −0.034、「Holm 0.11」 | D4 禁止新增;且 Holm 0.114 用的是 bootstrap p,與 sign-flip p 混用 | 不引 |
| 任何 NDCG(含修正後的 0.698／0.711) | D4:NDCG 是已知灌水的指標,本次不新引 | 不引 |
| 「500 題飽和題上 0 勝 10 負」 | 以控制臂分組造成的選擇偏誤,已撤回(`E3C/interim_report.md:391`);`VA:74` 原文未改 | MRR 勝負數(F26) |
| 「k 從 5 加到 10 補回一半缺跳」 | 實際只補回 27%(16/59)(`E3C/interim_report.md:398`) | 不引 |
| final_report T26f 的 kg_strong +0.012、complex_union +0.008 | 那是 full−sem(整條管線),不是圖譜效果 | full−nokg +0.008、−0.021(F25) |
| analysis.json KG_SUMMARY 的「MDE 約 0.07–0.10」 | 同檔 KG-TOUCHED `mde_obs` 是 0.1552,final_report 已更正 | 0.155 |
| 「事件登錄表 33 個事件」用於 Rebuild-2 | 33 是 legacy 匯出與 Rebuild-1 的數字 | Rebuild-2 是 31(F19) |
| GD 圖「16,633 條邊」 | 那個版本另連 split_passage_ids | 16,616(F19) |
| 把建置叫 R1／R2 | R1／R2 是路由名(D7) | Rebuild-1／Rebuild-2 |
| 「IT-GD 是 C5 種子的 PPR」 | `QDX/plan.md:106` 初稿誤寫;程式與 `NA/plan.md:20` 是以子查詢的 dense 前 10 為種子(D12) | F24 的種子描述 |
| 「IT-L0 輸給 dense」 | 事先規則判 `primary_IT-L0_lt_IT-D=false` | 「null,方向偏負」 |
| 「OLD31 V1 是確認性檢定」 | OLD31 只部分盲;D3 沒有 confirmatory | 「pre-registered direction check on a partially exposed set」 |
| GN-41「KG 事實給生成器 C5 0.000」 | 那是 audit 修正計分下的 C5−C0,不是 stats.json 的主比較 | C5−C2 +0.018 [−0.026, +0.081] |
| 「KG 覆蓋 9/104 個所需事實」 | 單位是答案實體組,不是事實 | 「9 of 104 answer-entity groups (3 strictly)」 |
| IT-D 增益的「79.7%」 | 精確值只在 dossier 重算 | 「約 80%」(`E3C/interim_report.md:89`) |
| 「T10 49 步 0 步改變」 | 0 是命中改變;選段改變 9 步,而且那是 L0∪dense 聯集 | F27 的 21–22/58 與「圖譜帶進且被選中 0」 |
| coverage 雜訊地板「\|Δ\| 0.060」當平均差門檻 | 0.060 是逐題平均;400 題平均差的雜訊帶約 ±0.013 | ±0.013(F31) |
| eval3c 答案層 CI 不含 0 當增益證據 | CI 只涵蓋題目抽樣;A/A 漂移約 0.015 | 依 F31 附註 |
| KG-RETR +0.163 當圖譜增益 | 樣本內、查表,eval3c 報告已改名不計入圖譜價值 | 只當 descriptive 的查表檢索層結果(F25) |

---

## 開放問題(交 orchestrator)

1. **D3 沒涵蓋的證據等級**:GN-41 本檔標 exploratory (development set)(題集名 gn_dev、規則寫於生成後);Rebuild-2 vs Rebuild-1 標 descriptive(屬 L1／路由詞表的改版,登記的是非劣性、不是優越性);legacy Round 3 標 exploratory (not pre-registered)。若要嚴格只用三個標籤,Round 3 需另定。
2. **機制 (C) 的字面範圍**:brief D2 寫「every apparent graph win over plain dense came from LLM query rewriting」。單發 GD@10(11:0)沒有 LLM,這句只對含拆解器的臂成立;GD 的勝出由圖譜特有空間小與贏家詛咒解釋(F29 注意欄)。
3. `QDX/plan.md:106` 的 IT-GD 種子更正在工作樹、尚未 commit。
4. OLD31 若要群聚 CI,需把重算腳本封存到 store 後才能引。
5. NEW82 審題 0 筆的說法需呼叫 HTTP 才能重查,本紀錄只引期中報告。
