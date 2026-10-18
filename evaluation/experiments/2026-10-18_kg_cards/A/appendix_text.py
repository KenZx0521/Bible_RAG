"""Fixed prose of repo A/appendix_A.md (rules written before any generation). No verse text, no TIPNR."""

ALIAS_RULE = """以註腳補別名時（text 層 footnotes.jsonl，`^(又名|就是)名$`，anchor 為 null），一律只綁出現處，
名稱不聯集。被綁的詞必須是該節已比對到的王位公式句裏的王名位置，依序取第一個不等於註腳名的：
(1) 繼位句的繼任者（P_SUCC／P_SEAT／P_REPL 的 s）；(2) 登基位置（P_ACC1、P_ACC_REV 的 nn，P_ACC0、
P_AGE 帶名者）；(3) 同步紀年的參照王（P_ACC1、P_ACC_REV、P_ACC_SUCC_SYNC 的 rn，P_COUP_SYNC 的 nn／rn）。
父名位置（rf、nf、pf）、同睡句、在位句不算。「就是X」另要求該位置的王與 X 解析到的王同國；X 解析
不到就拒絕。該節沒有合格位置就拒絕並記 log（fn_alias_rejected）。其餘建層步驟與探針 occ 政策逐字相同。"""

ARMS_SPEC = """- 種子（階段 1，每題 1 次，各臂共用）：`seeds_a.py` 的 SEED_SYSTEM／SEED_USER，輸入題目＋基底 context
  （對 prereg「讀題目」的補充，見 A.9），輸出「國別｜王名」最多 2 行。parse_seeds 先 NFKC、去掉「國別：」「王名：」
  標籤與 Markdown 表格列外側的「|」，再取前 2 個可解析的（國別, 名）；engine.resolve 以名稱或別名＋國別在 G-auto、
  G-ref 層各自解析，同國同名只用題目的「F的兒子name」或「name（F的兒子）」分開，分不開就不解析。
- G-auto／G-ref：`engine.py`。讀種子 ±3 位與 born_under 往回走到的列；推導行＝第 k 位繼位（k=±1..±3，
  附該王父、在位、登基歲數）、種子之後 +3 內第 n 個篡位者、出生時在位、兩個同國種子相隔幾代。沒有任何推導行＝棄權
  （不出 job，計分沿用該題 T-rows：G-auto 同 rep，G-ref 用 rep 1）。列與推導行合計 ≤900 字，超過先刪離種子最遠的列。
- T-rows：同一批（刪完後的）列，不給推導行；列＝國別王名（又稱）：父；在位；登基歲數；母；繼位方式；於對方王第幾年登基。
- T-canon：`tcanon.py`。王上、王下符合 supply.py skel_re 的經節依正典排序；中心＝以種子字串搜尋的登基節，
  依 tier 順序（「name(在X)登基作K」→「name(在X)登基」且後面不是另一國→「name(在X)作K王＋年數」→「name(在X)作王＋年數」
  →「K王name」→ name），同一 tier 內取正典順序第一個；名稱須是 text 層 PDF 專名 span 的完整範圍；題目附「（F的兒子）」時
  先要求該節含「F的兒子name」。兩種子先取兩中心之間（放得下時），再後、前交替加節；某一側下一節會超過 900 字或已無經節，
  就改加另一側，兩側都加不了才停。每節前標 王上／王下 章:節，窗內「又名／就是」註腳接在該節後。
- B0：無輔助資料區。所有 stage-2 prompt＝cards_common.build_user（SYSTEM_PROMPT）；次數 G-auto、T-canon、T-rows、
  B0 各 rep 1–2，G-ref rep 1；順序 rep → 題 → 臂，臂序依題序輪替；job_id 例 `A|SUC_01|T-rows|1`。"""

