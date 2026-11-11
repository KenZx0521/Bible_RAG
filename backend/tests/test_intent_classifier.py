"""Intent: read from the question's text alone, with no model call."""

import inspect

from utils import intent_classifier


def test_classifying_is_a_plain_call_with_no_model_behind_it():
    assert not inspect.iscoroutinefunction(intent_classifier.classify_intent)
    assert not hasattr(intent_classifier, "get_llm_client")


def test_a_question_with_no_reference_is_a_topic():
    out = intent_classifier.classify_intent("保羅歸主的經過為何？")

    assert out == {"type": "topic", "verse_refs": [], "rejected_refs": []}


def test_a_verse_reference_makes_it_verse_lookup():
    out = intent_classifier.classify_intent("約翰福音3:16說了什麼")

    assert out["type"] == "verse_lookup"
    assert [r.display for r in out["verse_refs"]] == ["約翰福音3:16"]


def test_a_chapter_reference_makes_it_verse_lookup():
    out = intent_classifier.classify_intent("羅馬書8章的重點")

    assert out["type"] == "verse_lookup" and len(out["verse_refs"]) == 1


def test_a_reference_to_no_verse_is_reported_not_routed():
    out = intent_classifier.classify_intent("約翰福音3:99說什麼？")

    assert out["verse_refs"] == [] and out["rejected_refs"] == ["約翰福音3:99"]
    assert out["type"] == "topic"
