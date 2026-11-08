"""The PDF-only kinship rules: what each reads from a verse's text and name tokens.

Verse texts are the PDF's own (RCUV). The first group is the fix of 2026-11-02: a name after 娶 or
的妻子 may be the wife's relative (the prototype's SPOUSE_OF stood at 0.864 for this reason)."""

from __future__ import annotations

import pytest

from kin_fixture import make_corpus
from ragdata.kg.kin_extract import extract
from ragdata.kg.kin_tokens import corpus


def _facts(*verses):
    return {(r.rel, r.head, r.tail) for r in extract(make_corpus(*verses))}


def _rows(*verses):
    return {(r.rel, r.head, r.tail, r.role, r.pattern) for r in extract(make_corpus(*verses))}


@pytest.mark.parametrize("unit, text, names, wrong", [
    ("gen.38.12", "過了許久，猶大的妻子書亞的女兒死了。", ("猶大", "書亞"), ("猶大", "書亞")),
    ("1ch.4.19", "荷第雅的妻是拿含的妹子，她所生的兒子是", ("荷第雅", "拿含"), ("荷第雅", "拿含")),
    ("exo.6.25", "亞倫的兒子以利亞撒娶了普鐵的一個女兒為妻，她給他生了非尼哈。",
     ("亞倫", "以利亞撒", "普鐵", "非尼哈"), ("以利亞撒", "普鐵")),
    ("neh.6.18", "他的兒子約哈難娶了比利迦兒子米書蘭的女兒為妻。", ("約哈難", "比利迦", "米書蘭"),
     ("約哈難", "比利迦")),
])
def test_a_relative_of_the_wife_is_not_the_spouse(unit, text, names, wrong):
    assert ("SPOUSE_OF", *wrong) not in _facts((unit, text, names))


@pytest.mark.parametrize("unit, text, names, wife", [
    ("exo.6.23", "亞倫娶了亞米拿達的女兒，拿順的妹妹，以利沙巴為妻，", ("亞倫", "亞米拿達", "拿順", "以利沙巴"), "以利沙巴"),
    ("2ch.11.18", "羅波安娶大衛兒子耶利摩的女兒瑪哈拉為妻，", ("羅波安", "大衛", "耶利摩", "瑪哈拉"), "瑪哈拉"),
])
def test_the_chain_of_relatives_after_marry_leads_to_the_wife(unit, text, names, wife):
    spouses = {f for f in _facts((unit, text, names)) if f[0] == "SPOUSE_OF"}
    assert spouses == {("SPOUSE_OF", names[0], wife)}


@pytest.mark.parametrize("unit, text, names", [
    ("gen.20.18", "因耶和華為亞伯拉罕的妻子撒拉的緣故，", ("亞伯拉罕", "撒拉")),
    ("gen.46.19", "雅各之妻拉結的兒子是約瑟和便雅憫。", ("雅各", "拉結", "約瑟", "便雅憫")),
    ("rut.2.1", "拿俄米的丈夫以利米勒的親族中，", ("拿俄米", "以利米勒")),
    ("gen.36.18", "以掃的妻子阿何利巴瑪的子孫中，", ("以掃", "阿何利巴瑪")),
])
def test_a_wife_followed_by_other_possessives_is_still_the_spouse(unit, text, names):
    assert ("SPOUSE_OF", names[0], names[1]) in _facts((unit, text, names))


