"""G-STRUCT (design §8): the struct layer is the text layer, segmented as S5 defines.

Checked against the text records the layer was built on (the snapshot holds both):

- coverage: the passages of each chapter run through its units in order and
  cover every character once; the pericopes of each book do the same through
  their passages, and start and end where their first and last piece do;
- headings: every heading position opens exactly one pericope, titled and
  linked as its stack says (the lowest heading names it, its parent is the
  ``section_heading_id``); an untitled pericope only opens a book; at most one
  mid-verse heading per unit and none in a merged unit; every heading is set in
  the heading style, does not start with （ and balances its brackets;
- NEXT: pericopes chain within their book and the last one names the next book;
- passages: keys, partial flags, superscription, ``content`` and the v1c token
  count are what S5 derives from the pieces; a cut unit is owned (verse_index)
  by the passage holding its offset 0 and lists both passages;
- chunks: a passage is chunked iff it is over 768 tokens; its chunks are runs of
  its pieces from first to last, each overlapping the previous by one piece, and
  their token counts are the tokenizer's.

Report only (design §8): headings of 8 or more characters that occur word for
word in a verse are listed in ``observed``; they are real headings, flagged for
review when the list changes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

from ragcommon import ids
from ragdata.gates.base import GateResult, Snapshot, capped
from ragdata.stages.errors import StageError
from ragdata.stages.s02_parse.navy import STYLE_CLASS
from ragdata.stages.s05_struct import chunker, content, rows
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.stages.s05_struct.view import Piece, TextView, key_range, text_view

NAME = "G-STRUCT"
HEADING_STYLE_CLASSES = frozenset({STYLE_CLASS})
CLOSERS = {"）": "（", "〕": "〔", "」": "「", "』": "『", ")": "("}
MIN_QUOTED = 8
Ref = tuple[str, int, int | None]


@dataclass(frozen=True)
class _Ctx:
    view: TextView
    snapshot: Snapshot
    passages: Mapping[str, Any]
    chunks: Mapping[str, tuple[Any, ...]]
    index: Mapping[str, int]               # unit_key -> its index in the book
    counter: TokenCounter


def _refs(record: Any) -> list[Ref]:
    return [(r.unit_key, r.from_, r.to) for r in record.unit_refs]


def _pieces(ctx: _Ctx, refs: Sequence[Ref]) -> tuple[Piece, ...] | None:
    if any(k not in ctx.view.unit for k, _, _ in refs):
        return None
    return tuple(Piece(ctx.view.unit[k], a, b) for k, a, b in refs)


def _tile(where: str, refs: Sequence[Ref], units: Sequence[Any]) -> list[str]:
    """``refs`` run through ``units`` in order, each unit from offset 0 to its end once."""
    pos = 0
    for unit in units:
        at = 0
        while True:
            if pos == len(refs) or refs[pos][0] != unit.unit_key:
                return [f"{where}: {unit.unit_key} is not covered from offset {at}"]
            _, start, end = refs[pos]
            pos += 1
            if start != at:
                return [f"{where}: {unit.unit_key} is covered from {start}, expected {at}"]
            if end is None:
                break
            at = end
    return [] if pos == len(refs) else [f"{where}: {refs[pos][0]} is covered out of order"]


def _key(key: str) -> tuple[int, int, bool]:
    p = ids.parse(key)
    return p.chapter, p.verse, p.half


def _chapter_coverage(ctx: _Ctx) -> Iterator[str]:
    by_chapter: dict[str, list[Any]] = defaultdict(list)
    for p in ctx.passages.values():
        by_chapter[p.chapter_key].append(p)
    chapters: dict[str, list[Any]] = defaultdict(list)
    for u in (u for b in ctx.view.books for u in ctx.view.units[b.book_id]):
        chapters[ids.chapter_key(u.book_id, u.chapter)].append(u)
    yield from (f"passages: chapter {c} is not in the text layer"
                for c in sorted(set(by_chapter) - set(chapters)))
    for chapter, units in chapters.items():
        held = sorted(by_chapter.get(chapter, ()), key=lambda p: _key(p.start_key))
        yield from _tile(f"chapter {chapter}", [r for p in held for r in _refs(p)], units)


def _start(ctx: _Ctx, pericope: Any) -> tuple[int, int]:
    return ctx.index.get(pericope.start.unit_key, -1), pericope.start.offset


def _pericope_refs(ctx: _Ctx, pericope: Any) -> list[Ref]:
    return [r for pid in pericope.passage_ids if pid in ctx.passages
            for r in _refs(ctx.passages[pid])]


def _book_coverage(ctx: _Ctx) -> Iterator[str]:
    by_book: dict[str, list[Any]] = defaultdict(list)
    for p in ctx.snapshot.of("pericopes"):
        by_book[p.book_id].append(p)
    for book in ctx.view.books:
        held = sorted(by_book.get(book.book_id, ()), key=lambda p: _start(ctx, p))
        yield from _tile(f"book {book.book_id}", [r for p in held for r in _pericope_refs(ctx, p)],
                         ctx.view.units[book.book_id])
        for p in held:
            refs = _pericope_refs(ctx, p)
            ends = refs and ((refs[0][0], refs[0][1]), (refs[-1][0], refs[-1][2]))
            if ends != ((p.start.unit_key, p.start.offset), (p.end.unit_key, p.end.offset)):
                yield f"{p.pericope_id}: start/end differ from its first and last piece"


def _passage_fields(ctx: _Ctx) -> Iterator[str]:
    for p in ctx.passages.values():
        pieces = _pieces(ctx, _refs(p))
        if pieces is None:
            yield f"{p.passage_id}: refers to a unit the text layer does not hold"
            continue
        start, end, _ = key_range(pieces)
        if (p.start_key, p.end_key, p.start_partial, p.end_partial) != (
                start, end, pieces[0].start > 0, pieces[-1].end is not None):
            yield f"{p.passage_id}: keys or partial flags differ from its pieces"
        sp = content.superscription_of(ctx.view, pieces)
        if p.superscription_id != (None if sp is None else sp.id):
            yield f"{p.passage_id}: superscription_id is {p.superscription_id}"
        if p.content != content.render(content.piece_blocks(ctx.view, pieces)):
            yield f"{p.passage_id}: content is not its pieces' text"
        n = rows.passage_tokens(ctx.view, pieces, p.title, ctx.counter)
        if p.token_count != n:
            yield f"{p.passage_id}: token_count {p.token_count}, the tokenizer gives {n}"


def _stack_links(stack: Sequence[Any]) -> Iterator[str]:
    for upper, lower in zip(stack, stack[1:]):
        if lower.parent_heading_id != upper.heading_id:
            yield f"{upper.heading_id}: stacked above {lower.heading_id} but not its parent"


def _expected_heading(stack: Sequence[Any]) -> dict[str, Any]:
    if not stack:
        return {"heading_id": None, "section_heading_id": None, "title": None}
    low = stack[-1]
    return {"heading_id": low.heading_id, "section_heading_id": low.parent_heading_id,
            "title": low.display_title}


def _pericope_headings(ctx: _Ctx) -> Iterator[str]:
    opened: set[tuple[str, tuple[int, int]]] = set()
    for p in ctx.snapshot.of("pericopes"):
        pos = _start(ctx, p)
        opened.add((p.book_id, pos))
        stack = ctx.view.stacks.get(p.book_id, {}).get(pos, ())
        if not stack and pos != (0, 0):
            yield f"{p.pericope_id}: no heading opens it and it does not open its book"
        for name, want in _expected_heading(stack).items():
            if getattr(p, name) != want:
                yield f"{p.pericope_id}: {name} is {getattr(p, name)!r}, expected {want!r}"
    for book_id, stacks in ctx.view.stacks.items():
        for pos, stack in stacks.items():
            yield from _stack_links(stack)
            if (book_id, pos) not in opened:
                yield f"{', '.join(h.heading_id for h in stack)}: opens no pericope"


def _mid_headings(ctx: _Ctx) -> Iterator[str]:
    mids = [h for h in ctx.snapshot.of("headings") if h.pos == "mid"]
    for unit, n in sorted(Counter(h.anchor_unit_key for h in mids).items()):
        if n > 1:
            yield f"{unit}: {n} mid-verse headings"
    for h in mids:
        unit = ctx.view.unit.get(h.anchor_unit_key)
        if unit is not None and unit.v_end > unit.v_start:
            yield f"{h.heading_id}: mid-verse heading in merged unit {unit.unit_key}"


def _balanced(text: str) -> bool:
    open_: list[str] = []
    for ch in text:
        if ch in CLOSERS.values():
            open_.append(ch)
        elif ch in CLOSERS and (not open_ or open_.pop() != CLOSERS[ch]):
            return False
    return not open_


def _heading_form(ctx: _Ctx) -> Iterator[str]:
    for h in ctx.snapshot.of("headings"):
        if h.prov.style_class not in HEADING_STYLE_CLASSES:
            yield f"{h.heading_id}: style class {h.prov.style_class} is not a heading style"
        if h.text_pdf.startswith("（"):
            yield f"{h.heading_id}: starts with （"
        if not _balanced(h.text_pdf):
            yield f"{h.heading_id}: brackets do not balance in {h.text_pdf!r}"


def _chain(ctx: _Ctx) -> Iterator[str]:
    by_book: dict[str, list[Any]] = defaultdict(list)
    for p in ctx.snapshot.of("pericopes"):
        by_book[p.book_id].append(p)
    books = [b.book_id for b in ctx.view.books]
    for book_id, next_book in zip(books, [*books[1:], None]):
        held = sorted(by_book.get(book_id, ()), key=lambda p: _start(ctx, p))
        for i, p in enumerate(held):
            last = i == len(held) - 1
            want = {"prev_id": held[i - 1].pericope_id if i else None,
                    "next_id": None if last else held[i + 1].pericope_id,
                    "next_book_id": next_book if last else None}
            for name, value in want.items():
                if getattr(p, name) != value:
                    yield f"{p.pericope_id}: {name} is {getattr(p, name)}, expected {value}"


def _verse_index(ctx: _Ctx) -> Iterator[str]:
    held: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for p in ctx.passages.values():
        for key, start, _ in _refs(p):
            held[key].append((p.passage_id, start))
    rows_ = ctx.snapshot.index("verse_index")
    for unit in (u for b in ctx.view.books for u in ctx.view.units[b.book_id]):
        row, here = rows_.get(unit.unit_key), held.get(unit.unit_key, [])
        owners = [pid for pid, start in here if start == 0]
        if row is None or len(owners) != 1:
            yield f"{unit.unit_key}: no verse_index row, or {len(owners)} passages hold offset 0"
            continue
        split = [pid for pid, _ in here] if len(here) > 1 else []
        pericope = ctx.passages[owners[0]].pericope_id
        for name, want in (("passage_id", owners[0]), ("split_passage_ids", tuple(split)),
                           ("pericope_id", pericope)):
            if getattr(row, name) != want:
                yield f"{unit.unit_key}: verse_index {name} is {getattr(row, name)}, expected {want}"


def _chunk_runs(ctx: _Ctx, p: Any, chunks: Sequence[Any]) -> Iterator[str]:
    refs, prev_hi = _refs(p), None
    for c in chunks:
        mine = _refs(c)
        lo = next((i for i in range(len(refs)) if refs[i:i + len(mine)] == mine), None)
        if lo is None:
            yield f"{c.chunk_id}: not a run of the pieces of {p.passage_id}"
            return
        hi = lo + len(mine)
        expect_lo = 0 if prev_hi is None else prev_hi - chunker.OVERLAP
        overlap = [] if prev_hi is None else [k for k, _, _ in refs[lo:prev_hi]]
        if lo != expect_lo or (prev_hi is not None and hi <= prev_hi):
            yield f"{c.chunk_id}: starts at piece {lo} of {p.passage_id}, expected {expect_lo}"
        if list(c.overlap_unit_keys) != overlap:
            yield f"{c.chunk_id}: overlap_unit_keys {list(c.overlap_unit_keys)}, expected {overlap}"
        prev_hi = hi
    if prev_hi != len(refs):
        yield f"{p.passage_id}: its chunks end at piece {prev_hi} of {len(refs)}"


def _chunk_fields(ctx: _Ctx, p: Any, c: Any) -> Iterator[str]:
    pieces = _pieces(ctx, _refs(c))
    if pieces is None:
        return
    start, end, verse_range = key_range(pieces)
    if (c.start_key, c.end_key, c.verse_range) != (start, end, verse_range):
        yield f"{c.chunk_id}: keys differ from its pieces"
    unit = pieces[0].unit
    text = content.v1c_text(ctx.view.book_name(unit.book_id), unit.chapter, p.title, verse_range,
                            content.bodies(content.piece_blocks(ctx.view, pieces)))
    n = ctx.counter.count(text)
    if c.token_count != n:
        yield f"{c.chunk_id}: token_count {c.token_count}, the tokenizer gives {n}"


def _chunks(ctx: _Ctx) -> Iterator[str]:
    for p in ctx.passages.values():
        chunks = ctx.chunks.get(p.passage_id, ())
        if p.requires_chunking != bool(chunks):
            yield f"{p.passage_id}: requires_chunking is {p.requires_chunking} with {len(chunks)} chunks"
        if chunks:
            yield from _chunk_runs(ctx, p, chunks)
            for c in chunks:
                yield from _chunk_fields(ctx, p, c)


def _quoted_headings(ctx: _Ctx) -> list[str]:
    body = "\n".join(u.text for b in ctx.view.books for u in ctx.view.units[b.book_id])
    return sorted(h.heading_id for h in ctx.snapshot.of("headings")
                  if len(h.text) >= MIN_QUOTED and h.text in body)


def _observed(ctx: _Ctx, violations: int) -> dict[str, Any]:
    pericopes = ctx.snapshot.of("pericopes")
    return {"violations": violations, "pericopes": len(pericopes),
            "passages": len(ctx.passages), "chunks": len(ctx.snapshot.of("chunks")),
            "next": sum(p.next_id is not None for p in pericopes),
            "next_book": sum(p.next_book_id is not None for p in pericopes),
            "untitled": sum(p.heading_id is None for p in pericopes),
            "split_units": sum(bool(v.split_passage_ids) for v in ctx.snapshot.of("verse_index")),
            "headings_in_verse_text": _quoted_headings(ctx)}


CHECKS = (_chapter_coverage, _book_coverage, _passage_fields, _pericope_headings, _mid_headings,
          _heading_form, _chain, _verse_index, _chunks)


def _context(snapshot: Snapshot, counter: TokenCounter) -> _Ctx:
    view = text_view(snapshot)
    chunks: dict[str, list[Any]] = defaultdict(list)
    for c in sorted(snapshot.of("chunks"), key=lambda c: c.idx):
        chunks[c.passage_id].append(c)
    return _Ctx(view, snapshot, snapshot.index("passages"),
                {k: tuple(v) for k, v in chunks.items()},
                {u.unit_key: i for b in view.units.values() for i, u in enumerate(b)}, counter)


def check_struct(snapshot: Snapshot, counter: TokenCounter) -> GateResult:
    """Gate the struct records of ``snapshot`` against its text records."""
    try:
        ctx = _context(snapshot, counter)
    except StageError as exc:
        return GateResult(NAME, True, False, {"violations": 1}, {"violations": 0}, (str(exc),))
    violations = [v for check in CHECKS for v in check(ctx)]
    return GateResult(NAME, True, not violations, _observed(ctx, len(violations)),
                      {"violations": 0}, capped(violations))
