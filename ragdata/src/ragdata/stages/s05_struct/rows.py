"""S5 records: pericopes, passages, chunks and verse_index from the text view.

Pericopes chain within their book (``prev_id``/``next_id``); the last one of each
book but the last names the next book (``next_book_id``). A unit cut by a
mid-verse heading lies in two passages; verse_index gives it to the one holding
its offset 0 and lists both in ``split_passage_ids``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from ragcommon import ids
from ragdata.contract.fields import sha256_text
from ragdata.contract.struct import CHUNK_MAX_TOKENS
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import chunker, content, segment
from ragdata.stages.s05_struct.segment import Section, UNTITLED_REASON
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.stages.s05_struct.view import Piece, TextView, key_range, slot_of

PDF = "pdf_deterministic"
STRUCT_TYPES = ("pericopes", "passages", "chunks", "verse_index")


def passage_tokens(view: TextView, pieces: Sequence[Piece], title: str | None,
                   counter: TokenCounter) -> int:
    """Tokens of the v1c text of a passage."""
    unit = pieces[0].unit
    text = content.v1c_text(view.book_name(unit.book_id), unit.chapter, title,
                            key_range(pieces)[2], content.bodies(content.piece_blocks(view, pieces)))
    return counter.count(text)


def passage_row(view: TextView, sec: Section, seg: tuple[int, int], pieces: Sequence[Piece],
                counter: TokenCounter) -> dict[str, Any]:
    start, end, verse_range = key_range(pieces)
    text = content.render(content.piece_blocks(view, pieces))
    sp = content.superscription_of(view, pieces)
    n = passage_tokens(view, pieces, sec.title, counter)
    return {
        "passage_id": ids.passage_id(start), "pericope_id": sec.pericope_id,
        "chapter_key": pieces[0].chapter_key, "seg_idx": seg[0], "seg_count": seg[1],
        "continued": seg[0] > 0, "title": sec.title, "start_slot": slot_of(start),
        "end_slot": slot_of(end), "verse_range": verse_range, "start_key": start,
        "end_key": end, "start_partial": pieces[0].start > 0,
        "end_partial": pieces[-1].end is not None, "unit_refs": [p.ref() for p in pieces],
        "superscription_id": None if sp is None else sp.id, "content": text,
        "content_sha": sha256_text(text), "token_count": n,
        "requires_chunking": n > CHUNK_MAX_TOKENS, "provenance_class": PDF,
    }


def pericope_row(sec: Section, passage_ids: Sequence[str], links: dict[str, Any]
                 ) -> dict[str, Any]:
    first, last = sec.pieces[0], sec.pieces[-1]
    heading = sec.heading
    return {
        "pericope_id": sec.pericope_id, "book_id": sec.book_id,
        "heading_id": None if heading is None else heading.heading_id,
        "section_heading_id": sec.section_heading_id, "title": sec.title,
        "untitled_reason": UNTITLED_REASON if heading is None else None,
        "start": {"unit_key": first.unit.unit_key, "offset": first.start},
        "end": {"unit_key": last.unit.unit_key, "offset": last.end},
        "start_slot": slot_of(first.first_key), "end_slot": slot_of(last.last_key),
        "chapters": list(range(first.unit.chapter, last.unit.chapter + 1)),
        "passage_ids": list(passage_ids), "prev_id": links["prev"], "next_id": links["next"],
        "next_book_id": links["next_book"], "provenance_class": PDF,
    }


def _book_rows(view: TextView, book_id: str, next_book: str | None, counter: TokenCounter
               ) -> dict[str, list[dict[str, Any]]]:
    secs = segment.sections(view, book_id)
    out: dict[str, list[dict[str, Any]]] = {"pericopes": [], "passages": [], "chunks": []}
    for i, sec in enumerate(secs):
        cut = segment.passage_pieces(sec)
        passages = [passage_row(view, sec, (j, len(cut)), pieces, counter)
                    for j, pieces in enumerate(cut)]
        chunks = [c for row, pieces in zip(passages, cut) if row["requires_chunking"]
                  for c in chunker.chunk_rows(view, row["passage_id"], pieces, sec.title, counter)]
        last = i == len(secs) - 1
        links = {"prev": secs[i - 1].pericope_id if i else None,
                 "next": None if last else secs[i + 1].pericope_id,
                 "next_book": next_book if last else None}
        out["pericopes"].append(pericope_row(sec, [p["passage_id"] for p in passages], links))
        out["passages"].extend(passages)
        out["chunks"].extend(chunks)
    return out


def verse_index_rows(view: TextView, passages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    holders: dict[str, list[tuple[str, int]]] = defaultdict(list)
    pericope_of = {p["passage_id"]: p["pericope_id"] for p in passages}
    for p in passages:
        for ref in p["unit_refs"]:
            holders[ref["unit_key"]].append((p["passage_id"], ref["from"]))
    rows = []
    for unit in (u for b in view.books for u in view.units[b.book_id]):
        held = holders.get(unit.unit_key, [])
        owners = [ps for ps, start in held if start == 0]
        if len(owners) != 1:
            raise StageError(f"{unit.unit_key}: offset 0 lies in {len(owners)} passages")
        rows.append({"unit_key": unit.unit_key, "passage_id": owners[0],
                     "pericope_id": pericope_of[owners[0]],
                     "split_passage_ids": [ps for ps, _ in held] if len(held) > 1 else [],
                     "provenance_class": PDF})
    return rows


def struct_rows(view: TextView, counter: TokenCounter) -> dict[str, list[dict[str, Any]]]:
    """Every struct record but the legacy map, in canonical order."""
    books = [b.book_id for b in view.books]
    per_book = [_book_rows(view, book_id, next_book, counter)
                for book_id, next_book in zip(books, [*books[1:], None])]
    out = {name: [row for rows in per_book for row in rows[name]]
           for name in ("pericopes", "passages", "chunks")}
    return {**out, "verse_index": verse_index_rows(view, out["passages"])}