SCORE_SPEC = """- 答案文字（`score_a.answer_text`）：NFKC，刪 Markdown 符號（星號、底線、井號、反引號、>），取最後一個「答案：」之後到第一個空行為止的
  文字；每行先刪行首清單記號（`-`、`1.`、`(1)` 等），再依 cards_common.norm 去空白，多行以「;」相接。沒有「答案：」、
  done_reason=length、或 prompt_eval_count+eval_count ≥ num_ctx（取 run_meta 的 num_ctx），記格式失敗 0。
- 名鍵：參照層全部王名與別名（加該題名鍵）的最長匹配斷詞（亞撒不會在亞撒利雅裏命中）。名字緊接在「另一國＋王」
  （可夾「X的兒子」）之後，視為另一國的王：不算命中，也不算陷阱。gold 王名若同國另有一王也叫此名（耶羅波安、約哈斯），
  答案寫出那位王的父親（「F的兒子name」「name（F的兒子）」「name，父F」，前面不是「不是／並非」）就記未命中。
- 數字鍵：數值須帶單位（年、歲、日／天，可夾「個」），前面不是「第」；先刪引文（`章:節`、`N章N節`）。
- 詞鍵：答案文字含任一可接受子字串，且不符合排除式。SUC_02 死因 焚／火；N_SUC_05 死因 殺／弒（排除「不是被殺」類否定）；
  N_KIN_14 曾祖／曾孫，排除「約西亞的曾孫」「希西家的曾祖」（方向相反）與「不是曾…」。
- 陷阱：答案文字刪括號、再刪 gold 王與種子王的父名片語（「F的兒子」接在該王名前、「，父F」接在該王名後）之後，
  出現參照層同國王名或別名、不是另一國前綴、又不在豁免名單者，該次記 0。豁免＝種子與 gold 王的名與別名、名鍵；
  自然題另加 dev_eval 的 walk 路徑（A.3）。模板題的路徑中間王不豁免（prereg：模板題只有 1 鍵）。
- 模板題 gold＝參照層答案王；可接受寫法＝其名與別名，但別名若是同國另一王的主名就不收（避免錯答算對）。
- a＝G-auto 出手且推導行冒號後的內容涵蓋該題全部鍵的題比例（arms_meta a_hit，prereg 字面）；h＝這些題 G-auto
  題層平均；pR、pC＝T-rows、T-canon 題層平均。代入 powerA_strong.cell 前，h（無 a 題時取 0）、pR、pC 各夾到
  [0.01, 0.99]，gap＝夾後 pR−夾後 pC（powerA 的 logit 在 0、1 無定義；報告同列原值與夾後值）。
- 描述（不進判定）：a_strict＝只看題目所問那一行（items 的 asked，掛在對應參照種子的 auto 節點上）；T-canon 窗是否含
  鍵的全部依據公式節，以及含齊的題上的 pC、pR；種子截斷與種子解析不到的題。"""

GUARDS = """- `seeds`、`arms` 先讀 store `A/k0_status.json`；檔案不存在就拒跑。smoke（`--items` 加 `--out-dir`）要 K0_1、K0_2
  的 pass=true；正式跑（A/ 本身）另要 K0_3 pass=true，且 K0_3.num_ctx 等於這次的 `--num-ctx`。格式：
  `{"K0_1":{"pass":true,...},"K0_2":{"pass":true,...},"K0_3":{"pass":true,"num_ctx":N,...}}`。
- 正式跑必須帶 `--num-ctx`；只有第一次 smoke（用來讀 /api/ps 的 context_length）可以不帶。
- 同一目錄續跑：`run_meta_<seeds|arms>.json`（開跑前就寫）的 options 或 prompts sha256 與這次不同就拒跑，
  有輸出卻沒有 run_meta 也拒跑；換 num_ctx 重跑 smoke 必須換目錄。
- `arms`：seed 與 arms 的 options 必須相同；每題的 seed job 都要有結果，否則拒跑（Ollama 例外先重跑 seeds）。
  seed 呼叫截斷＝格式失敗（prereg §1），視為沒有種子：G 棄權、T-canon／T-rows 區塊為空，記入 arms_meta 與報告。
- `score`：num_ctx 取 run_meta_arms.json；正式目錄沒有 num_ctx 就拒絕計分；smoke 沒有 num_ctx 時要帶 `--num-ctx`
  （/api/ps 的 context_length）。`trunc` 子命令列出一個目錄所有呼叫的截斷數與最大 token 數，供 K0-3。
- `analyze` 判「作廢」：k0_status.json 缺檔或 K0_1–K0_3 任一不是 pass=true、缺 seed 或 arm job、缺 run_meta、
  seed 與 arms 的 options 不同、arms_jobs.json 與 run_meta 的 prompts sha256 不符。"""

