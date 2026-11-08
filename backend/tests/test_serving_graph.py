"""The graph's state on /api/v1/health: Neo4j trouble is reported, it never fails the handshake."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from database import neo4j_db
from router_fakes import LEXICON
from routers import health
from serving import context, graph
from serving.build import Build
from serving.contracts import KgMeta
from serving.handshake import Handshake
from utils import embedder, reranker

BUILD = Build("b20261102_aaaaaaaa", "bb20261102_aaaaaaaa", "passages__b", Path("/c"), True, 22)
KG = KgMeta("ragdata.kg.v1", {"Person": 2, "Verse": 3}, {"PARENT_OF": 1}, "a" * 64, "b" * 64, "c" * 64)
GOOD = {"build_id": BUILD.build_id, "complete": True, "kg_sha256": "c" * 64, "nodes_Person": 2,
        "nodes_Verse": 3, "edges_PARENT_OF": 1}


def _judge(**changes):
    return graph.judge(BUILD.build_id, KG, {**GOOD, **changes})


def test_a_complete_build_info_of_this_graph_is_ready():
    status = _judge()
    assert status.ready and status.state == graph.READY and status.reason is None
    assert status.to_json() == {"state": "ready", "build_id": BUILD.build_id, "kg_sha256": "c" * 64,
                                "nodes": 5, "edges": 1, "complete": True}


def test_no_build_info_is_a_mismatch_that_says_to_project():
    status = graph.judge(BUILD.build_id, KG, None)
    assert not status.ready and status.state == graph.MISMATCH and "kg-project" in status.reason


@pytest.mark.parametrize("changes, reason", [
    ({"complete": False}, "complete"),
    ({"kg_sha256": "d" * 64}, "kg_sha256"),
    ({"nodes_Person": 1}, "nodes_Person"),
    ({"edges_PARENT_OF": 0}, "edges_PARENT_OF"),
    ({"nodes_Verse": None}, "nodes_Verse"),
])
def test_a_build_info_that_differs_is_a_mismatch_that_names_what(changes, reason):
    status = _judge(**changes)
    assert status.state == graph.MISMATCH and reason in status.reason and not status.ready


@pytest.fixture
def client():
    yield TestClient(main.app)  # no `with`: the lifespan (models, stores) does not run
    context.reset()


async def _up():
    return True


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(health.postgres, "health_check", _up)
    monkeypatch.setattr(health.qdrant_db, "health_check", lambda: True)
    monkeypatch.setattr(health, "get_llm_client", lambda: SimpleNamespace(health_check=_up))
    monkeypatch.setattr(embedder, "_fingerprint", None)
    monkeypatch.setattr(reranker, "_fingerprint", None)


def _serve(kg=KG, build=BUILD) -> None:
    context.install(context.make_active(build, LEXICON, (), kg=kg),
                    Handshake(build.build_id, (), strict=True))


def _neo4j(monkeypatch, answer) -> None:
    async def build_info(build_id):
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def server_version():
        return "5.26.32"
    monkeypatch.setattr(graph.neo4j_db, "build_info", build_info)
    monkeypatch.setattr(graph.neo4j_db, "server_version", server_version)


def test_health_says_ready_when_neo4j_holds_the_graph(client, services, monkeypatch):
    _serve()
    _neo4j(monkeypatch, GOOD)

    response = client.get("/api/v1/health")

    assert response.status_code == 200 and response.json()["status"] == "ok"
    found = response.json()["graph"]
    assert found["state"] == "ready" and found["complete"] is True and found["neo4j_version"] == "5.26.32"
    assert (found["nodes"], found["edges"]) == (5, 1)


@pytest.mark.parametrize("answer, state", [
    (ConnectionRefusedError("refused"), "unavailable"),
    (TimeoutError(), "unavailable"),
    ({**GOOD, "nodes_Person": 1}, "mismatch"),
    (None, "mismatch"),
])
def test_neo4j_trouble_is_reported_and_the_backend_stays_up(client, services, monkeypatch, answer, state):
    _serve()
    _neo4j(monkeypatch, answer)

    response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200 and body["status"] == "ok"
    assert body["handshake"]["ok"] is True and set(body["services"]) == {"postgres", "qdrant", "llm"}
    assert body["graph"]["state"] == state and body["graph"]["reason"]


def test_an_incomplete_projection_says_it_is_not_complete(client, services, monkeypatch):
    _serve()
    _neo4j(monkeypatch, {**GOOD, "complete": False})

    found = client.get("/api/v1/health").json()["graph"]

    assert found["state"] == "mismatch" and found["complete"] is False


def test_a_skip_is_reported_by_its_reason(monkeypatch):
    _serve()
    _neo4j(monkeypatch, neo4j_db.Skipped(neo4j_db.SKIPPING))
    status = asyncio.run(graph.status())
    context.reset()
    assert status.state == graph.UNAVAILABLE and status.reason == "neo4j: skipping"


def test_a_walk_asks_at_most_once_per_30_s(monkeypatch):
    _serve()
    asked, now = [], [100.0]

    async def status():
        asked.append(1)
        return graph.GraphStatus(graph.READY)
    monkeypatch.setattr(graph, "status", status)
    monkeypatch.setattr(graph, "_now", lambda: now[0])

    first = asyncio.run(graph.usable())
    now[0] += graph.USABLE_FOR_S - 1
    second = asyncio.run(graph.usable())
    assert first.ready and second.ready and len(asked) == 1

    now[0] += 1
    asyncio.run(graph.usable())
    context.reset()
    assert len(asked) == 2


def test_a_read_that_timed_out_is_not_kept_for_30_s(monkeypatch):
    """One slow read says nothing of Neo4j: the next question asks again."""
    _serve()
    answers, now = [graph.GraphStatus(graph.UNAVAILABLE, f"neo4j: {neo4j_db.TIMEOUT}"), graph.GraphStatus(graph.READY)], [100.0]

    async def status():
        return answers.pop(0)
    monkeypatch.setattr(graph, "status", status)
    monkeypatch.setattr(graph, "_now", lambda: now[0])

    first = asyncio.run(graph.usable())
    second = asyncio.run(graph.usable())
    context.reset()

    assert first.state == graph.UNAVAILABLE and second.ready


def test_a_skip_is_not_kept_past_its_own_30_s(monkeypatch):
    """neo4j_db already keeps Neo4j off for 30 s: kept here too, one pair of timeouts would cost a minute."""
    _serve()
    answers, now = [graph.GraphStatus(graph.UNAVAILABLE, f"neo4j: {neo4j_db.SKIPPING}"), graph.GraphStatus(graph.READY)], [100.0]

    async def status():
        return answers.pop(0)
    monkeypatch.setattr(graph, "status", status)
    monkeypatch.setattr(graph, "_now", lambda: now[0])

    first = asyncio.run(graph.usable())
    second = asyncio.run(graph.usable())
    context.reset()

    assert first.state == graph.UNAVAILABLE and second.ready


def test_neo4j_being_down_is_kept_for_30_s(monkeypatch):
    _serve()
    asked, now = [], [100.0]

    async def status():
        asked.append(1)
        return graph.GraphStatus(graph.UNAVAILABLE, f"neo4j: {neo4j_db.UNAVAILABLE}")
    monkeypatch.setattr(graph, "status", status)
    monkeypatch.setattr(graph, "_now", lambda: now[0])

    asyncio.run(graph.usable())
    asyncio.run(graph.usable())
    context.reset()

    assert len(asked) == 1


def test_an_unavailable_reason_names_the_error_type_not_its_message(monkeypatch):
    _serve()
    _neo4j(monkeypatch, RuntimeError("bolt://neo4j:s3cret@host"))
    status = asyncio.run(graph.status())
    context.reset()
    assert status.state == graph.UNAVAILABLE and status.reason == "neo4j: RuntimeError"


def test_a_build_without_a_graph_never_asks_neo4j(monkeypatch):
    plain = Build(BUILD.build_id, BUILD.pg_schema, "passages__b", Path("/c"), False, 22)
    _serve(kg=None, build=plain)
    _neo4j(monkeypatch, AssertionError("not asked"))
    status = asyncio.run(graph.status())
    context.reset()
    assert status.state == graph.OFF and not status.ready and status.to_json() == {"state": "off"}


def test_nothing_served_means_off():
    context.reset()
    assert asyncio.run(graph.status()).state == graph.OFF


def test_settings_missing_mean_unavailable_not_a_driver_with_a_default(monkeypatch):
    monkeypatch.setattr(neo4j_db.settings, "neo4j_uri", "")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_user", "")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_password", "")
    monkeypatch.setattr(neo4j_db, "_driver", None)
    with pytest.raises(neo4j_db.NotConfigured, match="NEO4J_PASSWORD"):
        asyncio.run(neo4j_db.build_info(BUILD.build_id))


def test_the_driver_is_built_once_with_short_timeouts_and_closed(monkeypatch):
    seen = []

    class FakeDriver:
        closed = False

        async def close(self):
            FakeDriver.closed = True

    def make(uri, **config):
        seen.append((uri, config))
        return FakeDriver()
    monkeypatch.setattr(neo4j_db.settings, "neo4j_uri", "bolt://neo4j:7687")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_user", "neo4j")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_password", "pw")
    monkeypatch.setattr(neo4j_db, "_driver", None)
    monkeypatch.setattr(neo4j_db.AsyncGraphDatabase, "driver", make)

    first = neo4j_db.get_driver()

    assert neo4j_db.get_driver() is first and len(seen) == 1
    uri, config = seen[0]
    assert uri == "bolt://neo4j:7687" and config["auth"] == ("neo4j", "pw")
    assert config["max_transaction_retry_time"] == 0 and config["telemetry_disabled"] is True
    assert config["connection_timeout"] == neo4j_db.CONNECT_S
    asyncio.run(neo4j_db.close_driver())
    assert FakeDriver.closed and neo4j_db._driver is None
