"""G-GRAPH: what the gate catches in a graph layer's rows."""

from __future__ import annotations

import copy
import json

import pytest

import mini_release
from ragdata.contract.registry import KG_EDGES, KG_META, KG_NODES
from ragdata.gates.graph import check_graph
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.gates.schema import check_schema
from ragdata.gates.runner import merge_files
from ragdata.kg.graph_build import build_graph
from ragdata.kg.graph_schema import meta_doc
from ragdata.store import read_layer


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("graph_gate"))


@pytest.fixture(scope="module")
def stored(mini):
    result = build_graph(*(mini.layers[k].path for k in ("text", "struct", "kg0", "events")),
                         mini.store, mini.root / "registries")
    assert result.passed
    return read_layer(result.layers["graph"].path)


@pytest.fixture(scope="module")
def snap(mini):
    layers = [read_layer(mini.layers[k].path) for k in ("text", "struct", "kg0", "events")]
    _, snapshot = check_schema(merge_files(layers), [d.layer for d in layers])
    return snapshot


def _person(pid, label, units):
    return {"kind": "Person", "id": pid, "props": {
        "label": label, "surfaces": [label], "kin_conflict": False, "mentions": len(units),
        "mention_units": list(units)}}


def _kin(rel, src, dst, units, provenance="pdf_rule", role="P"):
    return {"type": rel, "src_kind": "Person", "src": src, "dst_kind": "Person", "dst": dst,
            "props": {"role": role, "evidence_units": list(units), "patterns": ["begot"],
                      "provenance_class": provenance}}


def _rows(stored):
    """The mini graph plus three people and a parent edge the mini text can witness."""
    nodes = [*copy.deepcopy(stored.rows[KG_NODES]),
             _person("e000001", "掃羅", ["act.9.1"]), _person("e000002", "哥尼流", ["act.10.1"]),
             _person("e000003", "大馬士革", ["act.9.2"])]
    edges = [*copy.deepcopy(stored.rows[KG_EDGES]),
             _kin("PARENT_OF", "e000001", "e000002", ["act.9.1", "act.10.1"])]
    return nodes, edges


def _gate(nodes, edges, snap, meta=None):
    return check_graph(nodes, edges, meta or meta_doc(nodes, edges), snap)


def _red(result, text):
    assert not result.passed and result.hard
    assert any(text in d for d in result.details), result.details


def test_the_mini_graph_and_a_witnessed_kin_edge_pass(stored, snap):
    result = _gate(*_rows(stored), snap)
    assert result.passed, result.details


def test_an_edge_to_a_node_that_does_not_exist_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges.append(_kin("PARENT_OF", "e000001", "e000099", ["act.9.1"]))
    _red(_gate(nodes, edges, snap), "e000099")


def test_an_edge_whose_end_is_of_another_kind_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges.append({"type": "HAS_CHAPTER", "src_kind": "Verse", "src": "act.9.1", "dst_kind": "Chapter",
                  "dst": "act.9", "props": {}})
    _red(_gate(nodes, edges, snap), "HAS_CHAPTER")


def test_two_nodes_of_a_kind_with_one_id_are_red(stored, snap):
    nodes, edges = _rows(stored)
    nodes.append(_person("e000001", "掃羅", ["act.9.1"]))
    _red(_gate(nodes, edges, snap), "e000001")


def test_an_unknown_kind_or_type_is_red(stored, snap):
    nodes, edges = _rows(stored)
    nodes.append({"kind": "Planet", "id": "x", "props": {}})
    _red(_gate(nodes, edges, snap), "Planet")
    nodes, edges = _rows(stored)
    edges.append({"type": "ORBITS", "src_kind": "Person", "src": "e000001", "dst_kind": "Person", "dst": "e000002", "props": {}})
    _red(_gate(nodes, edges, snap), "ORBITS")


@pytest.mark.parametrize("kind_or_type, is_node", [
    ("Book", True), ("Chapter", True), ("Pericope", True), ("Passage", True), ("Verse", True),
    ("Name", True), ("Event", True), ("HAS_CHAPTER", False), ("HAS_PASSAGE", False),
    ("HAS_VERSE", False), ("NEXT", False), ("PARALLEL", False), ("ANCHORED_AT", False),
])
def test_a_structural_row_lost_is_red(stored, snap, kind_or_type, is_node):
    nodes, edges = _rows(stored)
    rows, key = (nodes, "kind") if is_node else (edges, "type")
    index = next(i for i, r in enumerate(rows) if r[key] == kind_or_type)
    gone = rows[index]
    del rows[index]
    if is_node:     # drop what pointed at it, so the count is what goes red
        edges = [e for e in edges if not ((e["src_kind"], e["src"]) == (gone["kind"], gone["id"])
                                          or (e["dst_kind"], e["dst"]) == (gone["kind"], gone["id"]))]
    _red(_gate(nodes, edges, snap), kind_or_type)


