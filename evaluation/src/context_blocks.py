"""
Context blocks: the exact text the generator saw for each retrieved source.

The backend generator builds ``[i] 書卷 第N章 - 標題 (節)`` + passage text
(``backend/utils/generator.py:_build_context``). The judge must see the same
block — headerless passages made RAGAS faithfulness reject every citation
sentence the prompt itself demands (2026-09-10 audit,
``docs/records/2026-09-10_faithfulness_audit.md``).

Preferred path: the backend returns the block per source (``include_context``);
fallback: rebuild it here from source metadata + PostgreSQL content, keeping the
header format byte-identical to the generator.
"""

from __future__ import annotations

from typing import Literal

from .models import SourceInfo

FetchKind = Literal["range", "verse", "pericope", "chunk", "unknown"]

VERSE_DIRECT_STRATEGY = "verse_direct"

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


def resolve_fetch_kind(source_id: str, strategy: str | None, verse_range: str) -> FetchKind:
    """
    Decide which table/lookup a source id refers to.

    Shapes: ``book:chapter:N`` (verse N or pericope index N),
    ``book:chapter:a-b`` (verse range), ``book:chapter:index:chunk`` (chunk),
    ``book:chapter:index:v:verse`` (verse id the backend hydrates with its
    parent pericope -> treated as that pericope).

    ``book:chapter:N`` is ambiguous. A pericope of index N can never span
    exactly verse N (index k starts at verse >= k+1), so ``verse_range == N``
    identifies a verse; the ``verse_direct`` strategy resolves the rare case
    with no verse_range.
    """
    parts = source_id.split(":")
    if len(parts) == 5 and parts[3] == "v" and parts[4].isdigit():
        return "pericope"
    if len(parts) == 4:
        return "chunk"
    if len(parts) != 3:
        return "unknown"
    third = parts[2]
    if "-" in third:
        start, _, end = third.partition("-")
        return "range" if start.isdigit() and end.isdigit() else "unknown"
    if not third.isdigit():
        return "unknown"
    if verse_range and verse_range == third:
        return "verse"
    if strategy == VERSE_DIRECT_STRATEGY and not verse_range:
        return "verse"
    return "pericope"


def pericope_id_of(source_id: str) -> str:
    """The pericope a source id resolves to (parent for ``:v:`` verse ids)."""
    parts = source_id.split(":")
    if len(parts) == 5 and parts[3] == "v":
        return ":".join(parts[:3])
    return source_id


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