@pytest.mark.parametrize("text, names, expected", [
    ("亞伯拉罕生以撒；", ("亞伯拉罕", "以撒"), ("PARENT_OF", "亞伯拉罕", "以撒", "P", "begot")),
    ("波阿斯從路得氏生俄備得；", ("波阿斯", "路得", "俄備得"), ("PARENT_OF", "路得", "俄備得", "M", "from_mother")),
    ("亞比孩給他生了亞辦和摩利。", ("亞比孩", "亞辦", "摩利"), ("PARENT_OF", "亞比孩", "摩利", "M", "gave_birth_to_him")),
    ("夏甲給亞伯蘭生了以實瑪利。", ("夏甲", "亞伯蘭", "以實瑪利"), ("PARENT_OF", "亞伯蘭", "以實瑪利", "F", "gave_birth_to_X")),
    ("含的兒子是古實、麥西、弗、迦南。", ("含", "古實", "麥西", "弗", "迦南"), ("PARENT_OF", "含", "迦南", "P", "child_noun")),
    ("利百加是彼土利的女兒。", ("利百加", "彼土利"), ("PARENT_OF", "彼土利", "利百加", "P", "is_child_of")),
    ("耶穌是從馬利亞生的。", ("耶穌", "馬利亞"), ("PARENT_OF", "馬利亞", "耶穌", "M", "born_from")),
    ("所羅門的母親拔示巴", ("所羅門", "拔示巴"), ("PARENT_OF", "拔示巴", "所羅門", "M", "parent_noun")),
    ("將女兒拉結給雅各為妻。", ("拉結", "雅各"), ("SPOUSE_OF", "雅各", "拉結", "-", "give_as_wife")),
    ("亞哈的兄弟約蘭", ("亞哈", "約蘭"), ("SIBLING_OF", "亞哈", "約蘭", "-", "sibling_noun")),
    ("西庇太的兒子雅各", ("西庇太", "雅各"), ("PARENT_OF", "西庇太", "雅各", "P", "child_noun")),
    ("烏列的女兒米該亞", ("烏列", "米該亞"), ("PARENT_OF", "烏列", "米該亞", "P", "child_noun")),
    ("這俄備得是耶西的父，", ("俄備得", "耶西"), ("PARENT_OF", "俄備得", "耶西", "F", "n5_isparent")),
    ("底波拉，是拉比多的妻，", ("底波拉", "拉比多"), ("SPOUSE_OF", "底波拉", "拉比多", "-", "n7_isspouse")),
    ("掃羅的孫子、約拿單的兒子米非波設", ("掃羅", "約拿單", "米非波設"), ("PARENT_OF", "掃羅", "約拿單", "P", "n8_grand")),
    ("亞們登基的時候年二十二歲。他母親名叫米舒利密", ("亞們", "米舒利密"), ("PARENT_OF", "米舒利密", "亞們", "M", "n10_regmother")),
])
def test_a_single_verse_rule(text, names, expected):
    assert expected in _rows(("gen.1.1", text, names))


@pytest.mark.parametrize("text, names, expected", [
    ("雅各之妻拉結的兒子是約瑟和便雅憫。", ("雅各", "拉結", "約瑟", "便雅憫"),
     ("PARENT_OF", "雅各", "便雅憫", "F", "n3_wife_bore")),
    ("迦勒的妾以法生哈蘭、摩撒、迦謝；", ("迦勒", "以法", "哈蘭", "摩撒", "迦謝"),
     ("PARENT_OF", "以法", "迦謝", "M", "n3_wife_bore")),
    ("亞倫的姊姊，女先知米利暗，手裏拿着鼓；", ("亞倫", "米利暗"), ("SIBLING_OF", "亞倫", "米利暗", "-", "n3_sibcomma")),
    ("大衛的兒子押沙龍有一個美貌的妹子，名叫她瑪。", ("大衛", "押沙龍", "她瑪"), ("SIBLING_OF", "押沙龍", "她瑪", "-", "n3_sibnamed")),
    ("以掃不是雅各的哥哥嗎？", ("以掃", "雅各"), ("SIBLING_OF", "以掃", "雅各", "-", "n3_issib")),
    ("耶和華對摩西說：「我使你在法老面前代替上帝，你的哥哥亞倫是替你說話的。", ("摩西", "法老", "亞倫"),
     ("SIBLING_OF", "摩西", "亞倫", "-", "n3_address")),
    ("耶和華向摩西發怒說：「不是有你的哥哥利未人亞倫嗎？", ("摩西", "利未", "亞倫"),
     ("SIBLING_OF", "摩西", "亞倫", "-", "n3_address")),
    ("亞倫的兒子以利亞撒娶了普鐵的一個女兒為妻，她給他生了非尼哈。", ("亞倫", "以利亞撒", "普鐵", "非尼哈"),
     ("PARENT_OF", "以利亞撒", "非尼哈", "F", "plus_P8")),
    ("約瑟在埃及地生了瑪拿西和以法蓮，", ("約瑟", "埃及", "瑪拿西", "以法蓮"), ("PARENT_OF", "約瑟", "以法蓮", "F", "plus_P9")),
])
def test_the_rules_the_golden_list_found_missing(text, names, expected):
    assert expected in _rows(("gen.1.1", text, names))


def test_a_comma_after_a_sibling_is_not_an_apposition_when_a_new_possessive_follows():
    facts = _facts(("1sa.14.3", "亞希突是以迦博的哥哥，非尼哈的兒子，以利的孫子。", ("亞希突", "以迦博", "非尼哈", "以利")))
    assert ("SIBLING_OF", "亞希突", "以迦博") in facts
    assert ("SIBLING_OF", "以迦博", "非尼哈") not in facts


