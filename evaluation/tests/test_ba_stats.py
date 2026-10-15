"""book_anchor ablation statistics and decision rules (experiments/.../_ba_stats.py).

prereg §5, §7, §8 and §10 test_ba_stats: every cell of verdict() (invalid by invariants
and by exclusions, harm by each of cov / strict / vrec@5, adoptable, significant
improvement, inconclusive, the 500-question strict floor) and of prod_action() (nopin harm
blocks off, off when both off pairs are adoptable, nopin when off:nopin's upper bound is
below 0, nopin when only nopin is adoptable, keep otherwise, rerun on an invalid verdict);
the valid-repetition rule; the t-CI against scipy; Holm; the 500-question conversions.
"""

import math
import sys
from pathlib import Path

import pytest

_EXP = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_stats as st  # noqa: E402

stats = pytest.importorskip("scipy.stats")


# ---------------------------------------------------------------- valid repetitions (§5)

def test_coverage_needs_four_of_six_valid_and_strict_two_of_three():
    assert st.unit_mean([1.0, 0.5, None, None, 0.0, 0.5], "cov") == pytest.approx(0.5)
    assert st.unit_mean([1.0, None, None, None, 0.0, 0.5], "cov") is None
    assert st.unit_mean([1.0, None, 0.5], "strict") == pytest.approx(0.75)
    assert st.unit_mean([1.0, None, None], "strict") is None
    with pytest.raises(ValueError):
        st.unit_mean([1.0] * 5, "cov")          # coverage has six repetitions


def test_unit_means_and_exclusions_per_pair():
    x = {"A": 0.8, "B": None, "C": 0.5, "D": 0.4}
    y = {"A": 0.6, "B": 0.7, "C": None, "D": 0.4}
    diffs, excluded = st.paired_diffs(x, y, ["A", "B", "C", "D"])
    assert diffs == pytest.approx({"A": 0.2, "D": 0.0}) and excluded == ["B", "C"]


# ---------------------------------------------------------------- t-CI, sign-flip, Holm

@pytest.mark.parametrize("level", [0.975, 0.95])
def test_t_ci_matches_scipy(level):
    d = [0.1, -0.2, 0.05, 0.3, 0.0, -0.1, 0.15, 0.2]
    n = len(d)
    mean = sum(d) / n
    sem = stats.sem(d)
    want = stats.t.interval(level, n - 1, loc=mean, scale=sem)
    assert st.t_ci(d, level) == pytest.approx(want)


def test_t_ci_is_none_below_two_and_degenerate_when_constant():
    assert st.t_ci([0.1], 0.975) is None and st.t_ci([], 0.975) is None
    assert st.t_ci([0.1, 0.1, 0.1], 0.975) == pytest.approx((0.1, 0.1))


def test_describe_counts_and_p():
    out = st.describe([0.2, -0.1, 0.0, 0.3])
    assert (out["n"], out["wins"], out["losses"], out["ties"]) == (4, 2, 1, 1)
    assert out["mean"] == pytest.approx(0.1)
    assert out["p"] == pytest.approx(st.ab_stats.sign_flip_p([0.2, -0.1, 0.0, 0.3],
                                                             n_perm=20000, seed=st.SEED))
    assert out["ci975"] == pytest.approx(st.t_ci([0.2, -0.1, 0.0, 0.3], 0.975))
    assert out["boot95"][0] <= out["mean"] <= out["boot95"][1]
    assert out["mde975"] > 0
    empty = st.describe([])
    assert empty["n"] == 0 and empty["mean"] is None and empty["p"] == 1.0


def test_holm_per_metric_family():
    comps = {pair: {m: {"p": p} for m, p in zip(st.METRICS, ps)}
             for pair, ps in (("nopin:ctrl", (0.01, 0.2, 0.5)), ("off:ctrl", (0.02, 0.03, 0.5)),
                              ("off:nopin", (0.04, 0.01, 1.0)))}
    out = st.add_holm(comps)
    assert out["nopin:ctrl"]["cov"]["p_holm"] == pytest.approx(0.03)
    assert out["off:ctrl"]["cov"]["p_holm"] == pytest.approx(0.04)
    assert out["off:nopin"]["cov"]["p_holm"] == pytest.approx(0.04)
    assert out["off:nopin"]["strict"]["p_holm"] == pytest.approx(0.03)
    assert out["off:ctrl"]["strict"]["p_holm"] == pytest.approx(0.06)
    assert "p_holm" not in comps["nopin:ctrl"]["cov"]          # input left unchanged


# ---------------------------------------------------------------- 500-question conversions

