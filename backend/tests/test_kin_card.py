"""The kinship card: which questions take it, who its ends are, how it walks and what it says."""

import asyncio

import pytest

import graph_fakes as G
from ragcommon import routing
from ragcommon.routing import MASK
from ragcommon.tests.lexicon_doc import document, name
from router_fakes import BOOK_TERMS
from utils.kg import kin_card, kin_cues

ABE, ISAAC, JACOB, SARAH, ESAU = "e000001", "e000002", "e000003", "e000004", "e000005"
JOSEPH1, JOSEPH2 = "e000006", "e000007"
NAMES = ["亞伯拉罕", "以撒", "雅各", "撒拉", "以掃", "約瑟", "伯特利", "撒母耳", "猶大", "以色列", "希西家", "亞哈", "便雅憫",
         "掃羅", "利未", "摩西", "亞倫", "哥亞", "約翰", "所羅門", "大衛", "羅波安", "彼得", "馬利亞", "瑪拿西"]
LEXICON = routing.parse_lexicon(document(
    names=[name(n, f"nm:5a{i:010d}", "Person") for i, n in enumerate(NAMES)],
    books=[*BOOK_TERMS]))


def _person(pid, label, mentions=10, units=("gen.1.1",), parents=(), conflict=False, surface=None,
            children=0, spouses=0, siblings=0):
    return {"surface": surface or label, "id": pid, "label": label, "mentions": mentions,
            "kin_conflict": conflict, "units": list(units), "parents": [list(p) for p in parents],
            "children": children, "spouses": spouses, "siblings": siblings}


def _edge(src, kind, dst, role="P", *units):
    return [src, kind, dst, role, list(units or ("gen.21.3",))]


LABELS = {ABE: "亞伯拉罕", ISAAC: "以撒", JACOB: "雅各", SARAH: "撒拉", ESAU: "以掃", JOSEPH1: "約瑟", JOSEPH2: "約瑟"}


def _path(*edges, start=None):
    """A path as the templates answer it: its nodes from ``start`` along its edges."""
    nodes = [start or edges[0][0]]
    for edge in edges:
        nodes.append(edge[2] if edge[0] == nodes[-1] else edge[0])
    return {"nodes": [[n, LABELS[n]] for n in nodes], "edges": list(edges), "hops": len(edges)}


UP = {"abe": _edge(ABE, "PARENT_OF", ISAAC, "P", "gen.21.3", "1ch.1.34"),
      "isaac": _edge(ISAAC, "PARENT_OF", JACOB, "P", "gen.25.26"),
      "sarah": _edge(SARAH, "PARENT_OF", ISAAC, "M", "gen.21.3")}


def _graph(monkeypatch, **answers) -> G.FakeGraph:
    return G.use(monkeypatch, G.FakeGraph(answers))


def _build(question, pool=(), lexicon=LEXICON):
    return asyncio.run(kin_card.build(question, list(pool), lexicon, "b1"))


def _masked(question):
    return kin_cues.masked(question, LEXICON.match(question), LEXICON)


def _cue(question):
    return kin_cues.read(_masked(question))


# --- the cues -----------------------------------------------------------------------------------

@pytest.mark.parametrize("word", [
    "父", "母", "兒子", "女兒", "孫", "祖", "妻", "丈夫", "岳", "婆", "媳", "兄", "弟", "哥", "姊", "姐", "妹", "叔",
    "伯", "舅", "姑", "姨", "侄", "甥", "親屬", "親戚", "家譜", "後代", "祖先", "子孫", "血緣", "同名"])
def test_every_kinship_word_is_a_cue(word):
    assert kin_cues.read(f"{MASK}的{word}") is not None


def test_no_kinship_word_is_no_cue():
    assert _cue("亞伯拉罕去過哪些地方") is None


@pytest.mark.parametrize("question", ["亞伯拉罕去了哪裡", "撒母耳做了什麼", "伯特利在哪裡", "約伯記講什麼",
                                      "撒母耳記上的作者"])
def test_a_cue_inside_a_name_or_a_book_name_is_no_cue(question):
    assert _cue(question) is None


@pytest.mark.parametrize("question", ["亞伯拉罕曾經去過哪裡", "雅各不曾說過什麼", "以撒未曾離開"])
def test_zeng_is_a_cue_only_in_a_generation_word(question):
    assert _cue(question) is None


def test_a_disciple_is_no_brother():
    assert _cue("以撒的弟子有誰") is None


@pytest.mark.parametrize("question, up, down", [
    ("雅各的父親是誰", 1, 0), ("雅各的母親是誰", 1, 0), ("雅各的祖父是誰", 2, 0), ("雅各的祖先有誰", 3, 0),
    ("雅各的曾祖父是誰", 3, 0), ("雅各的兒子是誰", 0, 1), ("雅各的女兒是誰", 0, 1), ("雅各的孫子是誰", 0, 2),
    ("雅各的後代有誰", 0, 3), ("雅各的子孫有誰", 0, 3), ("雅各的曾孫是誰", 0, 3), ("雅各的父親和兒子", 1, 1),
])
def test_the_cue_gives_the_direction_and_the_reach(question, up, down):
    cue = _cue(question)
    assert (cue.up, cue.down, cue.near) == (up, down, False)


