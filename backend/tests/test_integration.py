"""The backend against the ragdata mini build: a throwaway PostgreSQL and an in-memory Qdrant.

The PostgreSQL container uses only the local pgvector/pgvector:pg15 image
(``--pull never``), listens on 127.0.0.1 only and is removed when the module ends.
It is loaded with ``fixtures/mini_build/pg.sql`` (what ``ragdata.loader`` writes
for the mini release, see make_mini_build.py); Qdrant is an in-memory client
holding ``points.jsonl``; the contract directory is ``fixtures/mini_build/contracts``.
The models, the reranker and the LLM are stand-ins: what is real is startup, the
handshake, every SQL query and the Qdrant search.
"""

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient, models

import main
from config import settings
from ragcommon import ids
from serving import context, startup
from utils import embedder, reranker
from utils import intent_classifier
from routers import health

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
META = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))
BUILD_ID = META["build_id"]
POINTS = [json.loads(line) for line in (FIXTURE / "points.jsonl").read_text("utf-8").splitlines()]
VECTORS = {p["payload"]["record_id"]: p["vector"] for p in POINTS}
CONTRACT_FP = json.loads((FIXTURE / "contracts" / BUILD_ID / "encoder_fingerprint.json")
                         .read_text(encoding="utf-8"))
FP = {n: {k: CONTRACT_FP[n][k] for k in ("tokenizer_sha", "probe_ids_sha", "unk_count",
                                         "pair_template_ok")} for n in ("bge_m3", "reranker")}
IMAGE = "pgvector/pgvector:pg15"
READY_S = 90


def _docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, **kwargs)


def _image_present() -> bool:
    return shutil.which("docker") is not None and _docker("image", "inspect", IMAGE).returncode == 0


pytestmark = pytest.mark.skipif(not _image_present(),
                                reason=f"docker or the local image {IMAGE} is not available")


def _wait_ready(name: str) -> None:
    deadline = time.monotonic() + READY_S
    while time.monotonic() < deadline:
        ready = _docker("exec", name, "pg_isready", "-U", "test", "-d", "bible_rag",
                        "-h", "127.0.0.1")
        if ready.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError(f"{name} not ready after {READY_S} s")


def _psql(name: str, stdin: str) -> None:
    done = _docker("exec", "-i", name, "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", "test",
                   "-d", "bible_rag", "-h", "127.0.0.1", input=stdin)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)


@pytest.fixture(scope="module")
def pg_server():
    name = f"bible_rag_be_test_{uuid.uuid4().hex[:8]}"
    started = _docker("run", "-d", "--rm", "--pull", "never", "--name", name,
                      "-e", "POSTGRES_USER=test", "-e", "POSTGRES_PASSWORD=test",
                      "-e", "POSTGRES_DB=bible_rag", "-p", "127.0.0.1::5432", IMAGE)
    assert started.returncode == 0, started.stderr
    try:
        _wait_ready(name)
        _psql(name, (FIXTURE / "pg.sql").read_text(encoding="utf-8"))
        _psql(name, "INSERT INTO rag_meta.serving VALUES "
                    f"('staging', '{BUILD_ID}', 'sha256:{'0' * 64}', now());")
        port = _docker("inspect", "-f", '{{(index (index .NetworkSettings.Ports "5432/tcp") 0)'
                       '.HostPort}}', name).stdout.strip()
        yield {"host": "127.0.0.1", "port": int(port)}
    finally:
        _docker("rm", "-f", name)


def _qdrant(points=POINTS) -> QdrantClient:
    client = QdrantClient(location=":memory:")
    client.create_collection(META["qdrant_collection"], vectors_config=models.VectorParams(
        size=META["dim"], distance=models.Distance.COSINE))
    client.upsert(META["qdrant_collection"], points=[
        models.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points])
    return client


class FakeLlm:
    provider_name = "fake"

    async def health_check(self):
        return True

    async def chat(self, messages, temperature=0.1, max_tokens=512):
        return '{"intent": "topic", "entities": [], "keywords": []}'


