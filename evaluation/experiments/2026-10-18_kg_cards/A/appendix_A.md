# 附錄 A：王朝年表推導卡 stage-0（2026-10-18，harness 建置時寫入，尚無任何臂的生成）

規格：`../prereg.md` §1、§2。資料只在 store `reports/kg_cards_20261018/A/`；本檔不含經文與自然題原文。

## A.1 層

- G-auto：`layer_auto.json` sha256 `932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab`（`layer_check.py`）。
- G-ref：`ref_layer.json` sha256 `79d57efe451f675b6d2c1163d801b2a173a24a1a8b1ed0ba6a207f698ca16660`（K/probe_C5/ref_layer.json 原檔複製）。
- fn_rule=probe 重建與 K/probe_C5/auto_layer_occ.json 逐欄相同：是。
- 改用下列別名規則後，只有 nodes（別名）、log、occ_alias 不同；邊、同步、欄位衝突相同：True；別名變動 [['A37', '約哈斯', ['亞哈謝'], []]]。

## A.2 別名修正規則（K0-2，寫死，不看題目）

以註腳補別名時（text 層 footnotes.jsonl，`^(又名|就是)名$`，anchor 為 null），一律只綁出現處，
名稱不聯集。被綁的詞必須是該節已比對到的王位公式句裏的王名位置，依序取第一個不等於註腳名的：
(1) 繼位句的繼任者（P_SUCC／P_SEAT／P_REPL 的 s）；(2) 登基位置（P_ACC1、P_ACC_REV 的 nn，P_ACC0、
P_AGE 帶名者）；(3) 同步紀年的參照王（P_ACC1、P_ACC_REV、P_ACC_SUCC_SYNC 的 rn，P_COUP_SYNC 的 nn／rn）。
父名位置（rf、nf、pf）、同睡句、在位句不算。「就是X」另要求該位置的王與 X 解析到的王同國；X 解析
不到就拒絕。該節沒有合格位置就拒絕並記 log（fn_alias_rejected）。其餘建層步驟與探針 occ 政策逐字相同。

- 對照參照層：探針 occ 綁定 7 筆、錯綁 3；本規則綁定 4 筆、錯綁 0、拒絕 4 筆（fn:2ch.20.26#1, fn:2ch.21.17#1, fn:2ch.22.6#1, fn:2ch.25.23#1）；節點別名 5 個、錯 0 個。
- 這條規則是在看過探針 7 筆綁定之後寫的（prereg 要求以寫死的規則修到 0）；寫成後才建題與 prompt。

## A.3 題與答案鍵（dev 30）

抽樣：random.Random(20261018)；S1 候選 136、S4 候選（steps_back≥2、決定）8；S1 補題 0。

