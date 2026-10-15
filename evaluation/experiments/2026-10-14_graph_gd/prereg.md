# 事前登記：單發圖譜檢索 GD 在複雜關係題的檢索層確認性檢定

- **登記**：2026-10-14。登記 commit 只含本檔；§10 的腳本之後再寫，sha 記入附錄 A。
- **修改規則**：登記後到附錄 A 之前，只處理 NEW82（驗收 A、B）；這段期間寫、修腳本並重新 commit 不算違規。前文若要改，只能依驗收 A、B 的結果修正，diff 列入附錄 A。
- **凍結點是附錄 A**：本檔、腳本、HO 出題與稽核 prompt 的 sha，以及 OLD31 群聚表，都寫進附錄 A 之後才跑 OLD31。之後只在檔尾追加附錄，不改前文。
- **依據**：上一輪定稿（store `reports/multihop_kg_20261012/session_15748325_graphsel/workflow_result.json` 的 result.final），以及 Kay 2026-10-14 的裁決「照預設」（下稱裁決 1–4）。本檔沒寫到的事項，不得用來改變判定。路徑縮寫見檔尾。

> **一覽**
> - **主張**：GD（以 dense 結果為種子，在名稱圖上跑 PPR）對上只用 dense 的 C，比每題全跳覆蓋率 @10。以群聚精確 sign-flip 檢定，α=0.05，主張只靠這一個檢定。它過了之後，@5 與「勝過 BM25／LEXPRF」兩項次要結果以 Holm 並列檢定（§5）。
> - **資料**：NEW82 只用於探索。確認池＝OLD31（31 題）＋盲出的 HO（120 題）。
> - **停點**：V1（在 OLD31 上檢查方向）若單位層級不一致 ≥3 且負 ≥勝，就結案。E2（確認）若 p≥0.05 或方向為負，也結案。結案後不再開新的單發圖譜變體。
> - **E3**（500 題傷害檢查）：未過就不開始 prod 化，但不影響主張。
> - **Kay 只做一件事**：HO 凍結前抽查 15 題（§7）。

## 1. 主張與範圍

- **成功時的主張句**（採裁決 1 的措辭，範圍限定不得省略）：「目前架構的檢索階段搭配 KG 演算法＋dense，在複雜關係題的全跳覆蓋率有顯著提升：在離線重建的單發檢索階段（dense 30 段池 → prod reranker → top-10，未含 R2 路由、book anchor、事件附加槽），GD 相對只用 dense 的 C，在四類合併的 Claude 合成題（HO n=…、OLD31 n=31，共 … 單位）上，群聚精確 sign-flip p=…，單位平均差 …（95% CI …）。」
- **主張句之外**：k=5 與歸因的結果依 §5 另起一句，不改主張句。效果量另報 HO-only 的單位平均差與 CI。不做逐類主張。
- **KG 演算法**：只指在無權的名稱–段落二部圖（L0 名稱層）上跑 PPR。GD 不用題目中的名稱，也不用 kg0 names、parallel_links、triples。
- **檢索階段**：題目原文 → 主機 dense → 池 → prod reranker（送整段、512 截斷）→ top-k。prod 實際是用 Qdrant 取 20 筆記錄（約 12–13 段）、k=5，並經 R2 路由；上 prod 前另用完整流程重驗（裁決 3）。
- **母體**：Claude 合成、並經多跳必要性篩選的題；OLD31 另外是以「prod D5 有缺跳」為條件入選的。結果不外推到真實使用者的題。
- **不主張**：答案層增益（§9）；prod 完整流程或 500 題上的增益（E3 只測傷害）；名稱連結（G）有效；家譜、關係層、身分層（P5 已取消）。

## 2. 資料

| 代號 | 內容 | 角色 | 釘 |
|---|---|---|---|
| NEW82 | E7/newq/questions_v5.json 90 題中，status≠reject 且 reject_reason、dedup_drop 皆空的 82 題，共 223 跳（PN/common.py:33-40） | 開發／探索 | 檔 `4b37e5c3…`；題號 `84985f6d…` |
| OLD31 | E7/multihop/synth/usable.json 38 題中，凍結 prod D5（E7/reenable/api_arms.json）下缺跳數 m>0 的 31 題，共 101 跳（E7/realkg/extract_inputs.py:24-32） | 確認池；V1 先跑 | usable `0ade60b8…`；api_arms `7e28ef3b…`；題號 `868f75d6…` |
| HO | 盲出 120 題（§7） | 確認池（E2） | 附錄 B |
| GT v2 | repo 的 `ground_truth.v2.json` 500 題，不改 | 只測傷害（E3） | `7280bb42…`（config/gold/gt_v2_freeze.json:4-5） |

