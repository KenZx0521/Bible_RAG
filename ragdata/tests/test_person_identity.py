"""Which name tokens are one person (D2 of the PDF-only prototype, with the ancestor refusal)."""

from __future__ import annotations

from collections import Counter

import pytest

from kin_fixture import make_corpus
from ragdata.kg.kin_extract import extract
from ragdata.kg.person_aliases import Aliases, FootnotePair, Rename, check_evidence, parse
from ragdata.kg.person_graph import persons_and_edges
from ragdata.kg.person_identity import Context, Pericopes, identify
from ragdata.kg.person_signs import Kings
from ragdata.kg.registries import RegistryError

NO_ALIASES = Aliases("person_aliases@0", (), ())
NT = frozenset({"mat", "mrk", "luk", "jhn", "act"})


def _context(c, pericope_of=None, parallels=None, next_id=None, aliases=NO_ALIASES, homonyms=frozenset(),
             regnal_titles=None, regnal_sons=None, regnal_fathers=None):
    pericope_of = pericope_of or {v.unit_key: f"pc:{v.book_id}.{v.chapter}" for v in c.verses}
    size = Counter(pericope_of.values())
    return Context(c, Pericopes(pericope_of, size, next_id or {}, parallels or {}), NT, aliases,
                   Kings(homonyms, regnal_titles or {}, regnal_sons or {}, regnal_fathers or {}))


def _graph(*verses, **options):
    c = make_corpus(*verses)
    ctx = _context(c, **options)
    rows = extract(c)
    identity = identify(rows, ctx)
    return identity, *persons_and_edges(rows, identity, ctx)


def _named(people, name):
    return [p for p in people if name in p.surfaces]


def _edge_names(people, edges):
    label = {p.person_id: p.label for p in people}
    return {(e.rel, label[e.src], label[e.dst]) for e in edges}


def test_a_chain_is_one_person_at_each_name():
    _, people, edges = _graph(("gen.5.6", "塞特生以挪士，", ("塞特", "以挪士")),
                              ("gen.5.7", "以挪士生該南，", ("以挪士", "該南")))
    assert sorted(p.label for p in people) == ["以挪士", "塞特", "該南"]
    assert _edge_names(people, edges) == {("PARENT_OF", "塞特", "以挪士"), ("PARENT_OF", "以挪士", "該南")}


def test_two_fathers_of_different_names_are_two_people():
    _, people, _ = _graph(("gen.46.1", "雅各生約瑟；約瑟生瑪拿西。", ("雅各", "約瑟", "約瑟", "瑪拿西")),
                          ("1ch.25.2", "亞薩的兒子約瑟。", ("亞薩", "約瑟")))
    assert len(_named(people, "約瑟")) == 2


def test_a_footnote_alias_makes_two_fathers_agree():
    aliases = Aliases("person_aliases@0", (), (FootnotePair("亞比央", "亞比雅", "fn:1ki.14.31#1"),))
    _, people, _ = _graph(("1ki.15.8", "亞比央的兒子亞撒。", ("亞比央", "亞撒")),
                          ("1ki.15.9", "亞比雅的兒子亞撒。", ("亞比雅", "亞撒")), aliases=aliases)
    assert len(_named(people, "亞撒")) == 1


def test_a_genealogy_that_reuses_a_name_makes_no_one_their_own_ancestor():
    """1 Chronicles 6: 亞瑪利雅 begets 亞希突 twice, generations apart."""
    identity, people, edges = _graph(
        ("1ch.6.7", "亞瑪利雅生亞希突，", ("亞瑪利雅", "亞希突")),
        ("1ch.6.8", "亞希突生撒督，撒督生亞瑪利雅，", ("亞希突", "撒督", "撒督", "亞瑪利雅")),
        ("1ch.6.11", "亞瑪利雅生亞希突，", ("亞瑪利雅", "亞希突")))
    assert len(_named(people, "亞希突")) == 2
    children = {}
    for e in edges:
        children.setdefault(e.src, set()).add(e.dst)

    def descendants(node, seen):
        for child in children.get(node, ()):
            if child not in seen:
                seen.add(child)
                descendants(child, seen)
        return seen
    assert all(p.person_id not in descendants(p.person_id, set()) for p in people)


def test_a_printed_title_that_differs_keeps_two_kings_apart():
    _, people, _ = _graph(("1ki.15.1", "猶大王約蘭生亞哈謝。", ("猶大", "約蘭", "亞哈謝")),
                          ("2ki.1.17", "以色列王約蘭生米該亞。", ("以色列", "約蘭", "米該亞")))
    assert len(_named(people, "約蘭")) == 2


def test_a_relation_word_earlier_in_the_gap_does_not_make_the_next_name_a_woman():
    """雅各之妻拉結的兒子是約瑟: the gap from 雅各 to 約瑟 holds 之妻, and 約瑟 is still a man with a father."""
    identity, people, _ = _graph(("gen.46.19", "雅各之妻拉結的兒子是約瑟和便雅憫。", ("雅各", "拉結", "約瑟", "便雅憫")),
                                 ("1ch.8.1", "便雅憫生比拉。", ("便雅憫", "比拉")),
                                 ("1ch.8.37", "比尼亞生拉法。", ("比尼亞", "拉法")),
                                 ("1ch.8.2", "便雅憫生拉法。", ("便雅憫", "拉法")))
    assert "約瑟" not in identity.female and "便雅憫" not in identity.female and "拉結" in identity.female
    assert len(_named(people, "拉法")) == 2


