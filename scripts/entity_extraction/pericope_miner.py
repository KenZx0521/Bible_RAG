"""
Phase 1: Pericope Title Mining.

Extracts Event/Object/Theme candidates from ### pericope titles.
Filters out pure person/place/group names using entity_dict.
"""

import logging
from collections import defaultdict
from typing import List, Set

from .models import EntityCandidate, EntityType
from .bible_md_parser import PericopeData
from .entity_dict import (
    PERSON_DICT,
    PLACE_DICT,
    GROUP_DICT,
)

logger = logging.getLogger(__name__)

# Build flat name sets for filtering
_ALL_PERSON_NAMES: Set[str] = set()
for _aliases in PERSON_DICT.values():
    _ALL_PERSON_NAMES.update(_aliases)
_ALL_PERSON_NAMES.update(PERSON_DICT.keys())

_ALL_PLACE_NAMES: Set[str] = set()
for _aliases in PLACE_DICT.values():
    _ALL_PLACE_NAMES.update(_aliases)
_ALL_PLACE_NAMES.update(PLACE_DICT.keys())

_ALL_GROUP_NAMES: Set[str] = set()
for _aliases in GROUP_DICT.values():
    _ALL_GROUP_NAMES.update(_aliases)
_ALL_GROUP_NAMES.update(GROUP_DICT.keys())

_ALL_KNOWN_NAMES = _ALL_PERSON_NAMES | _ALL_PLACE_NAMES | _ALL_GROUP_NAMES

# Suffixes suggesting Object type
OBJECT_SUFFIXES = (
    "壇", "器", "衣", "冠", "殿", "櫃", "幕", "杖", "碗", "燈",
    "餅", "袍", "印", "角", "瓶", "盆", "桌", "座", "柱", "爐",
    "門", "幔", "鉤", "環", "板", "栓", "架", "帳", "鐘", "鏟",
)

# Keywords suggesting Theme type
THEME_KEYWORDS = {
    "救贖", "恩典", "信心", "公義", "審判", "聖潔", "盼望", "愛",
    "慈愛", "憐憫", "悔改", "饒恕", "智慧", "律法", "誡命", "約",
    "應許", "祝福", "咒詛", "順服", "敬拜", "禱告", "讚美", "感恩",
    "復興", "潔淨", "稱義", "成聖", "忍耐", "謙卑", "誠實", "正直",
    "義人", "罪", "罪惡", "赦免", "救恩", "永生", "天國", "福音",
}


def _is_pure_name(title: str) -> bool:
    """Check if title is purely a known person/place/group name."""
    return title in _ALL_KNOWN_NAMES


def _classify_title(title: str) -> EntityType | None:
    """Rule-based classification of a pericope title."""
    # Check for object suffixes
    for suffix in OBJECT_SUFFIXES:
        if title.endswith(suffix):
            return EntityType.OBJECT

    # Check for theme keywords
    for kw in THEME_KEYWORDS:
        if kw in title:
            return EntityType.THEME

    # Default: Event (pericope titles typically describe events)
    return EntityType.EVENT


def mine_pericope_titles(pericopes: List[PericopeData]) -> List[EntityCandidate]:
    """
    Phase 1: Extract entity candidates from pericope titles.

    Filters out pure person/place/group titles, classifies remaining
    as Event/Object/Theme candidates.
    """
    # Group titles across all pericopes for dedup
    title_sources: dict[str, list[str]] = defaultdict(list)
    title_texts: dict[str, list[str]] = defaultdict(list)

    for p in pericopes:
        title = p.title.strip()
        if not title:
            continue
        # Skip very short titles (single char)
        if len(title) <= 1:
            continue
        # Skip pure person/place/group names
        if _is_pure_name(title):
            continue
        title_sources[title].append(p.source_id)
        # Store first sentence of full_text as grounding
        if p.full_text:
            title_texts[title].append(p.full_text[:200])

    candidates: List[EntityCandidate] = []
    for title, source_ids in title_sources.items():
        proposed_type = _classify_title(title)
        grounding = title_texts[title][0] if title_texts[title] else ""

        candidates.append(EntityCandidate(
            name=title,
            proposed_type=proposed_type,
            source_ids=source_ids,
            grounding_text=grounding,
            confidence=0.5,
            extraction_phase=1,
            frequency=len(source_ids),
        ))

    logger.info(
        f"Phase 1: mined {len(candidates)} candidates from "
        f"{len(pericopes)} pericope titles"
    )
    return candidates