| 題號 | 類 | 題目（模板題才列） | 國別 | 種子（參照層） | 鍵（可接受寫法） | 依據經節 | 基底 context |
|---|---|---|---|---|---|---|---|
| SUC_01 | natural | （自然題，原題見 store items.json） | I | I10 | 名 耶羅波安；數字 41（單位 年） | 2ki.10.35,2ki.13.9,2ki.14.16；2ki.14.23 | ps:2ki.13.1,ps:2ki.10.32,ps:2ki.15.8,ps:1ki.16.21,ps:1ki.16.29,ck:2ki.17.1~2ki.17.14,ps:2ki.14.23 |
| SUC_02 | natural | （自然題，原題見 store items.json） | I | I02 | 數字 7（單位 日／天）；詞 焚／火 | 1ki.15.28,1ki.16.6,1ki.16.10,1ki.16.15；1ki.16.18 | ps:1ki.15.25,ps:1ki.16.8,ps:2ki.15.8,ps:1ki.14.19,ps:1ch.29.26,ps:2ki.15.13 |
| N_SUC_01 | natural | （自然題，原題見 store items.json） | I | I16 | 名 以拉；數字 9（單位 年） | 2ki.15.22,2ki.15.25,2ki.15.30；2ki.17.1 | ps:2ki.15.17,ps:2ki.15.8,ps:2ki.15.23,ps:1ki.16.29,ps:2ki.15.27,ps:2ki.17.1 |
| N_SUC_05 | natural | （自然題，原題見 store items.json） | J | J13 | 名 亞們；數字 22（單位 歲）；數字 2（單位 年）；詞 殺／弒（排除方向相反或否定） | 2ki.20.21,2ki.21.18；2ki.21.19；2ki.21.19；2ki.21.23 | ps:2ki.15.1,ps:2ki.13.1,ps:1ki.16.21,ps:1ch.29.26,ps:2ki.23.31,ps:2ch.28.22 |
| N_TO_08 | natural | （自然題，原題見 store items.json） | J | J16 | 名 瑪拿西 | 2ki.22.1,2ki.21.19,2ki.21.24,2ki.21.1,2ki.21.18 | ps:2ch.36.1,ps:2ki.22.1,ps:2ki.8.16,ps:2ch.34.1,ps:1ki.22.41,ps:2ki.23.31 |
| N_KIN_14 | natural | （自然題，原題見 store items.json） | J | J16,J13 | 詞 曾祖／曾孫（排除方向相反或否定） | 2ki.20.21,2ki.21.18,2ki.21.24,mat.1.10,1ch.3.13,1ch.3.14 | ps:1ki.13.1,ps:2ki.20.1,ps:isa.38.1,ps:1ki.3.1,ps:2ki.21.1,ps:mat.1.1 |
| T_S1_01 | S1 | 以色列王沙龍之後的第二位以色列王是誰？ | I | I15 | 名 比加轄 | 2ki.15.13,2ki.15.14,2ki.15.22,2ki.15.23 | ps:2ki.15.13 |
| T_S1_02 | S1 | 猶大王亞哈謝之前的第三位猶大王是誰？ | J | J06 | 名 亞撒 | 2ki.8.25,1ki.15.24,1ki.22.50,2ki.8.24,1ki.15.9 | ps:2ki.8.25 |
| T_S1_03 | S1 | 以色列王暗利之後的第三位以色列王是誰？ | I | I06 | 名 約蘭 | 1ki.16.23,1ki.16.28,1ki.22.40,2ki.1.17,2ki.3.1 | ps:1ki.16.21 |
| T_S1_04 | S1 | 猶大王亞們之後的第二位猶大王是誰？ | J | J15 | 名 約哈斯／沙龍 | 2ki.21.19,2ki.21.24,2ki.23.30,2ki.23.31 | ps:2ki.21.19 |
| T_S1_05 | S1 | 猶大王約哈斯（約西亞的兒子）之前的第三位猶大王是誰？ | J | J17 | 名 瑪拿西 | 2ki.23.31,2ki.21.18,2ki.21.24,2ki.23.30,2ki.21.1 | ps:2ki.23.31 |
| T_S1_06 | S1 | 以色列王約蘭之前的第二位以色列王是誰？ | I | I09 | 名 亞哈 | 2ki.3.1,1ki.22.40,2ki.1.17,1ki.16.29 | ps:2ki.3.1 |
| T_S1_07 | S1 | 以色列王米拿現之後的第三位以色列王是誰？ | I | I16 | 名 何細亞 | 2ki.15.17,2ki.15.22,2ki.15.25,2ki.15.30,2ki.17.1 | ps:2ki.15.17 |
| T_S1_08 | S1 | 以色列王心利之前的第三位以色列王是誰？ | I | I05 | 名 拿答 | 1ki.16.15,1ki.15.28,1ki.16.6,1ki.16.10,1ki.15.25 | ps:1ki.16.15 |
| T_S1_09 | S1 | 猶大王亞比央之後的第三位猶大王是誰？ | J | J02 | 名 約蘭 | 1ki.15.1,1ki.15.8,1ki.15.24,1ki.22.50,2ki.8.16 | ps:1ki.15.1 |
| T_S1_10 | S1 | 以色列王何細亞之前的第三位以色列王是誰？ | I | I19 | 名 米拿現 | 2ki.17.1,2ki.15.22,2ki.15.25,2ki.15.30,2ki.15.17 | ps:2ki.17.1 |
| T_S1_11 | S1 | 以色列王撒迦利雅之後的第二位以色列王是誰？ | I | I14 | 名 米拿現 | 2ki.15.8,2ki.15.10,2ki.15.14,2ki.15.17 | ps:2ki.15.8 |
| T_S1_12 | S1 | 猶大王約雅敬之前的第二位猶大王是誰？ | J | J18 | 名 約西亞 | 2ki.23.36,2ki.23.30,2ki.23.34,2ki.22.1 | ps:2ki.23.35 |
| T_S1_13 | S1 | 以色列王心利之後的第三位以色列王是誰？ | I | I05 | 名 亞哈謝 | 1ki.16.15,1ki.16.16,1ki.16.28,1ki.22.40,1ki.22.51 | ps:1ki.16.15 |
| T_S1_14 | S1 | 以色列王比加轄之前的第三位以色列王是誰？ | I | I17 | 名 撒迦利雅 | 2ki.15.23,2ki.15.10,2ki.15.14,2ki.15.22,2ki.15.8 | ps:2ki.15.23 |
| T_S1_15 | S1 | 以色列王耶戶之後的第三位以色列王是誰？ | I | I10 | 名 耶羅波安 | 2ki.9.14,2ki.10.35,2ki.13.9,2ki.14.16,2ki.14.23 | ps:2ki.9.14 |
| T_S1_16 | S1 | 以色列王約蘭之後的第三位以色列王是誰？ | I | I09 | 名 約阿施 | 2ki.3.1,2ki.9.14,2ki.10.35,2ki.13.9,2ki.13.10 | ps:2ki.3.1 |
| T_S1_17 | S1 | 以色列王亞哈之後的第二位以色列王是誰？ | I | I07 | 名 約蘭 | 1ki.16.29,1ki.22.40,2ki.1.17,2ki.3.1 | ps:1ki.16.29 |
| T_S1_18 | S1 | 以色列王沙龍之前的第三位以色列王是誰？ | I | I15 | 名 約阿施 | 2ki.15.13,2ki.14.16,2ki.14.29,2ki.15.10,2ki.13.10 | ps:2ki.15.13 |
| T_S4_01 | S4 | 猶大王亞哈謝出生時，在位的猶大王是誰？ | J | J06 | 名 約沙法 | 2ki.8.25,2ki.8.26,2ki.8.24,1ki.22.50,2ki.8.17,1ki.22.42 | ps:2ki.8.25 |
| T_S4_02 | S4 | 猶大王約雅敬出生時，在位的猶大王是誰？ | J | J18 | 名 約西亞 | 2ki.23.36,2ki.23.34,2ki.23.30,2ki.23.31,2ki.22.1 | ps:2ki.23.35 |
| T_S4_03 | S4 | 猶大王約蘭出生時，在位的猶大王是誰？ | J | J05 | 名 亞撒 | 2ki.8.16,2ki.8.17,1ki.22.50,1ki.15.24,1ki.22.42,1ki.15.10 | ps:2ki.8.16 |
| T_S4_04 | S4 | 猶大王希西家出生時，在位的猶大王是誰？ | J | J13 | 名 約坦 | 2ki.18.1,2ki.18.2,2ki.16.20,2ki.15.38,2ki.16.2,2ki.15.33 | ps:2ki.18.1 |
| T_S4_05 | S4 | 猶大王約雅斤出生時，在位的猶大王是誰？ | J | J19 | 名 約西亞 | 2ki.24.8,2ki.24.6,2ki.23.34,2ki.23.30,2ki.23.36,2ki.23.31,2ki.22.1 | ps:2ki.24.8 |
| T_S4_06 | S4 | 猶大王約西亞出生時，在位的猶大王是誰？ | J | J16 | 名 瑪拿西 | 2ki.22.1,2ki.21.24,2ki.21.18,2ki.21.19,2ki.21.1 | ps:2ki.22.1 |

