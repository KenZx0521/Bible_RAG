"""validate_kg on the 1B cross-reference provenance (W1 stream 1B).

After 1B a curated CROSS_REFERENCES edge is one row per pericope pair that
carries lists: curated_sources, the supplementary anchors (supp_anchors,
'heb 1:5>psa 2:7') and the markdown anchors (md_anchors, 'mrk 1:?>psa 2:7').
The gate reads them from a snapshot and from live Neo4j alike. The scalar
source_verses/target_verses of a graph built before 1B (prod until W1) stay
readable, so the same model scores both.

Shared pieces are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import re

import validate_kg as vk
from _validate_kg_helpers import read_rows
# snap is a pytest fixture: importing it is what makes it available here.
from _validate_kg_helpers import snap  # noqa: F401
from kg_validate.model import _LIVE_QUERIES

PROVENANCE_LISTS = ("curated_sources", "supp_anchors", "md_anchors")
LEGACY_SCALARS = ("source_verses", "target_verses")
SUPP, MD, TSK = ("heb:1:1", "psa:2:0"), ("mrk:1:0", "psa:2:0"), ("gen:22:0", "heb:1:1")


def _lists(x: vk.XRef) -> tuple:
    return tuple(getattr(x, name) for name in PROVENANCE_LISTS)


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
