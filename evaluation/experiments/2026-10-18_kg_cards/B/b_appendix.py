"""Render appendix_B.md from the frozen tables and the dry-run numbers. No verse text, no TIPNR
content or ids: pericope ids, generic kinship terms, rules, counts and sha256 only."""
from __future__ import annotations

import b_appendix_fix
import b_arms as A
import b_card as Cd
import b_items as I
import b_terms as Tm

TERM_KEYS = ("UNC", "COU", "SEQ3", "SEQ4", "SEQ5", "MGF", "PGM", "FIL_M", "FIL_F", "DIL", "DIL_F")
TERM_NOTE = {"SEQ3": "SEQ k=3", "SEQ4": "SEQ k=4", "SEQ5": "SEQ k=5", "FIL_M": "FIL，a 為男性",
             "FIL_F": "FIL，a 為女性", "DIL": "DIL，中間是兒子", "DIL_F": "DIL，中間是女兒"}
SIG_NAME = {"U": "父", "Um": "母", "D": "子（父出）", "Dm": "子（母出）", "S": "配偶"}


_table = b_appendix_fix.table


def _block(text: str) -> list[str]:
    return ["```text", text, "```"]


def sec_items(dry: dict) -> list[str]:
    m = dry["meta"]
    out = ["## B1 dev pericope（12 個）", "",
           f"抽樣框：C1 純文字框 {m['n_frame']} 個 pericope，其中 probe_C1/items_eval.json 有題的 "
           f"{m['n_item_pericopes']} 個。依書卷分層，按比例分配 12 個名額（最大餘數法；餘數相同時，"
           "依書卷代碼順序替每卷抽一次 random()，小者優先），再依書卷代碼順序在各卷內 rng.sample。"
           "rng＝random.Random(20261018)，同一個 rng 依序再用於抽題洗牌與題號排列。", ""]
    out += _table(["書卷", "分到", "該卷有題 pericope"], [[b, a, n] for b, (a, n) in m["alloc"].items()])
    out += ["", "dev pericope：" + "、".join(f"`{p}`" for p in m["dev_pericopes"]), "",
            "## B2 抽題與配額", "",
            "- 候選題：dev pericope 內 items_eval 的 10 種題型；SEQ 依 k 分成 SEQ3／SEQ4／SEQ5 三層。",
            "- 選題只讀 pericope、書卷、題型與 gold 鏈（ids、表層名）；不讀 items_eval 的 PER、R5、Q5、"
            "R5g、PERg outcome 欄位，也不讀任何臂的結果。R5.units 只在選題後當 context 用。",
            "- 題目有效性（不看結果）：錨點表層名在該 pericope 對到 >1 人 → 排除；雙錨點題在 gold 圖上"
            "≤5 跳的最短路徑若命名出兩種以上關係（同一人既是祖父又是公公之類）→ 排除；LIN 題錨點與答案同名 → 排除；"
            "題目文字重複 → 只留先抽到的。以上是基礎抽樣（v0 gold）的規則。",
            "- 修正後 gold（B14）另加三條，用於檢查基礎 48 題與換題候選：題目裡的兩端人名仍是該人在修正後 gold 的表層名；"
            "gold 鏈每一跳都要是修正後 gold 的邊，"
            "方向與父母性別要和簽名字母一致（U＝唯一的男性父母、Um＝女性父母、D／Dm 同理、S＝配偶）；"
            "UNC／COU 的 b 要是男性（伯叔、堂兄弟表只適用男性）。",
            f"- 每個 pericope 上限 {I.PER_PERICOPE_CAP} 題。順序：(1) 各層依基礎配額在上限內抽，層的順序＝"
            "候選題所在 pericope 數少者先、再按候選題數，UNC 移到 COU 之後，且 UNC 配額提高為 20−COU 已抽數；"
            "(2) UNC（不足用 COU）補到 UNC＋COU ≥20；(3) 剩下名額依 REFILL 順序一次一題輪流補。"
            "(2)(3) 只有在上限內沒有候選題時才放寬上限，放寬時選題數最少的 pericope，並記錄。", ""]
    base = I.BASE_QUOTA
    out += _table(["層", "基礎配額", "基礎抽樣實抽", "換題後"],
                  [[s, base[s], m["per_stratum"].get(s, 0), m["per_stratum_final"].get(s, 0)] for s in base])
    out += ["", f"- 抽層順序：{' → '.join(m['draw_order'])}；REFILL：{' → '.join(I.REFILL_ORDER)}",
            f"- 基礎抽樣放寬上限：{m['relaxed'] or '無'}；換題見 B14。",
            "- 候選題數（基礎 v0 gold → 修正後 gold）：" + "、".join(f"{s} {a}→{b}" for s, (a, b) in m["pool_sizes"].items()),
            "- 換題後每個 pericope 題數：" + "、".join(f"`{p}` {n}" for p, n in m["per_pericope_final"].items())
            + f"（群聚 {len(m['per_pericope_final'])} 個）",
            "- 基礎抽樣每個 pericope 實抽：" + "、".join(f"`{p}` {n}" for p, n in sorted(m["per_pericope"].items())),
            f"- 題號：48 題以 rng.sample 排列後依序編 b01–b48；執行依題號。", ""]
    return out


