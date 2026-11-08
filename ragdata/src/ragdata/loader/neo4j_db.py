"""The Neo4j adapter of the projection (``graph_load`` holds the logic; only this module imports the
driver). Every statement is a template closed over ``graph_schema``: a label or type outside the
schema is refused before it reaches Cypher, every other value is a parameter, and each statement
stays inside one ``build_id``. One server holds many builds: nodes and edges carry ``build_id``,
each label has a composite unique constraint on (build_id, id).

``Name.label`` and ``Person.label`` have their own indexes.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, TypeVar

from neo4j import GraphDatabase, RoutingControl
from neo4j.exceptions import DriverError, Neo4jError

from ragdata.kg.graph_schema import EDGE_ENDS, EDGE_KEY_PROPS, NODE_KINDS
from ragdata.loader.config import Neo4jSettings
from ragdata.loader.plan import LoaderError

BUILD_INFO = "BuildInfo"
LABELLED = ("Name", "Person")           # the kinds looked up by label
AWAIT_INDEXES_S = 120
DELETE_BATCH = 2000

READ_BUILD_INFO = "MATCH (i:BuildInfo {build_id:$b}) RETURN properties(i) AS info"
OPEN_BUILD = "MERGE (i:BuildInfo {build_id:$b}) SET i += $info, i.complete = false"
MARK_COMPLETE = "MATCH (i:BuildInfo {build_id:$b}) SET i.complete = true"
T = TypeVar("T")


class Neo4jDbError(LoaderError):
    """The server refused, could not be reached, or a statement left the schema."""


def _kind(name: str, allowed: Sequence[str] = NODE_KINDS) -> str:
    if name not in allowed:
        raise Neo4jDbError(f"{name!r} is not in the graph schema")
    return name


def _ends(edge_type: str, src_kind: str, dst_kind: str) -> None:
    if (src_kind, dst_kind) not in EDGE_ENDS.get(edge_type, ()):
        raise Neo4jDbError(f"({src_kind})-[{edge_type}]->({dst_kind}) is not in the graph schema")


def node_merge(kind: str) -> str:
    return (f"UNWIND $rows AS row MERGE (n:{_kind(kind)} {{build_id:$b, id:row.id}}) "
            "SET n += row.props")


def node_read(kind: str) -> str:
    return f"MATCH (n:{_kind(kind)} {{build_id:$b}}) RETURN n.id AS id, properties(n) AS props"


def edge_merge(edge_type: str, src_kind: str, dst_kind: str) -> str:
    """Both ends must be in the build; an edge is one per type and pair, and key properties."""
    _ends(edge_type, src_kind, dst_kind)
    key = "".join(f", {prop}:row.props.{prop}" for prop in EDGE_KEY_PROPS.get(edge_type, ()))
    return ("UNWIND $rows AS row "
            f"MATCH (a:{src_kind} {{build_id:$b, id:row.src}}) "
            f"MATCH (c:{dst_kind} {{build_id:$b, id:row.dst}}) "
            f"MERGE (a)-[r:{edge_type} {{build_id:$b{key}}}]->(c) SET r += row.props")


def edge_read(edge_type: str, src_kind: str, dst_kind: str) -> str:
    _ends(edge_type, src_kind, dst_kind)
    return (f"MATCH (a:{src_kind} {{build_id:$b}})-[r:{edge_type}]->(c:{dst_kind}) "
            "RETURN a.id AS src, c.id AS dst, c.build_id AS dst_build, properties(r) AS props")


def delete_batch(label: str) -> str:
    _kind(label, (BUILD_INFO, *NODE_KINDS))
    return (f"MATCH (n:{label} {{build_id:$b}}) WITH n LIMIT {DELETE_BATCH} "
            "DETACH DELETE n RETURN count(*) AS deleted")


def schema_statements() -> list[str]:
    keys = [f"CREATE CONSTRAINT kg_{kind.lower()}_key IF NOT EXISTS FOR (n:{kind}) "
            "REQUIRE (n.build_id, n.id) IS UNIQUE" for kind in NODE_KINDS]
    labels = [f"CREATE INDEX kg_{kind.lower()}_label IF NOT EXISTS FOR (n:{kind}) "
              "ON (n.build_id, n.label)" for kind in LABELLED]
    info = ("CREATE CONSTRAINT kg_buildinfo_key IF NOT EXISTS FOR (n:BuildInfo) "
            "REQUIRE n.build_id IS UNIQUE")
    return [*keys, info, *labels]


CONSTRAINT_NAMES = (*(f"kg_{kind.lower()}_key" for kind in NODE_KINDS), "kg_buildinfo_key")
INDEX_NAMES = tuple(f"kg_{kind.lower()}_label" for kind in LABELLED)
SCHEMA_NAMES = (*CONSTRAINT_NAMES, *INDEX_NAMES)


def guarded(call: Callable[[], T]) -> T:
    """``call``, with the driver's errors as a loader error (they never carry the password)."""
    try:
        return call()
    except (Neo4jError, DriverError, OSError) as exc:
        raise Neo4jDbError(f"neo4j: {type(exc).__name__}: {exc}") from exc


