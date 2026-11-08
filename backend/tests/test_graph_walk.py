"""The graph walk: its seeds, its two rounds and how its passages join the candidate pool.

The arithmetic is worked by hand on the small graph below; the Cypher itself is compared with a plain
computation on the real graph in test_cypher_live.py.
"""

import asyncio

import pytest

import graph_fakes as G
from config import settings
from database import neo4j_db, postgres
from router_fakes import LEXICON, cand, lexicon_doc
from ragcommon import routing
from utils.retrieval import graph_walk

# 甲 idf 2, 乙 idf 1, 樞 idf 0.5 and too common to walk through
SMALL = G.SmallGraph(
    mentions={"ps:p1": ("nm:a", "nm:hub"), "ps:p2": ("nm:a", "nm:b"), "ps:p3": ("nm:b",), "ps:p4": ("nm:a",)},
    names={"nm:a": ("甲", 3, 2.0), "nm:b": ("乙", 2, 1.0), "nm:hub": ("樞", 151, 0.5)})
SEEDS = (("ps:p1", 1.0), ("ps:p2", 0.5))


def _graph(monkeypatch, small=SMALL) -> G.FakeGraph:
    return G.use(monkeypatch, G.FakeGraph({"walk_round": G.walk_round(small)}))


def _walk(seeds=SEEDS, names=()):
    return asyncio.run(graph_walk.walk(seeds, names, "b1"))


# --- seeds --------------------------------------------------------------------------------------

def test_the_seed_passages_are_the_dense_arms_in_rank_order_with_weight_one_over_rank():
    pool = [cand("ps:a"), cand("ps:b"), cand("ps:c")]

    assert graph_walk.seed_passages(pool) == (("ps:a", 1.0), ("ps:b", 0.5), ("ps:c", 1 / 3))


def test_a_chunk_stands_for_its_passage_and_a_passage_counts_once():
    pool = [cand("ck:x~1", passage_id="ps:x"), cand("ck:x~2", passage_id="ps:x"), cand("ps:y")]

    assert graph_walk.seed_passages(pool) == (("ps:x", 1.0), ("ps:y", 0.5))


def test_only_the_dense_arm_seeds():
    pool = [cand("ps:anchor", "book_anchor"), cand("ps:sql", "sql_supplement"),
            cand("ps:both", "book_anchor", found_by=["hybrid_hybrid", "book_anchor"]), cand("ps:a")]

    assert graph_walk.seed_passages(pool) == (("ps:both", 1.0), ("ps:a", 0.5))


def test_at_most_ten_passages_seed():
    pool = [cand(f"ps:{i}") for i in range(15)]

    seeds = graph_walk.seed_passages(pool)

    assert len(seeds) == settings.walk_seed_passages == 10 and seeds[-1] == ("ps:9", 0.1)


def test_the_seed_names_are_the_lexicons_literal_hits_on_names():
    assert graph_walk.seed_names("掃羅和巴拿巴在耶路撒冷", LEXICON) == (
        "nm:5a0000000001", "nm:5a0000000002", "nm:5a0000000003")


def test_a_question_naming_nothing_has_no_seed_names_and_a_books_name_is_none():
    assert graph_walk.seed_names("約翰福音講什麼", LEXICON) == ()


def test_an_event_term_is_no_seed_name():
    lexicon = routing.parse_lexicon(lexicon_doc())
    assert graph_walk.seed_names("保羅歸主的經過", lexicon) == ()


# --- the two rounds -----------------------------------------------------------------------------

def test_two_rounds_worked_by_hand(monkeypatch):
    """a(甲) = (1 + .5)·2 = 3, a(乙) = .5·1 = .5; s1: p1 6, p2 6.5, p3 .5, p4 6.
    Normalized by p2: a2(甲) = (6/6.5 + 1 + 6/6.5)·2, a2(乙) = (1 + .5/6.5)·1; s = s1 + .5·s2."""
    graph = _graph(monkeypatch)

    walked = _walk()

    assert [p for p, _ in walked.passages] == ["ps:p2", "ps:p1", "ps:p4", "ps:p3"]
    scores = dict(walked.passages)
    assert scores["ps:p2"] == pytest.approx(12.730769, abs=1e-5)
    assert scores["ps:p1"] == scores["ps:p4"] == pytest.approx(11.692308, abs=1e-5)
    assert scores["ps:p3"] == pytest.approx(1.038462, abs=1e-5)
    assert walked.n_cypher == len(graph.calls) == 2 and walked.skip_reason is None


def test_equal_scores_are_ordered_by_id(monkeypatch):
    _graph(monkeypatch)
    order = [p for p, _ in _walk().passages]
    assert order.index("ps:p1") < order.index("ps:p4")


def test_a_hub_name_is_excluded_by_the_templates_parameter(monkeypatch):
    graph = _graph(monkeypatch)

    walked = _walk()

    assert all(params["max_df"] == settings.walk_max_df == 150 for _, params in graph.calls)
    assert "樞" not in [label for _, label in walked.names]