def test_a_mention_lost_is_red(stored, snap):
    nodes, edges = _rows(stored)
    index = next(i for i, r in enumerate(edges) if r["type"] == "MENTIONS" and r["src_kind"] == "Passage")
    del edges[index]
    _red(_gate(nodes, edges, snap), "MENTIONS")


def test_a_kin_edge_whose_end_is_not_written_in_its_evidence_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges[-1]["props"]["evidence_units"] = ["act.9.1"]
    _red(_gate(nodes, edges, snap), "哥尼流")


def test_a_kin_edge_whose_evidence_is_not_a_verse_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges[-1]["props"]["evidence_units"] = ["gen.1.1"]
    _red(_gate(nodes, edges, snap), "gen.1.1")


@pytest.mark.parametrize("provenance", ["external_dataset", "legacy_tuned", "curated_metadata", None])
def test_a_kin_edge_from_outside_the_pdf_is_red(stored, snap, provenance):
    nodes, edges = _rows(stored)
    edges[-1]["props"]["provenance_class"] = provenance
    _red(_gate(nodes, edges, snap), "provenance_class")


def test_a_parent_cycle_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges += [_kin("PARENT_OF", "e000002", "e000003", ["act.10.1", "act.9.2"]),
              _kin("PARENT_OF", "e000003", "e000001", ["act.9.2", "act.9.1"])]
    _red(_gate(nodes, edges, snap), "cycle")


def test_a_person_with_two_spouse_edges_each_way_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges.append(_kin("SPOUSE_OF", "e000002", "e000001", ["act.10.1", "act.9.1"], role="-"))
    _red(_gate(nodes, edges, snap), "SPOUSE_OF")


def test_the_same_kin_edge_twice_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges.append(copy.deepcopy(edges[-1]))
    _red(_gate(nodes, edges, snap), "twice")


def test_a_role_outside_the_schema_is_red(stored, snap):
    nodes, edges = _rows(stored)
    edges[-1]["props"]["role"] = "F"
    _red(_gate(nodes, edges, snap), "role")


def test_meta_that_disagrees_with_the_rows_is_red(stored, snap):
    nodes, edges = _rows(stored)
    meta = meta_doc(nodes, edges)
    _red(_gate(nodes, edges, snap, {**meta, "nodes_sha256": "0" * 64}), "nodes_sha256")
    _red(_gate(nodes, edges, snap, {**meta, "schema_version": "other"}), "schema_version")
    _red(_gate(nodes, edges, snap, {**meta, "counts": {"nodes": {}, "edges": {}}}), "counts")


def test_an_empty_graph_is_red(snap):
    assert not check_graph([], [], meta_doc([], []), snap).passed


def test_a_stored_layer_is_gated_through_the_runner_and_needs_its_dependencies(mini, stored):
    report = gate_layer(stored.path, "graph", [mini.layers[k].path for k in ("text", "struct", "kg0", "events")],
                        mini_release.MINI_COUNTS, inputs=mini.checks.inputs)
    assert [g.name for g in report.gates] == ["G-GRAPH"] and report.passed
    from ragdata.gates.base import GateInputError
    with pytest.raises(GateInputError):
        gate_layer(stored.path, "graph", [mini.layers["text"].path], mini_release.MINI_COUNTS,
                   inputs=mini.checks.inputs)


def test_a_graph_layer_without_its_meta_cannot_pass(mini, stored, tmp_path):
    from ragdata.store import write_layer
    files = {n: (stored.path / n).read_bytes() for n in (KG_NODES, KG_EDGES)}
    broken = write_layer(tmp_path, "graph", files, depends_on=dict(stored.depends_on))
    report = gate_layer(broken.path, "graph", [mini.layers[k].path for k in ("text", "struct", "kg0", "events")],
                        mini_release.MINI_COUNTS, inputs=GateInputs(registries=mini.root / "registries"))
    assert not report.passed
    assert json.dumps(report.to_json()).find(KG_META) > 0
