# 附錄 B：實驗 B（段內家譜走訪卡）stage-0

由 `run_b.py dry-run` 依程式內的凍結表與 dry-run 數字產生；改程式就重跑。依據 prereg.md §1、§3。

## B1 dev pericope（12 個）

抽樣框：C1 純文字框 169 個 pericope，其中 probe_C1/items_eval.json 有題的 92 個。依書卷分層，按比例分配 12 個名額（最大餘數法；餘數相同時，依書卷代碼順序替每卷抽一次 random()，小者優先），再依書卷代碼順序在各卷內 rng.sample。rng＝random.Random(20261018)，同一個 rng 依序再用於抽題洗牌與題號排列。

| 書卷 | 分到 | 該卷有題 pericope |
|---|---|---|
| 1ch | 5 | 39 |
| 2sa | 1 | 5 |
| gen | 3 | 18 |
| jer | 1 | 5 |
| neh | 1 | 6 |
| num | 1 | 3 |

dev pericope：`pc:1ch.1.43`、`pc:1ch.2.25`、`pc:1ch.3.10`、`pc:1ch.9.17`、`pc:1ch.9.35`、`pc:2sa.21.1`、`pc:gen.11.27`、`pc:gen.5.1`、`pc:gen.9.18`、`pc:jer.35.1`、`pc:neh.3.1`、`pc:num.32.1`

## B2 抽題與配額

- 候選題：dev pericope 內 items_eval 的 10 種題型；SEQ 依 k 分成 SEQ3／SEQ4／SEQ5 三層。
- 選題只讀 pericope、書卷、題型與 gold 鏈（ids、表層名）；不讀 items_eval 的 PER、R5、Q5、R5g、PERg outcome 欄位，也不讀任何臂的結果。R5.units 只在選題後當 context 用。
- 題目有效性（不看結果）：錨點表層名在該 pericope 對到 >1 人 → 排除；雙錨點題在 gold 圖上≤5 跳的最短路徑若命名出兩種以上關係（同一人既是祖父又是公公之類）→ 排除；LIN 題錨點與答案同名 → 排除；題目文字重複 → 只留先抽到的。以上是基礎抽樣（v0 gold）的規則。
- 修正後 gold（B14）另加三條，用於檢查基礎 48 題與換題候選：題目裡的兩端人名仍是該人在修正後 gold 的表層名；gold 鏈每一跳都要是修正後 gold 的邊，方向與父母性別要和簽名字母一致（U＝唯一的男性父母、Um＝女性父母、D／Dm 同理、S＝配偶）；UNC／COU 的 b 要是男性（伯叔、堂兄弟表只適用男性）。
- 每個 pericope 上限 8 題。順序：(1) 各層依基礎配額在上限內抽，層的順序＝候選題所在 pericope 數少者先、再按候選題數，UNC 移到 COU 之後，且 UNC 配額提高為 20−COU 已抽數；(2) UNC（不足用 COU）補到 UNC＋COU ≥20；(3) 剩下名額依 REFILL 順序一次一題輪流補。(2)(3) 只有在上限內沒有候選題時才放寬上限，放寬時選題數最少的 pericope，並記錄。

| 層 | 基礎配額 | 基礎抽樣實抽 | 換題後 |
|---|---|---|---|
| UNC | 10 | 14 | 14 |
| COU | 10 | 6 | 6 |
| LIN2 | 4 | 5 | 5 |
| LIN3 | 4 | 4 | 4 |
| LIN4 | 4 | 4 | 4 |
| SEQ3 | 3 | 1 | 3 |
| SEQ4 | 3 | 3 | 3 |
| SEQ5 | 2 | 2 | 2 |
| MGF | 2 | 2 | 1 |
| PGM | 2 | 2 | 2 |
| FIL | 2 | 3 | 2 |
| DIL | 2 | 2 | 2 |

- 抽層順序：PGM → COU → UNC → MGF → DIL → FIL → SEQ5 → LIN4 → SEQ4 → LIN3 → SEQ3 → LIN2；REFILL：UNC → COU → SEQ3 → SEQ4 → SEQ5 → LIN2 → LIN3 → LIN4 → MGF → PGM → FIL → DIL
- 基礎抽樣放寬上限：無；換題見 B14。
- 候選題數（基礎 v0 gold → 修正後 gold）：UNC 59→47、COU 14→14、LIN2 93→83、LIN3 62→54、LIN4 48→40、SEQ3 62→54、SEQ4 48→40、SEQ5 39→31、MGF 2→1、PGM 2→2、FIL 6→4、DIL 6→4
- 換題後每個 pericope 題數：`pc:1ch.2.25` 11、`pc:1ch.3.10` 8、`pc:1ch.9.35` 7、`pc:2sa.21.1` 6、`pc:gen.11.27` 4、`pc:gen.5.1` 8、`pc:gen.9.18` 2、`pc:neh.3.1` 1、`pc:num.32.1` 1（群聚 9 個）
- 基礎抽樣每個 pericope 實抽：`pc:1ch.1.43` 1、`pc:1ch.2.25` 8、`pc:1ch.3.10` 8、`pc:1ch.9.35` 8、`pc:2sa.21.1` 6、`pc:gen.11.27` 4、`pc:gen.5.1` 8、`pc:gen.9.18` 2、`pc:neh.3.1` 1、`pc:num.32.1` 2
- 題號：48 題以 rng.sample 排列後依序編 b01–b48；執行依題號。

