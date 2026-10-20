"""GEN confirmation set: syntactic checks of drafted questions and the three-way value comparison (prereg §3.4–§3.6).

A synthetic draft bank (made-up chain and names from test_gen_confirm_prompts) holds valid drafts and one
mutation per rule branch; the §3.4 pins (包含, 瑪土撒拉/撒拉, 兩人, 一生, 那一年) must not raise any error: the
store-free tests pin them with made-up stand-ins (梅洛撒蒂/撒蒂, the one-character 計 inside 合計), the store tests
with the real names read from gen_names.json at run time. syntax_violations (the P2 validity check, §5.6) runs on
bare qset-shaped questions. The value comparison is checked row by row, with the spent-round rule and row 3 as a
dispute. Store tests check the book list against the text layer and run every pool slot through a canonical
question built at run time (only counts, ids and rule names are asserted). Nothing calls Ollama or any LLM.
"""

import json
import sys
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import banned_g as B  # noqa: E402
import g_common as GC  # noqa: E402
import mech_g as M  # noqa: E402
import prompts_g as P  # noqa: E402
from test_gen_confirm_prompts import (CHAIN, Q_11, Q_F1, Q_F5, Q_MK, ROW_11, ROW_F1, ROW_F5, ROW_MK,  # noqa: E402
                                      STAND_IN_CUES, _gencard_cues, draft, fake_names, names_doc, pool_row,
                                      real_names)

BOOKS = GC.STAGE0_OUT.parents[1] / "layers/text/text@247eafe44b02/books.jsonl"
needs_store = pytest.mark.skipif(not GC.POOL.is_file(), reason=f"store not mounted ({GC.POOL})")
ROW_11B = pool_row("F1", "歐芙", "蘇倫", sid="S04")      # the one-character chain name 雷 is neither X nor Y
# CASES rows that fail only on the item's marker field (a bare P2 question has none)
FIELD_ONLY = {("洛珊的父親賽琳", None), ("洛珊的父親賽琳", "洛珊的父親"), (None, "柏羅丹的兒子茵德")}


@pytest.fixture(autouse=True)
def stand_in_cues():
    with B.override_cue_literals(STAND_IN_CUES):
        yield


def errors(row: dict, question: str, names: "P.Names | None" = None, **kw) -> set[str]:
    names = names or fake_names()
    qid = kw.pop("qid", "Q01")
    spec = P.slot_spec(row, names, qid)
    item = {**draft(row, question, qid=qid, **kw), "X": spec.x, "Y": spec.y}
    return {v.rule for v in M.errors_of(M.check_draft(item, spec, names))}


def item_errors(row: dict, item: dict, names: "P.Names | None" = None) -> set[str]:
    names = names or fake_names()
    return {v.rule for v in M.errors_of(M.check_draft(item, P.slot_spec(row, names, "Q01"), names))}


# ---------------------------------------------------------------- valid drafts
VALID = [
    (ROW_F1, Q_F1, {}),
    (ROW_F5, Q_F5, {}),
    (ROW_MK, Q_MK, {"marker": "洛珊的父親賽琳"}),
    (ROW_MK, "按創世記，賽琳（洛珊的父親）出生時，瓦勒幾歲？", {"marker": "洛珊的父親賽琳"}),
    (ROW_11, Q_11, {}),
    (ROW_F1, "根據創世記，柯梅出生後隔了多少年，茵德才出生？", {"unit": "年"}),
    (ROW_F1, "依創世記，柯梅的子孫茵德出生的時候，柯梅已經多老了", {}),
    (pool_row("F1", "茵德", "梅洛撒蒂"), "創世記說茵德活到多大時，梅洛撒蒂才出生？", {}),
    (ROW_F1, "依創世記，茵德出生時，柯梅已經多少年紀？", {}),             # 多少年紀 asks an age, not years
    (ROW_F1, "依創世記，茵德出生時，柯梅是多少年歲？", {}),
    (ROW_F5, "依創世記，柏羅丹去世時，梅洛撒蒂到了多少年齡？", {}),
    (ROW_F1, "依創世記，柯梅出生以後過了多久，茵德才出生？", {"unit": "年"}),
    (ROW_F1, "依創世記，在柯梅的子子孫孫裡，茵德出生時柯梅幾歲？", {}),      # 子子孫孫 is no generation count
    (ROW_F1, "依創世記，你知道嗎，茵德出生時柯梅幾歲？", {}),          # 嗎 not at the sentence end (§3.4 literal)
]


@pytest.mark.parametrize("row, question, kw", VALID)
def test_valid_drafts_raise_no_error(row, question, kw):
    assert errors(row, question, **kw) == set()


