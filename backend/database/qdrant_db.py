"""Qdrant access to the serving build's collection ``passages__{build_id}``.

The collection is fixed at startup from rag_meta.builds; points carry the emb
contract payload (record_id, kind, book_id, passage_id, …). Search is plain dense
cosine on the unnamed vector; a book restriction filters on the payload's
``book_id`` (indexed by the loader), never on the Chinese book name.
"""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from config import settings

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None
_collection: Optional[str] = None


def make_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_http_port)


def init_client(collection: str) -> QdrantClient:
    global _client, _collection
    _client, _collection = make_client(), collection
    logger.info("Qdrant client initialized (collection=%s)", collection)
    return _client


def close_client() -> None:
    global _client, _collection
    if _client:
        _client.close()
    _client, _collection = None, None
    logger.info("Qdrant client closed")


def get_client() -> QdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant client not initialized")
    return _client


def collection() -> str:
    if _collection is None:
        raise RuntimeError("Qdrant collection not chosen")
    return _collection


def health_check() -> bool:
    try:
        get_client().get_collections()
        return True
    except Exception:  # noqa: BLE001 — health reports, it does not raise
        return False


def collection_exists() -> bool:
    return bool(get_client().collection_exists(collection()))


def count() -> int:
    return int(get_client().count(collection(), exact=True).count)


def _book_filter(book_ids: Optional[list[str]]) -> Optional[models.Filter]:
    if not book_ids:
        return None
    return models.Filter(must=[models.FieldCondition(key="book_id",
                                                     match=models.MatchAny(any=book_ids))])


def search(query_vector: list[float], top_k: int = 20,
           book_ids: Optional[list[str]] = None) -> list[dict]:
    """Nearest points as {score, payload}; ``book_ids`` restricts to those books."""
    hits = get_client().search(collection_name=collection(), query_vector=query_vector,
                               limit=top_k, query_filter=_book_filter(book_ids))
    return [{"score": hit.score, "payload": dict(hit.payload or {})} for hit in hits]
