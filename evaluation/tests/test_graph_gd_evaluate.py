"""GD experiment metrics and tests (experiments/2026-10-14_graph_gd/evaluate.py).

Unit tests drive the §5 statistics (sign-flip DP against brute force, the Monte Carlo
fallback against ab_stats' draw, union-find, Δ̄ and W:L, the Holm gate), the §3 top-k
tie rule, §4 f(q) and the CLI's exit code on a locked set. The lists / scores inputs and
their provenance are in test_graph_gd_evaluate_inputs.py, E2 / V1 / D5≈ / [SHORTCUT] in
test_graph_gd_evaluate_e2.py, and the store-backed checks (archived NEW82 numbers,
acceptance B, the arms.py lists joined with the archived scores) in
test_graph_gd_evaluate_store.py.
"""

import importlib.util
import itertools
import random
import subprocess
import sys
from fractions import Fraction as F
from pathlib import Path

import pytest

from src.ab_stats import sign_flip_p

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
_SPEC_EV = importlib.util.spec_from_file_location("gd_evaluate", _DIR / "evaluate.py")
ev = importlib.util.module_from_spec(_SPEC_EV)
sys.modules["gd_evaluate"] = ev          # dataclasses resolve annotations through sys.modules
_SPEC_EV.loader.exec_module(ev)
st, M, acc = ev.st, ev.M, ev.acc

def brute_force_p(values):
    nz = [F(v) for v in values if v != 0]
    t = abs(sum(nz))
    hits = sum(abs(sum(s * v for s, v in zip(signs, nz))) >= t
               for signs in itertools.product((1, -1), repeat=len(nz)))
    return F(hits, 2 ** len(nz))


# ---------------------------------------------------------------- sign-flip (§5)

@pytest.mark.parametrize("seed", range(12))
def test_exact_dp_equals_brute_force_on_fractions_with_zero_units(seed):
    rng = random.Random(seed)
    values = [F(rng.randint(-6, 6), rng.choice((1, 2, 3, 4, 5, 6, 12))) for _ in range(rng.randint(1, 11))]
    values += [F(0)] * rng.randint(0, 3)
    res = st.sign_flip(values)
    assert res.method in ("exact_dp", "no_discordant_unit")
    assert res.p == (brute_force_p(values) if any(values) else 1)
    assert res.n_nonzero == sum(v != 0 for v in values)


def test_sign_flip_p_matches_the_review_numbers_for_eleven_wins():
    assert st.sign_flip([F(1, 12)] * 11 + [F(0)] * 29).p == F(1, 1024)


def test_sign_flip_threshold_is_exact_not_tolerant():
    # |±1/3 ± 1/3 ± 1/3| reaches 1 = T only with all signs equal: p = 2/8 exactly
    assert st.sign_flip([F(1, 3)] * 3).p == F(1, 4)
    assert st.sign_flip([F(1, 3), F(1, 3), F(-2, 3)]).p == 1


def test_all_zero_units_give_p_one_without_flipping():
    res = st.sign_flip([F(0), F(0)])
    assert (res.p, res.method, res.n_nonzero) == (1, "no_discordant_unit", 0)


def test_sign_flip_refuses_floats():
    with pytest.raises(TypeError):
        st.sign_flip([0.5, -0.25])


def test_monte_carlo_fallback_uses_the_ab_stats_draw_and_add_one_p():
    rng = random.Random(7)
    values = [rng.choice((-3, -1, 1, 2, 4)) for _ in range(17)]       # > 16: ab_stats samples too
    res = st.sign_flip([F(v) for v in values], max_states=1, draws=3000, seed=99)
    assert (res.method, res.states) == ("monte_carlo", None)
    assert float(res.p) == pytest.approx(sign_flip_p([float(v) for v in values], n_perm=3000, seed=99))
    assert res.p.denominator == 3001 or (3001 % res.p.denominator == 0)


def test_dp_switches_to_monte_carlo_only_past_the_state_limit():
    values = [F(1), F(2), F(4)]                                       # states 2, 4, 8
    assert st.sign_flip(values, max_states=8).states == 8
    assert st.sign_flip(values, max_states=7, draws=100).method == "monte_carlo"


# ---------------------------------------------------------------- units, Δ̄, W:L (§5)

def test_union_find_links_chains_of_shared_gold_and_orders_units_by_smallest_id():
    gold = {"Q3": frozenset({"a"}), "Q1": frozenset({"a", "b"}), "Q2": frozenset({"b"}),
            "Q4": frozenset({"z"}), "Q0": frozenset({"y"})}
    assert st.clusters(gold, gold) == (("Q0",), ("Q1", "Q2", "Q3"), ("Q4",))


def test_core_links_questions_without_shared_gold_but_none_never_links():
    gold = {"A": frozenset({"a"}), "B": frozenset({"b"}), "C": frozenset({"c"}), "D": frozenset({"d"})}
    core = {"A": "moses", "B": "moses", "C": None, "D": None}
    assert st.clusters(gold, gold, core) == (("A", "B"), ("C",), ("D",))