@pytest.mark.parametrize("question, types", [
    ("雅各的哥哥是誰", ("SIBLING_OF",)), ("雅各的弟弟是誰", ("SIBLING_OF",)), ("雅各的姊姊是誰", ("SIBLING_OF",)),
    ("雅各的妹妹是誰", ("SIBLING_OF",)), ("雅各的妻子是誰", ("SPOUSE_OF",)), ("撒拉的丈夫是誰", ("SPOUSE_OF",)),
    ("雅各的妻子和兄弟", ("SIBLING_OF", "SPOUSE_OF")),
])
def test_siblings_and_spouses_are_one_hop_sideways(question, types):
    assert _cue(question).side == types


@pytest.mark.parametrize("question", ["雅各的舅舅是誰", "雅各的岳父是誰", "雅各的親戚有誰", "雅各的家譜", "雅各的血緣",
                                      "以撒的媳婦是誰", "雅各的叔叔", "雅各的侄子"])
def test_every_other_cue_walks_near_in_any_direction(question):
    cue = _cue(question)
    assert cue.near and (cue.up, cue.down, cue.side) == (0, 0, ())


def test_same_name_cues():
    assert _cue("聖經裡有幾個叫約瑟的人").same_name
    assert _cue("約瑟有同名的人嗎").same_name
    assert _cue("聖經裡有幾位名叫約瑟的人").same_name
    assert not _cue("約瑟的父親").same_name


def test_relation_is_a_cue_only_for_two_ends():
    cue = _cue("雅各和以掃是什麼關係")
    assert cue.relation and not cue.near
    assert kin_cues.takes(cue, ends=2) and not kin_cues.takes(cue, ends=1)


@pytest.mark.parametrize("question", [
    "天父怎樣看顧大衛", "亞伯拉罕被稱為信心之父是什麼意思", "耶穌的比喻裡，浪子的父親做了什麼", "亞伯拉罕的比喻裡有兒子嗎",
    "摩西的休書條例論休妻", "以色列人的祖先是誰", "神的兒子是誰", "大衛所以為的父親", "以撒是亞伯拉罕所愛的兒子"])
def test_a_kinship_word_not_written_right_after_a_name_is_no_cue(question):
    assert _cue(question) is None


@pytest.mark.parametrize("question", ["亞伯拉罕的子孫會多如天上的星，是什麼意思", "雅各的兒子們都在田裡放羊的時候發生了什麼",
                                      "撒拉的兒子在摩西的生平中扮演了什麼角色"])
def test_a_question_going_on_from_the_word_without_asking_is_no_cue(question):
    assert _cue(question) is None


@pytest.mark.parametrize("question, up, down", [
    ("雅各有幾個兒子", 0, 1), ("雅各的十二個兒子是誰", 0, 1), ("大衛王的父親是誰", 1, 0), ("雅各之父是誰", 1, 0),
    ("雅各和以掃的母親是誰", 1, 0), ("撒拉有孩子嗎", 0, 1), ("雅各的長子是誰", 0, 1), ("雅各的兒女是誰", 0, 1),
])
def test_what_stands_between_the_name_and_the_word_may_be_a_title_or_a_count(question, up, down):
    cue = _cue(question)
    assert (cue.up, cue.down) == (up, down)


def test_a_kinship_word_that_only_names_the_next_person_asks_nothing():
    assert _cue("亞伯拉罕的兒子以撒是怎樣的人") is None
    assert _cue("亞伯拉罕的兒子以撒的妻子是誰").side == ("SPOUSE_OF",)
    assert _cue("亞伯拉罕的兒子以撒的妻子是誰").down == 0


def test_a_name_followed_by_is_still_asks():
    assert _cue("以撒的父親是亞伯拉罕嗎").up == 1


@pytest.mark.parametrize("question, kind", [("雅各的岳父是誰", "spouse"), ("雅各的婆婆是誰", "spouse"),
                                            ("雅各的媳婦是誰", "child"), ("雅各的女婿是誰", "child"), ("雅各的舅舅是誰", "")])
def test_an_in_law_says_which_edge_comes_first(question, kind):
    assert _cue(question).near and _cue(question).in_law == kind


def test_relation_wants_two_names_written_together_or_a_plural_pronoun():
    assert _cue("雅各與以掃的關係如何") is not None
    assert _cue("他們是什麼關係") is not None
    assert _cue("雅各在這裡的關係如何") is None


def test_relation_wants_them_in_its_own_clause():
    assert _cue("雅各和以掃都來了，這件事和立約有什麼關係") is None
    assert _cue("跟著他們回去的那人，和立約有什麼關係") is None


@pytest.mark.parametrize("question", [
    "雅各作王期間有一位王登基。他的父親是誰？",
    "以撒的僕人回去了。他有多少個兒子？",
    "他的父親是誰",
])
def test_a_pronoun_asks_nothing_of_the_names_written(question):
    """In a question that describes the one it asks about, 他 is that person and no name it writes."""
    assert _cue(question) is None


