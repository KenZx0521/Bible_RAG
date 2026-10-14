"""GD experiment §8 E3 gates (experiments/2026-10-14_graph_gd/_e3_gates.py).

Unit tests on in-memory values: the two-sided Clopper–Pearson lower bound (scipy's beta
quantile and the exact binomial bisection, against closed forms and textbook values),
the vrec bootstrap call (sorted(qid) order, n_boot 10000, seed 20261014), MRR win / loss
counting with the 1e−9 tie band, and the slot gold_out / 補回 counts on a fake ruler.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
import _e3_gates as G  # noqa: E402

IDS = ["Q3", "Q1", "Q2"]                       # deliberately not sorted


# ---------------------------------------------------------------- Clopper–Pearson

@pytest.mark.parametrize("x, n, want", [
    (5, 10, 0.18708602844739),                 # textbook 95% CP for 5/10: [0.1871, 0.8129]
    (50, 100, 0.39832112950330),               # 50/100: [0.3983, 0.6017]
    (10, 10, 0.025 ** (1 / 10)),               # x = n: (α/2)^(1/n)
    (1, 4, 1 - 0.975 ** (1 / 4)),              # x = 1: 1 − (1 − α/2)^(1/n)
])
def test_clopper_pearson_lower_bound_matches_known_values(x, n, want):
    assert G.cp_lower_bisect(x, n) == pytest.approx(want, abs=1e-9)
    value, method = G.cp_lower(x, n)
    assert value == pytest.approx(want, abs=1e-9)
    assert method in ("scipy_beta_ppf", "binomial_bisection")


@pytest.mark.parametrize("x, n", [(1, 1), (3, 7), (15, 20), (120, 200), (299, 300), (1, 500)])
def test_bisection_agrees_with_scipys_beta_quantile(x, n):
    beta = pytest.importorskip("scipy.stats").beta
    assert G.cp_lower_bisect(x, n) == pytest.approx(float(beta.ppf(0.025, x, n - x + 1)), abs=1e-9)


def test_without_scipy_the_bound_comes_from_the_binomial_bisection(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy.stats", None)       # makes the import fail
    value, method = G.cp_lower(5, 10)
    assert method == "binomial_bisection" and value == pytest.approx(0.18708602844739, abs=1e-9)


def test_zero_wins_give_a_zero_lower_bound_and_bad_counts_raise():
    assert G.cp_lower(0, 7) == (0.0, "x=0")
    for x, n in ((3, 2), (-1, 4), (0, 0)):
        with pytest.raises(gd.GdError):
            G.cp_lower(x, n)


def test_binomial_upper_tail_small_cases():
    assert G.binom_upper_tail(0, 5, 0.3) == 1.0
    assert G.binom_upper_tail(1, 2, 0.5) == pytest.approx(0.75)
    assert G.binom_upper_tail(2, 2, 0.5) == pytest.approx(0.25)


# ---------------------------------------------------------------- gate 1: vrec bootstrap

def test_vrec_diffs_are_gd_minus_c_in_sorted_qid_order_with_the_prereg_bootstrap(monkeypatch):
    calls = []

    def spy(diffs, n_boot=0, seed=0, level=0.95):
        calls.append((list(diffs), n_boot, seed))
        return (-0.01, 0.02)

    monkeypatch.setattr(G.ab_stats, "bootstrap_ci", spy)
    out = G.vrec_stats(IDS, {"Q1": 0.5, "Q2": 1.0, "Q3": 0.0}, {"Q1": 0.75, "Q2": 0.5, "Q3": 0.0})
    assert calls == [([0.25, -0.5, 0.0], 10_000, 20261014)]
    assert out["ci95"] == [-0.01, 0.02] and out["mean_diff"] == pytest.approx(-0.25 / 3)
    assert (out["n_up"], out["n_down"]) == (1, 1)


def test_vrec_ci_is_ab_stats_bootstrap_ci_with_seed_20261014():
    c = {f"Q{i:03d}": 0.5 for i in range(40)}
    g = {q: v + (0.1 if i % 3 == 0 else -0.05) for i, (q, v) in enumerate(sorted(c.items()))}
    diffs = [g[q] - c[q] for q in sorted(c)]
    assert G.vrec_stats(list(c), c, g)["ci95"] == list(G.ab_stats.bootstrap_ci(diffs, 10_000, 20261014))


# ---------------------------------------------------------------- gate 2: MRR sign

def test_mrr_counts_only_differences_beyond_1e_9():
    c = {"Q1": 0.5, "Q2": 1.0, "Q3": 0.25, "Q4": 0.2}
    g = {"Q1": 1.0, "Q2": 1.0 + 5e-10, "Q3": 0.2, "Q4": 0.2}
    out = G.mrr_stats(list(c), c, g)
    assert (out["wins"], out["losses"], out["ties"]) == (1, 1, 2)
    assert out["win_share"] == 0.5 and out["cp_method"] in ("scipy_beta_ppf", "binomial_bisection")


@pytest.mark.parametrize("wins, losses, passed", [(9, 1, True), (6, 4, False), (0, 0, True), (0, 3, False)])
def test_mrr_gate_needs_a_cp_lower_bound_above_0_4_or_no_discordant_question(wins, losses, passed):
    ids = [f"Q{i}" for i in range(wins + losses + 2)]
    c = dict.fromkeys(ids, 0.5)
    g = {q: 1.0 if i < wins else (0.25 if i < wins + losses else 0.5) for i, q in enumerate(ids)}
    out = gate(ids, mrr=(c, g))
    assert out["mrr"]["pass"] is passed
    assert out["mrr"]["no_discordant"] is (wins + losses == 0)


# ---------------------------------------------------------------- gate 3: slot gold_out on a fake ruler

class FakeRuler:
    """source_slots: the union of each source id's slots (sources are plain ids here)."""

    def __init__(self, slots):
        self.slots = slots

    def source_slots(self, sources):
        return frozenset().union(*(self.slots[s] for s in sources))


