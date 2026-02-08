#!/usr/bin/env python3
"""
Import dense + sparse vectors into Qdrant hybrid collection.

Creates a new collection with both dense (BGE-M3) and sparse (BM25) vectors
for hybrid search using RRF fusion.

Usage:
    python scripts/import_qdrant_hybrid.py [--output-dir OUTPUT_DIR] [--batch-size BATCH_SIZE]
"""

import json
import os
import argparse
from pathlib import Path
from typing import Generator, Dict, Tuple, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
COLLECTION_NAME = os.getenv("QDRANT_HYBRID_COLLECTION", "bible_embeddings_hybrid")
VECTOR_DIM = 1024  # BGE-M3 dimension


def get_qdrant_client() -> QdrantClient:
    """Create and return a Qdrant client."""
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_HTTP_PORT", "6333"))
    return QdrantClient(host=host, port=port)


def read_jsonl(filepath: Path) -> Generator[dict, None, None]:
    """Read JSONL file and yield records."""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def create_hybrid_collection(client: QdrantClient, recreate: bool = True):
    """Create the hybrid collection with dense and sparse vector configs."""
    collections = client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)

    if exists:
        if recreate:
            print(f"  Deleting existing collection '{COLLECTION_NAME}'...")
            client.delete_collection(COLLECTION_NAME)
        else:
            print(f"  Collection '{COLLECTION_NAME}' already exists")
            return

    print(f"  Creating hybrid collection '{COLLECTION_NAME}'...")

    # Create collection with named vectors for hybrid search
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=VECTOR_DIM,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(),
        },
        # Optimize for search performance
        optimizers_config=models.OptimizersConfigDiff(
            indexing_threshold=0,  # Index immediately
        ),
    )

    print(f"  ✓ Collection created:")
    print(f"    - Dense vectors: {VECTOR_DIM}D, COSINE distance")
    print(f"    - Sparse vectors: BM25-based")


def load_embedding_metadata(output_dir: Path) -> dict:
    """Load metadata from pericopes.jsonl and chunks.jsonl for payload enrichment."""
    metadata_map = {}

    # Load pericope metadata
    pericopes_file = output_dir / "pericopes.jsonl"
    if pericopes_file.exists():
        for record in read_jsonl(pericopes_file):
            record_id = record.get("id")
            meta = record.get("metadata", {})
            if record_id:
                metadata_map[record_id] = {
                    "type": "pericope",
                    "book_id": meta.get("book_id"),
                    "book_name": meta.get("book_name"),
                    "chapter_num": meta.get("chapter_num"),
                    "title": record.get("title"),
                    "verse_range": meta.get("verse_range"),
                    "token_count": meta.get("token_count"),
                    "content_preview": record.get("content_for_embedding", "")[:200],
                }

    # Load chunk metadata
    chunks_file = output_dir / "chunks.jsonl"
    if chunks_file.exists():
        for record in read_jsonl(chunks_file):
            record_id = record.get("id")
            meta = record.get("metadata", {})
            if record_id:
                metadata_map[record_id] = {
                    "type": "chunk",
                    "book_id": meta.get("book_id"),
                    "book_name": meta.get("book_name"),
                    "chapter_num": meta.get("chapter_num"),
                    "title": meta.get("pericope_title"),
                    "verse_range": meta.get("verse_range"),
                    "token_count": meta.get("token_count"),
                    "chunk_index": meta.get("chunk_index"),
                    "total_chunks": meta.get("total_chunks"),
                    "content_preview": record.get("content_for_embedding", "")[:200],
                }

    # Build verse metadata from pericopes' verses arrays
    if pericopes_file.exists():
        for record in read_jsonl(pericopes_file):
            pericope_id = record.get("id")
            meta = record.get("metadata", {})
            verses = record.get("verses", [])
            if not pericope_id or not verses:
                continue
            for v in verses:
                v_num = v.get("num", "")
                verse_id = f"{pericope_id}:v:{v_num}"
                metadata_map[verse_id] = {
                    "type": "verse",
                    "book_id": meta.get("book_id"),
                    "book_name": meta.get("book_name"),
                    "chapter_num": meta.get("chapter_num"),
                    "title": record.get("title"),
                    "verse_range": v_num,
                    "parent_pericope_id": pericope_id,
                    "content_preview": v.get("text", "")[:200],
                }

    return metadata_map


