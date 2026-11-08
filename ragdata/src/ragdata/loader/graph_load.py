"""``ragdata kg-project``: project a build's graph layer into Neo4j and read it back.

The layer is the source; Neo4j holds a projection of it, one ``build_id`` per build. Neo4j is
not in ``load``'s PG transaction, so this is a step of its own, after ``load``: rerunnable (rows go
in as UNWIND batches of MERGE, 500 at a time), and a run that was interrupted is finished by the
next. A build's ``(:BuildInfo)`` says ``complete=true`` only after every row was read back from the
server and hashed: the read-back, sorted and encoded as the layer's files are, must give the
``nodes_sha256`` and ``edges_sha256`` of ``kg_meta.json``. Neo4j stores no null, so a property the
schema declares nullable (``NULLABLE_PROPS``) is put back when it is not there.

A BuildInfo naming another ``kg_sha256`` is refused: a build id names one release, so that is a
broken server, not something to overwrite. ``kg_sha256`` is the sha256 of ``kg_meta.json``, which
the release's contract table pins. A complete build is only read back again, nothing is written.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.contract.registry import KG_EDGES, KG_META, KG_NODES
from ragdata.gates.base import capped
from ragdata.kg.graph_schema import (
    EDGE_ENDS, NODE_KINDS, NULLABLE_PROPS, sorted_edges, sorted_nodes,
)
from ragdata.loader.plan import LoaderError
from ragdata.release.assemble import Release
from ragdata.store import LayerData, encode_jsonl, read_layer
from ragdata.store.cas import sha256_bytes
from ragdata.store.versions import GRAPH

BATCH = 500
SHOWN = 6                               # violations an error message names
Row = Mapping[str, Any]


class ProjectionError(LoaderError):
    """The release has no graph to project, or Neo4j does not hold what the layer holds."""


@dataclass(frozen=True)
class GraphSource:
    """What a build's projection must hold, from its release's graph layer."""

    build_id: str
    version: str
    kg_sha256: str
    meta: Mapping[str, Any]
    nodes: tuple[Row, ...]
    edges: tuple[Row, ...]


@dataclass(frozen=True)
class ReadBack:
    """The server's rows of one build, in the layer's row format and order."""

    nodes: tuple[Row, ...]
    edges: tuple[Row, ...]
    cross_build: tuple[str, ...]


def _source(build_id: str, layer: LayerData, pinned: Any) -> GraphSource:
    data = (layer.path / KG_META).read_bytes()
    found = sha256_bytes(data)
    if found != pinned:
        raise ProjectionError(f"{layer.version}: {KG_META} does not hash to what the release pins "
                              f"({found[:12]}, {str(pinned)[:12]})")
    return GraphSource(build_id, layer.version, found, json.loads(data), layer.rows[KG_NODES],
                       layer.rows[KG_EDGES])


def source_of_release(release: Release) -> GraphSource:
    layer = release.layers.get(GRAPH)
    if layer is None:
        raise ProjectionError(f"{release.build_id}: the release holds no graph layer")
    return _source(release.build_id, layer, release.doc["contracts"].get(KG_META))


def source_of_build(build_id: str, releases: Path, store_root: Path) -> GraphSource:
    """``releases/{build_id}.json``'s graph layer, read through the store. Only this layer is read:
    ``load`` and ``verify`` assemble and gate the whole release, and neither is needed here."""
    if not ids.is_valid(build_id, "build"):
        raise ProjectionError(f"{build_id!r} is not a release build id (b<YYYYMMDD>_<8 hex>)")
    path = Path(releases) / f"{build_id}.json"
    if not path.is_file():
        raise ProjectionError(f"no release {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("build_id") != build_id:
        raise ProjectionError(f"{path} is the release of {doc.get('build_id')!r}, not of {build_id}")
    version = doc.get("layers", {}).get(GRAPH)
    if not version:
        raise ProjectionError(f"{build_id}: the release holds no graph layer")
    return _source(build_id, read_layer(Path(store_root) / GRAPH / version),
                   doc.get("contracts", {}).get(KG_META))


def build_info_props(source: GraphSource) -> dict[str, Any]:
    """What BuildInfo says besides ``build_id`` and ``complete``; a node holds no map, so flat."""
    counts = source.meta["counts"]
    return {"kg_sha256": source.kg_sha256, "graph_version": source.version,
            "schema_version": source.meta["schema_version"],
            "nodes_sha256": source.meta["nodes_sha256"], "edges_sha256": source.meta["edges_sha256"],
            **{f"nodes_{kind}": n for kind, n in counts["nodes"].items()},
            **{f"edges_{edge_type}": n for edge_type, n in counts["edges"].items()}}


def _batches(rows: Sequence[Row]) -> list[Sequence[Row]]:
    return [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]


def _write(source: GraphSource, db: Any) -> None:
    b = source.build_id
    for kind in NODE_KINDS:
        rows = [{"id": r["id"], "props": r["props"]} for r in source.nodes if r["kind"] == kind]
        for batch in _batches(rows):
            db.merge_nodes(b, kind, batch)
    groups: dict[tuple[str, str, str], list[Row]] = {}
    for r in source.edges:
        groups.setdefault((r["type"], r["src_kind"], r["dst_kind"]), []).append(
            {"src": r["src"], "dst": r["dst"], "props": r["props"]})
    for (edge_type, src_kind, dst_kind), rows in groups.items():
        for batch in _batches(rows):
            db.merge_edges(b, edge_type, src_kind, dst_kind, batch)


def _node_row(kind: str, found: Row) -> dict[str, Any]:
    """``properties(n)`` also holds what the node was merged on."""
    props = {k: v for k, v in found["props"].items() if k not in ("build_id", "id")}
    return {"kind": kind, "id": found["id"],
            "props": {**dict.fromkeys(NULLABLE_PROPS.get(kind, ())), **props}}


def read_back(build_id: str, db: Any) -> ReadBack:
    nodes = [_node_row(kind, r) for kind in NODE_KINDS for r in db.read_nodes(build_id, kind)]
    edges, cross = [], []
    for edge_type, ends in EDGE_ENDS.items():
        for src_kind, dst_kind in ends:
            for r in db.read_edges(build_id, edge_type, src_kind, dst_kind):
                edges.append({"type": edge_type, "src_kind": src_kind, "src": r["src"],
                              "dst_kind": dst_kind, "dst": r["dst"],
                              "props": {k: v for k, v in r["props"].items() if k != "build_id"}})
                if r["dst_build"] != build_id or r["props"].get("build_id") != build_id:
                    cross.append(f"{edge_type} {r['src']}->{r['dst']}")
    return ReadBack(tuple(sorted_nodes(nodes)), tuple(sorted_edges(edges)), tuple(cross))


def _count_violations(what: str, found: Counter, want: Mapping[str, int]) -> list[str]:
    return [f"{what} {key}: {found.get(key, 0)} in Neo4j, {want.get(key, 0)} in {KG_META}"
            for key in sorted({*found, *want}) if found.get(key, 0) != want.get(key, 0)]


def _lines(rows: Sequence[Row]) -> set[str]:
    return set(encode_jsonl(rows).decode("utf-8").splitlines())


def _row_violations(what: str, found: Sequence[Row], want: Sequence[Row]) -> list[str]:
    """The sha of the read-back, and when it differs the rows that do (they name their ids)."""
    sha, expected = sha256_bytes(encode_jsonl(found)), sha256_bytes(encode_jsonl(want))
    if sha == expected:
        return []
    have, need = _lines(found), _lines(want)
    return [f"{what}_sha256 of the read-back is {sha[:12]}, {KG_META} says {expected[:12]}",
            *(f"not in Neo4j as in the layer: {line[:160]}" for line in sorted(need - have)),
            *(f"in Neo4j, not in the layer: {line[:160]}" for line in sorted(have - need))]


def compare(source: GraphSource, back: ReadBack) -> list[str]:
    """How the read-back differs from the layer: counts by kind and type, shas and rows."""
    counts = source.meta["counts"]
    return [*_count_violations("nodes", Counter(r["kind"] for r in back.nodes), counts["nodes"]),
            *_count_violations("edges", Counter(r["type"] for r in back.edges), counts["edges"]),
            *(f"edge reaches another build: {edge}" for edge in back.cross_build),
            *_row_violations("nodes", back.nodes, source.nodes),
            *_row_violations("edges", back.edges, source.edges)]


def _info_violations(source: GraphSource, info: Mapping[str, Any]) -> list[str]:
    out = [] if info.get("complete") is True else [
        f"BuildInfo complete is {info.get('complete')!r}: run ragdata kg-project"]
    return out + [f"BuildInfo {key} is {info.get(key)!r}, {KG_META} says {value!r}"
                  for key, value in build_info_props(source).items() if info.get(key) != value]


def projection_violations(source: GraphSource, db: Any) -> list[str]:
    """What ``verify`` asks: BuildInfo complete and of this graph, the schema, the rows read back."""
    info = db.build_info(source.build_id)
    if info is None:
        return [f"no BuildInfo for {source.build_id}: run ragdata kg-project"]
    return [*_info_violations(source, info),
            *(f"no constraint or online index {name}" for name in db.schema_missing()),
            *compare(source, read_back(source.build_id, db))]


def _report(source: GraphSource, written: bool, start: float) -> dict[str, Any]:
    return {"build_id": source.build_id, "graph": source.version, "kg_sha256": source.kg_sha256,
            "written": written, "seconds": round(time.monotonic() - start, 2),
            "counts": source.meta["counts"], "nodes_sha256": source.meta["nodes_sha256"],
            "edges_sha256": source.meta["edges_sha256"]}


def _refused(source: GraphSource, what: str, found: Sequence[str]) -> ProjectionError:
    return ProjectionError(f"{source.build_id}: {what}: {list(capped(list(found), SHOWN))}")


def project(source: GraphSource, db: Any) -> dict[str, Any]:
    """Make the server hold the layer, or raise; a complete build is only read back."""
    start = time.monotonic()
    b = source.build_id
    db.ensure_schema()
    info = db.build_info(b)
    if info is not None and info.get("kg_sha256") != source.kg_sha256:
        raise ProjectionError(f"{b}: Neo4j holds kg_sha256 {str(info.get('kg_sha256'))[:12]}, the "
                              f"release pins {source.kg_sha256[:12]}; nothing was written")
    props = build_info_props(source)
    complete = info is not None and info.get("complete") is True
    if not complete:
        db.open_build(b, props)
        _write(source, db)
    bad = compare(source, read_back(b, db))
    if bad and complete:
        db.open_build(b, props)
        raise _refused(source, "marked complete but does not read back, now marked incomplete; "
                               "nothing was written", bad)
    if bad:
        raise _refused(source, "does not read back, left incomplete", bad)
    if not complete:
        db.mark_complete(b)
    return _report(source, not complete, start)
