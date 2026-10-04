"""Event registry auxiliary lane (2026-10 graph audit §3.3).

The graph contributes to event questions only by APPENDING one curated anchor
after the untouched dense top-k; it never competes for a top-k slot. Triggers
are exact registry keywords in the question with book names masked, on R4/R5
only. LLM keywords cannot trigger it.
"""

import asyncio

import pytest

from config import Settings
from models.request import QueryRequest
from utils.retrieval import event_registry as reg
from utils.retrieval import router
from utils.signal_detector import QuerySignals


def _ev(eid: str, triggers: list[str], anchors: list[str]) -> reg.RegistryEvent:
    return reg.RegistryEvent(id=eid, name=eid, triggers=tuple(triggers), anchors=tuple(anchors))


# --- the shipped registry file ----------------------------------------------

def test_shipped_registry_is_well_formed():
    events = reg.load_registry()

    assert events, "registry is empty"
    assert len({e.id for e in events}) == len(events)
    for e in events:
        assert e.triggers and e.anchors, e.id
        assert all(reg.PERICOPE_ID.fullmatch(a) for a in e.anchors), e.id


def test_shipped_triggers_survive_book_masking():
    """A trigger containing a book name could never fire once books are masked."""
    for e in reg.load_registry():
        for t in e.triggers:
            assert reg.mask_book_names(t) == t, (e.id, t)


