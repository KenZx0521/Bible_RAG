"""The real graph, over the served layers: relations written down from the Bible, positive and
negative, looked up edge by edge, and what G-GRAPH reads of the whole.

A person is found by a name and a verse: the Person whose surfaces hold the name and whose
``mention_units`` hold the verse. So a row also says which of the people of that name is meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ragdata import paths
from ragdata.kg import graph_build, person_aliases
from ragdata.kg.graph_schema import KIN_TYPES, PDF_RULE, meta_doc
from ragdata.gates.graph import check_graph

LAYERS = Path("/mnt/ollama-data/bible_rag_store/layers")
TEXT = LAYERS / "text/text@247eafe44b02"
STRUCT = LAYERS / "struct/struct@d8d432b4df15"
KG0 = LAYERS / "kg0/kg0@14e68c8344b1"
EVENTS = LAYERS / "events/events@01401ecad19a"
pytestmark = pytest.mark.skipif(not all(p.is_dir() for p in (TEXT, STRUCT, KG0, EVENTS)),
                                reason="the served layers are not in the store")

# (type, a, a's verse, b, b's verse): the graph must hold the edge a->b (undirected types: either way)
RELATIONS = [
    ("PARENT_OF", "亞伯拉罕", "gen.21.3", "以撒", "gen.21.3"),
    ("PARENT_OF", "以撒", "gen.25.26", "雅各", "gen.46.19"),
    ("PARENT_OF", "雅各", "gen.46.19", "約瑟", "gen.46.19"),
    ("PARENT_OF", "路得", "mat.1.5", "俄備得", "mat.1.5"),
    ("PARENT_OF", "波阿斯", "rut.4.21", "俄備得", "rut.4.21"),
    ("PARENT_OF", "俄備得", "rut.4.22", "耶西", "rut.4.22"),
    ("PARENT_OF", "耶西", "rut.4.22", "大衛", "rut.4.22"),
    ("PARENT_OF", "大衛", "1ch.3.5", "所羅門", "1ch.3.5"),
    ("PARENT_OF", "所羅門", "1ki.11.43", "羅波安", "1ki.11.43"),
    ("PARENT_OF", "掃羅", "1sa.14.1", "約拿單", "1sa.14.1"),
    ("PARENT_OF", "約拿單", "2sa.4.4", "米非波設", "2sa.4.4"),
    ("PARENT_OF", "羅波安", "mat.1.7", "亞比雅", "mat.1.7"),
    ("PARENT_OF", "亞當", "gen.5.3", "塞特", "gen.5.3"),
    ("PARENT_OF", "挪亞", "gen.5.32", "閃", "gen.5.32"),
    ("PARENT_OF", "他拉", "gen.11.27", "亞伯蘭", "gen.11.27"),
    ("PARENT_OF", "亞伯蘭", "gen.16.15", "以實瑪利", "gen.16.15"),
    ("PARENT_OF", "夏甲", "gen.16.15", "以實瑪利", "gen.16.15"),
    ("PARENT_OF", "拉結", "gen.35.24", "約瑟", "gen.35.24"),
    ("PARENT_OF", "利亞", "gen.35.23", "呂便", "gen.35.23"),
    ("PARENT_OF", "約瑟", "gen.46.20", "以法蓮", "gen.46.20"),
    ("PARENT_OF", "暗蘭", "exo.6.20", "摩西", "exo.6.20"),
    ("PARENT_OF", "暗蘭", "exo.6.20", "亞倫", "exo.6.20"),
    ("PARENT_OF", "約基別", "exo.6.20", "摩西", "exo.6.20"),
    ("PARENT_OF", "亞倫", "exo.6.23", "以利亞撒", "exo.6.23"),
    ("PARENT_OF", "以利亞撒", "exo.6.25", "非尼哈", "exo.6.25"),
    ("PARENT_OF", "馬利亞", "mat.1.16", "耶穌", "mat.1.16"),
    ("PARENT_OF", "西庇太", "mat.4.21", "雅各", "mat.4.21"),
    ("PARENT_OF", "大衛", "2sa.3.2", "押沙龍", "2sa.3.3"),
    ("PARENT_OF", "瑪迦", "2sa.3.3", "押沙龍", "2sa.3.3"),
    ("PARENT_OF", "拔示巴", "1ki.1.11", "所羅門", "1ki.1.11"),
    ("PARENT_OF", "哈拿", "1sa.1.20", "撒母耳", "1sa.1.20"),
    ("PARENT_OF", "亞哈", "1ki.22.49", "亞哈謝", "1ki.22.49"),
    ("PARENT_OF", "約哈斯", "2ki.13.10", "約阿施", "2ki.13.10"),
    ("PARENT_OF", "亞哈謝", "2ki.13.1", "約阿施", "2ki.13.1"),
    ("PARENT_OF", "約阿施", "2ki.14.1", "亞瑪謝", "2ki.14.1"),
    ("PARENT_OF", "約阿施", "2ki.14.23", "耶羅波安", "2ki.14.23"),
    ("PARENT_OF", "瑪拿西", "jos.17.1", "瑪吉", "jos.17.1"),
    ("PARENT_OF", "瑪吉", "jos.17.1", "基列", "jos.17.1"),
    ("SPOUSE_OF", "亞伯拉罕", "gen.20.18", "撒拉", "gen.20.18"),
    ("SPOUSE_OF", "雅各", "gen.29.28", "拉結", "gen.29.28"),
    ("SPOUSE_OF", "以撒", "gen.25.20", "利百加", "gen.25.20"),
    ("SPOUSE_OF", "波阿斯", "rut.4.13", "路得", "rut.4.13"),
    ("SPOUSE_OF", "摩西", "exo.2.21", "西坡拉", "exo.2.21"),
    ("SPOUSE_OF", "亞倫", "exo.6.23", "以利沙巴", "exo.6.23"),
    ("SPOUSE_OF", "大衛", "1sa.18.27", "米甲", "1sa.18.27"),
    ("SPOUSE_OF", "羅波安", "2ch.11.18", "瑪哈拉", "2ch.11.18"),
    ("SPOUSE_OF", "約瑟", "mat.1.16", "馬利亞", "mat.1.16"),
    ("SPOUSE_OF", "烏利亞", "2sa.11.3", "拔示巴", "2sa.11.3"),
    ("SPOUSE_OF", "暗蘭", "num.26.59", "約基別", "num.26.59"),
    ("SIBLING_OF", "亞倫", "exo.7.1", "摩西", "exo.7.1"),
    ("SIBLING_OF", "拿鶴", "gen.24.15", "亞伯拉罕", "gen.24.15"),
    ("SIBLING_OF", "以掃", "gen.27.6", "雅各", "gen.27.6"),
    ("SIBLING_OF", "該隱", "gen.4.2", "亞伯", "gen.4.2"),
    ("SIBLING_OF", "彼得", "mat.4.18", "安得烈", "jhn.1.40"),
    ("SIBLING_OF", "雅各", "mat.17.1", "約翰", "mat.17.1"),
    ("SIBLING_OF", "亞倫", "exo.15.20", "米利暗", "exo.15.20"),
    ("SIBLING_OF", "押沙龍", "2sa.13.1", "她瑪", "2sa.13.1"),
]
# (a, a's verse, b, b's verse, what they are): no kin edge of any type between them
NOT_KIN = [
    ("瑪拿西", "jos.17.1", "基列", "jos.17.1", "基列是瑪吉的兒子"),
    ("辟拉", "gen.29.29", "拉結", "gen.29.29", "使女"),
    ("悉帕", "gen.29.24", "利亞", "gen.29.24", "使女"),
    ("夏甲", "gen.16.3", "撒萊", "gen.16.3", "使女"),
    ("亞倫", "exo.6.23", "亞米拿達", "exo.6.23", "岳父"),
    ("羅波安", "2ch.11.18", "大衛", "2ch.11.18", "妻的曾祖"),
    ("以利亞撒", "exo.6.25", "普鐵", "exo.6.25", "岳父"),
    ("約哈難", "neh.6.18", "比利迦", "neh.6.18", "妻的祖父"),
    ("羅得", "gen.14.12", "亞伯蘭", "gen.14.12", "侄兒"),
    ("摩西", "exo.3.1", "葉忒羅", "exo.3.1", "岳父"),
    ("路得", "rut.1.14", "拿俄米", "rut.1.14", "婆媳"),
    ("約拿單", "1sa.18.3", "大衛", "1sa.18.3", "朋友"),
]
# the fix of 2026-11-02, by name: 猶大 and 荷第雅's in-laws have kin edges only through someone else
NO_SPOUSE_BY_NAME = [("猶大", "書亞"), ("荷第雅", "拿含"), ("亞倫", "亞米拿達"), ("羅波安", "大衛"),
                     ("以利亞撒", "普鐵"), ("約哈難", "比利迦")]
# two names at two verses are one person
SAME_PERSON = [("亞伯蘭", "gen.12.1", "亞伯拉罕", "gen.17.5"), ("撒萊", "gen.11.29", "撒拉", "gen.17.15"),
               ("雅各", "gen.32.28", "以色列", "gen.35.10"), ("西門‧彼得", "jhn.1.40", "彼得", "mat.4.18"),
               ("約西亞", "2ki.22.1", "約西亞", "1ch.3.14"), ("便雅憫", "gen.46.21", "便雅憫", "1ch.8.1"),
               ("比珥", "num.22.5", "比珥", "jos.24.9"), ("比珥", "num.22.5", "比珥", "mic.6.5"),
               ("約瑟", "gen.46.19", "約瑟", "1ch.7.29"), ("約阿施", "2ki.12.1", "約阿施", "2ki.11.2"),
               ("約阿施", "2ki.13.25", "約阿施", "2ki.14.23"), ("約蘭", "1ch.3.11", "約蘭", "2ch.22.1"),
               ("大衛", "rut.4.22", "大衛", "1ki.1.11"), ("摩西", "exo.2.21", "摩西", "1ch.23.15"),
               ("亞伯拉罕", "gen.21.3", "亞伯拉罕", "1ch.1.34"), ("耶穌", "mat.1.16", "耶穌", "jhn.1.45"),
               ("耶穌", "act.1.14", "耶穌", "jhn.1.45")]
# one name at two verses is two people
TWO_PEOPLE = [("約瑟", "mat.1.16", "約瑟", "gen.46.20"), ("雅各", "mat.1.16", "雅各", "gen.46.19"),
              ("雅各", "mat.4.21", "雅各", "gen.46.19"), ("拿鶴", "gen.11.24", "拿鶴", "gen.11.27"),
              ("猶大", "luk.3.26", "猶大", "gen.46.12"),
              # a name read as a woman's made its fathers no fathers
              ("瑪拿西", "gen.46.20", "瑪拿西", "1ch.3.13"), ("以利亞撒", "exo.6.23", "以利亞撒", "1ch.23.21"),
              ("比拉", "gen.36.32", "比拉", "gen.46.21"), ("猶大", "luk.3.30", "猶大", "luk.3.34"),
              ("謝拉", "gen.36.13", "謝拉", "gen.46.12"), ("底但", "gen.10.7", "底但", "gen.25.3"),
              ("示巴", "gen.10.7", "示巴", "gen.25.3"), ("哈諾", "gen.25.4", "哈諾", "gen.46.9"),
              ("拉法", "1ch.8.2", "拉法", "1ch.8.37"),
              # the same verse, and the kings two kingdoms share
              ("約阿施", "2ki.13.10", "約阿施", "2ki.12.1"), ("約蘭", "2ki.3.1", "約蘭", "1ch.3.11"),
              ("亞哈謝", "1ki.22.51", "亞哈謝", "2ki.8.25"),
              ("約哈斯", "2ki.13.1", "約哈斯", "2ki.23.30"),
              # no more than a name in common
              ("約翰", "mrk.10.35", "約翰", "jhn.1.42"),
              ("約翰", "mrk.10.35", "約翰", "luk.3.2"), ("雅各", "mat.4.21", "雅各", "mrk.6.3"),
              ("亞比雅", "2ch.11.22", "亞比雅", "2ch.29.1"), ("瑪迦", "2sa.3.3", "瑪迦", "1ch.2.48"),
              ("瑣轄", "gen.23.8", "瑣轄", "gen.46.10"),
              ("馬利亞", "mat.1.16", "馬利亞", "jhn.19.25"), ("約亞拿", "luk.3.27", "約亞拿", "luk.8.3"),
              ("亞大", "gen.4.19", "亞大", "gen.36.2"), ("她瑪", "gen.38.6", "她瑪", "2sa.13.1"),
              ("亞撒利雅", "1ch.6.9", "亞撒利雅", "2ch.28.12")]
# two tokens of one name that are not one person: a token the identity leaves out is fine too
NOT_ONE_PERSON = [("約翰", "mat.3.1", "約翰", "mrk.10.35"), ("約翰", "mat.14.4", "約翰", "mrk.10.35"),
                  ("比利亞", "gen.46.17", "比利亞", "1ch.7.23"), ("比利亞", "gen.46.17", "比利亞", "1ch.7.25"),
                  ("約翰", "act.12.12", "約翰", "mrk.10.35"), ("亞比米勒", "gen.20.2", "亞比米勒", "jdg.8.31"),
                  ("約瑟", "mrk.15.43", "約瑟", "mat.1.16"), ("約瑟", "act.1.23", "約瑟", "mat.1.16"),
                  ("約瑟", "act.4.36", "約瑟", "mat.1.16"), ("掃羅", "act.7.58", "掃羅", "act.13.21"),
                  ("撒迦利亞", "ezr.5.1", "撒迦利亞", "ezr.8.3"), ("撒迦利亞", "ezr.8.3", "撒迦利亞", "ezr.8.11"),
                  ("撒迦利亞", "ezr.8.11", "撒迦利亞", "ezr.8.16"), ("撒迦利亞", "ezr.8.16", "撒迦利亞", "ezr.10.26"),
                  ("西門", "mat.27.32", "西門", "mat.4.18")]
# (grandparent, a verse of theirs, grandchild, a verse of theirs): the two people review caught joined through
# one Person of the name between them have no such path
NO_GRANDCHILD = [("約瑟", "gen.46.20", "亞們", "1ch.3.14"), ("比珥", "gen.36.32", "亞大", "1ch.8.3"),
                 ("流珥", "gen.36.13", "心利", "1ch.2.6"), ("約哈斯", "2ki.13.10", "亞瑪謝", "2ki.14.1"),
                 ("西庇太", "mat.4.21", "西門", "jhn.1.42"), ("亞設", "gen.46.17", "利悉", "1ch.7.25"),
                 ("西緬", "gen.46.10", "以弗崙", "gen.23.8"), ("亞勒腓", "mat.10.3", "猶大", "act.1.13"),
                 ("耶哈利勒", "2ch.29.12", "約珥", "2ch.29.12"), ("瑪基雅", "jer.38.1", "基大利", "jer.38.1"),
                 ("亞哈", "2ki.8.25", "亞哈謝", "2ki.8.25"), ("亞哈", "2ch.22.6", "亞撒利雅", "2ch.22.6"),
                 ("拉但", "1ch.7.26", "示母利", "num.34.20"), ("掃羅", "1sa.31.2", "亞希約", "2sa.6.3"),
                 ("雅代", "1ch.2.47", "迦謝", "1ch.2.46")]
# every two-fathers or two-sexes person the rules leave: the identity refuses such a merge, so none is left
KNOWN_CONFLICTS: list[str] = []
# relations the Bible holds but no verse writes with a kinship word next to two names: not in the graph
NOT_WRITTEN = [("SPOUSE_OF", "雅各", "gen.29.23", "利亞", "gen.29.23")]    # 拉班將女兒利亞送來給雅各


@pytest.fixture(scope="module")
def graph():
    layers, snap = graph_build.load_layers(TEXT, STRUCT, KG0, EVENTS)
    nodes, edges, report = graph_build.compute(layers, person_aliases.load(paths.REGISTRIES))
    return nodes, edges, report, snap, layers


@pytest.fixture(scope="module")
def persons(graph):
    return [r for r in graph[0] if r["kind"] == "Person"]


@pytest.fixture(scope="module")
def kin(graph):
    return {(r["type"], r["src"], r["dst"]) for r in graph[1] if r["type"] in KIN_TYPES}


def _who(persons, name, verse):
    return [p["id"] for p in persons
            if name in p["props"]["surfaces"] and verse in p["props"]["mention_units"]]


def _holds(kin, edge_type, sources, targets):
    return any((edge_type, a, b) in kin or (edge_type != "PARENT_OF" and (edge_type, b, a) in kin)
               for a in sources for b in targets)


def test_the_whole_graph_passes_its_gate(graph):
    nodes, edges, _, snap, _ = graph
    result = check_graph(nodes, edges, meta_doc(nodes, edges), snap)
    assert result.passed, result.details


def test_the_size_is_the_d2_method_plus_what_the_fixes_added(graph, persons):
    edges = [r for r in graph[1] if r["type"] in KIN_TYPES]
    assert 1800 <= len(persons) <= 1900 and 1500 <= len(edges) <= 1650


def test_the_alias_registry_holds_to_the_pdf(graph):
    text = graph[4]["text"]
    verses = {r["unit_key"]: r["text"] for r in text.rows["verse_units.jsonl"]}
    notes = {r["fn_id"]: r for r in text.rows["footnotes.jsonl"]}
    assert person_aliases.check_evidence(person_aliases.load(paths.REGISTRIES), verses, notes) == []


@pytest.mark.parametrize("row", RELATIONS, ids=lambda r: f"{r[0]}-{r[1]}-{r[3]}")
def test_a_written_relation_is_in_the_graph(graph, persons, kin, row):
    edge_type, a, a_at, b, b_at = row
    verses = {r["unit_key"]: r["text"] for r in graph[4]["text"].rows["verse_units.jsonl"]}
    assert a in verses[a_at] and b in verses[b_at]
    assert _holds(kin, edge_type, _who(persons, a, a_at), _who(persons, b, b_at))


@pytest.mark.parametrize("row", NOT_KIN, ids=lambda r: f"{r[0]}-{r[2]}")
def test_people_who_are_not_kin_have_no_edge(persons, kin, row):
    a, a_at, b, b_at, _ = row
    sources, targets = _who(persons, a, a_at), _who(persons, b, b_at)
    assert not any(_holds(kin, t, sources, targets) or _holds(kin, t, targets, sources) for t in KIN_TYPES)


@pytest.mark.parametrize("a, b", NO_SPOUSE_BY_NAME)
def test_a_relative_of_the_wife_is_no_spouse_of_that_name(persons, kin, a, b):
    ids_a = [p["id"] for p in persons if a in p["props"]["surfaces"]]
    ids_b = [p["id"] for p in persons if b in p["props"]["surfaces"]]
    assert not _holds(kin, "SPOUSE_OF", ids_a, ids_b)


@pytest.mark.parametrize("a, a_at, b, b_at", SAME_PERSON)
def test_two_names_of_one_person_are_one_node(persons, a, a_at, b, b_at):
    assert set(_who(persons, a, a_at)) & set(_who(persons, b, b_at))


@pytest.mark.parametrize("a, a_at, b, b_at", TWO_PEOPLE)
def test_one_name_of_two_people_is_two_nodes(persons, a, a_at, b, b_at):
    first, second = set(_who(persons, a, a_at)), set(_who(persons, b, b_at))
    assert first and second and not first & second


@pytest.mark.parametrize("a, a_at, b, b_at", NOT_ONE_PERSON)
def test_two_tokens_of_a_name_are_not_one_person(persons, a, a_at, b, b_at):
    assert not set(_who(persons, a, a_at)) & set(_who(persons, b, b_at))


@pytest.mark.parametrize("a, a_at, c, c_at", NO_GRANDCHILD)
def test_a_person_joined_by_name_alone_makes_no_false_path(persons, kin, a, a_at, c, c_at):
    middles = {b for (t, x, b) in kin if t == "PARENT_OF" and x in _who(persons, a, a_at)}
    assert not any(("PARENT_OF", m, z) in kin for m in middles for z in _who(persons, c, c_at))


def test_the_people_flagged_conflicted_are_the_ones_expected(persons):
    assert sorted(p["props"]["label"] for p in persons if p["props"]["kin_conflict"]) == KNOWN_CONFLICTS


@pytest.mark.parametrize("name, mother_verse", [("亞多尼雅", "2sa.3.4"), ("示法提雅", "2sa.3.4")])
def test_a_son_listed_with_his_mother_has_one_father(persons, kin, name, mother_verse):
    (son,) = {p for p in _who(persons, name, mother_verse)}
    assert not next(p for p in persons if p["id"] == son)["props"]["kin_conflict"]


def test_the_cited_verse_of_an_edge_writes_both_names_when_any_of_its_verses_does(graph, persons):
    """大衛 -> 押沙龍 reads from 2 Samuel 3:2 to 3:3, but 13:1 writes them together."""
    verses = {r["unit_key"]: r["text"] for r in graph[4]["text"].rows["verse_units.jsonl"]}
    people = {p["id"]: p["props"] for p in persons}

    def both_at(row, unit):
        return all(any(s in verses[unit] for s in people[end]["surfaces"]) for end in (row["src"], row["dst"]))
    wrong = [r for r in graph[1] if r["type"] in KIN_TYPES and not both_at(r, r["props"]["evidence_units"][0])
             and any(both_at(r, u) for u in r["props"]["evidence_units"][1:])]
    assert wrong == []


@pytest.mark.parametrize("row", NOT_WRITTEN, ids=lambda r: f"{r[1]}-{r[3]}")
def test_a_relation_no_verse_writes_is_not_invented(persons, kin, row):
    edge_type, a, a_at, b, b_at = row
    assert not _holds(kin, edge_type, _who(persons, a, a_at), _who(persons, b, b_at))


def test_the_rename_of_paul_is_not_lent_to_king_saul(persons):
    """掃羅 has no kin row at act.13.9, where he is renamed: 保羅 stays out of the graph."""
    assert not [p for p in persons if "保羅" in p["props"]["surfaces"]]
    assert _who(persons, "掃羅", "1sa.14.1")


def test_tokens_written_as_a_people_are_not_the_man(persons):
    (israel,) = _who(persons, "以色列", "gen.35.10")
    jacob = next(p for p in persons if p["id"] == israel)
    assert "exo.1.7" not in jacob["props"]["mention_units"] and jacob["props"]["mentions"] < 600


def test_every_kin_edge_comes_from_the_pdf_rules(graph):
    assert {r["props"]["provenance_class"] for r in graph[1] if r["type"] in KIN_TYPES} == {PDF_RULE}


def test_no_person_is_named_by_something_kg0_does_not_know_but_jesus(graph):
    assert graph[2]["identity"]["surfaces_without_a_name"] == ["耶穌"]


def test_no_heading_name_is_left_without_a_pericope(graph):
    assert graph[2]["title_mentions"]["unplaced_heading_names"] == 0


def test_the_passages_are_in_reading_order_within_a_book(graph):
    verse_position = {r["unit_key"]: i for i, r in enumerate(graph[4]["text"].rows["verse_units.jsonl"])}
    edges = [r for r in graph[1] if r["type"] == "NEXT" and r["src_kind"] == "Passage"]
    starts = {r["passage_id"]: verse_position[r["unit_refs"][0]["unit_key"]]
              for r in graph[4]["struct"].rows["passages.jsonl"]}
    assert all(starts[r["src"]] <= starts[r["dst"]] for r in edges)
