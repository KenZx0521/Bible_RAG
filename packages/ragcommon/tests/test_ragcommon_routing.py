import json

import pytest

from ragcommon import routing
from ragcommon.routing import RoutingLexiconError

PROV = {"provenance_class": "external_legacy", "source": "test", "note": "n", "retire_by": "R2"}


def _named(canonical, *aliases):
    return {"canonical": canonical, "aliases": list(aliases), **PROV}


def _doc(**override):
    doc = {
        "schema": routing.SCHEMA, "variant": "legacy",
        "header": {"provenance_class": "external_legacy", "retire_by": "R2"},
        "persons": [_named("保羅", "保羅", "掃羅"), _named("掃羅", "掃羅"), _named("大衛", "大衛"),
                    _named("約翰", "約翰")],
        "places": [_named("耶路撒冷", "耶路撒冷"), _named("撒馬利亞", "撒馬利亞", "撒瑪利亞")],
        "events": [{"term": t, **PROV} for t in ("復活", "五旬節", "受洗", "洗禮")],
        "books": [{"name": n, "book_id": b, "full_name": f, **PROV} for n, b, f in (
            ("約翰一書", "1jn", "約翰一書"), ("約翰福音", "jhn", "約翰福音"), ("約壹", "1jn", "約翰一書"),
            ("約翰", "jhn", "約翰福音"), ("約", "jhn", "約翰福音"))],
    }
    doc.update(override)
    return doc


def test_persons_match_like_entity_dicts_longest_alias_first_ties_in_file_order():
    lex = routing.parse_lexicon(_doc())
    # 保羅 (max alias 2) precedes 掃羅 and 大衛 (also 2): equal keys keep file order
    assert lex.match_persons("大衛和掃羅") == ["保羅", "掃羅", "大衛"]
    assert lex.match_persons("沒有人名") == []


def test_places_match_any_alias_once():
    lex = routing.parse_lexicon(_doc())
    assert lex.match_places("撒瑪利亞與撒馬利亞，耶路撒冷") == ["耶路撒冷", "撒馬利亞"]


def test_events_sorted_by_length_then_codepoint():
    lex = routing.parse_lexicon(_doc())
    assert lex.match_events("五旬節受洗後復活的洗禮") == ["五旬節", "受洗", "復活", "洗禮"]


def test_books_skip_single_characters_and_repeat_books():
    lex = routing.parse_lexicon(_doc())
    assert lex.match_books("約翰一書與約翰福音、約壹") == ["約翰一書", "約翰福音"]
    assert lex.match_books("約") == []
    assert lex.count_books("約翰福音和約翰") == 1


def test_render_is_canonical_and_round_trips():
    doc = _doc()
    data = routing.render_lexicon(doc)
    assert data.endswith(b"\n")
    assert json.loads(data) == doc
    assert routing.render_lexicon(json.loads(data)) == data


def test_load_lexicon_reads_a_file(tmp_path):
    path = tmp_path / "lex.json"
    path.write_bytes(routing.render_lexicon(_doc()))
    assert routing.load_lexicon(path).match_persons("約翰") == ["約翰"]


@pytest.mark.parametrize("override, message", [
    ({"schema": "other"}, "schema"),
    ({"persons": [{"canonical": "甲", "aliases": [], **PROV}]}, "aliases"),
    ({"persons": [{"canonical": "甲", "aliases": ["甲"]}]}, "provenance_class"),
    ({"events": [{"term": "", **PROV}]}, "term"),
    ({"books": [{"name": "約", "book_id": "xyz", "full_name": "約", **PROV}]}, "book_id"),
    ({"places": "not a list"}, "places"),
    ({"extra": 1}, "keys"),
])
def test_malformed_lexicons_are_refused(override, message):
    with pytest.raises(RoutingLexiconError, match=message):
        routing.parse_lexicon(_doc(**override))


def test_unreadable_file_is_refused(tmp_path):
    path = tmp_path / "lex.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RoutingLexiconError, match="unreadable"):
        routing.load_lexicon(path)