@pytest.mark.parametrize("question", [
    "他和當時那位雅各王同名。這人是誰的兒子？",
    "這人的祖父和摩西所殺的人同名。兩人是同一人嗎",
    "有一位和這孩子同名的雅各王。他曾和誰交戰",
])
def test_same_name_wants_the_name_right_beside_it(question):
    """Here the name shared is not written: listing the people of the names written answers nothing."""
    cue = _cue(question)
    assert cue is None or not cue.same_name


def test_a_kinship_word_right_after_a_written_name_still_asks():
    assert _cue("雅各的曾孫是哪一位王").down == 3
    assert _cue("雅各的妻子當中，有哪幾位是寡婦") is not None


# --- the ends -----------------------------------------------------------------------------------

def test_the_question_literal_names_are_looked_up_in_the_persons_surfaces(monkeypatch):
    graph = _graph(monkeypatch)

    _build("雅各的父親是誰")

    assert graph.calls[0][0] == "kin_persons" and graph.calls[0][1]["surfaces"] == ["雅各"]


def test_no_name_at_all_sends_no_cypher(monkeypatch):
    graph = _graph(monkeypatch)

    outcome = _build("他們是什麼關係")

    assert graph.calls == [] and outcome.text is None and outcome.skip_reason == kin_card.NO_PERSON


def test_a_name_that_is_no_person_gives_no_card(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[])

    outcome = _build("雅各的父親是誰")

    assert outcome.text is None and outcome.skip_reason == kin_card.NO_PERSON and graph.names() == ["kin_persons"]


def _pool_with(*units):
    return [{"id": "ps:x", "unit_refs": [{"unit_key": u} for u in units]}]


@pytest.mark.parametrize("question, looked_up", [
    ("猶大王希西家的父親是誰", ["希西家"]), ("以色列王亞哈的父親是誰", ["亞哈"]), ("便雅憫人掃羅的父親是誰", ["掃羅"]),
    ("利未人摩西的父親是誰", ["摩西"]), ("以色列人的摩西的父親是誰", ["摩西"]), ("大衛王的父親是誰", ["大衛"]),
    ("猶大支派的掃羅的父親是誰", ["掃羅"]), ("亞哈的父親是誰", ["亞哈"])])
def test_a_nation_or_a_tribe_beside_a_person_is_no_person(monkeypatch, question, looked_up):
    graph = _graph(monkeypatch)

    _build(question)

    assert graph.calls[0][1]["surfaces"] == looked_up


def test_a_kinship_word_does_not_lose_the_name_after_it_to_the_lexicon(monkeypatch):
    """摩西的哥哥亞倫 reads 哥亞, a place, longest first."""
    graph = _graph(monkeypatch)

    _build("摩西的哥哥亞倫的兒子有哪些")

    assert graph.calls[0][1]["surfaces"] == ["摩西", "亞倫"]


@pytest.mark.parametrize("question", ["閃的兒子是誰", "含的妻子是誰", "嫩的兒子是誰"])
def test_a_one_character_name_before_a_kinship_word_is_looked_up_though_the_lexicon_never_reads_it(monkeypatch, question):
    graph = _graph(monkeypatch)

    _build(question)

    assert graph.calls[0][1]["surfaces"] == [question[0]]


@pytest.mark.parametrize("question", ["他的兒子是誰", "誰的兒子是誰", "神的兒子是誰", "你的父親是誰"])
def test_a_pronoun_is_no_one_character_name(monkeypatch, question):
    graph = _graph(monkeypatch)

    assert _build(question).skip_reason in (kin_card.NO_CUE, kin_card.NO_PERSON) and graph.calls == []


ZEBEDEE, ZECHARIAH = "e000020", "e000021"
JOHN_PARENTS = {ZEBEDEE: ("e000030", "西庇太", "P", ["mrk.10.35"]), ZECHARIAH: ("e000031", "撒迦利亞", "P", ["luk.3.2"])}


def _johns(zebedee_units=("mrk.10.35",), zechariah_units=("luk.3.2",)):
    return [_person(ZEBEDEE, "約翰", 40, zebedee_units, [JOHN_PARENTS[ZEBEDEE]]),
            _person(ZECHARIAH, "約翰", 10, zechariah_units, [JOHN_PARENTS[ZECHARIAH]])]


def test_a_qualifier_says_which_person_of_the_name_is_meant(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=_johns(zebedee_units=[f"mat.{i}.1" for i in range(1, 9)]),
                   kin_up=[_path(_edge(ABE, "PARENT_OF", ISAAC, "P", "luk.3.2"))])

    _build("施洗約翰的父親是誰", pool=_pool_with(*[f"mat.{i}.1" for i in range(1, 9)]))

    assert graph.calls[1][0] == "kin_up" and graph.calls[1][1]["x"] == ZECHARIAH


def test_a_description_with_no_known_person_gives_no_card(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[*_johns()])

    outcome = _build("亞利馬太的約翰的父親是誰")

    assert outcome.skip_reason == kin_card.NO_PERSON and graph.names() == ["kin_persons"]