def sec_templates() -> list[str]:
    out = ["## B3 題目模板", "", f"- LIN2／LIN3／LIN4：`{Tm.LIN_Q}`，word＝祖父／曾祖父／高祖父；a＝ids[0] 的表層名。",
           f"- 其餘：`{Tm.PAIR_Q}`，a＝ids[0]、b＝ids[-1]，表層名取 items_eval 的 surfaces。", "",
           "## B4 稱謂題的答案鍵與陷阱鍵（命中任一可接受稱謂，而且不含陷阱稱謂）", ""]
    rows = []
    for k in TERM_KEYS:
        acc, trap = Tm.term_table(k)
        rows.append([TERM_NOTE.get(k, k), "、".join(acc), "、".join(trap)])
    out += _table(["題型", "可接受", "陷阱"], rows)
    out += ["", "FIL 依 a 的性別、DIL 依中間那一代（a 的子女）的性別選表；性別取 gold 來源人物描述第一個短語裡的"
            "女性名詞（B14）。", "",
            "## B5 LIN 人名題的鍵", "",
            "- 答案鍵：gold 祖先在該 pericope 的全部表層名，命中任一即可。",
            "- 陷阱鍵：gold 鏈上中間各代，加上 gold 祖先的父親（若在該 pericope 有 gold 邊），各取全部表層名；"
            "與答案鍵或錨點同名者不列。錨點本人的表層名當中性字串。", "",
            "## B6 比對規則", "",
            "- 答案行＝先刪 Markdown 符號（*、_、#、`、>），再取 cards_common.answer_line（最後一個「答案：」之後），已做 NFKC、去空白；"
            "比對前答案行與所有鍵再去掉人名間隔點（U+2027、U+00B7、U+30FB、U+2022、U+2219、U+22C5）；"
            "沒有答案行、或呼叫被截斷（done_reason=length，或 prompt_eval_count+eval_count ≥ context_length），記格式失敗 0。"
            "階段 2 的階段 1 被截斷，也記格式失敗。",
            "- 稱謂題先刪除 gold 鏈上所有人的表層名（長的先刪，換成空字串），讓「父親〔人名〕的兄弟」讀成「父親的兄弟」。",
            "- 再把可接受、陷阱、中性字串合在一起，由長到短比對；比到的字串先遮掉，才比較短的"
            "（「曾祖父」先吃掉，「祖父」就不會再中；「叔父的兒子」先吃掉，「叔父」就不會再中）。",
            "- 陷阱檢查用刪掉括號內文字的答案行（cards_common.strip_parens）；可接受鍵用完整答案行。",
            "- LIN 題：context 經節裡含有答案名或陷阱名的其他人名（如甲乙丙含甲乙）列為中性字串，先被吃掉。",
            "- 只描述、不進判定（score_b／analyze_b）：(a) 陷阱只比答案行第一個子句（第一個「，。；、」或「因為」「即」之前）"
            "的答對率；(b) 答對但可接受詞只出現在括號內的次數。判定一律用上面 prereg 的規則。", ""]
    return out