## B3 題目模板

- LIN2／LIN3／LIN4：`根據經文，{a}的{word}是誰？`，word＝祖父／曾祖父／高祖父；a＝ids[0] 的表層名。
- 其餘：`根據經文，{b}是{a}的什麼人？`，a＝ids[0]、b＝ids[-1]，表層名取 items_eval 的 surfaces。

## B4 稱謂題的答案鍵與陷阱鍵（命中任一可接受稱謂，而且不含陷阱稱謂）

| 題型 | 可接受 | 陷阱 |
|---|---|---|
| UNC | 伯父、叔父、伯叔、叔伯、叔叔、伯伯、父親的兄弟、父親的弟兄、父親的哥哥、父親的弟弟、父親的兄長、父親兄弟、父親弟兄 | 祖父、父親、堂兄弟、堂兄、堂弟、叔伯兄弟、伯叔兄弟、舅舅、舅父 |
| COU | 堂兄弟、堂兄、堂弟、堂親、堂哥、堂弟兄、叔伯兄弟、伯叔兄弟、伯父的兒子、叔父的兒子、伯叔的兒子、父親兄弟的兒子、父親的兄弟的兒子、父親弟兄的兒子、父親的弟兄的兒子 | 親兄弟、叔父、伯父、伯叔、叔叔、伯伯、表兄弟、表兄、表弟、表親 |
| SEQ k=3 | 曾祖父、曾祖、祖父的父親、父親的祖父、第三代祖先、第3代祖先、三世祖 | 高祖父、高祖、天祖、祖父、父親、曾祖母、祖母、曾曾祖父、曾曾祖、四世祖、五世祖 |
| SEQ k=4 | 高祖父、高祖、曾祖父的父親、祖父的祖父、父親的曾祖父、第四代祖先、第4代祖先、曾曾祖父、曾曾祖、四世祖 | 曾祖父、曾祖、天祖、祖父、高祖母、曾祖母、曾曾曾祖父、三世祖、五世祖 |
| SEQ k=5 | 天祖、天祖父、高祖父的父親、高祖的父親、曾祖父的祖父、祖父的曾祖父、父親的高祖父、第五代祖先、第5代祖先、曾曾曾祖父、五世祖 | 高祖父、高祖、曾祖父、曾祖、烈祖、祖父、高祖母、曾曾曾曾祖父、三世祖、四世祖 |
| MGF | 外祖父、外公、母親的父親、媽媽的父親 | 祖父、父親、岳父、舅舅、舅父、外祖母、外婆 |
| PGM | 祖母、奶奶、阿嬤、父親的母親 | 外祖母、外婆、母親、曾祖母、祖父 |
| FIL，a 為男性 | 岳父、岳丈、丈人、妻子的父親、妻的父親、太太的父親、配偶的父親、妃嬪的父親、妾的父親 | 公公、父親、祖父、外祖父 |
| FIL，a 為女性 | 公公、家翁、丈夫的父親、夫的父親、配偶的父親 | 岳父、岳丈、丈人、父親、祖父 |
| DIL，中間是兒子 | 媳婦、兒媳、兒媳婦、兒子的妻子、兒子的妻、兒子的太太、兒婦、兒女的配偶、兒子的妃嬪、兒子的妾 | 妻子、女兒、孫女、孫媳、孫媳婦、女婿 |
| DIL，中間是女兒 | 女婿、女兒的丈夫、女兒的夫婿、女兒的配偶、兒女的配偶 | 媳婦、兒媳、兒子、丈夫、孫女婿、外孫 |

FIL 依 a 的性別、DIL 依中間那一代（a 的子女）的性別選表；性別取 gold 來源人物描述第一個短語裡的女性名詞（B14）。

## B5 LIN 人名題的鍵

- 答案鍵：gold 祖先在該 pericope 的全部表層名，命中任一即可。
- 陷阱鍵：gold 鏈上中間各代，加上 gold 祖先的父親（若在該 pericope 有 gold 邊），各取全部表層名；與答案鍵或錨點同名者不列。錨點本人的表層名當中性字串。

## B6 比對規則

