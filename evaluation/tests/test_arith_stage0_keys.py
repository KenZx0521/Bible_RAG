"""Ordered-chain arithmetic stage-0 answer keys (keys_x.py; prereg §5, K0-4).

Synthetic cases use made-up names (甲朗、甲雅 …) and numbers, the G derived-line formats of prereg §4
and a two-kingdom toy View; nothing here is scripture text. The store-backed tests at the end read
experiment A's stored generations and the hand reference layer v2, print no answer or name, and skip
when the store is not mounted. Ollama is never called.
"""

import json
import sys
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import x_common as X  # noqa: E402
import keys_x as K  # noqa: E402

YEARS = {"type": "arith", "value": 76, "classes": ["Y"], "ordinal": False}
AGE = {"type": "arith", "value": 235, "classes": ["A", "Y"], "ordinal": False}
FLOOD = {"type": "arith", "value": 37, "classes": ["Y"], "ordinal": True}
TOTAL_WORDS = ("一共", "總共", "合共", "共計", "合計", "總計", "累計", "加起來", "加總", "總和", "相加", "合起來",
               "總數", "共")


def fv(line, key=YEARS):
    return K.final_value(line, key)[0]


def flags(line, key=YEARS):
    return K.final_value(line, key)[1]


def key(value, classes=("Y",), ordinal=False):
    return {"type": "arith", "value": value, "classes": list(classes), "ordinal": ordinal}


# ---------------------------------------------------------------- answer line (score_a rule, list fix)
@pytest.mark.parametrize("content,want", [
    ("推理\n答案：41.", "41."),
    ("答案：41.5年", "41.5年"),
    ("答案：\n1. 41年", "41年"),
    ("答案：12、13", "12、13"),
    ("答案：**76年**", "76年"),
    ("答案：41.\n\n說明", "41."),
    ("答案： - 76年", "76年"),
    ("答案：(2) 76年", "76年"),
    ("答案：７６年", "76年"),
    ("答案：甲\n其後\n最終答案：76年", "76年"),
    ("答案：\n76年\n甲 41 年\n\n後記", "76年;甲41年"),
])
def test_answer_text_keeps_numbers_and_strips_list_markers_only_before_whitespace(content, want):
    assert K.answer_text_x(content) == want


def test_answer_text_without_marker_is_none():
    assert K.answer_text_x("七十六年") is None
    assert K.answer_text_x("") is None
    assert K.answer_text_x(None) is None


# ---------------------------------------------------------------- numerals
def cn(n: int) -> str:
    """A plain Chinese numeral for 1..999 (一百零五, 四十一, 十二)."""
    d = "零一二三四五六七八九"
    h, t, u = n // 100, n // 10 % 10, n % 10
    s = (d[h] + "百") if h else ""
    if t:
        s += ("" if (t == 1 and not h) else d[t]) + "十"
    elif h and u:
        s += "零"
    return s + (d[u] if u else "")


def test_cn2int_x_equals_cards_common_below_one_thousand():
    for n in range(1, 1000):
        assert K.cn2int_x(cn(n)) == X.cc.cn2int(cn(n)) == n


@pytest.mark.parametrize("s,want", [("一千零五十六", 1056), ("一千六百五十六", 1656), ("千", 1000), ("兩千", 2000),
                                    ("一千", 1000), ("一千零十", 1010), ("一〇五六", 1056), ("九百六十八", 968),
                                    ("十", 10), ("百", 100), ("甲", None), ("", None)])
def test_cn2int_x_reads_thousands(s, want):
    assert K.cn2int_x(s) == want


@pytest.mark.parametrize("line,want", [("一千零五十六年", 1056), ("41.5年", 41.5), ("41年半", 41.5),
                                       ("41,25,10年", 10)])
def test_numbers_with_thousands_decimals_and_halves(line, want):
    assert fv(line, key(0)) == want


@pytest.mark.parametrize("line,want", [("90，155年", 155), ("1,041年", 41)])
def test_no_thousands_separator_a_comma_list_is_read_as_a_list(line, want):
    """Every gold is below 1000, and NFKC makes the clause comma 「，」 an ASCII comma, so a thousands
    separator could only turn a list such as 「90，155年」 into one wrong number (execution log
    2026-10-20); 千 is still read."""
    assert fv(line, key(0)) == want


