"""Stand-ins for the graph tests: a served KG build and a Neo4j that answers by template name.

``FakeGraph.read`` replaces ``database.neo4j_db.read``: it records every call and answers from
``answers`` (a list of rows, a callable of the params, or an exception to raise). ``walk_round``
computes the walk template's answer over a small graph in plain Python, so the walk's two rounds
can be checked by hand; whether the Cypher computes the same is checked against the real server
(``test_cypher_live.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from serving import context
from serving import graph as serving_graph
from serving.build import Build
from serving.contracts import KgMeta
from serving.handshake import Handshake

GRAPH_BUILD = Build("b20261102_aaaaaaaa", "bb20261102_aaaaaaaa", "passages__b", Path("/c"), True, 22)
KG = KgMeta("ragdata.kg.v1", {"Person": 2}, {"PARENT_OF": 1}, "a" * 64, "b" * 64, "c" * 64)
READY = serving_graph.GraphStatus(serving_graph.READY, None, GRAPH_BUILD.build_id, KG.sha256, 2, 1)


def serve(lexicon, registry=(), regnal=None, gen=None, kg=KG, build=GRAPH_BUILD) -> None:
    context.install(context.make_active(build, lexicon, registry, regnal, gen, kg),
                    Handshake(build.build_id, (), True))


@dataclass
class FakeGraph:
    """``neo4j_db.read`` on made-up answers; an unlisted template answers nothing."""

    answers: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)

    async def read(self, name: str, **params: Any) -> list[dict]:
        self.calls.append((name, params))
        answer = self.answers.get(name, [])
        if isinstance(answer, Exception):
            raise answer
        return answer(params) if callable(answer) else answer

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def use(monkeypatch, graph: FakeGraph, status=READY) -> FakeGraph:
    """Make every graph-side module read ``graph``; the walk finds the graph ``status``."""
    async def usable():
        return status
    monkeypatch.setattr("database.neo4j_db.read", graph.read)
    monkeypatch.setattr("serving.graph.usable", usable)
    return graph


@dataclass(frozen=True)
class SmallGraph:
    """Passage -> the Names it mentions; Name -> (label, df, idf); Passage -> its PARALLEL passages."""

    mentions: Mapping[str, tuple[str, ...]]
    names: Mapping[str, tuple[str, int, float]]
    parallel: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def walk_round(graph: SmallGraph) -> Callable[[dict], list[dict]]:
    """The answer the ``walk_round`` template gives on ``graph``, in the template's row shape."""
    def answer(params: dict) -> list[dict]:
        weight: dict[str, float] = {}
        for seed in params["seeds"]:
            for name in graph.mentions.get(seed["id"], ()):
                weight[name] = weight.get(name, 0.0) + seed["w"]
        for seed in params["names"]:
            if seed["id"] in graph.names:
                weight[seed["id"]] = weight.get(seed["id"], 0.0) + seed["w"]
        activated = {name: round(w * graph.names[name][2], 9) for name, w in weight.items()
                     if graph.names[name][1] <= params["max_df"]}
        top = sorted(activated.items(), key=lambda kv: (-kv[1], kv[0]))[:params["top_names"]]
        scores: dict[str, float] = {}
        for passage, held in graph.mentions.items():
            total = sum(a * graph.names[name][2] for name, a in top if name in held)
            if any(name in held for name, _ in top):
                scores[passage] = round(total, 9)
        parallel: dict[str, float] = {}
        for seed in params["parallel"]:
            for other in graph.parallel.get(seed["id"], ()):
                parallel[other] = parallel.get(other, 0.0) + params["parallel_factor"] * seed["w"]
        return [{"names": [[name, graph.names[name][0], a] for name, a in top],
                 "hits": [[p, s] for p, s in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))],
                 "parallel": [[p, round(s, 9)] for p, s in sorted(parallel.items())]}]
    return answer


def idf(n_passages: int, df: int) -> float:
    return round(math.log(n_passages / df), 6)