def load_vectors(
    embeddings_file: Path,
    sparse_file: Path,
) -> Generator[Tuple[str, str, List[float], Dict], None, None]:
    """
    Load and merge dense and sparse vectors.

    Yields:
        Tuple of (record_id, record_type, dense_vector, sparse_vector_dict)
    """
    # Build sparse vector lookup
    sparse_map = {}
    for record in read_jsonl(sparse_file):
        record_id = record.get("id")
        sparse_vector = record.get("sparse_vector", {})
        if record_id:
            sparse_map[record_id] = sparse_vector

    # Yield merged records
    for record in read_jsonl(embeddings_file):
        record_id = record.get("id")
        record_type = record.get("type", "unknown")
        dense_vector = record.get("embedding")

        if not record_id or not dense_vector:
            continue

        sparse_vector = sparse_map.get(record_id, {"indices": [], "values": []})

        yield record_id, record_type, dense_vector, sparse_vector


def import_hybrid_vectors(
    client: QdrantClient,
    embeddings_file: Path,
    sparse_file: Path,
    metadata_map: dict,
    batch_size: int = 100,
) -> int:
    """Import dense + sparse vectors into Qdrant hybrid collection."""
    points_batch = []
    total = 0
    point_id = 0

    for record_id, record_type, dense_vector, sparse_vector in load_vectors(
        embeddings_file, sparse_file
    ):
        # Get metadata for this record
        meta = metadata_map.get(record_id, {})

        # Create payload
        payload = {
            "record_id": record_id,
            "type": meta.get("type", record_type),
            "book_id": meta.get("book_id"),
            "book_name": meta.get("book_name"),
            "chapter_num": meta.get("chapter_num"),
            "title": meta.get("title"),
            "verse_range": meta.get("verse_range"),
            "content_preview": meta.get("content_preview", ""),
        }
        # Add parent_pericope_id for verse-level embeddings
        if meta.get("parent_pericope_id"):
            payload["parent_pericope_id"] = meta["parent_pericope_id"]

        # Create sparse vector object (only if non-empty)
        sparse_vectors = {}
        if sparse_vector.get("indices"):
            sparse_vectors["sparse"] = models.SparseVector(
                indices=sparse_vector["indices"],
                values=sparse_vector["values"],
            )

        # Create point with named vectors
        point = models.PointStruct(
            id=point_id,
            vector={
                "dense": dense_vector,
            },
            payload=payload,
        )

        # Add sparse vector if present
        if sparse_vectors:
            point.vector["sparse"] = sparse_vectors["sparse"]

        points_batch.append(point)
        point_id += 1

        # Batch upsert
        if len(points_batch) >= batch_size:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points_batch,
            )
            total += len(points_batch)
            print(f"  Imported {total} vectors...")
            points_batch = []

    # Insert remaining
    if points_batch:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points_batch,
        )
        total += len(points_batch)

    return total


def verify_collection(client: QdrantClient) -> dict:
    """Verify collection stats."""
    info = client.get_collection(COLLECTION_NAME)
    # Handle different API versions
    vectors_count = getattr(info, "vectors_count", None) or getattr(
        info, "points_count", 0
    )
    points_count = getattr(info, "points_count", vectors_count)
    return {
        "vectors_count": vectors_count,
        "points_count": points_count,
        "status": info.status,
    }


