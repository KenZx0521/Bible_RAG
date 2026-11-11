"""The graph side of a request: when it runs, what it joins to the pool, what it sends to Neo4j.

The walk and the kinship card run on R3-R6 and fallback, after the pool is gathered and before it
is ranked. R1, R2, semantic_only, use_graph=false, a strategy left out and a build without a graph
send no Cypher at all; Neo4j being down is a skip_reason and the answer goes on.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import gen_fakes as F
import graph_fakes as G
import main
from config import settings
from database import neo4j_db, postgres
from router_fakes import LEXICON, cand, fake_dense, no_supplement
from routers import query
from serving import context
from test_regnal_card import _layer_doc
from utils import gen_card, generator
from utils.regnal.layer import parse_layer
from utils.retrieval import graph_stage, graph_walk, router, routes
from utils.signal_detector import QuerySignals

# 掃羅 and 巴拿巴 are persons of router_fakes' lexicon: a kinship question over one or two of them
KIN_QUESTION = "掃羅的父親是誰"
PERSON = {"surface": "掃羅", "id": "e000001", "label": "掃羅", "mentions": 3, "kin_conflict": False,
          "units": ["act.9.1"], "parents": [], "children": 0, "spouses": 0, "siblings": 0}
PATH = {"nodes": [["e000001", "掃羅"], ["e000002", "基士"]],
        "edges": [["e000002", "PARENT_OF", "e000001", "P", ["1sa.9.2"]]], "hops": 1}
WALKED = {"names": [["nm:5a0000000001", "掃羅", 3.0]], "hits": [["ps:act.9.1", 9.0], ["ps:walked", 3.0]], "parallel": []}


@pytest.fixture
def served(scores, monkeypatch):
    G.serve(LEXICON)
    no_supplement(monkeypatch)

    async def fetch_sources(passage_ids, chunk_ids=()):
        return {p: cand(p, "x", 0.0) for p in passage_ids}
    monkeypatch.setattr(postgres, "fetch_sources", fetch_sources)
    yield
    context.reset()


def _forced(monkeypatch, route, pool=None):
    pool = pool if pool is not None else [cand("ps:act.9.1"), cand("ps:act.9.3b")]
    signals = QuerySignals(route=route)

    async def handler(inp):
        return [dict(c) for c in pool], ["semantic"], {}
    monkeypatch.setattr(router, "detect_signals", lambda **kw: signals)
    monkeypatch.setitem(routes.ROUTES, route, handler)


def _run(**kwargs):
    defaults = {"query": KIN_QUESTION, "verse_refs": [], "top_k": 5}
    return asyncio.run(router.retrieve_and_rerank(**{**defaults, **kwargs}))


def _full(monkeypatch) -> G.FakeGraph:
    return G.use(monkeypatch, G.FakeGraph({"walk_round": [WALKED], "kin_persons": [PERSON], "kin_up": [PATH],
                                           "unit_passages": [{"unit": "1sa.9.2", "passage": "ps:1sa.9.1"}]}))


# --- when it runs -------------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["R3", "R4", "R5", "R6", "fallback"])
def test_these_routes_walk_and_take_the_card(served, monkeypatch, route):
    graph = _full(monkeypatch)
    _forced(monkeypatch, route)

    ranked, stats = _run()

    assert "walk_round" in graph.names() and "kin_persons" in graph.names()
    assert stats["graph_walk"]["n_cypher"] == 2 and stats["kin_card"]["text"]
    assert "ps:walked" in [c["id"] for c in ranked]


@pytest.mark.parametrize("route", ["R1", "R2"])
def test_a_written_reference_sends_no_cypher(served, monkeypatch, route):
    graph = _full(monkeypatch)
    _forced(monkeypatch, route)

    _, stats = _run()

    assert graph.calls == [] and stats["graph_walk"] is None and stats["kin_card"] is None


def test_semantic_only_sends_no_cypher(served, monkeypatch):
    graph = _full(monkeypatch)
    fake_dense(monkeypatch, hits=[cand("ps:a", "semantic")])

    _, stats = _run(semantic_only=True)

    assert graph.calls == [] and stats["graph_walk"] is None and stats["kin_card"] is None


def test_the_graph_off_sends_no_cypher(served, monkeypatch):
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run(use_graph=False)

    assert graph.calls == [] and stats["graph_walk"] is None and stats["kin_card"] is None


@pytest.mark.parametrize("strategies, walks, carded", [
    ([], False, False), (["event_registry"], False, False), (["graph_walk"], True, False),
    (["kin_card"], False, True), (["graph_walk", "kin_card"], True, True)])
def test_each_strategy_is_its_own_switch(served, monkeypatch, strategies, walks, carded):
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run(graph_strategies=strategies)

    assert ("walk_round" in graph.names()) is walks and ("kin_persons" in graph.names()) is carded
    assert (stats["graph_walk"] is not None) is walks and (stats["kin_card"] is not None) is carded


def test_a_build_without_a_graph_sends_no_cypher(monkeypatch, scores):
    G.serve(LEXICON, kg=None)
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run()
    context.reset()

    assert graph.calls == [] and stats["graph_walk"] is None and stats["kin_card"] is None


def test_a_question_with_no_kinship_cue_walks_and_takes_no_card(served, monkeypatch):
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R6")

    _, stats = _run(query="掃羅去過哪些地方")

    assert "walk_round" in graph.names() and "kin_persons" not in graph.names()
    assert stats["kin_card"] is None


# --- what it joins to the pool ------------------------------------------------------------------

def test_the_walk_runs_on_the_gathered_pool_before_ranking(served, monkeypatch, scores):
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3", [cand("ps:act.9.1"), cand("ps:other", "sql_supplement")])
    scores["ps:walked"] = 0.99

    ranked, stats = _run(query="掃羅去過哪些地方", top_k=2)

    assert graph.calls[0][1]["seeds"] == [{"id": "ps:act.9.1", "w": 1.0}]
    assert graph.calls[0][1]["names"] == [{"id": "nm:5a0000000001", "w": 1.0}]
    assert ranked[0]["id"] == "ps:walked" and ranked[0]["source_strategy"] == "graph_walk"
    assert ranked[0]["weight"] == pytest.approx(settings.walk_weight)
    assert "graph_walk" in stats["strategies_used"]


def test_the_walk_leaves_a_pool_passages_weight_alone(served, monkeypatch, scores):
    _full(monkeypatch)
    _forced(monkeypatch, "R3", [cand("ps:act.9.1", weight=0.65), cand("ps:act.9.3b")])

    ranked, _ = _run(query="掃羅去過哪些地方")

    held = next(c for c in ranked if c["id"] == "ps:act.9.1")
    assert held["weight"] == 0.65 and "graph_walk" in held["found_by"]
    assert held["source_strategy"] == "hybrid_hybrid"


def test_the_cards_evidence_joins_the_pool_at_its_weight(served, monkeypatch, scores):
    _full(monkeypatch)
    _forced(monkeypatch, "R3")

    ranked, stats = _run()

    added = next(c for c in ranked if c["id"] == "ps:1sa.9.1")
    assert added["source_strategy"] == "kin_evidence" and added["weight"] == 0.75
    assert "kin_evidence" in stats["strategies_used"]


def test_a_card_with_no_edge_adds_no_passage(served, monkeypatch):
    G.use(monkeypatch, G.FakeGraph({"walk_round": [{"names": [], "hits": [], "parallel": []}],
                                    "kin_persons": [PERSON], "kin_up": []}))
    _forced(monkeypatch, "R3")

    ranked, stats = _run()

    assert {c["id"] for c in ranked} == {"ps:act.9.1", "ps:act.9.3b"}
    assert stats["kin_card"]["text"] is None and stats["kin_card"]["skip_reason"] == "no_edge"
    assert "kin_evidence" not in stats["strategies_used"]


# --- the other two cards ------------------------------------------------------------------------

def _regnal():
    return parse_layer(json.dumps(_layer_doc(), ensure_ascii=False, indent=1).encode("utf-8"))


def _gen():
    return gen_card.parse_files(*F.files())


def test_a_question_the_regnal_trigger_fires_on_takes_no_kin_card(monkeypatch, scores):
    """暗利 ... 第二位王: the trigger fires, whether or not the card then comes."""
    G.serve(LEXICON, regnal=_regnal())
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run(query="暗利之後第二位王的父親是誰")
    context.reset()

    assert "walk_round" in graph.names() and "kin_persons" not in graph.names()
    assert stats["kin_card"] is None


def test_the_kin_card_takes_a_question_the_regnal_trigger_does_not_fire_on(monkeypatch, scores):
    G.serve(LEXICON, regnal=_regnal())
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _run()
    context.reset()

    assert "kin_persons" in graph.names()


def test_a_question_the_gen_rule_takes_takes_no_kin_card(monkeypatch, scores):
    G.serve(LEXICON, gen=_gen())
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run(query="安東幾歲時他的孫子卡爾出生")
    context.reset()

    assert "kin_persons" not in graph.names() and stats["kin_card"] is None


def test_a_question_on_a_gen_chain_pair_the_rule_abstains_on_takes_no_kin_card(monkeypatch, scores):
    """Two chain persons and no age asked: the rule found its pair and abstained at its shape."""
    G.serve(LEXICON, gen=_gen())
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _, stats = _run(query="安東是卡爾的祖父嗎")
    context.reset()

    assert "kin_persons" not in graph.names() and stats["kin_card"] is None


def test_a_gen_layer_does_not_stop_a_question_that_is_not_its_own(monkeypatch, scores):
    G.serve(LEXICON, gen=_gen())
    graph = _full(monkeypatch)
    _forced(monkeypatch, "R3")

    _run()
    context.reset()

    assert "kin_persons" in graph.names()


# --- Neo4j does not answer ----------------------------------------------------------------------

@pytest.mark.parametrize("reason", [neo4j_db.UNAVAILABLE, neo4j_db.TIMEOUT, neo4j_db.SKIPPING, neo4j_db.AUTH])
def test_neo4j_down_is_a_skip_reason_and_the_ranking_as_without_the_graph(served, monkeypatch, reason):
    G.use(monkeypatch, G.FakeGraph({"walk_round": neo4j_db.Skipped(reason)}))
    _forced(monkeypatch, "R3")

    ranked, stats = _run()
    plain, _ = _run(graph_strategies=[])

    assert stats["graph_walk"]["skip_reason"] == reason and stats["graph_walk"]["passages"] == []
    assert [c["id"] for c in ranked] == [c["id"] for c in plain]
    assert stats["strategy_errors"] == {}


def test_a_timeout_in_the_walk_skips_the_card_of_that_question_without_asking_again(served, monkeypatch):
    graph = G.use(monkeypatch, G.FakeGraph({"walk_round": neo4j_db.Skipped(neo4j_db.TIMEOUT)}))
    _forced(monkeypatch, "R3")

    _, stats = _run()

    assert graph.names() == ["walk_round"]
    assert stats["kin_card"]["skip_reason"] == neo4j_db.TIMEOUT and stats["kin_card"]["text"] is None


def test_a_card_that_fails_midway_gives_no_card(served, monkeypatch):
    G.use(monkeypatch, G.FakeGraph({"walk_round": [WALKED], "kin_persons": [PERSON],
                                    "kin_up": neo4j_db.Skipped(neo4j_db.TIMEOUT)}))
    _forced(monkeypatch, "R3")

    ranked, stats = _run()

    assert stats["kin_card"]["text"] is None and stats["kin_card"]["skip_reason"] == neo4j_db.TIMEOUT
    assert not [c for c in ranked if c["source_strategy"] == "kin_evidence"]


def test_a_bug_in_the_walk_does_not_fail_the_request(served, monkeypatch):
    G.use(monkeypatch, G.FakeGraph({"walk_round": [{"unexpected": 1}], "kin_persons": [PERSON], "kin_up": [PATH]}))
    _forced(monkeypatch, "R3")

    ranked, stats = _run()

    assert stats["graph_walk"]["skip_reason"] == "error" and ranked


def test_a_bug_before_the_walk_does_not_fail_the_request(served, monkeypatch):
    def broken(*args):
        raise KeyError("a bug")
    monkeypatch.setattr(graph_stage.kin_card, "wants", broken)
    G.use(monkeypatch, G.FakeGraph())
    _forced(monkeypatch, "R3")

    ranked, stats = _run()

    assert ranked and stats["graph_walk"]["skip_reason"] == "error" and stats["kin_card"]["skip_reason"] == "error"


@pytest.mark.parametrize("state, reason", [("unavailable", "unavailable"), ("mismatch", "mismatch")])
def test_a_graph_that_is_not_ready_is_not_walked(served, monkeypatch, state, reason):
    graph = G.use(monkeypatch, G.FakeGraph({"walk_round": [WALKED]}),
                  status=G.serving_graph.GraphStatus(state, "why"))
    _forced(monkeypatch, "R3")

    _, stats = _run()

    assert graph.calls == []
    assert stats["graph_walk"]["skip_reason"] == reason and stats["kin_card"]["skip_reason"] == reason


# --- /api/v1/query ------------------------------------------------------------------------------

@pytest.fixture
def http(served, monkeypatch):
    seen = {"chats": []}

    def intent(question):
        return {"type": "person", "verse_refs": [], "rejected_refs": []}

    class FakeLlm:
        async def chat(self, messages, temperature, max_tokens):
            seen["chats"].append(messages)
            return "答案：基士"

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(generator, "get_llm_client", lambda: FakeLlm())
    _forced(monkeypatch, "R3")
    return TestClient(main.app), seen


def _ask(client, question=KIN_QUESTION, **payload):
    return client.post("/api/v1/query", json={"question": question, "include_context": True, **payload})


def test_the_card_reaches_the_prompt_the_response_and_the_trace(http, monkeypatch):
    client, seen = http
    _full(monkeypatch)

    body = _ask(client).json()

    card = body["aux_card"]
    assert card["kind"] == "kin" and "基士 是 掃羅 的父母之一（撒母耳記上 9:2）" in card["text"]
    assert card["evidence"] == ["1sa.9.2"] and card["kings"] == ["e000001"] and card["seeds"] == ["掃羅"]
    assert card["layer_sha256"] == G.KG.sha256 and card["seed_source"] == "rule"
    context_text = "\n\n".join(s["context"] for s in body["sources"])
    assert seen["chats"] == [generator.build_messages(KIN_QUESTION, context_text, card["text"])]
    ops = {op["op"]: op for op in body["graph_trace"]}
    assert ops["kin_card"]["injected"] == "prompt" and ops["kin_card"]["hops"] == 1
    assert ops["kin_card"]["edges"] == [["e000002", "PARENT_OF", "e000001", "1sa.9.2"]]
    assert ops["kin_card"]["names"] == ["基士", "掃羅"]
    assert "ps:1sa.9.1" in ops["kin_card"]["passages"]
    assert ops["graph_walk"]["seeds"][0] == "ps:act.9.1" and ops["graph_walk"]["names"] == ["掃羅"]
    assert ops["graph_walk"]["n_cypher"] == 2 and ops["graph_walk"]["injected"] == "context"
    assert "ps:walked" in ops["graph_walk"]["walked"]
    assert body["retrieval_stats"]["kin_card"]["text"] == card["text"]


def test_no_edge_leaves_the_prompt_exactly_as_it_is_without_a_graph(http, monkeypatch):
    client, seen = http
    G.use(monkeypatch, G.FakeGraph({"walk_round": [{"names": [], "hits": [], "parallel": []}],
                                    "kin_persons": [PERSON]}))

    body = _ask(client).json()

    assert body["aux_card"] is None
    context_text = "\n\n".join(s["context"] for s in body["sources"])
    assert seen["chats"] == [generator.build_messages(KIN_QUESTION, context_text)]
    assert seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT


def test_retrieval_only_builds_the_card_for_the_stats_and_no_prompt_holds_it(http, monkeypatch):
    client, seen = http
    _full(monkeypatch)

    body = _ask(client, retrieval_only=True).json()

    assert body["answer"] == "" and seen["chats"] == []
    assert body["aux_card"] is None and body["retrieval_stats"]["kin_card"]["text"]
    ops = {op["op"]: op for op in body["graph_trace"]}
    assert ops["kin_card"]["injected"] == "none" and ops["kin_card"]["hops"] == 1


@pytest.mark.parametrize("payload", [{"use_graph": False}, {"semantic_only": True}, {"graph_strategies": []}])
def test_the_ablation_arms_send_no_cypher_through_the_api(http, monkeypatch, payload):
    client, _ = http
    graph = _full(monkeypatch)
    fake_dense(monkeypatch, hits=[cand("ps:a", "semantic")])

    response = _ask(client, **payload)

    body = response.json()
    assert response.status_code == 200 and graph.calls == []
    assert body["aux_card"] is None and body["graph_trace"] == []


def test_neo4j_down_answers_200_with_the_ordinary_prompt(http, monkeypatch):
    client, seen = http
    G.use(monkeypatch, G.FakeGraph({"walk_round": neo4j_db.Skipped(neo4j_db.UNAVAILABLE),
                                    "kin_persons": neo4j_db.Skipped(neo4j_db.SKIPPING)}))

    response = _ask(client)

    body = response.json()
    assert response.status_code == 200 and body["answer"] == "答案：基士" and body["aux_card"] is None
    context_text = "\n\n".join(s["context"] for s in body["sources"])
    assert seen["chats"] == [generator.build_messages(KIN_QUESTION, context_text)]
    ops = {op["op"]: op for op in body["graph_trace"]}
    assert ops["graph_walk"]["skip_reason"] == neo4j_db.UNAVAILABLE and ops["graph_walk"]["injected"] == "none"
    assert ops["kin_card"]["skip_reason"] == neo4j_db.SKIPPING and ops["kin_card"]["injected"] == "none"


def test_a_real_driver_on_a_closed_port_answers_200(http, monkeypatch):
    """The whole way down: the real neo4j_db and the real driver, a port nobody listens on."""
    client, seen = http
    monkeypatch.setattr(neo4j_db.settings, "neo4j_uri", "bolt://127.0.0.1:1")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_user", "neo4j")
    monkeypatch.setattr(neo4j_db.settings, "neo4j_password", "not-a-password")
    monkeypatch.setattr(neo4j_db, "_driver", None)

    response = _ask(client)

    body = response.json()
    assert response.status_code == 200 and body["aux_card"] is None
    assert [op["skip_reason"] for op in body["graph_trace"] if op["op"] == "graph_walk"] == ["unavailable"]



# --- the walk's place in the top-k --------------------------------------------------------------

TWO_WALKED = {"names": [["nm:5a0000000001", "掃羅", 3.0]], "parallel": [],
              "hits": [["ps:act.9.1", 9.0], ["ps:walked", 3.0], ["ps:walked2", 2.0]]}


def _walks_two(monkeypatch) -> G.FakeGraph:
    return G.use(monkeypatch, G.FakeGraph({"walk_round": [TWO_WALKED]}))


def _spans(monkeypatch, **spans):
    """What postgres returns for a walked passage, with the verses it holds."""
    async def fetch_sources(passage_ids, chunk_ids=()):
        return {p: {**cand(p, "x", 0.0), "start_key": spans.get(p.replace("ps:", ""), ("act.9.90", "act.9.90"))[0],
                    "end_key": spans.get(p.replace("ps:", ""), ("act.9.90", "act.9.90"))[1]} for p in passage_ids}
    monkeypatch.setattr(postgres, "fetch_sources", fetch_sources)


def _dense_pair():
    return [cand("ps:act.9.1", start_key="act.9.1", end_key="act.9.2"),
            cand("ps:act.9.3b", start_key="act.9.3b", end_key="act.9.4")]


def test_the_last_of_a_full_top_k_gives_way_to_the_walk(served, monkeypatch, scores):
    """A second hop looks nothing like the question, so the reranker alone never lets it in."""
    _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.8, "ps:walked": 0.1, "ps:walked2": 0.2})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=2)

    assert [c["id"] for c in ranked] == ["ps:act.9.1", "ps:walked2"]


def test_the_reranker_picks_among_the_walk_not_the_walks_own_score(served, monkeypatch, scores):
    _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.8, "ps:walked": 0.3, "ps:walked2": 0.2})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=2)

    assert ranked[-1]["id"] == "ps:walked"


def test_a_passage_only_the_walk_found_already_in_the_top_k_is_its_one_place(served, monkeypatch, scores):
    _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.1, "ps:walked": 0.95, "ps:walked2": 0.2})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=2)

    assert {c["id"] for c in ranked} == {"ps:walked", "ps:act.9.1"}


def test_the_walk_takes_no_place_with_verses_the_rest_already_holds(served, monkeypatch, scores):
    _walks_two(monkeypatch)
    _spans(monkeypatch, walked=("act.9.1", "act.9.2"), walked2=("act.9.1", "act.9.1"))
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.8, "ps:walked": 0.3, "ps:walked2": 0.2})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=2)

    assert [c["id"] for c in ranked] == ["ps:act.9.1", "ps:act.9.3b"]


def test_a_top_k_with_room_needs_no_place_given_up(served, monkeypatch, scores):
    _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.8, "ps:walked": 0.3, "ps:walked2": 0.2})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=5)

    assert {c["id"] for c in ranked} == {"ps:act.9.1", "ps:act.9.3b", "ps:walked", "ps:walked2"}


@pytest.mark.parametrize("strategy", ["chapter_block", "book_anchor", "sql_chapter"])
def test_a_place_a_route_decided_is_not_given_up(strategy):
    ranked = [{"id": "ps:a", "source_strategy": "hybrid_hybrid"}, {"id": "ps:b", "source_strategy": strategy}]
    pool = [*ranked, {"id": "ps:w", "source_strategy": "graph_walk", "found_by": ["graph_walk"], "rerank_score": 0.9}]

    assert graph_walk.with_slot(ranked, pool, 2) == ranked


def test_a_failed_reranker_leaves_the_top_k_as_it_fell_back_to(served, monkeypatch):
    _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())

    def broken(*args, **kwargs):
        raise RuntimeError("cuda")
    monkeypatch.setattr("utils.reranker.rerank", broken)

    ranked, stats = _run(query="掃羅去過哪些地方", top_k=2)

    assert "rerank" in stats["strategy_errors"] and {c["id"] for c in ranked} == {"ps:act.9.1", "ps:act.9.3b"}


def test_the_arm_without_the_walk_keeps_its_top_k(served, monkeypatch, scores):
    graph = _walks_two(monkeypatch)
    _spans(monkeypatch)
    _forced(monkeypatch, "R3", _dense_pair())
    scores.update({"ps:act.9.1": 0.9, "ps:act.9.3b": 0.8})

    ranked, _ = _run(query="掃羅去過哪些地方", top_k=2, graph_strategies=["event_registry"])

    assert graph.calls == [] and [c["id"] for c in ranked] == ["ps:act.9.1", "ps:act.9.3b"]