def test_every_name_of_a_list_of_sons_is_a_man():
    """1 Chronicles 2:46-47: 迦勒的妾以法, and 雅代的兒子是利健、以法."""
    _, people, _ = _graph(("1ch.2.46", "迦勒的妾以法生哈蘭。", ("迦勒", "以法", "哈蘭")),
                          ("1ch.2.47", "雅代的兒子是利健、以法。", ("雅代", "利健", "以法")))
    assert len(_named(people, "以法")) == 2


def test_a_woman_and_a_man_of_one_name_are_two_people():
    verses = (("2ch.11.22", "羅波安的兒子亞比雅作太子。", ("羅波安", "亞比雅")),
              ("2ch.29.1", "他母親名叫亞比雅，", ("亞比雅",)), ("2ch.29.2", "希西家的母親亞比雅。", ("希西家", "亞比雅")))
    _, people, _ = _graph(*verses, pericope_of={"2ch.11.22": "pc:a", "2ch.29.1": "pc:b", "2ch.29.2": "pc:b"})
    assert len(_named(people, "亞比雅")) == 2


def test_a_son_of_one_and_a_father_of_another_in_one_list_are_two_people():
    """2 Chronicles 29:12: 亞撒利雅的兒子約珥 and, further on, 耶哈利勒的兒子亞撒利雅."""
    _, people, edges = _graph(("2ch.29.12", "亞撒利雅的兒子約珥；米拉利的子孫，耶哈利勒的兒子亞撒利雅；",
                               ("亞撒利雅", "約珥", "米拉利", "耶哈利勒", "亞撒利雅")))
    assert len(_named(people, "亞撒利雅")) == 2


def test_a_son_named_again_as_a_father_is_one_person_in_a_chain():
    _, people, _ = _graph(("2sa.21.7", "掃羅的兒子約拿單起誓，又愛惜約拿單的兒子米非波設，", ("掃羅", "約拿單", "約拿單", "米非波設")))
    assert len(_named(people, "約拿單")) == 1
    _, people, _ = _graph(("1ch.4.37", "示非的兒子細撒。示非是亞龍的兒子；", ("示非", "細撒", "示非", "亞龍")))
    assert len(_named(people, "示非")) == 1


def test_a_list_of_men_with_a_son_of_one_and_a_father_of_another_is_two_people():
    """Acts 1:13: 亞勒腓的兒子雅各、奮銳黨的西門，和雅各的兒子猶大."""
    _, people, _ = _graph(("act.1.13", "亞勒腓的兒子雅各、奮銳黨的西門，和雅各的兒子猶大。",
                           ("亞勒腓", "雅各", "西門", "雅各", "猶大")))
    assert len(_named(people, "雅各")) == 2


def test_a_list_of_men_running_on_into_the_next_verse_is_two_people_too():
    """Luke 6:15-16: 亞勒腓的兒子雅各和奮銳黨的西門、 / 雅各的兒子猶大."""
    _, people, _ = _graph(("luk.6.15", "亞勒腓的兒子雅各和奮銳黨的西門、", ("亞勒腓", "雅各", "西門")),
                          ("luk.6.16", "雅各的兒子猶大。", ("雅各", "猶大")))
    assert len(_named(people, "雅各")) == 2


def test_a_kings_son_holds_his_fathers_kingdom():
    _, people, _ = _graph(("2ki.14.1", "以色列王約哈斯的兒子約阿施第二年，猶大王約阿施的兒子亞瑪謝登基。",
                           ("以色列", "約哈斯", "約阿施", "猶大", "約阿施", "亞瑪謝")),
                          homonyms=frozenset({"約阿施"}))
    assert len(_named(people, "約阿施")) == 2


def test_a_kings_father_holds_his_sons_kingdom():
    _, people, _ = _graph(("2ki.14.13", "約阿施的兒子猶大王亞瑪謝，", ("約阿施", "猶大", "亞瑪謝")),
                          ("2ki.14.14", "以色列王約阿施的兒子耶羅波安。", ("以色列", "約阿施", "耶羅波安")),
                          homonyms=frozenset({"約阿施"}))
    assert len(_named(people, "約阿施")) == 2


def test_the_regnal_table_gives_a_verse_its_king():
    _, people, _ = _graph(("2ki.22.1", "約西亞的母親名叫耶底大。", ("約西亞", "耶底大")),
                          ("1ch.3.14", "猶大王約西亞生約雅敬。", ("猶大", "約西亞", "約雅敬")),
                          pericope_of={"2ki.22.1": "pc:a", "1ch.3.14": "pc:b"},
                          regnal_titles={("約西亞", "2ki.22.1"): "猶大王"})
    assert len(_named(people, "約西亞")) == 1


def test_the_regnal_table_gives_a_son_of_its_father_his_kingdom():
    """2 Kings 8:25-28: the nearest earlier 約蘭 is the king of Judah; 亞哈的兒子 is Israel's."""
    verses = (("2ki.8.25", "猶大王約蘭的兒子亞哈謝登基。", ("猶大", "約蘭", "亞哈謝")),
              ("2ki.8.28", "他與亞哈的兒子約蘭同往。", ("亞哈", "約蘭")))
    pericopes = {"2ki.8.25": "pc:a", "2ki.8.28": "pc:a"}
    _, people, _ = _graph(*verses, pericope_of=pericopes, homonyms=frozenset({"約蘭"}),
                          regnal_sons={("約蘭", "亞哈"): "以色列王"})
    assert len(_named(people, "約蘭")) == 2