def test_addressing_someone_about_a_place_is_not_a_sibling():
    facts = _facts(("gen.37.13", "以色列對約瑟說：「你哥哥們不是在示劍放羊嗎？", ("以色列", "約瑟", "示劍")))
    assert not {f for f in facts if f[0] == "SIBLING_OF"}


def test_a_list_that_runs_into_a_people_is_not_children():
    facts = _facts(("1ki.12.23", "「你去告訴所羅門的兒子猶大王羅波安和猶大、便雅憫全家，並其餘的民說：",
                    ("所羅門", "猶大", "羅波安", "猶大", "便雅憫")))
    assert ("PARENT_OF", "所羅門", "猶大") not in facts and ("PARENT_OF", "所羅門", "羅波安") in facts
    facts = _facts(("2ch.24.26", "背叛他的是亞捫婦人示米押的兒子撒拔和摩押婦人示米利的兒子約薩拔。",
                    ("亞捫", "示米押", "撒拔", "摩押", "示米利", "約薩拔")))
    assert ("PARENT_OF", "示米押", "摩押") not in facts


def test_a_list_that_ends_on_a_name_often_written_as_a_people_is_children():
    """The prototype's filter dropped these: 猶大 and 以色列 are mostly written as peoples."""
    assert ("PARENT_OF", "以撒", "以色列") in _facts(
        ("1ch.1.34", "亞伯拉罕生以撒；以撒的兒子是以掃和以色列。", ("亞伯拉罕", "以撒", "以撒", "以掃", "以色列")))
    assert ("PARENT_OF", "以色列", "猶大") in _facts(
        ("1ch.2.1", "以色列的兒子是呂便、西緬、利未、猶大、以薩迦、西布倫、", ("以色列", "呂便", "西緬", "利未", "猶大", "以薩迦", "西布倫")))


def test_a_name_followed_by_a_place_word_makes_no_pattern_fact():
    facts = _facts(("num.1.7", "亞米拿達的兒子－拿順地", ("亞米拿達", "拿順")))
    assert ("PARENT_OF", "亞米拿達", "拿順") not in facts


def test_an_ordinal_list_runs_on_into_the_next_verse():
    rows = _rows(("1ch.3.1", "大衛的長子是暗嫩，次子但以理，", ("大衛", "暗嫩", "但以理")),
                 ("1ch.3.2", "三子押沙龍。", ("押沙龍",)))
    assert ("PARENT_OF", "大衛", "但以理", "P", "n2_ord") in rows
    assert ("PARENT_OF", "大衛", "押沙龍", "P", "n2_ord_xv") in rows


def test_a_titled_list_reads_its_ordinals_from_the_next_verses():
    rows = _rows(("1ch.3.1", "大衛在希伯崙所生的兒子記在下面：", ("大衛", "希伯崙")),
                 ("1ch.3.2", "長子暗嫩，", ("暗嫩",)), ("1ch.3.3", "次子但以理。", ("但以理",)))
    assert ("PARENT_OF", "希伯崙", "暗嫩", "F", "n2_head") in rows or ("PARENT_OF", "大衛", "暗嫩", "F", "n2_head") in rows


def test_a_child_named_in_the_next_verse_goes_to_the_one_who_bore():
    rows = _rows(("gen.30.23", "拉結懷孕生了一個兒子，", ("拉結",)), ("gen.30.24", "給他起名叫約瑟。", ("約瑟",)))
    assert ("PARENT_OF", "拉結", "約瑟", "P", "n4_xv") in rows


def test_a_summary_reads_its_list_back_across_verses_and_records_where_it_was_said():
    rows = extract(make_corpus(("1ch.2.1", "呂便、西緬、", ("呂便", "西緬")), ("1ch.2.2", "這都是以色列的兒子。", ("以色列",))))
    assert {(r.head, r.tail, r.pattern, r.unit, r.tail_unit) for r in rows} == {
        ("以色列", "呂便", "n1_summary", "1ch.2.2", "1ch.2.1"),
        ("以色列", "西緬", "n1_summary", "1ch.2.2", "1ch.2.1")}


def test_a_summary_over_people_with_another_father_names_descendants_not_children():
    facts = _facts(("1ch.1.1", "亞倫的兒子是拿答、亞比戶。這都是利未的兒子。", ("亞倫", "拿答", "亞比戶", "利未")))
    assert ("PARENT_OF", "利未", "拿答") not in facts and ("PARENT_OF", "亞倫", "拿答") in facts


