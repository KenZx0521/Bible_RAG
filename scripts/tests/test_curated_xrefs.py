"""Curated cross references in verse coordinates (bible_chunking/curated_xrefs.py).

Supplementary definitions name both ends as 'book chapter:verses'. Each end
resolves verse by verse through a (book, chapter, verse) → pericope map (the
keys of import_tsk_crossrefs.build_verse_map), so a definition whose verses
straddle a pericope boundary yields one anchor per touched pericope pair,
each carrying only that pair's verses (X4), at most MAX_FANOUT of them. Every
problem is an error; resolve_definitions collects all of them so Step 0 can
stop before writing anything.
"""

from types import SimpleNamespace

import pytest

from bible_chunking.curated_xrefs import (
    MAX_FANOUT, Anchor, Coord, XrefDefinitionError, build_anchors, format_anchor,
    format_verses, parse_anchor, parse_coord, resolve_definitions, resolve_span,
    verse_map_from_pericopes,
)


def span(book, chapter, lo, hi, pid) -> dict:
    return {(book, chapter, v): pid for v in range(lo, hi + 1)}


# rev 18 is one pericope; jer 51:6-9 and 51:45 sit in different pericopes
# (as on the real data: jer:51:0 and jer:51:5); mat 4 is split at 12/13.
VMAP = {
    **span("rev", 18, 1, 24, "rev:18:0"),
    **span("jer", 51, 1, 14, "jer:51:0"), **span("jer", 51, 15, 44, "jer:51:1"),
    **span("jer", 51, 45, 64, "jer:51:5"),
    **span("mat", 4, 1, 12, "mat:4:0"), **span("mat", 4, 13, 25, "mat:4:1"),
    **span("isa", 9, 1, 2, "isa:9:0"), **span("isa", 9, 3, 7, "isa:9:1"),
    **span("isa", 9, 8, 21, "isa:9:2"),
}


def define(src, tgt, ref_type="quotation", description="d", tsk_exempt=None):
    return SimpleNamespace(src=src, tgt=tgt, ref_type=ref_type,
                           description=description, tsk_exempt=tsk_exempt)


@pytest.mark.parametrize("text, expected", [
    ("rev 19:5", Coord("rev", 19, (5,))),
    ("rev 19:11-16", Coord("rev", 19, (11, 12, 13, 14, 15, 16))),
    ("mat 4:14,27", Coord("mat", 4, (14, 27))),
    ("jer 51:6-9,45", Coord("jer", 51, (6, 7, 8, 9, 45))),
    ("1pe 2:6", Coord("1pe", 2, (6,))),
])
def test_parse_coord_valid(text, expected):
    assert parse_coord(text) == expected


@pytest.mark.parametrize("text, reason", [
    ("", "expected 'book chapter:verses'"),
    ("rev 19", "expected 'book chapter:verses'"),
    ("rev x:1", "expected 'book chapter:verses'"),
    ("rev 19:", "no verses"),
    ("rev 19:16-11", "descending range '16-11'"),
    ("rev 19:a", "'a' is not n or a-b"),
    ("rev 19:1,", "'' is not n or a-b"),
    ("rev 19:1 - 2", "a space inside the verses"),
    ("rev 19:1-20:2", "crosses a chapter (one chapter per end)"),
    ("rev 19:1-3,2", "a verse is listed twice"),
])
def test_parse_coord_rejects(text, reason):
    with pytest.raises(XrefDefinitionError) as err:
        parse_coord(text)
    assert isinstance(err.value, ValueError)
    assert err.value.errors == (f"{text!r}: {reason}",)


def test_format_roundtrip():
    assert format_verses([6, 7, 8, 9]) == "6-9"
    assert format_verses([14, 27]) == "14,27"
    assert format_verses((45, 6, 7, 8, 9)) == "6-9,45"
    for text in ("rev 18:2-8>jer 51:45", "rev 18:2-8>jer 51:6-9,45", "1pe 2:6>isa 28:16"):
        src, tgt = parse_anchor(text)
        assert format_anchor(src, tgt) == text
    assert parse_anchor("rev 18:2-8>jer 51:45") == (
        Coord("rev", 18, (2, 3, 4, 5, 6, 7, 8)), Coord("jer", 51, (45,)))
    for bad in ("rev 18:2", "rev 18:2>jer 51:4>isa 1:1", "rev 18:2>jer 51"):
        with pytest.raises(XrefDefinitionError):
            parse_anchor(bad)