def test_a_kings_father_who_was_king_is_not_a_prophet_of_his_name():
    """耶戶 who begot 約哈斯 reigned; the 耶戶 of 2 Chronicles 19:2 is 哈拿尼's son."""
    _, people, _ = _graph(("2ki.9.2", "約沙法的兒子以色列王耶戶。", ("約沙法", "以色列", "耶戶")), ("2ki.9.3", "他們去了。", ()),
                          ("2ch.19.2", "哈拿尼的兒子耶戶。", ("哈拿尼", "耶戶")), ("2ch.19.3", "他們去了。", ()),
                          ("2ch.25.17", "耶戶的兒子約哈斯。", ("耶戶", "約哈斯")),
                          pericope_of={"2ki.9.2": "pc:a", "2ki.9.3": "pc:a", "2ch.19.2": "pc:b", "2ch.19.3": "pc:b",
                                       "2ch.25.17": "pc:c"},
                          regnal_fathers={("耶戶", "約哈斯"): "以色列王"})
    (king,) = [p for p in _named(people, "耶戶") if "2ch.25.17" in p.mention_units]
    assert "2ki.9.2" in king.mention_units and "2ch.19.2" not in king.mention_units


def test_the_regnal_table_says_nothing_of_a_verse_with_two_of_that_name():
    _, people, _ = _graph(("2ki.8.16", "亞哈的兒子約蘭，約沙法的兒子約蘭。", ("亞哈", "約蘭", "約沙法", "約蘭")),
                          ("2ki.8.17", "以色列王約蘭生甲。", ("以色列", "約蘭", "甲")), homonyms=frozenset({"約蘭"}),
                          pericope_of={"2ki.8.16": "pc:a", "2ki.8.17": "pc:c"},
                          regnal_titles={("約蘭", "2ki.8.16"): "猶大王"})
    assert len(_named(people, "約蘭")) >= 2


def test_a_shared_signature_joins_within_a_testament_group_whichever_cluster_sorts_first():
    """Acts sorts before Numbers; its 比珥 must not keep the Old Testament's apart."""
    _, people, _ = _graph(("act.2.15", "比珥的兒子巴蘭。", ("比珥", "巴蘭")),
                          ("num.22.5", "比珥的兒子巴蘭。", ("比珥", "巴蘭")),
                          ("jos.24.9", "比珥的兒子巴蘭。", ("比珥", "巴蘭")),
                          ("mic.6.5", "比珥的兒子巴蘭。", ("比珥", "巴蘭")))
    assert len(_named(people, "比珥")) == 2 and {len(p.mention_units) for p in _named(people, "比珥")} == {1, 3}


def test_a_signature_shared_by_a_conflicted_cluster_still_joins_the_others():
    _, people, _ = _graph(("1ch.7.6", "甲生丁。", ("甲", "丁")), ("gen.46.1", "乙生甲；甲生丁。", ("乙", "甲", "甲", "丁")),
                          ("gen.46.2", "丙生甲；甲生丁。", ("丙", "甲", "甲", "丁")),
                          ("exo.1.1", "甲生丁。", ("甲", "丁")),
                          pericope_of={"1ch.7.6": "pc:a", "gen.46.1": "pc:b", "gen.46.2": "pc:c", "exo.1.1": "pc:d"})
    assert len(_named(people, "甲")) == 2


def test_someone_called_by_another_name_is_not_the_one_without_it():
    """Acts 12: 約翰的哥哥雅各, and in the same pericope 稱呼馬可的約翰的母親馬利亞."""
    _, people, _ = _graph(("act.12.2", "約翰的哥哥雅各。", ("約翰", "雅各")), ("act.12.3", "他們去了。", ()),
                          ("act.12.12", "稱呼馬可的約翰的母親馬利亞。", ("馬可", "約翰", "馬利亞")),
                          ("act.12.25", "稱呼馬可的約翰的母親馬利亞。", ("馬可", "約翰", "馬利亞")),
                          pericope_of={"act.12.2": "pc:a", "act.12.3": "pc:a", "act.12.12": "pc:a", "act.12.25": "pc:b"})
    assert sorted(len(p.mention_units) for p in _named(people, "約翰")) == [1, 2]


def test_a_relatives_other_name_is_the_same_signature():
    aliases = Aliases("person_aliases@0", (Rename("雅各", "以色列", "O", "gen.32.28"),), ())
    _, people, _ = _graph(("gen.46.19", "雅各生約瑟；", ("雅各", "約瑟")), ("1ch.7.29", "以色列生約瑟；", ("以色列", "約瑟")),
                          aliases=aliases, pericope_of={"gen.46.19": "pc:a", "1ch.7.29": "pc:b"})
    assert len(_named(people, "約瑟")) == 1


