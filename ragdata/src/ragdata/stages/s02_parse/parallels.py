"""S2b: parallel-reference lines into ``parallel_refs`` records (design §2.8, G24).

A line such as （可11‧1－11；路19‧28－40；約12‧12－19） is cut at ； into segments;
every segment becomes one record whose ``targets`` are PDF slot ranges resolved by
``ragcommon.refs`` (the one reference grammar of the project). A segment without a
book name continues the book — and chapter — of the segment before it (路6‧27－28；
32－36), so segments are resolved as prefixes of the whole line. A segment that does
not resolve is a ParseError: no reference is dropped quietly.

A same-book segment with no book name whose range covers the heading itself
(（1‧1－7‧27） under 以西結所見的第一個異象) marks the extent of a section, not a
parallel account: its kind is ``section_range`` and it never becomes a parallel link.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from ragcommon import ids, refs
from ragcommon.refs import VerseRef
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse.navy import CLOSERS

PDF = "pdf_deterministic"
SEPARATOR = "；"


def _body(raw: str, where: str) -> str:
    wrapped = (raw[:1] == "*" and len(raw) > 1 and raw[-1] == "*") \
        or (raw[:1] == "（" and raw[-1:] in tuple(CLOSERS))
    if not wrapped:
        raise ParseError(f"{where}: reference line {raw!r} is not wrapped in a bracket or *")
    return raw[1:-1]


def _resolve(segments: Sequence[str], book_id: str, where: str) -> list[tuple[VerseRef, ...]]:
    """The references of each segment, each read in the context of the ones before it."""
    out: list[tuple[VerseRef, ...]] = []
    done: tuple[VerseRef, ...] = ()
    for k, segment in enumerate(segments, start=1):
        try:
            found = refs.parse_refs(SEPARATOR.join(segments[:k]), strict=True,
                                    default_book=book_id).refs
        except refs.RefParseError as exc:
            raise ParseError(f"{where}: reference {segment!r} does not resolve: "
                             f"{exc.reason}") from None
        if found[:len(done)] != done or len(found) == len(done):
            raise ParseError(f"{where}: reference {segment!r} changes or adds nothing")
        out.append(found[len(done):])
        done = found
    return out


def slot_range(ref: VerseRef) -> dict[str, str]:
    """The ``SlotRange`` of a validated reference: its first and last PDF slot."""
    slots = refs.expand_slots(ref)
    return {"book_id": ref.book_id, "start_slot": slots[0], "end_slot": slots[-1]}


def _covers(ref: VerseRef, slot: str) -> bool:
    anchor = ids.parse(slot)
    first = (ref.ch, ref.v_start or 1)
    last = (ref.ch_end, ref.v_end if ref.v_end is not None else 10 ** 6)
    return first <= (anchor.chapter, anchor.verse) <= last


def _kind(segment: str, found: Sequence[VerseRef], book_id: str, anchor_slot: str) -> str:
    own = segment[:1].isdigit() and all(r.book_id == book_id for r in found)
    return "section_range" if own and any(_covers(r, anchor_slot) for r in found) \
        else "parallel"


def parse_rule(segment: str) -> str:
    """The shape of a segment: ``abbr+`` when it names a book, numbers as ``n``."""
    book = "" if segment[:1].isdigit() else "abbr+"
    return book + re.sub(r"[0-9]+", "n", re.sub(r"^[^0-9]+", "", segment))


def parse_line(heading_id: str, raw: str, book_id: str, anchor_slot: str) -> tuple[dict, ...]:
    """Records of one reference line under ``heading_id`` (anchored at ``anchor_slot``)."""
    where = f"{heading_id} {raw!r}"
    segments = _body(raw, where).split(SEPARATOR)
    if not all(segments):
        raise ParseError(f"{where}: empty segment between ；")
    rows: list[dict[str, Any]] = []
    for idx, (segment, found) in enumerate(zip(segments, _resolve(segments, book_id, where))):
        rows.append({
            "pr_id": ids.parallel_ref_id(heading_id, idx + 1), "heading_id": heading_id,
            "raw": raw, "seg_idx": idx, "kind": _kind(segment, found, book_id, anchor_slot),
            "targets": [slot_range(r) for r in found], "parse_rule": parse_rule(segment),
            "provenance_class": PDF,
        })
    return tuple(rows)
