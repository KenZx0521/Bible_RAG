"""
Query signal detector for smart routing.

Analyzes query text, verse references, intent, and entities to produce the
signals that drive the 6-route decision tree. The words come from the serving
build's routing lexicon (contract routing_lexicon.json; R1 serves the legacy
vocabulary frozen from the old entity_dicts, D-12(a)), matched by
ragcommon.routing exactly as entity_dicts matched them.
"""

import logging
from dataclasses import dataclass, replace
from typing import Mapping

from ragcommon.routing import RoutingLexicon
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuerySignals:
    """Signals detected from a query, and the route they select."""

    has_book_chapter_verse: bool = False     # R1: book + chapter + verse
    has_book_chapter: bool = False           # R2: book + chapter, no verse
    has_multi_book: bool = False             # R5: several book names
    has_multi_person: bool = False           # R3: two or more persons
    has_event_keyword: bool = False          # R4: event keyword
    has_place: bool = False                  # R6: place name
    detected_persons: tuple[str, ...] = ()
    detected_places: tuple[str, ...] = ()
    detected_events: tuple[str, ...] = ()
    detected_book_names: tuple[str, ...] = ()
    detected_book_ids: tuple[str, ...] = ()  # aligned with detected_book_names
    route: str = "fallback"


def _persons(lexicon: RoutingLexicon, query: str, entity_names: list[str]) -> tuple[str, ...]:
    # dictionary hits in the query, then in the LLM's entity names; first-seen order
    found = lexicon.match_persons(query) + [
        p for name in entity_names for p in lexicon.match_persons(name)]
    return tuple(dict.fromkeys(found))


def _events(lexicon: RoutingLexicon, query: str, intent_type: str,
            keywords: list[str] | None) -> tuple[str, ...]:
    found = lexicon.match_events(query)
    for kw in keywords or []:
        found.extend(lexicon.match_events(kw))
    if intent_type == "event" and not found:
        # the LLM thinks it is an event question though no keyword matched
        found = list(keywords or [])
    return tuple(dict.fromkeys(found))


def _places(lexicon: RoutingLexicon, query: str, entity_names: list[str]) -> tuple[str, ...]:
    found = lexicon.match_places(query)
    for name in entity_names:
        found.extend(lexicon.match_places(name))
    return tuple(dict.fromkeys(found))


def detect_signals(query: str, verse_refs: list[VerseRef], intent_type: str,
                   entity_names: list[str], lexicon: RoutingLexicon,
                   book_ids: Mapping[str, str], keywords: list[str] | None = None
                   ) -> QuerySignals:
    """Signals of one query; ``book_ids`` maps the lexicon's full book names to book ids."""
    has_verse = any(ref.verse_start is not None for ref in verse_refs)
    books = tuple(lexicon.match_books(query))
    persons = _persons(lexicon, query, entity_names)
    events = _events(lexicon, query, intent_type, keywords)
    places = _places(lexicon, query, entity_names)
    signals = QuerySignals(
        has_book_chapter_verse=has_verse, has_book_chapter=bool(verse_refs) and not has_verse,
        has_multi_book=len(books) >= 2, has_multi_person=len(persons) >= 2,
        has_event_keyword=bool(events), has_place=bool(places),
        detected_persons=persons, detected_places=places, detected_events=events,
        detected_book_names=books, detected_book_ids=tuple(book_ids[b] for b in books))
    route = select_route(signals, intent_type)
    logger.info("Signal detector: route=%s, signals=[verse=%s, chapter=%s, multi_book=%s, "
                "multi_person=%s, event=%s, place=%s]", route, signals.has_book_chapter_verse,
                signals.has_book_chapter, signals.has_multi_book, signals.has_multi_person,
                signals.has_event_keyword, signals.has_place)
    return replace(signals, route=route)


def select_route(signals: QuerySignals, intent_type: str = "") -> str:
    """Decision tree: R1 > R5(multi-book+chapter) > R2 > R5 > R3 > R4 > R6 > fallback.

    A chapter reference in a multi-book question (「哥林多前書15章如何回應創世記…」)
    goes to R5, whose cross-book handling R2 would skip.
    """
    if signals.has_book_chapter_verse:
        return "R1"
    if signals.has_book_chapter and signals.has_multi_book:
        return "R5"
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
