"""
Query signal detector for smart routing.

Analyzes query text, verse references, intent, and entities
to produce boolean signals that drive the 6-route decision tree.
"""

import logging
from dataclasses import dataclass, field

from utils.verse_parser import VerseRef
from utils.entity_dicts import (
    match_persons_in_text,
    match_places_in_text,
    match_events_in_text,
    count_books_in_text,
)

logger = logging.getLogger(__name__)


@dataclass
class QuerySignals:
    """Boolean signals detected from a query."""

    # R1: exact verse reference (book + chapter + verse)
    has_book_chapter_verse: bool = False
    # R2: chapter-only reference (book + chapter, no verse)
    has_book_chapter: bool = False
    # R5: multiple book names mentioned
    has_multi_book: bool = False
    # R3: two or more person entities
    has_multi_person: bool = False
    # R4: event keyword detected
    has_event_keyword: bool = False
    # R6: place name detected
    has_place: bool = False

    # Detected entities for downstream retrieval
    detected_persons: list[str] = field(default_factory=list)
    detected_places: list[str] = field(default_factory=list)
    detected_events: list[str] = field(default_factory=list)

    # Selected route
    route: str = "fallback"


def detect_signals(
    query: str,
    verse_refs: list[VerseRef],
    intent_type: str,
    entity_names: list[str],
    keywords: list[str] | None = None,
) -> QuerySignals:
    """Analyze query and metadata to produce routing signals.

    Args:
        query: The raw user query text.
        verse_refs: Parsed verse references from verse_parser.
        intent_type: LLM-classified intent type.
        entity_names: Entity names from LLM classification.
        keywords: Keywords from LLM classification.

    Returns:
        QuerySignals with all boolean flags and detected entities set.
    """
    signals = QuerySignals()

    # --- Verse reference signals ---
    if verse_refs:
        has_verse = any(ref.verse_start is not None for ref in verse_refs)
        if has_verse:
            signals.has_book_chapter_verse = True
        else:
            signals.has_book_chapter = True

    # --- Multi-book signal ---
    book_count = count_books_in_text(query)
    if book_count >= 2:
        signals.has_multi_book = True

    # --- Person signal ---
    # Combine LLM entities with dictionary matching
    dict_persons = match_persons_in_text(query)
    all_persons: set[str] = set(dict_persons)
    # Also check LLM entity names against person dict
    for name in entity_names:
        extra = match_persons_in_text(name)
        all_persons.update(extra)

    signals.detected_persons = list(all_persons)
    if len(all_persons) >= 2:
        signals.has_multi_person = True

    # --- Event signal ---
    dict_events = match_events_in_text(query)
    if keywords:
        for kw in keywords:
            dict_events.extend(match_events_in_text(kw))
    # Also check intent type
    if intent_type == "event" and not dict_events:
        # LLM thinks it's an event query even without keyword match
        dict_events = keywords or []
    signals.detected_events = list(set(dict_events))
    if signals.detected_events:
        signals.has_event_keyword = True

    # --- Place signal ---
    dict_places = match_places_in_text(query)
    for name in entity_names:
        dict_places.extend(match_places_in_text(name))
    signals.detected_places = list(set(dict_places))
    if signals.detected_places:
        signals.has_place = True

    # --- Select route ---
    signals.route = select_route(signals, intent_type)

    logger.info(
        f"Signal detector: route={signals.route}, "
        f"signals=[verse={signals.has_book_chapter_verse}, "
        f"chapter={signals.has_book_chapter}, "
        f"multi_book={signals.has_multi_book}, "
        f"multi_person={signals.has_multi_person}, "
        f"event={signals.has_event_keyword}, "
        f"place={signals.has_place}]"
    )

    return signals


def select_route(signals: QuerySignals, intent_type: str = "") -> str:
    """Decision tree: select the best route based on signals.

    Priority order: R1 > R2 > R5 > R3 > R4 > R6 > fallback
    """
    if signals.has_book_chapter_verse:
        return "R1"
    if signals.has_book_chapter:
        return "R2"
    if signals.has_multi_book or intent_type == "cross_reference":
        return "R5"
    if signals.has_multi_person:
        return "R3"
    if signals.has_event_keyword:
        return "R4"
    if signals.has_place:
        return "R6"
    return "fallback"
