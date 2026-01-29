#!/usr/bin/env python3
"""
Import JSONL data into PostgreSQL.

Usage:
    python scripts/import_postgres.py [--output-dir OUTPUT_DIR]
"""

import json
import os
import argparse
from pathlib import Path
from typing import Generator

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_db_connection():
    """Create and return a database connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        database=os.getenv("POSTGRES_DB", "bible_rag"),
        user=os.getenv("POSTGRES_USER", "bible"),
        password=os.getenv("POSTGRES_PASSWORD", "bible_password"),
    )


def read_jsonl(filepath: Path) -> Generator[dict, None, None]:
    """Read JSONL file and yield records."""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def import_books(conn, filepath: Path) -> int:
    """Import books.jsonl into books table."""
    records = list(read_jsonl(filepath))
    if not records:
        return 0

    with conn.cursor() as cur:
        # Clear existing data
        cur.execute("TRUNCATE TABLE books CASCADE")
        
        # Prepare data
        values = [
            (
                r["id"],
                r.get("type", "book"),
                r["name"],
                r["name_en"],
                r["testament"],
                r["category"],
                r["order"],
                r["total_chapters"],
                r["total_pericopes"],
                r["total_verses"],
            )
            for r in records
        ]
        
        # Batch insert
        execute_values(
            cur,
            """
            INSERT INTO books (id, type, name, name_en, testament, category, "order", 
                              total_chapters, total_pericopes, total_verses)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                name_en = EXCLUDED.name_en,
                testament = EXCLUDED.testament,
                category = EXCLUDED.category,
                "order" = EXCLUDED."order",
                total_chapters = EXCLUDED.total_chapters,
                total_pericopes = EXCLUDED.total_pericopes,
                total_verses = EXCLUDED.total_verses
            """,
            values,
        )
        conn.commit()
    
    return len(records)


def import_chapters(conn, filepath: Path) -> int:
    """Import chapters.jsonl into chapters table."""
    records = list(read_jsonl(filepath))
    if not records:
        return 0

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE chapters CASCADE")
        
        values = [
            (
                r["id"],
                r.get("type", "chapter"),
                r["parent_id"],
                r["chapter_num"],
                r["total_verses"],
                r["total_pericopes"],
                json.dumps(r.get("metadata", {})),
                json.dumps(r.get("footnotes", [])),
            )
            for r in records
        ]
        
        execute_values(
            cur,
            """
            INSERT INTO chapters (id, type, parent_id, chapter_num, total_verses, 
                                 total_pericopes, metadata, footnotes)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                parent_id = EXCLUDED.parent_id,
                chapter_num = EXCLUDED.chapter_num,
                total_verses = EXCLUDED.total_verses,
                total_pericopes = EXCLUDED.total_pericopes,
                metadata = EXCLUDED.metadata,
                footnotes = EXCLUDED.footnotes
            """,
            values,
        )
        conn.commit()
    
    return len(records)


def import_pericopes(conn, filepath: Path) -> int:
    """Import pericopes.jsonl into pericopes table."""
    records = list(read_jsonl(filepath))
    if not records:
        return 0

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE pericopes CASCADE")
        
        values = [
            (
                r["id"],
                r.get("type", "pericope"),
                r["parent_id"],
                r["title"],
                r["content"],
                r["content_for_embedding"],
                json.dumps(r.get("metadata", {})),
                json.dumps(r.get("cross_references", [])),
                json.dumps(r.get("verses", [])),
            )
            for r in records
        ]
        
        execute_values(
            cur,
            """
            INSERT INTO pericopes (id, type, parent_id, title, content, content_for_embedding,
                                  metadata, cross_references, verses)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                parent_id = EXCLUDED.parent_id,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                content_for_embedding = EXCLUDED.content_for_embedding,
                metadata = EXCLUDED.metadata,
                cross_references = EXCLUDED.cross_references,
                verses = EXCLUDED.verses
            """,
            values,
        )
        conn.commit()
    
    return len(records)


def import_chunks(conn, filepath: Path) -> int:
    """Import chunks.jsonl into chunks table."""
    records = list(read_jsonl(filepath))
    if not records:
        return 0

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE chunks CASCADE")
        
        values = [
            (
                r["id"],
                r.get("type", "chunk"),
                r["parent_id"],
                r["content"],
                r["content_for_embedding"],
                json.dumps(r.get("metadata", {})),
                json.dumps(r.get("verses", [])),
            )
            for r in records
        ]
        
        execute_values(
            cur,
            """
            INSERT INTO chunks (id, type, parent_id, content, content_for_embedding,
                               metadata, verses)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                parent_id = EXCLUDED.parent_id,
                content = EXCLUDED.content,
                content_for_embedding = EXCLUDED.content_for_embedding,
                metadata = EXCLUDED.metadata,
                verses = EXCLUDED.verses
            """,
            values,
        )
        conn.commit()
    
    return len(records)


def import_entities(conn, filepath: Path) -> int:
    """Import entities.jsonl into entities table."""
    records = list(read_jsonl(filepath))
    if not records:
        return 0

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE entities CASCADE")
        
        values = [
            (
                r["entity_id"],
                r["type"],
                r["canonical_name"],
                json.dumps(r.get("aliases", [])),
                r.get("description", ""),
                r["extraction_method"],
                r.get("mention_count", 0),
            )
            for r in records
        ]
        
        execute_values(
            cur,
            """
            INSERT INTO entities (entity_id, type, canonical_name, aliases, description,
                                 extraction_method, mention_count)
            VALUES %s
            ON CONFLICT (entity_id) DO UPDATE SET
                type = EXCLUDED.type,
                canonical_name = EXCLUDED.canonical_name,
                aliases = EXCLUDED.aliases,
                description = EXCLUDED.description,
                extraction_method = EXCLUDED.extraction_method,
                mention_count = EXCLUDED.mention_count
            """,
            values,
        )
        conn.commit()
    
    return len(records)


def import_entity_mentions(conn, filepath: Path, batch_size: int = 5000) -> int:
    """Import entity_mentions.jsonl into entity_mentions table with batching."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE entity_mentions")
    conn.commit()
    
    total = 0
    batch = []
    
    for record in read_jsonl(filepath):
        batch.append((
            record["mention_id"],
            record["entity_id"],
            record["source_id"],
            record["source_type"],
            record["text_span"],
            record.get("context", ""),
            record.get("start_pos"),
            record.get("end_pos"),
        ))
        
        if len(batch) >= batch_size:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO entity_mentions (mention_id, entity_id, source_id, source_type,
                                                text_span, context, start_pos, end_pos)
                    VALUES %s
                    ON CONFLICT (mention_id) DO NOTHING
                    """,
                    batch,
                )
            conn.commit()
            total += len(batch)
            print(f"  Imported {total} entity mentions...")
            batch = []
    
    # Insert remaining
    if batch:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO entity_mentions (mention_id, entity_id, source_id, source_type,
                                            text_span, context, start_pos, end_pos)
                VALUES %s
                ON CONFLICT (mention_id) DO NOTHING
                """,
                batch,
            )
        conn.commit()
        total += len(batch)
    
    return total