def test_people_with_different_parents_the_pool_cannot_tell_apart_are_all_listed_with_no_evidence(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=_johns())

    outcome = _build("約翰的父親是誰", pool=_pool_with("mrk.10.35"))

    assert "kin_up" not in graph.names() and "unit_passages" not in graph.names()
    assert "約翰（1）：西庇太 的子女（馬可福音 10:35）" in outcome.text
    assert "約翰（2）：撒迦利亞 的子女（路加福音 3:2）" in outcome.text
    assert outcome.passages == () and outcome.persons == (ZEBEDEE, ZECHARIAH)


def test_a_pool_that_clearly_holds_one_of_them_settles_who_is_meant(monkeypatch):
    units = [f"mrk.{i}.1" for i in range(1, 5)]
    graph = _graph(monkeypatch, kin_persons=_johns(zebedee_units=units), kin_up=[_path(UP["isaac"])])

    _build("約翰的父親是誰", pool=_pool_with(*units, "luk.3.2"))

    assert graph.calls[1][0] == "kin_up" and graph.calls[1][1]["x"] == ZEBEDEE


def test_a_person_with_the_edge_asked_for_goes_before_one_without(monkeypatch):
    """亞哈 of the kings has 暗利 for a father; the other 亞哈 has none."""
    graph = _graph(monkeypatch, kin_persons=[
        _person(ISAAC, "亞哈", 100, ("1ki.16.1",)),
        _person(JACOB, "亞哈", 5, ("1ki.16.29",), [(ABE, "暗利", "P", ["1ki.16.29"])])],
        kin_up=[_path(UP["isaac"])])

    _build("亞哈的父親是誰")

    assert graph.calls[1][1]["x"] == JACOB


def test_a_person_with_the_children_asked_for_goes_before_one_without(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(ISAAC, "約瑟", 100), _person(JACOB, "約瑟", 5, children=2)],
                   kin_down=[_path(UP["isaac"])])

    _build("約瑟的兒子是誰")

    assert graph.calls[1][1]["x"] == JACOB


def test_two_names_go_to_the_pair_with_the_shortest_path(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100), _person(JOSEPH2, "約瑟", 5),
        _person(ISAAC, "馬利亞", 90), _person(JACOB, "馬利亞", 3)],
        kin_pair_hops=[{"x": JOSEPH2, "y": JACOB, "hops": 1}, {"x": JOSEPH1, "y": ISAAC, "hops": 4}],
        kin_path=[_path(_edge(JACOB, "SPOUSE_OF", JOSEPH2, "-", "mat.1.16"), start=JOSEPH2)])

    _build("約瑟和馬利亞是什麼關係")

    assert graph.names()[:3] == ["kin_persons", "kin_pair_hops", "kin_path"]
    assert len(graph.calls[1][1]["pairs"]) == 4
    assert (graph.calls[2][1]["x"], graph.calls[2][1]["y"]) == (JOSEPH2, JACOB)


def test_a_tie_between_pairs_goes_to_the_pool(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100, ("gen.1.1",)), _person(JOSEPH2, "約瑟", 5, ("mat.1.16",)), _person(ISAAC, "馬利亞", 3, ("mat.1.16",))],
        kin_pair_hops=[{"x": JOSEPH1, "y": ISAAC, "hops": 2}, {"x": JOSEPH2, "y": ISAAC, "hops": 2}], kin_path=[])

    _build("約瑟和馬利亞是什麼關係", pool=_pool_with("mat.1.16"))

    assert graph.calls[2][1]["x"] == JOSEPH2


def test_the_same_person_is_no_pair(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[
        _person(ABE, "亞伯拉罕", surface="亞伯拉罕"), _person(SARAH, "亞伯拉罕", surface="亞伯拉罕"),
        _person(ABE, "亞伯拉罕", surface="以撒"), _person(ISAAC, "以撒")],
        kin_pair_hops=[], kin_path=[])

    _build("亞伯拉罕和以撒是什麼關係")

    assert [pair for pair in graph.calls[1][1]["pairs"] if pair[0] == pair[1]] == []


def test_no_path_between_any_pair_falls_back_to_each_name_alone(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟", 100), _person(JOSEPH2, "約瑟", 5), _person(ISAAC, "以撒")],
                   kin_pair_hops=[], kin_path=[])

    _build("約瑟和以撒是什麼關係")

    assert graph.calls[2][0] == "kin_path" and graph.calls[2][1]["x"] == JOSEPH1


def test_a_shared_name_goes_to_the_person_most_mentioned_in_the_pool(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100, ("gen.30.24", "gen.37.3")), _person(JOSEPH2, "約瑟", 5, ("mat.1.16", "mat.1.18", "mat.1.19"))],
        kin_up=[_path(_edge(JACOB, "PARENT_OF", JOSEPH2, "P", "mat.1.16"))])

    _build("約瑟的父親是誰", pool=_pool_with("mat.1.16", "mat.1.18"))

    assert graph.calls[1][0] == "kin_up" and graph.calls[1][1]["x"] == JOSEPH2


def test_a_tie_in_the_pool_goes_to_the_person_mentioned_most(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JOSEPH2, "約瑟", 5), _person(JOSEPH1, "約瑟", 100)])

    _build("約瑟的父親是誰")

    assert graph.calls[1][1]["x"] == JOSEPH1


