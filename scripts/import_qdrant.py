#!/usr/bin/env python3
"""
Import embeddings into Qdrant vector database.

Usage:
    python scripts/import_qdrant.py [--output-dir OUTPUT_DIR] [--batch-size BATCH_SIZE]
"""

import json
import os
import argparse
from pathlib import Path
from typing import Generator

from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
COLLECTION_NAME = "bible_embeddings"
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


def create_collection(client: QdrantClient, recreate: bool = True):
    """Create the bible_embeddings collection."""
    collections = client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if exists:
        if recreate:
            print(f"  Deleting existing collection '{COLLECTION_NAME}'...")
            client.delete_collection(COLLECTION_NAME)
        else:
            print(f"  Collection '{COLLECTION_NAME}' already exists")
            return
    
    print(f"  Creating collection '{COLLECTION_NAME}'...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=VECTOR_DIM,
            distance=models.Distance.COSINE,
        ),
        # Optimize for search performance
        optimizers_config=models.OptimizersConfigDiff(
            indexing_threshold=0,  # Index immediately
        ),
    )
    print(f"  ✓ Collection created with dimension={VECTOR_DIM}, distance=COSINE")


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
    # Verse IDs have format: book:chapter:pericope_index:v:verse_num
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


def import_embeddings(
    client: QdrantClient,
    embeddings_file: Path,
    metadata_map: dict,
    batch_size: int = 100,
) -> int:
    """Import embeddings into Qdrant."""
    points_batch = []
    total = 0
    point_id = 0  # Use sequential IDs
    
    for record in read_jsonl(embeddings_file):
        record_id = record.get("id")
        embedding = record.get("embedding")
        
        if not record_id or not embedding:
            continue
        
        # Get metadata for this record
        meta = metadata_map.get(record_id, {})
        
        # Create point with metadata payload
        payload = {
            "record_id": record_id,
            "type": meta.get("type", record.get("type", "unknown")),
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

        point = models.PointStruct(
            id=point_id,
            vector=embedding,
            payload=payload,
        )
        
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
    vectors_count = getattr(info, 'vectors_count', None) or getattr(info, 'points_count', 0)
    points_count = getattr(info, 'points_count', vectors_count)
    return {
        "vectors_count": vectors_count,
        "points_count": points_count,
        "status": info.status,
    }


def main():
    parser = argparse.ArgumentParser(description="Import embeddings into Qdrant")
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
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    embeddings_file = output_dir / "embeddings.jsonl"
    
    print("=" * 60)
    print("Qdrant Import")
    print("=" * 60)
    
    # Check embeddings file exists
    if not embeddings_file.exists():
        print(f"\n✗ Error: {embeddings_file} not found")
        return
    
    # Connect to Qdrant
    print("\nConnecting to Qdrant...")
    try:
        client = get_qdrant_client()
        # Test connection
        client.get_collections()
        print("✓ Connected successfully")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    # Create collection
    print("\nSetting up collection...")
    create_collection(client, recreate=not args.no_recreate)
    
    # Load metadata
    print("\nLoading metadata...")
    metadata_map = load_embedding_metadata(output_dir)
    print(f"✓ Loaded metadata for {len(metadata_map):,} records")
    
    # Import embeddings
    print("\nImporting embeddings...")
    count = import_embeddings(client, embeddings_file, metadata_map, args.batch_size)
    print(f"✓ Imported {count:,} vectors")
    
    # Verify
    print("\nVerifying collection...")
    stats = verify_collection(client)
    print(f"  Vectors count: {stats['vectors_count']:,}")
    print(f"  Points count: {stats['points_count']:,}")
    print(f"  Status: {stats['status']}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Import Summary")
    print("=" * 60)
    print(f"  Collection: {COLLECTION_NAME}")
    print(f"  Vectors: {count:,}")
    print(f"  Dimension: {VECTOR_DIM}")
    print("=" * 60)


if __name__ == "__main__":
    main()