def test_a_pronoun_in_one_noun_phrase_is_not_resolved():
    assert not _facts(("gen.4.1", "該隱和他兄弟亞伯", ("該隱", "亞伯")))


def test_jesus_comes_from_the_divine_rule_and_a_merge_group_is_one_token():
    units = [{"unit_key": "mat.1.16", "book_id": "mat", "chapter": 1, "text": "耶穌是從馬利亞生的。在鹽海"}]
    spans = [{"container_id": "mat.1.16", "region": "body", "merge_group": None, "start": 4, "end": 7,
              "surface": "馬利亞", "norm_key": "馬利亞"},
             {"container_id": "mat.1.16", "region": "body", "merge_group": "mg:x#1", "start": 12, "end": 13,
              "surface": "鹽", "norm_key": "鹽"},
             {"container_id": "mat.1.16", "region": "body", "merge_group": "mg:x#1", "start": 13, "end": 14,
              "surface": "海", "norm_key": "海"},
             {"container_id": "fn:mat.1.16#1", "region": "footnote", "merge_group": None, "start": 0, "end": 3,
              "surface": "馬利亞", "norm_key": "馬利亞"}]
    extra = [{"container_id": "mat.1.16", "region": "body", "source": "divine_rule", "start": 0, "end": 2, "surface": "耶穌"},
             {"container_id": "mat.1.16", "region": "body", "source": "divine_rule", "start": 9, "end": 11, "surface": "上帝"}]
    c = corpus(units, spans, extra)
    assert [t.norm_key for t in c.verse("mat.1.16").tokens] == ["耶穌", "馬利亞", "鹽海"]
    assert {(r.head, r.tail) for r in extract(c)} == {("馬利亞", "耶穌")}


def test_every_row_points_at_the_characters_it_was_read_from():
    text = "亞伯拉罕生以撒；"
    (row,) = extract(make_corpus(("gen.1.1", text, ("亞伯拉罕", "以撒"))))
    assert text[row.head_start:row.head_end] == "亞伯拉罕" and text[row.tail_start:row.tail_end] == "以撒"
    assert (row.unit, row.head_unit, row.tail_unit, row.family) == ("gen.1.1", "gen.1.1", "gen.1.1", "k0")


def test_a_row_is_kept_once_per_token_pair_and_pattern():
    rows = extract(make_corpus(("gen.20.18", "亞伯拉罕的妻子撒拉的緣故", ("亞伯拉罕", "撒拉"))))
    assert sorted(r.pattern for r in rows) == ["n3_sp", "spouse_noun"]


def test_a_son_that_only_describes_the_next_name_is_not_the_son():
    """至於瑪拿西的長子基列之父瑪吉: 瑪吉 is the firstborn, 基列 his son (Numbers 26:29)."""
    facts = _rows(("jos.17.1", "至於瑪拿西的長子基列之父瑪吉，", ("瑪拿西", "基列", "瑪吉")))
    assert ("PARENT_OF", "瑪拿西", "瑪吉", "P", "child_noun") in facts
    assert ("PARENT_OF", "瑪吉", "基列", "F", "n3_fa") in facts
    assert not [f for f in facts if f[1:3] == ("瑪拿西", "基列")]


@pytest.mark.parametrize("unit, text, names, mother", [
    ("2sa.3.4", "四子亞多尼雅是哈及所生的；", ("亞多尼雅", "哈及"), "哈及"),
    ("1ch.3.1", "長子暗嫩是耶斯列人亞希暖生的。", ("暗嫩", "耶斯列", "亞希暖"), "亞希暖"),
])
def test_a_son_of_a_numbered_list_is_born_of_his_mother(unit, text, names, mother):
    assert ("PARENT_OF", mother, names[0], "M", "plus_P5") in _rows((unit, text, names))


@pytest.mark.parametrize("unit, text, names, father", [
    ("jdg.11.1", "耶弗他是基列所生的。", ("耶弗他", "基列"), "基列"),
    ("gen.24.15", "利百加是彼土利所生的；", ("利百加", "彼土利"), "彼土利"),
])
def test_born_of_someone_outside_a_numbered_list_says_nothing_of_the_sex(unit, text, names, father):
    assert ("PARENT_OF", father, names[0], "P", "plus_P5") in _rows((unit, text, names))
