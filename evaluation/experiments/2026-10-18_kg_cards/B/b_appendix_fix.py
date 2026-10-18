"""appendix_B.md §B14: the correction record (build, K0 and review results, all before any arm was
generated). Slot ids, pericope ids, strata, verse references and counts only: no names, no verse
text, no TIPNR ids (those stay in store gold_fixes.json / dryrun.json)."""
from __future__ import annotations

REASON = {"hop_U_not_in_gold": "gold 鏈有一跳（父）不在修正後 gold", "hop_Um_not_in_gold": "gold 鏈有一跳（母）不在修正後 gold",
          "hop_D_not_in_gold": "gold 鏈有一跳（子）不在修正後 gold", "hop_Dm_not_in_gold": "gold 鏈有一跳（子）不在修正後 gold",
          "hop_S_not_in_gold": "gold 鏈有一跳（配偶）不在修正後 gold", "collateral_b_female": "旁系題 b 為女性",
          "validity_rule": "有效性規則", "gold_exclusions": "K0 核錯（gold_exclusions.json）",
          "anchor_surface_not_in_gold": "題目人名已不是該人的表層名"}
TIER = {"same_pericope": "1 同 pericope、同題型", "other_dev_pericope": "2 同題型、其他 dev pericope（上限內）",
        "draw_fallback_cap": "3 抽樣 fallback（上限內）", "draw_fallback_least_loaded": "3 抽樣 fallback（放寬上限）"}


GOLD_STATUS = {"carried": "相同", "tables_extended": "只補詞表", "answer_changed": "答案鍵改變", "replaced": "換題"}


def status_text(st: dict) -> str:
    return "、".join(f"{GOLD_STATUS.get(k, k)} {v}" for k, v in st.items())


def table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def _reason(code: str) -> str:
    return "＋".join(REASON.get(c, c) for c in code.split("+"))


def sec_gold(dry: dict) -> list[str]:
    gf = dry["gold_fixes"]
    return [
        "## B14 更正紀錄（2026-10-18；依建置、K0 核對、審查三份結果；都在任何臂生成之前）", "",
        "K0 卡片精確率已過門檻（40 張 36 張正確＝0.90，store k0_verify/k0_verify_independent.json），"
        "沒有為了 K0 改層或改卡片規則。以下是 gold、答案鍵與 harness 的更正。", "",
        f"### B14.1 gold 更正（store gold_fixes.json：邊 {gf['n_edges']} 條、標籤 {gf['n_labels']} 條；sha256 見 B11）", "",
        "- 錯邊 2 條（所有 pericope）：TIPNR 把一條四代直系鏈壓平成同一父親的兄弟（代上 8:37、9:43），"
        "pc:1ch.9.35 的 5 題因此答案鍵錯（正確答案正好列在陷阱裡）。",
        "- 本段沒寫的邊 2 條（只在 pc:num.32.1）：民 32:11 只是三位先祖並列；題目錨點的表層名在本段指民族。",
        "- 本段沒寫性別的母系邊 1 條（只在 pc:1ch.1.43）：代上 1:50 字面作「孫女」，外祖父／祖父依本段無法決定。",
        "- 標籤改綁 1 條（pc:2sa.21.1，撒下 21:8）：探針把未具名的另一個女兒對到本節的女兒名；改綁回該名本人。",
        "- gold_exclusions.json：K0 核錯的 3 題 uid（在修正後 gold 下也已不成立，留作紀錄）。",
        "- 性別：TIPNR 描述原本只看第一個字，8 位女性被判成男性；改成看第一個短語裡的女性名詞。"
        "基礎 48 題沒有因此失效（逐槽位核過）。", ""]


def sec_keys(dry: dict) -> list[str]:
    st = dry["k0_gold"]["status_48"]
    return [
        "### B14.2 題目有效性與答案鍵", "",
        "- 新增三條有效性規則（B2）：題目兩端人名仍是該人的表層名；gold 每一跳要是修正後 gold 的邊、方向與性別和簽名一致；"
        "UNC／COU 的 b 要是男性。",
        "- DIL 依中間子女的性別選表（新增 DIL_F，女婿）；基礎 48 題中 1 題中間是女兒，答案鍵由媳婦表改成女婿表，題目不換。"
        "卡片 (D,S) 改寫「兒女的配偶」並列入兩張 DIL 表；K0 已核的 40 張卡沒有這個簽名（文字逐張相同）。",
        "- SEQ 補常見說法：曾曾祖父／四世祖（k=4）、曾曾曾祖父／五世祖（k=5）、三世祖（k=3），並交叉列為其他 k 的陷阱，"
        "避免「曾曾祖父」被當成陷阱「曾祖父」。「第 N 代」的其他寫法沒有改成 regex。",
        "- 妃嬪關係（TIPNR 記為配偶）：FIL（a 為男性）補「妃嬪的父親」「妾的父親」，DIL 補「兒子的妃嬪」「兒子的妾」，"
        "避免「妃嬪的父親」被當成陷阱「父親」。",
        "- LIN 題：context 裡含答案名或陷阱名的其他人名列為中性字串（B6）。",
        f"- 48 題答案鍵狀態（對 v0）：{status_text(st)}。", ""]