# ---------------------------------------------------------------- the §3.4 pins (each must raise no error)
PINS = [
    (ROW_F1, "依創世記的記載（包含茵德出生的那一年），柯梅幾歲？"),
    (ROW_F1, "依創世記，柯梅與茵德兩人之中，茵德出生時柯梅幾歲？"),
    (ROW_F5, "依創世記，柏羅丹的一生走完時，梅洛撒蒂幾歲？"),
    (ROW_F1, "依創世記，茵德出生的那一年，柯梅幾歲？"),
    (ROW_F1, "依創世記，茵德出生在同一年柯梅幾歲？"),
    (ROW_F5, "照創世記，柏羅丹去世這一年，梅洛撒蒂多大？"),
    (ROW_F1, "依創世記（含茵德出生那年），柯梅幾歲？"),
    (ROW_F1, "依創世記（計茵德出生那年），柯梅幾歲？"),                  # the made-up one-character name 計
    (ROW_F1, "依創世記的記載，合計在內來算，茵德出生時柯梅幾歲？"),
    (ROW_F1, "依創世記，從柯梅出生起總計多少年，茵德才出生？"),
    (ROW_F1, "依創世記（計出生那年），茵德出生時柯梅幾歲？"),            # one-character extras stay strict
]


@pytest.mark.parametrize("row, question", PINS)
def test_pins_raise_no_error(row, question):
    assert errors(row, question, unit="年" if "多少年" in question else "歲") == set()


def test_pin_a_name_inside_a_longer_name_with_made_up_names():
    names = fake_names()                                  # 撒蒂 inside 梅洛撒蒂 stands in for 撒拉 / 瑪土撒拉
    assert "撒蒂" in names.extra_persons and "梅洛撒蒂" in [p.name for p in names.chain]
    assert errors(ROW_F5, "照創世記所記，柏羅丹去世的時候，梅洛撒蒂多大？", names) == set()
    row = pool_row("F1", "瓦勒", "賽琳")
    found = M.check_draft(draft(row, "按創世記，瓦勒幾歲時梅洛撒蒂的兒子賽琳出生？"), P.slot_spec(row, names, "Q01"), names)
    extra = [v for v in found if v.rule == "extra_name"]
    assert len(extra) == 1 and extra[0].quote == "梅洛撒蒂"


def test_pin_a_one_character_name_inside_a_word_with_a_made_up_name():
    names = fake_names()
    assert "計" in names.extra_persons
    assert errors(ROW_F1, "依創世記的記載，合計在內來算，茵德出生時柯梅幾歲？") == set()
    assert "extra_name" in errors(ROW_F1, "依創世記，柯梅、計、茵德之中，茵德出生時柯梅幾歲？")
    assert M.extra_names("依創世記，計的兒子茵德出生時柯梅幾歲？", P.slot_spec(ROW_F1, names, "Q01"), names) == ["計"]


# ---------------------------------------------------------------- one mutation per rule
def _item(row, question, **change):
    it = draft(row, question)
    for k, v in change.items():
        it = {**it, k: v}
    return it


SCHEMA_BAD = [
    {k: v for k, v in draft(ROW_F1, Q_F1).items() if k != "steps"},
    _item(ROW_F1, Q_F1, qtype="F1"),
    _item(ROW_F1, Q_F1, answer={"value": 235}),
    _item(ROW_F1, Q_F1, steps=[{"person": "柯梅", "fact": "x", "verse": "5:3"},
                               {"person": "茵德", "fact": "y", "verse": "gen.5.6"}]),
    _item(ROW_F1, Q_F1, steps=[{"person": "柯梅", "fact": "x", "verse": "gen.5.3"}]),
    _item(ROW_F1, Q_F1, marker=5),
    _item(ROW_F1, Q_F1, notes=None),
    _item(ROW_F1, ""),
]


@pytest.mark.parametrize("item", SCHEMA_BAD)
def test_schema_rejects_malformed_items(item):
    assert "schema" in item_errors(ROW_F1, item)


@pytest.mark.parametrize("change", [{"id": "Q09"}, {"slot": "Q09"}, {"qtype": "age_at_death"}, {"X": "柏羅丹"},
                                    {"Y": "無名氏"}])
def test_slot_match(change):
    assert "slot_match" in item_errors(ROW_F1, _item(ROW_F1, Q_F1, **change))