RULER = FakeRuler({"a": {"g1", "x"}, "b": {"g2"}, "c": {"y"}, "d": {"g3"}, "e": set()})
GOLD = {"Q1": frozenset({"g1", "g2"}), "Q2": frozenset({"g3"}), "Q3": frozenset({"g1", "g3"}),
        "Q4": frozenset({"g2"})}


def test_lost_and_gained_follow_the_slot_set_differences_and_both_sides_count():
    c_src = {"Q1": ["a", "b"], "Q2": ["c"], "Q3": ["a", "e"], "Q4": ["c"]}
    g_src = {"Q1": ["a", "c"], "Q2": ["d"], "Q3": ["d", "e"], "Q4": ["b", "a"]}
    s_c, s_g = G.source_slots(RULER, c_src), G.source_slots(RULER, g_src)
    out = G.slot_stats(list(GOLD), GOLD, s_c, s_g)
    assert out["lost_slots"] == {"Q1": ["g2"], "Q3": ["g1"]}
    assert out["gained_slots"] == {"Q2": ["g3"], "Q3": ["g3"], "Q4": ["g2"]}
    assert (out["gold_out"], out["gained"], out["both"]) == (2, 3, ["Q3"])


def test_non_gold_slot_changes_do_not_count():
    s_c, s_g = {"Q1": frozenset({"x", "g1"})}, {"Q1": frozenset({"y", "g1"})}
    out = G.slot_stats(["Q1"], {"Q1": frozenset({"g1"})}, s_c, s_g)
    assert (out["gold_out"], out["gained"]) == (0, 0)


@pytest.mark.parametrize("n_lost, n_gained, passed", [(0, 0, True), (10, 10, True), (3, 2, False),
                                                       (11, 20, False), (10, 9, False)])
def test_slot_gate_needs_gold_out_at_most_10_and_at_most_the_gained(n_lost, n_gained, passed):
    ids = [f"Q{i:02d}" for i in range(n_lost + n_gained + 1)]
    gold = dict.fromkeys(ids, frozenset({"g"}))
    s_c = {q: frozenset({"g"}) if i < n_lost else frozenset() for i, q in enumerate(ids)}
    s_g = {q: frozenset({"g"}) if n_lost <= i < n_lost + n_gained else frozenset()
           for i, q in enumerate(ids)}
    out = gate(ids, slots=(gold, s_c, s_g))
    assert (out["slot"]["gold_out"], out["slot"]["gained"]) == (n_lost, n_gained)
    assert out["slot"]["pass"] is passed


# ---------------------------------------------------------------- gate_k

def gate(ids, mrr=None, vrec=None, slots=None, gated=True):
    zero = dict.fromkeys(ids, 0.0)
    c_m, g_m = mrr or (zero, zero)
    c_v, g_v = vrec or (zero, zero)
    gold, s_c, s_g = slots or (dict.fromkeys(ids, frozenset()),) + (dict.fromkeys(ids, frozenset()),) * 2
    return G.gate_k(ids, {"vrec": c_v, "mrr": c_m}, {"vrec": g_v, "mrr": g_m}, gold, s_c, s_g, gated)


def test_identical_arms_pass_all_three_gates():
    ids = [f"Q{i}" for i in range(5)]
    out = gate(ids)
    assert out["passed"] and out["vrec"]["ci95"] == [0.0, 0.0] and out["mrr"]["no_discordant"]
    assert out["slot"]["gold_out"] == 0


def test_a_vrec_drop_below_minus_0_02_fails_gate_1_only():
    ids = [f"Q{i}" for i in range(10)]
    out = gate(ids, vrec=(dict.fromkeys(ids, 0.5), dict.fromkeys(ids, 0.45)))
    assert (out["vrec"]["pass"], out["mrr"]["pass"], out["slot"]["pass"], out["passed"]) == (
        False, True, True, False)


def test_the_reported_k_carries_no_pass_flags():
    ids = ["Q1", "Q2"]
    out = gate(ids, gated=False)
    assert out["gated"] is False and "passed" not in out
    assert all("pass" not in out[name] for name in ("vrec", "mrr", "slot"))