def sec_card(dry: dict) -> list[str]:
    rows = [["、".join(SIG_NAME[s] for s in sig), term] for sig, term in Cd.SIG_TERM.items()]
    out = ["## B7 程式卡", "",
           "- 規則照 probe_C1/card.py：同名阻擋（有 ≥2 個不同父系父母的名字不能當中繼；錨點被標記就棄權）、"
           "≤5 跳 BFS 最短路徑出現 ≥2 種正規化簽名就棄權、LCA 化簡。邊來源＝context 經節的 MH kin 三元組；"
           "經節依正典順序走訪（card.py 原本走 set，引用經節與同簽名平手時挑哪條路徑不固定）。",
           f"- 移植核對：dev 48 題用 gold 表層名模擬錨點時，移植版與 items_eval R5 卡的 status、棄權原因、簽名"
           f"相同 {dry['stats']['port_check']['same']}/{dry['stats']['port_check']['n']} 題（只核對，不用來選題）。",
           "- LIN：單錨點父系上溯 k 代（ancestor_card），k 由題目的「祖父／曾祖父／高祖父」讀出；其餘：pair_card。",
           "- 卡片＝每跳一行（依走訪方向），最後一行是結論，≤6 行：", ""]
    out += _block("甲的父親是乙（代上 1:20）   ← U\n甲的母親是乙（…）          ← Um\n甲的孩子是乙（…）          ← D／Dm\n"
                  "甲的配偶是乙（…）          ← S\n甲與乙是手足（…）          ← B\n"
                  "結論：{a}的{祖父|曾祖父|高祖父}是{答案}      （LIN）\n結論：{b}是{a}的{稱謂}                 （其餘）")
    out += ["", "- 稱謂由正規化簽名查表；表外的簽名用每跳的詞以「的」串起（父親的父親的兒子…）。MH 的 D 跳不帶子女性別："
            "（D／Dm, S）寫「兒女的配偶」，其餘以 D 結尾的稱謂預設男性（兒子、孫子、伯父或叔父、堂兄弟）。",
            "- K0 看到的三個卡片規則缺口沒有改（理由見 B14）：同名阻擋只看 ≥2 個父系父母；(U,S)→Um 假設父親的配偶是母親；"
            "(Um,Dm) 等母系旁系沒有稱謂。", ""]
    out += _table(["正規化簽名（a 走到 b）", "稱謂"], rows)
    out += ["", "- 邊表每行：`甲是乙的父親（簡稱 章:節）`、`甲是乙的母親（…）`（role=M）、`甲與乙是夫妻（…）`、"
            "`甲與乙是手足（…）`；PARENT_OF 的 role P／F 都寫父親（與卡片的父系判定一致）。"
            "context 經節依正典順序、三元組依檔案順序，以 (head, rel, tail) 去重，不挑、不截斷；沒有邊寫「（無）」。"
            "書卷簡稱取 packages/ragcommon/data/books.json 的第一個 PDF 縮寫，沒有就取第一個口語縮寫。",
            "- G-oracle：TIPNR gold（修正後，B14）的 parent／partner 關係，兩端在同一 context 經節都有對齊標籤者，"
            "改寫成同格式的表層三元組（probe_oracle_extract.py），套同一套卡片規則；只稱理想上限，不截斷卡片。"
            "G-oracle 的附加區塊用的是這份 TIPNR 邊表（不是 MH 邊表）加 oracle 卡。", ""]
    return out