def test_a_footnote_pair_makes_no_other_persons_signature_alike():
    """亞撒利雅 is 亞哈謝 for one king (2 Chronicles 22:6): 耶戶's son 約哈斯 and 俄備得's 耶戶 are not joined by it."""
    aliases = Aliases("person_aliases@0", (), (FootnotePair("亞撒利雅", "亞哈謝", "fn:1"), FootnotePair("約哈斯", "亞哈謝", "fn:2")))
    _, people, _ = _graph(("2ki.13.1", "耶戶的兒子約哈斯。", ("耶戶", "約哈斯")), ("2ki.13.2", "他們去了。", ()),
                          ("1ch.2.38", "耶戶的兒子亞撒利雅。", ("耶戶", "亞撒利雅")), aliases=aliases,
                          pericope_of={"2ki.13.1": "pc:a", "2ki.13.2": "pc:a", "1ch.2.38": "pc:b"})
    assert len(_named(people, "耶戶")) == 2


def test_an_old_testament_rename_joins_every_cluster_of_its_two_names():
    aliases = Aliases("person_aliases@0", (Rename("雅各", "以色列", "O", "gen.32.28"),), ())
    _, people, _ = _graph(("gen.46.19", "雅各生約瑟；", ("雅各", "約瑟")), ("jdg.18.29", "以色列生但。", ("以色列", "但")),
                          ("1ch.1.34", "以撒生以色列。", ("以撒", "以色列")), aliases=aliases,
                          pericope_of={"gen.46.19": "pc:a", "jdg.18.29": "pc:b", "1ch.1.34": "pc:c"})
    (person,) = _named(people, "以色列")
    assert "雅各" in person.surfaces and person.mentions == 3


def test_an_old_testament_rename_leaves_a_name_of_several_men_alone():
    aliases = Aliases("person_aliases@0", (Rename("瑪探雅", "西底家", "O", "2ki.24.17"),), ())
    _, people, _ = _graph(("2ki.24.17", "瑪探雅的兒子甲。", ("瑪探雅", "甲")), ("1ch.25.4", "希幔的兒子瑪探雅。", ("希幔", "瑪探雅")),
                          ("2ch.20.14", "亞薩的兒子瑪探雅。", ("亞薩", "瑪探雅")), ("1ki.22.11", "基拿拿的兒子西底家。", ("基拿拿", "西底家")),
                          aliases=aliases, pericope_of={"2ki.24.17": "pc:a", "1ch.25.4": "pc:b", "2ch.20.14": "pc:c", "1ki.22.11": "pc:d"})
    assert len(_named(people, "瑪探雅")) == 3


def test_samuel_is_one_book_for_a_much_mentioned_name_only():
    others = [(f"1sa.20.{n}", "大衛去了。", ("大衛",)) for n in range(1, 30)]
    _, people, _ = _graph(("1sa.18.27", "大衛的妻子米甲。", ("大衛", "米甲")), *others, ("2sa.3.2", "大衛的兒子暗嫩。", ("大衛", "暗嫩")),
                          pericope_of={"1sa.18.27": "pc:a", **{f"1sa.20.{n}": "pc:c" for n in range(1, 30)}, "2sa.3.2": "pc:b"})
    assert len(_named(people, "大衛")) == 1
    _, people, _ = _graph(("1sa.31.2", "掃羅的兒子亞比拿達。", ("掃羅", "亞比拿達")), ("1sa.31.3", "他們去了。", ()),
                          ("2sa.6.3", "亞比拿達的兒子亞希約。", ("亞比拿達", "亞希約")),
                          pericope_of={"1sa.31.2": "pc:a", "1sa.31.3": "pc:a", "2sa.6.3": "pc:b"})
    assert len(_named(people, "亞比拿達")) == 2


def test_neighbouring_pericopes_join_in_a_narrative_of_the_old_testament_only():
    verses = (("{}.3.1", "甲生乙。", ("甲", "乙")), ("{}.3.2", "他們去了。", ()), ("{}.4.1", "丙生甲。", ("丙", "甲")))
    for book, joined in (("gen", 1), ("1ch", 2), ("mrk", 2)):
        written = [(u.format(book), t, n) for u, t, n in verses]
        _, people, _ = _graph(*written, pericope_of={written[0][0]: "pc:a", written[1][0]: "pc:a", written[2][0]: "pc:b"},
                              next_id={"pc:a": "pc:b"})
        assert len(_named(people, "甲")) == joined, book


def test_a_much_mentioned_name_with_rows_in_two_books_does_not_take_a_third():
    """亞比米勒 of Judges and 2 Samuel is not the king of Gerar in Genesis."""
    others = [(f"gen.20.{n}", "亞比米勒來了。", ("亞比米勒",)) for n in range(1, 30)]
    _, people, _ = _graph(("jdg.8.31", "基甸的兒子亞比米勒。", ("基甸", "亞比米勒")),
                          ("2sa.11.21", "基甸的兒子亞比米勒。", ("基甸", "亞比米勒")), *others)
    (person,) = _named(people, "亞比米勒")
    assert person.mention_units == ("jdg.8.31", "2sa.11.21")


def test_a_gentile_written_once_does_not_keep_a_man_with_no_father_out_of_his_book():
    """利未人亞倫 in Exodus 4:14 and 亞倫的姊姊 in 15:20 are one man."""
    _, people, _ = _graph(("exo.4.14", "暗蘭生利未人亞倫。", ("暗蘭", "利未", "亞倫")), ("exo.15.20", "亞倫的姊姊米利暗。", ("亞倫", "米利暗")),
                          pericope_of={"exo.4.14": "pc:a", "exo.15.20": "pc:b"})
    assert len(_named(people, "亞倫")) == 1