def test_scale_500_and_strict_500():
    assert st.scale(0.05, 20, 500) == pytest.approx(0.002)
    base = {f"Q{i}": 1.0 for i in range(10)} | {"Q9": None}
    arm = {"Q0": 0.5, "Q1": None}
    # Q0 replaced by 0.5, Q1 dropped (no valid arm value), Q9 has no eval3c value
    assert st.strict_500(base, arm, ["Q0", "Q1"]) == pytest.approx((7 * 1.0 + 0.5) / 8)


# ---------------------------------------------------------------- verdict (§8)

def metric(mean, lo=None, hi=None, p_holm=1.0):
    return {"mean": mean, "ci975": None if lo is None else (lo, hi), "p_holm": p_holm}


def comparison(cov=(0.0, -0.03, 0.03, 1.0), strict=(0.0, -0.02, 0.02, 1.0),
               vrec=(0.0, None, None, 1.0), excluded=()):
    return {"cov": metric(*cov), "strict": metric(*strict), "vrec5": metric(*vrec),
            "excluded": list(excluded)}


def v(cmp, invariants_ok=True, strict500=0.98, vs_ctrl=True):
    return st.verdict(cmp, invariants_ok=invariants_ok, strict500=strict500, vs_ctrl=vs_ctrl)


def test_adoptable():
    out = v(comparison())
    assert out["verdict"] == "adoptable" and out["improved"] is False


def test_invalid_when_an_invariant_fails_or_more_than_two_excluded():
    assert v(comparison(), invariants_ok=False)["verdict"] == "invalid"
    assert v(comparison(excluded=["A", "B", "C"]))["verdict"] == "invalid"
    assert v(comparison(excluded=["A", "B"]))["verdict"] == "adoptable"


@pytest.mark.parametrize("which", ["cov", "strict", "vrec"])
def test_harm_by_each_metric(which):
    hit = (-0.06, -0.1, -0.02, 0.01)
    out = v(comparison(**{which: hit}))
    assert out["verdict"] == "harm" and out["harm_metrics"] == [
        {"cov": "cov", "strict": "strict", "vrec": "vrec5"}[which]]


def test_a_significant_positive_difference_is_not_harm():
    out = v(comparison(vrec=(0.05, None, None, 0.001)))
    assert out["verdict"] == "adoptable"


def test_significant_improvement_is_flagged_on_adoptable():
    out = v(comparison(cov=(0.08, 0.02, 0.14, 0.004)))
    assert out["verdict"] == "adoptable" and out["improved"] is True
    assert v(comparison(cov=(0.08, 0.02, 0.14, 0.06)))["improved"] is False


@pytest.mark.parametrize("cmp, strict500", [
    (comparison(cov=(-0.01, -0.06, 0.04, 0.5)), 0.98),       # cov lower bound at −0.06
    (comparison(cov=(-0.01, -0.05, 0.04, 0.5)), 0.98),       # exactly −0.05 is not > −0.05
    (comparison(strict=(-0.01, -0.05, 0.03, 0.5)), 0.98),    # strict lower bound
    (comparison(), 0.969),                                    # 500-question strict floor
    (comparison(), None),
    ({**comparison(), "cov": metric(None)}, 0.98),            # no CI (n < 2)
], ids=["cov_lo", "cov_lo_edge", "strict_lo", "strict500", "strict500_none", "no_ci"])
def test_inconclusive(cmp, strict500):
    assert v(cmp, strict500=strict500)["verdict"] == "inconclusive"


def test_off_nopin_has_no_500_question_floor():
    assert v(comparison(), strict500=None, vs_ctrl=False)["verdict"] == "adoptable"


# ---------------------------------------------------------------- prod_action (§8)

def act(nc, oc, on, hi=0.02):
    return st.prod_action({"nopin:ctrl": {"verdict": nc}, "off:ctrl": {"verdict": oc},
                           "off:nopin": {"verdict": on}}, off_nopin_cov_hi975=hi)


@pytest.mark.parametrize("nc, oc, on, hi, action, rule", [
    ("harm", "adoptable", "adoptable", 0.02, "keep", 1),             # nopin harm blocks off
    ("inconclusive", "adoptable", "adoptable", 0.02, "off", 2),
    ("adoptable", "adoptable", "adoptable", 0.02, "off", 2),
    ("adoptable", "adoptable", "adoptable", -0.001, "nopin", 2),     # off:nopin hi < 0
    ("inconclusive", "adoptable", "adoptable", -0.001, "off", 2),    # exception needs nopin
    ("adoptable", "adoptable", "inconclusive", 0.02, "nopin", 3),    # off:nopin not adoptable
    ("adoptable", "harm", "harm", 0.02, "nopin", 3),
    ("adoptable", "inconclusive", "adoptable", 0.02, "nopin", 3),
    ("inconclusive", "inconclusive", "inconclusive", 0.02, "keep", 4),
    ("inconclusive", "adoptable", "inconclusive", 0.02, "keep", 4),
    ("inconclusive", "harm", "adoptable", 0.02, "keep", 4),
])
def test_prod_action_table(nc, oc, on, hi, action, rule):
    out = act(nc, oc, on, hi)
    assert (out["action"], out["rule"]) == (action, rule)