def test_who_is_meant_names_one_parent_with_its_verse(monkeypatch):
    """Two parents joined by 、 read as one couple, which a Person joined wrongly may not be."""
    _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100, parents=[(JACOB, "雅各", "P", ["gen.46.19"]), (SARAH, "拉結", "M", ["gen.30.25"])]),
        _person(JOSEPH2, "約瑟", 5)], kin_down=[_path(_edge(JOSEPH1, "PARENT_OF", ISAAC, "P", "gen.41.51"))])

    text = _build("約瑟的兒子是誰").text

    assert "這裡用 雅各 的子女那一筆（創世記 46:19）" in text and "、" not in text.splitlines()[1]


def test_the_card_says_the_name_is_shared_and_who_is_meant(monkeypatch):
    _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100, parents=[(JACOB, "雅各", "P", ["gen.30.25"])]), _person(JOSEPH2, "約瑟", 5)],
        kin_down=[_path(_edge(JOSEPH1, "PARENT_OF", ISAAC, "P", "gen.41.51"))])

    text = _build("約瑟的兒子是誰").text

    assert "「約瑟」在親屬資料中有 2 筆（可能是同名的不同人，也可能是同一人分列）" in text
    assert "這裡用 雅各 的子女那一筆" in text


def test_someone_with_no_parents_is_pointed_at_by_where_he_first_appears(monkeypatch):
    _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟", 100, ("mat.1.16",)), _person(JOSEPH2, "約瑟", 5)],
           kin_down=[_path(_edge(JOSEPH1, "PARENT_OF", ISAAC, "P", "gen.41.51"))])

    assert "這裡用 馬太福音 1:16 提到的那一筆" in _build("約瑟的兒子是誰").text


def test_a_person_the_build_flags_as_conflicted_is_said_to_be(monkeypatch):
    _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟", conflict=True)],
           kin_up=[_path(UP["isaac"])])

    assert "可能混入同名者" in _build("約瑟的父親是誰").text


# --- the walks ----------------------------------------------------------------------------------

def _two(monkeypatch, **answers):
    return _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各"), _person(ABE, "亞伯拉罕")], **answers)


def test_two_persons_ask_for_the_path_between_them(monkeypatch):
    graph = _two(monkeypatch, kin_path=[_path(UP["isaac"], UP["abe"], start=JACOB)])

    outcome = _build("雅各和亞伯拉罕是什麼關係")

    assert graph.names()[1] == "kin_path" and graph.calls[1][1]["x"] == JACOB and graph.calls[1][1]["y"] == ABE
    assert outcome.hops == 2
    assert "共 2 跳" in outcome.text


def test_at_most_three_pairs_are_asked(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(p, n) for p, n in (
        (ABE, "亞伯拉罕"), (ISAAC, "以撒"), (JACOB, "雅各"), (SARAH, "撒拉"))], kin_near=[])

    _build("亞伯拉罕、以撒、雅各和撒拉是什麼關係")

    assert graph.names().count("kin_path") == 3


def test_no_path_falls_back_to_walking_each_person_alone(monkeypatch):
    graph = _two(monkeypatch, kin_path=[], kin_up=[_path(UP["isaac"])])

    outcome = _build("雅各和亞伯拉罕的父親是誰")

    assert graph.names()[1] == "kin_path"
    assert [params["x"] for name, params in graph.calls if name == "kin_up"] == [JACOB, ABE]
    assert outcome.text is not None and outcome.skip_reason is None


def test_a_question_asking_only_for_the_relation_has_no_card_without_a_path(monkeypatch):
    graph = _two(monkeypatch, kin_path=[])

    outcome = _build("雅各和亞伯拉罕是什麼關係")

    assert graph.names() == ["kin_persons", "kin_path"]
    assert outcome.text is None and outcome.skip_reason == kin_card.NO_EDGE


