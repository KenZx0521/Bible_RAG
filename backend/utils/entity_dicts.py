"""
Entity dictionary bridge module for signal-based routing.

Provides flattened name sets and substring matching functions
for Person, Place, and Event detection in Chinese queries.
"""

import sys
from pathlib import Path

# Add project root so we can import entity_dict
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.entity_extraction.entity_dict import (
    PERSON_DICT,
    PLACE_DICT,
    GROUP_DICT,
)

# Biblical event keywords (~50 terms from Neo4j Event canonical names)
EVENT_KEYWORDS: set[str] = {
    # 創世記
    "創造", "墮落", "洪水", "巴別塔", "亞伯拉罕之約",
    # 出埃及記
    "出埃及", "十災", "過紅海", "頒布律法", "金牛犢",
    "逾越節", "嗎哪", "十誡",
    # 曠野 / 征服
    "曠野漂流", "探子窺地", "過約旦河", "耶利哥城", "征服迦南",
    # 士師 / 王國
    "士師時期", "掃羅受膏", "大衛受膏", "大衛與歌利亞",
    "建造聖殿", "所羅門獻殿", "王國分裂",
    # 被擄 / 歸回
    "被擄", "巴比倫之囚", "歸回", "重建聖殿", "重建城牆",
    # 新約 - 耶穌生平
    "道成肉身", "耶穌降生", "受洗", "受試探", "登山寶訓", "山上寶訓",
    "八福", "五餅二魚", "變像", "最後的晚餐", "客西馬尼園禱告",
    "客西馬尼禱告",
    "受難週", "釘十字架", "復活", "升天", "大使命",
    # 新約 - 教會
    "五旬節", "聖靈降臨", "司提反殉道", "保羅歸主",
    "第一次宣教旅程", "耶路撒冷大會",
    # 末世
    "末日審判", "新天新地",
}

# Pre-compute flattened name sets (all aliases)
_ALL_PERSON_NAMES: set[str] = set()
for _aliases in PERSON_DICT.values():
    _ALL_PERSON_NAMES.update(_aliases)

_ALL_PLACE_NAMES: set[str] = set()
for _aliases in PLACE_DICT.values():
    _ALL_PLACE_NAMES.update(_aliases)

# Book names for multi-book detection (reuse verse_parser's list)
from utils.verse_parser import _ALL_NAMES as _BOOK_NAMES  # noqa: E402


def match_persons_in_text(text: str) -> list[str]:
    """Find person names mentioned in text via substring matching.

    Returns canonical names, matched longest-first to avoid partial matches.
    """
    matched: list[str] = []
    # Sort by name length descending to match longer names first
    for canonical, aliases in sorted(
        PERSON_DICT.items(), key=lambda x: max(len(a) for a in x[1]), reverse=True
    ):
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text:
                matched.append(canonical)
                break
    return matched


def match_places_in_text(text: str) -> list[str]:
    """Find place names mentioned in text via substring matching.

    Returns canonical names, matched longest-first.
    """
    matched: list[str] = []
    for canonical, aliases in sorted(
        PLACE_DICT.items(), key=lambda x: max(len(a) for a in x[1]), reverse=True
    ):
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text:
                matched.append(canonical)
                break
    return matched


def match_events_in_text(text: str) -> list[str]:
    """Find event keywords mentioned in text via substring matching.

    Returns matched keywords, longest-first.
    """
    matched: list[str] = []
    for kw in sorted(EVENT_KEYWORDS, key=len, reverse=True):
        if kw in text:
            matched.append(kw)
    return matched


def count_books_in_text(text: str) -> int:
    """Count distinct Bible book names mentioned in text.

    Only considers book names with ≥2 characters to avoid
    false positives from single-character abbreviations.
    """
    return len(match_books_in_text(text))


def match_books_in_text(text: str) -> list[str]:
    """Return canonical Chinese names of Bible books mentioned in text.

    Returns full names (e.g. '撒迦利亞書', '馬太福音'), not abbreviations.
    Only considers ≥2-char tokens to avoid single-char false positives
    (利, 伯, 拉 etc.). Order follows first appearance in text.
    """
    from utils.verse_parser import _resolve_book

    seen_ids: set[str] = set()
    book_names: list[str] = []
    for name in sorted(_BOOK_NAMES, key=len, reverse=True):
        if len(name) < 2:
            continue
        if name in text:
            resolved = _resolve_book(name)
            if not resolved:
                continue
            book_id, full_name = resolved
            if book_id in seen_ids:
                continue
            seen_ids.add(book_id)
            book_names.append(full_name)
    return book_names