def test_hybrid_search(client: QdrantClient):
    """Run a quick test to verify hybrid search works."""
    print("\nTesting hybrid search...")

    # Get a sample point to use for testing
    sample_points = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=1,
        with_vectors=True,
    )[0]

    if not sample_points:
        print("  ⚠ No points found for testing")
        return

    sample = sample_points[0]
    dense_vector = sample.vector.get("dense") if isinstance(sample.vector, dict) else sample.vector
    sparse_vector = sample.vector.get("sparse") if isinstance(sample.vector, dict) else None

    # Check if query_points is available (qdrant-client >= 1.7.0)
    has_query_points = hasattr(client, 'query_points')

    if has_query_points:
        # New API (qdrant-client >= 1.7.0)
        # Test dense-only search
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vector,
            using="dense",
            limit=3,
        )
        print(f"  ✓ Dense search returned {len(results.points)} results")

        # Test sparse search (if sparse vector exists)
        if sparse_vector:
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=models.SparseVector(
                    indices=sparse_vector.indices,
                    values=sparse_vector.values,
                ),
                using="sparse",
                limit=3,
            )
            print(f"  ✓ Sparse search returned {len(results.points)} results")

            # Test hybrid search with RRF
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(query=dense_vector, using="dense", limit=10),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_vector.indices,
                            values=sparse_vector.values,
                        ),
                        using="sparse",
                        limit=10,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=5,
            )
            print(f"  ✓ Hybrid RRF search returned {len(results.points)} results")
        else:
            print("  ⚠ Sample point has no sparse vector, skipping sparse/hybrid tests")
    else:
        # Old API fallback (qdrant-client < 1.7.0)
        # Test dense-only search using search method
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=("dense", dense_vector),
            limit=3,
        )
        print(f"  ✓ Dense search returned {len(results)} results")

        if sparse_vector:
            print("  ⚠ Sparse/hybrid search requires qdrant-client >= 1.7.0")
            print("  ⚠ Please upgrade: pip install --upgrade qdrant-client")
        else:
            print("  ⚠ Sample point has no sparse vector")


def main():
    parser = argparse.ArgumentParser(
        description="Import dense + sparse vectors into Qdrant hybrid collection"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory containing JSONL files (default: output)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for upsert operations (default: 100)",
    )
    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Don't recreate collection if it exists",
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Skip hybrid search test after import",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    embeddings_file = output_dir / "embeddings.jsonl"
    sparse_file = output_dir / "sparse_vectors.jsonl"

    print("=" * 60)
    print("Qdrant Hybrid Import")
    print("=" * 60)

    # Check required files exist
    if not embeddings_file.exists():
        print(f"\n✗ Error: {embeddings_file} not found")
        print("  Run generate_embeddings.py first")
        return

    if not sparse_file.exists():
        print(f"\n✗ Error: {sparse_file} not found")
        print("  Run generate_sparse_vectors.py first")
        return

    # Connect to Qdrant
    print("\nConnecting to Qdrant...")
    try:
        client = get_qdrant_client()
        client.get_collections()
        print("✓ Connected successfully")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return

    # Create collection
    print("\nSetting up hybrid collection...")
    create_hybrid_collection(client, recreate=not args.no_recreate)

    # Load metadata
    print("\nLoading metadata...")
    metadata_map = load_embedding_metadata(output_dir)
    print(f"✓ Loaded metadata for {len(metadata_map):,} records")

    # Import vectors
    print("\nImporting hybrid vectors...")
    count = import_hybrid_vectors(
        client, embeddings_file, sparse_file, metadata_map, args.batch_size
    )
    print(f"✓ Imported {count:,} vectors")

    # Verify
    print("\nVerifying collection...")
    stats = verify_collection(client)
    print(f"  Points count: {stats['points_count']:,}")
    print(f"  Status: {stats['status']}")

    # Test hybrid search
    if not args.skip_test:
        test_hybrid_search(client)

    # Summary
    print("\n" + "=" * 60)
    print("Import Summary")
    print("=" * 60)
    print(f"  Collection: {COLLECTION_NAME}")
    print(f"  Points: {count:,}")
    print(f"  Dense dimension: {VECTOR_DIM}")
    print(f"  Sparse: BM25-based")
    print("=" * 60)


if __name__ == "__main__":
    main()
