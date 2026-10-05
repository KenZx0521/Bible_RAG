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

Shared pieces are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import re

import pytest

import validate_kg as vk
from _validate_kg_helpers import SHIPPED_BASELINE, append_row, edit_rows, measure, read_rows
# snap is a pytest fixture: importing it is what makes it available here.
from _validate_kg_helpers import snap  # noqa: F401
from kg_validate.model import _LIVE_QUERIES

PROVENANCE_LISTS = ("curated_sources", "supp_anchors", "md_anchors")
LEGACY_SCALARS = ("source_verses", "target_verses")
SUPP, MD, TSK = ("heb:1:1", "psa:2:0"), ("mrk:1:0", "psa:2:0"), ("gen:22:0", "heb:1:1")
H8_METRICS = ("no_provenance", "unflagged", "flag_mismatch")
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
    # the legacy scalars stay: R4 reads only them until 1B-C8c, and prod before W1 has nothing else
    assert (xrefs[SUPP].source_verses, xrefs[SUPP].target_verses) == ("5", "7")


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
