"""graph_trace: what a request's graph side did, one entry per operation that ran.

The lanes and cards themselves are tested elsewhere (test_event_registry, test_regnal_card,
test_gen_card); this is only the record of them. /query's arms are in test_gen_card.
"""

from __future__ import annotations

import gen_fakes as F
from test_gen_card import BUILD
from test_regnal_card import _layer_doc

import json

from serving import context
from serving.handshake import Handshake
from router_fakes import LEXICON
from utils import gen_card, gencard, graph_trace
from utils.regnal.card import card_from_rule
from utils.regnal.layer import parse_layer


def _regnal():
    return parse_layer(json.dumps(_layer_doc(), ensure_ascii=False, indent=1).encode("utf-8"))


def _gen():
    layer, names = F.files()
    return gen_card.parse_files(layer, names)


def _serve(regnal=None, gen=None):
    context.install(context.make_active(BUILD, LEXICON, (), regnal, gen),
                    Handshake(BUILD.build_id, (), True))


def teardown_function():
    context.reset()


NEW_FIELDS = {"seeds", "names", "walked", "confirmed", "n_cypher", "ms", "skip_reason"}


def test_a_request_whose_graph_side_did_nothing_has_an_empty_trace():
    _serve()
    assert graph_trace.of({"event_registry_events": []}, [{"id": "ps:a"}], None) == []
    assert graph_trace.of({}, [], None) == []


def test_an_appended_event_anchor_is_one_hop_into_the_context():
    _serve()
    results = [{"id": "ps:a", "source_strategy": "semantic"},
               {"id": "ps:b", "source_strategy": "event_registry", "via_event_id": "ev0001"}]

    [op] = graph_trace.of({"event_registry_events": ["ev0001", "ev0002"]}, results, None)

    assert op.model_dump(exclude=NEW_FIELDS) == {
        "op": "event_registry", "hops": 1, "nodes": ["ev0001", "ev0002"],
        "edges": [["ev0001", "anchor", "ps:b"]], "injected": "context", "passages": ["ps:b"]}


def test_an_event_that_fired_without_appending_is_recorded_as_not_injected():
    """The anchors were already in the top-k: it ran, it changed nothing."""
    _serve()

    [op] = graph_trace.of({"event_registry_events": ["ev0001"]}, [{"id": "ps:a"}], None)

    assert (op.op, op.hops, op.nodes, op.edges, op.injected, op.passages) == (
        "event_registry", 0, ["ev0001"], [], "none", [])


def test_a_regnal_card_records_the_chain_it_walked():
    layer = _regnal()
    _serve(regnal=layer)
    card = card_from_rule(layer, ("A00",))         # 暗利 -> 亞哈 -> 亞哈謝

    [op] = graph_trace.of({}, [], card)

    assert op.model_dump(exclude=NEW_FIELDS) == {
        "op": "regnal_card", "hops": 2, "nodes": ["A00", "A01", "A02"],
        "edges": [["A00", "son", "A01"], ["A01", "son", "A02"]], "injected": "prompt", "passages": []}


def test_a_regnal_card_counts_hops_within_each_kingdom():
    """Two seeds of different kingdoms have no distance between them."""
    layer = _regnal()
    _serve(regnal=layer)
    card = card_from_rule(layer, ("A01", "A03"))   # 亞哈 (Israel), 約沙法 (Judah)

    [op] = graph_trace.of({}, [], card)

    assert op.hops == 1
    assert ["A03", "son", "A04"] in op.edges and set(op.nodes) >= {"A01", "A03"}


def test_hops_is_each_seeds_own_reach_not_the_nearest_seeds():
    """暗利's card reads two successors though 亞哈, one of them, is a seed too."""
    layer = _regnal()
    _serve(regnal=layer)

    [op] = graph_trace.of({}, [], card_from_rule(layer, ("A00", "A01")))

    assert op.hops == 2


def test_a_gen_card_counts_the_walk_from_the_flood_anchor():
    """Chapter 11's flood line adds up from the anchor row to the seed, past the seeds' distance."""
    def anchored(doc):
        next(n for n in doc["nodes"] if n["id"] == "G11.00")["flood_offset"] = [2, "syn.11.0"]

    layer = gen_card.parse_files(*F.files(layer_edit=anchored))
    _serve(gen=layer)
    card = gencard.card_for_seeds(("G11.01", "G11.02"), layer)

    [op] = graph_trace.of({}, [], card)

    assert any(tag[0] == "flood" for tag in card.tags) and op.hops == 2


def test_a_gen_card_records_the_distance_between_its_seeds():
    layer = _gen()
    _serve(gen=layer)
    card = gen_card.card_of(F.FIRES, layer)        # G05.00 and G05.02, two generations apart

    [op] = graph_trace.of({}, [], card)

    assert (op.op, op.hops, op.injected, op.passages) == ("gen_card", 2, "prompt", [])
    assert set(op.nodes) >= set(F.FIRES_SEEDS)
    assert ["G05.00", "son", "G05.01"] in op.edges and ["G05.01", "son", "G05.02"] in op.edges


def test_event_anchor_and_card_are_two_entries_in_order():
    layer = _gen()
    _serve(gen=layer)
    results = [{"id": "ps:b", "source_strategy": "event_registry", "via_event_id": "ev0001"}]

    trace = graph_trace.of({"event_registry_events": ["ev0001"]}, results, gen_card.card_of(F.FIRES, layer))

    assert [op.op for op in trace] == ["event_registry", "gen_card"]


