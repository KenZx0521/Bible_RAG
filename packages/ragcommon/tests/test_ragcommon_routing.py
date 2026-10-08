import json

import pytest

from ragcommon import routing
from ragcommon.routing import RoutingLexiconError
from ragcommon.tests.lexicon_doc import book, document, event, exclusion, name, target, term

BOOKS = [book("約翰一書", "1jn", "約翰一書"), book("約翰福音", "jhn", "約翰福音"),
         book("約一", "1jn", "約翰一書"), book("約", "jhn", "約翰福音", routable=False)]


def _doc(**override):
    doc = document(
        names=[name("亞伯拉罕", "nm:000000000001"), name("亞伯", "nm:000000000002", "Person"),
               name("約翰", "nm:000000000003"), name("撒但", "nm:000000000004"),
               name("但", "nm:000000000005", routable=False), name("何提", "nm:000000000006"),
               name("大衛", "nm:000000000007"), name("歌利亞", "nm:000000000008")],
        divine=[term("耶穌", "divine", [target("dr.span.008", "耶穌", "Person")])],
        events=[event("大衛與歌利亞", "ev0008", "大衛擊殺歌利亞")],
        books=BOOKS, exclusions=[exclusion("何提", "如何提")])
    doc.update(override)
    return doc


def _surfaces(lex, text):
    return [h.surface for h in lex.match(text)]


def test_the_longest_term_wins_and_the_scan_goes_on_after_it():
    lex = routing.parse_lexicon(_doc())

    hits = lex.match("亞伯拉罕和亞伯")
    assert [(h.surface, h.start, h.end) for h in hits] == [("亞伯拉罕", 0, 4), ("亞伯", 5, 7)]
    assert hits[1].targets == (routing.Target("nm:000000000002", "亞伯", ("Person",)),)


def test_book_names_are_masked_before_matching_and_offsets_are_kept():
    lex = routing.parse_lexicon(_doc())

    assert lex.mask_books("約翰福音說約翰") == "□□□□說約翰"
    assert [(h.surface, h.start) for h in lex.match("約翰福音說約翰")] == [("約翰", 5)]


def test_a_name_inside_an_event_phrase_is_not_a_separate_hit():
    lex = routing.parse_lexicon(_doc())

    [hit] = lex.match("大衛與歌利亞的故事")
    assert hit.kind == "event" and hit.targets[0].ref == "ev0008"


def test_an_unroutable_term_neither_hits_nor_blocks():
    lex = routing.parse_lexicon(_doc())

    assert _surfaces(lex, "但是撒但") == ["撒但"]
    assert _surfaces(lex, "但是") == []
    # surfaces made up: the unroutable 以來 would otherwise swallow the 來 of 來亞
    lex = routing.parse_lexicon(document(names=[name("以來", "nm:00000000000a", routable=False),
                                                name("來亞", "nm:00000000000b")]))
    assert _surfaces(lex, "以來亞") == ["來亞"]


def test_an_exclusion_vetoes_the_surface_in_its_context_only():
    lex = routing.parse_lexicon(_doc())

    assert _surfaces(lex, "如何提醒門徒") == []
    assert _surfaces(lex, "何提是誰") == ["何提"]


def test_a_vetoed_candidate_lets_a_shorter_one_at_the_same_position_try():
    lex = routing.parse_lexicon(document(
        names=[name("甲乙丙", "nm:00000000000c"), name("甲乙", "nm:00000000000d")],
        exclusions=[exclusion("甲乙丙", "甲乙丙丁")]))

    assert _surfaces(lex, "甲乙丙丁") == ["甲乙"]
    assert _surfaces(lex, "甲乙丙") == ["甲乙丙"]


def _overlapping():
    return routing.parse_lexicon(document(
        names=[name("他拉", "nm:000000000015"), name("拉撒路", "nm:000000000016"),
               name("撒路", "nm:000000000017"), name("亞伯拉罕", "nm:000000000018"),
               name("亞伯", "nm:000000000019"), name("甲乙", "nm:00000000001a"),
               name("乙丙", "nm:00000000001b")],
        divine=[term("耶穌", "divine", [target("dr.span.008", "耶穌", "Person")])]))


def test_an_overlap_goes_to_the_longer_term_even_when_a_shorter_one_starts_first():
    lex = _overlapping()

    assert _surfaces(lex, "耶穌叫他拉撒路出來嗎？") == ["耶穌", "拉撒路"]
    assert _surfaces(lex, "他拉的兒子亞伯拉罕") == ["他拉", "亞伯拉罕"]


