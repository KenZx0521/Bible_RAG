"""Qdrant side of the loader (design §6, §7.3): one collection per build.

``passages__{build_id}``: dense vectors, cosine, point id ``uuid5(NS_RAG, record_id)``,
keyword payload indexes on ``book_id`` and ``kind``. HNSW and optimizer settings are
those of the serving ``bible_embeddings`` (read 2026-10-08: m 16, ef_construct 100,
full_scan_threshold 10000, on_disk false, indexing_threshold 0 so search stays exact,
payload on disk). Points go in batches with ``wait``; the loader counts them after.
"""

from __future__ import annotations

from typing import Any, Iterator, Sequence

import numpy as np
from qdrant_client import QdrantClient, models

from ragdata.loader.config import QdrantSettings
from ragdata.loader.plan import Point

HNSW = models.HnswConfigDiff(m=16, ef_construct=100, full_scan_threshold=10000,
                             max_indexing_threads=0, on_disk=False)
OPTIMIZERS = models.OptimizersConfigDiff(indexing_threshold=0)
PAYLOAD_INDEXES = ("book_id", "kind")
BATCH = 256
SCROLL = 1000
TIMEOUT_S = 300


class QdrantDb:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @classmethod
    def connect(cls, settings: QdrantSettings) -> "QdrantDb":
        return cls(QdrantClient(host=settings.host, port=settings.http_port,
                                grpc_port=settings.grpc_port, prefer_grpc=True,
                                timeout=TIMEOUT_S))

    def close(self) -> None:
        self._client.close()

    def exists(self, name: str) -> bool:
        return bool(self._client.collection_exists(name))

    def create(self, name: str, dim: int) -> None:
        self._client.create_collection(
            name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            hnsw_config=HNSW, optimizers_config=OPTIMIZERS, on_disk_payload=True)
        for field in PAYLOAD_INDEXES:
            self._client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD,
                                              wait=True)

    def upsert(self, name: str, points: Sequence[Point]) -> None:
        for start in range(0, len(points), BATCH):
            batch = [models.PointStruct(id=p.id, vector=np.asarray(p.vector, dtype=float).tolist(),
                                        payload=dict(p.payload))
                     for p in points[start:start + BATCH]]
            self._client.upsert(name, points=batch, wait=True)

    def count(self, name: str) -> int:
        return int(self._client.count(name, exact=True).count)

    def _scroll(self, name: str) -> Iterator[Any]:
        offset = None
        while True:
            found, offset = self._client.scroll(name, limit=SCROLL, offset=offset,
                                                with_payload=True, with_vectors=True)
            yield from found
            if offset is None:
                return

    def points(self, name: str) -> list[Point]:
        return [Point(str(r.id), np.asarray(r.vector, dtype=np.float32), dict(r.payload or {}))
                for r in self._scroll(name)]

    def config(self, name: str) -> dict[str, Any]:
        info = self._client.get_collection(name).config
        vectors = info.params.vectors
        return {"size": vectors.size, "distance": str(vectors.distance.value),
                "hnsw": info.hnsw_config.model_dump(include={"m", "ef_construct",
                                                              "full_scan_threshold", "on_disk"}),
                "indexing_threshold": info.optimizer_config.indexing_threshold}