- 答案行＝先刪 Markdown 符號（*、_、#、`、>），再取 cards_common.answer_line（最後一個「答案：」之後），已做 NFKC、去空白；比對前答案行與所有鍵再去掉人名間隔點（U+2027、U+00B7、U+30FB、U+2022、U+2219、U+22C5）；沒有答案行、或呼叫被截斷（done_reason=length，或 prompt_eval_count+eval_count ≥ context_length），記格式失敗 0。階段 2 的階段 1 被截斷，也記格式失敗。
- 稱謂題先刪除 gold 鏈上所有人的表層名（長的先刪，換成空字串），讓「父親〔人名〕的兄弟」讀成「父親的兄弟」。
- 再把可接受、陷阱、中性字串合在一起，由長到短比對；比到的字串先遮掉，才比較短的（「曾祖父」先吃掉，「祖父」就不會再中；「叔父的兒子」先吃掉，「叔父」就不會再中）。
- 陷阱檢查用刪掉括號內文字的答案行（cards_common.strip_parens）；可接受鍵用完整答案行。
- LIN 題：context 經節裡含有答案名或陷阱名的其他人名（如甲乙丙含甲乙）列為中性字串，先被吃掉。
- 只描述、不進判定（score_b／analyze_b）：(a) 陷阱只比答案行第一個子句（第一個「，。；、」或「因為」「即」之前）的答對率；(b) 答對但可接受詞只出現在括號內的次數。判定一律用上面 prereg 的規則。

## B7 程式卡

- 規則照 probe_C1/card.py：同名阻擋（有 ≥2 個不同父系父母的名字不能當中繼；錨點被標記就棄權）、≤5 跳 BFS 最短路徑出現 ≥2 種正規化簽名就棄權、LCA 化簡。邊來源＝context 經節的 MH kin 三元組；經節依正典順序走訪（card.py 原本走 set，引用經節與同簽名平手時挑哪條路徑不固定）。
- 移植核對：dev 48 題用 gold 表層名模擬錨點時，移植版與 items_eval R5 卡的 status、棄權原因、簽名相同 48/48 題（只核對，不用來選題）。
- LIN：單錨點父系上溯 k 代（ancestor_card），k 由題目的「祖父／曾祖父／高祖父」讀出；其餘：pair_card。
- 卡片＝每跳一行（依走訪方向），最後一行是結論，≤6 行：

```text
甲的父親是乙（代上 1:20）   ← U
甲的母親是乙（…）          ← Um
甲的孩子是乙（…）          ← D／Dm
甲的配偶是乙（…）          ← S
甲與乙是手足（…）          ← B
結論：{a}的{祖父|曾祖父|高祖父}是{答案}      （LIN）
結論：{b}是{a}的{稱謂}                 （其餘）
```

- 稱謂由正規化簽名查表；表外的簽名用每跳的詞以「的」串起（父親的父親的兒子…）。MH 的 D 跳不帶子女性別：（D／Dm, S）寫「兒女的配偶」，其餘以 D 結尾的稱謂預設男性（兒子、孫子、伯父或叔父、堂兄弟）。
- K0 看到的三個卡片規則缺口沒有改（理由見 B14）：同名阻擋只看 ≥2 個父系父母；(U,S)→Um 假設父親的配偶是母親；(Um,Dm) 等母系旁系沒有稱謂。

| 正規化簽名（a 走到 b） | 稱謂 |
|---|---|
| 父 | 父親 |
| 母 | 母親 |
| 子（父出） | 兒子 |
| 子（母出） | 兒子 |
| 配偶 | 配偶 |
| 父、子（父出） | 兄弟 |
| 父、父 | 祖父 |
| 父、父、父 | 曾祖父 |
| 父、父、父、父 | 高祖父 |
| 父、父、父、父、父 | 高祖父的父親 |
| 母、父 | 外祖父 |
| 父、母 | 祖母 |
| 母、母 | 外祖母 |
| 父、父、子（父出） | 伯父或叔父 |
| 父、父、子（父出）、子（父出） | 堂兄弟 |
| 母、父、子（父出） | 舅舅 |
| 母、父、子（父出）、子（父出） | 表兄弟 |
| 配偶、父 | 配偶的父親 |
| 配偶、母 | 配偶的母親 |
| 子（父出）、配偶 | 兒女的配偶 |
| 子（母出）、配偶 | 兒女的配偶 |
| 子（父出）、子（父出） | 孫子 |
| 子（父出）、子（父出）、子（父出） | 曾孫 |