def test_an_overlap_of_equal_lengths_goes_to_the_earlier_term():
    assert _surfaces(_overlapping(), "甲乙丙") == ["甲乙"]


def test_hits_come_back_in_text_order_though_the_longer_one_is_taken_first():
    hits = _overlapping().match("亞伯和亞伯拉罕")

    assert [(h.surface, h.start, h.end) for h in hits] == [("亞伯", 0, 2), ("亞伯拉罕", 3, 7)]


def test_a_shorter_term_still_hits_where_a_longer_one_at_its_start_was_blocked():
    # every occurrence is a candidate, not only the longest at each start
    lex = routing.parse_lexicon(document(
        names=[name("以利", "nm:00000000001f"), name("以利亞", "nm:000000000020"),
               name("亞伯拉罕", "nm:000000000021"), name("保羅", "nm:000000000022")],
        divine=[term("主耶穌基督", "divine", [target("dr.span.008", "耶穌", "Person")])],
        events=[event("保羅歸主", "ev0002", "保羅歸主")]))

    assert _surfaces(lex, "以利亞伯拉罕") == ["以利", "亞伯拉罕"]
    assert _surfaces(lex, "保羅歸主耶穌基督") == ["保羅", "主耶穌基督"]
    assert _surfaces(lex, "保羅歸主耶穌") == ["保羅歸主"]


def test_a_vetoed_longer_term_does_not_displace_the_shorter_ones_it_overlaps():
    # surfaces made up: the veto drops 乙丙丁 before selection, so 甲乙 and 丁戊 stay
    lex = routing.parse_lexicon(document(
        names=[name("甲乙", "nm:00000000001c"), name("乙丙丁", "nm:00000000001d"),
               name("丁戊", "nm:00000000001e")],
        exclusions=[exclusion("乙丙丁", "甲乙丙丁")]))

    assert _surfaces(lex, "甲乙丙丁戊") == ["甲乙", "丁戊"]
    assert _surfaces(lex, "乙丙丁戊") == ["乙丙丁"]


def test_a_hit_returns_every_target_of_its_term():
    two = term("西門彼得", "dotless", [target("nm:00000000000e", "西門‧彼得", "Person"),
                                     target("nm:00000000000f", "西門彼‧得", "Place")])
    lex = routing.parse_lexicon(document(names=[two]))

    [hit] = lex.match("西門彼得")
    assert [t.ref for t in hit.targets] == ["nm:00000000000e", "nm:00000000000f"]


def test_books_match_in_list_order_once_each_and_skip_single_characters():
    lex = routing.parse_lexicon(_doc())

    assert lex.match_books("約翰一書與約翰福音、約一") == ["約翰一書", "約翰福音"]
    assert lex.match_books("約") == []
    assert lex.count_books("約翰福音和約翰") == 1


def _abbreviations():
    return routing.parse_lexicon(document(
        names=[name("以撒", "nm:000000000011"), name("以斯帖", "nm:000000000012"),
               name("瓦實提", "nm:000000000013"), name("亞伯拉罕", "nm:000000000014")],
        events=[event("亞伯拉罕之約", "ev0024", "上帝與亞伯蘭立約")],
        books=[book("帖撒羅尼迦前書", "1th", "帖撒羅尼迦前書"), book("撒母耳記上", "1sa", "撒母耳記上"),
               book("提摩太後書", "2ti", "提摩太後書"), book("約翰三書", "3jn", "約翰三書"),
               book("撒上", "1sa", "撒母耳記上"), book("帖前", "1th", "帖撒羅尼迦前書"),
               book("提後", "2ti", "提摩太後書"), book("約三", "3jn", "約翰三書")]))


@pytest.mark.parametrize("text, hits", [
    ("亞伯拉罕帶以撒上摩利亞山", ["亞伯拉罕", "以撒"]),
    ("以斯帖前去見王", ["以斯帖"]),
    ("瓦實提後來的結局", ["瓦實提"]),
    ("亞伯拉罕之約三個應許", ["亞伯拉罕之約"]),
])
def test_a_term_over_an_abbreviation_wins_and_the_abbreviation_names_no_book(text, hits):
    lex = _abbreviations()

    assert _surfaces(lex, text) == hits
    assert lex.match_books(text) == [] and lex.mask_books(text) == text


def test_full_names_are_masked_and_an_abbreviation_the_scan_reads_names_its_book():
    lex = _abbreviations()

    assert set(lex.full_names) == {"帖撒羅尼迦前書", "撒母耳記上", "提摩太後書", "約翰三書"}
    assert lex.match_books("撒上17章與帖前4章") == ["撒母耳記上", "帖撒羅尼迦前書"]
    assert _surfaces(lex, "撒上17章以撒，撒母耳記上的以撒") == ["以撒", "以撒"]