CASES = [
    ("names_present", ROW_F1, "依創世記的記載，柯梅幾歲時生下這個人？", {}),
    ("names_present", ROW_F1, "依創世記，茵德出生那一年，那位先祖幾歲？", {}),
    ("extra_name", ROW_F1, "依創世記，柯梅幾歲時，柏羅丹之後的茵德出生？", {}),
    ("extra_name", ROW_F1, "依創世記，卡斯不算，茵德出生時柯梅幾歲？", {}),
    ("extra_name", ROW_F1, "依創世記，柯梅、計與茵德中，茵德出生時柯梅幾歲？", {}),
    ("extra_name", ROW_F1, "依創世記，撒蒂以外，茵德出生時柯梅幾歲？", {}),
    ("extra_name", ROW_11, "創世記記載雷去世那年，歐芙的兒子葛林的年紀是？", {}),
    ("marker_rule", ROW_MK, "按創世記，瓦勒幾歲時賽琳出生？", {"marker": "洛珊的父親賽琳"}),
    ("marker_rule", ROW_MK, Q_MK, {"marker": None}),
    ("marker_rule", ROW_MK, Q_MK, {"marker": "洛珊的父親"}),
    ("marker_rule", ROW_MK, "按創世記，瓦勒幾歲時梅洛撒蒂的兒子賽琳出生？", {"marker": "梅洛撒蒂的兒子賽琳"}),
    ("marker_rule", ROW_MK, "按創世記，瓦勒幾歲時洛珊的兒子賽琳出生？", {"marker": "洛珊的父親賽琳"}),
    ("marker_rule", ROW_F1, Q_F1, {"marker": "柏羅丹的兒子茵德"}),
    ("marker_rule", ROW_F1, "依創世記，柯梅幾歲時柏羅丹的兒子茵德出生？", {}),
    ("marker_rule", ROW_F1, "依創世記，柯梅幾歲時茵德（瓦勒的父親）出生？", {}),
    ("v_number", ROW_F1, "依創世記第五章，茵德出生時柯梅幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，柯梅130歲以後茵德出生時他幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，柯梅活過九百多那時茵德出生，他幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，茵德出生前一年柯梅幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，茵德出生時柯梅是否過了百歲以後的幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，茵德出生時柯梅幾歲？（第３節）", {}),
    ("v_number", ROW_F1, "依創世記，柯梅之後三世，茵德出生時柯梅幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，茵德出生時柯梅已經百多歲，確切是幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，柯梅出生後十多年茵德才出生，那時柯梅幾歲？", {}),
    ("v_number", ROW_F1, "依創世記，柯梅活了百餘年後茵德出生，柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，柯梅的孫子茵德出生時柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，茵德出生時他的祖父柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，茵德出生時他的曾祖柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，柯梅和茵德隔了幾代，茵德出生時柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，柯梅的兒子孫子茵德出生時柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，茵德出生時他的高祖柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，柯梅與茵德相隔多少代，茵德出生時柯梅幾歲？", {}),
    ("v_kin", ROW_F1, "依創世記，在子子孫孫的孫輩裡，茵德出生時柯梅幾歲？", {}),
    ("v_source", ROW_F1, "茵德出生那一年，柯梅幾歲？", {}),
    ("v_source", ROW_F1, "依創世記和路加福音，茵德出生那一年，柯梅幾歲？", {}),
    ("v_source", ROW_F1, "依創世記與出埃及記，茵德出生那一年，柯梅幾歲？", {}),
    ("v_source", ROW_F1, "依創世紀，茵德出生那一年，柯梅幾歲？", {}),
    ("ordinal_form", ROW_F1, "依創世記，茵德出生在柯梅人生的第幾年？", {"unit": "年"}),
    ("ordinal_form", ROW_F1, "依創世記，茵德出生是柯梅的第多少年？", {"unit": "年"}),
    ("yes_no", ROW_F1, "依創世記，茵德出生時柯梅幾歲，有記載嗎？", {}),
    ("yes_no", ROW_F1, "依創世記，是否能算出茵德出生時柯梅幾歲？", {}),
    ("yes_no", ROW_F1, "依創世記，茵德出生時柯梅是不是很老了，幾歲", {}),
    ("yes_no", ROW_F1, "依創世記，有沒有辦法知道茵德出生時柯梅幾歲？", {}),
    ("multi_question", ROW_F1, "依創世記，茵德出生時柯梅幾歲？柯梅又活了多久？", {}),
    ("key_form", ROW_F1, Q_F1, {"unit": "年"}),
    ("key_form", ROW_F1, "根據創世記，柯梅出生後隔了多少年，茵德才出生？", {"unit": "歲"}),
    ("key_form", ROW_F1, Q_F1, {"value": "235"}),
    ("key_form", ROW_F1, Q_F1, {"value": True}),
    ("key_form", ROW_F1, Q_F1, {"value": 0}),
    ("key_form", ROW_F1, "依創世記，柯梅出生以後過了多久，茵德才出生？", {"unit": "歲"}),
    ("marker_rule", ROW_MK, Q_MK + "洛珊的父親賽琳", {"marker": "洛珊的父親賽琳"}),        # written twice
]


@pytest.mark.parametrize("rule, row, question, kw", CASES)
def test_each_rule_rejects_its_mutation(rule, row, question, kw):
    assert rule in errors(row, question, **kw), (rule, question)


def test_every_rule_has_a_rejecting_case_and_runs_on_every_draft():
    covered = {r for r, *_ in CASES} | {"schema", "slot_match"}
    assert covered == set(M.RULES)