def test_year_and_month_value_is_not_the_whole_years():
    assert fv("41年7個月", key(41)) != 41
    assert fv("四十一年零七個月", key(41)) != 41


def test_lone_word_forming_numerals_are_not_numbers():
    assert K.tokens(K.clean("一生", key(0))) == []
    assert K.tokens(K.clean("百姓一半", key(0))) == []
    assert [t.value for t in K.tokens(K.clean("一個", key(0)))] == [1]


# ---------------------------------------------------------------- step 0: preprocessing
@pytest.mark.parametrize("line,want", [
    ("７６年", 76), ("**共76年**", 76), ("共76年(41+25+10)", 76), ("76年(王上9:8)", 76),
    ("王上9:8,76年", 76), ("列王紀上9章8節,76年", 76), ("創7:2-4,76年", 76), ("第2位王在位76年", 76),
    ("第9章8節記載作王76年", 76),
])
def test_preprocessing(line, want):
    assert fv(line) == want


def test_ordinals_are_dropped_unless_the_key_is_ordinal():
    assert fv("第三年") is None
    assert fv("第37年") is None
    for line in ("第37年", "洪水後37年", "37", "洪水之後第三十七年", "甲在洪水之後第37年出生"):
        assert fv(line, FLOOD) == 37, line
    assert fv("第3位王之後第37年", FLOOD) == 37


# ---------------------------------------------------------------- step 1: equations
@pytest.mark.parametrize("line,want", [
    ("41+25+10=76年", 76), ("76年=41+25+10", 76), ("76年=41年+25年+10年", 76), ("41+25=66;66+10=76年", 76),
    ("41+25+10=76", 76), ("41+25+10=是76", 76), ("41+25+10=76年,即甲+乙+丙", 76), ("41加25加10=76年", 76),
    ("76=41加25加10", 76),
])
def test_equation_takes_the_value_after_the_last_equals_or_before_a_sum(line, want):
    assert fv(line) == want
    assert flags(line)[0] in ("eq", "eq_left")


def test_equation_with_an_age_key():
    assert fv("甲雅生乙雅時:35歲+25年−32歲=28歲", key(28, ("A", "Y"))) == 28


@pytest.mark.parametrize("line,want", [("28歲=60歲−32歲", 28), ("548歲=910歲-362歲", 548), ("548歲=910減362", 548),
                                       ("60−32=28歲", 28)])
def test_a_difference_after_the_last_equals_is_read_like_a_sum(line, want):
    v, f = K.final_value(line, key(want, ("A", "Y")))
    assert v == want and "hedge" not in f


# ---------------------------------------------------------------- step 2: total words
@pytest.mark.parametrize("word", TOTAL_WORDS)
def test_every_total_word_wins_over_the_last_value(word):
    line = f"{word}76年,甲41年,乙25年,丙10年"
    assert fv(line) == 76
    assert flags(line)[0] == "marker"


def test_without_a_total_word_the_last_value_of_the_segment_is_taken():
    assert fv("76年,甲41年,乙25年,丙10年") == 10


@pytest.mark.parametrize("line", ["共同攝政3年,在位76年", "甲共活3年,在位76年"])
def test_gongtong_and_gonghuo_are_not_total_words(line):
    assert fv(line) == 76


@pytest.mark.parametrize("line,want", [("甲共活900歲,乙出生時甲235歲", 235), ("甲一共活了900歲,那年乙235歲", 235),
                                       ("甲總共活了900歲,那年乙235歲", 235), ("乙出生時甲235歲;甲共活900歲", 235)])
def test_lifespan_wording_is_not_a_total(line, want):
    assert fv(line, AGE) == want


def test_a_total_word_followed_by_a_count_is_skipped():
    assert fv("共三位王,在位76年") == 76
    assert fv("一共4位,在位76年") == 76
    assert fv("從甲到丁共4位,總共76年") == 76
    assert fv("總共76年,共4位") == 76


def test_a_bare_number_after_a_total_word_is_not_taken_by_step_2():
    """§5 step 2 takes an accepted value only; the 2-character bare number is step 1's (execution log)."""
    assert fv("從甲到丁共4位,總共76") is None
    assert (fv("甲41年,乙25年,總共是76"), flags("甲41年,乙25年,總共是76")[0]) == (25, "segment")
    assert (fv("共計:76"), flags("共計:76")[0]) == (76, "single")          # step 3: the line's one number
    assert fv("41+25+10=76") == 76                                          # step 1 keeps the bare number


