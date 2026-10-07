"""S2b: name spans from the PDF's proper-name underlines (design §2.11, G05, G07, G08).

The PDF draws every proper name with a horizontal 0.3985 pt stroke 1.9–2.6 pt
below the baseline of its glyphs. Each stroke becomes exactly one of:

- a name span: the glyphs right above it are consecutive characters of one verse
  (``body``) or one footnote (``footnote``) — one record per stroke, nothing merged;
- a rule: nothing is printed above it and a footnote or colophon row starts just
  below it (the footnote separators and the colophon rule).

A stroke that is neither — under a heading, across two verses, over a gap, or
overlapping another — is a ParseError, so a drawn name is never dropped silently
and a stray stroke never becomes one. Known misdrawn spans (代下1:17 舍客勒) are kept
here and declared by ``underline_fixes`` in the kg0 layer.

``with_merge_groups`` links the four names the PDF underlines apart from their
generic noun (鹽＋海, 毗珥＋山, 何烈＋山, 加利利＋海, G07) into merge groups.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.layout import Glyph, Row
from ragdata.stages.s01_extract import S1Book, Stroke

PDF = "pdf_deterministic"
BAND_PT = 5.0           # a glyph above a stroke has its baseline less than 5 pt above it
X_SLACK_PT = 1.0        # a glyph is under-lined when its centre lies within the stroke
RULE_GAP_PT = 15.0      # rules lie 9–12 pt above the first footnote or colophon row
GENERIC_NOUNS = frozenset({"山", "海"})
RULE_ROWS = frozenset({layout.NOTE_START, layout.NOTE_CONT, layout.COLOPHON})
Container = tuple[str, str, Sequence[Glyph]]  # (container id, region, glyphs of its text)


@dataclass(frozen=True)
class _Spot:
    container: str
    region: str
    offset: int


class _Page:
    """Non-space glyphs of one page by baseline, and the rows a rule may stand above."""

    def __init__(self, rows: Sequence[Row]):
        glyphs = sorted((g for r in rows for g in r.glyphs if not g.c.isspace()),
                        key=lambda g: (g.y, g.seq))
        self.glyphs, self.ys = glyphs, [g.y for g in glyphs]
        self.rule_rows = [r.y for r in rows if layout.classify(r) in RULE_ROWS]

    def above(self, x0: float, x1: float, y: float) -> list[Glyph]:
        lo, hi = bisect.bisect_right(self.ys, y - BAND_PT), bisect.bisect_left(self.ys, y)
        return [g for g in self.glyphs[lo:hi]
                if x0 - X_SLACK_PT < (g.x0 + g.x1) / 2 < x1 + X_SLACK_PT]

    def is_rule(self, y: float) -> bool:
        return any(0 < row_y - y <= RULE_GAP_PT for row_y in self.rule_rows)


def _segment(stroke: Stroke, where: str) -> tuple[float, float, float]:
    path = stroke.path
    if [op[0] for op in path] != ["m", "l"] or path[0][2] != path[1][2]:
        raise ParseError(f"{where} p{stroke.page}: stroke {path} is not one horizontal segment")
    x0, x1 = sorted((path[0][1], path[1][1]))
    return x0, x1, path[0][2]


def _span(spots: Sequence[_Spot], texts: Mapping[str, str], where: str) -> dict[str, Any]:
    containers = {s.container for s in spots}
    offsets = sorted(s.offset for s in spots)
    if len(containers) > 1 or offsets != list(range(offsets[0], offsets[-1] + 1)):
        raise ParseError(f"{where}: underline spans more than one record or skips characters "
                         f"({sorted(containers)}, offsets {offsets})")
    spot = spots[0]
    surface = texts[spot.container][offsets[0]:offsets[-1] + 1]
    return {"span_id": ids.name_span_id(spot.container, offsets[0]),
            "container_id": spot.container, "region": spot.region, "start": offsets[0],
            "end": offsets[-1] + 1, "surface": surface, "source": "pdf_underline",
            "norm_key": surface, "norm_rule_ids": [], "merge_group": None,
            "provenance_class": PDF}


def _stroke_span(stroke: Stroke, page: _Page, spots: Mapping[int, _Spot],
                 texts: Mapping[str, str], where: str) -> dict[str, Any] | None:
    x0, x1, y = _segment(stroke, where)
    glyphs = page.above(x0, x1, y)
    at = f"{where} p{stroke.page} ({x0}–{x1}, {y})"
    if not glyphs:
        if page.is_rule(y):
            return None
        raise ParseError(f"{at}: underline with no text above and no footnote or colophon below")
    missing = [g.c for g in glyphs if g.seq not in spots]
    if missing:
        raise ParseError(f"{at}: underline under {''.join(missing)!r}, which is neither verse "
                         "nor footnote text")
    return _span([spots[g.seq] for g in glyphs], texts, at)


def _check_overlaps(spans: Sequence[Mapping[str, Any]], where: str) -> None:
    for a, b in zip(spans, spans[1:]):
        if a["container_id"] == b["container_id"] and b["start"] < a["end"]:
            raise ParseError(f"{where}: underlines {a['span_id']} and {b['span_id']} overlap")


def name_spans(book: S1Book, rows: Sequence[Row], containers: Sequence[Container],
               where: str) -> tuple[dict[str, Any], ...]:
    """One span per name stroke of ``book``, in container order then by start."""
    spots = {g.seq: _Spot(cid, region, i) for cid, region, glyphs in containers
             for i, g in enumerate(glyphs)}
    texts = {cid: "".join(g.c for g in glyphs) for cid, _, glyphs in containers}
    order = {cid: i for i, (cid, _, _) in enumerate(containers)}
    by_page: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        by_page[row.page].append(row)
    pages = {p: _Page(page_rows) for p, page_rows in by_page.items()}
    empty = _Page(())
    found = [_stroke_span(s, pages.get(s.page, empty), spots, texts, where) for s in book.strokes]
    spans = sorted((s for s in found if s is not None),
                   key=lambda s: (order[s["container_id"]], s["start"]))
    _check_overlaps(spans, where)
    return tuple(spans)


def with_merge_groups(spans: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Link each name to the generic noun underlined right after it (corpus-wide numbering)."""
    groups: dict[int, str] = {}
    counts: dict[str, int] = defaultdict(int)
    for i, (a, b) in enumerate(zip(spans, spans[1:])):
        if a["container_id"] == b["container_id"] and a["end"] == b["start"] \
                and b["surface"] in GENERIC_NOUNS:
            merged = a["surface"] + b["surface"]
            counts[merged] += 1
            groups[i] = groups[i + 1] = ids.merge_group_id(merged, counts[merged])
    return tuple({**span, "merge_group": groups.get(i)} for i, span in enumerate(spans))