def test_all_rules_are_reported_not_only_the_first():
    got = errors(ROW_F1, "依第五章，柯梅的孫子柏羅丹是否幾歲？嗎？", unit="年")
    assert {"names_present", "extra_name", "v_number", "v_kin", "v_source", "yes_no", "multi_question",
            "key_form"} <= got


@pytest.mark.parametrize("item, also", [
    ({k: v for k, v in draft(ROW_F1, "依創世記第五章，茵德出生時柯梅幾歲？").items() if k != "notes"}, {"v_number"}),
    (_item(ROW_F1, "依創世記，茵德出生時他的祖父柯梅幾歲？", answer={"value": 7}), {"v_kin"}),
    (_item(ROW_F1, "依創世記，柏羅丹出生時柯梅幾歲？", X=5), {"slot_match", "names_present", "extra_name"}),
    ({"question": "依第五章，柯梅的孫子在130歲時是否…嗎？？", "answer": "1"},
     {"names_present", "v_number", "v_kin", "v_source", "yes_no", "multi_question"}),
])
def test_a_schema_error_does_not_hide_the_question_rules(item, also):
    assert {"schema"} | also <= item_errors(ROW_F1, item)


# ---------------------------------------------------------------- P2 validity: the syntax rules on a bare question
def test_p2_rules_are_the_prereg_list():
    assert M.P2_RULES == ("names_present", "extra_name", "marker_rule", "v_number", "v_kin", "v_source",
                          "ordinal_form", "yes_no", "multi_question")
    assert set(M.P2_RULES) == set(M.RULES) - {"schema", "slot_match", "key_form"}


def test_syntax_violations_on_a_qset_shaped_question():
    names, spec = fake_names(), P.slot_spec(ROW_F1, fake_names(), "Q01")
    q = "依第五章，柯梅的孫子在130歲時是否…嗎？？"
    assert {v.rule for v in M.syntax_violations(q, spec, names)} == {"names_present", "v_number", "v_kin", "v_source",
                                                                     "yes_no", "multi_question"}
    assert M.syntax_violations(Q_F1, spec, names) == []
    for bad in ("", "  ", None, 5):
        with pytest.raises(ValueError):
            M.syntax_violations(bad, spec, names)


def _syntax(row: dict, question: str) -> set[str]:
    names = fake_names()
    return {v.rule for v in M.errors_of(M.syntax_violations(question, P.slot_spec(row, names, "Q01"), names))}


@pytest.mark.parametrize("rule, row, question, kw", [c for c in CASES if c[0] in M.P2_RULES])
def test_syntax_violations_agree_with_check_draft_on_every_question_rule(rule, row, question, kw):
    got = _syntax(row, question)
    assert got <= set(M.P2_RULES)
    spec = P.slot_spec(row, fake_names(), "Q01")
    if (spec.marker, kw.get("marker", spec.marker)) in FIELD_ONLY:
        assert rule not in got                     # the bare question is fine; only the item's field is wrong
    else:
        assert rule in got and got == errors(row, question, **kw) & set(M.P2_RULES)


@pytest.mark.parametrize("row, question, kw", VALID)
def test_syntax_violations_pass_every_valid_draft(row, question, kw):
    assert _syntax(row, question) == set()


def test_the_marker_field_is_checked_only_on_an_item():
    names, spec = fake_names(), P.slot_spec(ROW_MK, fake_names(), "Q03")
    assert M.syntax_violations(Q_MK, spec, names) == []
    assert {v.rule for v in M.check_draft(draft(ROW_MK, Q_MK, qid="Q03", marker=None), spec, names)} == {"marker_rule"}


def test_canonical_item_takes_the_assigned_strings():
    names, spec = fake_names(), P.slot_spec(ROW_MK, fake_names(), "Q03")
    item = {**draft(ROW_MK, Q_MK, qid="Q03", marker="洛珊的父親賽琳"), "id": "Q03 ", "slot": "Ｑ０３", "X": "瓦勒\u3000"}
    assert M.errors_of(M.check_draft(item, spec, names)) == []
    out = M.canonical_item(item, spec)
    assert (out["id"], out["slot"], out["X"], out["Y"], out["marker"], out["qtype"]) == (
        "Q03", "Q03", "瓦勒", "賽琳", "洛珊的父親賽琳", "age_at_birth")
    assert item["id"] == "Q03 " and out["question"] == item["question"] and out is not item


def test_one_character_names_count_only_in_a_name_context():
    names, spec = fake_names(), P.slot_spec(ROW_F1, fake_names(), "Q01")
    for q in ("依創世記，柯梅聽見雷聲那年茵德出生，柯梅幾歲？", "依創世記，瑟瑟風中茵德出生時柯梅幾歲？"):
        assert M.extra_names(q, spec, names) == []
    for q, want in (("依創世記，除了雷，茵德出生時柯梅幾歲？", ["雷"]), ("依創世記，名叫瑟的人以外，茵德出生時柯梅幾歲？", ["瑟"]),
                    ("依創世記，茵德出生時柯梅與雷幾歲？", ["雷"])):
        assert M.extra_names(q, spec, names) == want, q


