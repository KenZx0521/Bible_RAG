"""QD experiment (experiments/2026-10-18_graph_qd, plan.md §2–§4): the pure selection rules.

Small synthetic graphs drive the names line of the prompt, PPR over every node (its passage
part must equal GD arms.ppr), the QD+G / QD+N name pickers and their shared exclusions, the
appended-passage pools and tie-break, the Ollama-failure rule for decompositions and the
W≥2L, W−L≥4 gate. With the store mounted, the real kg0 hub list and the NEW82 C5 are checked.
"""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_graph_qd"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

needs_store = pytest.mark.skipif(
    not Path("/mnt/ollama-data/bible_rag_store/layers").is_dir(), reason="store not mounted")

qd = pytest.importorskip("qd_common") if Path("/mnt/ollama-data/bible_rag_store").is_dir() else None
pytestmark = pytest.mark.skipif(qd is None, reason="store not mounted (qd_common pins store files)")

BASE = "問題：{question}\n\n目前已取得的經文段落：\n{context}\n\n---\n回答這個問題需要…"


def graph():
    """Passages A–E; names: 甲乙 in A,B; 丙丁 in B,C; 戊己 in C; 庚辛 in E; 但 in B; 大衛 (hub) in
    B,C; 問名 (question name) in C; 只甲 in A only. D has no name (dangling)."""
    edges = {("A", "甲乙"), ("B", "甲乙"), ("B", "丙丁"), ("C", "丙丁"), ("C", "戊己"),
             ("E", "庚辛"), ("B", "但"), ("B", "大衛"), ("C", "大衛"), ("C", "問名"), ("A", "只甲")}
    return qd.gd_arms.build_bip(["A", "B", "C", "D", "E"], edges)


KG0 = {"甲乙": 5, "丙丁": 5, "戊己": 2, "庚辛": 1, "但": 40, "大衛": 1048, "問名": 3, "只甲": 1}


# ------------------------------------------------------------------ prompt names line

def test_names_template_adds_one_line_between_context_and_separator():
    t = qd.names_template(BASE)
    assert "{context}\n\n可能相關名稱：{names}\n\n---\n" in t
    assert t.replace("可能相關名稱：{names}\n\n", "") == BASE


def test_names_template_refuses_a_template_without_the_anchor_once():
    with pytest.raises(qd.QdError):
        qd.names_template("問題：{question}\n{context}\n---")
    with pytest.raises(qd.QdError):
        qd.names_template(BASE + "\n{context}\n\n---\n")


def test_user_template_for_no_names_is_the_frozen_template():
    assert qd.user_template_for(BASE, ()) == BASE


def test_user_template_for_joins_names_with_a_dun():
    t = qd.user_template_for(BASE, ("甲乙", "丙丁"))
    assert "可能相關名稱：甲乙、丙丁\n\n---" in t and "{question}" in t and "{context}" in t


# ------------------------------------------------------------------ the graph ranking around C5

def test_ppr_ranking_is_gd_ppr_order_from_c5_and_drops_unreached_passages():
    g = graph()
    want = qd.gd_arms.ppr_order(qd.gd_arms.ppr(g, {g.row["A"]: 1.0}))
    assert qd.ppr_ranking(g, ("A",)) == tuple(g.passages[i] for i in want)
    assert qd.ppr_ranking(g, ("A",))[0] == "A" and "E" not in qd.ppr_ranking(g, ("A",))


def test_c5_seeds_weigh_by_rank():
    g = graph()
    assert qd.c5_seeds(g, ("A", "C")) == {g.row["A"]: 1.0, g.row["C"]: 0.5}


def test_names_by_passage_reads_the_bip_edges():
    by = qd.names_by_passage(graph())
    assert by["A"] == {"甲乙", "只甲"} and by["D"] == frozenset()


# ------------------------------------------------------------------ name pickers

def test_eligible_drops_short_hub_unknown_and_excluded_names():
    assert qd.is_eligible("甲乙", KG0, frozenset())
    assert not qd.is_eligible("但", KG0, frozenset())           # one character
    assert not qd.is_eligible("大衛", KG0, frozenset())         # kg0 body_occurrences > 300
    assert not qd.is_eligible("不在", KG0, frozenset())         # not a kg0 name
    assert not qd.is_eligible("甲乙", KG0, frozenset({"甲乙"}))  # question or C5 name


def test_graph_names_are_ranked_names_of_the_ppr_ranking_minus_context_names():
    g = graph()
    exclude = qd.context_exclusions(g, ("A",), ("問名",))
    assert exclude == {"甲乙", "只甲", "問名"}
    got = qd.graph_names(g, ("A",), KG0, exclude)
    assert got == qd.ranked_names(g, qd.c5_first(("A",), qd.ppr_ranking(g, ("A",))), ("A",), KG0, exclude)
    # ranking A, B, C: 丙丁 from B (1/2) and C (1/3), 戊己 from C only; 庚辛 (E) unreached
    assert got == ("丙丁", "戊己")


def test_ranked_names_use_only_the_first_30_passages():
    g = qd.gd_arms.build_bip([f"p{i}" for i in range(32)], {("p31", "遠名"), ("p0", "近名")})
    ranking = tuple(f"p{i}" for i in range(32))
    assert qd.ranked_names(g, ranking, ("p5",), {"遠名": 1, "近名": 1}, frozenset()) == ("近名",)


