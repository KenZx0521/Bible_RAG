"""Per-strategy graph gating (2026-10 graph-value diagnosis).

use_graph=True no longer means "every graph strategy injects candidates":
only the strategies named in settings.rag_graph_strategies (or the per-request
graph_strategies override) run. graph_event was the one in-pool strategy
whose injected passages beat the passages they displaced; since 2026-10-04 the
default is the event_registry auxiliary lane, which enters no pool at all.
"""

import asyncio
from typing import get_args

import pytest
from pydantic import ValidationError

from config import GraphStrategyName, Settings, settings
from models.request import QueryRequest
from utils.retrieval import router
from utils.signal_detector import QuerySignals


def _calls() -> dict[str, int]:
    return {}


def _patch_retrievers(monkeypatch, calls: dict[str, int]) -> None:
    """Replace every retriever a route can reach with call-counting stubs."""

    def counted(name, result=None):
        async def _stub(*args, **kwargs):
            calls[name] = calls.get(name, 0) + 1
            return list(result or [])
        return _stub

    sem = [{"id": "gen:1:0", "weight": 0.7, "content": "x"}]
    monkeypatch.setattr(router, "_get_semantic", counted("semantic", sem))
    monkeypatch.setattr(router, "retrieve_by_entities", counted("graph_person"))
    monkeypatch.setattr(router, "retrieve_by_events", counted("graph_event"))
    monkeypatch.setattr(router, "retrieve_by_places", counted("graph_place"))
    monkeypatch.setattr(router, "retrieve_via_cross_references", counted("cross_reference"))
    monkeypatch.setattr(router, "retrieve_cross_references", counted("cross_reference"))
    monkeypatch.setattr(router, "_expand_via_book_anchor", counted("book_anchor"))
    monkeypatch.setattr(router, "_sql_supplement", counted("sql_supplement"))

    async def entity_path(names, use_graph, errors, label, type_filter=None):
        if use_graph:
            calls["entity_path"] = calls.get("entity_path", 0) + 1
        return []

    async def cross_ref_seeds(cands, existing, use_graph, errors, label):
        if use_graph:
            calls["cross_ref_expand"] = calls.get("cross_ref_expand", 0) + 1
        return []

    async def entity_query(query, existing, use_graph, errors, label, deduped=None):
        if use_graph:
            calls["entity_query"] = calls.get("entity_query", 0) + 1
        return []

    monkeypatch.setattr(router, "_expand_via_entity_path", entity_path)
    monkeypatch.setattr(router, "_expand_via_cross_ref_seeds", cross_ref_seeds)
    monkeypatch.setattr(router, "_expand_via_entity_query", entity_query)


def _run(handler, signals, graph_strategies, entity_names=None, use_graph=True):
    return asyncio.run(handler(
        query="q",
        verse_refs=[],
        entity_names=entity_names or [],
        signals=signals,
        k=5,
        use_graph=use_graph,
        graph_strategies=frozenset(graph_strategies),
    ))


# --- strategy resolution -----------------------------------------------------

def test_default_setting_is_the_event_registry_lane_only():
    # Field default, not the loaded value: a developer's .env may override it.
    # 2026-10-04: graph_event (in-pool) replaced by the event_registry auxiliary
    # lane, which never changes the top-k (evaluation/experiments/
    # 2026-10-03_event_registry/results.md).
    assert Settings.model_fields["rag_graph_strategies"].default == ["event_registry"]


def test_unknown_strategy_in_settings_fails_at_startup():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_graph_strategies=["graph_evnt"])


def test_settings_parse_json_array_from_env(monkeypatch):
    monkeypatch.setenv("RAG_GRAPH_STRATEGIES", '["all"]')
    assert Settings(_env_file=None).rag_graph_strategies == ["all"]


def test_resolve_none_falls_back_to_settings(monkeypatch):
    monkeypatch.setattr(settings, "rag_graph_strategies", ["graph_event", "graph_person"])
    assert router.resolve_graph_strategies(None) == frozenset({"graph_event", "graph_person"})


def test_resolve_all_expands_to_every_graph_strategy():
    assert router.resolve_graph_strategies(["all"]) == router.GRAPH_STRATEGIES


def test_resolve_empty_list_disables_every_graph_strategy():
    assert router.resolve_graph_strategies([]) == frozenset()


def test_resolve_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="bogus"):
        router.resolve_graph_strategies(["graph_event", "bogus"])


def test_resolve_rejects_unknown_strategy_alongside_all():
    with pytest.raises(ValueError, match="bogus"):
        router.resolve_graph_strategies(["all", "bogus"])


