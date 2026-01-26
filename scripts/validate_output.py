#!/usr/bin/env python3
"""
Validate JSONL output files from Bible processing.

Usage:
    python scripts/validate_output.py [OUTPUT_DIR]
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Set


def load_jsonl(filepath: Path) -> List[dict]:
    """Load all records from a JSONL file."""
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{filepath.name}:{line_num}: Invalid JSON - {e}")
    return records


def validate_output(output_dir: Path) -> bool:
    """Validate all output files."""
    print(f"Validating output directory: {output_dir}")
    print("=" * 60)

    # Required files
    required_files = [
        "books.jsonl",
        "chapters.jsonl",
        "pericopes.jsonl",
        "chunks.jsonl",
        "embedding_queue.jsonl",
        "neo4j_nodes.jsonl",
        "neo4j_relationships.jsonl",
    ]

    errors = []
    warnings = []

    # Check file existence
    for filename in required_files:
        filepath = output_dir / filename
        if not filepath.exists():
            errors.append(f"Missing required file: {filename}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Load all files
    print("\nLoading files...")
    data: Dict[str, List[dict]] = {}
    for filename in required_files:
        filepath = output_dir / filename
        try:
            data[filename] = load_jsonl(filepath)
            print(f"  {filename}: {len(data[filename])} records")
        except ValueError as e:
            errors.append(str(e))

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Validate books
    print("\nValidating books...")
    books = data["books.jsonl"]
    if len(books) != 66:
        warnings.append(f"Expected 66 books, found {len(books)}")

    book_ids = {b["id"] for b in books}
    print(f"  Found {len(book_ids)} unique book IDs")

    # Validate chapters
    print("\nValidating chapters...")
    chapters = data["chapters.jsonl"]
    chapter_ids = {c["id"] for c in chapters}
    print(f"  Found {len(chapters)} chapters")

    # Check parent references
    orphan_chapters = 0
    for c in chapters:
        if c.get("parent_id") not in book_ids:
            orphan_chapters += 1
    if orphan_chapters > 0:
        warnings.append(f"{orphan_chapters} chapters have invalid parent_id")

    # Validate pericopes
    print("\nValidating pericopes...")
    pericopes = data["pericopes.jsonl"]
    pericope_ids = {p["id"] for p in pericopes}
    print(f"  Found {len(pericopes)} pericopes")

    # Check parent references
    orphan_pericopes = 0
    for p in pericopes:
        if p.get("parent_id") not in chapter_ids:
            orphan_pericopes += 1
    if orphan_pericopes > 0:
        warnings.append(f"{orphan_pericopes} pericopes have invalid parent_id")

    # Count pericopes requiring chunking
    requires_chunking = sum(1 for p in pericopes if p.get("metadata", {}).get("requires_chunking", False))
    print(f"  Pericopes requiring chunking: {requires_chunking}")

    # Validate chunks
    print("\nValidating chunks...")
    chunks = data["chunks.jsonl"]
    chunk_ids = {c["id"] for c in chunks}
    print(f"  Found {len(chunks)} chunks")

    # Check parent references
    orphan_chunks = 0
    for c in chunks:
        if c.get("parent_id") not in pericope_ids:
            orphan_chunks += 1
    if orphan_chunks > 0:
        warnings.append(f"{orphan_chunks} chunks have invalid parent_id")

    # Validate embedding queue
    print("\nValidating embedding queue...")
    embedding_queue = data["embedding_queue.jsonl"]
    print(f"  Found {len(embedding_queue)} embedding items")

    # Count by type
    pericope_embeds = sum(1 for e in embedding_queue if e.get("type") == "pericope")
    chunk_embeds = sum(1 for e in embedding_queue if e.get("type") == "chunk")
    print(f"    Pericope embeddings: {pericope_embeds}")
    print(f"    Chunk embeddings: {chunk_embeds}")

    # Expected: non-chunked pericopes + all chunks
    expected_embeds = (len(pericopes) - requires_chunking) + len(chunks)
    if len(embedding_queue) != expected_embeds:
        warnings.append(
            f"Embedding queue count mismatch: expected {expected_embeds}, got {len(embedding_queue)}"
        )

    # Validate Neo4j nodes
    print("\nValidating Neo4j nodes...")
    neo4j_nodes = data["neo4j_nodes.jsonl"]
    print(f"  Found {len(neo4j_nodes)} nodes")

    # Count by label
    label_counts: Dict[str, int] = {}
    for node in neo4j_nodes:
        for label in node.get("labels", []):
            label_counts[label] = label_counts.get(label, 0) + 1
    for label, count in sorted(label_counts.items()):
        print(f"    {label}: {count}")

    # Validate Neo4j relationships
    print("\nValidating Neo4j relationships...")
    neo4j_rels = data["neo4j_relationships.jsonl"]
    print(f"  Found {len(neo4j_rels)} relationships")

    # Count by type
    rel_counts: Dict[str, int] = {}
    for rel in neo4j_rels:
        rel_type = rel.get("type", "UNKNOWN")
        rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1
    for rel_type, count in sorted(rel_counts.items()):
        print(f"    {rel_type}: {count}")

    # Token statistics
    print("\nToken statistics...")
    token_counts = [p.get("metadata", {}).get("token_count", 0) for p in pericopes]
    if token_counts:
        total_tokens = sum(token_counts)
        avg_tokens = total_tokens / len(token_counts)
        max_tokens = max(token_counts)
        min_tokens = min(t for t in token_counts if t > 0) if any(t > 0 for t in token_counts) else 0
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Average tokens/pericope: {avg_tokens:.1f}")
        print(f"  Min tokens: {min_tokens}")
        print(f"  Max tokens: {max_tokens}")

    # Print results
    print("\n" + "=" * 60)
    if errors:
        print("VALIDATION FAILED")
        for e in errors:
            print(f"  [ERROR] {e}")
        return False

    if warnings:
        print("VALIDATION PASSED WITH WARNINGS")
        for w in warnings:
            print(f"  [WARNING] {w}")
    else:
        print("VALIDATION PASSED")

    return True


def main():
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "output")

    if not output_dir.exists():
        print(f"Error: Directory not found: {output_dir}")
        sys.exit(1)

    success = validate_output(output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