def test_a_total_word_followed_by_another_unit_is_skipped():
    assert fv("共7個月,在位76年") == 76


# ---------------------------------------------------------------- step 0: quotes and conclusion words (execution log)
def test_quoted_text_is_dropped_when_a_value_remains_outside():
    assert fv("甲朗到丙朗在位年數為76年,經文記載甲朗「在位四十一年」、丙朗「在位十年」") == 76
    assert fv("丁亞出生時甲士235歲。輔助資料亦推算指出「丁亞出生時甲士的年齡:235歲」,以及「甲士的總壽數:912歲」", AGE) == 235
    assert fv("丁亞出生時甲士235歲,經文說『甲士活到六十四歲,生了乙南』", AGE) == 235
    assert fv("丁亞出生時甲士235歲,經文說“甲士65歲生乙南”", AGE) == 235


def test_quoted_text_is_kept_when_it_holds_the_only_value():
    assert fv("根據「丁亞出生時甲士的年齡:235歲」", AGE) == 235
    assert fv("「在位七十六年」") == 76
    assert K.unquoted("根據「76年」", YEARS) == "根據「76年」"


@pytest.mark.parametrize("line,k,want", [
    ("甲雅35歲登基,在位25年,去世時60歲;乙雅登基時32歲,所以甲雅生乙雅時是28歲", key(28, ("A", "Y")), 28),
    ("甲雅35+25=60歲去世,乙雅32歲登基,所以甲雅生乙雅時28歲", key(28, ("A", "Y")), 28),
    ("1.甲朗:41年;2.乙朗:25年;3.丙朗:10年;因此是76年", YEARS, 76),
    ("洪水後2年生甲;甲35年生乙;乙30年生丙;故丙在洪水之後67年出生", key(67, ("Y",), True), 67),
    ("甲士65歲生乙南,乙南90歲生丙列,丙列80歲生丁亞,所以丁亞出生時甲士是235歲", AGE, 235),
])
def test_the_text_after_the_last_conclusion_word_holds_the_answer(line, k, want):
    v, f = K.final_value(line, k)
    assert v == want and "conclusion" in f


def test_conclusion_words_before_the_last_equals_or_without_a_value_after_are_not_used():
    v, f = K.final_value("所以41+25+10=76年", YEARS)
    assert (v, f[0]) == (76, "eq") and "conclusion" not in f
    v, f = K.final_value("76年,所以如此", YEARS)
    assert v == 76 and "conclusion" not in f
    assert not K.CONCL.search("故事") and not K.CONCL.search("故意")


def test_cross_chapter_citations_are_removed_whole():
    for line in ("76,見王上15:25-16:8", "76,見王上15:25、16:8", "76(王上15:25-16:8)"):
        v, f = K.final_value(line, YEARS)
        assert (v, f[0]) == (76, "single"), line
    assert fv("王上15:25-16:8,76年") == 76
    assert fv("王上15:25-16:8記載10年,共76年") == 76


# ---------------------------------------------------------------- step 3 and 4
@pytest.mark.parametrize("line,want", [("76", 76), ("七十六", 76), ("七十六年", 76), ("答案是76", 76), ("76年。", 76),
                                       ("76個月", None), ("76次", None), ("76歲", None)])
def test_single_number(line, want):
    assert fv(line) == want


@pytest.mark.parametrize("line,want", [("76年;甲41年;乙25年", 76), ("甲41年;乙25年", 41), ("甲在位4代;76年;10年", 76),
                                       ("甲41年,乙25年,丙10年", 10)])
def test_first_segment_with_a_value_last_value_in_it(line, want):
    assert fv(line) == want