- **題號 sha**：`"\n".join(sorted(ids))`，UTF-8 編碼，無結尾換行（X/x_data/new82_ids.txt、old31_ids.txt）。
- **NEW82 只當探索集**：結果已看過，而且檢索是決定性的，所以 NEW82 上的任何結果都只能標為探索性，不得與確認結果並列為證據。挑參數、挑臂、改規則都只用 NEW82；在 NEW82 上另做的探索（NAME_IDF、融合等）不影響本檔的臂與判定，也不帶進確認池。OLD31、HO 一旦跑過任何臂，就不再當開發資料。
- **確認池**＝OLD31∪HO（裁決 4）。OLD31 有 16 題和 NEW82 共用 gold 段（X/x_data/overlap_density.json 的 NEW82_x_OLD31）。其中 DISAMBIG_MH_04、DISAMBIG_MH_07、KIN_03 的 gold 含有 GD 在 NEW82 獨有救回的段（R/review_stats/s1_strata.json），屬部分樣本內，處理方式見 §5 的附註規則。
- **四類對應**：OLD31 依 id 前綴 `id.rsplit("_",1)[0]`：KIN→親屬；DISAMBIG_MH→消歧；MH_TO→時序；SUC、PRI、JDG、MH_BR、MH_OQ→多跳；NULL_MH→其他。依序為 7、9、4、10、1 題（R/review_stats/s1_strata.json）。NEW82 依 category：KIN→親屬；DIS→消歧；TO→時序；SUC、BRP、BRL、OQ→多跳；NULL→其他。HO 依 id 前綴：H_KIN_→親屬；H_DIS_→消歧；H_TO_→時序；H_MH_→多跳。

## 3. 臂

- **查詢與向量**：查詢用題目原文 `question`，不改寫（PN/prep.py:25-27）。向量在容器內用 `utils.embedder.encode_query` 產生（BGE-M3 rev 5617a9f6，fp32，已正規化；PN/encode_in_container.py:39-50）。NEW82 重用 PN/encode_out.jsonl，並依 sorted(id) 取前 5 題重編，逐分量 max|Δ| 須 ≤1e−5。OLD31、HO 各編一次，sha 記入 meta。
- **Dense 排名 D(q)**（PN/densemat.py:8-52）：主機以 **float64** 對 LAY/emb/emb@ae5525447eda 的 vectors.npy（34,058 列）算精確 cosine，不經 Qdrant。段分數＝該段所有記錄的最大值；verse、chunk 記錄依 payload.passage_id 歸段。排名在 sorted(passage_id) 上做 `argsort(−best, stable)`。NEW82 上 float64 與 float32 的 D[0:30] 82/82 相同（R/review_impl/dense_gap_check.out）。
- **池**＝D[0:20]＋extra。extra ≤10 段，不與 D[0:20] 重疊、不重複（FM/gd_vs_lexprf.py:64-66）。extra 不足 10 段時不補，池可少於 30；逐題記錄池大小，並報告池 <30 的題數。
- **Reranker**（PN/rerank_in_container.py:24-64）：在容器 `bible_rag_backend` 內呼叫 `utils.reranker.rerank(question, recs, top_k=len, text_key='content')`；模型 bge-reranker-v2-m3 rev 953dc6f6，fp32 CPU，max_length 512，longest_first，sigmoid。content 取 PG passages.content，與 struct passages.jsonl 的 2,773 段 sha 全同（X/x_arms/pg_content_check.py）；chunk 一律送母段。打分時每題把所有臂池的聯集一次打完，依 pid 排序，每批 16 對，torch 12 threads。
- **top-k**＝`sorted(pool, key=(−score, pid))[:k]`。k=10 為主，k=5 為次。不套用 backend/config.py:97-100 的融合。
- **bip 圖**（PN/graphs.py:11-39,84-117；PN/common.py:84-98）：段節點為 LAY/struct/struct@d8d432b4df15/passages.jsonl 的 2,773 段（依列序）；名稱節點為 LAY/text/text@247eafe44b02/name_spans.jsonl 中 region=='body' 的 2,929 個 norm_key；名稱在某段任一 unit 有 body span，就連一條無權邊；unit 經 verse_index 的 passage_id 歸段，不連 split_passage_ids。共 16,616 條，邊清單排序後建圖。
- **PPR**（PN/graphs.py:119-136）：種子分佈 e 的總和為 1，r0=e，固定迭代 40 次：r←0.5·e＋0.5·(Pᵀr＋(Σ_{deg=0} r)·e)，P 為 1/deg 列隨機矩陣。排序鍵是 (−round(r,12), passages.jsonl 列序)，只留 r>1e−12 的段。

| 臂 | extra（排除 D[0:20] 後） | 出處 |
|---|---|---|
| C（對照） | D[20:30] | EV/prf_pool.py:144 |
| GD（主臂） | 種子＝D[0:10]，權重 1/rank 並正規化為和 1；跑 PPR 後依上述排序取前 10 | EV/prf_pool.py:103-130 |
| GD_DEGNORM（敏感度） | 同 GD，但改用 prn＝r/max(deg,1)：依 (−round(prn,12), 列序) 排序，只留 prn>1e−12 | FM/gd_hub.py:29-37 |
| G（描述） | 種子＝0.5·GD 的 dense 種子＋0.5·名稱種子（每個名稱權重為 1／該名稱的段數，再正規化）；沒有名稱時 G＝GD | EV/prf_pool.py:119-128 |
| L（BM25） | 全部段（含零分段）依 (−score, pid) 排序後取前 10 | EV/prf_pool.py:35-72,138-140 |
| LEXPRF（同種子字面回饋） | 以 q(t) 加權的 BM25 打分，只取正分段，依 (−score, pid) 取前 10，不足不補 | AT/prf_controls.py:62-72,92-111 |