def test_a_relation_with_one_person_found_has_no_walk(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")])

    outcome = _build("雅各和以掃是什麼關係")

    assert graph.names() == ["kin_persons"] and outcome.text is None


def test_one_person_walks_in_the_cues_direction_and_reach(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")],
                   kin_up=[_path(UP["isaac"], UP["abe"])])

    _build("雅各的祖父是誰")

    assert graph.names()[1] == "kin_up" and graph.calls[1][1]["depth"] == 2


def test_sideways_is_one_template_with_the_cues_types(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")])

    _build("雅各的妻子是誰")

    assert graph.calls[1][0] == "kin_side" and graph.calls[1][1]["types"] == ["SPOUSE_OF"]


def test_any_other_cue_walks_near(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")])

    _build("雅各的舅舅是誰")

    assert graph.calls[1][0] == "kin_near"


def test_a_wifes_parent_is_read_only_through_his_wife(monkeypatch):
    """彼得的岳母: his brother is one hop away and says nothing of her."""
    brother = _path(_edge(JACOB, "SIBLING_OF", ESAU, "-", "gen.25.26"))
    wife = _path(_edge(JACOB, "SPOUSE_OF", SARAH, "-", "gen.29.28"), _edge(ISAAC, "PARENT_OF", SARAH, "P", "gen.29.10"))
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")], kin_near=[brother, wife])

    text = _build("雅各的岳父是誰").text

    assert "以掃" not in text and "雅各 與 撒拉 是配偶" in text


def test_a_wifes_parent_with_no_wife_written_gives_no_card(monkeypatch):
    brother = _path(_edge(JACOB, "SIBLING_OF", ESAU, "-", "gen.25.26"))
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")], kin_near=[brother])

    assert _build("雅各的岳母是誰").skip_reason == kin_card.NO_EDGE


def test_a_sons_wife_is_his_child_then_the_childs_spouse(monkeypatch):
    other = _path(_edge(JACOB, "SPOUSE_OF", SARAH, "-", "gen.29.28"))
    theirs = _path(_edge(JACOB, "PARENT_OF", JOSEPH1, "P", "gen.46.19"), _edge(JOSEPH1, "SPOUSE_OF", SARAH, "-", "gen.41.45"))
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")], kin_near=[other, theirs])

    text = _build("雅各的媳婦是誰").text

    assert "約瑟 與 撒拉 是配偶" in text and "雅各 與 撒拉 是配偶" not in text


def test_a_question_naming_two_people_walks_from_the_one_it_asks_about(monkeypatch):
    """亞伯拉罕的兒子以撒的妻子: the path between them, then 以撒's wife, and nothing of 亞伯拉罕's."""
    wife = _path(_edge(ISAAC, "SPOUSE_OF", SARAH, "-", "gen.25.20"))
    graph = _graph(monkeypatch, kin_persons=[_person(ABE, "亞伯拉罕"), _person(ISAAC, "以撒")],
                   kin_path=[_path(UP["abe"])], kin_side=[wife])

    outcome = _build("亞伯拉罕的兒子以撒的妻子是誰")

    assert [params["x"] for name, params in graph.calls if name == "kin_side"] == [ISAAC]
    lines = outcome.text.splitlines()
    assert lines[1].startswith("路徑：") and lines[2] == "以撒 與 撒拉 是配偶（創世記 25:20）"
    assert "亞伯拉罕 是 以撒 的父母之一（創世記 21:3）" in lines


def test_two_names_joined_by_and_are_both_walked_as_the_word_after_them_says(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各"), _person(ESAU, "以掃")],
                   kin_path=[_path(_edge(ESAU, "SIBLING_OF", JACOB, "-", "gen.25.26"))], kin_up=[_path(UP["isaac"])])

    _build("雅各和以掃的母親是誰")

    assert [params["x"] for name, params in graph.calls if name == "kin_up"] == [JACOB, ESAU]


def test_a_name_with_nothing_asked_of_it_is_not_walked(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟"), _person(ISAAC, "瑪拿西")],
                   kin_path=[_path(_edge(JOSEPH1, "PARENT_OF", ISAAC, "P", "gen.46.20"))], kin_down=[])

    _build("約瑟的兒子瑪拿西的兒子是誰")

    assert [params["x"] for name, params in graph.calls if name == "kin_down"] == [ISAAC]


def test_same_name_lists_everyone_and_walks_no_edge_template(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[
        _person(JOSEPH1, "約瑟", 100, ("gen.30.24",), [(JACOB, "雅各", "P", ["gen.30.25"])]),
        _person(JOSEPH2, "約瑟", 5, ("mat.1.16",))])

    outcome = _build("聖經裡有幾個叫約瑟的人")

    assert graph.names() == ["kin_persons", "unit_passages"]
    assert "「約瑟」在親屬資料中共 2 筆（只收有親屬記載的人，同一人可能分列）" in outcome.text
    assert "約瑟（1）：雅各 的子女（創世記 30:25）" in outcome.text
    assert "約瑟（2）：未整理到父母（馬太福音 1:16）" in outcome.text


def test_two_parents_of_one_person_are_two_rows_each_with_its_verse(monkeypatch):
    _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟", 100, ("gen.30.24",), [
        (JACOB, "雅各", "P", ["gen.46.19"]), (SARAH, "拉結", "M", ["gen.30.25"])])])

    outcome = _build("聖經裡有幾個叫約瑟的人")

    assert "約瑟（1）：雅各 的子女（創世記 46:19）" in outcome.text
    assert "約瑟（1）：拉結 的子女（創世記 30:25）" in outcome.text
    assert "、" not in "".join(line for line in outcome.text.splitlines() if line.startswith("約瑟（"))


def test_the_trace_of_a_same_name_card_holds_only_the_rows_it_shows(monkeypatch):
    many = [_person(f"e1{i:05d}", "約瑟", 100 - i, ("gen.30.24",), [(f"e2{i:05d}", f"父{i}", "P", ["gen.46.19"])])
            for i in range(20)]
    _graph(monkeypatch, kin_persons=many)

    outcome = _build("聖經裡有幾個叫約瑟的人")

    shown = sum(1 for line in outcome.text.splitlines() if line.startswith("約瑟（"))
    assert shown < 20 and len(outcome.edges) == shown
    assert set(outcome.nodes) == {n for e in outcome.edges for n in (e[0], e[2])}


def test_same_name_with_no_parent_edge_at_all_gives_no_card(monkeypatch):
    _graph(monkeypatch, kin_persons=[_person(JOSEPH1, "約瑟", units=("gen.30.24",))])

    outcome = _build("約瑟有同名的人嗎")

    assert outcome.text is None and outcome.skip_reason == kin_card.NO_EDGE


