"""The Genesis age card (utils.gen_card, plan 2026-10-21 §2.2, A2 (1) and (5)) on a made-up layer.

``card_of`` is utils.gencard's card where its rule fires, with one log line that never holds the
question. /query attaches it only when it is on (``use_gen_card``, else RAG_GEN_CARD with the regnal
card's ablation rule), there are passages and an answer is generated; the generator then gets
``build_messages`` on the response's own context blocks with the card as the auxiliary block. A
question the rule does not take gets today's messages. The regnal trigger's precedence (D3) is in
test_regnal_card, the startup reading in test_startup, the store's layer in test_gen_card_store. No
store, no LLM.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gen_fakes as F
import main
from config import settings
from router_fakes import LEXICON
from routers import query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import gen_card, gencard, generator

BUILD = Build("b20261021_0123abcd", "bb20261021_0123abcd", "passages__b", Path("/c"), False, 22)
LAYER, NAMES = F.files()
LAYER_SHA = hashlib.sha256(LAYER).hexdigest()


@pytest.fixture
def gen():
    return gen_card.parse_files(LAYER, NAMES)


def test_the_layer_parses_from_the_two_files_and_keeps_the_layers_sha(gen):
    assert gen_card.chain_size(gen) == {5: 5, 11: 3}
    assert gen.gen_layer_sha256 == LAYER_SHA


def test_card_of_is_the_rule_card_with_one_log_line_that_never_holds_the_question(gen, caplog):
    caplog.set_level(logging.INFO, logger="utils.gen_card")
    assert gen_card.card_of(F.SILENT, gen) is None
    assert caplog.records == []

    card = gen_card.card_of(F.FIRES, gen)
    assert card == gencard.card(F.FIRES, gen) and card.seeds == F.FIRES_SEEDS and len(card.lines) == 3
    [record] = caplog.records
    qhash = hashlib.sha256(F.FIRES.encode("utf-8")).hexdigest()[:12]
    assert record.levelno == logging.INFO
    assert record.getMessage() == f"gen card q={qhash} seeds=['G05.00', 'G05.02'] shape=F1 lines=3"


def test_evidence_is_the_rows_verse_keys_in_order(gen):
    assert gen_card.evidence(gen, ("G05.01", "G05.00", "G05.01")) == (
        "syn.5.3", "syn.5.4", "syn.5.5", "syn.5.0", "syn.5.1", "syn.5.2")


PASSAGES = [{"id": "ps:gen.5.1", "kind": "passage", "book_name": "創世記", "chapter_num": 5, "title": "甲",
             "verse_range": "1-5", "content": "1 經文", "found_by": ["semantic"]},
            {"id": "ps:gen.11.10", "kind": "passage", "book_name": "創世記", "chapter_num": 11, "title": "乙",
             "verse_range": "10-26", "content": "10 經文", "found_by": ["semantic"]}]


@pytest.fixture
def client(gen, monkeypatch):
    context.install(context.make_active(BUILD, LEXICON, (), None, gen), Handshake(BUILD.build_id, (), True))
    seen = {"chats": [], "results": PASSAGES}

    async def intent(question):
        return {"type": "person", "entities": [], "verse_refs": [], "keywords": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        return [dict(p) for p in seen["results"]], {"strategies_used": ["semantic"], "route_used": "R4"}

    class FakeLlm:
        async def chat(self, messages, temperature, max_tokens):
            seen["chats"].append(messages)
            return "推理\n答案：190歲"

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(query, "retrieve_and_rerank", retrieve)
    monkeypatch.setattr(generator, "get_llm_client", lambda: FakeLlm())
    yield TestClient(main.app), seen
    context.reset()


def _ask(http, question: str, **payload) -> dict:
    return http.post("/api/v1/query", json={"question": question, "include_context": True, **payload}).json()


def _context(body: dict) -> str:
    """What the response says the generator read: its sources' context blocks."""
    return "\n\n".join(s["context"] for s in body["sources"])


def test_query_attaches_the_card_and_the_prompt_is_build_messages_on_the_responses_context(client, gen):
    http, seen = client
    body = _ask(http, F.FIRES)
    card = gen_card.card_of(F.FIRES, gen)
    assert body["aux_card"] == {
        "kind": "gen", "text": card.g_block, "seeds": ["安東", "卡爾"], "kings": ["G05.00", "G05.02"], "lines": 3,
        "evidence": [f"syn.5.{i}" for i in range(12)], "layer_sha256": LAYER_SHA, "seed_source": "rule"}
    assert len(body["sources"]) == 2
    assert seen["chats"] == [generator.build_messages(F.FIRES, _context(body), body["aux_card"]["text"])]
    assert seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT_AUX


def test_a_question_the_rule_does_not_take_gets_todays_messages(client):
    http, seen = client
    body = _ask(http, F.SILENT)
    assert body["aux_card"] is None
    assert seen["chats"] == [generator.build_messages(F.SILENT, _context(body))]
    assert seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT


@pytest.mark.parametrize("payload, carded", [
    ({}, True),
    ({"use_regnal_card": False}, True),          # the regnal card's switch is not this one
    ({"use_gen_card": False}, False),
    ({"semantic_only": True}, False),
    ({"use_graph": False}, False),
    ({"use_graph": False, "use_gen_card": True}, True),
    ({"semantic_only": True, "use_gen_card": True}, True),
])
def test_the_ablation_arms_are_card_free_unless_asked(client, payload, carded):
    http, seen = client
    body = _ask(http, F.FIRES, **payload)
    assert (body["aux_card"] is not None) == carded
    assert seen["chats"][0][0]["content"] == (generator.SYSTEM_PROMPT_AUX if carded else generator.SYSTEM_PROMPT)


def test_rag_gen_card_off_leaves_only_the_request_flag(client, monkeypatch):
    http, _seen = client
    monkeypatch.setattr(settings, "rag_gen_card", False)
    assert _ask(http, F.FIRES)["aux_card"] is None
    assert _ask(http, F.FIRES, use_gen_card=True)["aux_card"]["kind"] == "gen"


def test_no_card_without_an_answer_passages_or_a_layer(client):
    http, seen = client
    body = _ask(http, F.FIRES, retrieval_only=True)
    assert body["aux_card"] is None and body["answer"] == "" and seen["chats"] == []
    seen["results"] = []
    body = _ask(http, F.FIRES)
    assert body["aux_card"] is None and seen["chats"] == []
    seen["results"] = PASSAGES
    context.install(context.make_active(BUILD, LEXICON, ()), Handshake(BUILD.build_id, (), True))
    assert context.active().gen is None
    assert _ask(http, F.FIRES)["aux_card"] is None