- **L 的打分**：content 先把 `**n**` 節號換成空白，再在每個極大 `[一-鿿]+` 字串內取相鄰字二元組；k1=1.2、b=0.75、avgdl＝每段二元組數的平均、idf=ln(1+(N−df+0.5)/(df+0.5))、N=2,773；查詢＝題目二元組的集合，各權 1。
- **LEXPRF 的 q(t)**：回饋取 D[0:10]，w=1/rank，不正規化。fb(t)=Σw·tf/段長·idf，段長＝該段二元組總數；取前 40 詞，同分依 (−值, 詞)（NEW82 上與原序 82/82 相同，X/x_arms/lexprf_tiebreak.out）。q(t)=0.5·tf_q/Σtf_q＋0.5·fb/Σfb。
- **G 的名稱連結**（改自 PN/common.py:48-81）：
  1. 遮書名：取 text books.jsonl 的書名，加上以「上／下」結尾、長度 >3 的書名去掉末字的形式；依 (−長度, 字串) 排序，逐一以等長的 □ 取代。
  2. 建 surf_table：依 kg0@14e68c8344b1 names.jsonl 列序，每列先放 surfaces、再放 norm_key（長度 ≥2）；之後以 setdefault 補 route@c31c88e4681e/query_aliases.json。
  3. 比對：依長度遞減，同長度依 surf_table 插入序；每個 surface 由左至右找，與已佔位置重疊的略過。
  4. 收尾：依起點排序、去重，只留在 bip 有節點的名稱。
- **W（逐窗重排；敏感度，只算 C、GD）**：段分數改取逐窗最大分。規範實作是 WF/exp/rr_probe_in_container.py:44-70 的 windows()／score()。只有一窗的段沿用整段分數（同檔 :102-108）；段依 pid 排序，逐段打分。
- **不是本檔的臂**：PO/build_cands.py 與 WF/arch/reach.py 的 PPR、PRF_VEC、EMBPRF、DENSITY、NAME_IDF、融合。OLD31 上舊的 PPR_bip 數字，不得當成 GD 或 G 的結果。
- **驗收 A（清單，NEW82）**：D[0:20]、C、GD、G、L、LEXPRF 須與 EV/prf_lists.json、AT/prf_lists.json 82/82 逐項相同。GD_DEGNORM 在 S1 池層（題目查詢、102 缺跳）須為 reach（gold 進池的缺跳數）=45、題層 11:3（FM/gd_hub.json）。PYTHONHASHSEED 設 0 或 1，結果都要相同。
- **驗收 B（選段，NEW82）**：用本節的打分方式在容器實跑一次，不讀舊分數；82 題 × {C、GD、G、L、LEXPRF} × k∈{5,10} 的逐題 top-k 集合，須與封存分數推得的集合（X/x_arms/reproduce_sel.py 的 merged()）完全相同。彙總參考值（X/x_arms/reproduce_sel.json，依 C、GD、G、L、LEXPRF 的順序）：全跳命中 @10 為 137、151、146、143、141，@5 為 119、126、124、120、122；缺跳命中（/102）@10 為 17、31、26、24、21，@5 為 7、14、13、10、12。**數值出口**：封存的跨 run 漂移為 9.24e−7，最小切點間隔 2.35e−5（同檔）。不符的題若都是切點間隔 <10 倍實測漂移（同一對新舊分數差的最大值）的邊界題，記入附錄 A，以新分數為準；否則就是實作錯誤，要修到相同，不得改定義遷就。A、B 都過之前，不得跑確認資料。
- **NEW82 參考（探索性，不得作證據）**：GD−C 題層級 @10 為 14:0，@5 為 10:3（X/x_arms/reproduce_sel.json）。§5 群聚後，@10 為 11:0（p=0.001），@5 為 8:2（p=0.27）（R/review_impl/cluster_signflip_check.out）。

## 4. 指標

