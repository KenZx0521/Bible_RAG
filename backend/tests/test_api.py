"""HTTP surface without stores: validation, retired endpoints, 503 when nothing is served."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from ragcommon import routing
from routers import health, query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import embedder, reranker

FROZEN = Path(__file__).resolve().parents[2] / "config" / "registries" / "routing_lexicon.legacy.json"
BUILD = Build("b20261008_1bb6912e", "bb20261008_1bb6912e", "passages__b", Path("/c"), False, 22)


@pytest.fixture
def client():
    yield TestClient(main.app)  # no `with`: the lifespan (models, stores) does not run
    context.reset()


@pytest.fixture
def serving():
    active = context.make_active(BUILD, routing.load_lexicon(FROZEN), ())
    context.install(active, Handshake(BUILD.build_id, (), strict=True))


@pytest.fixture
def fake_pipeline(monkeypatch):
    seen = {}

    async def intent(question):
        return {"type": "topic", "entities": [], "verse_refs": [], "keywords": [],
                "rejected_refs": ["約翰福音3:99"]}

    async def retrieve(**kwargs):
        seen.update(kwargs)
        hit = {"id": "vs:eph.6.2-3", "kind": "verse", "book_name": "以弗所書", "chapter_num": 6,
               "title": "兒女和父母", "verse_range": "2-3", "start_key": "eph.6.2",
               "end_key": "eph.6.3", "passage_id": "ps:eph.6.1", "split_passage_ids": [],
               "content": "2-3. 要孝敬父母", "source_strategy": "verse_direct",
               "found_by": ["verse_direct"]}
        return [hit], {"strategies_used": ["verse_direct"], "route_used": "R1"}

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(query, "retrieve_and_rerank", retrieve)
    return seen


@pytest.mark.parametrize("strategies", [["graph_event"], ["all"], ["event_registry"] * 2,
                                        ["cross_ref_expand"], "event_registry"])
def test_graph_strategies_other_than_the_event_lane_are_422(client, strategies):
    response = client.post("/api/v1/query", json={"question": "q", "graph_strategies": strategies})

    assert response.status_code == 422


@pytest.mark.parametrize("strategies", [[], ["event_registry"], None])
def test_the_event_lane_or_nothing_is_accepted(client, serving, fake_pipeline, strategies):
    response = client.post("/api/v1/query", json={"question": "q", "retrieval_only": True,
                                                  "graph_strategies": strategies})

    assert response.status_code == 200
    assert fake_pipeline["graph_strategies"] == strategies


def test_sources_carry_the_new_fields_and_the_build(client, serving, fake_pipeline):
    body = client.post("/api/v1/query", json={"question": "q", "retrieval_only": True,
                                              "include_context": True}).json()

    [source] = body["sources"]
    assert source["id"] == "vs:eph.6.2-3" and source["verse_range"] == "2-3"
    assert (source["kind"], source["start_key"], source["end_key"]) == ("verse", "eph.6.2", "eph.6.3")
    assert source["passage_id"] == "ps:eph.6.1" and source["split_passage_ids"] == []
    assert source["build_id"] == BUILD.build_id
    assert source["book"] == "以弗所書" and source["chapter"] == 6
    assert source["context"].startswith("[1] 以弗所書 第6章 - 兒女和父母 (2-3節)\n")
    assert body["intent"]["rejected_refs"] == ["約翰福音3:99"]
    assert body["answer"] == ""


def test_queries_answer_503_when_no_build_is_served(client, fake_pipeline):
    context.install(None, Handshake("b1", ("qdrant: x holds 0 points",), strict=False))

    response = client.post("/api/v1/query", json={"question": "q"})

    assert response.status_code == 503 and "holds 0 points" in response.json()["detail"]
    assert client.get("/api/v1/verse/jhn/3/16").status_code == 503
    assert client.get("/api/v1/verse/jhn/3").status_code == 503


def test_entity_is_retired_with_a_reason(client):
    response = client.get("/api/v1/entity/person:moxi")

    assert response.status_code == 410
    assert "D-08" in response.json()["detail"]


async def _up():
    return True


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(health.postgres, "health_check", _up)
    monkeypatch.setattr(health.qdrant_db, "health_check", lambda: True)
    monkeypatch.setattr(health, "get_llm_client", lambda: SimpleNamespace(health_check=_up))
    monkeypatch.setattr(embedder, "_fingerprint", {"probe_ids_sha": "p"})
    monkeypatch.setattr(reranker, "_fingerprint", None)


def test_health_is_200_with_the_build_when_the_handshake_passed(client, serving, services):
    response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert body["build_id"] == BUILD.build_id and body["handshake"]["ok"] is True
    assert body["encoder"] == {"embedder": {"probe_ids_sha": "p"}, "reranker": None}
    assert set(body["services"]) == {"postgres", "qdrant", "llm"}


def test_health_is_503_listing_every_mismatch(client, services):
    context.install(None, Handshake("b1", ("contracts: a", "encoder: b"), strict=False))

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["handshake"]["mismatches"] == ["contracts: a", "encoder: b"]
    assert response.json()["status"] == "mismatch"


def test_health_before_startup_is_503(client, services):
    context.reset()

    assert client.get("/api/v1/health").status_code == 503