WALK_STATS = {"seeds": ["ps:a", "nm:x"], "name_ids": ["nm:x"], "names": ["甲"],
              "passages": [["ps:a", 9.0], ["ps:b", 3.0]], "hops": 4, "n_cypher": 2, "ms": 3.5, "skip_reason": None}
KIN_STATS = {"text": "卡", "seeds": ["甲"], "persons": ["e1"], "nodes": ["e2", "e1"], "names": ["乙", "甲"],
             "edges": [["e2", "PARENT_OF", "e1", "gen.1.1"]], "hops": 1, "lines": 1, "evidence": ["gen.1.1"],
             "passages": ["ps:gen.1.1"], "n_cypher": 3, "ms": 1.5, "skip_reason": None}


def test_a_walk_records_its_seeds_names_and_the_passages_it_added_to_the_top_k():
    _serve()
    results = [{"id": "ps:b", "source_strategy": "graph_walk", "found_by": ["graph_walk"]},
               {"id": "ps:c", "source_strategy": "semantic", "found_by": ["semantic"]}]

    [op] = graph_trace.of({"graph_walk": WALK_STATS}, results, None)

    assert op.model_dump() == {
        "op": "graph_walk", "hops": 4, "nodes": ["nm:x", "ps:a", "ps:b"], "edges": [], "injected": "context",
        "passages": ["ps:b"], "confirmed": [], "seeds": ["ps:a", "nm:x"], "names": ["甲"],
        "walked": ["ps:a", "ps:b"], "n_cypher": 2, "ms": 3.5, "skip_reason": None}


def test_a_walked_passage_dense_had_found_anyway_is_no_injection():
    """The top-k would be what it is without the walk."""
    _serve()
    results = [{"id": "ps:b", "source_strategy": "hybrid_hybrid", "found_by": ["hybrid_hybrid", "graph_walk"]}]

    [op] = graph_trace.of({"graph_walk": WALK_STATS}, results, None)

    assert op.injected == "none" and op.passages == [] and op.confirmed == ["ps:b"]


def test_a_chunk_of_a_walked_passage_counts_as_that_passage():
    """absorb marks only the passage's first chunk; another chunk in the top-k is still that passage."""
    _serve()
    results = [{"id": "ck:b~2", "passage_id": "ps:b", "source_strategy": "semantic", "found_by": ["semantic"]}]

    [op] = graph_trace.of({"graph_walk": WALK_STATS}, results, None)

    assert op.confirmed == ["ck:b~2"] and op.injected == "none"


def test_the_hops_of_a_walk_that_added_a_passage_are_how_far_that_passage_was():
    _serve()
    stats = {**WALK_STATS, "reach": {"ps:a": 2, "ps:b": 1}}
    results = [{"id": "ps:b", "source_strategy": "graph_walk", "found_by": ["graph_walk"]}]

    [op] = graph_trace.of({"graph_walk": stats}, results, None)

    assert op.hops == 1


def test_a_walk_that_reached_no_top_k_is_not_injected():
    _serve()
    [op] = graph_trace.of({"graph_walk": WALK_STATS}, [{"id": "ps:c", "found_by": ["semantic"]}], None)
    assert op.injected == "none" and op.passages == [] and op.walked == ["ps:a", "ps:b"]


def test_a_card_nobody_generated_with_went_to_no_prompt():
    _serve()
    [op] = graph_trace.of({"kin_card": KIN_STATS}, [], None, generated=False)
    assert op.injected == "none"


def test_a_skipped_walk_says_why_and_counts_as_no_hops():
    _serve()
    skipped = {**WALK_STATS, "seeds": [], "name_ids": [], "names": [], "passages": [], "hops": 0, "n_cypher": 0,
               "ms": 0.0, "skip_reason": "unavailable"}
    [op] = graph_trace.of({"graph_walk": skipped}, [], None)
    assert (op.skip_reason, op.hops, op.injected) == ("unavailable", 0, "none")


def test_a_kinship_card_records_its_edges_with_verses_and_goes_to_the_prompt():
    _serve()
    results = [{"id": "ps:gen.1.1", "found_by": ["kin_evidence"]}]

    [op] = graph_trace.of({"kin_card": KIN_STATS}, results, None)

    assert op.model_dump() == {
        "op": "kin_card", "hops": 1, "nodes": ["e2", "e1"], "edges": [["e2", "PARENT_OF", "e1", "gen.1.1"]],
        "injected": "prompt", "passages": ["ps:gen.1.1"], "confirmed": [], "seeds": [], "names": ["乙", "甲"], "walked": [],
        "n_cypher": 3, "ms": 1.5, "skip_reason": None}


def test_a_kinship_question_with_no_card_says_why_and_reaches_nothing():
    _serve()
    none = {**KIN_STATS, "text": None, "nodes": [], "names": [], "edges": [], "hops": 0, "skip_reason": "no_edge"}
    [op] = graph_trace.of({"kin_card": none}, [], None)
    assert (op.injected, op.skip_reason) == ("none", "no_edge")


def test_the_trace_lists_retrieval_before_the_cards():
    _serve(gen=_gen())
    card = gen_card.card_of(F.FIRES, context.active().gen)
    ops = graph_trace.of({"event_registry_events": ["ev1"], "graph_walk": WALK_STATS}, [], card)
    assert [op.op for op in ops] == ["event_registry", "graph_walk", "gen_card"]
