"""loader.qdrant over the in-memory Qdrant client."""

from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient

from ragcommon import ids
from ragdata.loader import qdrant as qmod
from ragdata.loader.config import QdrantSettings
from ragdata.loader.plan import Point
from ragdata.loader.qdrant import QdrantDb

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")


def _points(n, dim=4):
    rng = np.random.default_rng(0)
    rows = rng.normal(size=(n, dim)).astype(np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    return [Point(ids.point_id(f"vs:gen.1.{i + 1}"), rows[i],
                  {"record_id": f"vs:gen.1.{i + 1}", "kind": "verse", "book_id": "gen"})
            for i in range(n)]


def test_a_collection_is_created_with_the_serving_settings_and_filled_in_batches(monkeypatch):
    monkeypatch.setattr(qmod, "BATCH", 7)
    monkeypatch.setattr(qmod, "SCROLL", 5)
    db = QdrantDb(QdrantClient(location=":memory:"))
    assert not db.exists("passages__b1")
    db.create("passages__b1", 4)
    points = _points(23)
    db.upsert("passages__b1", points)
    assert db.exists("passages__b1") and db.count("passages__b1") == 23
    back = {p.id: p for p in db.points("passages__b1")}
    assert set(back) == {p.id for p in points}
    first = back[points[0].id]
    assert first.payload == points[0].payload
    assert np.allclose(first.vector, points[0].vector, atol=1e-6)
    config = db.config("passages__b1")
    assert config["size"] == 4 and config["distance"] == "Cosine"
    hnsw = config["hnsw"]   # the in-memory client keeps HNSW but drops on_disk and optimizers
    assert (hnsw["m"], hnsw["ef_construct"], hnsw["full_scan_threshold"]) == (16, 100, 10000)
    db.close()


def test_connect_prefers_grpc_on_the_configured_ports(monkeypatch):
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)
    monkeypatch.setattr(qmod, "QdrantClient", Client)
    QdrantDb.connect(QdrantSettings("localhost", 6333, 6334))
    assert seen["host"] == "localhost" and (seen["port"], seen["grpc_port"]) == (6333, 6334)
    assert seen["prefer_grpc"] is True