def test_routing_lexicon_superstrings_are_not_names():
    spec = P.slot_spec(ROW_F5, fake_names(), "Q01")
    assert M.extra_names("照創世記，柏羅丹在茵德城去世的時候，梅洛撒蒂多大？", spec, fake_names()) == []
    assert M.extra_names("照創世記，柏羅丹在瓦勒斯去世的時候，梅洛撒蒂多大？", spec, fake_names()) == []


def test_a_lexicon_blocker_never_swallows_a_cue_word():
    names = P.Names.from_doc(names_doc(lexicon_blockers=["瓦勒斯", "茵德城", "柏羅丹來"]))
    spec = P.slot_spec(ROW_F1, names, "Q01")                      # 柏羅丹 lies between 柯梅 and 茵德
    assert M.extra_names("依創世記，柏羅丹來到世上之後，茵德出生時柯梅幾歲？", spec, names) == ["柏羅丹"]
    assert M.extra_names("依創世記，柏羅丹來客的那年，茵德出生時柯梅幾歲？", spec, names) == []
    assert "extra_name" in errors(ROW_F1, "依創世記，柏羅丹來到世上之後，茵德出生時柯梅幾歲？", names)


@pytest.mark.parametrize("lead", ["雷過世那年之前", "雷出生以後", "雷在世時", "雷的年紀之外", "雷離世之前", "雷去世之前",
                                  "雷生了兒子以後", "雷的一生之中", "在雷逝世之後"])
def test_a_one_character_chain_name_counts_before_an_event_or_age_word(lead):
    names = fake_names()
    spec = P.slot_spec(ROW_11B, names, "Q01")
    assert M.extra_names(f"依創世記，{lead}，蘇倫出生時歐芙幾歲？", spec, names) == ["雷"]


def test_one_character_extra_names_stay_strict_before_event_words():
    names = fake_names()
    assert M.extra_names("依創世記（計出生那年），茵德出生時柯梅幾歲？", P.slot_spec(ROW_F1, names, "Q01"), names) == []
    assert M.extra_names("依創世記，雷聲過世那年之前，蘇倫出生時歐芙幾歲？", P.slot_spec(ROW_11B, names, "Q01"), names) == []


def _marker_details(row: dict, question: str, **kw) -> set[str]:
    names = fake_names()
    spec = P.slot_spec(row, names, "Q01")
    item = {**draft(row, question, **kw), "X": spec.x, "Y": spec.y}
    return {v.detail for v in M.errors_of(M.check_draft(item, spec, names)) if v.rule == "marker_rule"}


def test_marker_rule_reports_a_second_phrase_beside_the_right_one():
    got = _marker_details(ROW_MK, "按創世記，茵德的兒子瓦勒幾歲時洛珊的父親賽琳出生？", marker="洛珊的父親賽琳")
    assert got == {"the only identifying phrase allowed is 洛珊的父親賽琳"}


def test_marker_rule_reports_the_required_phrase_written_twice():
    got = _marker_details(ROW_MK, Q_MK + "洛珊的父親賽琳", marker="洛珊的父親賽琳")
    assert got == {"the question must contain the identifying phrase 洛珊的父親賽琳 exactly once"}


def test_marker_rule_reports_a_phrase_naming_someone_on_the_path():
    on = "an identifying phrase names someone on the line from 柯梅 to 茵德"
    assert on in _marker_details(ROW_F1, "依創世記，柯梅幾歲時柏羅丹的兒子茵德出生？")
    off = _marker_details(ROW_F1, "依創世記，柯梅幾歲時茵德（瓦勒的父親）出生？")
    assert off and on not in off


def test_marker_phrases_are_found_in_both_forms():
    names, spec = fake_names(), P.slot_spec(ROW_MK, fake_names(), "Q03")
    assert M.marker_phrases(Q_MK, spec, names) == [("洛珊", "父親", "賽琳")]
    assert M.marker_phrases("按創世記，賽琳 (洛珊的父親) 出生時，瓦勒幾歲？", spec, names) == [("洛珊", "父親", "賽琳")]
    assert M.marker_phrases("按創世記，茵德的兒子瓦勒幾歲時賽琳出生？", spec, names) == [("茵德", "兒子", "瓦勒")]


def test_details_are_tool_text_and_quotes_are_agent_text():
    item = draft(ROW_F1, "依第五章，柯梅的孫子柏羅丹是否幾歲？嗎？", unit="年")
    found = M.check_draft(item, P.slot_spec(ROW_F1, fake_names(), "Q01"), fake_names())
    for v in found:
        assert B.prompt_hits(v.detail) == [], v
        assert v.quote == "" or v.quote not in v.detail
    issues = M.fix_issues(found)
    assert len(issues) == len({(v.detail, v.quote) for v in M.errors_of(found)})
    r = P.render_fix("mech", ROW_F1, fake_names(), "Q01", item, issues)
    assert "孫子" in r.user and "the question uses another name (a person, people or place) besides 柯梅 and 茵德" in r.user


