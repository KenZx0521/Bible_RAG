"""found_by: every strategy that returned a passage, not just the one whose copy
won dedup (2026-10 graph audit: `_dedup` overwrote the label, so 41% of
graph-labelled top-5 slots were passages dense had already retrieved, and
`Source.strategy` could not say whether a passage was graph-only).

found_by is provenance only — it must never change which passages are kept,
their weights, or their order.
"""

import asyncio

from utils.retrieval import router
from utils.signal_detector import QuerySignals


def _c(cid: str, strategy: str, weight: float) -> dict:
    return {"id": cid, "source_strategy": strategy, "weight": weight, "content": cid}


def _legacy_dedup(candidates: list[dict]) -> list[dict]:
    """The pre-found_by algorithm, kept here as the behavioural reference."""
    seen: dict[str, dict] = {}
    for c in candidates:
        cid = c["id"]
        if cid not in seen or c["weight"] > seen[cid]["weight"]:
            seen[cid] = c
    return list(seen.values())


def test_dedup_records_every_strategy_in_first_seen_order():
    out = router._dedup([
        _c("gen:1:0", "semantic", 0.7),
        _c("gen:1:0", "graph_event", 0.85),
        _c("gen:2:0", "semantic", 0.7),
    ])

    assert [(c["id"], c["source_strategy"], c["found_by"]) for c in out] == [
        ("gen:1:0", "graph_event", ["semantic", "graph_event"]),
        ("gen:2:0", "semantic", ["semantic"]),
    ]


def test_dedup_keeps_same_passages_weights_and_order_as_before():
    pool = [
        _c("a:1:0", "semantic", 0.7), _c("b:1:0", "graph_event", 0.85),
        _c("a:1:0", "graph_person", 0.9), _c("c:1:0", "semantic", 0.7),
        _c("b:1:0", "semantic", 0.7), _c("a:1:0", "semantic", 0.6),
    ]
    expected = [(c["id"], c["weight"], c["source_strategy"])
                for c in _legacy_dedup([dict(c) for c in pool])]

    out = router._dedup([dict(c) for c in pool])

    assert [(c["id"], c["weight"], c["source_strategy"]) for c in out] == expected


def test_second_dedup_pass_keeps_earlier_provenance():
    """R5 dedups twice; labels gathered by the first pass must survive the second."""
    first = router._dedup([_c("gen:1:0", "semantic", 0.65), _c("gen:1:0", "book_anchor", 0.9)])
    out = router._dedup(first + [_c("gen:1:0", "graph_event", 0.85)])

    assert out[0]["found_by"] == ["semantic", "book_anchor", "graph_event"]


def test_post_dedup_expansion_labels_passages_already_in_pool(monkeypatch):
    """cross_ref_expand returning a passage dense already had must say so."""
    async def semantic(query):
        return [_c("gen:1:0", "semantic", 0.7)]

    async def cross_ref_seeds(cands, existing, use_graph, errors, label):
        return [_c("gen:1:0", "cross_ref_expand", 0.6), _c("gen:9:0", "cross_ref_expand", 0.6)]

    async def nothing(*args, **kwargs):
        return []

    monkeypatch.setattr(router, "_get_semantic", semantic)
    monkeypatch.setattr(router, "_expand_via_cross_ref_seeds", cross_ref_seeds)
    monkeypatch.setattr(router, "_expand_via_entity_query", nothing)
    monkeypatch.setattr(router, "_sql_supplement", nothing)

    pool, _, _ = asyncio.run(router._route_r4(
        query="q", verse_refs=[], entity_names=[], signals=QuerySignals(route="R4"),
        k=5, use_graph=True, graph_strategies=frozenset({"cross_ref_expand"}),
    ))

    by_id = {c["id"]: c for c in pool}
    assert by_id["gen:1:0"]["found_by"] == ["semantic", "cross_ref_expand"]
    assert by_id["gen:1:0"]["source_strategy"] == "semantic"  # label of the kept copy unchanged
    # new passages get found_by filled in by retrieve_and_rerank
    assert router._labels_of(by_id["gen:9:0"]) == ["cross_ref_expand"]


def test_book_anchor_labels_passages_already_in_pool(monkeypatch):
    async def semantic(query, top_k=20, book_filter=None):
        return [_c("zec:9:1", "semantic", 0.7), _c("zec:9:2", "semantic", 0.7)]

    monkeypatch.setattr(router, "retrieve_semantic", semantic)
    pool = [_c("zec:9:1", "semantic", 0.7)]

    new = asyncio.run(router._expand_via_book_anchor(
        "q", ["撒迦利亞書"], {"zec:9:1"}, {}, "R4", pool=pool,
    ))

    assert [c["id"] for c in new] == ["zec:9:2"]
    assert pool[0]["found_by"] == ["semantic", "book_anchor"]


def test_retrieve_and_rerank_gives_every_result_found_by(monkeypatch):
    """Routes that never dedup (R1 verse_direct) still report provenance."""
    async def r1(**kwargs):
        return [_c("jhn:3:16", "verse_direct", 1.0)], ["verse_direct"], {}

    monkeypatch.setattr(router, "_route_r1", r1)
    monkeypatch.setattr(router, "detect_signals", lambda **kw: QuerySignals(route="R1"))

    ranked, _ = asyncio.run(router.retrieve_and_rerank(
        query="q", verse_refs=[], intent_type="verse", entity_names=[],
    ))

    assert ranked[0]["found_by"] == ["verse_direct"]


def test_query_response_exposes_found_by(monkeypatch):
    from models.request import QueryRequest
    from routers import query as query_mod

    async def intent(question):
        return {"type": "event", "entities": [], "verse_refs": [], "keywords": []}

    async def retrieve(**kwargs):
        hit = _c("act:9:0", "graph_event", 0.85)
        hit["found_by"] = ["semantic", "graph_event"]
        return [hit], {"strategies_used": ["semantic", "graph_event"], "route_used": "R4"}

    monkeypatch.setattr(query_mod, "classify_intent", intent)
    monkeypatch.setattr(query_mod, "retrieve_and_rerank", retrieve)

    resp = asyncio.run(query_mod.rag_query(QueryRequest(question="q", retrieval_only=True)))

    assert resp.sources[0].found_by == ["semantic", "graph_event"]