def test_resolve_single_pericope():
    assert resolve_span(parse_coord("rev 18:2-8"), VMAP) == {"rev:18:0": (2, 3, 4, 5, 6, 7, 8)}
    anchors = build_anchors("rev 18:2", "jer 51:6", VMAP, ref_type="allusion",
                            description="巴比倫傾倒了")
    assert anchors == [Anchor("rev:18:0", "jer:51:0", "rev 18:2>jer 51:6", "allusion",
                              "巴比倫傾倒了", None)]


def test_resolve_fanout_splits_verses():
    target = resolve_span(parse_coord("jer 51:6-9,45"), VMAP)
    assert target == {"jer:51:0": (6, 7, 8, 9), "jer:51:5": (45,)}
    assert list(target) == ["jer:51:0", "jer:51:5"]  # first-seen order
    anchors = build_anchors("rev 18:2-8", "jer 51:6-9,45", VMAP, ref_type="allusion",
                            description="巴比倫大城傾倒了", tsk_exempt="reason")
    assert [(a.start, a.end, a.text) for a in anchors] == [
        ("rev:18:0", "jer:51:0", "rev 18:2-8>jer 51:6-9"),
        ("rev:18:0", "jer:51:5", "rev 18:2-8>jer 51:45"),
    ]
    assert {(a.ref_type, a.description, a.tsk_exempt) for a in anchors} == {
        ("allusion", "巴比倫大城傾倒了", "reason")}


def test_missing_verse_is_an_error_listing_all():
    with pytest.raises(XrefDefinitionError) as err:
        resolve_span(parse_coord("rev 18:20-26,30"), VMAP)
    assert err.value.errors == ("'rev 18:20-26,30': verses 25-26,30 are in no pericope",)
    # both ends are checked before giving up
    with pytest.raises(XrefDefinitionError) as err:
        build_anchors("rev 18:25", "jer 51:70", VMAP, ref_type="allusion", description="d")
    assert err.value.errors == ("'rev 18:25': verses 25 are in no pericope",
                                "'jer 51:70': verses 70 are in no pericope")
    with pytest.raises(XrefDefinitionError) as err:
        build_anchors("gen 99:1", "rev 18:x", VMAP, ref_type="allusion", description="d")
    assert len(err.value.errors) == 2


def test_fanout_over_3_is_an_error():
    assert MAX_FANOUT == 3
    # 1 × 3 = 3 is allowed
    assert len(build_anchors("rev 18:2", "isa 9:1,3,8", VMAP, ref_type="allusion",
                             description="d")) == 3
    # 2 × 2 = 4 is not
    with pytest.raises(XrefDefinitionError) as err:
        build_anchors("mat 4:12-13", "isa 9:2-3", VMAP, ref_type="quotation", description="d")
    message = str(err.value)
    assert "4 pericope pairs" in message and "mat:4:0" in message and "isa:9:1" in message


def test_resolve_definitions_collects_all_errors():
    defs = [
        define("rev 18:2-8", "jer 51:6-9,45"),          # 2 anchors
        define("rev 18:2", "jer 51:99"),                # missing verse
        define("rev 18:2", "jer 51:1-52:2"),            # cross-chapter
        define("mat 4:12-13", "isa 9:2-3"),             # fan-out 4
        define("mat 4:15-16", "isa 9:1-2", tsk_exempt="r"),  # 1 anchor
    ]
    anchors, errors = resolve_definitions(defs, VMAP)
    assert [a.text for a in anchors] == [
        "rev 18:2-8>jer 51:6-9", "rev 18:2-8>jer 51:45", "mat 4:15-16>isa 9:1-2"]
    assert anchors[-1].tsk_exempt == "r"
    assert len(errors) == 3
    assert [e.split(":")[0] for e in errors] == ["definition 1", "definition 2", "definition 3"]
    assert "'jer 51:99'" in errors[0] and "'jer 51:1-52:2'" in errors[1]
    assert "4 pericope pairs" in errors[2]
    assert resolve_definitions(defs[:1], VMAP)[1] == []


def test_verse_map_from_pericopes_expands_ranges():
    records = [
        {"id": "gen:1:0", "metadata": {"book_id": "gen", "chapter_num": 1},
         "verses": [{"num": "1-2", "text": "x"}, {"num": "3", "text": "y"}]},
        {"id": "gen:1:1", "metadata": {"book_id": "gen", "chapter_num": 1},
         "verses": [{"num": "4", "text": "z"}]},
    ]
    assert verse_map_from_pericopes(records) == {
        ("gen", 1, 1): "gen:1:0", ("gen", 1, 2): "gen:1:0", ("gen", 1, 3): "gen:1:0",
        ("gen", 1, 4): "gen:1:1",
    }
