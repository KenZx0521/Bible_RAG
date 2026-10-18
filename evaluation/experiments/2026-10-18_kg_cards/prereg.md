# 生成端圖譜計算卡 stage-0：事前登記（2026-10-18）

依據：store `reports/kg_niche_20261018/kgniche/final_plan.md` §3（下稱 FP；FP 的 K＝store `reports/kg_niche_20261018/kgniche/`）。本檔 commit 後才建 harness；harness 與附錄 commit 後才呼叫 Ollama。看到任何臂的答案後，判定與界線都不改。程式只修基礎設施錯誤，修了記在文末「執行紀錄」。

## 0. Kay 2026-10-18 裁決（照建議）

- **D2**：程式在顯式邊上做 ≥2 步走訪或計算，必須同時贏文本雙胞胎（H1）與「LLM 讀同一份邊／層列」雙胞胎（H2），才記為圖譜操作。只過 H1，記「結構化表加程式計算有效，未證明圖譜操作」。
- **D3**：有序王朝鏈上的 k 步走訪、區間累加算圖譜操作，前提是 H2 過關。
- **D4b／D4c**：A 的王朝層開窄版實驗層例外：只用 regex 建、只放 store `reports/`、不進 release、可刪。A 的卡片在生成端注入 context 以外的事實。B 只讀既有的 MH kin 三元組，不建層（D4a）。
- **D5**：獨佔 Ollama 約 2.5 小時，可拆成兩段。
- **D8**：TIPNR 只當 B 的開發量尺，只存 store，不進 repo，也不進任何層。
- **D1**：沒有單獨提問。Kay 同意開跑，視為接受「生成端答案層顯著」算「某處」。上 prod 另需 500 題答案層非劣性。
- 本次只跑 stage-0，也就是開發集的 go/no-go，不構成證據。盲集確認（D6、D7）等 stage-0 結果出來，再請 Kay 授權。

## 1. 共同設定（`cards_common.py`）

- **生成**：Ollama `gemma4:e4b-it-q8_0` /api/chat，temperature 0.1、num_predict 10000，與 prod backend env 相同。主機直連 localhost:11434，不經 backend。
- **Prompt**：所有臂共用同一個 system prompt 和同一個 user 模板。
  - system prompt：prod `SYSTEM_PROMPT`，規則 1 放寬為「經文段落與輔助資料」。
  - user 模板：prod `CONTEXT_TEMPLATE` 的經文區，加「以下是輔助資料（依經文整理）：」區，再加作答指示「請先逐步列出推理，最後一行只寫『答案：』加上答案」。
  - B0 沒有輔助資料區。輔助資料區的標籤所有臂相同，不揭露臂名。
- **共同 K0（截斷）**：每次呼叫記 prompt_eval_count、eval_count、done_reason。開跑前先用 3 題做 smoke，以 /api/ps 讀 context_length。
  - 只要有 prompt_eval_count+eval_count ≥ context_length，或 done_reason=length，就是截斷。所有臂一律明確設定同一個 num_ctx 後重跑 smoke，再正式跑。
  - 正式跑中仍截斷的呼叫，記格式失敗。
- **順序與重做**：每個 rep 內逐題進行，臂的順序依題號輪替。Ollama 例外（逾時、連線）自動重做，最多 3 輪，不算結果。
- **計分前處理**：答案行＝最後一個「答案：」之後的文字。沒有答案行就是格式失敗，記 0。
  - 正規化：NFKC、去掉 Markdown 符號，國字數字轉成整數。
  - 陷阱檢查前，先刪除括號內的文字。
- **統計**：`src.ab_stats` 精確或 Monte Carlo sign-flip；bootstrap 95% CI，10000 次、seed 20261018。stage-0 的數字只用來判 go/no-go，報告時一律標「開發集」。
- **輸出**：store `reports/kg_cards_20261018/{A,B}/`。

## 2. 實驗 A：王朝年表推導卡（FP §3 實驗 A）

- **層**：
  - G-auto：純 regex 王朝層，用 FP 探針 `auto_layer.py` 的 occ 別名政策建。
  - G-ref：人工參照層 `ref_layer.json`，只稱「理想上限」。
  - 兩層都只放 store。
