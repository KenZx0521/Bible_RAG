"""The frozen R1 routing lexicon (config/registries/routing_lexicon.legacy.json, D-12(a))
must route exactly like the live entity_dicts it was frozen from, so the backend can
switch to it (ragcommon.routing) without changing a single route. G-ROUTE checks the
same on every verse at build time; this guards the backend side between builds."""

import json
from pathlib import Path

import pytest

from ragcommon import routing
from utils import entity_dicts

REPO = Path(__file__).resolve().parents[2]
FROZEN = REPO / "config" / "registries" / "routing_lexicon.legacy.json"


@pytest.fixture(scope="module")
def lexicon():
    return routing.load_lexicon(FROZEN)


def _questions():
    doc = json.loads((REPO / "ground_truth.json").read_text(encoding="utf-8"))
    return [q["question"] for q in doc["questions"]]


def test_frozen_lexicon_matches_entity_dicts_on_the_gt_questions(lexicon):
    for text in _questions():
        assert lexicon.match_persons(text) == entity_dicts.match_persons_in_text(text), text
        assert lexicon.match_places(text) == entity_dicts.match_places_in_text(text), text
        assert lexicon.match_events(text) == entity_dicts.match_events_in_text(text), text
        assert lexicon.match_books(text) == entity_dicts.match_books_in_text(text), text
        assert lexicon.count_books(text) == entity_dicts.count_books_in_text(text), text


def test_frozen_lexicon_holds_the_live_vocabulary(lexicon):
    assert {t.canonical: set(t.aliases) for t in lexicon.persons} == entity_dicts.PERSON_DICT
    assert {t.canonical: set(t.aliases) for t in lexicon.places} == entity_dicts.PLACE_DICT
    assert set(lexicon.events) == entity_dicts.EVENT_KEYWORDS