def test_jesus_is_one_person_everywhere():
    _, people, _ = _graph(("mat.1.16", "馬利亞生耶穌。", ("馬利亞", "耶穌")), ("mat.2.1", "他們去了。", ()),
                          ("jhn.1.45", "約瑟的兒子耶穌。", ("約瑟", "耶穌")), ("jhn.1.46", "他們去了。", ()),
                          ("act.1.14", "耶穌的母親馬利亞。", ("耶穌", "馬利亞")),
                          pericope_of={"mat.1.16": "pc:a", "mat.2.1": "pc:a", "jhn.1.45": "pc:b", "jhn.1.46": "pc:b", "act.1.14": "pc:c"})
    assert len(_named(people, "耶穌")) == 1


def test_a_token_goes_to_the_one_cluster_of_its_own_book_though_samuel_merges_as_one():
    """約拿單 is 掃羅's son alone in 1 Samuel, whoever else 2 Samuel calls 約拿單."""
    _, people, _ = _graph(("1sa.14.1", "掃羅的兒子約拿單。", ("掃羅", "約拿單")), ("1sa.18.1", "約拿單愛大衛。", ("約拿單",)),
                          ("2sa.15.27", "亞比亞他的兒子約拿單。", ("亞比亞他", "約拿單")),
                          pericope_of={"1sa.14.1": "pc:a", "1sa.18.1": "pc:b", "2sa.15.27": "pc:c"})
    (son,) = [p for p in _named(people, "約拿單") if "1sa.14.1" in p.mention_units]
    assert son.mention_units == ("1sa.14.1", "1sa.18.1")


def test_the_lists_of_numbers_merge_nothing_on_the_book_alone():
    """亞米忽 of Ephraim (Numbers 1:10) is not 亞米忽 of Simeon (34:20)."""
    _, people, _ = _graph(("num.1.10", "亞米忽的兒子以利沙瑪。", ("亞米忽", "以利沙瑪")), ("num.2.1", "他們去了。", ()),
                          ("num.34.20", "亞米忽的兒子示母利。", ("亞米忽", "示母利")),
                          pericope_of={"num.1.10": "pc:a", "num.2.1": "pc:a", "num.34.20": "pc:b"})
    assert len(_named(people, "亞米忽")) == 2


def test_two_wives_of_two_husbands_are_not_joined_by_their_book_alone():
    _, people, _ = _graph(("gen.4.19", "拉麥的妻子亞大。", ("拉麥", "亞大")), ("gen.36.2", "以掃的妻子亞大。", ("以掃", "亞大")),
                          pericope_of={"gen.4.19": "pc:a", "gen.36.2": "pc:b"})
    assert len(_named(people, "亞大")) == 2


def test_a_much_mentioned_name_does_not_merge_on_having_no_conflict():
    others = [(f"mrk.1.{n}", "約翰去了。", ("約翰",)) for n in range(1, 30)]
    _, people, _ = _graph(("mrk.10.35", "西庇太的兒子約翰。", ("西庇太", "約翰")), *others,
                          ("jhn.1.42", "約翰的兒子西門。", ("約翰", "西門")))
    assert len(_named(people, "約翰")) == 2


def test_the_narrative_of_the_new_testament_merges_nothing_on_the_same_book_alone():
    _, people, _ = _graph(("mat.2.11", "馬利亞的丈夫約瑟。", ("馬利亞", "約瑟")),
                          ("mat.2.12", "他們走了。", ()),
                          ("mat.27.56", "雅各的母親馬利亞。", ("雅各", "馬利亞")),
                          pericope_of={"mat.27.56": "pc:a", "mat.2.11": "pc:b", "mat.2.12": "pc:b"})
    assert len(_named(people, "馬利亞")) == 2


def test_a_gentile_and_a_man_with_no_gentile_are_not_joined_by_their_book_alone():
    _, people, _ = _graph(("gen.23.8", "赫人瑣轄的兒子以弗崙。", ("赫", "瑣轄", "以弗崙")),
                          ("gen.46.10", "西緬的兒子瑣轄。", ("西緬", "瑣轄")),
                          pericope_of={"gen.23.8": "pc:a", "gen.46.10": "pc:b"})
    assert len(_named(people, "瑣轄")) == 2


def test_in_a_list_book_a_token_without_a_row_goes_to_no_one_by_its_book_or_pericope():
    _, people, _ = _graph(("ezr.8.11", "比拜的兒子撒迦利亞。", ("比拜", "撒迦利亞")), ("ezr.8.12", "有撒迦利亞。", ("撒迦利亞",)),
                          ("ezr.10.1", "有撒迦利亞。", ("撒迦利亞",)), pericope_of={
                              "ezr.8.11": "pc:a", "ezr.8.12": "pc:a", "ezr.10.1": "pc:b"})
    (person,) = _named(people, "撒迦利亞")
    assert person.mention_units == ("ezr.8.11",)


def test_a_described_token_of_the_new_testament_without_a_row_goes_to_no_one():
    _, people, _ = _graph(("act.12.2", "約翰的哥哥雅各。", ("約翰", "雅各")), ("act.12.3", "約翰來了。", ("約翰",)),
                          ("act.12.12", "稱呼馬可的約翰來了。", ("馬可", "約翰",)),
                          pericope_of={"act.12.2": "pc:a", "act.12.3": "pc:a", "act.12.12": "pc:a"})
    (person,) = _named(people, "約翰")
    assert person.mention_units == ("act.12.2", "act.12.3")