- **題（dev 30）**：
  - 自然題 6 題：SUC_01、SUC_02、N_SUC_01、N_SUC_05、N_TO_08、N_KIN_14。
    - 基底 context：OLD31 用 realkg `dk_sources`；NEW82 用 graph_qd `lanes.json` 的 C5＋QD rep1 段（QD@6）。
    - 答案鍵依 FP 探針 dev_eval 的 walk／lookup 鍵凍結（附錄 A）。
  - 模板題 24 題：從參照層可決定的候選題中以 seed 20261018 抽出。
    - S1「某王之前／之後第 k 位王」k∈{±2,±3}，18 題；S4「某王出生時在位的王」（往前 ≥2 步），6 題。
    - gold 由參照層產生，再對照經文逐題核對。
    - 基底 context：種子王登基公式節所在的 struct pericope。
- **種子**：gemma 讀題目，抽王名與國別一次，各臂共用。
  - G-auto 用 auto 層的名稱與出現處別名解析，G-ref 用參照層解析。
  - T-canon 用經文字串搜尋定位，不讀層。
- **臂**：附加區塊上限 900 字，各臂相同，實際字數都要報告。
  - **G-auto**（現況可建圖譜臂）：T-rows 的同一批層列，加上引擎算出的推導行。推導行涵蓋繼位第 k 位（k=±1..±3）、篡位序、出生時在位，以及兩個種子之間相隔幾代。推導行只依種子產生，不依題型。引擎棄權時（無推導行），G-auto 沿用該題同 rep 的 T-rows 生成。
  - **T-canon**（主非圖譜雙胞胎）：取列王紀上下的登基公式節，依正典順序排列，以種子王的登基節為中心，向兩側交替擴張到 900 字，並附該窗內經節的註腳別名。不建層，不用圖。
  - **T-rows**（歸因雙胞胎）：G 引擎實際讀到的層列，包括種子王前後各 3 位的國別、名、父、在位年數、登基歲數、母、同步紀年，依鏈序平鋪，不給推導行。
  - **B0**：沒有附加區塊。
  - **G-ref**：參照層跑同一個引擎，只稱理想上限。
  - PoT 不跑。
- **次數**：G-auto、T-canon、T-rows、B0 各 2 次，G-ref 1 次。
- **指標**：key_score＝答案行命中答案鍵的比例；模板題只有 1 鍵。若答案行出現鍵以外的同國王名（陷阱），該題記 0。每題取各次的平均。
- **K0（CPU，叫 Ollama 前）**：任一不過，A 就停。
  1. G-auto 隨機抽 40 欄，對照經文核對，精確率 ≥0.95。
  2. 別名只綁出現處，名稱不得聯集。occ 政策目前錯綁 3/7：以附錄 A 寫死的規則修到 0 錯綁；修不到就關閉別名。
  3. 共同截斷檢查。
- **K-S0（判定）**：任一成立就停，記「依事先規則停止，不構成無效證據」。
  1. dev 30 題上 G-auto−T-rows 的平均 <+0.22。
  2. 把實測值代入 FP `synth/powerA_strong.py` 的 `cell(C=12, m=3, a, h, pR, gap=pR−pC, nsim=500)`，pow_H1_and_H2 <0.7。實測值定義如下：
     - a＝引擎出手且推導行含全部 gold 鍵的題比例；
     - h＝這些題上 G-auto 的 key_score 平均；
     - pR＝T-rows 平均；
     - pC＝T-canon 平均。
- **過關**：只表示可以請 Kay 授權確認集。確認集的 K-U、K1、K2、K3、出題前配額，照 FP 原文。
- **描述**（不進判定）：G-auto−T-canon、G-auto−B0、G-ref−G-auto、自然題與模板題分開、錯答率、格式失敗率、各臂附加字數。

## 3. 實驗 B：段內家譜走訪卡（FP §3 實驗 B）

- **題（dev 48）**：
  - 先選 dev pericope：C1 純文字框 169 個 pericope 中，有 FP `probe_C1/items_eval.json` 題目的，依書卷分層，以 seed 20261018 保留 12 個。
  - 再從這些 pericope 的 TIPNR 機械題中，依題型分層抽 48 題：旁系 UNC＋COU ≥20 題，其餘為 LIN2–4、SEQ、MGF、PGM、FIL、DIL。
  - 題目文字、答案鍵與陷阱鍵依附錄 B 的模板凍結。LIN 類是單錨點問人名，其餘是雙錨點問稱謂，與探針相同。
  - 先核對 20 題 gold，對照經文；核錯的題換掉並記錄，揭露為單人判讀。
  - 基底 context：探針的 R5，強制含 gold 單位，加 BGE-M3 近鄰，偏樂觀。
