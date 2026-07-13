"""
Verse-level retrieval coverage — the honest replacement for unit-level recall.

Unit-level recall (relevance_judge.estimate_total_relevant) counts an entire
chapter range ("馬太福音 5-7章" = 111 verses) as ONE relevant unit, so hitting
any single verse scores recall=1.0. On the 2026-07-12 500-question run that
inflated hit_rate to 0.944 while true verse coverage was 0.75.

This module expands both ground-truth references and retrieved sources into
explicit verse sets, using the corpus chapter table (output/chapters.jsonl)
for per-chapter verse counts:

  verse_recall_at_k    |retrieved verses ∩ gold verses| / |gold verses|
  anchor_coverage_at_k covered chapter-anchors / total chapter-anchors.
                       A chapter range expands to one anchor per chapter, so a
                       multi-anchor question must hit EVERY chapter to score
                       1.0 — not just any one verse anywhere in the range.

Both are deterministic (no LLM). Verse numbers are treated as 1..total_verses
per chapter; out-of-range verse specs are clamped to the chapter size on both
the gold and retrieved side, so the comparison stays consistent.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .models import ParsedReference, SourceInfo
from .relevance_judge import _chinese_name_to_book_id

_CHAPTERS_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "chapters.jsonl"

# (book_id, chapter, verse)
Verse = tuple[str, int, int]
# (book_id, chapter, verse_start|None, verse_end|None, to_chapter_end)
Anchor = tuple[str, int, int | None, int | None, bool]

_VR_RANGE = re.compile(r"^(\d+)\s*[-–~]\s*(\d+)$")
_VR_SINGLE = re.compile(r"^(\d+)$")


@lru_cache(maxsize=1)
def _chapter_table() -> dict[str, dict[int, int]]:
    """book_id → {chapter_num: total_verses}, loaded from the corpus chapter table."""
    table: dict[str, dict[int, int]] = {}
    with open(_CHAPTERS_PATH, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            book_id = rec["metadata"]["book_id"]
            table.setdefault(book_id, {})[rec["chapter_num"]] = rec["total_verses"]
    return table


def _chapter_verses(book_id: str, chapter: int) -> set[Verse]:
    total = _chapter_table().get(book_id, {}).get(chapter)
    if not total:
        return set()
    return {(book_id, chapter, v) for v in range(1, total + 1)}


def _range_verses(
    book_id: str, chapter: int,
    verse_start: int, verse_end: int | None,
    to_chapter_end: bool,
) -> set[Verse]:
    total = _chapter_table().get(book_id, {}).get(chapter)
    if not total:
        return set()
    start = max(1, verse_start)
    if to_chapter_end or verse_end is None:
        end = total
    else:
        end = min(verse_end, total)
    if start > end:
        return set()
    return {(book_id, chapter, v) for v in range(start, end + 1)}


def expand_refs_to_verses(refs: list[ParsedReference]) -> set[Verse]:
    """Expand parsed GT references into the full set of gold verses."""
    verses: set[Verse] = set()
    for ref in refs:
        book_chapters = _chapter_table().get(ref.book_id, {})
        if not book_chapters:
            continue  # book not in corpus table — cannot expand
        if ref.is_whole_book:
            for ch in book_chapters:
                verses |= _chapter_verses(ref.book_id, ch)
            continue
        if ref.verse_start is None:
            for ch in ref.chapters:
                verses |= _chapter_verses(ref.book_id, ch)
            continue
        if not ref.chapters:
            continue
        verses |= _range_verses(
            ref.book_id, ref.chapters[0],
            ref.verse_start, ref.verse_end, ref.to_chapter_end,
        )
    return verses


def expand_refs_to_anchors(refs: list[ParsedReference]) -> list[Anchor]:
    """Expand parsed GT references into chapter-level anchors (deduplicated).

    "創世記 6-9章" → 4 anchors (one per chapter); "約翰福音 3:16" → 1
    verse-range anchor. A multi-anchor question needs every anchor hit.
    """
    anchors: list[Anchor] = []
    for ref in refs:
        book_chapters = _chapter_table().get(ref.book_id, {})
        if ref.is_whole_book:
            anchors.extend((ref.book_id, ch, None, None, False) for ch in sorted(book_chapters))
            continue
        if ref.verse_start is None:
            anchors.extend((ref.book_id, ch, None, None, False) for ch in ref.chapters)
            continue
        if ref.chapters:
            anchors.append(
                (ref.book_id, ref.chapters[0], ref.verse_start, ref.verse_end, ref.to_chapter_end)
            )
    seen: set[Anchor] = set()
    out: list[Anchor] = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _anchor_verses(anchor: Anchor) -> set[Verse]:
    book_id, chapter, verse_start, verse_end, to_chapter_end = anchor
    if verse_start is None:
        return _chapter_verses(book_id, chapter)
    return _range_verses(book_id, chapter, verse_start, verse_end, to_chapter_end)


def expand_source_to_verses(source: SourceInfo) -> set[Verse]:
    """Expand one retrieved source into the set of verses it actually contains."""
    book_id = _chinese_name_to_book_id(source.book)
    if book_id is None or source.chapter is None:
        return set()
    vr = (source.verse_range or "").strip()
    if not vr:
        # Chapter-level source (e.g. SQL chapter route) — covers the whole chapter.
        return _chapter_verses(book_id, source.chapter)
    m = _VR_RANGE.match(vr)
    if m:
        return _range_verses(book_id, source.chapter, int(m.group(1)), int(m.group(2)), False)
    m = _VR_SINGLE.match(vr)
    if m:
        v = int(m.group(1))
        return _range_verses(book_id, source.chapter, v, v, False)
    # Unparseable verse_range but book+chapter known — fall back to the chapter.
    return _chapter_verses(book_id, source.chapter)


def verse_level_metrics(
    gt_refs: list[ParsedReference],
    sources: list[SourceInfo],
) -> tuple[float, float]:
    """Compute (verse_recall, anchor_coverage) for one sample's top-k sources."""
    gold = expand_refs_to_verses(gt_refs)
    anchors = expand_refs_to_anchors(gt_refs)

    retrieved: set[Verse] = set()
    for s in sources:
        retrieved |= expand_source_to_verses(s)

    verse_recall = len(gold & retrieved) / len(gold) if gold else 0.0
    covered = sum(1 for a in anchors if _anchor_verses(a) & retrieved)
    anchor_coverage = covered / len(anchors) if anchors else 0.0
    return round(verse_recall, 4), round(anchor_coverage, 4)
