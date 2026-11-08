"""The graph walk: two rounds of spreading activation over passages and names (a truncated
personalized PageRank), on the build's graph in Neo4j.

Seeds: the names the routing lexicon reads in the question, weight 1, and the route's dense arm's
first passages, weight 1/rank (a chunk stands for its passage). The first round goes passage -> name:
a(n) = Σ w(p)·idf(n), plus 1·idf(n) for a name of the question, leaving out names in more than
WALK_MAX_DF passages, and keeps the top names; then name -> passage: s1(q) = Σ a(n)·idf(n). A passage of
the PARALLEL pericope of a seed's gets 0.5·w(p) on top. The second round takes the top passages of s1,
scaled so the first weighs 1 like the first seed, and does the same for s2. s = s1 + 0.5·s2.

Both rounds are one template (database.cypher.WALK_ROUND), so a walk is two queries. What it finds
joins the pool before ranking: a new passage at ``walk_weight``, below the dense arm's, one already there
as it was. s only says what to keep: a prior raised by s put passages the reranker scored low in the top-k
(measured: gold-slot recall 0.69 -> 0.63 on 60 questions), and it favoured the longest genealogies, which hold
the most names. So the walk finds and the reranker decides.

Except for one place. A second hop looks nothing like the question, so the reranker never lets it in by itself:
the last of a full top-k gives way to the walked passage the reranker likes best among those with no verse the
others hold (``with_slot``). The size of the context stays k. Measured on 113 complex questions: hops in the
top-k 0.547 -> 0.579 (13 up, 3 down) with one place, 0.544 with two.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from config import settings
from database import neo4j_db, postgres
from ragcommon.routing import RoutingLexicon
from utils.retrieval import candidates as cands
from utils.retrieval import chapter_blocks
from utils.retrieval.dense import ROUTE_ARM
from utils.retrieval.pins import BOOK_ANCHOR

logger = logging.getLogger(__name__)

LABEL = "graph_walk"
_NAME_REF = "nm:"
Scores = dict[str, float]
Seeds = tuple[tuple[str, float], ...]
_A_ROUTES_OWN_PLACE = frozenset({chapter_blocks.SOURCE, BOOK_ANCHOR, "sql_chapter"})


@dataclass(frozen=True)
class Walk:
    seeds: tuple[str, ...] = ()                    # seed passages, then the question's Name ids
    names: tuple[tuple[str, str], ...] = ()        # (Name id, label) the walk crossed
    passages: tuple[tuple[str, float], ...] = ()   # (passage id, s), best first
    hops: int = 0                                  # the most edges a path of the walk crossed
    reach: tuple[tuple[str, int], ...] = ()        # (passage id, the edges that reached it)
    n_cypher: int = 0
    ms: float = 0.0
    skip_reason: str | None = None

    def to_stats(self) -> dict[str, Any]:
        return {"seeds": list(self.seeds), "name_ids": [n for n, _ in self.names],
                "names": [label for _, label in self.names], "passages": [list(p) for p in self.passages],
                "hops": self.hops, "reach": dict(self.reach), "n_cypher": self.n_cypher, "ms": self.ms,
                "skip_reason": self.skip_reason}


def seed_passages(pool: Sequence[dict]) -> Seeds:
    """The dense arm's first passages in hit order, each with weight 1/rank."""
    passages: dict[str, None] = {}
    for c in pool:
        if ROUTE_ARM.label in cands.labels_of(c):
            passages.setdefault(c.get("passage_id") or c["id"], None)
    first = list(passages)[:settings.walk_seed_passages]
    return tuple((pid, 1 / rank) for rank, pid in enumerate(first, 1))


def seed_names(query: str, lexicon: RoutingLexicon) -> tuple[str, ...]:
    """The Names the question writes: the lexicon's literal hits, no vectors."""
    refs = (t.ref for hit in lexicon.match(query) for t in hit.targets)
    return tuple(dict.fromkeys(r for r in refs if r.startswith(_NAME_REF)))


def _seed_rows(seeds: Iterable[tuple[str, float]]) -> list[dict[str, Any]]:
    return [{"id": pid, "w": w} for pid, w in seeds]


async def _round(reads: neo4j_db.Reads, seeds: Seeds, names: tuple[str, ...], parallel: Seeds) -> Mapping[str, Any]:
    rows = await reads(
        "walk_round", seeds=_seed_rows(seeds), names=_seed_rows((n, 1.0) for n in names),
        parallel=_seed_rows(parallel), parallel_factor=settings.walk_parallel_factor,
        max_df=settings.walk_max_df, top_names=settings.walk_top_names)
    return rows[0]


def _best(scores: Mapping[str, float], n: int) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _first_round_scores(found: Mapping[str, Any]) -> Scores:
    scores: Scores = {pid: s for pid, s in found["hits"]}
    for pid, s in found["parallel"]:
        scores[pid] = scores.get(pid, 0.0) + s
    return scores


def _normalized(scores: Mapping[str, float]) -> Seeds:
    best = _best(scores, settings.walk_round2_seeds)
    return tuple((pid, s / best[0][1]) for pid, s in best) if best and best[0][1] > 0 else ()


