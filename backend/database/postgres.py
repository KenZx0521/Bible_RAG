"""
PostgreSQL async connection pool and query functions using asyncpg.
"""

import json
import logging
from typing import Optional

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=2,
        max_size=10,
    )
    logger.info("PostgreSQL connection pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized")
    return _pool


async def health_check() -> bool:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


# --- Verse / Chapter queries ---

async def get_chapter(book_id: str, chapter_num: int) -> Optional[dict]:
    """Get chapter with all its pericopes."""
    pool = get_pool()
    chapter_id = f"{book_id}:{chapter_num}"
    async with pool.acquire() as conn:
        chapter = await conn.fetchrow(
            """
            SELECT c.id, c.chapter_num, c.total_verses, c.total_pericopes,
                   b.name as book_name, b.name_en as book_name_en
            FROM chapters c
            JOIN books b ON c.parent_id = b.id
            WHERE c.id = $1
            """,
            chapter_id,
        )
        if not chapter:
            return None

        pericopes = await conn.fetch(
            """
            SELECT id, title, content, verses, metadata
            FROM pericopes
            WHERE parent_id = $1
            ORDER BY id
            """,
            chapter_id,
        )

        return {
            "id": chapter["id"],
            "chapter_num": chapter["chapter_num"],
            "book_name": chapter["book_name"],
            "book_name_en": chapter["book_name_en"],
            "total_verses": chapter["total_verses"],
            "pericopes": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "content": p["content"],
                    "verses": json.loads(p["verses"]) if isinstance(p["verses"], str) else p["verses"],
                    "metadata": json.loads(p["metadata"]) if isinstance(p["metadata"], str) else p["metadata"],
                }
                for p in pericopes
            ],
        }


async def get_verse(book_id: str, chapter_num: int, verse_num: int) -> Optional[dict]:
    """Get a specific verse by searching pericopes' verses JSONB."""
    pool = get_pool()
    chapter_id = f"{book_id}:{chapter_num}"
    async with pool.acquire() as conn:
        pericopes = await conn.fetch(
            """
            SELECT p.id, p.title, p.content, p.verses, p.metadata,
                   b.name as book_name
            FROM pericopes p
            JOIN chapters c ON p.parent_id = c.id
            JOIN books b ON c.parent_id = b.id
            WHERE p.parent_id = $1
            ORDER BY p.id
            """,
            chapter_id,
        )

        for p in pericopes:
            verses = json.loads(p["verses"]) if isinstance(p["verses"], str) else p["verses"]
            for v in verses:
                # verses JSONB uses "num" (string) as the verse number key
                v_num = v.get("num") or v.get("verse")
                if v_num is not None and int(v_num) == verse_num:
                    return {
                        "book_id": book_id,
                        "book_name": p["book_name"],
                        "chapter": chapter_num,
                        "verse": verse_num,
                        "text": v.get("text", ""),
                        "pericope_id": p["id"],
                        "pericope_title": p["title"],
                    }
    return None


async def get_verses_range(book_id: str, chapter_num: int, start_verse: int, end_verse: int) -> list[dict]:
    """Get a range of verses."""
    results = []
    for v in range(start_verse, end_verse + 1):
        verse = await get_verse(book_id, chapter_num, v)
        if verse:
            results.append(verse)
    return results


async def get_pericope_by_id(pericope_id: str) -> Optional[dict]:
    """Get a pericope by ID with full content."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.title, p.content, p.content_for_embedding,
                   p.verses, p.metadata, p.cross_references,
                   b.name as book_name, c.chapter_num
            FROM pericopes p
            JOIN chapters c ON p.parent_id = c.id
            JOIN books b ON c.parent_id = b.id
            WHERE p.id = $1
            """,
            pericope_id,
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "content_for_embedding": row["content_for_embedding"],
            "verses": json.loads(row["verses"]) if isinstance(row["verses"], str) else row["verses"],
            "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            "cross_references": json.loads(row["cross_references"]) if isinstance(row["cross_references"], str) else row["cross_references"],
            "book_name": row["book_name"],
            "chapter_num": row["chapter_num"],
        }