def sec_arms(dry: dict) -> list[str]:
    cap = dry["slot_cap_chars_k0"]
    out = ["## B8 臂與 prompt", "",
           "- 所有生成 job：system＝cards_common.SYSTEM_PROMPT；user＝cards_common.build_user(context, 題目, aux_block)。"
           "context＝items_eval R5.units 的 ps:／ck: 單位，依 R5 順序，取 store struct@d8d432b4df15 的 passages／chunks，"
           "組成 prod build_context_blocks 的格式（chunk 內容照 backend/database/content.py chunk_content）。",
           "- aux_block（「以下是輔助資料（依經文整理）：」之後）：", ""]
    out += _table(["臂", "aux_block"], [
        ["G", f"`{A.TABLE_HEAD}`＋邊表＋空行＋`{A.SLOT_HEAD}`＋程式卡"],
        ["T-1hop+CoT 階段 1", f"`{A.TABLE_HEAD}`＋邊表；instruction 換成寫鏈指示"],
        ["T-1hop+CoT 階段 2", f"`{A.TABLE_HEAD}`＋邊表＋空行＋`{A.SLOT_HEAD}`＋槽位"],
        ["T-LLM 階段 1", "無；instruction 換成寫鏈指示"],
        ["T-LLM 階段 2", f"`{A.SLOT_HEAD}`＋槽位"],
        ["B0", "無"],
        ["G-oracle", f"`{A.TABLE_HEAD}`＋oracle 邊表＋空行＋`{A.SLOT_HEAD}`＋oracle 卡"]])
    out += ["", "- 寫鏈指示（build_user 的 instruction 參數）：", ""] + _block(A.CHAIN_INSTRUCTION)
    out += ["", "- 槽位＝階段 1 輸出經 cards_common.fill_slot（前 6 個非空行，再截到上限字數）。"
            "G 的卡片也經同一個 fill_slot（卡片本來就 ≤上限，不會被截）。",
            f"- 槽位字數上限（三臂相同）＝max(K0 值, arms 子命令建 job 時正式錨點下 G 卡片的最大字數)：不低於 K0，"
            f"也不會截到 G 卡片；兩個值都寫進 cards.json／arm_jobs.json。K0（dry-run，gold 表層名模擬錨點）＝{cap} 字，"
            "行數上限 6。建 job 時還沒有生成任何臂。",
            "- 不對稱（照 prereg 字面保留，報告時寫明）：G 的槽位最後一行是程式寫的「結論：」，T 臂階段 1 只寫世代鏈、"
            "不寫結論；所以 H2 量到的是程式走訪加稱謂合成，不只是走訪。",
            "- 錨點（階段 1，kind=seed，每題一次，各臂共用）：", ""]
    out += _block(f"system: {A.SEED_SYSTEM}\nuser: {A.SEED_USER}")
    out += ["", "- parser：逐行去掉項目符號與首尾標點，以「、，,；;/ 空白」切開；出現在題目裡的詞排前面，取前 2 個。"
            "對到卡片子圖節點名：完全相同優先；否則去掉人名間隔點後相同且唯一；否則去掉間隔點後互相包含且唯一；"
            "都不成就保留原字（卡片因此棄權）。雙錨點題中，在題目裡位置較前的名字是 b、較後的是 a"
            "（模板「{b}是{a}的什麼人」），與輸出順序無關。G 與 G-oracle 各自對自己的子圖解析同一份輸出。",
            "  dry-run 用 gold 表層名模擬（雙錨點題依題目順序輸出 b、a）。",
            "- 次數與順序：rep 1 跑 G、T-1hop+CoT、T-LLM、B0、G-oracle；rep 2 跑 G、T-1hop+CoT。rep → 題 → 臂，"
            "臂的順序依題號（第 i 題左旋 i 位）輪替；兩段式臂的階段 1 緊接在其階段 2 之前。卡片棄權的題不生成 G"
            "（G-oracle 同）。", ""]
    return out


