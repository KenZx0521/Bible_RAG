"""PostgreSQL access to the serving build's schema ``b{build_id}`` (asyncpg).

The pool's connections run with ``search_path`` set to the build schema, so the
queries below name the build's tables unqualified; ``rag_meta`` is read once, at
startup, through ``connect_meta``. Ids are interpreted with ragcommon.ids, never by
splitting them. A row a query needs and the build lacks raises LookupError: a
store that disagrees with its own build is a defect, not something to paper over.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

import asyncpg

from config import settings
from database import content
from ragcommon import ids

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

PASSAGES_SQL = """
SELECT p.passage_id, p.pericope_id, p.chapter_key, p.title, p.verse_range, p.start_key,
       p.end_key, p.content, p.unit_refs, c.book_id, c.chapter, b.name AS book_name
FROM passages p
JOIN chapters c ON c.chapter_key = p.chapter_key
JOIN books b ON b.book_id = c.book_id
"""
CHUNKS_SQL = ("SELECT chunk_id, passage_id, unit_refs, start_key, end_key, verse_range "
              "FROM chunks WHERE chunk_id = ANY($1::text[])")
SLOTS_SQL = """
SELECT s.slot_key, s.status, s.unit_key, s.variant_footnote_id, u.label, u.v_start, u.v_end,
       u.text, f.text AS footnote_text
FROM verse_slots s
LEFT JOIN verse_units u ON u.unit_key = s.unit_key
LEFT JOIN footnotes f ON f.fn_id = s.variant_footnote_id
WHERE s.slot_key = ANY($1::text[])
"""
OWNERS_SQL = ("SELECT record_id, payload->>'passage_id' AS passage_id, "
              "payload->'split_passage_ids' AS split_passage_ids "
              "FROM embedding_records WHERE record_id = ANY($1::text[])")


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads,
                              schema="pg_catalog")


def _connect_args() -> dict[str, Any]:
    return {"host": settings.postgres_host, "port": settings.postgres_port,
            "database": settings.postgres_db, "user": settings.postgres_user,
            "password": settings.postgres_password}


@asynccontextmanager
async def connect_meta() -> AsyncIterator[asyncpg.Connection]:
    """One connection with the default search_path, for rag_meta at startup."""
    conn = await asyncpg.connect(**_connect_args())
    try:
        yield conn
    finally:
        await conn.close()


async def init_pool(schema: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(**_connect_args(), min_size=2, max_size=10,
                                      server_settings={"search_path": schema},
                                      init=_init_connection)
    logger.info("PostgreSQL pool created (search_path=%s)", schema)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized")
    return _pool


async def _fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def health_check() -> bool:
    try:
        await _fetch("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 — health reports, it does not raise
        return False


# --- startup checks ---

async def build_info_ids() -> list[str]:
    return [r["build_id"] for r in await _fetch("SELECT build_id FROM build_info")]


async def missing_passages(passage_ids: Sequence[str]) -> list[str]:
    rows = await _fetch("SELECT passage_id FROM passages WHERE passage_id = ANY($1::text[])",
                        list(passage_ids))
    found = {r["passage_id"] for r in rows}
    return [p for p in passage_ids if p not in found]


# --- passages and chunks ---

def _passage(row: asyncpg.Record) -> dict[str, Any]:
    return {"id": row["passage_id"], "kind": "passage", "content": row["content"],
            "title": row["title"] or "", "book_id": row["book_id"],
            "book_name": row["book_name"], "chapter_num": row["chapter"],
            "verse_range": row["verse_range"], "start_key": row["start_key"],
            "end_key": row["end_key"], "passage_id": row["passage_id"],
            "pericope_id": row["pericope_id"], "split_passage_ids": [],
            "unit_refs": row["unit_refs"]}


async def _passage_rows(passage_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    rows = await _fetch(PASSAGES_SQL + "WHERE p.passage_id = ANY($1::text[])",
                        list(dict.fromkeys(passage_ids)))
    return {r["passage_id"]: _passage(r) for r in rows}


def _chunk(row: asyncpg.Record, passage: dict[str, Any]) -> dict[str, Any]:
    text = content.chunk_content(passage["content"], passage["unit_refs"], row["unit_refs"])
    return {**passage, "id": row["chunk_id"], "kind": "chunk", "content": text,
            "verse_range": row["verse_range"], "start_key": row["start_key"],
            "end_key": row["end_key"], "unit_refs": row["unit_refs"]}


def _require(found: dict[str, Any], wanted: Sequence[str], what: str) -> None:
    missing = [w for w in dict.fromkeys(wanted) if w not in found]
    if missing:
        raise LookupError(f"the build has no {what} {missing[:3]}")


async def fetch_sources(passage_ids: Sequence[str], chunk_ids: Sequence[str] = ()
                        ) -> dict[str, dict[str, Any]]:
    """Passages and chunks by id, as candidate fields; raise LookupError for any missing."""
    if not passage_ids and not chunk_ids:
        return {}
    chunk_rows = await _fetch(CHUNKS_SQL, list(dict.fromkeys(chunk_ids))) if chunk_ids else []
    passages = await _passage_rows([*passage_ids, *(r["passage_id"] for r in chunk_rows)])
    _require(passages, passage_ids, "passage")
    sources = {pid: passages[pid] for pid in passage_ids}
    sources.update({r["chunk_id"]: _chunk(r, passages[r["passage_id"]]) for r in chunk_rows})
    _require(sources, chunk_ids, "chunk")
    return sources


async def owner_passages(unit_keys: Sequence[str]) -> dict[str, dict[str, Any]]:
    """unit_key -> {passage_id, split_passage_ids}, from the units' verse records."""
    if not unit_keys:
        return {}
    records = {ids.verse_record_id(u): u for u in unit_keys}
    rows = await _fetch(OWNERS_SQL, list(records))
    owners = {records[r["record_id"]]: {"passage_id": r["passage_id"],
                                        "split_passage_ids": list(r["split_passage_ids"] or [])}
              for r in rows}
    _require(owners, list(unit_keys), "verse record for unit")
    return owners