def _hops(seeds: Seeds, first: Mapping[str, Any], second: Mapping[str, Any] | None) -> int:
    """The edges a path of the walk crossed at most: passage-name-passage is two, a name of the
    question to a passage one, and a seed's parallel passage three (pericope, PARALLEL, pericope)."""
    if not first["hits"] and not first["parallel"]:
        return 0
    reach = 3 if first["parallel"] else 2 if seeds else 1
    return reach + (2 if second and second["hits"] else 0)


def _reach(passages: Iterable[str], seeds: Seeds, first: Mapping[str, Any], second: Mapping[str, Any] | None,
           ) -> tuple[tuple[str, int], ...]:
    """How many edges reached each passage, at the fewest: its name of the question 1, passage-name-passage 2, a
    seed's parallel passage 3, and round two 2 more than the first round's."""
    in_first = {pid for pid, _ in first["hits"]}
    parallel = {pid for pid, _ in first["parallel"]}
    one = 2 if seeds else 1

    def edges_to(pid: str) -> int:
        if pid in in_first:
            return one
        return 3 if pid in parallel else one + 2
    return tuple((pid, edges_to(pid)) for pid in passages)


def _crossed(*rounds: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    found: dict[str, str] = {}
    for found_round in rounds:
        for name_id, label, _ in (found_round or {}).get("names", ()):
            found.setdefault(name_id, label)
    return tuple(found.items())


def _final_scores(s1: Mapping[str, float], second: Mapping[str, Any] | None) -> Scores:
    scores = dict(s1)
    for pid, s in (second or {}).get("hits", ()):
        scores[pid] = scores.get(pid, 0.0) + settings.walk_round2_factor * s
    return {pid: round(s, 9) for pid, s in scores.items()}


async def walk(seeds: Seeds, names: tuple[str, ...], build_id: str) -> Walk:
    """The walk from ``seeds`` and the question's ``names``. Neo4j not answering is a ``skip_reason``."""
    started = time.perf_counter()
    all_seeds = (*(pid for pid, _ in seeds), *names)
    if not all_seeds:
        return Walk()
    reads = neo4j_db.Reads(build_id)

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        first = await _round(reads, seeds, names, seeds)
        s1 = _first_round_scores(first)
        second_seeds = _normalized(s1)
        second = await _round(reads, second_seeds, (), ()) if second_seeds else None
    except neo4j_db.Skipped as exc:
        return Walk(all_seeds, n_cypher=reads.n, ms=elapsed(), skip_reason=exc.reason)
    passages = tuple(_best(_final_scores(s1, second), settings.walk_k))
    return Walk(all_seeds, _crossed(first, second), passages, _hops(seeds, first, second),
                _reach((pid for pid, _ in passages), seeds, first, second), reads.n, elapsed())


def walk_weights(passages: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Each walked passage's weight in the pool: the one ``walk_weight``, whatever its score."""
    return {pid: settings.walk_weight for pid, _ in passages}


def _held(pool: Sequence[dict], passage_id: str) -> dict | None:
    """The pool's candidate for a passage: itself, or its first chunk. One only: every chunk of a long
    passage lifted together would fill the top-k with one passage."""
    return next((c for c in pool if c["id"] == passage_id),
                next((c for c in pool if c.get("passage_id") == passage_id), None))


async def absorb(pool: list[dict], weights: Mapping[str, float], label: str, errors: dict[str, str]) -> None:
    """Join passages to ``pool``: one it holds gets ``label`` noted and its weight lifted to at least
    the given one, the rest are fetched from PostgreSQL. A store that fails is a strategy error."""
    missing = [pid for pid in weights if _held(pool, pid) is None]
    try:
        fetched = await postgres.fetch_sources(missing) if missing else {}
    except Exception as exc:  # noqa: BLE001 — recorded in strategy_errors
        logger.warning("%s: fetching passages failed: %s", label, exc)
        errors[label] = repr(exc)[:200]
        fetched = {}
    for pid, weight in weights.items():
        held = _held(pool, pid)
        if held is not None:
            cands.note_found_by(held, label)
            held["weight"] = max(held.get("weight", 0), weight)
        elif pid in fetched:
            pool.append({**fetched[pid], "source_strategy": label, "weight": weight, "found_by": [label]})


def _only_walked(candidate: dict) -> bool:
    return cands.labels_of(candidate) == [LABEL]


def with_slot(ranked: list[dict], pool: Sequence[dict], k: int) -> list[dict]:
    """``ranked`` with its last place given to the walk, when it is full and the walk has not got one yet."""
    if len(ranked) < k or ranked[-1].get("source_strategy") in _A_ROUTES_OWN_PLACE or any(map(_only_walked, ranked)):
        return ranked
    rest = ranked[:-1]
    found = [c for c in pool if LABEL in cands.labels_of(c) and "rerank_score" in c
             and not any(cands.shares_verse(c, kept) or c["id"] == kept["id"] for kept in rest)]
    if not found:
        return ranked
    return [*rest, max(found, key=lambda c: c["rerank_score"])]
