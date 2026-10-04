"""A full rebuild must reproduce backend/data/event_registry.json (EV-06).

Offline version of docs/records/2026-10-04_kg_fix/events/a6_simulate_rebuild.py:
the graph a rebuild would hold is projected from output/ JSONL, the Step 10
curated overlays are replayed on it, and export_event_registry's pure core
(registry_from_rows, the same function build_registry feeds from Neo4j) turns
that projection into a registry, no database involved. The committed registry
has 33 events; with ON CREATE-only replay of the manual patch nodes the
projection drops to 31 (山上寶訓 loses 八福/登山寶訓, both 保羅敘述歸主 events
lose 保羅歸主), which is exactly the silent regression this guards against.

Replay order mirrors docs/build_database.md: Step 5 import → 10.2 generic
events → 10.4 backfill_head_events → 10.5 backfill_manual_patches. Steps that
cannot change Event names, aliases or MENTIONS (10.1 touches Person/Place/
Group only, 10.3 adds relation edges) are not modelled. The 10.5 node replay
is the script's own `overlay_nodes`; 10.2 and 10.4 are modelled here from the
scripts' constants, since their Cypher is not under test.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pytest

import backfill_manual_patches as bmp
import export_event_registry as exr
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output"
ENTITIES = OUTPUT / "entities.jsonl"
MENTIONS = OUTPUT / "entity_mentions.jsonl"
REGISTRY = ROOT / "backend" / "data" / "event_registry.json"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in (ENTITIES, MENTIONS, exr.BOOKS)),
    reason="output/ JSONL artifacts are not present (gitignored build products)",
)


def _pericope_of(source_id: str) -> str:
    # Verse (gen:1:0:v:3) and chunk (gen:1:0:0) mentions are anchored on the
    # parent pericope, as import_neo4j remaps verses and the registry query
    # walks Chunk → parent Pericope.
    return ":".join(source_id.split(":")[:3])


class Graph(NamedTuple):
    """What the registry export reads: props, type label and anchors per id."""

    props: dict[str, dict]
    labels: dict[str, str]
    anchors: dict[str, frozenset[str]]


def _step5_import() -> Graph:
    props: dict[str, dict] = {}
    labels: dict[str, str] = {}
    with ENTITIES.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            props[rec["entity_id"]] = {"canonical_name": rec.get("canonical_name", ""),
                                       "aliases": list(rec.get("aliases") or [])}
            labels[rec["entity_id"]] = rec["type"]

    anchors: dict[str, set[str]] = defaultdict(set)
    with MENTIONS.open(encoding="utf-8") as fh:
        for line in fh:
            if '"event:' not in line:
                continue
            rec = json.loads(line)
            if labels.get(rec["entity_id"]) == "Event":
                anchors[rec["entity_id"]].add(_pericope_of(rec["source_id"]))
    return Graph(props, labels, {eid: frozenset(a) for eid, a in anchors.items()})


def _with_anchors(anchors: dict, extra: dict[str, Iterable[str]]) -> dict:
    out = dict(anchors)
    for eid, pids in extra.items():
        out[eid] = out.get(eid, frozenset()) | frozenset(pids)
    return out


def _step10_2_generic_events(g: Graph) -> Graph:
    generic = set(GENERIC_EVENT_STOPLIST)
    props = {eid: p for eid, p in g.props.items()
             if not (g.labels.get(eid) == "Event" and p["canonical_name"] in generic)}
    return g._replace(props=props)


def _step10_4_head_events(g: Graph) -> Graph:
    props = dict(g.props)
    for eid, extra in ALIAS_INJECTIONS.items():
        node = props[eid]  # validate() aborts the script when a target is missing
        props[eid] = {**node, "aliases": bmp.merge_aliases(node["aliases"], extra,
                                                            node["canonical_name"])}
    for ev in NEW_EVENTS:
        # _CREATE_EVENT_CYPHER: MERGE by id, then SET name/aliases outright.
        props[ev["entity_id"]] = {**props.get(ev["entity_id"], {}),
                                  "canonical_name": ev["canonical_name"],
                                  "aliases": list(ev["aliases"])}
    labels = {**g.labels, **{ev["entity_id"]: "Event" for ev in NEW_EVENTS}}
    anchors = _with_anchors(g.anchors, {ev["entity_id"]: ev["anchors"] for ev in NEW_EVENTS})
    return Graph(props, labels, anchors)


def _step10_5_manual_patches(g: Graph) -> Graph:
    nodes, edges = bmp.load_patches(bmp.DEFAULT_PATCH_FILE)
    props = bmp.overlay_nodes(g.props, nodes)
    labels = {**{n["entity_id"]: next(l for l in n["labels"] if l != "Entity")
                 for n in nodes}, **g.labels}
    edge_anchors: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if labels.get(e["entity_id"]) == "Event":
            edge_anchors[e["entity_id"]].append(e["pericope_id"])
    return Graph(props, labels, _with_anchors(g.anchors, edge_anchors))


def _simulated_graph() -> Graph:
    graph = _step5_import()
    for step in (_step10_2_generic_events, _step10_4_head_events, _step10_5_manual_patches):
        graph = step(graph)
    return graph


def _anchor_rows(graph: Graph) -> list[dict]:
    """export_event_registry._ANCHOR_QUERY's rows, for every Event in the projection."""
    return [{"id": eid, "name": graph.props[eid]["canonical_name"],
             "aliases": graph.props[eid]["aliases"],
             "anchors": sorted(graph.anchors.get(eid, ()))}
            for eid in graph.props if graph.labels.get(eid) == "Event"]


@pytest.fixture(scope="module")
def rebuilt_registry():
    return exr.registry_from_rows(_anchor_rows(_simulated_graph()), exr.curated_event_ids(),
                                  exr.event_keywords(), exr.load_book_order())


@pytest.fixture(scope="module")
def committed_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_rebuild_keeps_all_33_registry_events(rebuilt_registry, committed_registry):
    assert len(committed_registry["events"]) == 33
    assert len(rebuilt_registry["events"]) == 33


def test_rebuild_reproduces_committed_registry_exactly(rebuilt_registry, committed_registry):
    rebuilt = exr._comparable(rebuilt_registry)
    committed = exr._comparable(committed_registry)

    # Per-event view first so a failure names the drifting events.
    got = {e["id"]: (e["triggers"], e["anchors"]) for e in rebuilt["events"]}
    want = {e["id"]: (e["triggers"], e["anchors"]) for e in committed["events"]}
    assert {eid: got.get(eid) for eid in want if got.get(eid) != want[eid]} == {}
    assert rebuilt == committed


def test_rebuild_renders_the_committed_file_byte_for_byte(rebuilt_registry, committed_registry):
    # Same layout, key order and escaping as the file the backend image ships;
    # only generated_at may differ, so it is taken from the committed file.
    stamped = {**rebuilt_registry, "generated_at": committed_registry["generated_at"]}

    assert exr.render_registry(stamped) == REGISTRY.read_text(encoding="utf-8")


@pytest.mark.parametrize("eid, trigger", [
    ("event:shanshangbaoxun", "八福"),
    ("event:shanshangbaoxun", "登山寶訓"),
    ("event:baoluoxushuguizhudejingguo", "保羅歸主"),
    ("event:baoluoxushuguizhujingguo", "保羅歸主"),
])
def test_extracted_curated_events_keep_their_triggers(rebuilt_registry, eid, trigger):
    events = {e["id"]: e for e in rebuilt_registry["events"]}

    assert eid in events
    assert trigger in events[eid]["triggers"]
