"""
Query signal detector for smart routing.

Analyzes query text, verse references, intent, and entities to produce the
signals that drive the 6-route decision tree. The words come from the serving
build's routing lexicon (contract routing_lexicon.json v2), matched by
ragcommon.routing's one matcher: book names masked, non-overlapping and longest
first, routable terms only, every hit carrying all of its targets.

Persons and places are counted by distinct target (ref): a target counts as a
person when "Person" is among its route types and as a place when "Place" is;
K4 resolved the route types, so the backend applies no type rule of its own. The
question and the LLM's entity names feed persons and places; the question and the
LLM's keywords feed events (hits of kind event, reported by ev id).
"""

import logging
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from ragcommon.routing import Hit, RoutingLexicon
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
    detected_persons: tuple[str, ...] = ()   # target labels, one per distinct target
    detected_places: tuple[str, ...] = ()
    detected_events: tuple[str, ...] = ()    # ev ids (the LLM keywords in the fallback)
    detected_book_names: tuple[str, ...] = ()
    detected_book_ids: tuple[str, ...] = ()  # aligned with detected_book_names
    route: str = "fallback"


def _hits(lexicon: RoutingLexicon, texts: Iterable[str]) -> list[Hit]:
    return [hit for text in texts for hit in lexicon.match(text)]


def _typed(hits: Iterable[Hit], route_type: str) -> tuple[str, ...]:
    """Labels of the distinct targets (by ref, first seen) that count as ``route_type``."""
    found: dict[str, str] = {}
    for hit in hits:
        for target in hit.targets:
            if route_type in target.route_types:
                found.setdefault(target.ref, target.label)
    return tuple(found.values())


def _events(hits: Iterable[Hit], intent_type: str, keywords: list[str]) -> tuple[str, ...]:
    found = [t.ref for hit in hits if hit.kind == "event" for t in hit.targets]
    if intent_type == "event" and not found:
        # the LLM thinks it is an event question though no event term matched
        found = list(keywords)
    return tuple(dict.fromkeys(found))


def detect_signals(query: str, verse_refs: list[VerseRef], intent_type: str,
                   entity_names: list[str], lexicon: RoutingLexicon,
                   book_ids: Mapping[str, str], keywords: list[str] | None = None
                   ) -> QuerySignals:
    """Signals of one query; ``book_ids`` maps the lexicon's full book names to book ids."""
    has_verse = any(ref.verse_start is not None for ref in verse_refs)
    books = tuple(lexicon.match_books(query))
    query_hits = lexicon.match(query)
    named = query_hits + _hits(lexicon, entity_names)
    persons, places = _typed(named, "Person"), _typed(named, "Place")
    events = _events(query_hits + _hits(lexicon, keywords or []), intent_type, keywords or [])
    signals = QuerySignals(
        has_book_chapter_verse=has_verse, has_book_chapter=bool(verse_refs) and not has_verse,
        has_multi_book=len(books) >= 2, has_multi_person=len(persons) >= 2,
        has_event_keyword=bool(events), has_place=bool(places),
        detected_persons=persons, detected_places=places, detected_events=events,
        detected_book_names=books, detected_book_ids=tuple(book_ids[b] for b in books))
    route = select_route(signals, intent_type)
    logger.info("Signal detector: route=%s, signals=[verse=%s, chapter=%s, multi_book=%s, "
                "multi_person=%s, event=%s, place=%s], persons=%s, places=%s, events=%s",
                route, signals.has_book_chapter_verse, signals.has_book_chapter,
                signals.has_multi_book, signals.has_multi_person, signals.has_event_keyword,
                signals.has_place, persons, places, events)
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
