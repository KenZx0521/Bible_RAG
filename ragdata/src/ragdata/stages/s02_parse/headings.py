"""S2b: heading, parallel-reference and speaker records of one book (design §2.7, §2.8, §2.10).

From the placed navy rows (``navy.place_navy``):

- headings are numbered per start key: ``hd:{slot}#n`` before a verse, ``hd:{slot}b#n``
  inside one; two headings at one key are a stack (the 6 stacked headings);
- a reference line belongs to the heading right above it (one line per heading);
- level: the PDF sets every heading in the same typeface, so the level comes from the
  structure the page prints: a heading is level 1 when it heads a section — its
  reference line is a ``section_range`` or another heading stacks under it — else 2;
- parent: a － subheading hangs under the nearest heading before it that is not one
  (its ``display_title`` completes that title: 上帝審判以色列的鄰國－亞蘭, 埃及遭災－蛙災);
  a heading stacked under another hangs under it; any other heading inside a section
  range hangs under that section heading;
- speakers are numbered per unit (``sk:{unit}#n``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import parallels
from ragdata.stages.s02_parse.navy import HEADING, PARALLEL, SPEAKER, STYLE_CLASS, Placed

PDF = "pdf_deterministic"
DASH = "－"


@dataclass(frozen=True)
class NavyRecords:
    headings: tuple[dict[str, Any], ...]
    parallel_refs: tuple[dict[str, Any], ...]
    speakers: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _Draft:
    heading_id: str
    start_key: str
    anchor_slot: str
    placed: Placed
    reference: str | None = None

    @property
    def text(self) -> str:
        return self.placed.line.text


def _keys(placed: Placed) -> tuple[str, str]:
    unit = ids.parse(placed.unit_key)
    return (ids.verse_key(unit.book_id, unit.chapter, unit.verse, half=placed.pos == "mid"),
            ids.slot_key(unit.book_id, unit.chapter, unit.verse))


def _drafts(placed: Sequence[Placed], where: str) -> list[_Draft]:
    drafts: list[_Draft] = []
    counts: dict[str, int] = {}
    last_kind = None
    for item in placed:
        kind = item.line.kind
        if kind == HEADING:
            start, slot = _keys(item)
            counts[start] = counts.get(start, 0) + 1
            drafts.append(_Draft(ids.heading_id(start, counts[start]), start, slot, item))
        elif kind == PARALLEL:
            if last_kind != HEADING:
                raise ParseError(f"{where} p{item.line.page}: reference line {item.line.text!r} "
                                 "has no heading right above it")
            if drafts[-1].reference is not None:
                raise ParseError(f"{where} p{item.line.page}: {drafts[-1].heading_id} has a "
                                 f"second reference line {item.line.text!r}")
            drafts[-1] = replace(drafts[-1], reference=item.line.text)
        last_kind = kind if kind != PARALLEL else last_kind
    return drafts


def _sections(refs: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    """Section heading id -> the slot range its section_range covers."""
    return {r["heading_id"]: (r["targets"][0]["start_slot"], r["targets"][-1]["end_slot"])
            for r in refs if r["kind"] == "section_range"}


def _order(slot: str) -> tuple[int, int]:
    p = ids.parse(slot)
    return (p.chapter, p.verse)


def _parent(i: int, drafts: Sequence[_Draft], sections: Mapping[str, tuple[str, str]],
            where: str) -> str | None:
    draft = drafts[i]
    if draft.text.startswith(DASH):
        for earlier in reversed(drafts[:i]):
            if not earlier.text.startswith(DASH):
                return earlier.heading_id
        raise ParseError(f"{where}: subheading {draft.text!r} has no heading before it")
    if i > 0 and drafts[i - 1].start_key == draft.start_key:
        return drafts[i - 1].heading_id
    for earlier in reversed(drafts[:i]):
        span = sections.get(earlier.heading_id)
        if span is not None and _order(span[0]) <= _order(draft.anchor_slot) <= _order(span[1]):
            return earlier.heading_id
    return None


def _display(text: str, parent: _Draft | None) -> str:
    if parent is None or not text.startswith(DASH):
        return text
    return parent.text.split(DASH)[0] + text


def _heading_row(i: int, drafts: Sequence[_Draft], sections: Mapping[str, tuple[str, str]],
                 parent: _Draft | None, ord_: int) -> dict[str, Any]:
    draft = drafts[i]
    stacked = i + 1 < len(drafts) and drafts[i + 1].start_key == draft.start_key
    glyphs = draft.placed.line.glyphs
    return {
        "heading_id": draft.heading_id, "book_id": ids.parse(draft.anchor_slot).book_id,
        "anchor_unit_key": draft.placed.unit_key, "anchor_offset": draft.placed.offset,
        "pos": draft.placed.pos, "level": 1 if stacked or draft.heading_id in sections else 2,
        "parent_heading_id": parent.heading_id if parent else None, "text_pdf": draft.text,
        "text": draft.text, "display_title": _display(draft.text, parent), "ord": ord_,
        "prov": {"style_class": STYLE_CLASS, "glyph_range": [glyphs[0].seq, glyphs[-1].seq]},
        "provenance_class": PDF,
    }


def _speaker_rows(placed: Sequence[Placed]) -> tuple[dict[str, Any], ...]:
    rows, counts = [], {}
    for item in placed:
        if item.line.kind != SPEAKER:
            continue
        counts[item.unit_key] = counts.get(item.unit_key, 0) + 1
        text = item.line.text
        rows.append({"sk_id": ids.speaker_id(item.unit_key, counts[item.unit_key]),
                     "unit_key": item.unit_key, "offset": item.offset, "pos": item.pos,
                     "text_pdf": text, "text": text, "provenance_class": PDF})
    return tuple(rows)


def navy_records(book_id: str, placed: Sequence[Placed], ord_start: int) -> NavyRecords:
    """Records of one book's navy rows; heading ``ord`` continues from ``ord_start``."""
    drafts = _drafts(placed, book_id)
    refs = tuple(row for d in drafts if d.reference is not None
                 for row in parallels.parse_line(d.heading_id, d.reference, book_id,
                                                 d.anchor_slot))
    sections = _sections(refs)
    by_id = {d.heading_id: d for d in drafts}
    parents = [by_id.get(_parent(i, drafts, sections, book_id)) for i in range(len(drafts))]
    rows = tuple(_heading_row(i, drafts, sections, parents[i], ord_start + i)
                 for i in range(len(drafts)))
    return NavyRecords(rows, refs, _speaker_rows(placed))
