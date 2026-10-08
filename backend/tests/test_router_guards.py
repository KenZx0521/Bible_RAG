"""Legacy router behaviour R1 keeps, one guard each (ported from the deleted
test_event_registry, test_found_by and test_graph_strategies).

- the event lane runs on R4/R5 only, and only after a full top-k;
- an appended anchor the pool already held keeps that provenance;
- book anchors note themselves on pool hits, and on multi-book questions raise
  only each book's first new hit;
- multi-book rankings keep one book anchor per book;
- R5 asks for chapters only when the question names one;
- with the graph off, stats list no graph strategy.
"""

import asyncio
from types import SimpleNamespace

import pytest

from router_fakes import cand, fake_dense, no_supplement, run
from utils.retrieval import router, routes
from utils.signal_detector import QuerySignals

EVENT_QUESTION = "保羅歸主的經過"


def _core(n=5):
    return [cand(f"ps:rom.{i}.1", "semantic", 0.7, book="rom", chapter=i) for i in range(1, n + 1)]


@pytest.fixture
def forced(active, scores, monkeypatch):
    """``forced.route(signals)`` makes the router take that route, gathering ``forced.pool``."""
    state = SimpleNamespace(pool=_core(), fetched=[])

    def route(signals):
        async def handler(inp):
            return [dict(c) for c in state.pool], ["semantic"], {}
        monkeypatch.setattr(router, "detect_signals", lambda **kw: signals)
        monkeypatch.setitem(routes.ROUTES, signals.route, handler)

    async def content(record_id):
        state.fetched.append(record_id)
        return cand(record_id, "x", 0.0)

    monkeypatch.setattr(router.postgres, "get_content_by_id", content)
    state.route = route
    return state


@pytest.mark.parametrize("route, appended", [
    ("R4", True), ("R5", True), ("R1", False), ("R2", False), ("R3", False), ("R6", False),
    ("fallback", False)])
def test_the_event_lane_runs_on_event_routes_only(forced, route, appended):
    forced.route(QuerySignals(route=route))

    ranked, stats = run(query=EVENT_QUESTION, top_k=5)

    assert [c["id"] for c in ranked[5:]] == (["ps:act.9.1"] if appended else [])
    assert stats["event_registry_events"] == (["ev0002"] if appended else [])


@pytest.mark.parametrize("size", [0, 3])
def test_a_short_core_gets_no_anchor(forced, size):
    forced.pool = _core(size)
    forced.route(QuerySignals(route="R5"))

    ranked, stats = run(query=EVENT_QUESTION, top_k=5)

    assert [c["id"] for c in ranked] == [c["id"] for c in _core(size)]
    assert stats["event_registry_events"] == [] and forced.fetched == []


def test_an_anchor_from_the_pool_keeps_its_dense_provenance(forced, scores):
    forced.pool = _core() + [cand("ps:act.9.1", "semantic", 0.7)]
    scores["ps:act.9.1"] = 0.0
    forced.route(QuerySignals(route="R4"))

    ranked, _ = run(query=EVENT_QUESTION, top_k=5)

    assert ranked[5]["id"] == "ps:act.9.1"
    assert ranked[5]["found_by"] == ["semantic", "event_registry"]


@pytest.mark.parametrize("use_graph, listed", [(True, ["event_registry"]), (False, [])])
def test_stats_list_graph_strategies_only_when_the_graph_is_on(forced, use_graph, listed):
    forced.route(QuerySignals(route="R3"))

    _, stats = run(query="q", top_k=5, use_graph=use_graph)

    assert stats["graph_strategies"] == listed and stats["use_graph"] is use_graph


def test_multi_book_rankings_keep_one_book_anchor_per_book(forced, scores):
    forced.pool = [cand("ps:rev.1.1", "book_anchor", 0.9, book="rev", chapter=1),
                   cand("ps:rev.2.1", "book_anchor", 0.9, book="rev", chapter=2),
                   cand("ps:eph.1.1", "semantic", 0.65, book="eph", chapter=1)]
    scores.update({"ps:rev.1.1": 0.9, "ps:rev.2.1": 0.8, "ps:eph.1.1": 0.5})
    forced.route(QuerySignals(route="R5", detected_book_names=("啟示錄", "以弗所書"),
                              detected_book_ids=("rev", "eph")))

    ranked, _ = run(query="q", top_k=3)

    assert [c["id"] for c in ranked] == ["ps:rev.1.1", "ps:eph.1.1", "ps:rev.2.1"]


def _anchor(monkeypatch, books, hits_by_book, pool=()):
    fake_dense(monkeypatch, hits_by_book=hits_by_book)
    names, book_ids = zip(*books)
    signals = QuerySignals(detected_book_names=names, detected_book_ids=book_ids)
    inp = routes.RouteInput("q", [], signals)
    return asyncio.run(routes._book_anchor(inp, "R4", list(pool), [], {}))


def test_book_anchors_note_themselves_on_hits_the_pool_already_holds(monkeypatch):
    pool = [cand("ps:zec.9.1", "semantic", 0.7, book="zec")]
    hits = [cand("ps:zec.9.1", book="zec"), cand("ps:zec.9.9", book="zec")]

    new = _anchor(monkeypatch, [("撒迦利亞書", "zec")], {"zec": hits}, pool)

    assert [c["id"] for c in new] == ["ps:zec.9.9"]
    assert pool[0]["found_by"] == ["semantic", "book_anchor"]


def test_multi_book_anchors_raise_only_each_book_s_first_new_hit(monkeypatch):
    hits = {b: [cand(f"ps:{b}.1.1", weight=0.6, book=b), cand(f"ps:{b}.2.1", weight=0.6, book=b)]
            for b in ("rom", "gal")}

    multi = _anchor(monkeypatch, [("羅馬書", "rom"), ("加拉太書", "gal")], hits)
    single = _anchor(monkeypatch, [("羅馬書", "rom")], hits)

    assert [(c["id"], c["weight"]) for c in multi] == [
        ("ps:rom.1.1", 0.9), ("ps:rom.2.1", 0.6), ("ps:gal.1.1", 0.9), ("ps:gal.2.1", 0.6)]
    assert [c["weight"] for c in single] == [0.9, 0.9]


def test_r5_asks_for_chapters_only_when_the_question_names_one(active, monkeypatch):
    asked = []

    async def verses(refs):
        asked.append(list(refs))
        return []

    monkeypatch.setattr(routes, "retrieve_by_verse_refs", verses)
    fake_dense(monkeypatch, hits=_core())
    no_supplement(monkeypatch)
    signals = QuerySignals(route="R5")

    pool, strategies, errors = asyncio.run(routes.route_r5(routes.RouteInput("q", [], signals)))

    assert asked == [] and "sql_chapter" not in strategies and errors == {}
    assert len(pool) == 5
