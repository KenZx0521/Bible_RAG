"""E0a: the "hybrid" arm is the dense query prod has always run (G28).

qdrant-client 1.8.2 has no query_points, so every hybrid_search fell back to
dense_only_search: one client.search on the hybrid collection's "dense" vector
with limit=k and nothing else (prod logs: 587/587 "Hybrid retriever (hybrid)").
CKIP + BM25 only decided the label. These tests pin that call, the candidates
built from it and the strategy labels, so retiring the sparse side changes no
retrieval result.
"""

import asyncio
from types import SimpleNamespace

import pytest

from config import Settings, settings
from database import qdrant_db
from utils import embedder
from utils.retrieval import hybrid_retriever, router
from utils.signal_detector import QuerySignals

VECTOR = [0.25, -0.5, 0.125]


class _QdrantClient182:
    """The qdrant-client 1.8.2 surface: search, no query_points."""

    def __init__(self, points):
        self.points = points
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.points


def _point(score: float, **payload) -> SimpleNamespace:
    return SimpleNamespace(payload=payload, score=score)


POINTS = [
    _point(0.91, record_id="jhn:3:2:v:16", type="verse", parent_pericope_id="jhn:3:2",
           book_name="約翰福音", chapter_num=3, title="神愛世人", verse_range="16",
           content_preview="神愛世人"),
    _point(0.88, record_id="rom:8:3", type="pericope", book_name="羅馬書", chapter_num=8,
           title="得勝有餘", verse_range="31-39", content_preview="誰能使我們與基督的愛隔絕呢"),
    _point(0.80, record_id="gen:1:0:v:1", type="verse", book_name="創世記", chapter_num=1),
]


async def _content(record_id: str):
    if record_id == "rom:8:3":
        return None  # missing in PG: falls back to the Qdrant payload
    return {"content": f"text {record_id}", "title": "pg title", "book_name": "pg book",
            "chapter_num": 9, "metadata": {"verse_range": "pg range"}}


@pytest.fixture
def client(monkeypatch):
    fake = _QdrantClient182(POINTS)
    monkeypatch.setattr(qdrant_db, "_client", fake)
    monkeypatch.setattr(embedder, "encode_query", lambda text: VECTOR)
    monkeypatch.setattr(hybrid_retriever.postgres, "get_content_by_id", _content)
    return fake


def test_default_hybrid_collection_is_the_one_prod_queries():
    assert Settings(_env_file=None).qdrant_hybrid_collection == "bible_embeddings_hybrid"


@pytest.mark.parametrize(("top_k", "limit"), [(None, 20), (7, 7)])
def test_one_dense_search_with_the_old_fallback_parameters(client, top_k, limit):
    asyncio.run(hybrid_retriever.retrieve_hybrid("神愛世人", top_k=top_k))

    assert client.calls == [{
        "collection_name": settings.qdrant_hybrid_collection,
        "query_vector": ("dense", VECTOR),
        "limit": limit,
    }]


def test_candidates_keep_order_ids_weights_scores_and_label(client):
    got = asyncio.run(hybrid_retriever.retrieve_hybrid("神愛世人"))

    assert got == [
        {"id": "jhn:3:2", "content": "text jhn:3:2:v:16", "title": "pg title",
         "book_name": "pg book", "chapter_num": 9, "verse_range": "pg range",
         "source_strategy": "hybrid_hybrid", "weight": 0.70, "hybrid_score": 0.91,
         "_is_verse_hit": True},
        {"id": "rom:8:3", "content": "誰能使我們與基督的愛隔絕呢", "title": "得勝有餘",
         "book_name": "羅馬書", "chapter_num": 8, "verse_range": "31-39",
         "source_strategy": "hybrid_hybrid", "weight": 0.65, "hybrid_score": 0.88,
         "_is_verse_hit": False},
        {"id": "gen:1:0", "content": "text gen:1:0:v:1", "title": "pg title",
         "book_name": "pg book", "chapter_num": 9, "verse_range": "pg range",
         "source_strategy": "hybrid_hybrid", "weight": 0.70, "hybrid_score": 0.80,
         "_is_verse_hit": True},
    ]


def test_fallback_route_keeps_the_hybrid_labels(client, monkeypatch):
    monkeypatch.setattr(settings, "hybrid_search_enabled", True)

    candidates, strategies, errors = asyncio.run(router._route_fallback(
        query="神愛世人", verse_refs=[], entity_names=[], signals=QuerySignals(route="fallback"),
        k=5, use_graph=False, graph_strategies=frozenset(),
    ))

    assert (strategies, errors) == (["hybrid"], {})
    assert [(c["id"], c["source_strategy"], c["found_by"]) for c in candidates] == [
        ("jhn:3:2", "hybrid_hybrid", ["hybrid_hybrid"]),
        ("rom:8:3", "hybrid_hybrid", ["hybrid_hybrid"]),
        ("gen:1:0", "hybrid_hybrid", ["hybrid_hybrid"]),
    ]


def test_switch_off_still_selects_the_semantic_collection(client, monkeypatch):
    monkeypatch.setattr(settings, "hybrid_search_enabled", False)

    candidates = asyncio.run(router._get_semantic("神愛世人"))

    assert client.calls[0]["collection_name"] == settings.qdrant_collection
    assert {c["source_strategy"] for c in candidates} == {"semantic"}

