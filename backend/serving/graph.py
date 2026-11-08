"""Whether the serving build's graph can be used: what /api/v1/health reports and a walk asks.

Neo4j is not part of the handshake: a server that is down, or holds another graph or none, leaves
the build served and the answers as they are, without the graph; ``state`` says why. ``status``
reads ``(:BuildInfo)``, which ``ragdata kg-project`` marks complete only after reading every row back
and hashing it. Rows deleted behind its back are for ``ragdata verify`` to find, not for a health check.

/api/v1/health asks ``status`` every time. A walk asks ``usable``, the same answer at most once per
30 s, so a request costs no extra query and a graph projected meanwhile is picked up without a restart.
A read that timed out is not an answer: only that question goes without the graph, and the next one asks
again (``neo4j_db`` counts two in a row as Neo4j being down). Nor is a read that was skipped: ``neo4j_db`` holds
Neo4j off for its own 30 s, and keeping that answer here would add 30 more.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Mapping

from database import neo4j_db
from serving import context
from serving.contracts import KG_META, KgMeta

logger = logging.getLogger(__name__)

OFF, READY, UNAVAILABLE, MISMATCH = "off", "ready", "unavailable", "mismatch"
USABLE_FOR_S = 30.0
_NOT_ANSWERS = frozenset({f"neo4j: {neo4j_db.TIMEOUT}", f"neo4j: {neo4j_db.SKIPPING}"})


@dataclass(frozen=True)
class GraphStatus:
    state: str
    reason: str | None = None
    build_id: str | None = None
    kg_sha256: str | None = None
    nodes: int | None = None
    edges: int | None = None
    complete: bool | None = None
    neo4j_version: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == READY

    def to_json(self) -> dict[str, Any]:
        found = {"state": self.state, "reason": self.reason, "build_id": self.build_id,
                 "kg_sha256": self.kg_sha256, "nodes": self.nodes, "edges": self.edges,
                 "complete": self.complete, "neo4j_version": self.neo4j_version}
        return {key: value for key, value in found.items() if value is not None}


def _wrong(kg: KgMeta, info: Mapping[str, Any]) -> list[str]:
    want = {"kg_sha256": kg.sha256, **{f"nodes_{k}": n for k, n in kg.nodes.items()},
            **{f"edges_{k}": n for k, n in kg.edges.items()}}
    out = [] if info.get("complete") is True else [f"BuildInfo complete is {info.get('complete')!r}"]
    return out + [f"BuildInfo {key} is {info.get(key)!r}, {KG_META} says {value!r}"
                  for key, value in want.items() if info.get(key) != value]


def judge(build_id: str, kg: KgMeta, info: Mapping[str, Any] | None) -> GraphStatus:
    """The state of a reachable server that says ``info`` of the build."""
    if info is None:
        return GraphStatus(MISMATCH, f"no BuildInfo for {build_id}: run ragdata kg-project", build_id,
                           kg.sha256, complete=False)
    wrong = _wrong(kg, info)
    complete = info.get("complete") is True
    if wrong:
        return GraphStatus(MISMATCH, "; ".join(wrong), build_id, kg.sha256, complete=complete)
    return GraphStatus(READY, None, build_id, kg.sha256, sum(kg.nodes.values()), sum(kg.edges.values()),
                       complete=complete)


async def status() -> GraphStatus:
    """Never raises: any error reaching Neo4j is the state ``unavailable``."""
    try:
        active = context.active()
    except context.NoActiveBuild:
        return GraphStatus(OFF)
    if active.kg is None:
        return GraphStatus(OFF)
    build_id = active.build.build_id
    try:
        info = await neo4j_db.build_info(build_id)
        version = await neo4j_db.server_version()
    except Exception as exc:  # noqa: BLE001 - whatever it is, the build is served without the graph
        logger.warning("Neo4j unavailable for %s: %s", build_id, type(exc).__name__)
        why = getattr(exc, "reason", type(exc).__name__)
        return GraphStatus(UNAVAILABLE, f"neo4j: {why}", build_id, active.kg.sha256)
    return replace(judge(build_id, active.kg, info), neo4j_version=version)


_usable: tuple[float, GraphStatus] | None = None


def _now() -> float:
    return time.monotonic()


def forget() -> None:
    """Ask Neo4j again next time (tests; a new process starts this way)."""
    global _usable
    _usable = None


def _no_answer(found: GraphStatus) -> bool:
    return found.state == UNAVAILABLE and found.reason in _NOT_ANSWERS


async def usable() -> GraphStatus:
    """``status``, asked at most once per ``USABLE_FOR_S``; a timeout or a skip is not kept."""
    global _usable
    now = _now()
    if _usable is not None and now - _usable[0] < USABLE_FOR_S:
        return _usable[1]
    found = await status()
    _usable = None if _no_answer(found) else (now, found)
    return found