def sec_numbers(dry: dict) -> list[str]:
    s = dry["stats"]
    out = ["## B9 dry-run 實測（K0 數字）", ""]
    out += _table(["項目", "值"], [
        ["邊表字數（不含小標）min／中位／max", f"{s['edge_table_chars']['min']}／{s['edge_table_chars']['median']}／{s['edge_table_chars']['max']}"],
        ["邊數 min／中位／max", f"{s['n_edges']['min']}／{s['n_edges']['median']}／{s['n_edges']['max']}"],
        ["context 字數 max", s["context_chars"]["max"]],
        ["G 卡片出手（模擬錨點）", f"{s['G_fired']}/48"],
        ["G 卡片字數 min／中位／max", f"{s['G_card_chars'].get('min')}／{s['G_card_chars'].get('median')}／{s['G_card_chars'].get('max')}"],
        ["G-oracle 卡片出手", f"{s['GO_fired']}/48"],
        ["user prompt 字數 max（階段 2 以上限字數的槽位計）", s["user_chars_max_all"]],
        ["分散題（gold 鏈已定位、非連續行）", s["n_dispersed"]],
        ["gold 鏈版面", s["layout"]],
        ["gold 每跳經節都在 context 內", "是" if not s["context_check"]["hop_verses_outside_context"] else
         f"否：{s['context_check']['hop_verses_outside_context']}"],
        ["基礎抽樣＝K0 已核的 v0 48 題（逐槽位）", s["base_check"].get("same")],
        ["job 總數（含錨點 48）", s["n_jobs_total"]]])
    out += ["", "各臂 job 數（模擬錨點；實際 G／G-oracle 數依 gemma 錨點而定）：", ""]
    out += _table(["臂:種類:rep", "數"], [[k, v] for k, v in s["jobs_by_arm"].items()])
    out += ["", "## B10 分析定義（prereg §3 K-S0）", "",
            "- 題分數＝該臂各 rep 答對的平均。G 棄權的題，每個比較都取比較臂自己的分數（差 0）。",
            "- 分散題：gold 鏈每一跳以表層名（該人在 pericope 的全部表層名）在邊表裡定位，套 probe_C1/twin_struct.py "
            "的分類；分散＝全部定位到、但不是連續行（monotone 或 scattered）。有一跳找不到（unlocated）不算分散，另外報告；"
            "描述另報「分散＋unlocated」「只有 scattered」「只有 unlocated」三種讀法。",
            "- 描述另報：同鏈去重（每條 gold ids 鏈留題號最小的一題）的比較、群聚數、兩段式臂階段 1 的原始行數字數與被截比例。",
            "- 卡片答對＝卡片出手，而且結論行用同一套鍵判為答對。",
            "- adh、r 依題層平均：x̄、T̄ 分別是該集合上的臂平均與 T-LLM 平均，值＝clip((x̄−T̄)/(1−T̄), 0, 1)；"
            "集合為空記 0；1−T̄=0 時 x̄=1 記 1、否則記 0。",
            "- a＝出手率×0.82×(92/169)；prec＝出手卡答對率；檢定力＝power_c1_v2.gen(32, 4, pT, a, adh, r, prec, 3) "
            "300 次中，H1（G−T-LLM）與 H2（G−T-1hop+CoT）的 pflip p 都 <0.05 且平均差都 ≥0.05 的比例。",
            "- 描述：src/ab_stats.py 的 bootstrap_ci（10000 次、seed 20261018）與 sign_flip_p（20000 次、seed 20261018），"
            "題層與 pericope 群聚兩種。", ""]
    return out