def test_router_strategy_set_derives_from_the_literal():
    assert set(get_args(GraphStrategyName)) == (
        set(router.GRAPH_STRATEGIES) | set(router.AUXILIARY_STRATEGIES) | {"all"}
    )
    assert len(router.GRAPH_STRATEGIES) == 8  # in-pool strategies, unchanged since Round 3
    assert router.AUXILIARY_STRATEGIES == {"event_registry"}


def test_request_rejects_unknown_strategy_name():
    with pytest.raises(ValidationError):
        QueryRequest(question="q", graph_strategies=["bogus"])


# --- route gating ------------------------------------------------------------

def test_r3_with_graph_event_only_runs_no_person_graph(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_persons=["摩西", "亞倫"], route="R3")

    _, strategies, _ = _run(router._route_r3, signals, {"graph_event"})

    for name in ("graph_person", "entity_path", "cross_ref_expand", "entity_query"):
        assert name not in calls, name
    assert "graph_person" not in strategies
    assert calls["semantic"] == 1


def test_r3_runs_person_graph_when_enabled(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_persons=["摩西", "亞倫"], route="R3")

    _run(router._route_r3, signals, {"graph_person", "entity_path"})

    assert calls["graph_person"] == 1
    assert calls["entity_path"] == 1
    assert "cross_ref_expand" not in calls
    assert "entity_query" not in calls


def test_r4_runs_graph_event_but_not_supplements(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_events=["出埃及"], route="R4")

    _run(router._route_r4, signals, {"graph_event"})

    assert calls["graph_event"] == 1
    assert "cross_ref_expand" not in calls
    assert "entity_query" not in calls


def test_r5_keeps_graph_event_and_skips_cross_ref_and_entity_traversal(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_events=["大使命"], route="R5")

    _run(router._route_r5, signals, {"graph_event"}, entity_names=["耶穌"])

    assert calls["graph_event"] == 1
    assert "graph_person" not in calls  # R5 `graph` uses retrieve_by_entities
    assert "cross_reference" not in calls
    assert "entity_query" not in calls


def test_r5_entity_traversal_runs_when_graph_enabled(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(route="R5")

    _run(router._route_r5, signals, {"graph", "cross_reference"}, entity_names=["耶穌"])

    assert calls["graph_person"] == 1
    assert calls["cross_reference"] == 1


def test_r6_with_graph_event_only_runs_no_place_graph(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_places=["耶路撒冷"], route="R6")

    _run(router._route_r6, signals, {"graph_event"})

    for name in ("graph_place", "entity_path", "cross_ref_expand", "entity_query"):
        assert name not in calls, name


def test_use_graph_false_still_disables_everything(monkeypatch):
    calls = _calls()
    _patch_retrievers(monkeypatch, calls)
    signals = QuerySignals(detected_events=["出埃及"], route="R4")

    _run(router._route_r4, signals, router.GRAPH_STRATEGIES, use_graph=False)

    assert "graph_event" not in calls
    assert "entity_query" not in calls


# --- provenance --------------------------------------------------------------

def test_stats_report_effective_graph_strategies(monkeypatch):
    async def no_candidates(**kwargs):
        return [], ["semantic"], {}

    monkeypatch.setattr(router, "_route_fallback", no_candidates)
    monkeypatch.setattr(router, "detect_signals", lambda **kw: QuerySignals(route="fallback"))

    _, stats = asyncio.run(router.retrieve_and_rerank(
        query="q", verse_refs=[], intent_type="topic", entity_names=[],
        graph_strategies=["graph_person", "graph_event"],
    ))

    assert stats["graph_strategies"] == ["graph_event", "graph_person"]


@pytest.mark.parametrize("kwargs", [{"use_graph": False}, {"semantic_only": True}])
def test_stats_report_no_graph_strategies_when_graph_is_off(monkeypatch, kwargs):
    async def no_candidates(**kw):
        return [], ["semantic"], {}

    async def no_semantic(query):
        return []

    monkeypatch.setattr(router, "_route_fallback", no_candidates)
    monkeypatch.setattr(router, "retrieve_semantic", no_semantic)
    monkeypatch.setattr(router, "detect_signals", lambda **kw: QuerySignals(route="fallback"))

    _, stats = asyncio.run(router.retrieve_and_rerank(
        query="q", verse_refs=[], intent_type="topic", entity_names=[], **kwargs,
    ))

    assert stats["graph_strategies"] == []