def test_in_the_new_testament_narrative_a_token_without_a_row_goes_only_to_its_pericopes_person():
    verses = (("mrk.1.19", "西庇太的兒子約翰。", ("西庇太", "約翰")), ("mrk.1.20", "約翰就去了。", ("約翰",)),
              ("mrk.9.2", "約翰也去了。", ("約翰",)), ("jhn.1.42", "約翰的兒子西門。", ("約翰", "西門")))
    pericopes = {"mrk.1.19": "pc:a", "mrk.1.20": "pc:a", "mrk.9.2": "pc:b", "jhn.1.42": "pc:c"}
    _, people, _ = _graph(*verses, pericope_of=pericopes)
    (zebedee,) = [p for p in _named(people, "約翰") if "mrk.1.19" in p.mention_units]
    assert zebedee.mention_units == ("mrk.1.19", "mrk.1.20")


def test_a_person_seen_once_in_the_new_testament_does_not_take_the_books_other_tokens():
    """Acts 13:21 cites 基士的兒子掃羅; the 掃羅 of Acts 7 to 13 is someone else."""
    others = [(f"act.8.{n}", "掃羅去了。", ("掃羅",)) for n in range(1, 31)]
    _, people, _ = _graph(("act.13.21", "基士的兒子掃羅。", ("基士", "掃羅")), *others,
                          pericope_of={**{f"act.8.{n}": "pc:a" for n in range(1, 31)}, "act.13.21": "pc:b"})
    (saul,) = _named(people, "掃羅")
    assert saul.mention_units == ("act.13.21",)


def test_a_rename_joins_the_cluster_at_its_evidence_verse():
    rename = Rename("西門", "磯法", "N", "jhn.1.42")
    aliases = Aliases("person_aliases@0", (rename,), ())
    _, people, _ = _graph(("mat.27.32", "古利奈人西門的兒子甲。", ("古利奈", "西門", "甲")),
                          ("jhn.1.42", "約翰的兒子西門，又叫磯法。磯法的兒子乙。", ("約翰", "西門", "磯法", "磯法", "乙")),
                          aliases=aliases,
                          pericope_of={"mat.27.32": "pc:a", "jhn.1.42": "pc:b"})
    joined = [p for p in _named(people, "磯法")]
    assert len(joined) == 1 and "西門" in joined[0].surfaces and "mat.27.32" not in joined[0].mention_units


def test_the_same_book_merges_unless_the_name_is_a_regnal_homonym():
    verses = (("2ki.1.1", "約蘭生亞哈謝。", ("約蘭", "亞哈謝")), ("2ki.2.1", "他們去了。", ()),
              ("2ki.2.2", "約蘭生米該亞。", ("約蘭", "米該亞")))
    pericopes = {"2ki.1.1": "pc:a", "2ki.2.1": "pc:b", "2ki.2.2": "pc:b"}
    assert len(_named(_graph(*verses, pericope_of=pericopes)[1], "約蘭")) == 1
    assert len(_named(_graph(*verses, pericope_of=pericopes, homonyms=frozenset({"約蘭"}))[1], "約蘭")) == 2


def test_the_list_books_merge_by_chapter_only():
    _, people, _ = _graph(("1ch.3.1", "示瑪生亞哈謝。", ("示瑪", "亞哈謝")), ("1ch.4.1", "示瑪生米該亞。", ("示瑪", "米該亞")))
    assert len(_named(people, "示瑪")) == 2


def test_a_rename_joins_two_names_in_its_scope_only():
    rename = Rename("亞伯蘭", "亞伯拉罕", "O", "gen.17.5")
    aliases = Aliases("person_aliases@0", (rename,), ())
    _, people, _ = _graph(("gen.11.27", "他拉生亞伯蘭。", ("他拉", "亞伯蘭")),
                          ("gen.21.3", "亞伯拉罕生以撒。", ("亞伯拉罕", "以撒")),
                          ("mat.1.2", "亞伯拉罕生以撒。", ("亞伯拉罕", "以撒")), aliases=aliases)
    joined = _named(people, "亞伯蘭")
    assert len(joined) == 1 and "亞伯拉罕" in joined[0].surfaces
    assert len(_named(people, "亞伯拉罕")) == 2


def test_a_renamed_name_without_rows_lends_its_tokens_the_cluster_at_the_evidence_verse():
    rename = Rename("西門‧彼得", "彼得", "N", "jhn.1.40")
    aliases = Aliases("person_aliases@0", (rename,), ())
    _, people, _ = _graph(("jhn.1.40", "西門‧彼得的兄弟安得烈。", ("西門‧彼得", "安得烈")),
                          ("mat.4.18", "耶穌看見彼得。", ("彼得",)), aliases=aliases)
    (person,) = _named(people, "彼得")
    assert person.surfaces == ("彼得", "西門‧彼得") and person.mention_units == ("jhn.1.40", "mat.4.18")


def test_a_token_without_a_row_goes_to_the_one_cluster_of_its_name_in_its_book():
    _, people, _ = _graph(("gen.21.3", "亞伯拉罕生以撒。", ("亞伯拉罕", "以撒")),
                          ("gen.22.1", "亞伯拉罕獻祭。", ("亞伯拉罕",)),
                          ("exo.3.6", "亞伯拉罕的上帝。", ("亞伯拉罕",)))
    (person,) = _named(people, "亞伯拉罕")
    assert person.mentions == 2 and person.mention_units == ("gen.21.3", "gen.22.1")