# --- what it says -------------------------------------------------------------------------------

def _card(monkeypatch, question="雅各的祖父是誰", **answers):
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各", surface=LEXICON.match(question)[0].surface)], **answers)
    return _build(question)


def test_a_card_opens_by_saying_it_comes_from_the_text_and_the_text_wins(monkeypatch):
    text = _card(monkeypatch, kin_up=[_path(UP["isaac"])]).text
    assert text.splitlines()[0] == kin_card.HEADER and "以經文為準" in kin_card.HEADER


def test_each_row_is_one_relation_with_its_verse(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[_path(UP["abe"], UP["isaac"])])
    lines = outcome.text.splitlines()
    assert "亞伯拉罕 是 以撒 的父母之一（創世記 21:3）" in lines and "以撒 是 雅各 的父母之一（創世記 25:26）" in lines
    assert outcome.lines == 2


def test_only_a_written_mother_is_called_a_mother_and_no_parent_a_father(monkeypatch):
    """Role P is a parent the text does not settle the sex of: 拉結 -> 約瑟 is P."""
    outcome = _card(monkeypatch, "以撒的母親是誰", kin_up=[_path(UP["sarah"]), _path(UP["abe"])])
    assert "撒拉 是 以撒 的母親（創世記 21:3）" in outcome.text
    assert "亞伯拉罕 是 以撒 的父母之一（創世記 21:3）" in outcome.text and "父親" not in outcome.text


def test_spouses_and_siblings_read_both_ways(monkeypatch):
    outcome = _card(monkeypatch, "雅各的妻子和兄弟", kin_side=[
        _path(_edge(JACOB, "SPOUSE_OF", SARAH, "-", "gen.29.28")), _path(_edge(ESAU, "SIBLING_OF", JACOB, "-", "gen.25.26"))])
    assert "雅各 與 撒拉 是配偶（創世記 29:28）" in outcome.text
    assert "以掃 與 雅各 是兄弟姊妹（創世記 25:26）" in outcome.text


def test_a_merged_unit_is_cited_as_written(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[_path(_edge(ISAAC, "PARENT_OF", JACOB, "P", "1ch.16.12-13"))])
    assert "（歷代志上 16:12-13）" in outcome.text


def test_a_path_gets_its_own_line_with_every_step_and_the_hops(monkeypatch):
    _two(monkeypatch, kin_path=[_path(UP["isaac"], UP["abe"], start=JACOB)])

    text = _build("雅各和亞伯拉罕是什麼關係").text

    assert "路徑：雅各 是 以撒 的子女，以撒 是 亞伯拉罕 的子女（共 2 跳）" in text


def test_a_path_through_a_spouse_reads_along_its_way(monkeypatch):
    spouse = _edge(ABE, "SPOUSE_OF", SARAH, "-", "gen.11.29")
    _graph(monkeypatch, kin_persons=[_person(SARAH, "撒拉"), _person(ISAAC, "以撒")],
           kin_path=[_path(spouse, UP["abe"], start=SARAH)])

    assert "路徑：亞伯拉罕 與 撒拉 是配偶，亞伯拉罕 是 以撒 的父母之一（共 2 跳）" in _build("撒拉和以撒是什麼關係").text


def test_at_most_twelve_rows_and_what_was_left_out_is_said(monkeypatch):
    many = [_path(_edge(JACOB, "PARENT_OF", ISAAC, "P", f"gen.1.{i}")) for i in range(1, 2)]
    many += [{"nodes": [[JACOB, "雅各"], [f"e1{i:05d}", f"子{i}"]],
              "edges": [[JACOB, "PARENT_OF", f"e1{i:05d}", "P", [f"gen.2.{i}"]]], "hops": 1} for i in range(1, 30)]

    outcome = _card(monkeypatch, "雅各的兒子是誰", kin_down=many)

    rows = outcome.text.splitlines()[1:]
    assert len(rows) == 12 == outcome.lines and rows[-1] == "另有 19 條關係未列"
    assert len(outcome.edges) == 11


def test_at_most_700_characters(monkeypatch):
    many = [{"nodes": [[JACOB, "雅各"], [f"e1{i:05d}", "亞" * 90 + str(i)]],
             "edges": [[JACOB, "PARENT_OF", f"e1{i:05d}", "P", [f"gen.2.{i}"]]], "hops": 1} for i in range(1, 30)]

    outcome = _card(monkeypatch, "雅各的兒子是誰", kin_down=many)

    assert len(outcome.text) <= 700 and outcome.text.splitlines()[-1].startswith("另有")


def test_notes_and_paths_count_among_the_twelve_rows(monkeypatch):
    many = [_path(UP["isaac"], UP["abe"], start=JACOB)] * 9
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各", conflict=True), _person(ABE, "亞伯拉罕", conflict=True)],
           kin_path=many)

    outcome = _build("雅各和亞伯拉罕是什麼關係")

    rows = outcome.text.splitlines()[1:]
    assert len(rows) == 12 == outcome.lines


def test_a_card_says_it_may_be_incomplete():
    assert "可能不完整" in kin_card.HEADER


