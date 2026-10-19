"""The chronology card (utils.regnal): the trigger takes only the confirmed question types,
the ordinary prompt is untouched without a card (plan A2), the layer parses from its contract
bytes, and /query attaches the card only when it is on and fires."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from router_fakes import LEXICON
from routers import query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import generator
from utils.regnal import card as card_mod
from utils.regnal.layer import parse_layer
from utils.regnal.trigger import trigger

NAMES = ("耶羅波安", "撒迦利雅", "比加轄", "約西亞", "希西家", "亞哈謝", "沙龍", "比加", "暗利", "拿答", "亞哈")
BUILD = Build("b20261019_0123abcd", "bb20261019_0123abcd", "passages__b", Path("/c"), False, 22)


def _layer_doc() -> dict:
    """A two-kingdom layer: I01 -> I02 -> I03 (Israel), J01 -> J02 (Judah)."""
    def node(i, kd, name, order, reign, age=None):
        fields = {"reign": [reign, f"2ki.{order}.1", "ki"]}
        if age is not None:
            fields["age"] = [age, f"2ki.{order}.2", "ki"]
        return {"id": i, "kingdom": kd, "name": name, "aliases": [], "fields": fields,
                "evidence": [f"2ki.{order}.1"], "pending": False, "order": order, "created_by": "t",
                "has_acc": True}
    return {"policy": "occ", "fn_rule": "slot",
            "nodes": [node("A00", "I", "暗利", 0, 12), node("A01", "I", "亞哈", 1, 22),
                      node("A02", "I", "亞哈謝", 2, 2), node("A03", "J", "約沙法", 3, 25, 35),
                      node("A04", "J", "約蘭", 4, 8, 32)],
            "edges": [["A00", "A01", "son", "1ki.16.28"], ["A01", "A02", "son", "1ki.22.40"],
                      ["A03", "A04", "son", "1ki.22.50"]],
            "fallback_edges": [], "syncs": [], "conflicts": [], "log": [], "occ_alias": [],
            "union_classes": None}


@pytest.fixture
def layer():
    return parse_layer(json.dumps(_layer_doc(), ensure_ascii=False, indent=1).encode("utf-8"))


@pytest.mark.parametrize("question, cues", [
    ("請問沙龍之後的第二位王是哪一位？", ("S1a",)),
    ("亞哈謝之前的第3位王叫什麼名字？", ("S1a",)),
    ("暗利以後第三任的王是誰？", ("S1a",)),
    ("亞哈之後，第二位作王的是誰？", ("S1a",)),
    ("從暗利往前數第三位作王的是誰？", ("S1a",)),
    ("沙龍之前，往前數的第二位王是誰？", ("S1a",)),
    ("希西家死後由兒子接續他作王，再下一位是誰？", ("S1a",)),
    ("拿答到暗利之間王位交接了幾回？", ("S1b",)),
    ("撒迦利雅以後，第二個篡位得國的是誰？", ("S1c",)),
    ("約西亞出生時，耶路撒冷的王是哪位？", ("S4",)),
    ("希西家出生那年誰在位？", ("S4",)),
])
def test_the_confirmed_types_take_the_card(question, cues):
    hit = trigger(question, NAMES)
    assert hit.fired and hit.cues == cues


@pytest.mark.parametrize("question", [
    "約西亞年間有哪些先知？",                                # 年間: the events of a reign
    "聖殿被焚毀前後發生了哪些事？先後順序如何？",            # no chain king, no cue
    "希西家在位時國中有什麼改革？",                          # 在位時 is no cue
    "暗利一共作王多少年？",                                  # a reign length is no cue
    "大衛之後的第二位王是誰？",                              # David is not on the chain
])
def test_broad_words_and_unchained_kings_do_not(question):
    assert not trigger(question, NAMES).fired


def test_the_longest_name_wins_and_full_width_digits_count():
    hit = trigger("比加轄之前的第３位王是哪一位？", NAMES)
    assert hit.fired and hit.kings == ("比加轄",)


def test_without_a_card_the_prompt_is_the_one_served_before_the_card():
    assert hashlib.sha256(generator.SYSTEM_PROMPT.encode()).hexdigest() == \
        "eae1f438f51749bdaff9a5a524b02b1e7e549995989895d9d1e0977f375d14fc"
    assert hashlib.sha256(generator.CONTEXT_TEMPLATE.encode()).hexdigest() == \
        "de9abb728d086b33f91ec350ef242dd9ea3146189b265e6fa476ea98ccd2e4ea"
    for aux in (None, ""):
        assert generator.build_messages("問題", "[1] 經文", aux) == [
            {"role": "system", "content": generator.SYSTEM_PROMPT},
            {"role": "user", "content": generator.CONTEXT_TEMPLATE.format(context="[1] 經文", question="問題")}]


def test_with_a_card_the_prompt_has_the_auxiliary_block_and_the_answer_line():
    system, user = generator.build_messages("問題", "[1] 經文", "卡片列")
    assert system["content"] == generator.SYSTEM_PROMPT_AUX
    assert user["content"] == ("以下是提供的經文段落（你只能使用這些內容來回答）：\n\n[1] 經文\n\n"
                               "以下是輔助資料（依經文整理）：\n卡片列\n\n---\n\n嚴格根據以上經文段落與輔助資料的內容，"
                               "回答以下問題。不要添加提供內容中沒有的資訊。請先逐步列出推理，最後一行只寫「答案：」加上答案。\n問題")


def test_the_layer_parses_its_contract_bytes_and_refuses_others(layer):
    assert layer.chain_size() == {"I": 3, "J": 2}
    assert layer.names[:2] == ("亞哈謝", "約沙法")
    with pytest.raises(ValueError):
        parse_layer(b"{}")
    with pytest.raises(ValueError):
        parse_layer(b"not json")


def test_a_seed_output_becomes_the_engine_card(layer):
    card = card_mod.card_from_seeds(layer, "暗利之後的第二位王是哪一位？", "以色列｜暗利")
    assert card is not None and card.kings == ("A00",) and card.seeds == (("I", "暗利"),)
    assert "依上列資料推算：" in card.text and "以色列王暗利之後第2位以色列王：亞哈謝" in card.text
    assert card.evidence[0] == "2ki.0.1" and card.layer_sha256 == layer.sha256
    assert card_mod.card_from_seeds(layer, "q", "猶大｜大衛") is None
    assert card_mod.card_from_seeds(layer, "q", "") is None


@pytest.fixture
def client(layer, monkeypatch):
    context.install(context.make_active(BUILD, LEXICON, (), layer), Handshake(BUILD.build_id, (), True))
    seen = {"chats": []}

    async def intent(question):
        return {"type": "person", "entities": [], "verse_refs": [], "keywords": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        hit = {"id": "ps:2ki.8.16", "kind": "passage", "book_name": "列王紀下", "chapter_num": 8,
               "title": "猶大王約蘭", "verse_range": "16-24", "content": "16 經文", "found_by": ["semantic"]}
        return [hit], {"strategies_used": ["semantic"], "route_used": "R4"}

    class FakeLlm:
        async def chat(self, messages, temperature, max_tokens):
            seen["chats"].append(messages)
            return "以色列｜暗利" if messages[0]["content"] == card_mod.SEED_SYSTEM else "推理\n答案：亞哈謝"

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(query, "retrieve_and_rerank", retrieve)
    monkeypatch.setattr(card_mod, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(generator, "get_llm_client", lambda: FakeLlm())
    yield TestClient(main.app), seen
    context.reset()


def test_query_attaches_the_card_on_a_chronology_question(client):
    http, seen = client
    body = http.post("/api/v1/query", json={"question": "暗利之後的第二位王是哪一位？"}).json()
    assert body["aux_card"]["seeds"] == ["以色列｜暗利"] and body["aux_card"]["kings"] == ["A00"]
    assert len(seen["chats"]) == 2 and seen["chats"][1][0]["content"] == generator.SYSTEM_PROMPT_AUX
    assert body["aux_card"]["text"] in seen["chats"][1][1]["content"]


@pytest.mark.parametrize("payload", [
    {"question": "暗利一共作王多少年？"},                                       # no cue
    {"question": "暗利之後的第二位王是哪一位？", "use_regnal_card": False},  # switched off
])
def test_query_answers_the_ordinary_way_otherwise(client, payload):
    http, seen = client
    body = http.post("/api/v1/query", json=payload).json()
    assert body["aux_card"] is None
    assert len(seen["chats"]) == 1 and seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT


def test_a_build_without_the_layer_has_no_card(client, monkeypatch):
    http, seen = client
    context.install(context.make_active(BUILD, LEXICON, ()), Handshake(BUILD.build_id, (), True))
    body = http.post("/api/v1/query", json={"question": "暗利之後的第二位王是哪一位？"}).json()
    assert body["aux_card"] is None and len(seen["chats"]) == 1


def test_a_failed_seed_call_falls_back_to_the_ordinary_answer(client, monkeypatch):
    http, seen = client

    async def boom(question, context):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(card_mod, "seed_call", boom)
    body = http.post("/api/v1/query", json={"question": "暗利之後的第二位王是哪一位？"}).json()
    assert body["aux_card"] is None and body["answer"] == "推理\n答案：亞哈謝"