def sec_replace(dry: dict) -> list[str]:
    reps = dry["meta"]["replacements"]
    rows = [[f"b{r['slot']:02d}", r["stratum"], f"`{r['old_pericope']}`", _reason(r["reason"]), r["new_stratum"],
             f"`{r['new_pericope']}`", TIER.get(r["tier"], r["tier"]), r["n_eligible"]] for r in reps]
    head = ["槽位", "原題型", "原 pericope", "理由", "新題型", "新 pericope", "層級", "可選題數"]
    out = [f"### B14.3 換題（{len(reps)} 題；槽位題號不變，其他槽位不動；uid 在 store dryrun.json meta.replacements）", "",
           "- 程序：基礎 48 題照原規則重現（逐槽位與 K0 已核的 v0 相同，B9），再依題號逐一處理不成立的槽位；"
           "候選題＝修正後 gold 下成立、從未被選過、題目文字不重複的 dev 題。以一個 Random(20261018) 在第一個非空層級內"
           "（候選依 pericope、題型、表層名排序）抽一題：",
           "  1. 同 pericope、同題型；2. 同題型、其他 dev pericope（每個 pericope 上限 8 題內）；"
           "3. 都沒有時用基礎抽樣自己的 fallback：UNC／COU 槽位依抽樣步驟 2（UNC 再 COU，維持旁系 ≥20），其他槽位依步驟 3"
           "（REFILL 順序）；先在上限內，再放寬到題數最少的 pericope。第 3 層是任務規則沒涵蓋時的延伸，需主程序認可。", ""]
    out += table(head, rows)
    per, st = dry["meta"]["per_pericope_final"], dry["meta"]["per_stratum_final"]
    out += ["", "- 換題後題型數：" + "、".join(f"{k} {v}" for k, v in st.items())
            + f"；旁系 UNC＋COU＝{st.get('UNC', 0) + st.get('COU', 0)}；群聚 {len(per)} 個；"
            f"最大的 pericope {max(per.values())} 題（超過上限 8 是為了維持旁系 ≥20）。", ""]
    return out


def sec_harness() -> list[str]:
    return [
        "### B14.4 harness", "",
        "- 槽位上限＝max(K0 值, 正式錨點下 G 卡最大字數)（B8）；原本只取正式 G 卡最大值，可能低於 K0。",
        "- 寫鏈指示加「第一行就寫第一跳，不要前言、不要編號」，避免前言吃掉 T 臂的 6 行。",
        "- 截斷：smoke 後自動存 /api/ps 與截斷數；score 沒有 context_length 就拒絕；analyze 在缺 ctx_len 時判「未判定」；"
        "正式 seeds／arms 的 --num-ctx 必須與 smoke 相同（B12）。",
        "- K0 審查檔拿掉自動判定（另存）；K0 卡片樣本固定為已核的 40 張再加新卡（B12）。",
        "- 描述新增：計分變體、分散題其他讀法、同鏈去重、群聚數、階段 1 槽位統計（B6、B10）。",
        "- 2026-10-18 第二輪複核：用新的 --num-ctx 重跑 smoke 時，原本會跳過 smoke/ 裡已完成的呼叫（0 個呼叫），"
        "ps.json 卻照樣改記新 num_ctx、context_length 仍是舊值，正式 score 會把 ≥舊 ctx 的呼叫誤判截斷。"
        "改成：smoke 的 --num-ctx 與 smoke/smoke_ctx.json 不同就先把舊 smoke 檔移到 smoke/superseded/ 再全部重發；"
        "save_ps 只在 /api/ps 的 context_length 等於 --num-ctx 時寫入；seeds／arms 也核對 ps.json 的 context_length（B12）。"
        "判定規則、門檻、K0 樣本、層與卡片規則都沒動。",
        "- 2026-10-18 主程序：cards_common.answer_line 在去 Markdown 之前找「答案：」，「**答案**：」會記成沒有答案行；"
        "score_b 改成先刪 Markdown 符號再取答案行（prereg §1 本來就要求去 Markdown；實驗 A 的 answer_text 同理）。", "",
        "### B14.5 沒有照做的建議", "",
        "- 陷阱只比答案行第一子句、可接受詞也先去括號：這兩條會改 prereg §1／§3 寫死的計分（答案行不含任何陷阱鍵；"
        "只有陷阱檢查前去括號），所以判定照 prereg，只加描述（B6）。",
        "- T 臂階段 1 也寫結論行：prereg 寫的是「世代鏈」；照字面保留，報告寫明不對稱（B8）。",
        "- K0 看到的三個卡片規則缺口（B7）：是看了 40 張卡的核對結果才知道的，改了等於依核對結果調卡片規則；"
        "這些缺口只會讓 G 的卡片出錯，方向對 G 不利。", "",
        "### B14.6 待主程序寫進 prereg「執行紀錄」（呼叫 Ollama 前）", "",
        "- 建置者自加的三條：錨點表層名在 pericope 對到 >1 人排除、雙錨點最短路徑多種關係排除、每個 pericope 上限 8 題。",
        "- B14.1–B14.3 的 gold 更正、新增有效性規則、換題程序（含第 3 層）與結果；gold 48 題全核（比 prereg 的 20 題嚴格），單人判讀。",
        "- 分散題採「每跳都定位到、但不是連續行」，n 見 B9；其他讀法只描述。",
        "- 槽位上限規則（B8）。", ""]


def render(dry: dict) -> list[str]:
    return sec_gold(dry) + sec_keys(dry) + sec_replace(dry) + sec_harness()