def test_an_empty_lexicon_is_legal():
    lex = routing.parse_lexicon(document())

    assert lex.match("亞伯拉罕") == [] and lex.match_books("約翰福音") == []


def test_render_is_canonical_and_round_trips():
    doc = _doc()
    data = routing.render_lexicon(doc)
    assert data.endswith(b"\n")
    assert json.loads(data) == doc
    assert routing.render_lexicon(json.loads(data)) == data


def test_load_lexicon_reads_a_file(tmp_path):
    path = tmp_path / "lex.json"
    path.write_bytes(routing.render_lexicon(_doc()))
    assert _surfaces(routing.load_lexicon(path), "約翰") == ["約翰"]


def _names(*rows):
    return {"names": list(rows)}


@pytest.mark.parametrize("override, message", [
    ({"schema": "ragdata.routing_lexicon.v1"}, "schema must be"),
    ({"variant": "R1"}, "variant must be R2"),
    ({"persons": []}, "keys"),
    (_names({**name("甲乙", "nm:000000000010"), "extra": 1}), "keys"),
    (_names({**name("甲乙", "nm:000000000010"), "kind": "event"}), "does not belong"),
    (_names(name("約翰福音", "nm:000000000010")), "duplicate surface"),
    (_names(name("甲", "nm:000000000010")), "shorter than 2 but routable"),
    (_names({**name("甲乙", "nm:000000000010"), "routable": 1}), "true or false"),
    (_names({**name("甲乙", "nm:000000000010"), "provenance_class": "external_legacy"}),
     "legacy provenance"),
    ({"header": {"retire_by": "R2"}}, "legacy provenance"),
    (_names(name("甲乙", "nm:000000000010", "Divine")), "route_types"),
    ({"events": [event("甲乙", "event:jiayi", "甲乙")]}, "not an event id"),
    ({"books": [book("甲乙", "xyz", "甲乙")]}, "unknown book"),
    ({"exclusions": [exclusion("何提", "如何把")]}, "does not contain"),
    ({"names": "not a list"}, "names: expected a list"),
    (_names({**name("甲乙", "nm:000000000010"), "targets": [{"ref": "nm:1"}]}), "keys"),
])
def test_malformed_lexicons_are_refused(override, message):
    with pytest.raises(RoutingLexiconError, match=message):
        routing.parse_lexicon(_doc(**override))


def test_an_r1_lexicon_is_refused_by_its_schema():
    r1 = {"schema": "ragdata.routing_lexicon.v1", "variant": "legacy", "header": {},
          "persons": [], "places": [], "events": [], "books": []}

    with pytest.raises(RoutingLexiconError, match="schema must be ragdata.routing_lexicon.v2"):
        routing.parse_lexicon(r1)


def test_unreadable_file_is_refused(tmp_path):
    path = tmp_path / "lex.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RoutingLexiconError, match="unreadable"):
        routing.load_lexicon(path)


# ------------------------------------------------------------------ query_aliases.json

ALIAS = {"alias_id": "qa.001", "surface": "古列", "target": "塞魯士",
         "target_ref": "nm:f64cf0ccb922", "provenance_class": "external_query",
         "source": "CUNP", "note": "RCUV 作塞魯士"}


def _aliases(*rows, **override):
    return {"schema": routing.QUERY_ALIASES_SCHEMA, "kg0": "kg0@14e68c8344b1",
            "registry": "query_aliases@000000000000", "aliases": list(rows), **override}


def test_query_aliases_parse_and_may_be_empty():
    [alias] = routing.parse_query_aliases(_aliases(ALIAS))

    assert (alias.surface, alias.target_ref) == ("古列", "nm:f64cf0ccb922")
    assert routing.parse_query_aliases(_aliases()) == ()


@pytest.mark.parametrize("doc, message", [
    (_aliases(ALIAS, schema="other"), "schema"),
    (_aliases(ALIAS, extra=1), "keys"),
    (_aliases({**ALIAS, "extra": 1}), "keys"),
    (_aliases({**ALIAS, "note": ""}), "note"),
    (_aliases({**ALIAS, "provenance_class": "external_legacy"}), "legacy provenance"),
    ([], "schema"),
])
def test_malformed_query_aliases_are_refused(doc, message):
    with pytest.raises(RoutingLexiconError, match=message):
        routing.parse_query_aliases(doc)