- 邊表每行：`甲是乙的父親（簡稱 章:節）`、`甲是乙的母親（…）`（role=M）、`甲與乙是夫妻（…）`、`甲與乙是手足（…）`；PARENT_OF 的 role P／F 都寫父親（與卡片的父系判定一致）。context 經節依正典順序、三元組依檔案順序，以 (head, rel, tail) 去重，不挑、不截斷；沒有邊寫「（無）」。書卷簡稱取 packages/ragcommon/data/books.json 的第一個 PDF 縮寫，沒有就取第一個口語縮寫。
- G-oracle：TIPNR gold（修正後，B14）的 parent／partner 關係，兩端在同一 context 經節都有對齊標籤者，改寫成同格式的表層三元組（probe_oracle_extract.py），套同一套卡片規則；只稱理想上限，不截斷卡片。G-oracle 的附加區塊用的是這份 TIPNR 邊表（不是 MH 邊表）加 oracle 卡。

## B8 臂與 prompt

- 所有生成 job：system＝cards_common.SYSTEM_PROMPT；user＝cards_common.build_user(context, 題目, aux_block)。context＝items_eval R5.units 的 ps:／ck: 單位，依 R5 順序，取 store struct@d8d432b4df15 的 passages／chunks，組成 prod build_context_blocks 的格式（chunk 內容照 backend/database/content.py chunk_content）。
- aux_block（「以下是輔助資料（依經文整理）：」之後）：

| 臂 | aux_block |
|---|---|
| G | `〔經文親屬關係〕`＋邊表＋空行＋`〔關係推算〕`＋程式卡 |
| T-1hop+CoT 階段 1 | `〔經文親屬關係〕`＋邊表；instruction 換成寫鏈指示 |
| T-1hop+CoT 階段 2 | `〔經文親屬關係〕`＋邊表＋空行＋`〔關係推算〕`＋槽位 |
| T-LLM 階段 1 | 無；instruction 換成寫鏈指示 |
| T-LLM 階段 2 | `〔關係推算〕`＋槽位 |
| B0 | 無 |
| G-oracle | `〔經文親屬關係〕`＋oracle 邊表＋空行＋`〔關係推算〕`＋oracle 卡 |

- 寫鏈指示（build_user 的 instruction 參數）：

```text
這一步先不要作答：只寫出與問題相關的世代鏈，最多 6 行，每行一跳，格式如「甲的父親是乙（書卷 章:節）」。第一行就寫第一跳，不要前言、不要編號。
```

- 槽位＝階段 1 輸出經 cards_common.fill_slot（前 6 個非空行，再截到上限字數）。G 的卡片也經同一個 fill_slot（卡片本來就 ≤上限，不會被截）。
- 槽位字數上限（三臂相同）＝max(K0 值, arms 子命令建 job 時正式錨點下 G 卡片的最大字數)：不低於 K0，也不會截到 G 卡片；兩個值都寫進 cards.json／arm_jobs.json。K0（dry-run，gold 表層名模擬錨點）＝107 字，行數上限 6。建 job 時還沒有生成任何臂。
- 不對稱（照 prereg 字面保留，報告時寫明）：G 的槽位最後一行是程式寫的「結論：」，T 臂階段 1 只寫世代鏈、不寫結論；所以 H2 量到的是程式走訪加稱謂合成，不只是走訪。
- 錨點（階段 1，kind=seed，每題一次，各臂共用）：

```text
system: 你是一個資訊抽取工具，只輸出要求的內容。
user: 請找出下面問題中的人名，最多 2 個。每行輸出一個人名，照問題中的原字，不要加編號、標點或其他文字。

問題：{question}
```

- parser：逐行去掉項目符號與首尾標點，以「、，,；;/ 空白」切開；出現在題目裡的詞排前面，取前 2 個。對到卡片子圖節點名：完全相同優先；否則去掉人名間隔點後相同且唯一；否則去掉間隔點後互相包含且唯一；都不成就保留原字（卡片因此棄權）。雙錨點題中，在題目裡位置較前的名字是 b、較後的是 a（模板「{b}是{a}的什麼人」），與輸出順序無關。G 與 G-oracle 各自對自己的子圖解析同一份輸出。
  dry-run 用 gold 表層名模擬（雙錨點題依題目順序輸出 b、a）。
- 次數與順序：rep 1 跑 G、T-1hop+CoT、T-LLM、B0、G-oracle；rep 2 跑 G、T-1hop+CoT。rep → 題 → 臂，臂的順序依題號（第 i 題左旋 i 位）輪替；兩段式臂的階段 1 緊接在其階段 2 之前。卡片棄權的題不生成 G（G-oracle 同）。

## B9 dry-run 實測（K0 數字）

| 項目 | 值 |
|---|---|
| 邊表字數（不含小標）min／中位／max | 92／1223.0／2347 |
| 邊數 min／中位／max | 5／69.0／123 |
| context 字數 max | 3639 |
| G 卡片出手（模擬錨點） | 18/48 |
| G 卡片字數 min／中位／max | 47／73.0／107 |
| G-oracle 卡片出手 | 28/48 |
| user prompt 字數 max（階段 2 以上限字數的槽位計） | 4969 |
| 分散題（gold 鏈已定位、非連續行） | 14 |
| gold 鏈版面 | {'scattered': 6, 'unlocated': 21, 'contiguous': 13, 'monotone': 8} |
| gold 每跳經節都在 context 內 | 是 |
| 基礎抽樣＝K0 已核的 v0 48 題（逐槽位） | True |
| job 總數（含錨點 48） | 448 |