- **gold**：每跳 hop_slots 的每個鍵，經 E7/newq/tools/bt.py:43-70 的 find_unit／resolve 對到 unit；該 unit 在 verse_index 的 passage_id ∪ split_passage_ids，即為該跳的 gold 段集合。合併節鍵可用；a/b 半節鍵無法解析，HO 不得使用（§7 的機械檢查會拒收）。NEW82 的 223 跳、OLD31 的 101 跳，與各自存檔規則的差異為 0（X/x_data/gold_map_check.py、X/x_arms/gold_rules.out）；兩個題集都沒有 split unit（R/review_impl/gold_clusters.out）。OLD31 用 hop_slots，不用 gold_slots；其中 16 題兩跳共用 gold 段，照算。
- **主指標**：每題全跳覆蓋率 f(q)=(1/H)·Σ_h 1[gold_h∩top_k≠∅]（EV/sel_eval_ev.py:41-51），以 Fraction 精確計算。@10 為主、@5 為次，不限定 m>0。這是本實驗專用的指標，版本＝evaluate.py 的 sha（記入 meta）；metric_version 4d0826bb8d14 只用於 E3 的 GT v2 指標。
- **嚴格版（敏感度）**：一跳命中 ⇔ gold_h⊆top_k。
- **描述**：全跳命中數、全鏈題數（f=1）、缺跳命中數。缺跳＝gold 不在 D5≈ 的跳。D5≈＝主機記錄層 cosine 前 20 筆，映段去重後依 (−整段分數, pid) 取前 5（PN/analyze.py:124-131 的主機版）；在 NEW82 上，輸入與容器版 82/82 相同（R/review_impl/d5_host_check.out）。NEW82 用存檔的 102 跳／63 題（PN/question_summary.json 的 missing_rr）；OLD31 另附 prod D5 缺跳 58 跳（E7/reenable/api_arms.json）。

## 5. 檢定與判定

- **配對差**：d(q)=f_X(q)−f_C(q)。
- **群聚單位**（AT/cluster_signflip.py:36-51）：兩題的 gold 段聯集有交集就相連，取 union-find 連通元件。單位值 v_u＝單位內各題 d 的不加權平均（0 也算入）。OLD31 為 20 單位、最大 9 題（R/review_impl/gold_clusters.out），寫入附錄 A。HO 照同法計算，寫入附錄 B；依 §7 不重疊，預期每題自成一群，以計算結果為準。子集與分層分析一律在子集內重做 union-find。
- **統計量與方向**：單位平均差 Δ̄＝Σ_u v_u／單位數（含 v=0 的單位），方向依 Σv 的正負，與 sign-flip 一致；單位 W:L＝#{v_u>0}:#{v_u<0}，不一致單位＝v_u≠0。單位依其最小題號排序。題層級平均只作描述。
- **精確 sign-flip**（雙尾；EV/sel_eval_ev.py:27-33）：v 以 Fraction 表示，丟掉 v=0 的單位。T=|Σv|，p=#{s∈{±1}^n: |Σs·v|≥T}/2^n，以精確 DP 計算，不用容差。DP 狀態數 >10^7 時改用 Monte Carlo：random.Random(20261014)，R=10^6，抽法同 evaluation/src/ab_stats.py:52-57，p=(hits+1)/(R+1)。
- **CI**：evaluation/src/ab_stats.py:59-72 的 `bootstrap_ci(單位值, n_boot=10000, seed=20261014)`。以單位重抽，統計量同 Δ̄，每次呼叫都從 seed 重新開始。
- **把關順序**（全程 FWER 控制在 α=0.05）：H1 沒過時，H2、H3 只報 W:L 與 CI，不報 p、不寫「顯著」。
  1. **H1** GD−C@10，α=0.05：p<0.05 且 Σv>0 → 主張成立，用 §1 的主張句。
  2. **H1 過了之後**，H2 與 H3 以 Holm 並列檢定（α=0.05；p 較小者要 <0.025，另一項要 <0.05）。兩項互不為前提。H3 的 p 取 max(p_LEXPRF, p_L)，兩項都要 Σv>0。
     - **H2** GD−C@5 通過 → 加一句「k=5（prod 的 k）也顯著」。
     - **H3** GD−LEXPRF@10 與 GD−L@10 通過 → 加一句「且增益超出同種子字面回饋與 BM25（題目經單段字面捷徑排除）」；否則寫「未證明超出字面通道」。
  - **理由**：H2、H3 都依裁決 2、3 列為次要，裁決沒有排先後。NEW82 群聚後，H2 的 p=0.27，H3 兩項為 0.025、0.024（R/review_impl/cluster_signflip_check.out）。若用固定序列 H1→H2→H3，H3 會被較弱的 H2 綁住。
- **只描述**（W:L、Δ̄、CI，不報 p）：G−C、GD_DEGNORM−C、L−C、LEXPRF−C、GD−G。
- **必報敏感度**（GD−C@10 與 @5；只報 W:L 與 CI；不改變判定，也不得單獨構成主張）：題層級（不群聚）、嚴格版、W 版（GD_W−C_W）。核心群聚（gold 段相交或 core 欄位相同就相連；OLD31 沒有 core，只用 gold）。OLD31、HO 分開；剔除與 NEW82 共用 gold 段的 16 題 OLD31。名稱密度兩層（§7）、四類各自。對 H3 另報排除 [SHORTCUT] 題的結果。
- **事先寫死的附註**（H1 成立時）：HO-only 的 Δ̄≤0 → 主張句加「僅看 held-out 時方向不一致」。剔除上述 16 題後 Δ̄≤0 → 主張句加「排除與開發集共用段落的題後方向不一致」。