def test_load_rejects_malformed_anchor(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text('{"events": [{"id": "e", "name": "e", "triggers": ["x"], "anchors": ["act 9"]}]}')
    with pytest.raises(ValueError, match="act 9"):
        reg.load_registry(bad)


# --- matching ----------------------------------------------------------------

def test_match_orders_most_specific_event_first():
    events = (
        _ev("hub", ["保羅歸主"], ["act:9:0", "act:9:1", "act:22:1"]),
        _ev("exact", ["保羅歸主"], ["act:9:0"]),
        _ev("other", ["五旬節"], ["act:2:0"]),
    )

    matched = reg.match_events("保羅歸主的經過是什麼？", events)

    assert [e.id for e in matched] == ["exact", "hub"]


def test_match_ignores_trigger_inside_book_name():
    events = (_ev("lev", ["利未"], ["lev:1:0"]),)

    assert reg.match_events("利未記中的贖罪祭是什麼？", events) == []
    assert [e.id for e in reg.match_events("利未人的職責是什麼？", events)] == ["lev"]


def test_select_skips_anchors_already_in_core_including_their_chunks():
    events = [_ev("a", ["x"], ["act:9:0", "act:9:1", "act:9:2"])]

    picks = reg.select_aux_anchors(events, ["act:9:0", "act:9:1:2"], slots=1)

    assert picks == [("a", "act:9:2")]


def test_select_takes_one_anchor_per_event_up_to_slots():
    events = [_ev("a", ["x"], ["gen:1:0", "gen:1:1"]), _ev("b", ["y"], ["exo:1:0"])]

    assert reg.select_aux_anchors(events, [], slots=1) == [("a", "gen:1:0")]
    assert reg.select_aux_anchors(events, [], slots=2) == [("a", "gen:1:0"), ("b", "exo:1:0")]


def test_select_returns_nothing_when_core_already_has_every_anchor():
    events = [_ev("a", ["x"], ["gen:1:0"])]

    assert reg.select_aux_anchors(events, ["gen:1:0"], slots=1) == []


# --- strategy plumbing -------------------------------------------------------

def test_all_keeps_round3_meaning_and_excludes_the_auxiliary_lane():
    assert "event_registry" not in router.resolve_graph_strategies(["all"])
    assert router.resolve_graph_strategies(["all", "event_registry"]) == (
        router.GRAPH_STRATEGIES | {"event_registry"}
    )


def test_request_and_settings_accept_event_registry():
    assert QueryRequest(question="q", graph_strategies=["event_registry"]).graph_strategies == ["event_registry"]
    assert Settings(_env_file=None, rag_graph_strategies=["event_registry"]).rag_graph_strategies == ["event_registry"]


# --- router integration ------------------------------------------------------

def _core(n: int = 5) -> list[dict]:
    return [
        {"id": f"act:{i}:0", "content": "x", "weight": 0.7, "source_strategy": "semantic",
         "rerank_score": 0.9 - i / 100}
        for i in range(1, n + 1)
    ]


def _wire(monkeypatch, route: str, pool: list[dict], events=None, fetch=None):
    async def handler(**kwargs):
        return [dict(c) for c in pool], ["semantic"], {}

    def rerank(query, candidates, top_k, text_key):
        return sorted(candidates, key=lambda c: -c["rerank_score"])[:top_k]

    async def content(record_id):
        return {"content": f"text {record_id}", "title": "t", "book_name": "使徒行傳",
                "chapter_num": int(record_id.split(":")[1]), "metadata": {"verse_range": "1-3"}}

    monkeypatch.setattr(router, f"_route_{route.lower()}", handler)
    monkeypatch.setattr(router, "detect_signals", lambda **kw: QuerySignals(route=route))
    monkeypatch.setattr(router.reranker_mod, "rerank", rerank)
    monkeypatch.setattr(router.postgres, "get_content_by_id", fetch or content)
    monkeypatch.setattr(router.event_registry, "load_registry", lambda path=None: tuple(
        events if events is not None else [_ev("conv", ["保羅歸主"], ["act:9:0", "act:9:1"])]
    ))


def _query(**kwargs):
    return asyncio.run(router.retrieve_and_rerank(
        query=kwargs.pop("query", "保羅歸主的經過？"), verse_refs=[], intent_type="event",
        entity_names=[], top_k=5, **kwargs,
    ))


def test_registry_appends_after_untouched_core(monkeypatch):
    _wire(monkeypatch, "R4", _core())
    baseline, _ = _query(graph_strategies=[])

    ranked, stats = _query(graph_strategies=["event_registry"])

    assert [c["id"] for c in ranked[:5]] == [c["id"] for c in baseline]
    aux = ranked[5]
    assert (aux["id"], aux["source_strategy"], aux["found_by"]) == ("act:9:0", "event_registry", ["event_registry"])
    assert aux["content"] == "text act:9:0" and aux["chapter_num"] == 9
    assert aux.get("rerank_score") is None and aux.get("fused_score") is None
    assert stats["event_registry_events"] == ["conv"]
    assert "event_registry" in stats["strategies_used"]
    assert stats["reranked_top_k"] == 5  # appended passages are not reranked


def test_registry_aux_from_pool_keeps_dense_provenance(monkeypatch):
    """An anchor dense retrieved but ranked below k keeps its found_by, plus the registry."""
    pool = _core() + [{"id": "act:9:0", "content": "x", "weight": 0.7,
                       "source_strategy": "semantic", "rerank_score": 0.1}]
    _wire(monkeypatch, "R5", pool)

    ranked, _ = _query(graph_strategies=["event_registry"])

    assert ranked[5]["found_by"] == ["semantic", "event_registry"]


@pytest.mark.parametrize("route", ["R1", "R2", "R3", "R6", "fallback"])
def test_registry_only_runs_on_event_routes(monkeypatch, route):
    _wire(monkeypatch, route, _core())

    ranked, stats = _query(graph_strategies=["event_registry"])

    assert len(ranked) == 5
    assert stats["event_registry_events"] == []


@pytest.mark.parametrize("kwargs", [
    {"graph_strategies": ["graph_event"]},
    {"graph_strategies": ["event_registry"], "use_graph": False},
])
def test_registry_off_unless_requested_with_graph_on(monkeypatch, kwargs):
    _wire(monkeypatch, "R4", _core())

    ranked, _ = _query(**kwargs)

    assert len(ranked) == 5


def test_llm_keywords_cannot_trigger_registry(monkeypatch):
    _wire(monkeypatch, "R4", _core())

    ranked, stats = _query(query="掃羅在路上發生了什麼？", keywords=["保羅歸主"],
                           graph_strategies=["event_registry"])

    assert len(ranked) == 5
    assert stats["event_registry_events"] == []


def test_registry_reports_triggered_events_even_when_core_has_every_anchor(monkeypatch):
    _wire(monkeypatch, "R4", _core(), events=[_ev("conv", ["保羅歸主"], ["act:1:0"])])

    ranked, stats = _query(graph_strategies=["event_registry"])

    assert len(ranked) == 5
    assert stats["event_registry_events"] == ["conv"]


def test_registry_fetch_failure_is_reported_not_raised(monkeypatch):
    async def boom(record_id):
        raise RuntimeError("pg down")

    _wire(monkeypatch, "R4", _core(), fetch=boom)

    ranked, stats = _query(graph_strategies=["event_registry"])

    assert len(ranked) == 5
    assert "pg down" in stats["strategy_errors"]["event_registry"]


def test_registry_skips_when_core_is_empty(monkeypatch):
    """A failed dense retrieval must stay an empty (invalid) result, not become registry-only."""
    _wire(monkeypatch, "R4", [])

    ranked, stats = _query(graph_strategies=["event_registry"])

    assert ranked == []
    assert stats["event_registry_events"] == []


def test_registry_skips_when_core_is_short(monkeypatch):
    """An anchor appended to a short core would sit inside the top-k."""
    _wire(monkeypatch, "R5", _core(3))

    ranked, _ = _query(graph_strategies=["event_registry"])

    assert [c["source_strategy"] for c in ranked] == ["semantic"] * 3
