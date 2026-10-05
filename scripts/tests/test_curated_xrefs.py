"""Curated cross references in verse coordinates (bible_chunking/curated_xrefs.py).

Supplementary definitions name both ends as 'book chapter:verses'. Each end
resolves verse by verse through a (book, chapter, verse) → pericope map (the
keys of import_tsk_crossrefs.build_verse_map), so a definition whose verses
straddle a pericope boundary yields one anchor per touched pericope pair,
each carrying only that pair's verses (X4), at most MAX_FANOUT of them. Every
problem is an error; resolve_definitions collects all of them so Step 0 can
stop before writing anything.

aggregate_curated then folds the markdown refs and the supplementary anchors
into one CROSS_REFERENCES row per (start, end) pair (XREF-1(b): Step 5's MERGE
used to keep only the last row of a pair), with the curated/tsk flags and the
per-source lists. Neo4j cannot store a list holding null, so no value and no
list element may be None. A markdown ref's anchor marks with '?' whatever
CrossRefParser did not read from the ref text (XREF-5, fixed by 2D).
"""

from types import SimpleNamespace

import pytest

from bible_chunking.curated_xrefs import (
    MAX_FANOUT, Anchor, Coord, XrefDefinitionError, aggregate_curated, build_anchors,
    format_anchor, format_verses, markdown_anchor, parse_anchor, parse_coord,
    resolve_definitions, resolve_span, verse_map_from_pericopes,
)
from bible_chunking.markdown_parser import CrossRefParser


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


@pytest.mark.parametrize("src, tgt, loop", [
    ("rev 18:2", "rev 18:3", "rev:18:0"),
    ("isa 9:1", "isa 9:2-3", "isa:9:0"),  # one of two pairs loops: the whole definition fails
])
def test_both_ends_in_one_pericope_is_an_error(src, tgt, loop):
    # a self-loop: TSK drops them (aggregate_tsk), so no curated edge may be one
    with pytest.raises(XrefDefinitionError) as err:
        build_anchors(src, tgt, VMAP, ref_type="allusion", description="d")
    assert err.value.errors == (f"{src!r}>{tgt!r}: both ends in {loop}",)
    anchors, errors = resolve_definitions([define(src, tgt)], VMAP)
    assert (anchors, errors) == ([], [f"definition 0: {src!r}>{tgt!r}: both ends in {loop}"])


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


def md_row(start, end, ref_text, md_anchor) -> dict:
    return {"start": start, "end": end, "ref_text": ref_text, "md_anchor": md_anchor}


HEB_3_7 = Anchor("heb:3:1", "psa:95:0", "heb 3:7-11>psa 95:7-11", "quotation",
                 "你們今日若聽他的話就不可硬著心", None)
HEB_3_15 = Anchor("heb:3:1", "psa:95:0", "heb 3:15>psa 95:7-8", "quotation", "不可硬著心", None)


def md_anchor_of(src_book, src_ch, ref_text) -> str:
    """The anchor of one markdown ref text as CrossRefParser reads it."""
    (ref,) = CrossRefParser.parse(ref_text)
    return markdown_anchor(src_book, src_ch, ref)


def test_markdown_anchor_formats():
    # markdown refs are pericope-level: the source verse is always unknown
    assert md_anchor_of("gen", 5, "代上1‧1－4") == "gen 5:?>1ch 1:1-4"
    assert md_anchor_of("mrk", 1, "詩2‧7") == "mrk 1:?>psa 2:7"
    ref = SimpleNamespace(book_id="psa", chapter=2, verse_start=7, verse_end=None,
                          reference_text="詩2‧7")
    assert markdown_anchor("mrk", 1, ref) == "mrk 1:?>psa 2:7"
    for verse_end in (None, 9):
        ref = SimpleNamespace(book_id="isa", chapter=7, verse_start=None,
                              verse_end=verse_end, reference_text="賽7")
        assert markdown_anchor("mat", 1, ref) == "mat 1:?>isa 7:?"


def test_markdown_anchor_cross_chapter_end_is_unknown():
    # The parser stops at '－12' of 代下11‧5－12‧15 and keeps the end chapter in
    # verse_end, so the end verse is unknown whether the chapter number is below
    # (申2‧26－3‧11), above or equal to (代下15‧16－16‧6) the start verse (crit#8)
    assert md_anchor_of("num", 21, "申2‧26－3‧11") == "num 21:?>deu 2:26-?"
    assert md_anchor_of("1ki", 14, "代下11‧5－12‧15") == "1ki 14:?>2ch 11:5-?"
    assert md_anchor_of("1ki", 15, "代下15‧16－16‧6") == "1ki 15:?>2ch 15:16-?"
    # a descending range with nothing after it is still not stored as one
    assert md_anchor_of("num", 21, "申2‧26－3") == "num 21:?>deu 2:26-?"