def test_a_much_mentioned_name_with_one_cluster_holds_its_tokens_across_its_testament_group():
    others = [(f"lev.1.{n}", "耶和華曉諭摩西說：", ("摩西",)) for n in range(1, 30)]
    _, people, _ = _graph(("exo.2.22", "摩西生革舜。", ("摩西", "革舜")), ("num.3.1", "摩西生革舜。", ("摩西", "革舜")),
                          ("1ch.23.15", "摩西生革舜。", ("摩西", "革舜")), *others, ("mrk.1.44", "摩西所吩咐的。", ("摩西",)))
    (person,) = _named(people, "摩西")
    assert person.mentions == 32 and "lev.1.29" in person.mention_units
    assert "mrk.1.44" not in person.mention_units


def test_a_token_of_a_name_with_two_clusters_in_its_book_goes_to_neither():
    _, people, _ = _graph(("1ki.1.1", "猶大王約蘭生亞哈謝。", ("猶大", "約蘭", "亞哈謝")),
                          ("1ki.2.1", "以色列王約蘭生米該亞。", ("以色列", "約蘭", "米該亞")),
                          ("1ki.3.1", "約蘭去了。", ("約蘭",)), pericope_of={
                              "1ki.1.1": "pc:a", "1ki.2.1": "pc:b", "1ki.3.1": "pc:c"})
    assert all("1ki.3.1" not in p.mention_units for p in _named(people, "約蘭"))


def test_a_token_followed_by_a_people_word_is_no_mention_of_the_person():
    _, people, _ = _graph(("gen.21.3", "亞伯拉罕生以撒。", ("亞伯拉罕", "以撒")),
                          ("gen.22.1", "以撒人來了，以撒地。", ("以撒", "以撒")),
                          ("gen.22.2", "以撒去了。", ("以撒",)))
    (person,) = _named(people, "以撒")
    assert person.mention_units == ("gen.21.3", "gen.22.2")


def test_a_name_mostly_written_as_a_people_is_a_person_only_where_a_kin_row_says_so():
    tribe = [(f"num.1.{n}", "以色列人都來了。", ("以色列",)) for n in range(1, 5)]
    _, people, _ = _graph(("gen.46.1", "以色列生呂便。", ("以色列", "呂便")), *tribe,
                          ("psa.1.1", "以色列的上帝。", ("以色列",)))
    (person,) = _named(people, "以色列")
    assert person.mention_units == ("gen.46.1",)


def test_parallel_pericopes_join_a_name_across_books():
    verses = (("2sa.3.2", "大衛生暗嫩。", ("大衛", "暗嫩")), ("1ch.3.1", "大衛生但以理。", ("大衛", "但以理")))
    pericopes = {"2sa.3.2": "pc:2sa.3.2", "1ch.3.1": "pc:1ch.3.1"}
    apart = _graph(*verses, pericope_of=pericopes)[1]
    joined = _graph(*verses, pericope_of=pericopes,
                    parallels={"pc:2sa.3.2": ("pc:1ch.3.1",), "pc:1ch.3.1": ("pc:2sa.3.2",)})[1]
    assert (len(_named(apart, "大衛")), len(_named(joined, "大衛"))) == (2, 1)


def test_the_new_testament_genealogies_join_the_old_testament_only_on_two_signatures():
    one = _graph(("gen.21.3", "亞伯拉罕生以撒；以撒生以掃。", ("亞伯拉罕", "以撒", "以撒", "以掃")),
                 ("mat.1.2", "亞伯拉罕生以撒；以撒生雅各。", ("亞伯拉罕", "以撒", "以撒", "雅各")))[1]
    two = _graph(("gen.21.3", "亞伯拉罕生以撒；以撒生雅各。", ("亞伯拉罕", "以撒", "以撒", "雅各")),
                 ("mat.1.2", "亞伯拉罕生以撒；以撒生雅各。", ("亞伯拉罕", "以撒", "以撒", "雅各")))[1]
    assert (len(_named(one, "以撒")), len(_named(two, "以撒"))) == (2, 1)


def test_edges_merge_their_evidence_and_undirected_ones_run_from_the_smaller_id():
    _, people, edges = _graph(("gen.20.18", "亞伯拉罕的妻子撒拉的緣故", ("亞伯拉罕", "撒拉")),
                              ("gen.21.2", "撒拉的丈夫亞伯拉罕", ("撒拉", "亞伯拉罕")))
    (edge,) = edges
    assert edge.rel == "SPOUSE_OF" and edge.src < edge.dst and edge.role == "-"
    assert edge.evidence_units == ("gen.20.18", "gen.21.2")
    assert edge.patterns == ("n3_sp", "spouse_noun")


def test_a_role_is_a_mother_only_when_all_its_evidence_writes_a_mother():
    verse = ("mat.1.5", "波阿斯從路得氏生俄備得；", ("波阿斯", "路得", "俄備得"))
    _, people, edges = _graph(verse)
    assert {(e.role) for e in edges} == {"P", "M"}
    _, people, edges = _graph(verse, ("rut.4.13", "路得的兒子俄備得", ("路得", "俄備得")))
    label = {p.person_id: p.label for p in people}
    roles = {(label[e.src], e.role) for e in edges}
    assert ("路得", "P") in roles


