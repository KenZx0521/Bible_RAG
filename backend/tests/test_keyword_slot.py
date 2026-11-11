"""The keyword slot: the BM25 index, the pick (no verse of the results twice), and the handler
appending it last, after the cards, only when it is on."""

import asyncio
import math
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from config import settings
from database import postgres
from router_fakes import LEXICON
from routers import query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils.retrieval import keyword_slot as ks

BUILD = Build("b20261008_1bb6912e", "bb20261008_1bb6912e", "passages__b", Path("/c"), False, 22)


def _passage(pid, book_id, book, chapter, title, first, last, content):
    return {"id": pid, "kind": "passage", "content": content, "title": title, "book_id": book_id,
            "book_name": book, "chapter_num": chapter, "verse_range": f"{first}-{last}",
            "start_key": f"{book_id}.{chapter}.{first}", "end_key": f"{book_id}.{chapter}.{last}",
            "passage_id": pid, "split_passage_ids": []}


EPH = _passage("ps:eph.6.1", "eph", "以弗所書", 6, "兒女和父母", 1, 4, "**1** 要孝敬父母。")
EXO = _passage("ps:exo.20.1", "exo", "出埃及記", 20, "十誡", 1, 17, "**12** 當孝敬父母。")
DEU = _passage("ps:deu.5.1", "deu", "申命記", 5, "十誡", 1, 21, "**16** 當照耶和華的吩咐孝敬父母。")
ACT = {**_passage("ps:act.9.1", "act", "使徒行傳", 9, "掃羅歸主", 1, 19, "**1** 掃羅。"),
       "id": "ck:act.9.1~act.9.9", "kind": "chunk", "verse_range": "1-9", "end_key": "act.9.9"}
SOURCES = {p["id"]: p for p in (EPH, EXO, DEU, ACT)}
RECORDS = [("ps:deu.5.1", "passage", "申命記 第5章 十誡 (1-21節)：當照耶和華的吩咐孝敬父母"),
           ("ps:eph.6.1", "passage", "以弗所書 第6章 兒女和父母 (1-4節)：要孝敬父母，孝敬父母"),
           ("ps:exo.20.1", "passage", "出埃及記 第20章 十誡 (1-17節)：當孝敬父母"),
           ("ck:act.9.1~act.9.9", "chunk", "使徒行傳 第9章 掃羅歸主 (1-9節)：掃羅往大馬士革去")]


@pytest.fixture
def lookups(monkeypatch):
    asked = []

    async def fetch_sources(passage_ids, chunk_ids=()):
        asked.append((list(passage_ids), list(chunk_ids)))
        return {i: dict(SOURCES[i]) for i in [*passage_ids, *chunk_ids] if i in SOURCES}

    monkeypatch.setattr(postgres, "fetch_sources", fetch_sources)
    return asked