各臂 job 數（模擬錨點；實際 G／G-oracle 數依 gemma 錨點而定）：

| 臂:種類:rep | 數 |
|---|---|
| B0:gen:r1 | 48 |
| G:gen:r1 | 18 |
| G:gen:r2 | 18 |
| GO:gen:r1 | 28 |
| T1C:gen:r1 | 48 |
| T1C:gen:r2 | 48 |
| T1C:stage1:r1 | 48 |
| T1C:stage1:r2 | 48 |
| TLLM:gen:r1 | 48 |
| TLLM:stage1:r1 | 48 |

## B10 分析定義（prereg §3 K-S0）

- 題分數＝該臂各 rep 答對的平均。G 棄權的題，每個比較都取比較臂自己的分數（差 0）。
- 分散題：gold 鏈每一跳以表層名（該人在 pericope 的全部表層名）在邊表裡定位，套 probe_C1/twin_struct.py 的分類；分散＝全部定位到、但不是連續行（monotone 或 scattered）。有一跳找不到（unlocated）不算分散，另外報告；描述另報「分散＋unlocated」「只有 scattered」「只有 unlocated」三種讀法。
- 描述另報：同鏈去重（每條 gold ids 鏈留題號最小的一題）的比較、群聚數、兩段式臂階段 1 的原始行數字數與被截比例。
- 卡片答對＝卡片出手，而且結論行用同一套鍵判為答對。
- adh、r 依題層平均：x̄、T̄ 分別是該集合上的臂平均與 T-LLM 平均，值＝clip((x̄−T̄)/(1−T̄), 0, 1)；集合為空記 0；1−T̄=0 時 x̄=1 記 1、否則記 0。
- a＝出手率×0.82×(92/169)；prec＝出手卡答對率；檢定力＝power_c1_v2.gen(32, 4, pT, a, adh, r, prec, 3) 300 次中，H1（G−T-LLM）與 H2（G−T-1hop+CoT）的 pflip p 都 <0.05 且平均差都 ≥0.05 的比例。
- 描述：src/ab_stats.py 的 bootstrap_ci（10000 次、seed 20261018）與 sign_flip_p（20000 次、seed 20261018），題層與 pericope 群聚兩種。

## B11 sha256

| 對象 | sha256 |
|---|---|
| SYSTEM_PROMPT | `f58c03fa9dfbdfbded1c4c6a01c72c5129078f54cdade009299448bb28ddfa54` |
| USER_TEMPLATE | `677e91e5d33a0791a67007785f5993db8f62e4241bb62378ca639891f44328b8` |
| ANSWER_INSTRUCTION | `09c4fa661675e42ff89ba827294f2398b8b95dcac5f812ff0942b4fe5f3517b6` |
| AUX_LABEL | `a56e9e78f9a04a42f6d695e9ba4175882098744ef66ce0b4a1489164d21f3b5b` |
| SEED_SYSTEM | `71b2f31528d65479c7cc68a735989103e1c5442f140803f56a749d58f5f26d58` |
| SEED_USER | `e3fabe8f1cce3838e5fe903e33b8373df9557cece010bb6f1ef14a7695e6be7f` |
| CHAIN_INSTRUCTION | `9616587e423a2f7f88da4e66023f871e5b1983838d6af6aab979a18c3d01725a` |
| TABLE_HEAD | `b12283e0a9f45dbde5b367761bdd6c891a7cbaa97f7c2551ea4355de930503a4` |
| SLOT_HEAD | `3259c72a9136d130e31c31ccb5029923e78f7381438a53baeb809499ced58cf5` |
| store B/items.json | `2586fc0c5008d097985c9285dc7ce4025aecd76283e8c02e5c65ab5e49c47539` |
| store B/seed_jobs.json | `a201f4f0f96a2aa5ec14fbec21b211bbe5025ef28c035917246238fe456f3372` |
| store B/gold_fixes.json | `556cce89d76a316a4513c7b4ec6aa1ecb7b3cebc3c4abddb4ee1afcf9894b70d` |
| store B/gold_exclusions.json | `ea89225b5cd534b73eb7c00d24cfe735df91960f2463bdb43415cc025ebcad8b` |
| store B/v0_k0checked/items.json（K0 已核的 v0） | `ebb175cdc0f1cce5cb8d1bf07dc2d3df3fdb8f015990400502681f46396c29cf` |
| code analyze_b.py | `bb76a0738c418760a70cd76cfdb38e5ba974d94f8f0941a5e00ae61a8f6a693a` |
| code b_appendix.py | `7b35048cc420d1ce644a254000d003a68aa06206af4b62aabecde57af8eb98c7` |
| code b_appendix_fix.py | `9a5a6664ef5cbcc81edc7e2cf1c7e88eba5763016cf528c161f6accbf90643dd` |
| code b_arms.py | `1a48ffdb0d1225f95b3f5d7f38de2e7d7940cb380f0149e2d1d60f25929cacc9` |
| code b_build.py | `a50acc89eadbee32c78f41249c6fee697168ac7f56d47e59167b3adbf41679f7` |
| code b_card.py | `8e54991356f3c2ef4fac17578f456fc44ea8ba2a9f89c856b75e0930b967b000` |
| code b_dryrun.py | `a9f49694dd3513f72cdf373c85bad6abe9106187bf0c068b120d273bd7a741b9` |
| code b_gold.py | `28ebaffe154b5fd229c593f11786840021fa97aa2ae8336f5a7be60531d2c0d9` |
| code b_items.py | `c516c450306e094bf3b7101d412576807484892e4f72b858863a3562138059a1` |
| code b_k0.py | `80469c48344f37d71477b572c1373684b02955d8591fe02f6f5139ca26bcec44` |
| code b_lib.py | `4a10ffd19750d3079e430995fa3a4607df1f3d99d2c6cf50f7b315789143c72a` |
| code b_terms.py | `7e6a185cc016a4970ebf9277e266469c1b980b84d61d6adcbe988cdecd2d97bc` |
| code report_b.py | `945c3567fc5c6661ae5576b98f965c67e330b7923f6e740f5fa1ce4cee8247f3` |
| code run_b.py | `a2652866f98b32c1ee29386edb5fa0f8072110e841cd3cb3dff7f90e97d0f923` |
| code score_b.py | `e18ce05680b70261624621dcef715cd17d12f15b2fc0d84a4faee2469f1b3ade` |
| code cards_common.py | `ae9dc16ceedad750a0ea0e2da0ec4db8098dfa4f58ae32820e84a567ed56acef` |