自然題鍵的依據（dev_eval Q 表，K0 更正後）：

- SUC_01：Q: kth_succ I10 +3 → I13 (walk), reign 41 (lookup); father 約阿施 not asked: a wrong father (尼八) voids the name；豁免（walk 路徑）I10,I11,I12,I13
- SUC_02：Q: nth_usurper_after I02 (2, I05) (walk), reign 七日 (lookup, unit 日), death 自焚 (lookup, term 焚／火; K0 gold correction)；豁免（walk 路徑）I02,I03,I04,I05
- N_SUC_01：Q: edges I17→I18→I19 usurp (walk), father 以拉 and reign 9 (lookup)；豁免（walk 路徑）I16,I17,I18,I19
- N_SUC_05：Q: kth_succ J13 +2 → J15 (walk), age 22, reign 2, death killed (lookup, term 殺／弒; K0 gold correction)；豁免（walk 路徑）J13,J14,J15
- N_TO_08：Q: born_under J16 → J14 (walk); ages/reigns are the asked explanation (reasoning lines), the answer line asks the king；豁免（walk 路徑）J16,J15,J14
- N_KIN_14：Q: kth_succ J16 −3 → J13 曾祖父 (walk); the question asks a kinship term only; a reversed direction (約西亞的曾孫, 希西家的曾祖) or a negation misses；豁免（walk 路徑）J16,J15,J14,J13

模板題旗標：

- T_S1_07：same seed and answer king as natural item N_SUC_01 (different wording and context)
- T_S1_15：same seed and answer king as natural item SUC_01 (different wording and context)
- T_S4_06：same seed and answer king as natural item N_TO_08 (different wording and context)

- 基底 context：OLD31 用 MH/realkg/inputs_nogold.json 的 dk_sources（prod 回傳的 context 去標頭）；NEW82 用 graph_qd lanes.json 的 C5＋QD rep1 pid，模板題用參照層登基節（主同步節，否則登基歲數、繼位、開國、在位節）所在的 struct passage（pc:2ki.23.35 跨章有 2 個 passage，取含登基節的那個）。struct passages 與 realkg dk_sources 的 prod 內容逐字相同（314/316，另 2 個只差 title None／空字串）。
- 提比尼（王上 16:21–22）不算王：參照鏈心利→暗利；K0 gold 核對逐題確認（T_S1_13）。

## A.4 臂

