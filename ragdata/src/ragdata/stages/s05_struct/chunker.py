"""Chunks of long passages: bible_chunking/hierarchical_chunker.py ported to pieces.

Only a passage whose v1c text has more than 768 tokens is chunked (design §2.15).
The old logic is kept: pieces are added while the running count stays within
``512 - tokens(head) - 20``; a full chunk is closed and the next one starts with
its last piece (1-piece overlap); a final chunk under 128 tokens of at most 3
pieces is merged into the one before. A piece is one verse, or the part of a verse
the passage holds; its count is that of its block texts (the superscription goes
with the first piece). Chunk ids use keys, so a chunk starting on a half verse
is ``ck:act.9.19b~…``. A chunk over 768 tokens stops the build.
"""

from __future__ import annotations

from typing import Any, Sequence

from ragcommon import ids
from ragdata.contract.struct import CHUNK_MAX_TOKENS
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import content
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.stages.s05_struct.view import Piece, TextView, key_range

TARGET_TOKENS = 512
MIN_TOKENS = 128
OVERLAP = 1
MERGE_MAX_PIECES = 3
HEAD_SLACK = 20        # room the old chunker kept for the verse range in the head
PDF = "pdf_deterministic"


def plan_chunks(counts: Sequence[int], budget: int) -> list[tuple[int, int]]:
    """``[lo, hi)`` piece ranges, as ``HierarchicalChunker._create_chunks`` cut verses."""
    too_big = [i for i, n in enumerate(counts) if n > budget]
    if too_big:
        raise StageError(f"pieces {too_big} alone exceed the chunk budget of {budget} tokens")
    chunks: list[tuple[int, int]] = []
    lo, total = 0, 0
    for i, n in enumerate(counts):
        if total + n > budget and i > lo:
            chunks.append((lo, i))
            lo = i - OVERLAP
            total = sum(counts[lo:i])
        total += n
    tail = len(counts) - lo
    if chunks and total < MIN_TOKENS and tail <= MERGE_MAX_PIECES:
        chunks[-1] = (chunks[-1][0], len(counts))
    else:
        chunks.append((lo, len(counts)))
    return chunks


def _row(passage_id: str, idx: int, pieces: Sequence[Piece], overlap: Sequence[Piece],
         token_count: int) -> dict[str, Any]:
    start, end, verse_range = key_range(pieces)
    return {"chunk_id": ids.chunk_id(start, end), "passage_id": passage_id, "idx": idx,
            "unit_refs": [p.ref() for p in pieces],
            "overlap_unit_keys": [p.unit.unit_key for p in overlap],
            "start_key": start, "end_key": end, "verse_range": verse_range,
            "token_count": token_count, "provenance_class": PDF}


def chunk_rows(view: TextView, passage_id: str, pieces: Sequence[Piece], title: str | None,
               counter: TokenCounter) -> list[dict[str, Any]]:
    """The chunks of one passage (pieces of one chapter)."""
    unit = pieces[0].unit
    name = view.book_name(unit.book_id)
    groups = content.piece_blocks(view, pieces)
    counts = [counter.count(" ".join(content.bodies([g]))) for g in groups]
    budget = TARGET_TOKENS - counter.count(content.v1c_head(name, unit.chapter, title)) - HEAD_SLACK
    rows, prev_hi = [], None
    for idx, (lo, hi) in enumerate(plan_chunks(counts, budget)):
        verse_range = key_range(pieces[lo:hi])[2]
        text = content.v1c_text(name, unit.chapter, title, verse_range,
                                content.bodies(groups[lo:hi]))
        n = counter.count(text)
        if n > CHUNK_MAX_TOKENS:
            raise StageError(f"{passage_id}: chunk {idx} has {n} tokens, over {CHUNK_MAX_TOKENS}")
        overlap = pieces[lo:prev_hi] if prev_hi is not None else ()
        rows.append(_row(passage_id, idx, pieces[lo:hi], overlap, n))
        prev_hi = hi
    return rows