def test_evidence_runs_across_both_verses_of_a_row():
    _, _, edges = _graph(("1ch.2.1", "呂便、西緬、", ("呂便", "西緬")), ("1ch.2.2", "這都是以色列的兒子。", ("以色列",)))
    assert {e.evidence_units for e in edges} == {("1ch.2.1", "1ch.2.2")}


def test_one_token_written_as_a_man_and_as_a_woman_is_a_kin_conflict():
    _, people, _ = _graph(("gen.1.1", "丁的妻子乙的妻子丙。", ("丁", "乙", "丙")))
    assert [p.label for p in people if p.kin_conflict] == ["乙"]


def test_two_tokens_written_as_a_man_and_as_a_woman_are_two_people():
    _, people, _ = _graph(("gen.1.1", "甲的妻子乙。乙的妻子丙。", ("甲", "乙", "乙", "丙")))
    assert len(_named(people, "乙")) == 2 and not any(p.kin_conflict for p in people)


def test_fathers_that_are_one_name_through_each_other_are_no_conflict():
    aliases = Aliases("person_aliases@0", (Rename("耶路‧巴力", "基甸", "O", "jdg.6.32"),),
                      (FootnotePair("耶路‧比設", "耶路‧巴力", "fn:1"),))
    _, people, _ = _graph(("jdg.8.31", "基甸的兒子亞比米勒，耶路‧巴力的兒子亞比米勒，耶路‧比設的兒子亞比米勒。",
                           ("基甸", "亞比米勒", "耶路‧巴力", "亞比米勒", "耶路‧比設", "亞比米勒")), aliases=aliases)
    assert not any(p.kin_conflict for p in people)


def test_a_mother_read_from_a_list_is_no_second_father():
    _, people, _ = _graph(("2sa.3.2", "大衛的四子亞多尼雅是哈及所生的；", ("大衛", "亞多尼雅", "哈及")))
    assert not any(p.kin_conflict for p in people)


def test_the_cited_verse_writes_both_people_when_one_does():
    _, _, edges = _graph(("2sa.3.2", "大衛在希伯崙得了幾個兒子：", ("大衛",)),
                         ("2sa.3.3", "長子押沙龍，", ("押沙龍",)),
                         ("2sa.13.1", "大衛的兒子押沙龍。", ("大衛", "押沙龍")), pericope_of={
                             "2sa.3.2": "pc:a", "2sa.3.3": "pc:a", "2sa.13.1": "pc:b"})
    (edge,) = edges
    assert edge.evidence_units == ("2sa.13.1", "2sa.3.2", "2sa.3.3")


def test_two_fathers_of_different_names_in_one_person_is_a_kin_conflict():
    aliases = Aliases("person_aliases@0", (), (FootnotePair("亞比央", "亞比雅", "fn:1"),))
    _, people, _ = _graph(("gen.1.1", "甲生丙。乙生丙。", ("甲", "丙", "乙", "丙")), aliases=aliases)
    assert [p.label for p in people if p.kin_conflict] == []     # refused: two people
    _, people, _ = _graph(("1ki.15.8", "亞比央的兒子亞撒。亞比雅的兒子亞撒。", ("亞比央", "亞撒", "亞比雅", "亞撒")), aliases=aliases)
    assert not any(p.kin_conflict for p in people)


def test_person_ids_follow_the_first_mention_in_pdf_order():
    _, people, _ = _graph(("gen.1.1", "甲生乙。", ("甲", "乙")), ("gen.1.2", "丙生丁。", ("丙", "丁")))
    assert [(p.person_id, p.label) for p in people] == [
        ("e000001", "甲"), ("e000002", "乙"), ("e000003", "丙"), ("e000004", "丁")]


def test_the_alias_registry_is_held_to_what_the_pdf_writes():
    aliases = parse({"schema": "ragdata.person_aliases.v1",
                     "rename": [{"old": "撒萊", "new": "撒拉", "scope": "O", "evidence": "gen.17.15"}],
                     "footnote": [{"name": "亞比央", "other": "亞比雅", "evidence": "fn:1ki.14.31#1"}]}, "person_aliases@0")
    verses = {"gen.17.15": "你的妻子撒萊不可再叫撒萊，她的名要叫撒拉。", "1ki.14.31": "他兒子亞比央接續他作王。"}
    notes = {"fn:1ki.14.31#1": {"text": "又名亞比雅", "unit_key": "1ki.14.31"}}
    assert check_evidence(aliases, verses, notes) == []
    assert aliases.same["亞比雅"] == frozenset({"亞比央"})
    assert len(check_evidence(aliases, {**verses, "gen.17.15": "別的話"}, notes)) == 1
    assert len(check_evidence(aliases, verses, {})) == 1


@pytest.mark.parametrize("doc", [
    {"schema": "other", "rename": [], "footnote": []},
    {"schema": "ragdata.person_aliases.v1", "rename": [{"old": "甲", "new": "乙", "scope": "X", "evidence": "gen.1.1"}], "footnote": []},
    {"schema": "ragdata.person_aliases.v1", "rename": [], "footnote": [{"name": "甲", "evidence": "fn:1"}]},
    {"schema": "ragdata.person_aliases.v1", "rename": None, "footnote": []},
])
def test_a_malformed_alias_registry_is_refused(doc):
    with pytest.raises(RegistryError):
        parse(doc, "person_aliases@0")