class Neo4jDb:
    def __init__(self, driver: Any) -> None:
        self._driver = driver

    @classmethod
    def connect(cls, settings: Neo4jSettings) -> "Neo4jDb":
        """A driver connects on its first statement, so a server that is down shows up there."""
        return cls(guarded(lambda: GraphDatabase.driver(
            settings.uri, auth=(settings.user, settings.password), telemetry_disabled=True)))

    def close(self) -> None:
        guarded(self._driver.close)

    def run_read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        result = guarded(lambda: self._driver.execute_query(query, params,
                                                            routing_=RoutingControl.READ))
        return [dict(record) for record in result.records]

    def run_write(self, query: str, **params: Any) -> None:
        guarded(lambda: self._driver.execute_query(query, params, routing_=RoutingControl.WRITE))

    def ensure_schema(self) -> None:
        for statement in schema_statements():
            self.run_write(statement)
        self.run_write(f"CALL db.awaitIndexes({AWAIT_INDEXES_S})")

    def schema_missing(self) -> list[str]:
        """The constraints and indexes that do not exist or are not online."""
        constraints = {r["name"] for r in self.run_read("SHOW CONSTRAINTS YIELD name")}
        online = {r["name"] for r in self.run_read("SHOW INDEXES YIELD name, state")
                  if r["state"] == "ONLINE"}
        return sorted({*(n for n in CONSTRAINT_NAMES if n not in constraints or n not in online),
                       *(n for n in INDEX_NAMES if n not in online)})

    def build_info(self, build_id: str) -> dict[str, Any] | None:
        rows = self.run_read(READ_BUILD_INFO, b=build_id)
        return dict(rows[0]["info"]) if rows else None

    def open_build(self, build_id: str, info: Mapping[str, Any]) -> None:
        """The BuildInfo node with ``info``, and not complete."""
        self.run_write(OPEN_BUILD, b=build_id, info=dict(info))

    def mark_complete(self, build_id: str) -> None:
        self.run_write(MARK_COMPLETE, b=build_id)

    def merge_nodes(self, build_id: str, kind: str, rows: Sequence[Mapping[str, Any]]) -> None:
        self.run_write(node_merge(kind), b=build_id, rows=list(rows))

    def merge_edges(self, build_id: str, edge_type: str, src_kind: str, dst_kind: str,
                    rows: Sequence[Mapping[str, Any]]) -> None:
        self.run_write(edge_merge(edge_type, src_kind, dst_kind), b=build_id, rows=list(rows))

    def read_nodes(self, build_id: str, kind: str) -> list[dict[str, Any]]:
        return self.run_read(node_read(kind), b=build_id)

    def read_edges(self, build_id: str, edge_type: str, src_kind: str, dst_kind: str
                   ) -> list[dict[str, Any]]:
        return self.run_read(edge_read(edge_type, src_kind, dst_kind), b=build_id)

    def delete_build(self, build_id: str) -> int:
        """Every node of the build and so its edges, BuildInfo first; the graph nodes deleted."""
        self.run_write(f"MATCH (n:{BUILD_INFO} {{build_id:$b}}) DELETE n", b=build_id)
        return sum(self._delete_kind(kind, build_id) for kind in NODE_KINDS)

    def _delete_kind(self, kind: str, build_id: str) -> int:
        total, statement = 0, delete_batch(kind)
        while True:
            result = guarded(lambda: self._driver.execute_query(statement, {"b": build_id},
                                                                routing_=RoutingControl.WRITE))
            deleted = result.records[0]["deleted"]
            total += deleted
            if deleted < DELETE_BATCH:
                return total
