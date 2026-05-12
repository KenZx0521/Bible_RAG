#!/usr/bin/env python3
"""P2-B — Embed all Entity nodes into Qdrant `bible_entities` collection.

Builds a 200-char text representation per entity (name + aliases + description
+ top pericope titles) and stores BGE-M3 embeddings in a NEW Qdrant collection
distinct from `bible_embeddings` so entity-aware retrieval does not pollute
the pericope/chunk search top-k.

Usage:
    python scripts/embed_entities.py [--batch-size 64] [--device cuda] [--recreate]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.embeddings.embedder import BGEEmbedder  # noqa: E402

load_dotenv()
logger = logging.getLogger("embed_entities")


COLLECTION_NAME = os.getenv("QDRANT_ENTITY_COLLECTION", "bible_entities")
EMBEDDING_DIM = 1024


_FETCH_ENTITIES_CYPHER = """
MATCH (e:Entity)
OPTIONAL MATCH (e)<-[:MENTIONS]-(src)
WHERE src:Pericope OR src:Chunk
OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(src)
WITH e, src, parent,
     CASE
       WHEN src:Pericope THEN src.title
       WHEN src:Chunk    THEN src.pericope_title
       ELSE NULL
     END AS title,
     CASE
       WHEN src:Pericope THEN src.id
       WHEN src:Chunk    THEN coalesce(parent.id, src.pericope_id)
       ELSE NULL
     END AS pid
WITH e,
     [t IN collect(DISTINCT title) WHERE t IS NOT NULL AND t <> ''][0..5] AS pericope_titles,
     [i IN collect(DISTINCT pid)   WHERE i IS NOT NULL AND i <> ''][0..5] AS pericope_ids
RETURN e.entity_id AS entity_id,
       e.canonical_name AS canonical_name,
       e.aliases AS aliases,
       coalesce(e.description, '') AS description,
       [l IN labels(e) WHERE l <> 'Entity'][0] AS type,
       pericope_titles,
       pericope_ids
ORDER BY e.entity_id
"""


def _build_text(entity: dict, max_chars: int = 200) -> str:
    name = entity.get("canonical_name") or ""
    aliases = entity.get("aliases") or []
    if isinstance(aliases, str):
        try:
            import json as _json
            aliases_decoded = _json.loads(aliases)
            if isinstance(aliases_decoded, list):
                aliases = aliases_decoded
        except Exception:
            aliases = [aliases]
    alias_chunk = f"({', '.join(a for a in aliases if a)})" if aliases else ""

    description = entity.get("description") or ""
    titles = entity.get("pericope_titles") or []
    title_chunk = "; ".join(t for t in titles if t)

    parts = [f"{name}{alias_chunk}"]
    if description:
        parts.append(description)
    if title_chunk:
        parts.append(f"常見於:{title_chunk}")
    text = " ".join(parts).strip()
    return text[:max_chars]


def _ensure_collection(client: QdrantClient, recreate: bool) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME in existing:
        if recreate:
            client.delete_collection(COLLECTION_NAME)
            logger.info("Deleted existing collection %s", COLLECTION_NAME)
        else:
            logger.info("Collection %s already exists — keeping", COLLECTION_NAME)
            return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qmodels.VectorParams(
            size=EMBEDDING_DIM,
            distance=qmodels.Distance.COSINE,
        ),
    )
    logger.info("Created Qdrant collection %s (dim=%d, cosine)", COLLECTION_NAME, EMBEDDING_DIM)


def _entity_uuid(entity_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"entity:{entity_id}"))


def _chunked(it: Iterable[dict], n: int):
    bucket = []
    for x in it:
        bucket.append(x)
        if len(bucket) >= n:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def _fetch_entities(driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(_FETCH_ENTITIES_CYPHER)
        return [dict(r) for r in result]


def _embed_and_upsert(
    client: QdrantClient,
    embedder: BGEEmbedder,
    entities: list[dict],
    batch_size: int,
) -> int:
    total = 0
    for batch in _chunked(entities, batch_size):
        texts = [_build_text(e) for e in batch]
        vectors = embedder.encode_batch(
            texts, batch_size=batch_size, show_progress=False,
        )
        points = []
        for entity, vector in zip(batch, vectors):
            payload = {
                "entity_id": entity["entity_id"],
                "type": entity.get("type") or "",
                "canonical_name": entity.get("canonical_name") or "",
                "aliases": entity.get("aliases") or [],
                "description": entity.get("description") or "",
                "pericope_titles": entity.get("pericope_titles") or [],
                "pericope_ids": entity.get("pericope_ids") or [],
            }
            points.append(qmodels.PointStruct(
                id=_entity_uuid(entity["entity_id"]),
                vector=vector,
                payload=payload,
            ))
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=False)
        total += len(points)
        logger.info("Upserted %d/%d entities", total, len(entities))
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default=None, help="cuda | cpu (auto if omitted)")
    parser.add_argument("--recreate", action="store_true",
                        help="Drop and recreate the bible_entities collection")
    parser.add_argument("--limit", type=int, default=None,
                        help="Embed only first N entities (debug)")
    parser.add_argument("--qdrant-host", default=os.getenv("QDRANT_HOST", "localhost"))
    parser.add_argument("--qdrant-port", type=int, default=int(os.getenv("QDRANT_HTTP_PORT", "6333")))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    client = QdrantClient(host=args.qdrant_host, port=args.qdrant_port)
    _ensure_collection(client, args.recreate)

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_password"),
        ),
    )

    try:
        entities = _fetch_entities(driver)
        logger.info("Fetched %d entities from Neo4j", len(entities))
        if args.limit:
            entities = entities[:args.limit]
        if not entities:
            return 0

        embedder = BGEEmbedder(device=args.device, normalize=True)
        if hasattr(embedder, "load_model"):
            embedder.load_model()
        total = _embed_and_upsert(client, embedder, entities, args.batch_size)
        logger.info("Done. Upserted %d entity vectors into %s", total, COLLECTION_NAME)
    finally:
        driver.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
