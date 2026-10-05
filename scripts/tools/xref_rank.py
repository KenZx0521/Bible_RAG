"""Offline replica of the backend's cross-reference ranking (W1 1B 模擬等於實測).

Mirrors, for one CROSS_REFERENCES edge table held in memory:
  * backend/database/neo4j_db.get_cross_references (legacy, one seed) and
    get_cross_references_multi_hop (one-hop pool, sparse fallback), as of the
    C1 Cypher: curated = coalesce(r.curated, r.source IN markdown/supplementary)
    (neo4j_db._CURATED_XREF), ties broken by apoc.util.md5([target.id]);
  * backend/utils/retrieval/cross_ref_retriever._edge_weight (hop curves).

The weight tables are deliberately duplicated here instead of imported: the
measured side (backend probes/xref_measure) reads them from the real
retriever, so a drift between the two shows up in xref_probe compare.

Pure: no I/O. Rows are (id, hop, curated, weight) tuples in backend order.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable, Mapping

CURATED_SOURCES = ("markdown", "supplementary")
# cross_ref_retriever._HOP_WEIGHT / _TSK_HOP_WEIGHT
HOP_WEIGHT = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}
TSK_HOP_WEIGHT = {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30}
MAX_FALLBACK_HOPS = 4  # neo4j_db: hops = max(2, min(max_hops, 4))

Row = tuple[str, int, bool, float]


def md5_key(pid: str) -> str:
    """apoc.util.md5([pid]): the md5 hex digest of the id's UTF-8 bytes."""
    return hashlib.md5(pid.encode("utf-8")).hexdigest()


def is_curated(curated, source) -> bool:
    """coalesce(r.curated, r.source IN ['markdown', 'supplementary'])."""
    return bool(curated) if curated is not None else source in CURATED_SOURCES


def edge_weight(hop: int, curated: bool) -> float:
    curve = HOP_WEIGHT if curated else TSK_HOP_WEIGHT
    return curve.get(hop, curve[max(curve)])


class XrefIndex:
    """Undirected adjacency: pid -> [(neighbour, curated, votes)], one entry per edge."""

    def __init__(self, adjacency: Mapping[str, list[tuple[str, bool, int | None]]]):
        self.adjacency = adjacency

    @classmethod
    def from_edges(cls, edges: Iterable[Mapping]) -> "XrefIndex":
        """Edges are {a, b, source, curated, votes}; self loops are skipped
        (the Cypher excludes the seed itself as a target)."""
        adjacency: dict[str, list] = defaultdict(list)
        for e in edges:
            if e["a"] == e["b"]:
                continue
            curated = is_curated(e.get("curated"), e.get("source"))
            adjacency[e["a"]].append((e["b"], curated, e.get("votes")))
            adjacency[e["b"]].append((e["a"], curated, e.get("votes")))
        return cls(dict(adjacency))

    def neighbours(self, pid: str):
        return self.adjacency.get(pid, ())


def one_hop(index: XrefIndex, seeds: list[str], limit: int) -> list[Row]:
    """MATCH (seed)-[r]-(target) WHERE NOT target.id IN $ids, per target:
    seed_support = count(DISTINCT seed), curated = any edge curated,
    votes = max(coalesce(r.votes, 0)); ORDER BY seed_support DESC,
    curated DESC, votes DESC, md5; LIMIT."""
    excluded = set(seeds)
    pool: dict[str, list] = {}
    for seed in dict.fromkeys(seeds):
        for target, curated, votes in index.neighbours(seed):
            if target in excluded:
                continue
            agg = pool.setdefault(target, [set(), False, 0])
            agg[0].add(seed)
            agg[1] = agg[1] or curated
            agg[2] = max(agg[2], votes or 0)
    order = sorted(pool, key=lambda t: (-len(pool[t][0]), -int(pool[t][1]), -pool[t][2], md5_key(t)))
    return [(t, 1, pool[t][1], edge_weight(1, pool[t][1])) for t in order[:limit]]


def _shortest_paths(index: XrefIndex, seeds: list[str], hops: int) -> tuple[dict, dict]:
    """BFS from every seed: distance, and whether SOME shortest path back to a
    seed is curated on every edge (the fallback's any(p WHERE p[0] = hop AND p[1]))."""
    dist = dict.fromkeys(seeds, 0)
    all_curated = dict.fromkeys(seeds, True)
    frontier = list(dist)
    for d in range(1, hops + 1):
        reached: dict[str, bool] = {}
        for u in frontier:
            for v, curated, _votes in index.neighbours(u):
                if v not in dist:
                    reached[v] = reached.get(v, False) or (all_curated[u] and curated)
        dist.update(dict.fromkeys(reached, d))
        all_curated.update(reached)
        frontier = list(reached)
    return dist, all_curated


def multi_hop(index: XrefIndex, seeds: list[str], max_hops: int = 2, limit: int = 10) -> list[Row]:
    """get_cross_references_multi_hop: the one-hop rows; only when they cannot
    fill `limit` (and max_hops >= 2), targets 2..hops away that are neither
    seeds nor one-hop rows, ORDER BY hop ASC, curated DESC, md5."""
    if not seeds or max_hops < 1:
        return []
    rows = one_hop(index, seeds, limit)
    if len(rows) >= limit or max_hops < 2:
        return rows
    dist, all_curated = _shortest_paths(index, seeds, max(2, min(max_hops, MAX_FALLBACK_HOPS)))
    exclude = set(seeds) | {r[0] for r in rows}
    cand = sorted((v for v, d in dist.items() if d >= 2 and v not in exclude),
                  key=lambda v: (dist[v], -int(all_curated[v]), md5_key(v)))
    return rows + [(v, dist[v], all_curated[v], edge_weight(dist[v], all_curated[v]))
                   for v in cand[:limit - len(rows)]]


def legacy(index: XrefIndex, pid: str, limit: int = 10) -> list[Row]:
    """get_cross_references(pid): one seed, so seed_support is always 1."""
    return one_hop(index, [pid], limit)
