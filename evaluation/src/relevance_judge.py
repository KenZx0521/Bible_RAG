"""
Judge relevance between RAG retrieval sources and ground truth references.

Provides binary relevance (for Precision/Recall/MRR) and graded relevance (for NDCG).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .models import ParsedReference, SourceInfo
from .reference_parser import parse_reference

# Import BOOK_CONFIG
_BIBLE_CHUNKING = Path(__file__).resolve().parent.parent.parent / "bible_chunking"
if str(_BIBLE_CHUNKING) not in sys.path:
    sys.path.insert(0, str(_BIBLE_CHUNKING))

from config import BOOK_CONFIG  # type: ignore

_BOOK_ALIASES: dict[str, str] = {
    "尼希米記": "尼西米記",
}


def _chinese_name_to_book_id(chinese_name: str) -> str | None:
    """Convert Chinese book name to book_id."""
    normalized = _BOOK_ALIASES.get(chinese_name, chinese_name)
    cfg = BOOK_CONFIG.get(normalized)
    return cfg["id"] if cfg else None


def _parse_verse_range(vr: str) -> tuple[int | None, int | None]:
    """Parse verse_range string like '1-3' or '16' into (start, end)."""
    if not vr:
        return None, None
    vr = vr.strip()
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", vr)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d+)", vr)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


def _ranges_overlap(s1: int | None, e1: int | None, s2: int | None, e2: int | None) -> bool:
    """Check if two verse ranges overlap. None means 'entire chapter'."""
    if s1 is None or s2 is None:
        return True  # if either is whole chapter, overlap
    return s1 <= (e2 or s2) and s2 <= (e1 or s1)


def binary_relevance(source: SourceInfo, gt_refs: list[ParsedReference]) -> bool:
    """
    Return True if the source is relevant to any of the ground truth references.

    Relevant = same book + same chapter + verse range overlap.
    """
    src_book_id = _chinese_name_to_book_id(source.book)
    if src_book_id is None:
        return False

    src_chapter = source.chapter
    src_vs, src_ve = _parse_verse_range(source.verse_range)

    for ref in gt_refs:
        if ref.book_id != src_book_id:
            continue

        if ref.is_whole_book:
            return True

        if src_chapter is None:
            # Source has no chapter info, but book matches — generous match
            return True

        if src_chapter not in ref.chapters:
            continue

        # Chapter matches; check verses
        if ref.verse_start is None:
            # Ref is whole chapter(s), source is in that chapter
            return True

        # to_chapter_end → range is [verse_start, end of chapter]
        ref_ve = 10**6 if ref.to_chapter_end else ref.verse_end
        if _ranges_overlap(src_vs, src_ve, ref.verse_start, ref_ve):
            return True

    return False


def graded_relevance(source: SourceInfo, gt_refs: list[ParsedReference]) -> int:
    """
    Return graded relevance score:
      0 = irrelevant
      1 = same book, chapter in range (loose)
      2 = same book + same chapter
      3 = same book + same chapter + verse overlap (exact)
    """
    src_book_id = _chinese_name_to_book_id(source.book)
    if src_book_id is None:
        return 0

    src_chapter = source.chapter
    src_vs, src_ve = _parse_verse_range(source.verse_range)

    best = 0

    for ref in gt_refs:
        if ref.book_id != src_book_id:
            continue

        if ref.is_whole_book:
            best = max(best, 2)
            continue

        if src_chapter is None:
            best = max(best, 1)
            continue

        if src_chapter not in ref.chapters:
            continue

        # Chapter matches
        if ref.verse_start is None:
            best = max(best, 2)
            continue

        ref_ve = 10**6 if ref.to_chapter_end else ref.verse_end
        if _ranges_overlap(src_vs, src_ve, ref.verse_start, ref_ve):
            best = max(best, 3)
        else:
            best = max(best, 2)

    return best


def estimate_total_relevant(gt_refs: list[ParsedReference]) -> int:
    """
    Estimate the total number of relevant retrievable units for recall calculation.

    Heuristic: each ParsedReference unit counts as 1 (a pericope typically maps 1:1).

    ⚠️ 量尺缺陷(2026-07-13 確認):章範圍(如「馬太福音 5-7章」111 節)也只算
    1 個 unit,命中任一節即 recall=1.0 → hit_rate/recall_at_k 系統性灌水
    (官方 0.944 vs 經節級真實覆蓋 0.75)。本函式僅為與歷史 run 可比而保留;
    讀數請以 verse_coverage.py 的 verse_recall_at_k / anchor_coverage_at_k 為準。
    """
    if not gt_refs:
        return 1
    return max(len(gt_refs), 1)