@pytest.mark.parametrize("line,k,want", [
    ("76年,分別是甲朗41年、乙朗25年、丙朗10年", YEARS, 76),
    ("甲朗到丙朗76年,其中甲朗41年、乙朗25年、丙朗10年", YEARS, 76),
    ("甲雅生乙雅時是28歲,因為甲雅去世時60歲,而乙雅登基時32歲", key(28, ("A", "Y")), 28),
    ("甲士235歲時丁亞出生,計算方式為甲士65歲生乙南、乙南90歲生丙列、丙列80歲生丁亞", AGE, 235),
    ("丁亞出生時甲士235歲,計算過程:65歲+90歲+80歲", AGE, 235),
    ("丙伯在洪水之後67年出生,因為甲法撒生於洪水後2年", key(67, ("Y",), True), 67),
    # lifespan cue words (execution log variant)
    ("丁亞出生時甲士235歲,甲士共活912歲", AGE, 235),
    ("丁亞出生時甲士的年齡為235歲,甲士的總壽數為912歲,甲士去世時丁亞677歲", AGE, 235),
    ("丁亞出生時甲士235歲,甲士享壽912歲", AGE, 235),
    ("丁亞出生時甲士235歲,甲士一共活了912歲", AGE, 235),
    # G's three F5 lines as one sentence: the first value, like the prereg's three-line F5 ruling (0)
    ("丁拉出生時甲南的年齡為362歲,甲南的總壽數為910歲,甲南去世時丁拉的年齡為548歲", key(548, ("A", "Y")), 362),
])
def test_step_4_ignores_values_after_a_cue_word_that_follows_the_first_value(line, k, want):
    assert K.final_value(line, k)[0] == want


@pytest.mark.parametrize("line,want", [
    ("甲士共活912歲,丁亞出生時甲士235歲", 235),               # the cue comes before the first value
    ("甲士65歲生乙南,根據輔助資料推算,丁亞出生時甲士235歲", 235),   # 根據／經文記載／由於 are not cue words
    ("甲士65歲生乙南,經文記載乙南90歲生丙列,丙列80歲生丁亞,丁亞出生時甲士235歲", 235),
    ("甲士65歲生乙南,由於乙南90歲生丙列、丙列80歲生丁亞,丁亞出生時甲士235歲", 235),
])
def test_reasons_first_lines_keep_the_last_value(line, want):
    assert fv(line, AGE) == want


def test_age_keys_take_years_only_when_the_line_has_no_age():
    assert fv("甲當時235年", AGE) == 235
    assert fv("乙出生後105年;丙出生時甲235歲", AGE) == 235
    assert fv("甲在位16年,登基25歲,乙出生時甲235歲", AGE) == 235


# ---------------------------------------------------------------- exactness
@pytest.mark.parametrize("line", ["40到41年", "40或41年", "40年或41年", "40~41年", "40-41年", "40至41年", "四十或四十一年",
                                  "40年,或41年", "40年還是41年", "40/41年"])
def test_ranges_and_alternatives_score_zero_as_hedge(line):
    v, f = K.final_value(line, key(41))
    assert v is None and "hedge" in f


@pytest.mark.parametrize("line", ["五十多年", "五十餘年", "50年左右", "41年多", "50多年"])
def test_inexact_values_score_zero(line):
    v, f = K.final_value(line, key(50))
    assert v is None and "inexact" in f


def test_same_value_twice_is_not_a_hedge_and_approx_is_only_flagged():
    assert fv("41年或41年", key(41)) == 41
    v, f = K.final_value("約41年", key(41))
    assert v == 41 and "approx" in f
    assert "approx" not in flags("約丙朗在位25年", key(25))


# ---------------------------------------------------------------- score_line_x on number keys
def arith_item(value, classes=("Y",), ordinal=False, distractors=()):
    return {"id": "T_01", "family": "DYN", "qtype": "S5", "keys": [key(value, classes, ordinal)],
            "distractors": [{"value": v, "kind": k} for v, k in distractors]}


def test_score_line_hedge_is_a_trap_and_none_is_a_format_failure():
    it = arith_item(41)
    r = K.score_line_x(it, "40或41年")
    assert (r["score"], r["trap"], r["format_fail"]) == (0, ["hedge"], False)
    r = K.score_line_x(it, None)
    assert (r["score"], r["format_fail"], r["trap"]) == (0, True, [])
    r = K.score_line_x(it, "共41年")
    assert (r["score"], r["value"], r["hits"], r["distractor"]) == (1, 41, [True], None)