def test_every_mech_detail_and_hint_passes_the_full_check_with_the_real_cue_words():
    cues = _gencard_cues()
    names, details = fake_names(), {P.GOLD_MISMATCH_HINT, P.AMBIGUITY_HINT, " Suggested fix: ", ": "}
    for _, row, question, kw in CASES + [(None, ROW_F1, it["question"], {}) for it in SCHEMA_BAD[1:-1]]:
        spec = P.slot_spec(row, names, "Q01")
        item = {**draft(row, question, **kw), "X": spec.x, "Y": spec.y}
        details |= {v.detail for v in M.check_draft(item, spec, names)}
    for it in SCHEMA_BAD:
        details |= {v.detail for v in M.check_draft(it, P.slot_spec(ROW_F1, names, "Q01"), names)}
    assert len(details) > 30
    with B.override_cue_literals(cues):
        for d in details:
            assert B.prompt_hits(d) == [], d


def test_check_gen_output():
    it = draft(ROW_F1, Q_F1)
    assert M.check_gen_output({"status": "drafted", "reason": "", "item": it}) == []
    assert M.check_gen_output({"status": "abandoned", "reason": "cannot verify", "item": None}) == []
    for bad in ({"status": "drafted", "reason": "", "item": None}, {"status": "dropped", "reason": "", "item": it},
                {"status": "done", "reason": "", "item": it}, {"status": "drafted", "item": it}, None):
        assert M.check_gen_output(bad) and all(v.rule == "schema" for v in M.check_gen_output(bad))


# ---------------------------------------------------------------- §3.6 three-way value comparison
def test_three_values_agree():
    d = M.compare_values(235, 235, 235, False)
    assert (d.action, d.case, d.issues, d.uses_audit_round, d.gold_trace) == ("pass", "agree", (), False, False)
    assert M.compare_values(235, 235, 235, True).action == "pass"


def test_writer_differs_auditor_matches_program():
    d = M.compare_values(230, 235, 235, False)
    assert (d.action, d.case, d.reaudit, d.uses_audit_round) == ("fix", "writer_differs", True, True)
    assert [i.text for i in d.issues] == [P.GOLD_MISMATCH_HINT]
    assert "235" not in P.GOLD_MISMATCH_HINT and "230" not in P.GOLD_MISMATCH_HINT


def test_writer_matches_auditor_differs_is_ambiguity():
    d = M.compare_values(235, 230, 235, False)
    assert (d.action, d.case, d.reaudit, d.uses_audit_round) == ("fix", "auditor_differs", True, True)
    assert [i.text for i in d.issues] == [P.AMBIGUITY_HINT]


def test_writer_and_auditor_agree_against_the_program():
    d = M.compare_values(230, 230, 235, False)
    assert (d.action, d.case, d.uses_audit_round, d.gold_trace, d.issues) == ("dispute", "program_differs", False,
                                                                             True, ())


def test_all_three_differ():
    d = M.compare_values(230, 231, 235, False)
    assert (d.action, d.case, d.reaudit, d.uses_audit_round) == ("fix", "all_differ", True, True)
    assert [i.text for i in d.issues] == [P.GOLD_MISMATCH_HINT, P.AMBIGUITY_HINT]


@pytest.mark.parametrize("w, a", [(230, 235), (235, 230), (230, 231)])
def test_a_spent_audit_round_ends_the_attempt_on_a_mismatch_that_needs_a_fix(w, a):
    d = M.compare_values(w, a, 235, True)
    assert d.action == "end_attempt" and d.issues == () and not d.uses_audit_round
    assert not d.gold_trace and not d.closes_slot


def test_row_three_is_a_dispute_that_closes_the_slot_whatever_the_round():
    for spent in (False, True):
        d = M.compare_values(230, 230, 235, spent)
        assert (d.action, d.case, d.gold_trace, d.closes_slot, d.uses_audit_round) == (
            "dispute", "program_differs", True, True, False)
    others = ((235, 235), (230, 235), (235, 230), (230, 231))
    assert not any(M.compare_values(w, a, 235, s).closes_slot for w, a in others for s in (False, True))


def test_row_three_after_a_major_finding():
    first = M.after_audit(_audit("major", value=230), 230, 235, False)
    assert (first.action, first.gold_trace, first.closes_slot) == ("fix", True, False)
    again = M.after_audit(_audit("major", value=230), 230, 235, True)
    assert (again.action, again.case, again.gold_trace, again.closes_slot) == ("dispute", "program_differs", True, True)
    assert M.after_audit(_audit("major", value=235), 230, 235, True).action == "end_attempt"
    assert M.after_audit(_audit(value=230), 230, 235, True).action == "dispute"