def main():
    parser = argparse.ArgumentParser(description="Import JSONL data into PostgreSQL")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory containing JSONL files (default: output)",
    )
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    
    print("=" * 60)
    print("PostgreSQL Import")
    print("=" * 60)
    
    # Connect to database
    print("\nConnecting to PostgreSQL...")
    try:
        conn = get_db_connection()
        print("✓ Connected successfully")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    try:
        # Import in order (respecting foreign key constraints)
        import_tasks = [
            ("books", import_books, "books.jsonl"),
            ("chapters", import_chapters, "chapters.jsonl"),
            ("pericopes", import_pericopes, "pericopes.jsonl"),
            ("chunks", import_chunks, "chunks.jsonl"),
            ("entities", import_entities, "entities.jsonl"),
            ("entity_mentions", import_entity_mentions, "entity_mentions.jsonl"),
        ]
        
        results = {}
        for table_name, import_func, filename in import_tasks:
            filepath = output_dir / filename
            if not filepath.exists():
                print(f"\n⚠ Skipping {table_name}: {filename} not found")
                continue
            
            print(f"\nImporting {table_name}...")
            count = import_func(conn, filepath)
            results[table_name] = count
            print(f"✓ Imported {count:,} records into {table_name}")
        
        # Summary
        print("\n" + "=" * 60)
        print("Import Summary")
        print("=" * 60)
        total = 0
        for table, count in results.items():
            print(f"  {table}: {count:,} records")
            total += count
        print(f"\n  Total: {total:,} records")
        print("=" * 60)
        
    finally:
        conn.close()
        print("\n✓ Database connection closed")


if __name__ == "__main__":
    main()