def test_score_line_labels_distractors_without_changing_the_score():
    it = arith_item(76, distractors=[(41, "component"), (75, "off_by_one"), (75, "drop_last")])
    r = K.score_line_x(it, "共75年")
    assert r["score"] == 0 and sorted(r["distractor"]) == ["drop_last", "off_by_one"]
    r = K.score_line_x(it, "共99年")
    assert r["score"] == 0 and r["distractor"] is None
    r = K.score_line_x(it, "共76年")
    assert r["score"] == 1 and r["distractor"] is None


# ---------------------------------------------------------------- score_any (sensitivity, execution log)
@pytest.mark.parametrize("line,score,any_", [
    ("76年,甲朗在位41年,乙朗在位25年,丙朗在位10年", 0, 1),        # the gold written, another value taken
    ("甲朗=41年,乙朗=25年,丙朗=10年,共76年", 0, 1),
    ("共76年", 1, 1), ("76", 1, 1), ("75年", 0, 0),
    ("76年或75年", 0, 0), ("76年左右", 0, 0), ("七十六年多", 0, 0),       # hedged or inexact: never
    ("從甲到丁共4位,總共76", 0, 0),                                       # a bare number that is not the only one
    ("76個月,在位10年", 0, 0),                                            # another unit
])
def test_score_any_is_one_when_the_gold_is_written_as_an_accepted_value(line, score, any_):
    r = K.score_line_x(arith_item(76), line)
    assert (r["score"], r["score_any"]) == (score, any_)


def test_score_any_never_lowers_the_score_and_is_zero_without_an_answer_line():
    it = arith_item(76)
    for line in ("共76年", "76", "41+25+10=76", "共計:76", "76年;甲41年"):
        r = K.score_line_x(it, line)
        assert r["score"] == 1 and r["score_any"] == 1, line
    assert K.score_line_x(it, None)["score_any"] == 0
    assert K.gold_written(None, YEARS) is False


# ---------------------------------------------------------------- K0-4: G derived lines copied verbatim
def g_answer(*lines):
    """A generation whose answer line is the given G derived lines, verbatim, one per line."""
    return "依上列資料推算如下。\n答案：" + "\n".join(lines)


def scored(item, content):
    return K.score_line_x(item, K.answer_text_x(content))


S5_SUM = "甲朗 到 丁朗（含首尾，共 4 位）在位年數首尾相接合計：76 年"
S5_HANDOVER = "甲朗 到 丁朗 之間王位交接 3 次"
S6_LINE = "甲雅 生 乙雅 時：35 歲＋25 年−32 歲＝28 歲"
GEN_BIRTH = "丙 出生時 甲 的年齡：235 歲"
GEN_LIFE = "甲 的總壽數：912 歲"
GEN_DEATH = "甲 去世時 丙 的年齡：677 歲"
GEN_DEATH_ALT = ("丙 在 甲 去世前 12 年已去世", "甲 在 丙 出生前 5 年去世", "甲在 300 歲時被取去")
F3_LINE = "丁 在洪水之後 37 年出生"


@pytest.mark.parametrize("lines", [(S5_SUM,), (S5_SUM, S5_HANDOVER), (S5_HANDOVER, S5_SUM)])
def test_k0_4_s5_derived_lines_copied_score_gold(lines):
    assert scored(arith_item(76), g_answer(*lines))["score"] == 1


def test_k0_4_s5_sum_line_without_brackets_scores_gold():
    assert scored(arith_item(76), g_answer("甲朗到丁朗,含首尾,共4位,在位年數首尾相接合計:76年"))["score"] == 1


def test_k0_4_s6_derived_line_copied_scores_gold():
    assert scored(arith_item(28, ("A", "Y")), g_answer(S6_LINE))["score"] == 1


@pytest.mark.parametrize("death", (GEN_DEATH,) + GEN_DEATH_ALT)
def test_k0_4_f1_three_derived_lines_copied_score_gold(death):
    assert scored(arith_item(235, ("A", "Y")), g_answer(GEN_BIRTH, GEN_LIFE, death))["score"] == 1


def test_k0_4_f3_derived_line_copied_scores_gold():
    assert scored(arith_item(37, ("Y",), ordinal=True), g_answer(F3_LINE))["score"] == 1


def test_k0_4_f5_death_line_alone_scores_gold_and_three_lines_score_zero():
    f5 = arith_item(677, ("A", "Y"))
    assert scored(f5, g_answer(GEN_DEATH))["score"] == 1
    r = scored(f5, g_answer(GEN_BIRTH, GEN_LIFE, GEN_DEATH))
    assert (r["score"], r["value"], r["flags"][0]) == (0, 235, "segment")