def test_missing_and_boolean_values_never_count_as_equal():
    assert M.compare_values(235, None, 235, False).case == "auditor_differs"
    assert M.compare_values(230, None, 235, False).case == "all_differ"
    assert M.compare_values(None, None, 235, False).case == "all_differ"
    assert M.compare_values(True, 1, 1, False).case == "writer_differs"
    with pytest.raises(ValueError):
        M.compare_values(1, 1, "1", False)


def _audit(*sev: str, value: int | None = 235) -> dict:
    return {"id": "Q01", "value": value, "reading": "read both people as named", "checked": "read both lines",
            "findings": [{"severity": s, "issue": f"{s} issue", "suggested_fix": f"{s} fix"} for s in sev]}


def test_severity_of_findings():
    assert M.severity_of([]) == "ok"
    assert M.severity_of(_audit("minor")["findings"]) == "minor"
    assert M.severity_of(_audit("minor", "critical", "major")["findings"]) == "critical"


def test_after_audit_major_takes_the_audit_round_with_merged_issues():
    d = M.after_audit(_audit("major"), 230, 235, False)
    assert (d.action, d.severity, d.case, d.uses_audit_round, d.reaudit) == ("fix", "major", "writer_differs", True,
                                                                            True)
    texts = [i.text for i in d.issues]
    assert "major issue" in texts[0] and "major fix" in texts[0] and P.GOLD_MISMATCH_HINT in texts
    assert M.after_audit(_audit("critical"), 235, 235, True).action == "end_attempt"
    e = M.after_audit(_audit("major", value=230), 230, 235, False)
    assert e.action == "fix" and e.gold_trace


def _numbered_audit(value: int) -> dict:
    return {**_audit(value=value), "findings": [
        {"severity": "major", "issue": "gen.5.3 plus gen.5.6-gen.5.7 give 235 (二百三十五歲), not what the wording says",
         "suggested_fix": "ask for the age, 235 years, in one reading"}]}


@pytest.mark.parametrize("writer, case", [(230, "writer_differs"), (231, "all_differ")])
def test_forwarded_findings_lose_their_numbers_when_the_writer_value_differs(writer, case):
    d = M.after_audit(_numbered_audit(235 if case == "writer_differs" else 232), writer, 235, False)
    text = " ".join(i.text for i in d.issues)
    assert d.case == case and "235" not in text and "二百三十五" not in text and "232" not in text
    assert "gen.5.3" in text and "gen.5.6-gen.5.7" in text and P.GOLD_MISMATCH_HINT in text


def test_forwarded_findings_keep_their_numbers_otherwise():
    for writer, value in ((235, 235), (235, 230), (230, 230)):
        d = M.after_audit(_numbered_audit(value), writer, 235, False)
        assert any("235" in i.text for i in d.issues), (writer, value)


def test_redact_numbers_keeps_verse_keys():
    got = M.redact_numbers("gen.11.10-gen.11.12 and gen.5.3 give 235, ２３５, 二百三十五歲, 一年 and 百多歲")
    assert got == "gen.11.10-gen.11.12 and gen.5.3 give #, #, #歲, #年 and #多歲"


def test_after_audit_minor_goes_to_the_value_comparison():
    assert M.after_audit(_audit("minor"), 235, 235, False).action == "pass"
    assert M.after_audit(_audit(), 235, 235, False).severity == "ok"
    d = M.after_audit(_audit("minor", value=230), 235, 235, False)
    assert (d.action, d.case, d.severity) == ("fix", "auditor_differs", "minor")


def test_check_audit_output():
    assert M.check_audit(_audit("minor"), "Q01") == []
    for loose in ("Q01 ", "Ｑ０１"):
        assert M.check_audit({**_audit(), "id": loose}, "Q01") == []
    for bad in ({**_audit(), "id": "Q02"}, {**_audit(), "value": True}, {**_audit(), "findings": "none"},
                {**_audit(), "findings": [{"severity": "ok", "issue": "", "suggested_fix": ""}]},
                {k: v for k, v in _audit().items() if k != "reading"}, None):
        assert M.check_audit(bad, "Q01"), bad


def test_audit_issues_are_agent_text():
    issues = M.audit_issues(_audit("major", "minor")["findings"])
    assert len(issues) == 2 and all(any(s == "agent" for s, _ in i.parts) for i in issues)