## B12 K0（CPU，叫 Ollama 前；任一不過 B 就停）

- 40 張出手卡（v0 規則：dev 出手卡在前，不足由框內其他有題 pericope 的題目依 Random(20261018) 洗牌順序補到 40；已人工核過，store v0_k0checked/）。改版後這 40 張用現行程式重畫，逐張比對卡片文字：相同 40、不同 0、不再出手 0；另加換題後新出手的 dev 卡 4 張。待核：b02, b17, b27, b48。審查檔 k0_cards_sample.json 不附自動判定（自動判定另存 k0_cards_auto.json，人工核完再看）。精確率門檻 ≥0.85。
- gold：prereg 的 20 題（Random(20261018).sample 48 個題號；題號是槽位，換題不改題號）＋審查建議的 48 題全核（k0_gold_check_all.json）。48 題狀態：相同 29、只補詞表 9、答案鍵改變 1、換題 9。待核（換題或答案鍵改變）：20 題中 b13, b17, b18；48 題中 b01, b02, b13, b17, b18, b19, b24, b27, b38, b48。單人判讀，揭露。
- 截斷：先用 `arms --smoke 3`（prompt 最長的 3 題、rep 1 全部臂），跑完自動存 /api/ps（smoke/ps.json）與截斷數（smoke/truncation.json）；有截斷就所有臂與錨點用同一個 `--num-ctx` 重跑 smoke：--num-ctx 和 smoke/smoke_ctx.json 記的不同時，舊 smoke 檔先移到 smoke/superseded/，所有 smoke 呼叫重發；/api/ps 裡模型的 context_length 不等於 --num-ctx 就不寫 ps.json（模型已卸載或仍以舊 ctx 載入，要移走 smoke/ 檔重跑）。之後 seeds／arms 只接受與 smoke 相同的 `--num-ctx`；score 沒有 `--ctx-len` 時讀 smoke/ps.json 的 context_length，兩者都沒有就拒絕；analyze 在 ctx_len 缺時判「未判定」。正式跑仍截斷的呼叫記格式失敗。

## B13 store 檔案（reports/kg_cards_20261018/B/，含經文與 TIPNR 衍生內容，不進 repo）

items.json、seed_jobs.json、dryrun.json、gold_fixes.json、gold_exclusions.json、k0_cards_sample.json、k0_cards_auto.json、k0_gold_check.json、k0_gold_check_all.json、v0_k0checked/（K0 已核的 v0 檔）、k0_verify/；之後 smoke/、seeds.jsonl、cards.json、arm_jobs.json、arms.jsonl、scores.json、report.json、report.md；人工 K0 結果寫 k0_result.json（cards_precision、truncation_ok…）。gold 再有錯：錯邊或錯標籤寫 gold_fixes.json，個別題 uid 寫 gold_exclusions.json，重跑 dry-run（只換該槽位，見 B14）。