## 6. 停損與結案

- **V1（OLD31，附錄 A 之後）**：一次打完 OLD31 所有臂的池（@10、@5）。原始輸出封存在 store、不讀；腳本只印停損判定與 GD−C@10 的單位 W:L。E2 的 OLD31 部分沿用這份封存。**停損**：20 個單位中不一致 ≥3 且負 ≥勝 → 結案，不出 HO。其餘一律繼續，不要求顯著。題層級版的操作特性：在 r=0.222 時，虛無下停損 0.56，勝率 0.8 時停損 0.063（X/x_metrics/recheck.json）；單位層級版在附錄 A 以同法重算。只因反向而停不會膨脹 α：拒絕虛無需要「V1 繼續且 E2 顯著」。
- **E2 判定**：依 §5 的把關順序。H1 不過（含 p<0.05 但方向為負）→ 結案。
- **檢定力（揭露）**：程序層模擬含 V1 停損，條件為 HO 120 題＋OLD31 20 單位（R/review_stats/s2_power.json）。不一致率 0.17：勝率 0.8 時約 0.83，0.75 時約 0.65。不一致率 0.12、勝率 0.8：約 0.69。兩個參數都取自 NEW82 上挑出的設定，有贏家詛咒。
- **結案措辭**：V1 停損寫「方向檢查未過，依事先規則停止，不構成無效證據（OLD31 單位 W:L＝…）。」E2 未過寫「本設計（n=… 單位，勝率 0.8 時檢定力約 0.83）下未達顯著，單位平均差 …（95% CI …）。」方向顯著為負時加「且有顯著傷害」。結案後不再開新的單發圖譜變體，並寫入 store README 與 memory。

## 7. HO 出題協定

- **題數**：N=120，四類各 30。多跳指 SUC／BRP／BRL／OQ 型橋接，配額 8／7／8／7。每題 2–5 跳，不出 NULL；同一核心人物或事件最多 2 題。生成順序固定：四類輪替，多跳內再依子型輪替。每類依此順序取前 30 個通過稽核的題。某類草稿達 60 題仍不足 30 時，以實際數凍結，並記入附錄 B。
- **格式**：沿用 NEW82 的欄位（E7/newq/annotate.py:25-49，含 shortcut_search），另加 core 欄位。id 前綴：H_MH_、H_DIS_、H_KIN_、H_TO_。hop_slots 只能用整節或合併節鍵。因「可被單段直接取回」而改寫的題，在 change_log 加固定標記 [SHORTCUT]。
- **盲化**：出題與稽核 agent 從 /home/kenzx0521/Bible_RAG 以外的 cwd 啟動，以免載入專案記憶與 CLAUDE.md；工具只開 ho_tools/ 的 bt.py 副本（v、grep、pid、books、old）。`old` 對 GT v2 與 OLD31 回傳題目文字；對 NEW82 與 HO 草稿只回報 gold 段衝突，不回傳全文。prompt 全文（ho_tools/gen_prompt.md、audit_prompt.md）在附錄 A 前凍結，內含本節規則與多跳必要性判準（能獨立提供該跳事實的平行經文必須全列），不得出現檢索、dense、reranker、圖譜、PPR、名稱圖等字樣。保存 transcript；凍結前機械檢查沒有讀過 store 的 layers/ 以外路徑，也沒有出現專案記憶的內容。凍結前不跑任何檢索，也不用檢索篩題。
- **不重疊**（一律用 §4 的 gold 段集合）：同題兩跳之間、HO 之間、HO 與 OLD31、HO 與 NEW82，都不得相交。GT v2 例外：它的 gold 段佔 42.6%（X/x_data/exclusion_budget.json），改為不得考同一條事實鏈或核心事實，以 `old` 比對加稽核把關。這條規則會擋掉高密度段：≥0.9 百分位的 278 段中，已有 40.3% 被 NEW82∪OLD31 佔用（同檔）。這對 GD 的影響方向未知。
- **稽核**：(1) 機械檢查（逐批跑，凍結前再全量跑一次）：annotate.py 的檢查（經節存在、每跳有 pid、≥2 跳），加上半節鍵拒收、gold 可計算、不重疊、同一核心 ≤2 題。(2) 獨立 Claude 稽核：每題給 severity（ok／minor／major／critical）並附 checked，格式同 E7/newq/audit_result.json。major、critical 須修好並複驗，否則刪題，由後續題遞補。(3) Kay 抽查：從 120 題候選以 `random.Random(20261014).sample(sorted(ids), 15)` 抽題，在 build_page.py 的審題頁上看；有問題就在凍結前修或刪，遞補方式同上。
- **工具**：bt.py:17-18、84-93、annotate.py:8、build_page.py:8 寫死了 /tmp。改用 ho_tools/ 的副本：路徑改成參數，`old` 加入 NEW82 與 HO 草稿；原檔不改。
- **名稱密度**（描述；PN/hub_check.py:20-28）：deg(p)＝段的 body 名稱種類數，pct(d)＝#{deg≤d}/2773。跳值＝該跳 gold 段 pct 的最大值，題值＝各跳值的最小值；題值 <0.8 為低密度層。NEW82 參考：低密度 47/82（R/review_impl/gold_clusters.out）。
- **凍結**（附錄 B，在跑任何 HO 臂之前）：記錄 `evaluation/experiments/2026-10-14_graph_gd/heldout_ho.json` 的 sha256、題號 sha、群聚表、core 表、密度層、[SHORTCUT] 清單、各類因不重疊被擋的草稿數，以及 HO 的密度分佈。附錄 B 之後不改題、不剔除。