def sec_sha(dry: dict) -> list[str]:
    sh = dry["sha256"]
    out = ["## B11 sha256", ""]
    rows = [[k, f"`{v}`"] for k, v in sh["prompts"].items()]
    rows += [[f"store B/{k}", f"`{sh[k]}`"] for k in ("items.json", "seed_jobs.json", "gold_fixes.json", "gold_exclusions.json")]
    rows += [["store B/v0_k0checked/items.json（K0 已核的 v0）", f"`{dry['stats']['base_check'].get('v0')}`"]]
    rows += [[f"code {k}", f"`{v}`"] for k, v in sh["code"].items()]
    out += _table(["對象", "sha256"], rows)
    kc, kg = dry["k0_cards"], dry["k0_gold"]
    out += ["", "## B12 K0（CPU，叫 Ollama 前；任一不過 B 就停）", "",
            "- 40 張出手卡（v0 規則：dev 出手卡在前，不足由框內其他有題 pericope 的題目依 Random(20261018) 洗牌順序補到 40；"
            "已人工核過，store v0_k0checked/）。改版後這 40 張用現行程式重畫，逐張比對卡片文字："
            f"相同 {kc['status']['carried']}、不同 {kc['status']['changed']}、不再出手 {len(kc['lost_from_v0'])}；"
            f"另加換題後新出手的 dev 卡 {kc['status']['new']} 張。待核：{', '.join(kc['recheck']) or '無'}。"
            "審查檔 k0_cards_sample.json 不附自動判定（自動判定另存 k0_cards_auto.json，人工核完再看）。精確率門檻 ≥0.85。",
            "- gold：prereg 的 20 題（Random(20261018).sample 48 個題號；題號是槽位，換題不改題號）＋審查建議的 48 題全核"
            f"（k0_gold_check_all.json）。48 題狀態：{b_appendix_fix.status_text(kg['status_48'])}。待核（換題或答案鍵改變）：20 題中 "
            f"{', '.join(kg['recheck_20']) or '無'}；48 題中 {', '.join(kg['recheck_48']) or '無'}。單人判讀，揭露。",
            "- 截斷：先用 `arms --smoke 3`（prompt 最長的 3 題、rep 1 全部臂），跑完自動存 /api/ps（smoke/ps.json）與截斷數"
            "（smoke/truncation.json）；有截斷就所有臂與錨點用同一個 `--num-ctx` 重跑 smoke：--num-ctx 和 smoke/smoke_ctx.json 記的不同時，"
            "舊 smoke 檔先移到 smoke/superseded/，所有 smoke 呼叫重發；/api/ps 裡模型的 context_length 不等於 --num-ctx 就不寫 ps.json"
            "（模型已卸載或仍以舊 ctx 載入，要移走 smoke/ 檔重跑）。之後 seeds／arms 只接受與 smoke 相同的 "
            "`--num-ctx`；score 沒有 `--ctx-len` 時讀 smoke/ps.json 的 context_length，兩者都沒有就拒絕；analyze 在 ctx_len 缺時判「未判定」。"
            "正式跑仍截斷的呼叫記格式失敗。", ""]
    out += ["## B13 store 檔案（reports/kg_cards_20261018/B/，含經文與 TIPNR 衍生內容，不進 repo）", "",
            "items.json、seed_jobs.json、dryrun.json、gold_fixes.json、gold_exclusions.json、k0_cards_sample.json、"
            "k0_cards_auto.json、k0_gold_check.json、k0_gold_check_all.json、v0_k0checked/（K0 已核的 v0 檔）、k0_verify/；"
            "之後 smoke/、seeds.jsonl、cards.json、arm_jobs.json、arms.jsonl、scores.json、report.json、report.md；"
            "人工 K0 結果寫 k0_result.json（cards_precision、truncation_ok…）。gold 再有錯：錯邊或錯標籤寫 gold_fixes.json，"
            "個別題 uid 寫 gold_exclusions.json，重跑 dry-run（只換該槽位，見 B14）。", ""]
    return out


def render(dry: dict) -> str:
    head = ["# 附錄 B：實驗 B（段內家譜走訪卡）stage-0", "",
            "由 `run_b.py dry-run` 依程式內的凍結表與 dry-run 數字產生；改程式就重跑。依據 prereg.md §1、§3。", ""]
    parts = (head + sec_items(dry) + sec_templates() + sec_card(dry) + sec_arms(dry) + sec_numbers(dry) + sec_sha(dry)
             + b_appendix_fix.render(dry))
    return "\n".join(parts)
