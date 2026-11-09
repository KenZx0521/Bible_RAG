"""Intent: references from ragcommon (rejected ones reported), intent from the LLM."""

import asyncio

import pytest

from utils import intent_classifier


class Llm:
    def __init__(self, answer=None, error=None):
        self.answer, self.error = answer, error

    async def chat(self, messages, temperature=0.1, max_tokens=512):
        if self.error:
            raise self.error
        return self.answer


def _classify(monkeypatch, question, llm):
    monkeypatch.setattr(intent_classifier, "get_llm_client", lambda: llm)
    return asyncio.run(intent_classifier.classify_intent(question))


def test_the_llm_intent_entities_and_keywords_are_kept(monkeypatch):
    out = _classify(monkeypatch, "保羅歸主的經過為何？", Llm(
        'thinking… {"intent": "event", "entities": ["保羅"], "keywords": ["歸主"]}'))

    assert (out["type"], out["entities"], out["keywords"]) == ("event", ["保羅"], ["歸主"])
    assert out["verse_refs"] == [] and out["rejected_refs"] == []


def test_a_verse_reference_makes_it_verse_lookup_even_when_the_llm_fails(monkeypatch):
    out = _classify(monkeypatch, "約翰福音3:16說了什麼", Llm(error=ConnectionError("down")))

    assert out["type"] == "verse_lookup"
    assert [r.display for r in out["verse_refs"]] == ["約翰福音3:16"]


def test_an_unknown_intent_or_garbage_falls_back_to_topic(monkeypatch):
    assert _classify(monkeypatch, "q", Llm('{"intent": "poetry"}'))["type"] == "topic"
    assert _classify(monkeypatch, "q", Llm("no json at all"))["type"] == "topic"


@pytest.mark.parametrize("field", ["null", '"保羅"', '{"a": 1}', "3", "true"])
def test_entities_or_keywords_that_are_not_a_list_become_empty(monkeypatch, field):
    out = _classify(monkeypatch, "q", Llm(
        f'{{"intent": "event", "entities": {field}, "keywords": {field}}}'))

    assert (out["type"], out["entities"], out["keywords"]) == ("event", [], [])


def test_only_non_blank_strings_are_kept_from_entities_and_keywords(monkeypatch):
    out = _classify(monkeypatch, "q", Llm(
        '{"intent": "person", "entities": [1, "保羅", null, "", "  ", ["x"]], "keywords": [2, "歸主"]}'))

    assert (out["entities"], out["keywords"]) == (["保羅"], ["歸主"])


@pytest.mark.parametrize("answer", ['["event"]', "3", '"event"', "null"])
def test_json_that_is_not_an_object_is_a_parse_failure_not_an_llm_failure(monkeypatch, caplog, answer):
    with caplog.at_level("WARNING", logger=intent_classifier.__name__):
        out = _classify(monkeypatch, "q", Llm(answer))

    assert (out["type"], out["entities"], out["keywords"]) == ("topic", [], [])
    assert "not parseable" in caplog.text and "classification failed" not in caplog.text


def test_an_object_wrapped_in_an_array_is_still_read(monkeypatch):
    out = _classify(monkeypatch, "q", Llm('[{"intent": "event", "entities": ["保羅"], "keywords": ["歸主"]}]'))

    assert (out["type"], out["entities"], out["keywords"]) == ("event", ["保羅"], ["歸主"])


def test_output_with_no_json_is_logged_as_unparseable(monkeypatch, caplog):
    with caplog.at_level("WARNING", logger=intent_classifier.__name__):
        out = _classify(monkeypatch, "q", Llm(""))

    assert out["type"] == "topic" and "not parseable" in caplog.text


def test_a_reference_to_no_verse_is_reported_not_routed(monkeypatch):
    out = _classify(monkeypatch, "約翰福音3:99說什麼？", Llm('{"intent": "topic"}'))

    assert out["verse_refs"] == [] and out["rejected_refs"] == ["約翰福音3:99"]
    assert out["type"] == "topic"