# ---------------------------------------------------------------- store
@pytest.mark.skipif(not BOOKS.is_file(), reason="text layer not mounted")
def test_other_books_cover_every_book_of_the_text_layer_but_genesis():
    names = [json.loads(ln)["name"] for ln in BOOKS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(names) == 66 and names[0] == "創世記"
    assert set(names[1:]) <= set(M.OTHER_BOOKS) and "創世記" not in M.OTHER_BOOKS


def _canonical(spec: "P.SlotSpec") -> str:
    y = spec.marker if spec.marker_end == "Y" else spec.y
    x = spec.marker if spec.marker_end == "X" else spec.x
    return (f"依照創世記的記載，{y}出生的那一年，{x}是幾歲？" if spec.qtype == "age_at_birth"
            else f"依照創世記的記載，{x}去世那一年，{y}是幾歲？")


def _real_item(spec: "P.SlotSpec", question: str) -> dict:
    return {**draft(pool_row("F1", "柯梅", "茵德"), question, qid=spec.qid), "slot": spec.slot_id,
            "qtype": spec.qtype, "X": spec.x, "Y": spec.y, "marker": spec.marker}


def _real_specs(names: "P.Names") -> list["P.SlotSpec"]:
    pool = GC.read_json(GC.POOL)["pool"]
    assert len(pool) == 58
    return [P.slot_spec(row, names, f"Q{k + 1:02d}") for k, row in enumerate(pool)]


@needs_store
def test_canonical_questions_on_every_pool_slot_raise_no_error():
    names = real_names()
    bad = []
    for spec in _real_specs(names):
        found = M.errors_of(M.check_draft(_real_item(spec, _canonical(spec)), spec, names))
        found += M.errors_of(M.syntax_violations(_canonical(spec), spec, names))
        if found:
            bad.append((spec.sid, sorted({v.rule for v in found})))
    assert bad == []


def _plain(specs: list["P.SlotSpec"], *avoid: str) -> "P.SlotSpec":
    return next(s for s in specs if s.marker is None and not {s.x, s.y} & set(avoid))


@needs_store
def test_pin_a_name_inside_a_longer_name_with_the_real_chain():
    """prereg §3.4 pin 瑪土撒拉/撒拉: each long chain name's last two characters, added as a person, never count
    inside it (names are read from the store; nothing real is written here)."""
    real = real_names()
    longs = [p.name for p in real.chain if len(p.name) >= 4]
    names = P.Names.from_doc(names_doc(chain=[{"id": p.id, "name": p.name, "chapter": p.chapter} for p in real.chain],
                                       extra_persons=sorted(set(real.extra_persons) | {n[-2:] for n in longs}),
                                       lexicon_blockers=list(real.lexicon_blockers)))
    specs = _real_specs(names)
    as_end = [s for s in specs if {s.x, s.y} & set(longs)]
    assert longs and as_end
    for spec in as_end:
        assert M.errors_of(M.check_draft(_real_item(spec, _canonical(spec)), spec, names)) == [], spec.sid
    for n in longs:
        spec = _plain(specs, n)
        assert M.extra_names(f"依創世記，{n}以外，{spec.y}出生時{spec.x}幾歲？", spec, names) == [n]


@needs_store
def test_pin_contains_with_the_real_one_character_names():
    names = real_names()
    ones = [n for n in names.extra_persons if len(n) == 1]
    assert "包含"[1] in ones                                    # the prereg's pin word holds a real name
    spec = _plain(_real_specs(names))
    for q in (f"依創世記的記載，包含在內來算，{spec.y}出生時{spec.x}幾歲？", f"依創世記，包含{spec.y}出生的那一年，{spec.x}幾歲？"):
        assert M.errors_of(M.check_draft(_real_item(spec, q), spec, names)) == []
    for c in ones:
        assert M.errors_of(M.check_draft(_real_item(spec, f"依創世記（{c}{spec.y}出生那年），{spec.x}幾歲？"), spec,
                                         names)) == [], len(c)
        assert M.extra_names(f"依創世記，{spec.x}、{c}、{spec.y}之中，{spec.y}出生時{spec.x}幾歲？", spec, names) == [c]


@needs_store
def test_real_blockers_never_swallow_a_cue_word():
    names = real_names()
    specs, hits = _real_specs(names), 0
    for b in names.lexicon_blockers:
        for p in names.chain:
            tail = b[len(p.name):]
            if not (b.startswith(p.name) and tail):
                continue
            for w in M.trigger_words()["RULE7_WORDS"]:
                if w.startswith(tail) and len(w) > len(tail):
                    spec = _plain(specs, p.name)
                    assert p.name in M.extra_names(f"依創世記，{p.name}{w}之前，{spec.y}出生時{spec.x}幾歲？", spec, names)
                    hits += 1
    assert hits >= 1


@needs_store
def test_real_one_character_chain_names_count_before_event_words():
    names = real_names()
    specs = _real_specs(names)
    ones = [p.name for p in names.chain if len(p.name) == 1]
    assert ones
    for c in ones:
        spec = _plain(specs, c)
        for lead in ("過世那年之前", "出生以後", "在世時", "的年紀之外", "離世之前", "去世之前"):
            assert M.extra_names(f"依創世記，{c}{lead}，{spec.y}出生時{spec.x}幾歲？", spec, names) == [c], lead