async def get_content_by_id(record_id: str) -> Optional[dict[str, Any]]:
    """A passage, a chunk, or (for a ``vs:`` record) the passage that owns the unit.

    None when the build holds no such record; an id of another kind raises ValueError.
    """
    parsed = ids.parse(record_id)
    try:
        if parsed.kind == "verse_record":
            unit = parsed.parent.raw
            record_id = (await owner_passages([unit]))[unit]["passage_id"]
            parsed = ids.parse(record_id)
        if parsed.kind == "passage":
            return (await fetch_sources([record_id]))[record_id]
        if parsed.kind == "chunk":
            return (await fetch_sources([], [record_id]))[record_id]
    except LookupError:
        return None
    raise ValueError(f"{record_id} is a {parsed.kind}, not a passage, chunk or verse record")


async def chapter_passages(book_id: str, chapter: int) -> list[dict[str, Any]]:
    """The chapter's passages in canonical order (start key, a second half after its verse)."""
    rows = await _fetch(PASSAGES_SQL + "WHERE p.chapter_key = $1",
                        ids.chapter_key(book_id, chapter))
    return sorted((_passage(r) for r in rows), key=lambda p: content.key_order(p["start_key"]))


# --- verses and chapters ---

async def verse_slots(slot_keys: Sequence[str]) -> list[content.VersePiece]:
    return content.verse_pieces(slot_keys, await _fetch(SLOTS_SQL, list(slot_keys)))


async def book_name(book_id: str) -> Optional[str]:
    rows = await _fetch("SELECT name FROM books WHERE book_id = $1", book_id)
    return rows[0]["name"] if rows else None


async def mid_headings(unit_keys: Sequence[str]) -> list[dict[str, Any]]:
    rows = await _fetch("SELECT heading_id, anchor_unit_key, anchor_offset, text FROM headings "
                        "WHERE pos = 'mid' AND anchor_unit_key = ANY($1::text[]) "
                        "ORDER BY anchor_unit_key, anchor_offset", list(unit_keys))
    return [dict(r) for r in rows]


async def chapter_row(book_id: str, chapter: int) -> Optional[dict[str, Any]]:
    rows = await _fetch("SELECT c.chapter_key, c.chapter, c.max_verse, b.name, b.name_en "
                        "FROM chapters c JOIN books b ON b.book_id = c.book_id "
                        "WHERE c.chapter_key = $1", ids.chapter_key(book_id, chapter))
    return dict(rows[0]) if rows else None


async def chapter_texts(chapter_key: str) -> list[dict[str, Any]]:
    rows = await _fetch('SELECT id, kind, text, "order" FROM chapter_texts '
                        "WHERE chapter_key = $1 ORDER BY kind, id", chapter_key)
    return [dict(r) for r in rows]
