"""
Context blocks: the exact text the generator saw for each retrieved source.

The backend generator builds ``[i] 書卷 第N章 - 標題 (節)`` + passage text
(``backend/utils/generator.py:_build_context``). The judge must see the same
block — headerless passages made RAGAS faithfulness reject every citation
sentence the prompt itself demands (2026-09-10 audit,
``docs/records/2026-09-10_faithfulness_audit.md``).

Preferred path: the backend returns the block per source (``include_context``);
fallback (legacy sources only): rebuild it here from source metadata +
PostgreSQL content, keeping the header format byte-identical to the generator.
"""

from __future__ import annotations

from typing import Literal

from ragcommon import ids

from .book_names import book_id_of
from .models import SourceInfo

FetchKind = Literal["verse", "range", "record", "build"]

# raw_responses.json `context_source` values whose `contexts` are generator blocks.
CONTEXT_SOURCE_BACKEND = "backend"
CONTEXT_SOURCE_REBUILT = "rebuilt"
CONTEXT_SOURCE_LEGACY = "legacy_headerless"
GENERATOR_CONTEXT_SOURCES = (CONTEXT_SOURCE_BACKEND, CONTEXT_SOURCE_REBUILT)


def format_context_header(index: int, source: SourceInfo) -> str:
    """Header line, byte-identical to the backend generator."""
    chapter = "" if source.chapter is None else source.chapter
    header = f"[{index}] {source.book} 第{chapter}章"
    if source.title:
        header += f" - {source.title}"
    if source.verse_range:
        header += f" ({source.verse_range}節)"
    return header


def format_context_block(index: int, source: SourceInfo, content: str) -> str:
    """Header + passage text, as concatenated by the generator."""
    return f"{format_context_header(index, source)}\n{content}"


def verse_span(raw: object) -> tuple[int, int] | None:
    """Parse a verse number or range ("16", 16, "29-30") into an inclusive span."""
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


def _legacy_verse_id(source: SourceInfo, book_id: str) -> str:
    """The id the legacy verse retriever spells for a verse or range source
    (backend utils/retrieval/verse_retriever.py), from the source's own fields."""
    return f"{book_id}:{source.chapter}:{source.verse_range.strip()}"


def resolve_fetch_kind(source: SourceInfo) -> FetchKind:
    """
    How to fetch a source's text, decided from its payload and never by
    splitting its id (G-IDLINT).

    * ``build``: a new build's record. The payload carries ``kind`` or the id
      follows the ragcommon.ids grammar; its text comes with the backend's
      context blocks (include_context), not from the legacy tables.
    * ``verse`` / ``range``: the id equals the one the legacy verse retriever
      spells from this source's book, chapter and verse_range. A pericope can
      never match (pericope k starts at verse >= k+1 and carries its own
      span), which settles the ``3jn:1:2`` collision: 3 John 1:2 is a verse,
      the 3rd pericope of 3 John 1 is not.
    * ``record``: any other legacy id, a stored pericope or chunk looked up by id.
    """
    if source.kind is not None or ids.is_valid(source.id):
        return "build"
    span = verse_span(source.verse_range)
    book_id = book_id_of(source.book)
    if span and book_id and source.chapter is not None \
            and source.id == _legacy_verse_id(source, book_id):
        return "range" if span[1] > span[0] else "verse"
    return "record"


def contexts_from_raw_item(item: dict) -> list[str] | None:
    """
    Generator-format context blocks from a raw_responses.json item, or None
    when the checkpoint is legacy (headerless) -> caller must rebuild.

    New checkpoints mark ``context_source`` and keep the blocks in ``contexts``;
    transitional ones carry ``sources[].context``.
    """
    tagged = item.get("context_source") in GENERATOR_CONTEXT_SOURCES
    if tagged and (item.get("contexts") or not item.get("sources")):
        return list(item.get("contexts") or [])  # a zero-source sample keeps its tag
    sources = item.get("sources") or []
    if sources and all(s.get("context") for s in sources):
        return [s["context"] for s in sources]
    return None