async def get_chunk_by_id(chunk_id: str) -> Optional[dict]:
    """Get a chunk by ID with full content."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ch.id, ch.content, ch.content_for_embedding, ch.verses, ch.metadata,
                   p.title as pericope_title, b.name as book_name, c.chapter_num
            FROM chunks ch
            JOIN pericopes p ON ch.parent_id = p.id
            JOIN chapters c ON p.parent_id = c.id
            JOIN books b ON c.parent_id = b.id
            WHERE ch.id = $1
            """,
            chunk_id,
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "content": row["content"],
            "content_for_embedding": row["content_for_embedding"],
            "verses": json.loads(row["verses"]) if isinstance(row["verses"], str) else row["verses"],
            "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            "title": row["pericope_title"],
            "book_name": row["book_name"],
            "chapter_num": row["chapter_num"],
        }


async def get_content_by_id(record_id: str) -> Optional[dict]:
    """Get content by ID (pericope, chunk, or verse).

    ID formats:
        3 parts (book:chapter:index) = pericope
        4 parts (book:chapter:index:chunk_index) = chunk (4th part is digit)
        5 parts (book:chapter:index:v:verse_num) = verse (4th part is 'v')
    """
    parts = record_id.split(":")
    if len(parts) == 5 and parts[3] == "v":
        # Verse ID — hydrate with parent pericope content
        parent_pericope_id = ":".join(parts[:3])
        return await get_pericope_by_id(parent_pericope_id)
    if len(parts) == 4:
        return await get_chunk_by_id(record_id)
    return await get_pericope_by_id(record_id)


async def search_pericopes_by_verse_ref(book_id: str, chapter_num: int, verse_num: Optional[int] = None) -> list[dict]:
    """Find pericopes containing a specific verse reference."""
    pool = get_pool()
    chapter_id = f"{book_id}:{chapter_num}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.title, p.content, p.verses, p.metadata,
                   b.name as book_name, c.chapter_num
            FROM pericopes p
            JOIN chapters c ON p.parent_id = c.id
            JOIN books b ON c.parent_id = b.id
            WHERE p.parent_id = $1
            ORDER BY p.id
            """,
            chapter_id,
        )

        results = []
        for row in rows:
            verses = json.loads(row["verses"]) if isinstance(row["verses"], str) else row["verses"]
            metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            if verse_num is not None:
                verse_nums = [int(v.get("num") or v.get("verse") or 0) for v in verses]
                if verse_num not in verse_nums:
                    continue
            results.append({
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "book_name": row["book_name"],
                "chapter_num": row["chapter_num"],
                "verse_range": metadata.get("verse_range", ""),
                "verses": verses,
            })
        return results


async def get_entity(entity_id: str) -> Optional[dict]:
    """Get entity info by entity_id."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM entities WHERE entity_id = $1",
            entity_id,
        )
        if not row:
            return None
        return {
            "entity_id": row["entity_id"],
            "type": row["type"],
            "canonical_name": row["canonical_name"],
            "aliases": json.loads(row["aliases"]) if isinstance(row["aliases"], str) else row["aliases"],
            "description": row["description"],
            "mention_count": row["mention_count"],
        }


async def search_entities_by_name(name: str, limit: int = 10) -> list[dict]:
    """Search entities by canonical name or alias."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT entity_id, type, canonical_name, aliases, description, mention_count
            FROM entities
            WHERE canonical_name ILIKE $1
               OR aliases::text ILIKE $1
            ORDER BY mention_count DESC
            LIMIT $2
            """,
            f"%{name}%",
            limit,
        )
        return [
            {
                "entity_id": r["entity_id"],
                "type": r["type"],
                "canonical_name": r["canonical_name"],
                "aliases": json.loads(r["aliases"]) if isinstance(r["aliases"], str) else r["aliases"],
                "description": r["description"],
                "mention_count": r["mention_count"],
            }
            for r in rows
        ]


async def get_entity_mentions(entity_id: str, limit: int = 20) -> list[dict]:
    """Get mentions for an entity with source content."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT em.source_id, em.source_type, em.text_span, em.context
            FROM entity_mentions em
            WHERE em.entity_id = $1
            ORDER BY em.source_id
            LIMIT $2
            """,
            entity_id,
            limit,
        )
        return [dict(r) for r in rows]