## B14 更正紀錄（2026-10-18；依建置、K0 核對、審查三份結果；都在任何臂生成之前）

K0 卡片精確率已過門檻（40 張 36 張正確＝0.90，store k0_verify/k0_verify_independent.json），沒有為了 K0 改層或改卡片規則。以下是 gold、答案鍵與 harness 的更正。

### B14.1 gold 更正（store gold_fixes.json：邊 5 條、標籤 1 條；sha256 見 B11）

- 錯邊 2 條（所有 pericope）：TIPNR 把一條四代直系鏈壓平成同一父親的兄弟（代上 8:37、9:43），pc:1ch.9.35 的 5 題因此答案鍵錯（正確答案正好列在陷阱裡）。
- 本段沒寫的邊 2 條（只在 pc:num.32.1）：民 32:11 只是三位先祖並列；題目錨點的表層名在本段指民族。
- 本段沒寫性別的母系邊 1 條（只在 pc:1ch.1.43）：代上 1:50 字面作「孫女」，外祖父／祖父依本段無法決定。
- 標籤改綁 1 條（pc:2sa.21.1，撒下 21:8）：探針把未具名的另一個女兒對到本節的女兒名；改綁回該名本人。
- gold_exclusions.json：K0 核錯的 3 題 uid（在修正後 gold 下也已不成立，留作紀錄）。
- 性別：TIPNR 描述原本只看第一個字，8 位女性被判成男性；改成看第一個短語裡的女性名詞。基礎 48 題沒有因此失效（逐槽位核過）。

### B14.2 題目有效性與答案鍵

- 新增三條有效性規則（B2）：題目兩端人名仍是該人的表層名；gold 每一跳要是修正後 gold 的邊、方向與性別和簽名一致；UNC／COU 的 b 要是男性。
- DIL 依中間子女的性別選表（新增 DIL_F，女婿）；基礎 48 題中 1 題中間是女兒，答案鍵由媳婦表改成女婿表，題目不換。卡片 (D,S) 改寫「兒女的配偶」並列入兩張 DIL 表；K0 已核的 40 張卡沒有這個簽名（文字逐張相同）。
- SEQ 補常見說法：曾曾祖父／四世祖（k=4）、曾曾曾祖父／五世祖（k=5）、三世祖（k=3），並交叉列為其他 k 的陷阱，避免「曾曾祖父」被當成陷阱「曾祖父」。「第 N 代」的其他寫法沒有改成 regex。
- 妃嬪關係（TIPNR 記為配偶）：FIL（a 為男性）補「妃嬪的父親」「妾的父親」，DIL 補「兒子的妃嬪」「兒子的妾」，避免「妃嬪的父親」被當成陷阱「父親」。
- LIN 題：context 裡含答案名或陷阱名的其他人名列為中性字串（B6）。
- 48 題答案鍵狀態（對 v0）：相同 29、只補詞表 9、答案鍵改變 1、換題 9。

### B14.3 換題（9 題；槽位題號不變，其他槽位不動；uid 在 store dryrun.json meta.replacements）

- 程序：基礎 48 題照原規則重現（逐槽位與 K0 已核的 v0 相同，B9），再依題號逐一處理不成立的槽位；候選題＝修正後 gold 下成立、從未被選過、題目文字不重複的 dev 題。以一個 Random(20261018) 在第一個非空層級內（候選依 pericope、題型、表層名排序）抽一題：
  1. 同 pericope、同題型；2. 同題型、其他 dev pericope（每個 pericope 上限 8 題內）；3. 都沒有時用基礎抽樣自己的 fallback：UNC／COU 槽位依抽樣步驟 2（UNC 再 COU，維持旁系 ≥20），其他槽位依步驟 3（REFILL 順序）；先在上限內，再放寬到題數最少的 pericope。第 3 層是任務規則沒涵蓋時的延伸，需主程序認可。

