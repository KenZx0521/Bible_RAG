"""Curated cross references in verse coordinates (W1 1B, XREF-1 / X4).

A supplementary definition names both ends as 'book chapter:verses', e.g.
'rev 18:2-8' > 'jer 51:6-9,45'. Each end resolves verse by verse through a
(book, chapter, verse) → pericope_id map (the keys of
import_tsk_crossrefs.build_verse_map). A definition whose verses straddle a
pericope boundary yields one anchor per touched (source, target) pericope
pair, each carrying only that pair's verses, at most MAX_FANOUT per
definition: 'rev 18:2-8>jer 51:6-9' (jer:51:0) and 'rev 18:2-8>jer 51:45'
(jer:51:5). Anything that does not resolve cleanly is an error; nothing falls
back to a chapter or skips silently.

Pure: no I/O. Shared by Step 0 (process_bible), validate_output, Step 9 and
xref_probe.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, NamedTuple

MAX_FANOUT = 3  # anchors one definition may produce (X4)

VerseMap = Mapping[tuple[str, int, int], str]

_BOOK = re.compile(r"[0-9a-z]+")
_NUMBER = re.compile(r"[0-9]+")


class XrefDefinitionError(ValueError):
    """A coordinate or definition that does not resolve; .errors lists every problem."""

    def __init__(self, *errors: str):
        super().__init__("\n".join(errors))
        self.errors = errors


class Coord(NamedTuple):
    book: str
    chapter: int
    verses: tuple[int, ...]


class Anchor(NamedTuple):
    """One (source pericope, target pericope) pair of a definition."""

    start: str
    end: str
    text: str           # e.g. 'rev 18:2-8>jer 51:45': this pair's verse subsets
    ref_type: str
    description: str
    tsk_exempt: str | None


def _parse_verses(spec: str, text: str) -> tuple[int, ...]:
    """'n', 'a-b' or a comma list of those, ascending ranges, no verse twice."""
    if not spec:
        raise XrefDefinitionError(f"{text!r}: no verses")
    if any(ch.isspace() for ch in spec):
        raise XrefDefinitionError(f"{text!r}: a space inside the verses")
    if ":" in spec:
        raise XrefDefinitionError(f"{text!r}: crosses a chapter (one chapter per end)")
    verses: list[int] = []
    for part in spec.split(","):
        lo, dash, hi = part.partition("-")
        if not _NUMBER.fullmatch(lo) or (dash and not _NUMBER.fullmatch(hi)):
            raise XrefDefinitionError(f"{text!r}: {part!r} is not n or a-b")
        first, last = int(lo), int(hi or lo)
        if last < first:
            raise XrefDefinitionError(f"{text!r}: descending range {part!r}")
        verses.extend(range(first, last + 1))
    if len(set(verses)) != len(verses):
        raise XrefDefinitionError(f"{text!r}: a verse is listed twice")
    return tuple(verses)


def parse_coord(text: str) -> Coord:
    """'jer 51:6-9,45' → Coord('jer', 51, (6, 7, 8, 9, 45))."""
    book, space, rest = text.partition(" ")
    chapter, colon, spec = rest.partition(":")
    if not (space and colon and _BOOK.fullmatch(book) and _NUMBER.fullmatch(chapter)):
        raise XrefDefinitionError(f"{text!r}: expected 'book chapter:verses'")
    return Coord(book, int(chapter), _parse_verses(spec, text))


def format_verses(verses: Iterable[int]) -> str:
    """Sorted runs: [6, 7, 8, 9] → '6-9', [14, 27] → '14,27'."""
    ordered = sorted(set(verses))
    if not ordered:
        raise ValueError("no verses to format")
    runs, start, prev = [], ordered[0], ordered[0]
    for verse in ordered[1:]:
        if verse != prev + 1:
            runs.append((start, prev))
            start = verse
        prev = verse
    runs.append((start, prev))
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def format_coord(coord: Coord) -> str:
    return f"{coord.book} {coord.chapter}:{format_verses(coord.verses)}"


def format_anchor(src: Coord, tgt: Coord) -> str:
    """→ 'rev 18:2-8>jer 51:45'."""
    return f"{format_coord(src)}>{format_coord(tgt)}"


def parse_anchor(text: str) -> tuple[Coord, Coord]:
    src, arrow, tgt = text.partition(">")
    if not arrow or ">" in tgt:
        raise XrefDefinitionError(f"{text!r}: expected 'source>target'")
    return parse_coord(src), parse_coord(tgt)


def resolve_span(coord: Coord, verse_map: VerseMap) -> dict[str, tuple[int, ...]]:
    """{pericope_id: verses}, both in first-seen order; every missing verse is reported."""
    parts: dict[str, list[int]] = {}
    missing = []
    for verse in coord.verses:
        pid = verse_map.get((coord.book, coord.chapter, verse))
        if pid is None:
            missing.append(verse)
        else:
            parts.setdefault(pid, []).append(verse)
    if missing:
        raise XrefDefinitionError(
            f"{format_coord(coord)!r}: verses {format_verses(missing)} are in no pericope")
    return {pid: tuple(verses) for pid, verses in parts.items()}


def _resolve_ends(src_text: str, tgt_text: str,
                  verse_map: VerseMap) -> list[tuple[Coord, dict[str, tuple[int, ...]]]]:
    """Both ends parsed and resolved; the errors of both ends together."""
    ends, errors = [], []
    for text in (src_text, tgt_text):
        try:
            coord = parse_coord(text)
            ends.append((coord, resolve_span(coord, verse_map)))
        except XrefDefinitionError as err:
            errors.extend(err.errors)
    if errors:
        raise XrefDefinitionError(*errors)
    return ends


def build_anchors(src_text: str, tgt_text: str, verse_map: VerseMap, *, ref_type: str,
                  description: str, tsk_exempt: str | None = None) -> list[Anchor]:
    """One Anchor per touched (source pericope, target pericope) pair, source-major."""
    (src, src_parts), (tgt, tgt_parts) = _resolve_ends(src_text, tgt_text, verse_map)
    fanout = len(src_parts) * len(tgt_parts)
    if fanout > MAX_FANOUT:
        raise XrefDefinitionError(
            f"{src_text!r}>{tgt_text!r}: {fanout} pericope pairs (max {MAX_FANOUT}): "
            f"{', '.join(src_parts)} × {', '.join(tgt_parts)}")
    return [
        Anchor(start, end,
               format_anchor(src._replace(verses=src_verses), tgt._replace(verses=tgt_verses)),
               ref_type, description, tsk_exempt)
        for start, src_verses in src_parts.items()
        for end, tgt_verses in tgt_parts.items()
    ]


def resolve_definitions(defs: Iterable, verse_map: VerseMap) -> tuple[list[Anchor], list[str]]:
    """Anchors of every definition (.src, .tgt, .ref_type, .description, .tsk_exempt)
    in definition order, and the complete error list, each prefixed 'definition <i>'."""
    anchors: list[Anchor] = []
    errors: list[str] = []
    for i, d in enumerate(defs):
        try:
            anchors.extend(build_anchors(d.src, d.tgt, verse_map, ref_type=d.ref_type,
                                         description=d.description, tsk_exempt=d.tsk_exempt))
        except XrefDefinitionError as err:
            errors.extend(f"definition {i}: {message}" for message in err.errors)
    return anchors, errors


def verse_map_from_pericopes(records: Iterable[Mapping]) -> dict[tuple[str, int, int], str]:
    """(book, chapter, verse) → pericope_id from output/pericopes.jsonl rows;
    verse numbers like '1-2' are expanded, as in build_verse_map."""
    verse_map: dict[tuple[str, int, int], str] = {}
    for record in records:
        meta = record["metadata"]
        for verse in record["verses"]:
            lo, _, hi = verse["num"].partition("-")
            for n in range(int(lo), int(hi or lo) + 1):
                verse_map[(meta["book_id"], meta["chapter_num"], n)] = record["id"]
    return verse_map