def test_dense_names_score_is_idf_times_reciprocal_rank_after_c5():
    g = graph()
    d30 = ("C", "A", "B", "E")                 # dense order; C5 = (A,) moves to the front
    exclude = qd.context_exclusions(g, ("A",), ())
    got = qd.dense_names(g, d30, ("A",), KG0, exclude, n=5)
    # ranking A, C, B, E: C at 1 (1/2), B at 2 (1/3), E at 3 (1/4)
    s = {"丙丁": math.log(5 / 2) * (1 / 2 + 1 / 3), "戊己": math.log(5 / 1) * (1 / 2),
         "庚辛": math.log(5 / 1) * (1 / 4), "問名": math.log(5 / 1) * (1 / 2)}
    want = tuple(n for _, n in sorted((-round(v, 12), n) for n, v in s.items()))
    assert got == want


def test_c5_first_moves_c5_to_the_front_in_its_own_order():
    assert qd.c5_first(("B", "A"), ("X", "A", "Y", "B", "Z")) == ("B", "A", "X", "Y", "Z")


def test_eligible_names_keep_link_order_and_the_shared_exclusions():
    got = qd.eligible_names(["大衛", "甲乙", "丙丁", "甲乙", "戊己"], KG0, frozenset({"丙丁"}), n=5)
    assert got == ("甲乙", "戊己")


def test_pickers_cut_at_n_and_break_ties_by_name():
    g = qd.gd_arms.build_bip(["A", "B"], {("A", "乙乙"), ("B", "甲甲"), ("B", "丙丙"), ("A", "種子")})
    kg0 = {"甲甲": 1, "乙乙": 1, "丙丙": 1, "種子": 1}
    got = qd.dense_names(g, ("A", "B"), ("A",), kg0, frozenset({"種子", "乙乙"}), n=1)
    assert got == ("丙丙",)


# ------------------------------------------------------------------ pools and the appended passage

def test_pool_is_first_n_outside_c5():
    assert qd.pool_of(["A", "X", "B", "Y", "Z"], ("A", "B"), n=2) == ("X", "Y")


def test_deep_pool_is_the_first_50_minus_c5():
    rank = [f"p{i}" for i in range(60)]
    pool = qd.deep_pool(rank, ("p0", "p55"))
    assert len(pool) == 49 and "p49" in pool and "p50" not in pool


def test_pick_takes_highest_score_then_smallest_pid():
    assert qd.pick(("B", "A", "C"), {"A": 0.5, "B": 0.5, "C": 0.1}) == "A"


# ------------------------------------------------------------------ decompositions and the gate

def _dec(fallback, *errors):
    return {"type": "dec", "fallback": fallback, "attempts": [{"error": e} for e in errors]}


def test_an_ollama_failure_fallback_is_not_a_result():
    assert not qd.dec_is_result(_dec(True, "ReadTimeout()", "ConnectError()"))
    assert not qd.dec_is_result(_dec(True, None, "ReadTimeout()"))


def test_a_model_fallback_or_a_recovered_call_is_a_result():
    assert qd.dec_is_result(_dec(True, None, None))
    assert qd.dec_is_result(_dec(False, "ReadTimeout()", None))


@pytest.mark.parametrize("w,l,mean,ok", [(4, 0, 0.1, True), (8, 4, 0.01, True), (3, 0, 0.2, False),
                                         (7, 4, 0.1, False), (6, 2, 0.0, False), (12, 6, 0.05, True)])
def test_gate_needs_w_at_least_2l_and_4_more_wins_and_positive_mean(w, l, mean, ok):
    assert qd.gate_pass({"unit_W": w, "unit_L": l, "mean_unit_diff": mean}) is ok


# ------------------------------------------------------------------ the real store

@needs_store
def test_kg0_hubs_are_the_14_names_over_300():
    occ = qd.load_kg0_occurrences()
    hubs = sorted(n for n, c in occ.items() if c > qd.HUB_OCC)
    assert len(occ) == 2926 and len(hubs) == 14 and "以色列" in hubs and "非利士" in hubs


@needs_store
def test_new82_c5_matches_the_it_host_c5():
    inp = qd.load_step1_inputs()
    assert len(inp.c5) == 82
    assert inp.c5["N_KIN_01"] == ("ps:num.16.1", "ps:1ch.23.2", "ps:num.26.1", "ps:exo.6.14", "ps:num.4.34")


# ------------------------------------------------------------------ qd_eval verdict M

@pytest.mark.parametrize("sum_v,p,w,l,ok", [("3/2", "1/8", 4, 1, True), ("3/2", "1/4", 4, 1, False),
                                            ("-1", "1/16", 4, 1, False), ("1", "1/16", 2, 2, False),
                                            ("0", "1", 0, 0, False)])
def test_m_needs_positive_direction_one_sided_p_below_010_and_w_at_least_2l(sum_v, p, w, l, ok):
    ev = pytest.importorskip("qd_eval")
    assert ev.m_pass({"sum_v": sum_v, "p_exact": p, "unit_W": w, "unit_L": l}) is ok