- **錨點**：gemma 讀題目抽一次，各臂共用。
- **臂**：
  - **G**：〔完整邊表〕＋〔程式卡 ≤6 行〕。
    - 邊表＝context 經節的全部 MH kin 三元組，依經節排序，不挑、不截斷。
    - 程式卡依 FP `probe_C1/card.py` 的規則：同名阻擋、最短路徑平手就棄權、≤5 跳 BFS 加 LCA 稱謂合成。
  - **T-1hop+CoT**（決定歸因）：同一份邊表，加上 gemma 第一段讀 context 與邊表寫出的世代鏈 ≤6 行；第二段再作答。
  - **T-LLM**（主非圖譜雙胞胎）：gemma 第一段只讀 context 寫出的世代鏈 ≤6 行，第二段作答，不給任何邊。
  - **B0**：沒有附加區塊。
  - **G-oracle**：TIPNR gold 關係改寫成表層三元組，套同一套卡片規則，只稱理想上限。
  - 槽位的行數與字數上限三臂相同，由 K0 以 dev 卡片的最大長度定。
- **棄權**：G 棄權的題，每個比較都改用該比較臂自己的生成，所以差值為 0。另報只看出手題的結果。
- **次數**：G、T-1hop+CoT 各 2 次；T-LLM、B0、G-oracle 各 1 次。
- **指標**：答對＝答案行含全部答案鍵，而且不含任何陷阱鍵。每題取各次的平均。gold 只需一條邊的卡片路徑標為查表層，另外報告。
- **K0（CPU，叫 Ollama 前）**：任一不過，B 就停。
  1. 抽 40 張出手卡，對照經文核對，精確率 ≥0.85。
  2. 實測邊表與卡片的字數，定出槽位上限。
  3. 共同截斷檢查。
- **K-S0（判定）**：任一成立就停，記「依事先規則停止，不構成無效證據」。
  1. pT ≥0.65。pT＝T-LLM 平均。
  2. 分散題上，T-1hop+CoT 平均 ≥ 卡片答對率 −0.05。分散題＝gold 鏈在邊表裡不是連續行的題；卡片答對率＝卡片出手且稱謂或人名正確的比例。
  3. G 平均 ≤ B0 平均。
  4. 實測值代入 FP `verify_C1_power_cost/power_c1_v2.gen(32, 4, pT, a, adh, r, prec, 3)`，用 IUT（H1、H2 各自 `pflip` p<0.05，而且 Δ̄≥+0.05），300 次模擬的檢定力 <0.7。實測值定義如下（依該模型的參數語意）：
     - prec＝出手卡的正確率；
     - a＝dev 卡片出手率 ×0.82×(92/169)：檢索係數取樂觀端，乘上框內有題 pericope 的比例，這是寫死的保守折扣；
     - adh＝卡片正確的題上，(G−T-LLM)/(1−T-LLM)，用題層平均計算，截在 0–1；
     - r＝出手題上，(T-1hop+CoT−T-LLM)/(1−T-LLM)，用題層平均計算，截在 0–1。
- **過關**：只表示可以請 Kay 授權確認集，照 FP 原文。
- **描述**：G−T-LLM、G−T-1hop+CoT、G−B0、G-oracle−G、依題型分層、出手題子集、各臂附加字數。

## 4. 措辭（寫死）

- A、B 的 stage-0 只會寫成三種結果之一：
  - 「依事先規則停止，不構成無效證據」，並附停在哪一條；
  - 「開發集通過，請 Kay 授權確認集」；
  - 「作廢」（K0 或基礎設施）。
- 不寫「圖譜有效」，也不寫「圖譜無效」。
- A、B 都停時，FP §5 的分層說法照用。

## 附錄 A、附錄 B