| 槽位 | 原題型 | 原 pericope | 理由 | 新題型 | 新 pericope | 層級 | 可選題數 |
|---|---|---|---|---|---|---|---|
| b01 | UNC | `pc:1ch.9.35` | gold 鏈有一跳（父）不在修正後 gold | UNC | `pc:1ch.9.35` | 1 同 pericope、同題型 | 2 |
| b02 | UNC | `pc:1ch.9.35` | gold 鏈有一跳（父）不在修正後 gold | UNC | `pc:1ch.9.35` | 1 同 pericope、同題型 | 1 |
| b13 | DIL | `pc:2sa.21.1` | gold 鏈有一跳（子）不在修正後 gold＋K0 核錯（gold_exclusions.json） | DIL | `pc:2sa.21.1` | 1 同 pericope、同題型 | 1 |
| b17 | FIL | `pc:2sa.21.1` | 題目人名已不是該人的表層名＋K0 核錯（gold_exclusions.json） | SEQ3 | `pc:1ch.9.35` | 3 抽樣 fallback（上限內） | 12 |
| b18 | UNC | `pc:1ch.9.35` | gold 鏈有一跳（父）不在修正後 gold＋K0 核錯（gold_exclusions.json） | UNC | `pc:1ch.2.25` | 3 抽樣 fallback（放寬上限） | 36 |
| b24 | LIN2 | `pc:num.32.1` | gold 鏈有一跳（父）不在修正後 gold | LIN2 | `pc:2sa.21.1` | 2 同題型、其他 dev pericope（上限內） | 22 |
| b27 | MGF | `pc:1ch.1.43` | gold 鏈有一跳（母）不在修正後 gold | SEQ3 | `pc:1ch.9.35` | 3 抽樣 fallback（上限內） | 11 |
| b38 | UNC | `pc:1ch.9.35` | gold 鏈有一跳（父）不在修正後 gold | UNC | `pc:1ch.2.25` | 3 抽樣 fallback（放寬上限） | 35 |
| b48 | UNC | `pc:1ch.9.35` | gold 鏈有一跳（父）不在修正後 gold | UNC | `pc:1ch.2.25` | 3 抽樣 fallback（放寬上限） | 34 |

- 換題後題型數：UNC 14、COU 6、LIN2 5、LIN3 4、LIN4 4、SEQ3 3、SEQ4 3、SEQ5 2、MGF 1、PGM 2、FIL 2、DIL 2；旁系 UNC＋COU＝20；群聚 9 個；最大的 pericope 11 題（超過上限 8 是為了維持旁系 ≥20）。

### B14.4 harness

- 槽位上限＝max(K0 值, 正式錨點下 G 卡最大字數)（B8）；原本只取正式 G 卡最大值，可能低於 K0。
- 寫鏈指示加「第一行就寫第一跳，不要前言、不要編號」，避免前言吃掉 T 臂的 6 行。
- 截斷：smoke 後自動存 /api/ps 與截斷數；score 沒有 context_length 就拒絕；analyze 在缺 ctx_len 時判「未判定」；正式 seeds／arms 的 --num-ctx 必須與 smoke 相同（B12）。
- K0 審查檔拿掉自動判定（另存）；K0 卡片樣本固定為已核的 40 張再加新卡（B12）。
- 描述新增：計分變體、分散題其他讀法、同鏈去重、群聚數、階段 1 槽位統計（B6、B10）。
- 2026-10-18 第二輪複核：用新的 --num-ctx 重跑 smoke 時，原本會跳過 smoke/ 裡已完成的呼叫（0 個呼叫），ps.json 卻照樣改記新 num_ctx、context_length 仍是舊值，正式 score 會把 ≥舊 ctx 的呼叫誤判截斷。改成：smoke 的 --num-ctx 與 smoke/smoke_ctx.json 不同就先把舊 smoke 檔移到 smoke/superseded/ 再全部重發；save_ps 只在 /api/ps 的 context_length 等於 --num-ctx 時寫入；seeds／arms 也核對 ps.json 的 context_length（B12）。判定規則、門檻、K0 樣本、層與卡片規則都沒動。
- 2026-10-18 主程序：cards_common.answer_line 在去 Markdown 之前找「答案：」，「**答案**：」會記成沒有答案行；score_b 改成先刪 Markdown 符號再取答案行（prereg §1 本來就要求去 Markdown；實驗 A 的 answer_text 同理）。

### B14.5 沒有照做的建議

- 陷阱只比答案行第一子句、可接受詞也先去括號：這兩條會改 prereg §1／§3 寫死的計分（答案行不含任何陷阱鍵；只有陷阱檢查前去括號），所以判定照 prereg，只加描述（B6）。
- T 臂階段 1 也寫結論行：prereg 寫的是「世代鏈」；照字面保留，報告寫明不對稱（B8）。
- K0 看到的三個卡片規則缺口（B7）：是看了 40 張卡的核對結果才知道的，改了等於依核對結果調卡片規則；這些缺口只會讓 G 的卡片出錯，方向對 G 不利。

### B14.6 待主程序寫進 prereg「執行紀錄」（呼叫 Ollama 前）

- 建置者自加的三條：錨點表層名在 pericope 對到 >1 人排除、雙錨點最短路徑多種關係排除、每個 pericope 上限 8 題。
- B14.1–B14.3 的 gold 更正、新增有效性規則、換題程序（含第 3 層）與結果；gold 48 題全核（比 prereg 的 20 題嚴格），單人判讀。
- 分散題採「每跳都定位到、但不是連續行」，n 見 B9；其他讀法只描述。
- 槽位上限規則（B8）。