def test_k0_4_f3_echo_cases_are_recorded():
    """The answer line also writes the flood anchor's 2 years: scored by §5 as is (appendix)."""
    table = {c["case"]: c for c in K.f3_echo_table()}
    assert {c: (r["value"], r["score"]) for c, r in table.items()} == {
        "anchor_first_segment": (2, 0), "anchor_same_segment": (37, 1), "anchor_after_answer": (2, 0),
        "anchor_after_answer_because": (37, 1), "anchor_in_brackets": (37, 1), "anchor_in_sum": (37, 1),
        "anchor_total_word": (37, 1)}
    assert all(set(c) >= {"case", "line", "value", "flags", "score"} for c in table.values())


# ---------------------------------------------------------------- K0-4: SYNC name keys (toy View)
def toy_view():
    from regnal import View
    V = View("toy")
    for kd, names in (("I", ("甲朗", "乙朗", "丙朗", "丁朗", "戊朗")), ("J", ("甲雅", "乙雅", "丙雅", "丁雅", "戊雅"))):
        for i, nm in enumerate(names, 1):
            x = f"{kd}{i:02d}"
            V.nodes[x] = dict(kingdom=kd, name=nm, aliases=[], reign=10 + i, age=20 + i, mother=None, mother_desc=None,
                              father=names[i - 2] if i > 1 else None, death=None, has_acc=True, prov={})
            V.chain[kd].append(x)
    # primary syncs: J03 acceded in I02's 5th year, I04 in J03's 7th year
    V.syncs += [("J03", "I02", 5, "t.1.1", True), ("I04", "J03", 7, "t.1.2", True), ("J04", "I03", 2, "t.1.3", True)]
    return V


def sync_item(seed, k, kd, y, z, zkd):
    return {"id": "SYNC_t", "family": "SYNC", "qtype": f"SYNC{k}", "kingdom": kd, "seeds_ref": [seed], "k": k,
            "path": [f"p{i}" for i in range(k + 1)], "gold": {"Y": y, "Z": z},
            "keys": [{"type": "name", "role": "Y", "kingdom": kd, "accept": [y], "basis": []},
                     {"type": "name", "role": "Z", "kingdom": zkd, "accept": [z], "basis": []}]}


@pytest.fixture(scope="module")
def toy():
    V = toy_view()
    from keys_a import king_lexicon
    judah = sync_item("J01", 2, "J", "丙雅", "乙朗", "I")
    israel = sync_item("I02", 2, "I", "丁朗", "丙雅", "J")
    return {"V": V, "J": (judah, K.ctxs_x(judah, V, king_lexicon(V))), "I": (israel, K.ctxs_x(israel, V, king_lexicon(V)))}


@pytest.mark.parametrize("kd,line", [
    ("J", "丙雅;以色列王乙朗"), ("J", "猶大王丙雅於以色列王乙朗第5年登基"),
    ("I", "丁朗;猶大王丙雅"), ("I", "以色列王丁朗於猶大王丙雅第7年登基"),
    ("J", "甲雅之後第2位猶大王:丙雅;丙雅登基時對方國在位:乙朗(丙雅於乙朗第5年登基)"),
    ("J", "猶大王丙雅:父乙雅;在位13年;登基23歲;繼位:子繼父;於以色列王乙朗第5年登基"),
])
def test_k0_4_sync_both_writings_score_one(toy, kd, line):
    item, ctxs = toy[kd]
    r = K.score_line_x(item, line, ctxs)
    assert (r["score"], r["hits"], r["trap"]) == (1, [True, True], [])


def test_sync_needs_both_keys_and_reports_z_alone(toy):
    item, ctxs = toy["J"]
    r = K.score_line_x(item, "以色列王乙朗", ctxs)
    assert (r["score"], r["score_z"], r["hits"]) == (0, 1, [False, True])
    r = K.score_line_x(item, "丙雅", ctxs)
    assert (r["score"], r["score_z"]) == (0, 0)