def test_unit_value_is_the_unweighted_mean_including_zeros():
    units = (("A", "B", "C"), ("D",))
    d = {"A": F(1, 2), "B": F(0), "C": F(-1, 4), "D": F(0)}
    assert st.unit_values(units, d) == (F(1, 12), F(0))


def test_summary_direction_follows_sum_and_counts_zero_units_in_the_mean():
    s = st.summarize([F(1, 2), F(-1, 4), F(0), F(0)])
    assert (s.wins, s.losses, s.n_units, s.total, s.mean, s.direction) == (1, 1, 4, F(1, 4), F(1, 16), 1)
    assert st.summarize([F(-1, 3), F(1, 6)]).direction == -1


def item(qid, gold, set_name="new82", category=gd.KIN, core=None):
    return ev.Item(qid, set_name, category, tuple(frozenset(h) for h in gold), frozenset(), core, F(1, 2))


def test_compare_is_x_minus_y_so_a_better_treatment_is_positive():
    items = [item("A", [{"a"}]), item("B", [{"b"}]), item("C", [{"a"}])]
    fx = {"A": F(1), "B": F(1, 2), "C": F(1)}
    fy = {"A": F(1, 2), "B": F(1, 2), "C": F(1)}
    out, (p, total) = ev.compare(items, fx, fy, with_p=True)
    assert (out["unit_W:L"], out["n_units"], out["question_W:L"], out["direction"]) == ("1:0", 2, "1:0", 1)
    assert total == F(1, 4) and out["mean_unit_diff"] == pytest.approx(1 / 8) and p == 1
    flipped, _ = ev.compare(items, fy, fx, with_p=False)
    assert (flipped["unit_W:L"], flipped["direction"]) == ("0:1", -1) and "p" not in flipped


def test_compare_singletons_ignores_shared_gold():
    items = [item("A", [{"a"}]), item("B", [{"a"}])]
    f1 = {"A": F(1), "B": F(1)}
    f0 = {"A": F(0), "B": F(1)}
    assert ev.compare(items, f1, f0, with_p=False, singletons=True)[0]["n_units"] == 2
    assert ev.compare(items, f1, f0, with_p=False)[0]["n_units"] == 1


# ---------------------------------------------------------------- Holm gate (§5)

@pytest.mark.parametrize("p2, p3, want", [
    (F(2, 100), F(4, 100), {"H2": True, "H3": True}),
    (F(3, 100), F(4, 100), {"H2": False, "H3": False}),     # smaller p must be < 0.025
    (F(2, 100), F(6, 100), {"H2": True, "H3": False}),
    (F(49, 1000), F(1, 1000), {"H2": True, "H3": True}),     # order does not matter
    (F(1, 40), F(3, 100), {"H2": False, "H3": False}),        # 0.025 itself is not < 0.025
    (F(1, 40), F(1, 100), {"H2": True, "H3": True}),          # 0.01 < 0.025, then 0.025 < 0.05
])
def test_holm_pair(p2, p3, want):
    assert st.holm({"H2": p2, "H3": p3}) == want


def test_gate_withholds_h2_h3_when_h1_fails_even_on_a_significant_negative():
    g = st.gate((F(1, 1000), F(-1)), (F(1, 1000), F(1)), [(F(1, 1000), F(1)), (F(1, 1000), F(1))])
    assert g["H1"] == {"pass": False, "rejected": True, "direction_positive": False}
    assert not g["H2"]["tested"] and not g["H3"]["tested"] and not g["H2"]["pass"]


def test_gate_h3_takes_the_larger_p_and_needs_both_directions():
    g = st.gate((F(1, 100), F(1)), (F(9, 10), F(1)), [(F(1, 100), F(1)), (F(4, 100), F(1))])
    assert g["H3"]["p"] == F(4, 100) and not g["H3"]["pass"]           # 0.04 is the smaller: needs < 0.025
    g = st.gate((F(1, 100), F(1)), (F(3, 100), F(1)), [(F(1, 100), F(1)), (F(2, 100), F(-1))])
    assert g["H3"]["rejected"] and not g["H3"]["pass"]                 # one part points the wrong way
    assert g["H2"]["pass"]                                             # 0.03 < 0.05 after H3 rejected


class FakeTable:
    """hypotheses() needs only .items and .cov(arm, k)."""

    def __init__(self, items, cov):
        self.items, self._cov = items, cov

    def cov(self, arm, k, strict=False):
        return self._cov[arm, k]


