"""Store queries without a server: the Qdrant book filter and the passage order of a chapter.

Qdrant is an in-memory client holding the mini build's points; PostgreSQL rows
come from a fake ``_fetch`` in an order where id strings and verse order disagree.
"""

import asyncio
import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from database import postgres, qdrant_db

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
META = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))
POINTS = [json.loads(line) for line in (FIXTURE / "points.jsonl").read_text("utf-8").splitlines()]


@pytest.fixture
def collection(monkeypatch):
    client = QdrantClient(location=":memory:")
    client.create_collection(META["qdrant_collection"], vectors_config=models.VectorParams(
        size=META["dim"], distance=models.Distance.COSINE))
    client.upsert(META["qdrant_collection"], points=[
        models.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in POINTS])
    monkeypatch.setattr(qdrant_db, "_client", client)
    monkeypatch.setattr(qdrant_db, "_collection", META["qdrant_collection"])
    return client


def test_a_book_restriction_returns_only_that_book_s_points(collection):
    vector = next(p["vector"] for p in POINTS if p["payload"]["book_id"] == "eph")

    restricted = qdrant_db.search(vector, top_k=len(POINTS), book_ids=["act"])
    everything = qdrant_db.search(vector, top_k=len(POINTS))

    act = sum(1 for p in POINTS if p["payload"]["book_id"] == "act")
    assert len(restricted) == act > 0
    assert {h["payload"]["book_id"] for h in restricted} == {"act"}
    assert len({h["payload"]["book_id"] for h in everything}) > 1


def _row(start_key: str) -> dict:
    return {"passage_id": f"ps:{start_key}", "pericope_id": f"pc:{start_key}",
            "chapter_key": "gen.1", "title": "", "verse_range": "", "start_key": start_key,
            "end_key": start_key, "content": "", "unit_refs": [], "book_id": "gen",
            "chapter": 1, "book_name": "創世記"}


def test_a_chapter_s_passages_come_in_verse_order_not_id_order(monkeypatch):
    async def fetch(query, *args):
        assert args == ("gen.1",)
        return [_row(k) for k in ("gen.1.19b", "gen.1.10", "gen.1.2", "gen.1.19")]

    monkeypatch.setattr(postgres, "_fetch", fetch)

    found = asyncio.run(postgres.chapter_passages("gen", 1))

    assert [p["id"] for p in found] == ["ps:gen.1.2", "ps:gen.1.10", "ps:gen.1.19", "ps:gen.1.19b"]