@pytest.mark.parametrize("line", ["丙雅;以色列王乙朗", "以色列王乙朗", "丙雅;以色列王乙朗或丙朗"])
def test_sync_score_any_is_the_strict_score(toy, line):
    item, ctxs = toy["J"]
    r = K.score_line_x(item, line, ctxs)
    assert r["score_any"] == r["score"]
    assert K.score_line_x(item, None, ctxs)["score_any"] == 0


def test_sync_naming_a_second_other_kingdom_king_is_a_trap(toy):
    item, ctxs = toy["J"]
    r = K.score_line_x(item, "丙雅;以色列王乙朗或丙朗", ctxs)
    assert r["score"] == 0 and r["trap"] and r["score_z"] == 0


def test_sync_one_ctx_per_key_is_why_the_prefixed_z_counts(toy):
    """A single item_ctx with the item's kingdom drops the name after 「以色列王」 (prereg §5 reason)."""
    from keys_a import item_ctx, key_hit, king_lexicon
    item, _ = toy["J"]
    one = item_ctx(dict(item, gold=["J03"], seeds=["J01"], exempt=[]), toy["V"], king_lexicon(toy["V"]))
    assert [key_hit(one, k, "丙雅;以色列王乙朗") for k in item["keys"]] == [True, False]


def test_sync_ctx_resolves_gold_ids_and_checks_accept(toy):
    item, ctxs = toy["J"]
    assert ctxs["Y"]["item"]["gold"] == ["J03"] and ctxs["Z"]["item"]["gold"] == ["I02"]
    bad = sync_item("J01", 2, "J", "丁雅", "乙朗", "I")
    from keys_a import king_lexicon
    with pytest.raises(ValueError):
        K.ctxs_x(bad, toy["V"], king_lexicon(toy["V"]))


@pytest.mark.parametrize("change", [{"gold_ref": "J04"}, {"exempt": ["丙雅"]}])
def test_sync_ctx_refuses_a_key_that_disagrees_with_the_reference(toy, change):
    from keys_a import king_lexicon
    item, _ = toy["J"]
    bad = dict(item, keys=[dict(item["keys"][0], **change), item["keys"][1]])
    with pytest.raises(ValueError):
        K.ctxs_x(bad, toy["V"], king_lexicon(toy["V"]))


def test_sync_ctx_accepts_the_builders_gold_ref_exempt_and_path_ref(toy):
    from keys_a import king_lexicon
    item, _ = toy["J"]
    exempt = sorted({"甲雅", "乙雅", "丙雅", "乙朗"})
    good = dict(item, path_ref=["J01", "J02", "J03"],
                keys=[dict(item["keys"][0], gold_ref="J03", exempt=exempt), dict(item["keys"][1], gold_ref="I02")])
    assert set(K.ctxs_x(good, toy["V"], king_lexicon(toy["V"]))) == {"Y", "Z"}
    with pytest.raises(ValueError):
        K.ctxs_x(dict(good, path_ref=["J01", "J02", "J04"]), toy["V"], king_lexicon(toy["V"]))


# ---------------------------------------------------------------- K0-4 on a card: the item's own lines
def fake_card(*lines):
    """(kind, seeds, head, payload) lines as engine_x.card returns them (lines + tags)."""
    return {"lines": [[h, p] for _k, _s, h, p in lines],
            "tags": [{"kind": k, "seeds": list(s), "k": None, "value": None, "unit": None} for k, s, _h, _p in lines]}


GEN_CARD = fake_card(("born_age", ("x", "y"), "丙出生時甲的年齡", "235歲"), ("total", ("x",), "甲的總壽數", "912歲"),
                     ("death_age", ("x", "y"), "甲去世時丙的年齡", "677歲"), ("flood", ("y",), "", "丙在洪水之後50年出生"))


def test_copy_cases_f1_and_f5_follow_the_prereg_sets():
    f1 = dict(arith_item(235, ("A", "Y")), qtype="F1", family="GEN", seeds=["x", "y"])
    assert [(c["case"], c["want"], c["got"]) for c in K.copy_cases(f1, GEN_CARD)] == [("born_age+total+death", 1, 1)]
    f5 = dict(arith_item(677, ("A", "Y")), qtype="F5", family="GEN", seeds=["x", "y"])
    assert [(c["case"], c["want"], c["got"], c["value"]) for c in K.copy_cases(f5, GEN_CARD)] == [
        ("death_age", 1, 1, 677), ("born_age+total+death", 0, 0, 235)]