def test_hypotheses_report_no_p_for_h2_h3_when_h1_fails():
    items = [item(f"Q{i}", [{f"p{i}"}]) for i in range(4)]
    ones = {q.qid: F(1) for q in items}
    zeros = {q.qid: F(0) for q in items}
    cov = {(a, k): ones for a in ("GD", "LEXPRF", "L") for k in (5, 10)}
    cov.update({("C", 10): ones, ("C", 5): zeros})                     # H1 has no discordant unit
    out = ev.hypotheses(FakeTable(items, cov))
    assert out["H1"]["pass"] is False and out["H1"]["p"] == 1.0
    assert "p" not in out["H2"] and "p_withheld" in out["H2"] and out["H2"]["unit_W:L"] == "4:0"
    assert "p" not in out["H3"] and all("p" not in part for part in out["H3"]["parts"].values())


# ---------------------------------------------------------------- top-k and f(q) (§3, §4)

def test_top_k_breaks_score_ties_by_passage_id():
    scores = {"ps:b": 0.5, "ps:a": 0.5, "ps:c": 0.9, "ps:d": 0.1}
    assert M.top_k(["ps:d", "ps:b", "ps:c", "ps:a"], scores, 2) == ("ps:c", "ps:a")
    assert M.cut_gap(["ps:d", "ps:b", "ps:c", "ps:a"], scores, 2) == 0.0
    assert M.cut_gap(["ps:a", "ps:c"], scores, 2) is None


def test_top_k_refuses_a_pool_passage_without_a_score():
    with pytest.raises(gd.GdError):
        M.top_k(["ps:a", "ps:x"], {"ps:a": 1.0}, 1)


def test_coverage_is_an_exact_fraction_of_hit_hops_and_strict_needs_every_gold_passage():
    gold = (frozenset({"a", "b"}), frozenset({"c"}), frozenset({"d"}))
    assert M.coverage(gold, ["a", "c", "x"]) == F(2, 3)
    assert M.coverage(gold, ["a", "c", "x"], strict=True) == F(1, 3)
    assert M.coverage(gold, ["a", "b", "c", "d"], strict=True) == 1
    with pytest.raises(gd.GoldError):
        M.coverage((), ["a"])


# ---------------------------------------------------------------- acceptance B classification

def ref_q(top, gap):
    return {"topk": {"5": {"GD": top}}, "cut_gap": {"5": {"GD": gap}}}


def test_a_differing_top_k_is_a_boundary_question_only_when_both_gaps_are_under_the_limit():
    pool = [f"ps:{i}" for i in range(7)]
    scores = {p: 1 - i / 10 for i, p in enumerate(pool)}
    scores["ps:4"], scores["ps:5"] = 0.5, 0.5 - 2e-6                  # new cut gap 2e-6
    top = list(M.top_k(pool, scores, 5))
    assert acc._mismatch("Q", "GD", 5, pool, scores, ref_q(top, 3e-6), 2e-5) is None
    other = top[:4] + ["ps:5"]
    kind, row = acc._mismatch("Q", "GD", 5, pool, scores, ref_q(other, 3e-6), 2e-5)
    assert kind == "boundary" and row["new_only"] == ["ps:4"] and row["ref_only"] == ["ps:5"]
    assert acc._mismatch("Q", "GD", 5, pool, scores, ref_q(other, 3e-5), 2e-5)[0] == "failed"
    assert acc._mismatch("Q", "GD", 5, pool, scores, ref_q(other, 3e-6), 0.0)[0] == "failed"


# ---------------------------------------------------------------- CLI

@pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")
def test_cli_exits_2_with_one_line_and_no_output_on_a_locked_set(tmp_path):
    out = tmp_path / "report.json"
    proc = subprocess.run([sys.executable, "-B", str(_DIR / "evaluate.py"), "report", "--set", "old31",
                           "--lists", str(tmp_path / "l.json"), "--scores", str(tmp_path / "s.jsonl"),
                           "--out", str(out)], capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 2 and not out.exists()
    assert proc.stderr.startswith("evaluate.py: ConfirmationLockedError:") and "Traceback" not in proc.stderr


@pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")
def test_cli_v1_refuses_old31_before_appendix_a(tmp_path):
    out = tmp_path / "v1.json"
    proc = subprocess.run([sys.executable, "-B", str(_DIR / "evaluate.py"), "v1", "--lists",
                           str(tmp_path / "l.json"), "--scores", str(tmp_path / "s.jsonl"), "--out",
                           str(out)], capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 2 and not out.exists()
    assert proc.stderr.startswith("evaluate.py: ConfirmationLockedError:")


def test_an_unpinned_accept_b_refuses_to_write_the_acceptance_file(tmp_path):
    with pytest.raises(gd.GdError, match="never writes"):
        ev.accept(tmp_path / "l.json", tmp_path / "s.jsonl", tmp_path / "r.json", pinned=False)


@pytest.mark.parametrize("name", ["old31", "ho", "gtv2"])
def test_report_runs_only_on_new82_or_the_e2_pool(name, tmp_path):
    with pytest.raises(gd.ConfirmationLockedError):
        ev.report(name, tmp_path / "l.json", tmp_path / "s.jsonl")