def test_rows_saying_the_same_of_two_people_of_one_name_are_one_row(monkeypatch):
    """雅各 of Genesis and of 1 Chronicles are two Persons: one row for 雅各 是 約瑟 的父母之一."""
    first = {"nodes": [[JACOB, "雅各"], [JOSEPH1, "約瑟"]], "edges": [_edge(JACOB, "PARENT_OF", JOSEPH1, "P", "gen.46.19")], "hops": 1}
    second = {"nodes": [[JACOB, "雅各"], [JOSEPH2, "約瑟"]], "edges": [_edge(JACOB, "PARENT_OF", JOSEPH2, "P", "1ch.7.29")], "hops": 1}

    outcome = _card(monkeypatch, "雅各的兒子是誰", kin_down=[first, second])

    assert outcome.text.count("雅各 是 約瑟 的父母之一") == 1
    assert outcome.edges == ((JACOB, "PARENT_OF", JOSEPH1, "gen.46.19"),)


@pytest.mark.parametrize("question, noted", [("雅各的姊姊是誰", True), ("雅各的哥哥是誰", True), ("雅各的兄弟有誰", False)])
def test_a_card_says_it_cannot_tell_a_sister_from_a_brother(monkeypatch, question, noted):
    outcome = _card(monkeypatch, question, kin_side=[_path(_edge(ESAU, "SIBLING_OF", JACOB, "-", "gen.25.26"))])
    assert ("不分" in outcome.text) is noted


def test_the_trace_holds_the_edges_of_a_path_line_though_its_rows_were_cut(monkeypatch):
    long_path = _path(UP["isaac"], UP["abe"], start=JACOB)
    _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各", conflict=True), _person(ABE, "亞伯拉罕", conflict=True)],
           kin_path=[long_path] * 11)

    outcome = _build("雅各和亞伯拉罕是什麼關係")

    assert (ISAAC, "PARENT_OF", JACOB, "gen.25.26") in outcome.edges and (ABE, "PARENT_OF", ISAAC, "gen.21.3") in outcome.edges
    assert set(outcome.nodes) == {ISAAC, JACOB, ABE} and "gen.25.26" in outcome.evidence


def test_no_edge_means_no_card(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[])
    assert outcome.text is None and outcome.skip_reason == kin_card.NO_EDGE and outcome.evidence == ()


def test_an_edge_repeated_by_several_paths_is_one_row(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[_path(UP["isaac"], UP["abe"]), _path(UP["isaac"])])
    assert outcome.text.count("以撒 是 雅各 的父母之一") == 1 and outcome.lines == 2


def test_the_evidence_is_the_verses_of_the_rows_and_their_passages_are_asked_for(monkeypatch):
    graph = _graph(monkeypatch, kin_persons=[_person(JACOB, "雅各")], kin_up=[_path(UP["isaac"], UP["abe"])],
                   unit_passages=[{"unit": "gen.25.26", "passage": "ps:gen.25.19"},
                                  {"unit": "gen.21.3", "passage": "ps:gen.21.1"},
                                  {"unit": "gen.21.3", "passage": "ps:gen.21.3b"}])

    outcome = _build("雅各的祖父是誰")

    assert outcome.evidence == ("gen.25.26", "gen.21.3")
    assert graph.calls[-1] == ("unit_passages", {"b": "b1", "units": ["gen.25.26", "gen.21.3"]})
    assert outcome.passages == ("ps:gen.25.19", "ps:gen.21.1", "ps:gen.21.3b")


def test_the_trace_fields_carry_nodes_labels_and_edges_with_verses(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[_path(UP["isaac"], UP["abe"])])

    assert outcome.persons == (JACOB,) and outcome.seeds == ("雅各",)
    assert outcome.nodes == (ISAAC, JACOB, ABE) and outcome.names == ("以撒", "雅各", "亞伯拉罕")
    assert outcome.edges == ((ISAAC, "PARENT_OF", JACOB, "gen.25.26"), (ABE, "PARENT_OF", ISAAC, "gen.21.3"))
    assert outcome.hops == 2 and outcome.n_cypher == 3


def test_hops_are_those_of_the_paths_walked(monkeypatch):
    assert _card(monkeypatch, kin_up=[_path(UP["isaac"], UP["abe"]), _path(UP["isaac"])]).hops == 2


def test_the_same_question_gives_the_same_card(monkeypatch):
    a = _card(monkeypatch, kin_up=[_path(UP["isaac"], UP["abe"])])
    b = _card(monkeypatch, kin_up=[_path(UP["isaac"], UP["abe"])])
    assert a.text == b.text


def test_to_and_from_stats_round_trip(monkeypatch):
    outcome = _card(monkeypatch, kin_up=[_path(UP["isaac"])])

    back = kin_card.from_stats({"kin_card": outcome.to_stats()})

    assert back.text == outcome.text and back.evidence == outcome.evidence and back.persons == outcome.persons


def test_a_stats_without_a_card_is_no_card():
    assert kin_card.from_stats({}) is None
    assert kin_card.from_stats({"kin_card": None}) is None
    assert kin_card.from_stats({"kin_card": kin_card.skipped("timeout").to_stats()}) is None