harness commit 時寫入，當時還沒有任何 Ollama 呼叫。全文是 `A/appendix_A.md`（sha256 `09f63b4a…`）與 `B/appendix_B.md`（sha256 `5aa1395a…`），分別由 `A/appendix_a.py`、`B/b_appendix.py` 從 store 檔案產生。內容：題號與答案鍵表、模板、別名修正規則、臂規格、計分規則、prompt 與程式的 sha256、job 數。經文、自然題原文、TIPNR 衍生內容只放 store。

- **A**：job 300（seed 30、stage-2 270；正式跑扣掉棄權）。生成 system `f58c03fa…`、user 模板 `677e91e5…`、全部 seed prompt `84e32f9a…`、dry-run（gold 種子）全部 stage-2 prompt `e73504f1…`。K0-1 40/40、K0-2 錯綁 0。
- **B**：job 448（錨點 48、各臂 400；G、G-oracle 數依 gemma 錨點而定）。卡片 K0 36/40＋換題新卡 4/4＝40/44（0.909）。槽位上限 107 字、6 行。
- `cards_common.py` sha256 `ae9dc16c…`，與 a5966c1 相同。

## 執行紀錄

### 2026-10-18 生成前（harness commit 時，還沒有任何 Ollama 呼叫）

harness 由 workflow 經四步產生：建置、K0 核對、對抗審查、修正（wf_aba360bd-38c），之後第二輪對抗審查（wf_1f1d4f3d-187）。下面是對本檔字面的修訂與解讀，由主程序在任何生成之前定案。依 Kay「流程精簡」的偏好，不另外請簽核；Kay 若不同意，本次判定作廢重跑。

**共同**
- 答案行：先去掉 Markdown，再找最後一個「答案：」，否則「**答案**：」會被當成沒有答案行（§1 本來就要求去 Markdown）。A 取這個標記之後到第一個空行的整段（A.5）；B 取 `cards_common.answer_line` 的一行。

**A（附錄 A.5、A.6、A.9、A.10）**
- 自然題答案鍵只計題目有問的項目。dev_eval 的其他 walk/lookup 王名只從陷阱豁免，不計分（A.9-1）。理由：作答指示要求最後一行只寫答案，若把沒問的中間王也當鍵，量到的是答案行寫多長。
- K0 核對時補了兩把死因詞鍵：SUC_02 焚／火，N_SUC_05 殺／弒。數字鍵改為必須帶單位，SUC_02 是「七日」。依據節都已核對經文。
- 陷阱規則的豁免範圍：父名片語、同名王錯父、另一國前綴、自然題 walk 路徑（A.5）。模板題的答案行若列出整條鏈，仍記 0。
- powerA 的輸入 h、pR、pC 夾到 [0.01, 0.99]。原因是 logit 在 0 與 1 無定義，cell 會 ZeroDivisionError。
- T-canon 中心仍用 tier 優先。dry-run 有 11/30 題的窗缺依據公式節，所以 H1 是跟「同字數預算的經文窗」比，不是跟「拿到完整事實的文本」比。判定照舊，含齊依據節的子集另列描述（A.9-7、A.9-8）。
- 防呆：K0 檔、num_ctx、續跑 options 與 prompt sha、seed 完整性（A.6）。

**B（附錄 B14；B14.6 列出的事項）**
- 建置者另加三條題目有效性規則：錨點表層名在 pericope 對到超過 1 人就排除；雙錨點最短路徑命名出超過一種關係就排除；每個 pericope 上限 8 題。
- gold：48 題全部對照經文核對，比本檔規定的 20 題嚴格。錯 9 題，b19 另外是答案鍵錯；錯誤來源是 TIPNR 錯邊與探針的標籤對錯。修法是在 store `gold_fixes.json` 改邊與標籤，再按槽位換題，換題程序含第 3 層 fallback。換進來的 9 題與 4 張新卡由第二輪獨立判讀再核一次，全部正確。
- 分散題的定義：每一跳都在邊表裡定位到，但不是連續行，n＝14。有一跳找不到（unlocated）的讀法只列描述。
- 槽位上限＝max(K0 的 107 字, 正式錨點下 G 卡的最大字數)。
- 寫鏈指示加上「第一行就寫第一跳，不要前言、不要編號」。
- smoke 換 num_ctx 時，舊檔移到 `smoke/superseded/`，所有呼叫重發；ps.json 只在 context_length 等於 --num-ctx 時寫入。
- K0 核對看到三個卡片規則缺口，都不修，因為修了等於看核對結果調規則；方向對 G 不利。三個缺口：同名阻擋只看 ≥2 個父系父母；(U,S)→Um；母系旁系沒有稱謂。