def test_copy_cases_s5_and_a_missing_line():
    card = fake_card(("sum", ("a", "b"), "甲朗到丁朗（含首尾，共4位）在位年數首尾相接合計", "76年"),
                     ("handover", ("a", "b"), "", "甲朗到丁朗之間王位交接3次"))
    s5 = dict(arith_item(76), seeds=["a", "b"])
    assert [(c["case"], c["got"]) for c in K.copy_cases(s5, card)] == [("sum", 1), ("sum+handover", 1),
                                                                        ("handover+sum", 1)]
    assert K.copy_cases(dict(s5, qtype="S6"), card) == [{"case": "father_age", "want": 1, "got": None, "value": None}]


# ---------------------------------------------------------------- store-backed
KG = X.STORE / "reports/kg_cards_20261018"
needs_a = pytest.mark.skipif(not (KG / "A/gen_arms.jsonl").is_file(), reason=f"store not mounted ({KG})")
needs_ref = pytest.mark.skipif(not X.REF_V2.is_file(), reason=f"store not mounted ({X.REF_V2})")


@needs_a
def test_store_answer_text_x_equals_score_a_on_every_stored_generation():
    import score_a
    n = 0
    for sub in ("A", "A_confirm"):
        for line in (KG / sub / "gen_arms.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("type") == "answer":
                n += 1
                assert K.answer_text_x(rec["content"]) == score_a.answer_text(rec["content"]), rec["job_id"]
    assert n == 747


@needs_ref
def test_store_sync_writings_score_one_on_every_reference_candidate():
    """k = 2, 3 from every king, target with one primary sync, answer names borne in one kingdom only."""
    from keys_a import king_lexicon
    V = X.ref_v2_view()
    base = king_lexicon(V)
    kname = {"I": "以色列", "J": "猶大"}
    names = {kd: {nm for x, n in V.nodes.items() if n["kingdom"] == kd for nm in V.names(x)} for kd in "IJ"}
    n = 0
    for kd in "IJ":
        for x in V.chain[kd]:
            for k in (2, 3):
                y = V.succ(x, k)
                zs = [o for (a, o, _yr, _v, prim) in V.syncs if a == y and prim] if y else []
                if len(zs) != 1:
                    continue
                z = zs[0]
                zkd = V.nodes[z]["kingdom"]
                path = [V.succ(x, i) for i in range(k + 1)]
                if "J07" in path or V.nodes[y]["name"] in names[zkd] or V.nodes[z]["name"] in names[kd]:
                    continue
                yn, zn = V.nodes[y]["name"], V.nodes[z]["name"]
                it = sync_item(x, k, kd, yn, zn, zkd)
                ctxs = K.ctxs_x(it, V, base)
                yr = next(yr for (a, o, yr, _v, prim) in V.syncs if a == y and prim)
                for line in (f"{yn};{kname[zkd]}王{zn}", f"{kname[kd]}王{yn}於{kname[zkd]}王{zn}第{yr}年登基"):
                    assert K.score_line_x(it, line, ctxs)["score"] == 1, (x, k)
                n += 1
    assert n >= 29


needs_build = pytest.mark.skipif(not (X.REF_V2.is_file() and X.R4_LAYER.is_file() and (X.TEXT / "verse_units.jsonl").is_file()),
                                 reason="store not mounted (layers for the item builder)")


@needs_build
def test_store_k0_4_every_items_own_g_lines_copied_score_as_registered():
    """K0-4 on the 52 template items built in memory (items_x, gen_layer, engine_x; nothing written)."""
    import engine_x
    import gen_layer
    import items_x
    from keys_a import king_lexicon
    gen = gen_layer.build()
    doc = items_x.build_items(gen=gen)
    V = X.ref_v2_view()
    base = king_lexicon(V)
    bad, n = [], 0
    for it in doc["items"]:
        ctxs = K.ctxs_x(it, V, base) if it["family"] == "SYNC" else None
        for c in K.copy_cases(it, engine_x.card(it, gen=gen), ctxs):
            n += 1
            if c["got"] != c["want"]:
                bad.append((it["id"], c["case"], c["want"], c["got"]))
    assert bad == [] and n == 14 * 3 + 4 + 12 + 4 + 2 * 2 + 16 * 3
