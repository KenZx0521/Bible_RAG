"""validate_kg on the 1B cross-reference provenance (W1 stream 1B).

After 1B a curated CROSS_REFERENCES edge is one row per pericope pair that
carries lists: curated_sources, the supplementary anchors (supp_anchors,
'heb 1:5>psa 2:7') and the markdown anchors (md_anchors, 'mrk 1:?>psa 2:7').
The gate reads them from a snapshot and from live Neo4j alike. The scalar
source_verses/target_verses of a graph built before 1B (prod until W1) stay
readable, so the same model scores both.

H8 then asks every edge for both flags (unflagged) and for flags that agree
with the evidence they summarise (flag_mismatch): curated with
curated_sources, tsk with votes.

R4 judges each supplementary anchor against the edge's two pericopes, both
by its first verse (misaligned) and by every verse (misaligned_any_verse),
and counts the anchors it cannot read (unparsed). A graph built before 1B has
no anchors, so R4 falls back to its legacy scalars.

Shared pieces are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import re

import pytest

import validate_kg as vk
from _validate_kg_helpers import SHIPPED_BASELINE, append_row, edit_rows, measure, read_rows, write_rows
# snap is a pytest fixture: importing it is what makes it available here.
from _validate_kg_helpers import snap  # noqa: F401
from kg_validate.model import _LIVE_QUERIES

PROVENANCE_LISTS = ("curated_sources", "supp_anchors", "md_anchors")
LEGACY_SCALARS = ("source_verses", "target_verses")
SUPP, MD, TSK = ("heb:1:1", "psa:2:0"), ("mrk:1:0", "psa:2:0"), ("gen:22:0", "heb:1:1")
H8_METRICS = ("no_provenance", "unflagged", "flag_mismatch")
R4_METRICS = ("misaligned", "misaligned_any_verse", "unparsed")
NEW_TSK = {"source_id": "exo:1:0", "target_id": "gen:22:0", "source": "tsk", "votes": 3}


def _lists(x: vk.XRef) -> tuple:
    return tuple(getattr(x, name) for name in PROVENANCE_LISTS)


def _h8(snap) -> tuple:
    return tuple(measure(snap)["H8"].metrics[name] for name in H8_METRICS)


def _row(pair: tuple[str, str]):
    return lambda r: (r["source_id"], r["target_id"]) == pair


def test_snapshot_reads_provenance_lists(snap):
    xrefs = {(x.src, x.tgt): x for x in vk.load_snapshot(snap).xrefs}
    assert _lists(xrefs[SUPP]) == (["supplementary"], ["heb 1:5>psa 2:7"], None)
    assert _lists(xrefs[MD]) == (["markdown"], None, ["mrk 1:?>psa 2:7"])
    assert _lists(xrefs[TSK]) == (None, None, None)  # a pure TSK edge has no curated provenance
    # a 1B row has no legacy scalars: R4 reads its anchors (prod before W1: test_r4_legacy_fields_fallback)
    assert (xrefs[SUPP].source_verses, xrefs[SUPP].target_verses) == (None, None)


def test_write_snapshot_round_trips_new_fields(snap, tmp_path):
    kg = vk.load_snapshot(snap)
    vk.write_snapshot(kg, tmp_path / "dumped")
    rows = {(r["source_id"], r["target_id"]): r
            for r in read_rows(tmp_path / "dumped" / "cross_references.jsonl")}
    assert all(set(PROVENANCE_LISTS + LEGACY_SCALARS) <= set(row) for row in rows.values())
    assert rows[SUPP]["supp_anchors"] == ["heb 1:5>psa 2:7"]
    assert rows[MD]["md_anchors"] == ["mrk 1:?>psa 2:7"]
    assert vk.load_snapshot(tmp_path / "dumped").xrefs == kg.xrefs


def test_live_query_selects_new_fields():
    cypher = _LIVE_QUERIES["xrefs"]
    for name in PROVENANCE_LISTS + LEGACY_SCALARS:
        assert re.search(rf"\br\.{name} AS {name}\b", cypher), name


# ---------------------------------------------------------------------------
# H8: both flags on every edge, each agreeing with its evidence
# ---------------------------------------------------------------------------

def test_clean_fixture_h8_zero(snap):
    # the curated rows carry curated_sources (1B-C8a), the TSK row its votes
    assert _h8(snap) == (0, 0, 0)


@pytest.mark.parametrize("flags", [{"curated": None, "tsk": True}, {"curated": False, "tsk": None}],
                         ids=["curated_none", "tsk_none"])
def test_h8_unflagged(snap, flags):
    # votes, so not no_provenance; one flag missing, the other agrees with the evidence
    append_row(snap / "cross_references.jsonl", {**NEW_TSK, **flags})
    assert _h8(snap) == (0, 1, 0)
    res = measure(snap)["H8"]
    assert res.detail["by_source"]["unflagged"] == {"tsk": 1}
    assert res.samples == [{"unflagged": ["exo:1:0->gen:22:0"]}]


@pytest.mark.parametrize("pair,changes", [
    (SUPP, {"curated_sources": None}),             # curated=true, nothing says where from
    (SUPP, {"curated_sources": []}),
    (TSK, {"curated_sources": ["markdown"]}),      # curated=false over a curated source
], ids=["sources_none", "sources_empty", "sources_on_uncurated"])
def test_h8_flag_mismatch_curated_without_sources(snap, pair, changes):
    edit_rows(snap / "cross_references.jsonl", _row(pair), **changes)
    assert _h8(snap) == (0, 0, 1)


@pytest.mark.parametrize("pair,changes", [
    (TSK, {"votes": None}),                        # tsk=true, no votes
    (MD, {"votes": 21}),                           # tsk=false over TSK votes
    (TSK, {"votes": None, "curated_sources": ["markdown"]}),  # both flags wrong: one edge
], ids=["votes_none", "votes_on_non_tsk", "both_flags"])
def test_h8_flag_mismatch_tsk_without_votes(snap, pair, changes):
    edit_rows(snap / "cross_references.jsonl", _row(pair), **changes)
    assert _h8(snap) == (0, 0, 1)
    res = measure(snap)["H8"]
    assert res.detail["by_source"]["flag_mismatch"] == {"tsk" if pair == TSK else "markdown": 1}
    assert res.samples == [{"flag_mismatch": [f"{pair[0]}->{pair[1]}"]}]


def test_shipped_h8_records_the_new_metrics(snap):
    # the gate scores only the metrics the baseline names: a metric missing
    # from h.json would be measured and never compared. Values are
    # measurements (--ratchet moves them), so only the design is pinned.
    report = vk.evaluate(measure(snap), vk.load_baseline(SHIPPED_BASELINE))
    assert list(report["checks"]["H8"]["metrics"]) == list(H8_METRICS)
    spec = next(c for c in vk.load_baseline(SHIPPED_BASELINE)["checks"] if c["id"] == "H8")
    for name, m in spec["metrics"].items():
        assert m["value"] is not None and (m["direction"], m["tolerance"], m["target"]) == ("down", 0, 0), name


# ---------------------------------------------------------------------------
# R4: each supplementary anchor judged against the edge's pericopes
# ---------------------------------------------------------------------------

def _r4(snap) -> tuple:
    return tuple(measure(snap)["R4"].metrics[name] for name in R4_METRICS)


def _anchors(snap, *anchors: str) -> None:
    edit_rows(snap / "cross_references.jsonl", _row(SUPP), supp_anchors=list(anchors))


def _legacy_supp_row(source_verses, target_verses) -> dict:
    # a supplementary edge as prod holds it before W1: no flags, no lists
    return {"source_id": SUPP[0], "target_id": SUPP[1], "source": "supplementary", "votes": None,
            "source_verses": source_verses, "target_verses": target_verses}


def test_clean_fixture_r4_zero(snap):
    # the fixture's supplementary row has its anchor and no legacy scalars
    assert _r4(snap) == (0, 0, 0)
    assert measure(snap)["R4"].detail == {"supplementary": 1, "legacy_fields": 0}


def test_r4_anchor_wrong_pericope(snap):
    _anchors(snap, "heb 1:3>psa 2:7")  # heb 1:3 is in heb:1:0 (1-4), the edge starts at heb:1:1 (5-14)
    assert _r4(snap) == (1, 1, 0)
    assert measure(snap)["R4"].samples == [{"misaligned": ["heb:1:1->psa:2:0 heb 1:3>psa 2:7"]},
                                           {"misaligned_any_verse": ["heb:1:1->psa:2:0 heb 1:3>psa 2:7"]}]


def test_r4_fanout_anchor_aligned(snap):
    # one definition, rev 18:2-8 > jer 51:6-9,45, resolves to two pericope
    # pairs (1B-C3b); each edge keeps the part of the anchor that lands on it
    for pid, verses in (("rev:18:0", "1-24"), ("jer:51:0", "1-14"), ("jer:51:5", "41-49")):
        append_row(snap / "pericopes.jsonl", {"id": pid, "book_id": pid.split(":")[0], "verse_range": verses})
    for tgt, anchor in (("jer:51:0", "rev 18:2-8>jer 51:6-9"), ("jer:51:5", "rev 18:2-8>jer 51:45")):
        append_row(snap / "cross_references.jsonl",
                   {"source_id": "rev:18:0", "target_id": tgt, "source": "supplementary", "curated": True,
                    "tsk": False, "votes": None, "curated_sources": ["supplementary"], "supp_anchors": [anchor]})
    assert _r4(snap) == (0, 0, 0)
    assert measure(snap)["R4"].detail["supplementary"] == 3


@pytest.mark.parametrize("anchor", ["heb 2:5>psa 2:7", "heb 1:5>psa 3:7", "rom 1:5>psa 2:7"],
                         ids=["source_chapter", "target_chapter", "source_book"])
def test_r4_wrong_chapter_anchor(snap, anchor):
    # the verse numbers fit the pericopes' ranges; the chapter or book does not
    _anchors(snap, anchor)
    assert _r4(snap) == (1, 1, 0)


@pytest.mark.parametrize("anchors", [["heb 1:5>psa 2:7-13"], ["heb 1:5-15>psa 2:7"],
                                     ["heb 1:5>psa 2:7", "heb 1:5>psa 2:7,13"]],
                         ids=["target_range", "source_range", "second_anchor"])
def test_r4_any_verse_only(snap, anchors):
    # the first verse is inside (psa:2:0 is 1-12, heb:1:1 5-14), a later one is not
    _anchors(snap, *anchors)
    assert _r4(snap) == (0, 1, 0)


@pytest.mark.parametrize("source_verses,target_verses,expected", [
    ("5", "7", (0, 0, 0)),
    ("5", "7, 13", (0, 1, 0)),     # first target verse inside, the last outside
    ("5", "13", (1, 1, 0)),
    (None, "7", (0, 0, 1)),        # nothing to judge
], ids=["aligned", "any_verse", "first_verse", "missing"])
def test_r4_legacy_fields_fallback(snap, source_verses, target_verses, expected):
    rows = [r for r in read_rows(snap / "cross_references.jsonl") if (r["source_id"], r["target_id"]) != SUPP]
    write_rows(snap / "cross_references.jsonl", rows + [_legacy_supp_row(source_verses, target_verses)])
    assert _r4(snap) == expected
    assert measure(snap)["R4"].detail == {"supplementary": 1, "legacy_fields": 1}


@pytest.mark.parametrize("anchors", [["heb 1:5 psa 2:7"], ["heb 1:5>psa 2:?"], ["heb 1:5>psa 2:7>psa 2:8"],
                                     ["heb1:5>psa 2:7"], ["heb 1:5>psa 2:7", "heb 1:5"], []],
                         ids=["no_arrow", "unknown_verse", "three_ends", "no_space", "second_anchor", "empty"])
def test_r4_unparsed_anchor(snap, anchors):
    # an empty list falls back to the legacy scalars, which a 1B row lacks
    _anchors(snap, *anchors)
    assert _r4(snap) == (0, 0, 1)


def test_r4_unparsed_when_an_end_pericope_is_unknown(snap):
    edit_rows(snap / "cross_references.jsonl", _row(SUPP), target_id="psa:3:0")  # not in pericopes.jsonl
    assert _r4(snap) == (0, 0, 1)


def test_r4_judges_supplementary_anchors_of_a_markdown_edge(snap):
    # a pair both sources define keeps source 'markdown'; its supplementary
    # anchors are judged, its markdown anchors are not (XREF-5, 2D)
    edit_rows(snap / "cross_references.jsonl", _row(MD), curated_sources=["markdown", "supplementary"],
              supp_anchors=["mrk 1:9>psa 2:7"])  # mrk:1:0 is 1-8
    assert _r4(snap) == (1, 1, 0)
    assert measure(snap)["R4"].detail["supplementary"] == 2


def test_shipped_r4_records_the_new_metrics(snap):
    report = vk.evaluate(measure(snap), vk.load_baseline(SHIPPED_BASELINE))
    assert list(report["checks"]["R4"]["metrics"]) == list(R4_METRICS)
    spec = next(c for c in vk.load_baseline(SHIPPED_BASELINE)["checks"] if c["id"] == "R4")
    for name, m in spec["metrics"].items():
        assert m["value"] is not None and (m["direction"], m["tolerance"], m["target"]) == ("down", 0, 0), name