def test_markdown_anchor_marks_unread_ranges():
    # the parser reads only the first range of 王下25‧18－21，27－30
    assert md_anchor_of("jer", 52, "王下25‧18－21，27－30") == "jer 52:?>2ki 25:18-21,?"
    assert md_anchor_of("luk", 12, "太6‧25－34，19－21") == "luk 12:?>mat 6:25-34,?"


def test_markdown_anchor_refuses_other_unread_text():
    with pytest.raises(XrefDefinitionError, match="創2‧4上"):
        md_anchor_of("exo", 20, "創2‧4上")


def test_two_supp_anchors_one_pair_aggregate():
    assert aggregate_curated([], [HEB_3_7, HEB_3_15]) == [{
        "start": "heb:3:1", "end": "psa:95:0", "type": "CROSS_REFERENCES",
        "properties": {
            "source": "supplementary", "curated": True, "tsk": False,
            "curated_sources": ["supplementary"],
            "supp_anchors": ["heb 3:7-11>psa 95:7-11", "heb 3:15>psa 95:7-8"],
            "supp_ref_types": ["quotation", "quotation"],
            "supp_descriptions": ["你們今日若聽他的話就不可硬著心", "不可硬著心"],
        },
    }]


def test_md_and_supp_same_pair():
    rows = aggregate_curated([md_row("heb:3:1", "psa:95:0", "詩95‧7－11", "heb 3:?>psa 95:7-11")],
                             [HEB_3_15])
    assert len(rows) == 1
    props = rows[0]["properties"]
    assert props["curated_sources"] == ["markdown", "supplementary"]
    assert props["source"] == "markdown"
    assert props["md_ref_texts"] == ["詩95‧7－11"]
    assert props["md_anchors"] == ["heb 3:?>psa 95:7-11"]
    assert props["supp_anchors"] == ["heb 3:15>psa 95:7-8"]
    assert props["supp_ref_types"] == ["quotation"]
    assert props["supp_descriptions"] == ["不可硬著心"]


def test_every_row_curated_true_tsk_false():
    md_rows = [md_row("mrk:1:0", "psa:2:0", "詩2‧7", "mrk 1:?>psa 2:7"),
               md_row("gen:5:0", "1ch:1:0", "代上1‧1－4", "gen 5:?>1ch 1:1-4")]
    rows = aggregate_curated(md_rows, [HEB_3_7, HEB_3_15])
    assert [(r["start"], r["end"]) for r in rows] == [
        ("gen:5:0", "1ch:1:0"), ("heb:3:1", "psa:95:0"), ("mrk:1:0", "psa:2:0")]
    assert {r["type"] for r in rows} == {"CROSS_REFERENCES"}
    assert all(r["properties"]["curated"] is True and r["properties"]["tsk"] is False
               for r in rows)
    # md-only rows carry no supp_* key and supp-only rows no md_* key
    assert [sorted(r["properties"]) for r in rows] == [
        ["curated", "curated_sources", "md_anchors", "md_ref_texts", "source", "tsk"],
        ["curated", "curated_sources", "source", "supp_anchors", "supp_descriptions",
         "supp_ref_types", "tsk"],
        ["curated", "curated_sources", "md_anchors", "md_ref_texts", "source", "tsk"],
    ]


def test_no_none_anywhere_and_lists_homogeneous():
    exempt = Anchor("rev:18:0", "jer:51:5", "rev 18:2-8>jer 51:45", "allusion", "巴比倫",
                    "TSK only points to jer 51:6-9")
    rows = aggregate_curated([md_row("rev:18:0", "jer:51:5", "耶51‧45", "rev 18:?>jer 51:45")],
                             [HEB_3_7, HEB_3_15, exempt])
    for row in rows:
        for key, value in row["properties"].items():
            assert value is not None, (row["start"], key)
            if isinstance(value, list):
                assert value and all(isinstance(item, str) for item in value), (row["start"], key)
    by_pair = {(r["start"], r["end"]): r["properties"] for r in rows}
    # tsk_exempt None is not stored; a reason lists only that anchor
    assert "supp_tsk_exempt_anchors" not in by_pair["heb:3:1", "psa:95:0"]
    assert by_pair["rev:18:0", "jer:51:5"]["supp_tsk_exempt_anchors"] == ["rev 18:2-8>jer 51:45"]
    # a None that would reach Step 5 is refused here, as an error Step 0 reports
    with pytest.raises(XrefDefinitionError, match="supp_descriptions"):
        aggregate_curated([], [HEB_3_15._replace(description=None)])
    with pytest.raises(XrefDefinitionError, match="md_ref_texts"):
        aggregate_curated([md_row("mrk:1:0", "psa:2:0", None, "mrk 1:?>psa 2:7")], [])