def test_the_question_names_seed_with_weight_one_only_in_the_first_round(monkeypatch):
    graph = _graph(monkeypatch)

    _walk(seeds=(), names=("nm:b",))

    first, second = [params for _, params in graph.calls]
    assert first["names"] == [{"id": "nm:b", "w": 1.0}] and second["names"] == []


def test_a_name_seed_alone_walks_one_hop_then_two(monkeypatch):
    """a(乙) = 1; s1: p2 1, p3 1. Both seed the second round at 1: a2(甲) = 2, a2(乙) = 2, so
    s2: p1 4, p2 6, p3 2, p4 4 and s: p2 4, then p1, p3, p4 tied at 2, in id order."""
    _graph(monkeypatch)
    walked = _walk(seeds=(), names=("nm:b",))
    assert walked.passages == (("ps:p2", 4.0), ("ps:p1", 2.0), ("ps:p3", 2.0), ("ps:p4", 2.0))
    assert walked.hops == 3


def test_the_second_round_seeds_are_the_first_twenty_normalized(monkeypatch):
    many = G.SmallGraph(mentions={f"ps:{i:02d}": ("nm:a",) for i in range(30)}, names={"nm:a": ("甲", 30, 2.0)})
    graph = _graph(monkeypatch, many)

    _walk(seeds=(("ps:00", 1.0),))

    _, second = graph.calls
    seeds = second[1]["seeds"]
    assert len(seeds) == settings.walk_round2_seeds == 20
    assert seeds[0] == {"id": "ps:00", "w": 1.0} and all(s["w"] == 1.0 for s in seeds)
    assert second[1]["parallel"] == []


def test_at_most_walk_k_passages_come_back(monkeypatch):
    many = G.SmallGraph(mentions={f"ps:{i:02d}": ("nm:a",) for i in range(30)}, names={"nm:a": ("甲", 30, 2.0)})
    _graph(monkeypatch, many)

    assert len(_walk(seeds=(("ps:00", 1.0),)).passages) == settings.walk_k == 10


def test_at_most_thirty_names_are_taken(monkeypatch):
    graph = _graph(monkeypatch)
    _walk()
    assert all(params["top_names"] == settings.walk_top_names == 30 for _, params in graph.calls)


def test_a_parallel_pericopes_passage_gets_half_the_seeds_weight(monkeypatch):
    small = G.SmallGraph(mentions={"ps:seed": ()}, names={}, parallel={"ps:seed": ("ps:other",)})
    graph = _graph(monkeypatch, small)

    walked = _walk(seeds=(("ps:seed", 0.5),))

    assert graph.calls[0][1]["parallel"] == [{"id": "ps:seed", "w": 0.5}]
    assert dict(walked.passages) == {"ps:other": pytest.approx(0.25)}


def test_each_passage_says_how_many_edges_reached_it(monkeypatch):
    """Passage-name-passage from a seed: 2; round two from there: 4; a seed's parallel passage: 3."""
    small = G.SmallGraph(mentions={"ps:p1": ("nm:a",), "ps:p2": ("nm:a", "nm:b"), "ps:p3": ("nm:b",)},
                         names={"nm:a": ("甲", 2, 2.0), "nm:b": ("乙", 2, 1.0)},
                         parallel={"ps:p1": ("ps:p9",)})
    _graph(monkeypatch, small)

    walked = _walk(seeds=(("ps:p1", 1.0),))

    reach = dict(walked.reach)
    assert reach["ps:p2"] == 2 and reach["ps:p3"] == 4 and reach["ps:p9"] == 3


def test_a_name_of_the_question_reaches_its_passages_in_one_edge(monkeypatch):
    _graph(monkeypatch)
    assert dict(_walk(seeds=(), names=("nm:b",)).reach)["ps:p2"] == 1


def test_hops_are_the_edges_actually_crossed(monkeypatch):
    _graph(monkeypatch)
    assert _walk().hops == 4                                # passage-name-passage, twice
    small = G.SmallGraph(mentions={"ps:seed": ()}, names={}, parallel={"ps:seed": ("ps:other",)})
    _graph(monkeypatch, small)
    assert _walk(seeds=(("ps:seed", 1.0),)).hops == 3       # pericope, PARALLEL, pericope


def test_nothing_to_start_from_sends_no_cypher(monkeypatch):
    graph = _graph(monkeypatch)

    walked = _walk(seeds=(), names=())

    assert graph.calls == [] and walked.passages == () and walked.hops == 0 and walked.n_cypher == 0


def test_the_walk_records_its_seeds_and_names(monkeypatch):
    _graph(monkeypatch)

    walked = _walk(names=("nm:b",))

    assert walked.seeds == ("ps:p1", "ps:p2", "nm:b")
    assert walked.names == (("nm:a", "甲"), ("nm:b", "乙"))


def test_the_same_walk_gives_the_same_answer(monkeypatch):
    _graph(monkeypatch)
    assert _walk().passages == _walk().passages


# --- joining the pool ---------------------------------------------------------------------------

