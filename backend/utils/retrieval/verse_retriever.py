"""Verse retriever — exact verse and chapter lookup in PostgreSQL (R1 route).

A verse reference reads the slots it names (design §2.23): a merged unit comes
back whole once, its range marked (asking for 6:3 gives ``2-3``); an omitted slot
comes back as 「本譯本此節從缺」 with its variant footnote. One candidate per
reference; its verse_range is chapter-internal, start_key/end_key name the slots,
and its id is ``vs:{unit}`` for exactly one unit, else ``vr:{start}~{end}``.
A chapter-only reference returns its chapter's passages in canonical order (a
chapter range only its first chapter's, see utils.verse_parser).
"""

from __future__ import annotations

import logging
from typing import Any

from database import content, postgres
from ragcommon import ids
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)
SOURCE = "verse_direct"


def source_id(pieces: list[content.VersePiece], start_key: str, end_key: str) -> str:
    """``vs:{unit}`` for exactly one unit; else ``vr:{start}~{end}`` over the slots."""
    if len(pieces) == 1 and pieces[0].unit_key is not None:
        return ids.verse_record_id(pieces[0].unit_key)
    return ids.verse_range_id(start_key, end_key)


def _passages_of(pieces, owners) -> tuple[str | None, list[str]]:
    spanned = [p for piece in pieces if piece.unit_key
               for p in (owners[piece.unit_key]["passage_id"],
                         *owners[piece.unit_key]["split_passage_ids"])]
    spanned = list(dict.fromkeys(spanned))
    return (spanned[0] if spanned else None), (spanned if len(spanned) > 1 else [])


async def _verse_candidate(ref: VerseRef) -> dict[str, Any]:
    slots = [ids.slot_key(ref.book_id, ref.chapter, v)
             for v in range(ref.verse_start, (ref.verse_end or ref.verse_start) + 1)]
    pieces = await postgres.verse_slots(slots)
    owners = await postgres.owner_passages([p.unit_key for p in pieces if p.unit_key])
    passages = await postgres.fetch_sources([o["passage_id"] for o in owners.values()])
    first, last = pieces[0], pieces[-1]
    start = ids.slot_key(ref.book_id, ref.chapter, first.v_start)
    end = ids.slot_key(ref.book_id, ref.chapter, last.v_end)
    passage_id, split = _passages_of(pieces, owners)
    span = str(first.v_start) if first.v_start == last.v_end else f"{first.v_start}-{last.v_end}"
    return {"id": source_id(pieces, start, end), "kind": "verse",
            "content": "\n".join(p.line for p in pieces),
            "title": passages[passage_id]["title"] if passage_id else "",
            "book_id": ref.book_id, "book_name": await postgres.book_name(ref.book_id),
            "chapter_num": ref.chapter, "verse_range": span, "start_key": start, "end_key": end,
            "passage_id": passage_id, "split_passage_ids": split,
            "source_strategy": SOURCE, "weight": 1.0}


async def _chapter_candidates(ref: VerseRef) -> list[dict[str, Any]]:
    return [{**p, "source_strategy": SOURCE, "weight": 1.0}
            for p in await postgres.chapter_passages(ref.book_id, ref.chapter)]


async def retrieve_by_verse_refs(verse_refs: list[VerseRef]) -> list[dict[str, Any]]:
    """One candidate per verse reference, the passages of each chapter-only one; no repeats."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in verse_refs:
        found = (await _chapter_candidates(ref) if ref.verse_start is None
                 else [await _verse_candidate(ref)])
        for c in found:
            if c["id"] not in seen:
                seen.add(c["id"])
                candidates.append(c)
    logger.info("Verse retriever: %d candidates from %d refs", len(candidates), len(verse_refs))
    return candidates