**num_ctx（K0-3）的決定規則，在 smoke 前寫定**
- smoke1 照 §1 不帶 num_ctx，結束後馬上讀 /api/ps 的 context_length（C0）。
- smoke1 有任何截斷，或最大的 prompt_eval_count+eval_count ≥ 0.75×C0：N＝16384，換新目錄用 N 重跑 smoke；smoke2 還有截斷就 N＝32768。
- 都沒有：N＝C0。
- 正式跑一律帶 `--num-ctx N`。
- B 的 smoke 直接用 A 定出的 N：模型和預設 context 相同，C0 已在 A 的 smoke1 量過。B 的 smoke 在 N 下仍截斷，B 就改用 32768。

### 2026-10-18 Ollama 時段一（21:38 起）

- 環境：git HEAD 2f6694f；Ollama 0.32.5；backend 映像 bible_rag-backend:r2（release b20261008_e05d3e55）；開跑前 /api/ps 為空。完整紀錄在 store `run_env.json`。
- A smoke1（N_KIN_14、SUC_01、N_SUC_01；不帶 num_ctx）：3 個 seed 加 27 個 stage-2 呼叫，0 截斷，done_reason=length 0 次，最大 prompt+生成 5921 token。/api/ps 的 context_length C0＝131072。依上面的規則，N＝C0＝131072，不重跑 smoke；K0-3 通過（store `A/k0_status.json`）。只看了 token 數，沒有看答案內容。
- A 正式跑：seed 30/30、stage-2 270/270（沒有棄權），0 截斷，最大 prompt+生成 6240 token；22:12 完成。
- B smoke（`--num-ctx 131072`，3 題）：錨點 3 個、各臂 20 個呼叫，0 截斷，最大 5318 token。`k0_result.json` 寫入：卡片 40/44＝0.909，truncation_ok。
- B 正式跑：錨點 48/48、各臂 391/391，22:57 完成。Ollama 時段一共用約 1 小時 20 分（21:38–22:57），沒有用到第二段。

### 2026-10-18 stage-0 判定（照 §4 措辭，看結果後沒有改任何規則）

- **A：開發集通過，請 Kay 授權確認集。**
  - K-S0-1：G-auto−T-rows ＝ +0.525，門檻 +0.22。
  - K-S0-2：a＝0.867、h＝0.865、pR＝0.242、pC＝0.179，pow_H1_and_H2＝1.0，門檻 0.7。
  - 描述，開發集 30 題的各臂平均：G-auto 0.767、T-canon 0.179、T-rows 0.242、B0 0.017、G-ref 0.750。
  - 自然題 6 題：G-auto 0.417、T-rows 0.125、T-canon 0.312。模板題 24 題：0.854、0.271、0.146。
  - 拿掉陷阱規則重算（描述）：G-auto 0.783、T-rows 0.258、T-canon 0.329。
  - 模板題的 gold 與引擎同源，只能當開發集。
- **B：開發集通過，請 Kay 授權確認集。**
  - K-S0 1–4 都不成立：pT 0.292；分散題 T-1hop+CoT 0.179，卡片答對 0.571；G 0.302 對 B0 0.042；IUT 檢定力 0.823。
  - 代入值：出手 15/48、a 0.1395、prec 1.000、adh 0.833、r 0.000。
  - 描述，48 題：G−T-LLM +0.156，題層 p 0.008，9 群聚 p 0.125；G−T-1hop+CoT +0.188，題層 p 0.002，群聚 p 0.062。
  - 只看出手的 15 題：G 0.90、T-1hop+CoT 0.30、T-LLM 0.40。
  - 卡片只在 LIN、SEQ、UNC 出手；COU、DIL、FIL、MGF 都是 0 張。
- FP §2 第 2 步：盲集確認最多只開一條，A 優先。確認集（D6、D7）要等 Kay 另行授權；stage-0 不構成證據。
- 輸出、報告與 run_env 都在 store `reports/kg_cards_20261018/`（A/report.md、B/report.md）。