@pytest.fixture
def fetched(monkeypatch):
    calls = []

    async def fetch_sources(passage_ids, chunk_ids=()):
        calls.append(list(passage_ids))
        return {p: cand(p, "x", 0.0) for p in passage_ids}
    monkeypatch.setattr(postgres, "fetch_sources", fetch_sources)
    return calls


def _absorb(pool, weights, label="graph_walk"):
    errors: dict[str, str] = {}
    asyncio.run(graph_walk.absorb(pool, weights, label, errors))
    return errors


def test_every_walked_passage_joins_at_the_one_weight_below_the_dense_arm():
    """A prior above dense's 0.65 moved passages the reranker scored low into the top-k: the walk finds, the
    reranker decides."""
    weights = graph_walk.walk_weights(((("ps:a", 10.0)), ("ps:b", 5.0), ("ps:c", 0.0)))
    assert set(weights.values()) == {settings.walk_weight} and settings.walk_weight < 0.65
    assert graph_walk.walk_weights(()) == {}


def test_a_walked_passage_already_in_the_pool_keeps_its_weight(fetched):
    pool = [cand("ps:a", weight=0.7)]

    _absorb(pool, graph_walk.walk_weights((("ps:a", 10.0),)))

    assert pool[0]["weight"] == 0.7 and "graph_walk" in pool[0]["found_by"]


def test_a_walked_passage_not_in_the_pool_is_fetched_and_added(fetched):
    pool = [cand("ps:a")]

    errors = _absorb(pool, {"ps:new": 0.8})

    assert fetched == [["ps:new"]] and errors == {}
    assert [c["id"] for c in pool] == ["ps:a", "ps:new"]
    assert pool[1]["source_strategy"] == "graph_walk" and pool[1]["weight"] == 0.8
    assert pool[1]["found_by"] == ["graph_walk"]


def test_a_passage_in_the_pool_is_noted_and_its_weight_only_rises(fetched):
    pool = [cand("ps:low", weight=0.6), cand("ps:high", weight=0.85)]

    _absorb(pool, {"ps:low": 0.8, "ps:high": 0.8})

    assert fetched == []
    assert [c["weight"] for c in pool] == [0.8, 0.85]
    assert pool[0]["found_by"] == ["hybrid_hybrid", "graph_walk"]
    assert pool[0]["source_strategy"] == "hybrid_hybrid"


def test_a_chunk_of_the_walked_passage_counts_as_in_the_pool(fetched):
    pool = [cand("ck:x~1", weight=0.65, passage_id="ps:x")]

    _absorb(pool, {"ps:x": 0.9})

    assert fetched == [] and len(pool) == 1
    assert pool[0]["weight"] == 0.9 and "graph_walk" in pool[0]["found_by"]


def test_only_one_copy_of_a_passage_is_lifted_the_passage_itself_first(fetched):
    pool = [cand("ck:x~1", weight=0.65, passage_id="ps:x"), cand("ps:x", weight=0.7, passage_id="ps:x"),
            cand("ck:x~2", weight=0.65, passage_id="ps:x")]

    _absorb(pool, {"ps:x": 0.9})

    assert [c["weight"] for c in pool] == [0.65, 0.9, 0.65]


def test_of_several_chunks_only_the_first_is_lifted(fetched):
    pool = [cand("ck:x~1", weight=0.65, passage_id="ps:x"), cand("ck:x~2", weight=0.65, passage_id="ps:x")]

    _absorb(pool, {"ps:x": 0.9})

    assert [c["weight"] for c in pool] == [0.9, 0.65]
    assert "graph_walk" in pool[0]["found_by"] and "graph_walk" not in pool[1].get("found_by", [])


def test_a_store_that_fails_is_a_strategy_error_and_the_pool_stays(monkeypatch):
    async def down(passage_ids, chunk_ids=()):
        raise ConnectionError("pg")
    monkeypatch.setattr(postgres, "fetch_sources", down)
    pool = [cand("ps:a")]

    errors = _absorb(pool, {"ps:new": 0.8})

    assert [c["id"] for c in pool] == ["ps:a"] and "graph_walk" in errors


def test_neo4j_not_answering_is_a_skip_reason_with_the_queries_that_went_out(monkeypatch):
    def second_round_times_out(params):
        if not params["names"] and not params["parallel"]:
            raise neo4j_db.Skipped(neo4j_db.TIMEOUT)
        return G.walk_round(SMALL)(params)
    graph = G.use(monkeypatch, G.FakeGraph({"walk_round": second_round_times_out}))

    walked = _walk()

    assert walked.skip_reason == neo4j_db.TIMEOUT and walked.passages == () and walked.n_cypher == 2
    assert len(graph.calls) == 2


def test_neo4j_already_being_skipped_sends_nothing(monkeypatch):
    G.use(monkeypatch, G.FakeGraph({"walk_round": neo4j_db.Skipped(neo4j_db.SKIPPING)}))

    walked = _walk()

    assert walked.skip_reason == neo4j_db.SKIPPING and walked.n_cypher == 0