READINGS = """1. 自然題答案鍵：prereg 寫「依 FP 探針 dev_eval 的 walk／lookup 鍵凍結」。本附錄取其中題目所問的項目計分，
   其餘 walk／lookup 王名（A.3 的 walk 路徑）只豁免陷阱、不計分。理由：作答指示要最後一行只寫答案，未問的中間王當鍵，
   量到的會是答案行寫得多長。若 Kay 要照字面全列，SUC_01 加 約阿施，SUC_02 加 心利，N_SUC_01 加 比加轄、比加、何細亞，
   N_SUC_05 加 瑪拿西，N_TO_08 加 8 歲、亞們、2 年、55 年，N_KIN_14 加 亞們、瑪拿西；須在任何生成前改。
2. 陷阱：prereg 寫「鍵以外的同國王名」。A.5 另豁免種子名、gold 別名、gold／種子王的父名片語、另一國前綴的名字，
   以及自然題的 walk 路徑；模板題答案行列出整條鏈仍記 0。
3. 數字鍵要帶單位、不算「第N年」；SUC_02 的 7 依經文是七日。
4. 答案文字取最後一個「答案：」之後的整段（到空行），對應 prereg「最後一個『答案：』之後的文字」；
   cards_common.answer_line 只取一行（實驗 B 照舊）。
5. 種子 prompt 除題目外也給基底 context（各臂共用）。
6. powerA 輸入夾到 [0.01, 0.99] 是固定值，不依呼叫數調整。
7. T-canon 中心沿用 tier 優先；審查建議的「正典順序最早的登基節」會把以色列王約阿施、耶羅波安（約阿施的兒子）、
   猶大王亞哈謝的中心放到另一位同名王的經節（2ki.11.21、1ki.14.20、1ki.22.51），所以不採用。
8. T-canon 是 900 字的正典窗，dry-run 有 11/30 題缺依據公式節（A.7）；FP 檢定力模型假設 T-canon 拿得到完整事實。
   K-S0-2 用實測 pC，含齊子集的 pC 另列描述。要不要加強 T-canon 留給 Kay。"""

CORRECTIONS = """- K0 gold 核對（另一位 agent，store A/k0_verify/verify_A.json）：K0-1 40/40、K0-2 錯綁 0；模板 24 題 gold 全對，不改。
  自然題依經文補正：SUC_02 加死因詞鍵（焚／火，1ki.16.18），數字鍵 7 改帶單位「日／天」（1ki.16.15）；N_SUC_05 加死因
  詞鍵（殺／弒，2ki.21.23）。
- 審查 critical：powerA_strong.cell 在 h、pR 或 pC＝1.0 時 ZeroDivisionError（實測重現）→ A.5 夾值規則（analyze_a.clamp）。
- 審查 major（皆生成前修，未改層與卡片規則）：父名寫法誤判陷阱、同名王錯父仍得分 → A.5 父名片語與錯父規則；
  自然題中間王誤判陷阱 → walk 路徑豁免（A.9-1）；跨國同名王答錯國別仍得分 → 另一國前綴規則；
  「**答案**：」解析不到、多行答案只取一行 → answer_text；種子失敗靜默變棄權、續跑不檢查 options、K0 閘門沒強制
  → A.6 防呆；T-canon 窗缺依據節 → 描述欄位（中心規則不改，A.9-7、A.9-8）。
- 審查 minor：數字鍵吃到引文 → 單位＋刪引文；N_KIN_14 方向 → 排除式；a_strict 與 T-canon 覆蓋列描述；
  種子 parser 接受「國別：…｜王名：…」與表格列；T-canon 窗一側超限時改擴另一側。
- 影響：layer_auto.json、ref_layer.json sha256 不變，k0_fields_sample.json 逐位元相同；模板題題目、gold、鍵、context 不變；
  dry-run 的 stage-2 prompt 只有 N_SUC_01、T_S1_07 的 T-canon（窗多 1 節）改變，其餘 266 個逐字相同。"""
