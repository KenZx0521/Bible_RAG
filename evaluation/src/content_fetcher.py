"""
Fetch a legacy source's text from the legacy PostgreSQL tables.

``context_blocks.resolve_fetch_kind`` decides from the source's own fields
(never by splitting the id):

  - verse / range: the verses of book, chapter and verse_range, each as
    ``N. text`` (the legacy verse retriever's ids, e.g. jhn:3:16, psa:23:1-3);
  - record: a stored pericope, else a chunk, with that id.

Old verse-record ids (``…:v:N``) are records too and are not found by id:
their block falls back to the checkpoint's stored text (no archived
checkpoint holds one). A new build's sources are refused: their text comes
with the backend's context blocks (include_context).

Verse numbers in ``pericopes.verses`` may be merged ("29-30", 70 entries in
the corpus); ``verse_span`` treats them as inclusive spans.
"""

from __future__ import annotations

import json
import logging

import asyncpg

from .book_names import book_id_of
from .config import settings
from .context_blocks import format_context_block, resolve_fetch_kind, verse_span
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
    row = await pool.fetchrow("SELECT content FROM pericopes WHERE id = $1", source_id)
    return row["content"] if row else ""


async def _fetch_chunk(pool: asyncpg.Pool, source_id: str) -> str:
    row = await pool.fetchrow("SELECT content FROM chunks WHERE id = $1", source_id)
    return row["content"] if row else ""


async def get_content_by_id(pool: asyncpg.Pool, source: SourceInfo) -> str:
    """The text of one legacy source ("" if not found); see the module docstring."""
    kind = resolve_fetch_kind(source)
    if kind == "build":
        raise ValueError(f"{source.id} is a new build's record; its text comes with the "
                         "backend's context blocks (include_context)")
    if kind == "record":
        content = await _fetch_pericope(pool, source.id)
        return content or await _fetch_chunk(pool, source.id)
    book_id, (start, end) = book_id_of(source.book), verse_span(source.verse_range)
    if kind == "verse":
        return await _fetch_single_verse(pool, book_id, source.chapter, start)
    return await _fetch_verse_range(pool, book_id, source.chapter, start, end)


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
    with no text from either is skipped with an error log. A new build's
    sources raise: only the backend has their blocks.
    """
    new = [src.id for src in sources if resolve_fetch_kind(src) == "build"]
    if new:
        raise ValueError(f"sources {new} belong to a new build; their context blocks come "
                         "from the backend (include_context), not from PostgreSQL")
    aligned = stored_texts if stored_texts and len(stored_texts) == len(sources) else None
    blocks = []
    for index, src in enumerate(sources, 1):
        content = ""
        try:
            content = await get_content_by_id(pool, src)
        except Exception as e:  # noqa: BLE001 - one bad id must not lose the sample
            logger.error("[Context] %s: lookup failed for %s: %r", src.book, src.id, e)
        if not content and aligned:
            content = aligned[index - 1]
        if not content:
            logger.error("[Context] %s: no content found for %s; block skipped", src.book, src.id)
            continue
        blocks.append(format_context_block(index, src, content))
    return blocks