## 8. E3：500 題傷害檢查（不擋主張）

- **範圍**：GT v2 500 題，跑 C 與 GD（定義同 §3），k=5，不呼叫 LLM。比的是相對離線 C 的傷害，不是相對 prod R2。
- **計分**：轉成 raw_responses.json（每題恰好 k 個 passage 來源，帶 start_key、end_key、中文書名，route_used 設為 "OFFLINE"），另附 run_meta.json（build b20261008_e05d3e55＋encoder 指紋）。執行 `quick_retrieval_eval.py --from-raw … --gt v2 --top-k 5 --metric-k 5`（evaluation/quick_retrieval_eval.py:436-498），metric_version 必須是 4d0826bb8d14。輸出移到本目錄 e3/，results_quick 不留檔。
- **閘門**（三道全過才通過；逐題差都是 GD−C）：
  1. vrec@5：逐題差（依 sorted(qid) 排列）的 `bootstrap_ci(diffs, n_boot=10000, seed=20261014)` 下界 >−0.02。不用 ab_compare 預設的 seed 0。
  2. MRR@5：|Δ|>1e−9 才計勝負；勝/(勝+負) 的雙尾 95% Clopper–Pearson 下界 >0.4。勝＋負＝0 時視為通過，並記錄。
  3. slot 層級 gold_out ≤10，且不多於補回。用 quick_retrieval_eval 為該 build 建的 GT v2 ruler，S(·)＝ruler.source_slots（evaluation/src/slot_coverage.py:258-259）。lost(q)＝gold_slots∩(S(C@5)−S(GD@5))，gained(q)＝gold_slots∩(S(GD@5)−S(C@5))。gold_out＝#{lost≠∅}，補回＝#{gained≠∅}，兩者都非空的題兩邊都計。不用 ab_stats.ledger_entry。
- **角色**：未過 → 不開始 prod 化，報告附上傷害，E2 主張照樣成立。通過只代表可以開始 prod 化。正式的 500 題傷害判定，交給上 prod 前完整流程的 prereg（上一輪 O5「prod 化」）。k=10 同法只報告，不設閘門。O5 原寫「k=5 與 k=10 都通過」；本檔只以 prod 的 k=5 設閘門。E3 可在附錄 A 之後，與 V1、HO 並行。

## 9. 答案層

- **定位**：答案層不屬主張。它的非劣性是上 prod 的前提，和完整流程重驗寫進同一份上 prod 前的 prereg：用 prod 流程（k=5），在任何生成之前登記，並在那時審核用到的參考答案。
- **界限（現在先定）**：key_points 覆蓋率與 faithfulness（GD−C）的 95% CI 下界 >−0.05；wrong_merge 率（GD−C）的 95% CI 上界 <+0.05。

## 10. 執行與決定性

- **腳本**：放在 `evaluation/experiments/2026-10-14_graph_gd/`，包括 `arms.py`、`evaluate.py`、`e3_raw.py`、`ho_tools/`、`encode_stdin.py`、`rerank_stdin.py`。後兩支以 `docker exec -i -e PYTHONDONTWRITEBYTECODE=1 -e HF_HUB_OFFLINE=1 bible_rag_backend /app/backend/.venv/bin/python -B -` 執行，不寫檔。一律讀 store，不讀 /tmp。原始輸出寫到 store 的 `reports/graph_gd_20261014/`；摘要與報告寫在本目錄。
- **meta**（每次執行都記；任一指紋不符就停止，不出結果）：sha256 包括本檔（含當時已追加的附錄）、各腳本、題集（檔與題號）、向量檔。層：text@247eafe44b02、struct@d8d432b4df15、emb@ae5525447eda（vectors.npy `870ca1fc…`）、kg0@14e68c8344b1、route@c31c88e4681e。build b20261008_e05d3e55，映像 `sha256:c79266296cb0…`。reranker 指紋：rev 953dc6f6、tokenizer_sha `69564b69…`、probe_ids_sha `0e7683de…`、unk 2。embedder 指紋：rev 5617a9f6、tokenizer_sha `21106b6d…`、probe_ids_sha `a0e8db60…`、unk 3。環境：PYTHONHASHSEED、BLAS 名稱與 threads、batch、python／numpy 版本、時間。
- **決定性**：清單在 PYTHONHASHSEED 設 0 與 1 時必須相同。每次打分另外重打 32 個參考對（EV/ev_sel_out.jsonl 依 (qid, pid) 排序的前 32 對），差 >1e−5 算基礎設施失敗。報告各臂 top-k 切點的最小間隔，<1e−5 的題列為邊界題。
- **重跑**：每個階段最多重跑 2 次，只限基礎設施失敗（容器錯誤、分數缺漏、指紋或 build 不符、參考對漂移）。附錄 A 之後，腳本只能修基礎設施錯誤；修後要重過驗收 A、B，並在附錄記錄 diff。看到確認資料後，不改臂、參數、指標、群聚、序列、門檻與題集。
- **順序**：登記 commit → 驗收 A、B → 附錄 A → V1 →（未停損）HO 出題、稽核、凍結 → 附錄 B → E2（跑 HO 全部臂，與 V1 封存的 OLD31 輸出合併）→ 報告。E3 可在附錄 A 之後並行。

