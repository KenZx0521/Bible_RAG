"""Routing signals come from the build's routing lexicon and route exactly as before.

R1 serves the legacy vocabulary frozen from the old entity_dicts (D-12(a)). The
golden file holds what that old code (f9ad4d3) answered on every GT question;
the backend, now matching through ragcommon.routing on the frozen lexicon, must
give the same persons, places, events and books, text for text.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ragcommon import routing
from utils.signal_detector import QuerySignals, detect_signals, select_route
from utils.verse_parser import VerseRef

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FROZEN = REPO / "config" / "registries" / "routing_lexicon.legacy.json"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "routing_legacy_gt.json"


@pytest.fixture(scope="module")
def lexicon():
    return routing.load_lexicon(FROZEN)


def _signals(lexicon, text, verse_refs=(), intent="topic", entities=(), keywords=None):
    book_ids = {b.full_name: b.book_id for b in lexicon.books}
    return detect_signals(text, list(verse_refs), intent, list(entities), lexicon, book_ids,
                          keywords)


def test_signals_reproduce_the_old_entity_dicts_on_every_gt_question(lexicon):
    rows = json.loads(GOLDEN.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 500
    for row in rows:
        s = _signals(lexicon, row["text"])
        found = {"persons": list(s.detected_persons), "places": list(s.detected_places),
                 "events": list(s.detected_events), "books": list(s.detected_book_names)}
        assert found == {k: row[k] for k in found}, row["text"]


def test_book_ids_follow_the_detected_names(lexicon):
    s = _signals(lexicon, "耶利米書的新約預言在希伯來書的應驗")

    assert s.detected_book_names == ("耶利米書", "希伯來書")
    assert s.detected_book_ids == ("jer", "heb")
    assert s.route == "R5"


def test_llm_entities_and_keywords_add_signals(lexicon):
    s = _signals(lexicon, "他們的關係如何？", intent="person", entities=["摩西", "葉忒羅"],
                 keywords=["出埃及"])

    assert s.detected_persons == ("摩西", "葉忒羅")
    assert s.detected_events == ("出埃及",)
    assert s.route == "R3"


def test_an_event_intent_without_a_keyword_keeps_the_llm_keywords(lexicon):
    s = _signals(lexicon, "那件事怎麼發生的", intent="event", keywords=["某事"])

    assert s.detected_events == ("某事",) and s.route == "R4"


@pytest.mark.parametrize("signals, intent, route", [
    (QuerySignals(has_book_chapter_verse=True, has_multi_book=True), "", "R1"),
    (QuerySignals(has_book_chapter=True, has_multi_book=True), "", "R5"),
    (QuerySignals(has_book_chapter=True), "", "R2"),
    (QuerySignals(), "cross_reference", "R5"),
    (QuerySignals(has_multi_person=True, has_event_keyword=True), "", "R3"),
    (QuerySignals(has_event_keyword=True, has_place=True), "", "R4"),
    (QuerySignals(has_place=True), "", "R6"),
    (QuerySignals(), "topic", "fallback"),
])
def test_route_priority(signals, intent, route):
    assert select_route(signals, intent) == route


def test_verse_references_set_the_verse_signals(lexicon):
    assert _signals(lexicon, "q", [VerseRef("jhn", "約翰福音", 3, 16, 16)]).route == "R1"
    assert _signals(lexicon, "q", [VerseRef("jhn", "約翰福音", 3)]).route == "R2"


def test_detected_signals_are_identical_across_hash_seeds():
    code = (
        "from ragcommon import routing\n"
        "from utils.signal_detector import detect_signals\n"
        f"lex = routing.load_lexicon({str(FROZEN)!r})\n"
        "ids = {b.full_name: b.book_id for b in lex.books}\n"
        "s = detect_signals('摩西和亞倫在耶路撒冷與伯利恆經歷出埃及、過紅海與逾越節', [], 'event',\n"
        "                   ['摩西', '亞倫', '約書亞'], lex, ids, ['十誡', '五旬節', '受難週'])\n"
        "print(s.detected_events, s.detected_places, s.detected_persons)\n"
    )
    path = os.pathsep.join([str(BACKEND), str(REPO / "packages")])
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=True, text=True,
                              capture_output=True,
                              env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": path}
                              ).stdout for seed in ("1", "2", "3", "4")}
    assert len(outputs) == 1, outputs