def _bm25(records, query, k1=1.2, b=0.75):
    """BM25 written out term by term, the reference the index must equal."""
    docs = [Counter(ks.terms(text)) for _, _, text in records]
    lengths = [sum(d.values()) for d in docs]
    avgdl = sum(lengths) / len(lengths)
    scores = []
    for doc, dl in zip(docs, lengths):
        s = 0.0
        for t in set(ks.terms(query)):
            if doc[t]:
                df = sum(1 for d in docs if d[t])
                idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                s += idf * doc[t] * (k1 + 1) / (doc[t] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores


# --- terms and the index ---

def test_terms_are_bigrams_of_each_run_and_a_lone_character_is_one():
    assert ks.terms("天國裏誰是最大的？") == ["天國", "國裏", "裏誰", "誰是", "是最", "最大", "大的"]
    assert ks.terms("神，愛") == ["神", "愛"]
    assert ks.terms("約3:16 Jesus") == ["約", "3", "16", "Je", "es", "su", "us"]
    assert ks.terms("，。！") == []


def test_runs_cover_the_experiments_code_points_only():
    """CJK Extension A, the unified and the compatibility ideographs (U+F900-U+FAFF, whose first
    character looks like the unified 豈 U+8C48): nothing else, so Hangul splits a run."""
    assert ks.terms("神가 누구") == ["神"]
    assert ks.terms("\uf900\ufaff") == ["\uf900\ufaff"] and ks.terms("\u3400\u4dbf") == ["\u3400\u4dbf"]
    assert ks.terms("\ue000\ua000") == []


@pytest.mark.parametrize("question", ["孝敬父母", "十誡是甚麼", "掃羅往大馬士革", "父"])
def test_scores_equal_bm25_written_out(question):
    index = ks.build(RECORDS)
    expected = _bm25(RECORDS, question)
    hits = index.top(question, 10)

    assert {h.record_id: h.score for h in hits} == pytest.approx(
        {rid: s for (rid, _, _), s in zip(RECORDS, expected) if s > 0})
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_ties_go_to_the_earlier_record_and_n_cuts():
    index = ks.build([("ps:b", "passage", "孝敬父母"), ("ps:a", "passage", "孝敬父母"),
                      ("ps:c", "passage", "別的話")])

    assert [h.record_id for h in index.top("孝敬", 5)] == ["ps:b", "ps:a"]
    assert [h.record_id for h in index.top("孝敬", 1)] == ["ps:b"]


def test_a_question_with_no_indexed_term_finds_nothing():
    assert ks.build(RECORDS).top("！？", 5) == []
    assert ks.build(RECORDS).top("曠野嗎哪", 5) == []
    assert ks.build([]).top("孝敬", 5) == []


def test_hits_carry_their_kind():
    [hit] = ks.build(RECORDS).top("掃羅", 5)

    assert (hit.record_id, hit.kind) == ("ck:act.9.1~act.9.9", "chunk")


def test_a_verse_record_is_refused():
    with pytest.raises(ValueError, match="verse"):
        ks.build([("vs:jhn.3.16", "verse", "上帝愛世人")])


# --- the pick ---

def _pick(question, results, index=None):
    return asyncio.run(ks.pick(question, results, ks.build(RECORDS) if index is None else index))


def test_the_best_hit_is_taken_when_it_repeats_no_verse(lookups):
    slot = _pick("孝敬父母", [])

    assert slot.candidate["id"] == "ps:eph.6.1" and slot.rank == 1
    assert slot.candidate["source_strategy"] == "keyword" and slot.candidate["found_by"] == ["keyword"]
    assert slot.candidate["weight"] == 0.0 and "rerank_score" not in slot.candidate
    assert lookups == [(["ps:eph.6.1", "ps:exo.20.1", "ps:deu.5.1"], [])]


def test_a_chunk_hit_is_looked_up_as_a_chunk(lookups):
    slot = _pick("掃羅往大馬士革", [])

    assert slot.candidate["id"] == "ck:act.9.1~act.9.9" and slot.candidate["kind"] == "chunk"
    assert lookups == [([], ["ck:act.9.1~act.9.9"])]


def test_a_hit_sharing_a_verse_with_the_results_is_passed_over(lookups):
    held = {**EPH, "id": "ck:eph.6.3~eph.6.4", "kind": "chunk", "start_key": "eph.6.3"}

    slot = _pick("孝敬父母", [held])

    assert slot.candidate["id"] == "ps:exo.20.1" and slot.rank == 2 and slot.looked_at == 3


def test_a_hit_in_another_chapter_or_range_of_the_same_book_is_kept(lookups):
    other = {**EPH, "id": "ps:eph.6.5", "start_key": "eph.6.5", "end_key": "eph.6.9"}

    assert _pick("孝敬父母", [other]).candidate["id"] == "ps:eph.6.1"


def test_nothing_is_appended_when_every_hit_repeats_a_verse(lookups):
    slot = _pick("孝敬父母", [EPH, EXO, DEU])

    assert slot.candidate is None and slot.looked_at == 3 and slot.error is None


def test_no_hit_means_no_lookup(lookups):
    slot = _pick("曠野嗎哪", [])

    assert slot == ks.Slot() and lookups == []


def test_a_failed_lookup_is_an_error_not_a_crash(monkeypatch):
    async def down(passage_ids, chunk_ids=()):
        raise ConnectionError("pg down")

    monkeypatch.setattr(postgres, "fetch_sources", down)
    slot = _pick("孝敬父母", [])

    assert slot.candidate is None and "pg down" in slot.error


def test_without_an_index_the_slot_says_so():
    assert asyncio.run(ks.pick("孝敬父母", [], None)).error == "no keyword index"


def test_apply_appends_last_and_reports_without_touching_its_inputs():
    results, stats = [EPH], {"strategies_used": ["hybrid_hybrid"], "strategy_errors": {}}
    slot = ks.Slot({**EXO, "source_strategy": "keyword", "found_by": ["keyword"]}, 2, 1.5, 3)

    out, out_stats = ks.apply(results, stats, slot)

    assert [r["id"] for r in out] == ["ps:eph.6.1", "ps:exo.20.1"] and results == [EPH]
    assert out_stats["strategies_used"] == ["hybrid_hybrid", "keyword"]
    assert out_stats["keyword_slot"] == {"id": "ps:exo.20.1", "rank": 2, "score": 1.5, "looked_at": 3}
    assert stats == {"strategies_used": ["hybrid_hybrid"], "strategy_errors": {}}


def test_apply_records_an_error_and_appends_nothing():
    out, out_stats = ks.apply([EPH], {"strategy_errors": {"rerank": "x"}}, ks.Slot(error="pg down"))

    assert out == [EPH] and out_stats["strategy_errors"] == {"rerank": "x", "keyword": "pg down"}
    assert out_stats["keyword_slot"]["id"] is None


# --- the handler ---

@pytest.fixture
def client():
    yield TestClient(main.app)  # no `with`: the lifespan (models, stores) does not run
    context.reset()


@pytest.fixture
def pipeline(monkeypatch, lookups):
    """A served build with the RECORDS index; retrieval returns EPH; the card and the generator
    record what they were given."""
    seen = {}
    context.install(context.make_active(BUILD, LEXICON, (), keywords=ks.build(RECORDS)),
                    Handshake(BUILD.build_id, (), strict=True))

    def intent(question):
        return {"type": "topic", "verse_refs": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        return [dict(EPH, source_strategy="hybrid_hybrid", found_by=["hybrid_hybrid"])], {
            "strategies_used": ["hybrid_hybrid"], "route_used": "fallback", "strategy_errors": {}}

    async def card(question, context_text, regnal):
        seen["card_context"] = context_text
        return None

    async def generate(question, results, aux):
        seen["generated_from"] = [r["id"] for r in results]
        return "答"

    def trace(stats, results, card, generated=True):
        seen["traced"] = [r["id"] for r in results]
        return []

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(query, "retrieve_and_rerank", retrieve)
    monkeypatch.setattr(query, "chronology_card", card)
    monkeypatch.setattr(query, "generate_answer", generate)
    monkeypatch.setattr(query.graph_trace, "of", trace)
    return seen


def _ask(client, **extra):
    response = client.post("/api/v1/query", json={"question": "孝敬父母", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_off_by_default(client, pipeline):
    body = _ask(client)

    assert [s["id"] for s in body["sources"]] == ["ps:eph.6.1"]
    assert body["retrieval_stats"]["keyword_slot"] is None


def test_on_it_is_the_last_source_and_comes_after_the_card(client, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "rag_keyword_slot", True)

    body = _ask(client)

    last = body["sources"][-1]
    assert [s["id"] for s in body["sources"]] == ["ps:eph.6.1", "ps:exo.20.1"]
    assert last["strategy"] == "keyword" and last["found_by"] == ["keyword"] and last["score"] is None
    assert body["retrieval_stats"]["keyword_slot"] == {"id": "ps:exo.20.1", "rank": 2,
                                                       "score": pytest.approx(last_score()),
                                                       "looked_at": 3}
    assert body["retrieval_stats"]["strategies_used"] == ["hybrid_hybrid", "keyword"]
    assert "出埃及記" not in pipeline["card_context"]
    assert pipeline["generated_from"] == ["ps:eph.6.1", "ps:exo.20.1"]
    assert pipeline["traced"] == ["ps:eph.6.1"]


def last_score():
    return {h.record_id: h.score for h in ks.build(RECORDS).top("孝敬父母", 5)}["ps:exo.20.1"]


def test_retrieval_only_gets_it_too(client, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "rag_keyword_slot", True)

    body = _ask(client, retrieval_only=True)

    assert [s["id"] for s in body["sources"]] == ["ps:eph.6.1", "ps:exo.20.1"] and body["answer"] == ""


@pytest.mark.parametrize("setting, extra, on", [
    (True, {"semantic_only": True}, False),
    (True, {"semantic_only": True, "use_keyword_slot": True}, True),
    (True, {"use_keyword_slot": False}, False),
    (False, {"use_keyword_slot": True}, True),
    (True, {"use_graph": False}, True),
])
def test_the_switch(client, pipeline, monkeypatch, setting, extra, on):
    monkeypatch.setattr(settings, "rag_keyword_slot", setting)

    body = _ask(client, retrieval_only=True, **extra)

    assert (body["sources"][-1]["strategy"] == "keyword") is on
    assert (body["retrieval_stats"]["keyword_slot"] is not None) is on