## 附錄（只追加，不改前文）

- **附錄 A**（凍結點，V1 之前）：本檔 sha、腳本 commit sha、ho_tools 兩份 prompt 的 sha、OLD31 的群聚表（20 單位）與密度層、驗收 A 與 B 的結果、NEW82 新打分彙總，以及單位層級 V1 的操作特性與程序檢定力重算。待追加。
- **附錄 B**（HO 凍結，E2 之前）：§7 的凍結清單。待追加。

## 出處縮寫

- **store**：以下路徑都相對 store `/mnt/ollama-data/bible_rag_store`。
- **WF 系列**：WF＝`reports/multihop_kg_20261012/session_15748325_graphsel/wf`；PN、EV、AT、FM、PO 依序是 WF 下的 probe_newq、verify_evidence、verify_attribution、final_merge、probe_old31。
- **其他**：E7＝`reports/multihop_kg_20261012/session_e73fd5d9`；LAY＝`layers`。
- **核對輸出**：X＝撰寫時的核對輸出（x_arms、x_metrics、x_data）；R＝審查時的核對輸出（review_impl、review_stats）。兩者都在登記時封存到 `…/session_15748325_graphsel/prereg_check/`。
- **repo**：repo 內的檔案寫 repo 相對路徑。

### 附錄 A（2026-10-14 追加；凍結點，V1 之前）

- **凍結**：腳本全在 commit `83ea0638a9b8b477d33afbe75788d6623e279b4b`，實驗目錄的追蹤檔與該 commit 無差異。本檔追加前 sha256 `985d933dcd903a7aa22ece2cd05a3ec78bff7e8e00862997255398805f6d4920`。全部腳本、兩份 HO prompt（gen `ac17dc2e…`、audit `74458b1e…`）、page_template、units_old31.json、v1_power.json、驗收檔的完整 sha256 列在同目錄 `appendix_a_sha256.txt`（52 行，sha256 `c673b98ead3a11207b4716c384538aef79afed26bf6d80dff86d501b4ec8ee4e`）。本附錄與 units_old31.json、v1_power.json、appendix_a_sha256.txt 尚未 commit，等 Kay 同意後 commit；V1 的 meta 會記錄含本附錄的 prereg sha。
- **驗收**：A 通過（lists_sha256 `25b196a2…`，PYTHONHASHSEED 0／1、threads 1 都相同）。B 通過：逐題 top-k 820/820 相同，漂移 1.76e−6（上限 1e−5），邊界題 0，refcheck 32 對 max|Δ|=0。NEW82 新打分彙總與 §3 參考值相同（new82_report.json，探索性）。
- **OLD31 群聚表**（units_old31.json）：20 單位、最大 9 題。多題單位：{DISAMBIG_MH_07, 08, 09, 10, KIN_01–05}（9）、{DISAMBIG_MH_03, DISAMBIG_MH_04, MH_OQ_02}（3）、{MH_TO_02, SUC_01}（2），其餘 17 題各自成單位。四類：親屬 7、消歧 9、時序 4、多跳 10、其他 1。低密度層 15 題。與 NEW82 共用 gold 段的 16 題：DISAMBIG_MH_04、07、08、09，KIN_01、02、03、04、06、07，MH_OQ_01，MH_TO_01、03、04，PRI_01，SUC_01。與封存的 R/review_impl/gold_clusters.out 相同。
- **V1 操作特性（單位層級，v1_power.json；操作特性 200,000 次模擬、程序檢定力 4,000 次）**：r＝0.222 時，虛無（勝率 0.5）下停損 0.552，勝率 0.8 時停損 0.072（題層級版 0.562／0.063）。程序檢定力（含 V1 停損，HO 120 題＋OLD31 20 單位）：r_ho 0.17、勝率 0.8 時拒絕 0.825，0.75 時 0.653，虛無下 0.024；r_ho 0.12、勝率 0.8 時 0.695。封存的 s2_power.json、recheck.json 都已重現。方法選擇（|d| 取四位小數、單位大小排序、HO 視為 120 個單題群、r_old＝min(0.9, r_ho·0.222/0.171)）未另行獨立審查，只作揭露、不影響判定。
- **Kay 2026-10-14 裁決**：(a) HO agent 的 context 會被注入帳號 email（OAuth 無法關閉），接受並揭露；transcript 看不到注入內容。(b) Claude Code CLI 釘 2.1.299，`_ho_claude.launch` 版本不符就拒跑（`--thinking-display` 是 --help 未列的選項，換版前要用 ho/probe 的方法重測）。(c) `/srv` 必須為空，`check_cwd` 已擋。(d) E3 用 `--arms C,GD`（批次組成與 §3「所有臂池的聯集」不同；實測 |Δ| 最大 1.07e−6，封存跨 run 漂移 9.24e−7，驗收 B 漂移 1.76e−6，都在 §10 門檻 1e−5 內）。
- **偏離登記內容的事項**：(1) HO transcript 只含 API 端 thinking 摘要；(2) 禁用字出現在 agent 自己寫的文字只記 warn，出現在 system prompt 才是 error；(3) 盲化違規在提交時就刪題、由後續題遞補；(4) agent 看得到所有已用核心與題數，core 的別名異寫由稽核判 major、機械檢查只 warn；(5) bt_guard 拒絕引號外的萬用字元與 ~，bt 不回顯非經節鍵的參數；(6) E3 run 互斥，失敗輸出留在 failed/；(7) W 另報切點間隔；(8) 附錄 B 另列 overlap_avoided、transcript_breaches；(9) 工作樹另有一處未 commit 的測試檔改動（evaluation/tests/test_graph_gd_ho_order.py 移除 CLI 釘版測試，來源不明），不影響實驗腳本，釘版檢查仍在 `_ho_claude.py`。

