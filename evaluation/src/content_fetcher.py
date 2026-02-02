"""
Fetch pericope/chunk/verse content from PostgreSQL by source ID.

Source ID formats:
  - 3 segments (book:chapter:index)       → pericope  (e.g. rom:8:0)
  - 3 segments (book:chapter:verse)        → verse     (e.g. jhn:3:16)
  - 3 segments (book:chapter:start-end)    → verse range (e.g. psa:23:1-3)
  - 4 segments (book:chapter:index:chunk)  → chunk
"""

from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings

logger = logging.getLogger(__name__)


async def get_pool() -> asyncpg.Pool:
    """Create a connection pool."""
    return await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=2,
        max_size=10,
    )


async def _fetch_verse_range(pool: asyncpg.Pool, book_id: str, chapter: int, start: int, end: int) -> str:
    """Fetch a range of verses from pericopes' verses JSONB field."""
    chapter_id = f"{book_id}:{chapter}"
    rows = await pool.fetch(
        "SELECT verses FROM pericopes WHERE parent_id = $1 ORDER BY id",
        chapter_id,
    )

    verse_texts: dict[int, str] = {}
    for row in rows:
        verses = row["verses"]
        if isinstance(verses, str):
            verses = json.loads(verses)
        for v in verses:
            v_num = v.get("num") or v.get("verse")
            if v_num is not None:
                num = int(v_num)
                if start <= num <= end:
                    verse_texts[num] = v.get("text", "")

    if not verse_texts:
        return ""
    return "\n".join(f"{num}. {verse_texts[num]}" for num in sorted(verse_texts))


async def _fetch_single_verse(pool: asyncpg.Pool, book_id: str, chapter: int, verse_num: int) -> str:
    """Fetch a single verse from pericopes' verses JSONB field."""
    chapter_id = f"{book_id}:{chapter}"
    rows = await pool.fetch(
        "SELECT verses FROM pericopes WHERE parent_id = $1 ORDER BY id",
        chapter_id,
    )

    for row in rows:
        verses = row["verses"]
        if isinstance(verses, str):
            verses = json.loads(verses)
        for v in verses:
            v_num = v.get("num") or v.get("verse")
            if v_num is not None and int(v_num) == verse_num:
                return f"{verse_num}. {v.get('text', '')}"
    return ""


async def get_content_by_id(pool: asyncpg.Pool, source_id: str) -> str:
    """
    Fetch the text content for a source ID.

    Returns the content string, or empty string if not found.
    """
    parts = source_id.split(":")
    n = len(parts)

    if n == 3:
        third = parts[2]

        if "-" in third:
            # Verse range: book:chapter:start-end (e.g. psa:23:1-3)
            start_s, end_s = third.split("-", 1)
            return await _fetch_verse_range(
                pool, parts[0], int(parts[1]), int(start_s), int(end_s)
            )

        # Try pericope first
        row = await pool.fetchrow(
            "SELECT content FROM pericopes WHERE id = $1", source_id
        )
        if row:
            return row["content"]

        # Fallback: try as single verse (e.g. jhn:3:16)
        return await _fetch_single_verse(
            pool, parts[0], int(parts[1]), int(third)
        )

    elif n == 4:
        # Chunk
        row = await pool.fetchrow(
            "SELECT content FROM chunks WHERE id = $1", source_id
        )
        return row["content"] if row else ""

    else:
        # Unknown — try pericope, then chunk
        row = await pool.fetchrow(
            "SELECT content FROM pericopes WHERE id = $1", source_id
        )
        if row is None:
            row = await pool.fetchrow(
                "SELECT content FROM chunks WHERE id = $1", source_id
            )
        return row["content"] if row else ""


async def fetch_contexts(pool: asyncpg.Pool, source_ids: list[str]) -> list[str]:
    """Fetch content for multiple source IDs, preserving order."""
    contexts = []
    for sid in source_ids:
        content = await get_content_by_id(pool, sid)
        if content:
            contexts.append(content)
    return contexts
