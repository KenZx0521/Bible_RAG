"""
Fetch pericope/chunk/verse content from PostgreSQL by source ID.

Source ID formats:
  - 3 segments (book:chapter:index)          → pericope  (e.g. rom:8:0)
  - 3 segments (book:chapter:verse)           → verse     (e.g. jhn:3:16)
  - 3 segments (book:chapter:start-end)       → verse range (e.g. psa:23:1-3)
  - 4 segments (book:chapter:index:chunk)     → chunk
  - 5 segments (book:chapter:index:v:verse)   → parent pericope (backend hydrates
                                                 verse ids with the pericope text)

The verse/pericope forms collide (3jn:1:2 is both 3 John 1:2 and the 2nd
pericope of 3 John 1); ``context_blocks.resolve_fetch_kind`` disambiguates
from the source's verse_range / strategy, so pass them whenever available.

Verse numbers in ``pericopes.verses`` may be merged ("29-30", 70 entries in
the corpus); ``verse_span`` treats them as inclusive spans.
"""

from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings
from .context_blocks import format_context_block, pericope_id_of, resolve_fetch_kind
from .models import SourceInfo

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


def verse_span(raw: object) -> tuple[int, int] | None:
    """Parse a stored verse number ("16", 16, "29-30") into an inclusive span."""
    if raw is None:
        return None
    text = str(raw).strip()
    start, sep, end = text.partition("-")
    if not start.isdigit():
        return None
    if sep and not end.isdigit():
        return None
    a = int(start)
    return (a, int(end)) if sep else (a, a)


def _iter_chapter_verses(rows) -> list[tuple[str, tuple[int, int], str]]:
    """(label, span, text) for every verse entry in the chapter's pericope rows."""
    out = []
    for row in rows:
        verses = row["verses"]
        if isinstance(verses, str):
            verses = json.loads(verses)
        for v in verses:
            raw = v.get("num") or v.get("verse")
            span = verse_span(raw)
            if span is not None:
                out.append((str(raw), span, v.get("text", "")))
    return out


async def _chapter_verses(pool: asyncpg.Pool, book_id: str, chapter: int):
    rows = await pool.fetch(
        "SELECT verses FROM pericopes WHERE parent_id = $1 ORDER BY id",
        f"{book_id}:{chapter}",
    )
    return _iter_chapter_verses(rows)


async def _fetch_verse_range(pool: asyncpg.Pool, book_id: str, chapter: int, start: int, end: int) -> str:
    """Verses overlapping [start, end], each as ``N. text``."""
    hits = [
        (span[0], f"{label}. {text}")
        for label, span, text in await _chapter_verses(pool, book_id, chapter)
        if span[0] <= end and span[1] >= start
    ]
    return "\n".join(line for _, line in sorted(hits))


async def _fetch_single_verse(pool: asyncpg.Pool, book_id: str, chapter: int, verse_num: int) -> str:
    """The verse entry containing ``verse_num`` as ``N. text``."""
    for label, span, text in await _chapter_verses(pool, book_id, chapter):
        if span[0] <= verse_num <= span[1]:
            return f"{label}. {text}"
    return ""


async def _fetch_pericope(pool: asyncpg.Pool, source_id: str) -> str:
    row = await pool.fetchrow("SELECT content FROM pericopes WHERE id = $1", pericope_id_of(source_id))
    return row["content"] if row else ""


async def _fetch_chunk(pool: asyncpg.Pool, source_id: str) -> str:
    row = await pool.fetchrow("SELECT content FROM chunks WHERE id = $1", source_id)
    return row["content"] if row else ""


async def get_content_by_id(
    pool: asyncpg.Pool,
    source_id: str,
    strategy: str | None = None,
    verse_range: str = "",
) -> str:
    """
    Fetch the text content for a source ID.

    ``strategy`` / ``verse_range`` come from the source metadata and resolve
    the verse-vs-pericope id collision. Returns "" if not found.
    """
    kind = resolve_fetch_kind(source_id, strategy, verse_range)
    parts = source_id.split(":")

    if kind == "range":
        start_s, end_s = parts[2].split("-", 1)
        return await _fetch_verse_range(pool, parts[0], int(parts[1]), int(start_s), int(end_s))

    if kind == "verse":
        return await _fetch_single_verse(pool, parts[0], int(parts[1]), int(parts[2]))

    if kind == "chunk":
        return await _fetch_chunk(pool, source_id)

    if kind == "pericope":
        content = await _fetch_pericope(pool, source_id)
        if content or len(parts) != 3:
            return content
        # Legacy checkpoints without metadata: a verse id that is not a pericope id.
        return await _fetch_single_verse(pool, parts[0], int(parts[1]), int(parts[2]))

    # Unknown shape — try pericope, then chunk.
    content = await _fetch_pericope(pool, source_id)
    return content or await _fetch_chunk(pool, source_id)


async def fetch_context_blocks(
    pool: asyncpg.Pool,
    sources: list[SourceInfo],
    stored_texts: list[str] | None = None,
) -> list[str]:
    """
    Rebuild the generator's context blocks (header + text) for sources that
    did not carry one. Indices follow the source position, as the generator
    numbers every source.

    ``stored_texts`` (a legacy checkpoint's headerless ``contexts``, aligned
    with ``sources``) is used when the DB lookup fails or errors; a source
    with no text from either is skipped with an error log.
    """
    aligned = stored_texts if stored_texts and len(stored_texts) == len(sources) else None
    blocks = []
    for index, src in enumerate(sources, 1):
        content = ""
        try:
            content = await get_content_by_id(pool, src.id, src.strategy, src.verse_range)
        except Exception as e:  # noqa: BLE001 - one bad id must not lose the sample
            logger.error("[Context] %s: lookup failed for %s: %r", src.book, src.id, e)
        if not content and aligned:
            content = aligned[index - 1]
        if not content:
            logger.error("[Context] %s: no content found for %s; block skipped", src.book, src.id)
            continue
        blocks.append(format_context_block(index, src, content))
    return blocks