### 執行紀錄一（2026-10-15 追加；V1 的啟動時序與打分環境）

- **時序**：V1 在 2026-10-14 15:56（UTC+8）就啟動（encode、arms、rerank），早於 Kay 同意 commit 附錄 A（2026-10-15）。當時附錄 A 已寫進工作樹、尚未 commit。lists.json 與 scores.jsonl 的 meta 記錄的 prereg sha256 是 `c2432536…`，等於 commit f3d1bd4 的版本；腳本與 83ea063 相同（appendix_a_sha256.txt 其餘 50 檔核對無誤）。
- **中斷**：rerank 在 16:06 隨 session 中止而停下，完成 18/31 題（兩個 chunk，10 題與 8 題）。沒有 refcheck 行，`evaluate.py v1` 沒執行。續跑前只讀過分數檔的行數、meta 與每題的 sid／elapsed／missing，沒有讀分數。
- **打分環境**：第二個 chunk（JDG_01、MH_BR_01、MH_BR_03、MH_TO_01–04、MH_OQ_01）打分時，兩支已中止 workflow 留下的行程（p5_query.py、build_it.py）同時在用機器與 backend。每題耗時 42–52 秒，第一個 chunk 是 19–37 秒。容器設定沒變（CPU、batch 16、12 threads，meta 有記錄）。
- **處理（看結果前決定）**：(1) 已打的 18 題另存重打一次（G/old31/recheck18/，只呼叫 score.py 原函式，不改腳本），逐對比較，只印對數與 max|Δ|。max|Δ| ≤ 1e−5 就沿用原檔；超過算 §10 基礎設施失敗，另起新分數檔，OLD31 31 題全部重打（算第 1 次重跑）。(2) 照 README 續跑 `score.py rerank`（補 13 題，結尾 refcheck），再跑 `evaluate.py v1`。續跑的 meta 會記錄追加本段後的 prereg sha。
- **命名**：本段不叫附錄 B。§10 的附錄 B 是 HO 凍結清單，`gd.assert_set_allowed` 把「附錄 B」標題下有內容當作 HO 的解鎖條件。
- **CLI 版本**：本機 Claude Code CLI 已自動更新到 2.1.300，與附錄 A (b) 釘的 2.1.299 不同。只影響 HO（`_ho_claude.launch` 會拒跑），V1 不用 CLI；HO 前另行處理。

### 執行紀錄二（2026-10-15 追加；V1 結果與結案）

- **重打比對**：已打的 18 題另存重打（G/old31/recheck18/），1,078 對 max|Δ| 0，原檔沿用。
- **續跑**：補打 13 題（769 對），結尾 refcheck 32 對 max|Δ| 0。
- **V1**（v1_old31.json，scores 內容 sha256 `3df080bf…`）：stop＝true。GD−C@10 單位 W:L 2:2，20 個單位中不一致 4 個。
- **結案**：方向檢查未過，依事先規則停止，不構成無效證據（OLD31 單位 W:L＝2:2）。依 §6、§10：不出 HO，不跑 E2；不再開新的單發圖譜變體。E3 只決定能不能開始 prod 化，結案後沒有作用，不跑。OLD31 原始分數照 §6 封存在 store，未讀。
