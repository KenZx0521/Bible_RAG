"""Routing, ranking, pins and the event-registry lane, on fake retrievers.

Only Neo4j-free strategies remain (R1): dense, verse/chapter SQL, book anchors,
SQL supplement, rerank + fusion, the chapter and book-anchor pins, and the event
registry appended after the finished top-k on R4/R5.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config import settings
from ragcommon import routing
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import reranker
from utils.retrieval import candidates as cands
from utils.retrieval import event_registry as reg
from utils.retrieval import pins, router, routes
from utils.verse_parser import VerseRef

BACKEND = Path(__file__).resolve().parents[1]
FROZEN = BACKEND.parent / "config" / "registries" / "routing_lexicon.legacy.json"
EVENT = reg.RegistryEvent("event:saoluo", "ev0003", "掃羅歸主", ("保羅歸主",),
                          ("ps:act.9.1", "ps:act.9.3b"))


def _c(cid, strategy="hybrid_hybrid", weight=0.7, book="act", chapter=9, **extra):
    return {"id": cid, "source_strategy": strategy, "weight": weight, "content": cid,
            "book_id": book, "book_name": book, "chapter_num": chapter, "title": "",
            "verse_range": "1", "kind": "passage", "passage_id": cid, **extra}


@pytest.fixture
def active():
    lexicon = routing.load_lexicon(FROZEN)
    build = Build("b20261008_1bb6912e", "bb20261008_1bb6912e", "passages__b", Path("/c"), False, 9)
    context.install(context.make_active(build, lexicon, (EVENT,)), Handshake(build.build_id, (), True))
    yield
    context.reset()


@pytest.fixture
def scores(monkeypatch):
    """rerank_score = table[id] (0.5 when absent), sorted like the real reranker."""
    table = {}

    def rerank(query, passages, top_k=5, text_key="content"):
        for p in passages:
            p["rerank_score"] = table.get(p["id"], 0.5)
        return sorted(passages, key=lambda p: p["rerank_score"], reverse=True)[:top_k]

    monkeypatch.setattr(reranker, "rerank", rerank)
    return table


def _dense(monkeypatch, hits_by_book=None, hits=()):
    calls = []

    async def fake(query, arm, top_k=None, book_ids=None):
        calls.append((arm.label, top_k, book_ids))
        found = (hits_by_book or {}).get(book_ids[0], []) if book_ids else list(hits)
        return [{**c, "source_strategy": arm.label} for c in found]

    monkeypatch.setattr(routes, "retrieve_dense", fake)
    monkeypatch.setattr(router, "retrieve_dense", fake)
    return calls


def _no_supplement(monkeypatch):
    async def chapter_passages(book_id, chapter):
        return []
    monkeypatch.setattr(routes.postgres, "chapter_passages", chapter_passages)


def _run(**kwargs):
    defaults = {"verse_refs": [], "intent_type": "topic", "entity_names": []}
    return asyncio.run(router.retrieve_and_rerank(**{**defaults, **kwargs}))


# --- pool bookkeeping ------------------------------------------------------------------

def test_dedup_keeps_the_heaviest_copy_and_records_every_strategy():
    out = cands.dedup([_c("ps:a.1.1", "semantic", 0.7), _c("ps:a.1.1", "sql_chapter", 0.85),
                       _c("ps:a.2.1", "semantic", 0.7), _c("ps:a.1.1", "book_anchor", 0.85)])

    assert [(c["id"], c["source_strategy"], c["found_by"]) for c in out] == [
        ("ps:a.1.1", "sql_chapter", ["semantic", "sql_chapter", "book_anchor"]),
        ("ps:a.2.1", "semantic", ["semantic"])]


def test_book_chapters_follow_first_appearance():
    pool = [_c("1", book="act", chapter=26), _c("2", book="gal", chapter=1),
            _c("3", book="act", chapter=26), _c("4", book="act", chapter=22)]

    assert cands.book_chapters(pool) == [("act", 26), ("gal", 1), ("act", 22)]


def test_chapter_pins_follow_verse_ref_order_across_hash_seeds():
    code = (
        "from utils.retrieval import pins\n"
        "from utils.verse_parser import VerseRef\n"
        "refs = [VerseRef('jhn', '約翰福音', 1), VerseRef('gen', '創世記', 1)]\n"
        "ranked = [{'id': f'ps:rom.{i}.1', 'book_id': 'rom', 'chapter_num': i, 'rerank_score': 0.5}"
        " for i in range(1, 6)]\n"
        "pool = ranked + [{'id': f'ps:{b}.1.{j}', 'book_id': b, 'chapter_num': 1, 'weight': 0.9}\n"
        "                 for b in ('gen', 'jhn') for j in range(1, 4)]\n"
        "print([c['id'] for c in pins.pin_chapter_candidates(ranked, pool, refs, top_k=5)])\n"
    )
    path = os.pathsep.join([str(BACKEND), str(BACKEND.parent / "packages")])
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=True, text=True,
                              capture_output=True,
                              env={**os.environ, "PYTHONHASHSEED": s, "PYTHONPATH": path}).stdout
               for s in ("1", "2", "3", "4")}
    assert len(outputs) == 1
    assert outputs.pop().startswith("['ps:gen.1.1', 'ps:gen.1.2', 'ps:jhn.1.1', 'ps:jhn.1.2'")


def test_book_anchor_pin_only_absent_books_on_multi_book_questions():
    ranked = [_c("ps:heb.8.1", book="heb", chapter=8, rerank_score=0.9)]
    pool = ranked + [_c("ps:jer.31.1", "book_anchor", 0.9, book="jer", chapter=31,
                        semantic_score=0.8),
                     _c("ps:heb.9.1", "book_anchor", 0.9, book="heb", chapter=9, semantic_score=0.9)]

    out = pins.pin_book_anchor_candidates(ranked, pool, top_k=5, book_gate=True)

    assert [c["id"] for c in out] == ["ps:jer.31.1", "ps:heb.8.1"]


def test_cap_keeps_one_book_anchor_per_book():
    ranked = [_c("1", "book_anchor", book="rev"), _c("2", "book_anchor", book="rev"),
              _c("3", "semantic", book="eph")]

    assert [c["id"] for c in pins.cap_book_anchor_entries(ranked)] == ["1", "3", "2"]


def test_fusion_blends_rerank_and_weight():
    out = pins.fuse_and_rank([_c("lo", weight=0.9, rerank_score=0.5),
                              _c("hi", weight=0.5, rerank_score=0.62)], top_k=2, alpha=0.3)

    assert [c["id"] for c in out] == ["lo", "hi"]


def test_graph_strategies_accept_only_the_event_lane():
    assert router.resolve_graph_strategies(None) == frozenset(settings.rag_graph_strategies)
    assert router.resolve_graph_strategies([]) == frozenset()
    with pytest.raises(ValueError, match="graph_event"):
        router.resolve_graph_strategies(["graph_event"])


# --- routes ----------------------------------------------------------------------------

def test_r1_returns_verses_unranked_with_provenance(active, monkeypatch, scores):
    async def verses(refs):
        return [_c("vs:jhn.3.16", "verse_direct", 1.0, book="jhn", chapter=3, kind="verse")]
    monkeypatch.setattr(routes, "retrieve_by_verse_refs", verses)

    ranked, stats = _run(query="約翰福音3:16", verse_refs=[VerseRef("jhn", "約翰福音", 3, 16, 16)])

    assert [c["id"] for c in ranked] == ["vs:jhn.3.16"]
    assert ranked[0]["found_by"] == ["verse_direct"] and "rerank_score" not in ranked[0]
    assert stats["route_used"] == "R1" and stats["fusion_alpha"] is None


def test_r1_falls_back_to_r2_and_keeps_both_errors(active, monkeypatch, scores):
    async def failing(refs):
        raise LookupError("no slot")
    monkeypatch.setattr(routes, "retrieve_by_verse_refs", failing)
    _dense(monkeypatch, hits=[_c("ps:jhn.3.1")])

    ranked, stats = _run(query="約翰福音3:16", verse_refs=[VerseRef("jhn", "約翰福音", 3, 16, 16)])

    assert [c["id"] for c in ranked] == ["ps:jhn.3.1"]
    assert stats["strategies_used"] == ["semantic"]
    assert set(stats["strategy_errors"]) == {"verse_direct", "sql_chapter"}


def test_r2_pins_the_named_chapter(active, monkeypatch, scores):
    async def chapter(refs):
        return [_c(f"ps:mat.6.{i}", weight=1.0, book="mat", chapter=6) for i in (1, 5)]
    monkeypatch.setattr(routes, "retrieve_by_verse_refs", chapter)
    _dense(monkeypatch, hits=[_c(f"ps:luk.{i}.1", book="luk", chapter=i) for i in range(1, 8)])
    scores.update({f"ps:luk.{i}.1": 0.99 for i in range(1, 8)})
    scores.update({"ps:mat.6.1": 0.0, "ps:mat.6.5": 0.0})

    ranked, stats = _run(query="馬太福音第6章的禱告", verse_refs=[VerseRef("mat", "馬太福音", 6)],
                         top_k=5)

    assert stats["route_used"] == "R2" and stats["strategies_used"] == ["sql_chapter", "semantic"]
    assert {c["id"] for c in ranked[:2]} == {"ps:mat.6.1", "ps:mat.6.5"}
    assert all(c["source_strategy"] == "sql_chapter" for c in ranked[:2])


def test_dense_routes_add_book_anchors_and_a_sql_supplement(active, monkeypatch, scores):
    calls = _dense(monkeypatch, hits=[_c("ps:act.9.1")],
                   hits_by_book={"act": [_c("ps:act.9.1"), _c("ps:act.10.1", chapter=10)]})

    async def chapter_passages(book_id, chapter):
        return [_c(f"ps:{book_id}.{chapter}.{v}", "x", 0.0, book=book_id, chapter=chapter)
                for v in (1, 20)]
    monkeypatch.setattr(routes.postgres, "chapter_passages", chapter_passages)

    ranked, stats = _run(query="使徒行傳裡掃羅與巴拿巴", top_k=3,
                         entity_names=["掃羅", "巴拿巴"])

    assert stats["route_used"] == "R3"
    assert stats["strategies_used"] == ["semantic", "book_anchor", "sql_supplement"]
    assert calls[1] == ("semantic", 10, ["act"])
    pool_ids = {c["id"] for c in ranked}
    assert "ps:act.10.1" in pool_ids  # the book anchor is pinned (single book)


def test_fallback_reports_the_dense_arm_as_hybrid(active, monkeypatch, scores):
    _dense(monkeypatch, hits=[_c("ps:psa.23.1", book="psa", chapter=23)])

    ranked, stats = _run(query="平安是什麼")

    assert stats["route_used"] == "fallback" and stats["strategies_used"] == ["hybrid"]
    assert ranked[0]["found_by"] == ["hybrid_hybrid"]


def test_a_failed_reranker_falls_back_to_weights(active, monkeypatch):
    _dense(monkeypatch, hits=[_c("ps:a.1.1", weight=0.6), _c("ps:a.2.1", weight=0.7)])

    def broken(*args, **kwargs):
        raise RuntimeError("cuda")
    monkeypatch.setattr(reranker, "rerank", broken)

    ranked, stats = _run(query="平安是什麼")

    assert [c["id"] for c in ranked] == ["ps:a.2.1", "ps:a.1.1"]
    assert "rerank" in stats["strategy_errors"]


def test_semantic_only_skips_routing(active, monkeypatch, scores):
    calls = _dense(monkeypatch, hits=[_c("ps:a.1.1")])

    ranked, stats = _run(query="約翰福音3:16", semantic_only=True,
                         verse_refs=[VerseRef("jhn", "約翰福音", 3, 16, 16)])

    assert stats["route_used"] == "semantic_only" and stats["graph_strategies"] == []
    assert calls == [("semantic", None, None)]


def test_no_active_build_refuses(monkeypatch):
    context.reset()
    with pytest.raises(context.NoActiveBuild):
        _run(query="q")


# --- event registry lane -------------------------------------------------------------

@pytest.fixture
def event_question(active, monkeypatch, scores):
    _dense(monkeypatch, hits=[_c(f"ps:rom.{i}.1", book="rom", chapter=i) for i in range(1, 7)])
    _no_supplement(monkeypatch)
    fetched = []

    async def content(record_id):
        fetched.append(record_id)
        return _c(record_id, "x", 0.0)
    monkeypatch.setattr(router.postgres, "get_content_by_id", content)
    return fetched


def test_r4_appends_the_first_anchor_the_top_k_lacks(event_question):
    ranked, stats = _run(query="保羅歸主的經過", top_k=5)

    assert stats["route_used"] == "R4" and stats["reranked_top_k"] == 5
    assert [c["id"] for c in ranked[5:]] == ["ps:act.9.1"]
    assert ranked[5]["source_strategy"] == "event_registry"
    assert ranked[5]["found_by"] == ["event_registry"] and ranked[5]["via_event_id"] == "event:saoluo"
    assert stats["event_registry_events"] == ["event:saoluo"]
    assert stats["strategies_used"][-1] == "event_registry"


@pytest.mark.parametrize("override", [{"use_graph": False}, {"graph_strategies": []}])
def test_the_lane_is_off_without_graph_or_without_the_strategy(event_question, override):
    ranked, stats = _run(query="保羅歸主的經過", top_k=5, **override)

    assert len(ranked) == 5 and stats["event_registry_events"] == []
    assert event_question == []


def test_an_anchor_already_in_the_top_k_through_a_chunk_counts_as_covered(event_question,
                                                                          monkeypatch, scores):
    _dense(monkeypatch, hits=[_c("ck:act.9.1~act.9.2", passage_id="ps:act.9.1"),
                              *[_c(f"ps:rom.{i}.1", book="rom", chapter=i) for i in range(1, 6)]])
    scores["ck:act.9.1~act.9.2"] = 0.99

    ranked, _ = _run(query="保羅歸主的經過", top_k=5)

    assert [c["id"] for c in ranked[5:]] == ["ps:act.9.3b"]


def test_a_missing_anchor_is_an_error_not_a_silent_skip(event_question, monkeypatch):
    async def gone(record_id):
        return None
    monkeypatch.setattr(router.postgres, "get_content_by_id", gone)

    ranked, stats = _run(query="保羅歸主的經過", top_k=5)

    assert len(ranked) == 5 and "ps:act.9.1" in stats["strategy_errors"]["event_registry"]


def test_r5_pulls_chapter_passages_and_anchors_every_named_book(active, monkeypatch, scores):
    async def chapter(refs):
        return [_c("ps:1co.15.1", weight=1.0, book="1co", chapter=15),
                _c("ps:gen.1.1", weight=1.0, book="gen", chapter=1)]
    monkeypatch.setattr(routes, "retrieve_by_verse_refs", chapter)
    calls = _dense(monkeypatch, hits=[_c("ps:1co.15.1", book="1co", chapter=15)],
                   hits_by_book={"1co": [_c("ps:1co.15.35", book="1co", chapter=15)],
                                 "gen": [_c("ps:gen.3.1", book="gen", chapter=3)]})
    _no_supplement(monkeypatch)

    ranked, stats = _run(query="哥林多前書15章如何回應創世記關於死亡的敘述？", top_k=4,
                         verse_refs=[VerseRef("1co", "哥林多前書", 15)])

    assert stats["route_used"] == "R5"
    assert stats["strategies_used"] == ["semantic", "sql_chapter", "book_anchor"]
    by_id = {c["id"]: c for c in ranked}
    assert by_id["ps:1co.15.1"]["source_strategy"] == "sql_chapter"  # wins the dedup tie
    assert by_id["ps:1co.15.1"]["found_by"] == ["hybrid_hybrid", "sql_chapter"]
    assert [c[1:] for c in calls[1:]] == [(5, ["1co"]), (5, ["gen"])]


def test_fusion_off_ranks_by_rerank_score_alone(active, monkeypatch, scores):
    monkeypatch.setattr(settings, "rag_rank_fusion_enabled", False)
    _dense(monkeypatch, hits=[_c("ps:a.1.1", weight=0.9), _c("ps:a.2.1", weight=0.1)])
    scores.update({"ps:a.1.1": 0.2, "ps:a.2.1": 0.3})

    ranked, stats = _run(query="平安是什麼")

    assert [c["id"] for c in ranked] == ["ps:a.2.1", "ps:a.1.1"]
    assert stats["fusion_alpha"] is None and "fused_score" not in ranked[0]


def test_failing_strategies_are_recorded_and_the_route_goes_on(active, monkeypatch, scores):
    async def broken(query, arm, top_k=None, book_ids=None):
        raise ConnectionError("qdrant down")
    monkeypatch.setattr(routes, "retrieve_dense", broken)
    monkeypatch.setattr(router, "retrieve_dense", broken)

    async def supplement_fails(book_id, chapter):
        raise ConnectionError("pg down")
    monkeypatch.setattr(routes.postgres, "chapter_passages", supplement_fails)

    ranked, stats = _run(query="以弗所書與使徒行傳的保羅")
    assert ranked == [] and stats["route_used"] == "R5"
    assert set(stats["strategy_errors"]) == {"semantic", "book_anchor:以弗所書",
                                             "book_anchor:使徒行傳"}

    ranked, stats = _run(query="q", semantic_only=True)
    assert ranked == [] and set(stats["strategy_errors"]) == {"semantic"}


def test_a_failing_supplement_is_recorded(active, monkeypatch):
    async def supplement_fails(book_id, chapter):
        raise ConnectionError("pg down")
    monkeypatch.setattr(routes.postgres, "chapter_passages", supplement_fails)
    errors: dict[str, str] = {}

    pool = asyncio.run(routes._supplement([_c("ps:act.9.1")], "R3", 0.5, [], errors))

    assert [c["id"] for c in pool] == ["ps:act.9.1"] and "pg down" in errors["sql_supplement"]


def test_an_anchor_fetch_that_raises_is_recorded(event_question, monkeypatch):
    async def broken(record_id):
        raise ConnectionError("pg down")
    monkeypatch.setattr(router.postgres, "get_content_by_id", broken)

    ranked, stats = _run(query="保羅歸主的經過", top_k=5)

    assert len(ranked) == 5 and "pg down" in stats["strategy_errors"]["event_registry"]