@pytest.fixture
def backend(pg_server, monkeypatch):
    """Settings and stand-ins for one app start; ``backend.qdrant`` may be replaced first."""
    for key, value in {"postgres_host": pg_server["host"], "postgres_port": pg_server["port"],
                       "postgres_user": "test", "postgres_password": "test",
                       "postgres_db": "bible_rag", "rag_env": "staging", "rag_build_id": None,
                       "contracts_root": str(FIXTURE / "contracts"),
                       "strict_build_check": True}.items():
        monkeypatch.setattr(settings, key, value)
    state = SimpleNamespace(qdrant=_qdrant(), query_vector=VECTORS["ps:act.10.1"], scores={})
    monkeypatch.setattr(startup.qdrant_db, "make_client", lambda: state.qdrant)
    monkeypatch.setattr(main, "load_models", lambda: FP)
    monkeypatch.setattr(embedder, "encode_query", lambda text: state.query_vector)
    monkeypatch.setattr(intent_classifier, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(main, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(health, "get_llm_client", lambda: FakeLlm())

    def rerank(query, passages, top_k=5, text_key="content"):
        for p in passages:
            p["rerank_score"] = state.scores.get(p["id"], 0.1)
        return sorted(passages, key=lambda p: p["rerank_score"], reverse=True)[:top_k]

    monkeypatch.setattr(reranker, "rerank", rerank)
    yield state
    context.reset()


def _ask(client, question, **extra):
    response = client.post("/api/v1/query", json={"question": question, "retrieval_only": True,
                                                  **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_startup_serves_the_staging_build_and_health_says_so(backend):
    with TestClient(main.app) as client:
        body = client.get("/api/v1/health").json()

    assert body["build_id"] == BUILD_ID and body["status"] == "ok"
    assert body["handshake"] == {"build_id": BUILD_ID, "ok": True, "strict": True,
                                 "mismatches": []}


def test_a_merged_verse_returns_its_whole_unit(backend):
    with TestClient(main.app) as client:
        verse = client.get("/api/v1/verse/eph/6/3").json()
        sources = _ask(client, "以弗所書6:3說什麼？")["sources"]

    assert verse["unit_key"] == "eph.6.2-3" and verse["verse_range"] == "2-3"
    assert verse["status"] == "merged" and verse["text"].startswith("「要孝敬父母")
    assert verse["passage_id"] == verse["pericope_id"] == "ps:eph.6.1"
    assert verse["build_id"] == BUILD_ID
    [source] = sources
    assert (source["id"], source["kind"], source["verse_range"]) == ("vs:eph.6.2-3", "verse", "2-3")
    assert (source["start_key"], source["end_key"]) == ("eph.6.2", "eph.6.3")
    assert source["strategy"] == "verse_direct" and source["book"] == "以弗所書"


def test_an_omitted_verse_says_it_is_absent_with_its_footnote(backend):
    with TestClient(main.app) as client:
        verse = client.get("/api/v1/verse/mat/18/3").json()
        [source] = _ask(client, "馬太福音18:3-4", include_context=True)["sources"]

    assert verse["status"] == "omitted_variant" and verse["text"] == "本譯本此節從缺"
    assert verse["footnote"] == "有古卷加：3人子來，為要拯救失喪的人。"
    assert source["id"] == "vr:mat.18.3~mat.18.4" and source["passage_id"] == "ps:mat.18.1"
    assert ids.parse(source["id"]).kind == "verse_range"
    assert "3. 本譯本此節從缺（有古卷加：3人子來，為要拯救失喪的人。）" in source["context"]


def test_a_verse_cut_by_a_heading_lists_the_heading_and_both_passages(backend):
    with TestClient(main.app) as client:
        verse = client.get("/api/v1/verse/act/9/3").json()
        opening = client.get("/api/v1/verse/act/9/1").json()

    assert verse["text"] == "掃羅將到大馬士革，蹚過小河，忽然有光四面照着他。"
    assert verse["headings"] == [{"heading_id": "hd:act.9.3b#1", "offset": 14,
                                  "text": "天上的光"}]
    assert verse["passage_id"] == "ps:act.9.1"
    assert verse["split_passage_ids"] == ["ps:act.9.1", "ps:act.9.3b"]
    assert opening["headings"] == []  # the headings before act.9.1 do not cut it


def test_a_chapter_lists_passages_in_order_with_its_chapter_texts(backend):
    with TestClient(main.app) as client:
        acts = client.get("/api/v1/verse/act/9").json()
        psalm = client.get("/api/v1/verse/psa/42").json()
        missing = client.get("/api/v1/verse/jhn/3")
        unknown = client.get("/api/v1/verse/xyz/1")

    assert [p["id"] for p in acts["pericopes"]] == ["ps:act.9.1", "ps:act.9.3b"]
    assert acts["id"] == "act.9" and acts["build_id"] == BUILD_ID
    assert [(t["kind"], t["text"]) for t in psalm["chapter_texts"]] == [
        ("book_division", "卷二"), ("superscription", "可拉後裔的訓誨詩，交給聖詠團長。")]
    assert missing.status_code == 404 and unknown.status_code == 404


def test_dense_hits_become_passages_and_chunks_with_their_text(backend):
    backend.query_vector = VECTORS["ck:act.9.2~act.9.3"]
    backend.scores.update({"ck:act.9.2~act.9.3": 0.9, "ps:act.9.1": 0.8})

    with TestClient(main.app) as client:
        body = _ask(client, "大馬士革的路上", semantic_only=True, top_k=2, include_context=True)

    chunk, passage = body["sources"]
    assert (chunk["id"], chunk["kind"], chunk["passage_id"]) == (
        "ck:act.9.2~act.9.3", "chunk", "ps:act.9.1")
    assert chunk["context"].endswith("**2** 求文書給大馬士革的各會堂，經過鹽海。\n\n"
                                     "**3** 掃羅將到大馬士革，蹚過小河，")
    assert (passage["id"], passage["kind"], passage["verse_range"]) == ("ps:act.9.1", "passage", "1-3")
    assert {s["build_id"] for s in body["sources"]} == {BUILD_ID}


def test_an_event_question_appends_the_registry_anchor_after_the_top_k(backend):
    backend.scores.update({"ps:psa.42.1": 0.9, "ps:sng.1.1": 0.8})

    with TestClient(main.app) as client:
        body = _ask(client, "保羅歸主的經過如何？", top_k=2)

    stats = body["retrieval_stats"]
    assert stats["route_used"] == "R4" and stats["event_registry_events"] == ["ev0003"]
    assert [s["id"] for s in body["sources"]] == ["ps:psa.42.1", "ps:sng.1.1", "ps:act.9.1"]
    assert body["sources"][2]["strategy"] == "event_registry"


@pytest.mark.parametrize("env, build_id, message", [
    ("staging", "b20990101_deadbeef",
     rf"RAG_BUILD_ID=b20990101_deadbeef but rag_meta\.serving\(env=staging\) names {BUILD_ID}"),
    ("prod", BUILD_ID, "rag_meta.serving has no row for env=prod"),
])
def test_a_rag_build_id_serving_does_not_name_stops_strict_startup(backend, monkeypatch, env,
                                                                   build_id, message):
    monkeypatch.setattr(settings, "rag_env", env)
    monkeypatch.setattr(settings, "rag_build_id", build_id)

    with pytest.raises(startup.StartupError, match=message):
        with TestClient(main.app):
            pass


def test_a_point_count_that_differs_is_reported_by_health_when_not_strict(backend, monkeypatch):
    backend.qdrant = _qdrant(POINTS[:-1])
    monkeypatch.setattr(settings, "strict_build_check", False)

    with TestClient(main.app) as client:
        health_response = client.get("/api/v1/health")
        query_response = client.post("/api/v1/query", json={"question": "q"})

    assert health_response.status_code == 503
    assert health_response.json()["handshake"]["mismatches"] == [
        f"qdrant: {META['qdrant_collection']} holds {META['points'] - 1} points, "
        f"rag_meta.builds says {META['points']}"]
    assert query_response.status_code == 503
