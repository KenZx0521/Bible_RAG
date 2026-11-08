"""A stand-in for ``loader.neo4j_db.Neo4jDb``: what the server holds, per build.

It does to a row what the server does and the projection has to live with: a null property is
not stored, only scalars and lists of scalars fit, an edge is MERGEd on its type, its ends and
its key properties, and an edge whose end is not there is skipped without a word.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ragdata.kg.graph_schema import EDGE_KEY_PROPS
from ragdata.loader.neo4j_db import SCHEMA_NAMES, Neo4jDbError


def _storable(props: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in props.items():
        items = value if isinstance(value, list) else [value]
        if any(isinstance(item, (dict, list)) for item in items):
            raise Neo4jDbError(f"property {key} is neither a scalar nor a list of scalars")
    return {k: v for k, v in props.items() if v is not None}


class FakeNeo4j:
    def __init__(self) -> None:
        self.nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.edges: dict[tuple, dict[str, Any]] = {}
        self.infos: dict[str, dict[str, Any]] = {}
        self.schema: set[str] = set()
        self.writes: list[tuple[str, int]] = []     # what was written, in batches of how many
        self.fail_at_write: int | None = None       # the n-th write raises
        self.unreachable = False
        self.lose_kind: str | None = None           # rows of this kind vanish on the way in
        self.calls: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def _reach(self, call: str) -> None:
        self.calls.append(call)
        if self.unreachable:
            raise Neo4jDbError("neo4j: ServiceUnavailable")

    def _wrote(self, what: str, size: int) -> None:
        if self.fail_at_write is not None and len(self.writes) + 1 >= self.fail_at_write:
            raise Neo4jDbError(f"neo4j: the server went away writing {what}")
        self.writes.append((what, size))

    def ensure_schema(self) -> None:
        self._reach("ensure_schema")
        self.schema |= set(SCHEMA_NAMES)

    def schema_missing(self) -> list[str]:
        self._reach("schema_missing")
        return sorted(set(SCHEMA_NAMES) - self.schema)

    def build_info(self, build_id: str) -> dict[str, Any] | None:
        self._reach("build_info")
        found = self.infos.get(build_id)
        return dict(found) if found is not None else None

    def open_build(self, build_id: str, info: Mapping[str, Any]) -> None:
        self._reach("open_build")
        self.infos[build_id] = {**info, "build_id": build_id, "complete": False}

    def mark_complete(self, build_id: str) -> None:
        self._reach("mark_complete")
        self.infos[build_id] = {**self.infos[build_id], "complete": True}

    def merge_nodes(self, build_id: str, kind: str, rows: Sequence[Mapping[str, Any]]) -> None:
        self._reach("merge_nodes")
        self._wrote(kind, len(rows))
        if kind == self.lose_kind:
            return
        for row in rows:
            key = (build_id, kind, row["id"])
            self.nodes[key] = {**self.nodes.get(key, {}), **_storable(row["props"])}

    def merge_edges(self, build_id: str, edge_type: str, src_kind: str, dst_kind: str,
                    rows: Sequence[Mapping[str, Any]]) -> None:
        self._reach("merge_edges")
        self._wrote(edge_type, len(rows))
        for row in rows:
            ends = (build_id, src_kind, row["src"]), (build_id, dst_kind, row["dst"])
            if not all(end in self.nodes for end in ends):
                continue
            key_props = tuple(row["props"][k] for k in EDGE_KEY_PROPS.get(edge_type, ()))
            key = (build_id, edge_type, src_kind, row["src"], dst_kind, row["dst"], key_props)
            self.edges[key] = {**self.edges.get(key, {}), **_storable(row["props"])}

    def read_nodes(self, build_id: str, kind: str) -> list[dict[str, Any]]:
        self._reach("read_nodes")
        return [{"id": node_id, "props": {**props, "build_id": build_id, "id": node_id}}
                for (build, found, node_id), props in self.nodes.items()
                if (build, found) == (build_id, kind)]

    def read_edges(self, build_id: str, edge_type: str, src_kind: str, dst_kind: str
                   ) -> list[dict[str, Any]]:
        self._reach("read_edges")
        return [{"src": src, "dst": dst, "dst_build": build_id, "props": {**props, "build_id": build}}
                for (build, found, skind, src, dkind, dst, _), props in self.edges.items()
                if (build, found, skind, dkind) == (build_id, edge_type, src_kind, dst_kind)]

    def delete_build(self, build_id: str) -> int:
        self._reach("delete_build")
        self.infos.pop(build_id, None)
        gone = [key for key in self.nodes if key[0] == build_id]
        for key in gone:
            del self.nodes[key]
        for key in [key for key in self.edges if key[0] == build_id]:
            del self.edges[key]
        return len(gone)