@pytest.mark.parametrize("which", [0, 1, 2])
def test_prod_action_waits_for_a_rerun_on_any_invalid_verdict(which):
    verdicts = ["adoptable"] * 3
    verdicts[which] = "invalid"
    assert act(*verdicts)["action"] == "rerun"


VALID = ("harm", "adoptable", "inconclusive")


def table(nc, oc, on, hi):
    """§8's table written out on valid verdicts only (an independent statement)."""
    if nc == "harm":
        return "keep", 1
    if oc == on == "adoptable":
        return ("nopin", 2) if nc == "adoptable" and hi is not None and hi < 0 else ("off", 2)
    return ("nopin", 3) if nc == "adoptable" else ("keep", 4)


@pytest.mark.parametrize("hi", [None, -0.01, 0.01])
def test_prod_action_is_the_table_and_reruns_only_when_an_invalid_pair_could_change_it(hi):
    """With invalid pairs: the table's answer when every valid stand-in for them gives the
    same (action, rule), otherwise rerun; any invalid pair is listed."""
    import itertools
    for trio in itertools.product(VALID + ("invalid",), repeat=3):
        options = [VALID if v == "invalid" else (v,) for v in trio]
        outcomes = {table(*fill, hi) for fill in itertools.product(*options)}
        want = outcomes.pop() if len(outcomes) == 1 else ("rerun", 0)
        got = act(*trio, hi)
        assert (got["action"], got["rule"]) == want, trio
        names = [n for n, v in zip(("nopin:ctrl", "off:ctrl", "off:nopin"), trio)
                 if v == "invalid"]
        assert got.get("invalid_pairs", []) == names, trio


@pytest.mark.parametrize("nc, oc, on, action, rule", [
    ("harm", "adoptable", "invalid", "keep", 1),         # row 1 stands: off is not adopted
    ("adoptable", "harm", "invalid", "nopin", 3),        # row 2 already ruled out by off:ctrl
    ("inconclusive", "invalid", "inconclusive", "keep", 4),
    ("adoptable", "invalid", "adoptable", "rerun", 0),   # row 2 needs off:ctrl
    ("invalid", "harm", "harm", "rerun", 0),             # row 1 needs nopin:ctrl
])
def test_prod_action_with_one_invalid_pair(nc, oc, on, action, rule):
    out = act(nc, oc, on)
    assert (out["action"], out["rule"]) == (action, rule)


def test_prod_action_upper_bound_missing_is_not_below_zero():
    assert act("adoptable", "adoptable", "adoptable", None)["action"] == "off"


# ---------------------------------------------------------------- compare and refusals

def test_compare_builds_each_metric_on_the_population():
    cov = {"x": {"A": 0.8, "B": 0.5, "C": None}, "y": {"A": 0.6, "B": 0.5, "C": 0.4}}
    strict = {"x": {"A": 1.0, "B": 1.0, "C": 1.0}, "y": {"A": 1.0, "B": 0.9, "C": 1.0}}
    vrec = {"x": {"A": 1.0, "B": 0.5, "C": 0.5}, "y": {"A": 0.5, "B": 0.5, "C": 0.5}}
    out = st.compare("x", "y", ["A", "B", "C"], cov, strict, vrec)
    assert out["cov"]["n"] == 2 and out["cov"]["excluded"] == ["C"]
    assert out["strict"]["n"] == 3 and out["excluded"] == ["C"]
    assert out["vrec5"]["mean"] == pytest.approx(0.5 / 3)
    assert out["cov"]["diffs"] == pytest.approx({"A": 0.2, "B": 0.0})


def test_refusal_counts_and_sign_test():
    answers = {"x": {"A": ["找不到相關的經文內容", "好", "長答案" * 20],
                     "B": ["長答案" * 20] * 3},
               "y": {"A": ["長答案" * 20] * 3, "B": ["長答案" * 20] * 3}}
    out = st.refusal_compare(answers, "x", "y", ["A", "B"],
                             lambda a: len(a) < 30 or a.startswith("找不到"))
    assert out["x"] == 2 and out["y"] == 0
    assert (out["wins"], out["losses"]) == (1, 0) and out["p_sign"] == pytest.approx(1.0)


def test_mde_shrinks_with_n():
    sd = 0.146
    assert st.mde(sd, 39) < st.mde(sd, 20)
    want = (stats.t.ppf(1 - 0.0125, 19) + stats.t.ppf(0.8, 19)) * sd / math.sqrt(20)
    assert st.mde(sd, 20) == pytest.approx(want)
