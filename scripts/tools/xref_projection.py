"""Offline projection of the CROSS_REFERENCES table that Steps 5 and 9 build
(W1 1B; xref_probe expect / fingerprint, plan §3 期望檔先行).

Step 5 (import_neo4j) MERGEs one edge per CROSS_REFERENCES row of
neo4j_relationships.jsonl and SETs the row's properties; it refuses a
duplicate pair. Step 9 (import_tsk_crossrefs) refuses a graph with an edge
whose curated or tsk is unset, then MERGEs every TSK pericope pair:
ON CREATE source 'tsk', curated false; on every pair votes, verse_pairs and
tsk = true. step5_edges and step9_edges replay both on an empty graph, refusing
what the pipeline refuses. summarize gives the expect file's counts, the keys
of diff_kg's xref_provenance section and curated_xrefs.edge_fingerprint, all
of which xref_probe fingerprint also reads from a live graph.

Pure: no I/O (PROVENANCE_CYPHER is only a string). Edges are
{(a, b): {source, curated, tsk, votes, verse_pairs}}.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from bible_chunking.curated_xrefs import edge_fingerprint

Pair = tuple[str, str]
FLAGS = ("curated", "tsk")  # Step 9's precondition: neither may be unset
SHOWN = 10
# One row per (source, curated, tsk): the query of diff_kg's xref_provenance section (1B-D1)
PROVENANCE_CYPHER = """
MATCH (:Pericope)-[x:CROSS_REFERENCES]->(:Pericope)
RETURN x.source AS source, x.curated AS curated, x.tsk AS tsk, count(*) AS n"""


def _v(value) -> str:
    """diff_kg._v: '-' for a missing value."""
    return "-" if value is None else str(value)


def provenance_key(source, curated, tsk) -> str:
    """diff_kg's xref_provenance key, e.g. 'source=markdown curated=True tsk=False'."""
    return f"source={_v(source)} curated={_v(curated)} tsk={_v(tsk)}"


def step5_edges(rows: Iterable[Mapping]) -> dict[Pair, dict]:
    """The CROSS_REFERENCES rows as Step 5 writes them. ValueError, naming the
    first SHOWN pairs of each kind, for duplicate pairs and rows without curated or tsk."""
    edges: dict[Pair, dict] = {}
    duplicates: dict[str, None] = {}  # each pair once, however many rows repeat it
    unflagged = []
    for row in rows:
        pair, props = (row["start"], row["end"]), row.get("properties", {})
        if pair in edges:
            duplicates[f"{pair[0]}→{pair[1]}"] = None
        if any(props.get(flag) is None for flag in FLAGS):
            unflagged.append(f"{pair[0]}→{pair[1]}")
        edges[pair] = {key: props.get(key) for key in ("source", "curated", "tsk", "votes", "verse_pairs")}
    problems = [f"{len(pairs)} {what}: {', '.join(pairs[:SHOWN])}" for what, pairs in (
        ("duplicate pairs (import_neo4j refuses them)", list(duplicates)),
        ("rows with curated or tsk unset (Step 9's precondition refuses them)", unflagged)) if pairs]
    if problems:
        raise ValueError("; ".join(problems))
    return edges


def step9_edges(edges: Mapping[Pair, dict], tsk_pairs: Mapping[Pair, Mapping]) -> dict[Pair, dict]:
    """Step 9's MERGE of import_tsk_crossrefs.aggregate_tsk's pairs over `edges`."""
    merged = dict(edges)
    for pair, tsk in tsk_pairs.items():
        base = edges.get(pair, {"source": "tsk", "curated": False})  # ON CREATE
        merged[pair] = {**base, "votes": tsk["votes"], "verse_pairs": tsk["verse_pairs"], "tsk": True}
    return merged


def fingerprint_rows(edges: Mapping[Pair, dict]) -> list[dict]:
    """The rows curated_xrefs.EDGE_FINGERPRINT_CYPHER would return."""
    return [{"a": a, "b": b, **edge} for (a, b), edge in edges.items()]


def edge_rows(edges: Mapping[Pair, dict]) -> list[dict]:
    """xref_probe predict --edges input, sorted by (a, b)."""
    return [{"a": a, "b": b, "source": e["source"], "curated": e["curated"], "votes": e["votes"]}
            for (a, b), e in sorted(edges.items())]


def summarize(curated: Mapping[Pair, dict], tsk_pairs: Mapping[Pair, Mapping],
              edges: Mapping[Pair, dict]) -> dict:
    """counts, xref_provenance, xrefs_by_source and fingerprint of the expect file."""
    attached = len(curated.keys() & tsk_pairs.keys())
    counts = {"curated_rows": len(curated), "attached": attached,
              "curated_without_tsk": len(curated) - attached, "pure_tsk": len(tsk_pairs) - attached,
              "total": len(edges), "votes_edges": sum(e["votes"] is not None for e in edges.values())}
    provenance = Counter(provenance_key(e["source"], e["curated"], e["tsk"]) for e in edges.values())
    by_source = Counter(_v(e["source"]) for e in edges.values())
    return {"counts": counts, "xref_provenance": dict(sorted(provenance.items())),
            "xrefs_by_source": dict(sorted(by_source.items())),
            "fingerprint": edge_fingerprint(fingerprint_rows(edges))}


def live_summary(rows: list[dict], provenance_rows: Iterable[Mapping]) -> dict:
    """{fingerprint, xref_provenance, edges} of a graph, from EDGE_FINGERPRINT_CYPHER's
    rows and PROVENANCE_CYPHER's (source, curated, tsk, n) rows."""
    provenance: Counter = Counter()
    for row in provenance_rows:
        provenance[provenance_key(row["source"], row["curated"], row["tsk"])] += row["n"]
    return {"fingerprint": edge_fingerprint(rows), "xref_provenance": dict(sorted(provenance.items())),
            "edges": len(rows)}


def expectation_problems(live: Mapping, expected: Mapping) -> list[str]:
    """Where a live_summary differs from an expect file (fingerprint, xref_provenance)."""
    if expected.get("version") != 1:
        raise ValueError("not a version-1 expect file")
    problems = []
    if live["fingerprint"] != expected["fingerprint"]:
        problems.append(f"fingerprint differs: {live['fingerprint']} on the target, "
                        f"{expected['fingerprint']} expected")
    got, want = live["xref_provenance"], expected["xref_provenance"]
    for key in sorted(got.keys() | want.keys()):
        if got.get(key, 0) != want.get(key, 0):
            problems.append(f"xref_provenance {key}: {got.get(key, 0):,}, expected {want.get(key, 0):,}")
    return problems