- 種子（階段 1，每題 1 次，各臂共用）：`seeds_a.py` 的 SEED_SYSTEM／SEED_USER，輸入題目＋基底 context
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
  B0 各 rep 1–2，G-ref rep 1；順序 rep → 題 → 臂，臂序依題序輪替；job_id 例 `A|SUC_01|T-rows|1`。

## A.5 計分與 K-S0 輸入

- 答案文字（`score_a.answer_text`）：NFKC，刪 Markdown 符號（星號、底線、井號、反引號、>），取最後一個「答案：」之後到第一個空行為止的
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
  鍵的全部依據公式節，以及含齊的題上的 pC、pR；種子截斷與種子解析不到的題。

## A.6 執行防呆

- `seeds`、`arms` 先讀 store `A/k0_status.json`；檔案不存在就拒跑。smoke（`--items` 加 `--out-dir`）要 K0_1、K0_2
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
  seed 與 arms 的 options 不同、arms_jobs.json 與 run_meta 的 prompts sha256 不符。

## A.7 Prompt 與 job（dry-run，gold 種子，未呼叫 Ollama）

- 種子 system sha256 `5405fbb037d50d16603adef0909be68ed1947f30f149b3f9820b0e6f57026abd`；種子 user 模板 `dd00c3dfc2f6c30d980b110df66c4065d134339410f6dbf2e79bd060db114d62`。
- 生成 system（cards_common.SYSTEM_PROMPT）`f58c03fa9dfbdfbded1c4c6a01c72c5129078f54cdade009299448bb28ddfa54`；user 模板 `677e91e5d33a0791a67007785f5993db8f62e4241bb62378ca639891f44328b8`。
- 全部 seed prompt 合併 sha256 `84e32f9a77811faf845839806e1b61e7306ce6ed57587a68084882d1554de684`；全部 stage-2 prompt `e73504f14a0c822e77354acb3372f834dafc699d45c240cc79a2e03304dcf969`（逐 job 見 store dry_run/prompt_sha256.tsv）。正式跑的 seed prompt 與 dry-run 相同；stage-2 prompt 取決於 gemma 的種子輸出，B0 與 dry-run 相同。
- job 數：seed 30；stage-2 270（{'G-auto': 60, 'T-canon': 60, 'T-rows': 60, 'B0': 60, 'G-ref': 30}，gold 種子下無棄權），共 300。正式跑的 stage-2 數＝270 減棄權。
- 附加字數（平均, 最大）：{'G-auto': (494.7, 867), 'T-canon': (877.5, 899), 'T-rows': (261.4, 339), 'B0': (0.0, 0), 'G-ref': (518.8, 886)}；user prompt 最大 5510 字。
- gold 種子下 a_hit 27/30、a_strict 27/30；T-canon 窗缺依據公式節 11/30 題（SUC_01, N_SUC_01, T_S1_02, T_S1_07, T_S1_09, T_S1_10, T_S1_15, T_S1_16, T_S1_18, T_S4_01, T_S4_03）。
- 計分自測（selftest_a.py，合成答案）：177/177 符合本附錄規則；各類 {'gold': [30, 30], 'gold+trap': [30, 30], 'bold marker': [30, 30], 'list block': [30, 30], 'numbers only in a citation': [4, 4], 'number with another unit': [4, 4], 'father phrase': [28, 28], 'wrong-father homonym': [3, 3], 'negated wrong father': [3, 3], 'walk path named': [6, 6], 'kinship direction': [1, 1], 'kinship reversed': [1, 1], "other kingdom's homonym": [7, 7]}。
- code sha256 見 store `inputs_manifest.json`。

## A.8 K0 檔（store A/）

- `k0_fields_sample.json`：G-auto 40 欄（Random(20261018)，母體＝臂上顯示的欄），附出處節與經文；門檻精確率 ≥0.95。
- `k0_gold_check.json`：30 題的鍵、gold、依據節與經文（自然題附原題答案或 key_points）。
- `layer_check.json`：K0-2 別名核對；`dry_run/summary.json`：附加字數、prompt 字數、job 數、計分自測。

## A.9 對 prereg 字面的解讀與補充（生成前寫定，請 Kay 確認）

1. 自然題答案鍵：prereg 寫「依 FP 探針 dev_eval 的 walk／lookup 鍵凍結」。本附錄取其中題目所問的項目計分，
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
   K-S0-2 用實測 pC，含齊子集的 pC 另列描述。要不要加強 T-canon 留給 Kay。

## A.10 更正紀錄（harness 建置後、任何生成前）

- K0 gold 核對（另一位 agent，store A/k0_verify/verify_A.json）：K0-1 40/40、K0-2 錯綁 0；模板 24 題 gold 全對，不改。
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
  dry-run 的 stage-2 prompt 只有 N_SUC_01、T_S1_07 的 T-canon（窗多 1 節）改變，其餘 266 個逐字相同。
