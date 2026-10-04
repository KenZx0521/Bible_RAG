"""Paired A/B statistics and the change ledger (2026-10 graph audit §3.3 step 1).

Retrieval is near-deterministic, so arms are compared question by question:
a sign-flip permutation test on the mean difference (primary), an exact sign
test on win/loss counts (it caught the MRR harm the mean test missed), Holm
across the metric family, and a ledger of what each question's top-k change
actually was — half the graph changes in Round 3 never moved any metric.
"""

import pytest

from src.ab_stats import (
    bootstrap_ci,
    holm,
    ledger_entry,
    sign_flip_p,
    sign_test_p,
    summarize_ledger,
)


def test_sign_test_matches_binomial_two_sided():
    # S2 − S0 verse recall in the audit: 14 wins, 5 losses → p ≈ 0.064
    assert sign_test_p(14, 5) == pytest.approx(0.0636, abs=1e-4)
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 5) == 1.0


def test_sign_flip_is_exact_for_few_nonzero_differences():
    # only the all-plus and all-minus patterns reach |mean| = 1 → 2/8
    assert sign_flip_p([1.0, 1.0, 1.0, 0.0, 0.0]) == pytest.approx(0.25)
    assert sign_flip_p([0.0, 0.0]) == 1.0


def test_sign_flip_monte_carlo_is_seeded():
    diffs = [0.1 * (i % 7) - 0.2 for i in range(40)]
    assert sign_flip_p(diffs, seed=3) == sign_flip_p(diffs, seed=3)


def test_bootstrap_ci_brackets_a_constant_shift():
    lo, hi = bootstrap_ci([0.5] * 20)
    assert lo == hi == 0.5


def test_holm_step_down_is_monotone():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == pytest.approx({"a": 0.03, "c": 0.06, "b": 0.06})


def _s(cid: str, gold: bool) -> dict:
    return {"id": cid, "gold": gold}


def test_ledger_identical_and_order_only():
    a = [_s("x", True), _s("y", False)]
    assert ledger_entry(a, list(a))["status"] == "identical"
    assert ledger_entry(a, [a[1], a[0]])["status"] == "order_only"


def test_ledger_classifies_swaps_by_gold():
    base = [_s("x", True), _s("y", False)]

    nongold = ledger_entry(base, [_s("x", True), _s("z", False)])
    gain = ledger_entry(base, [_s("x", True), _s("g", True)])
    loss = ledger_entry(base, [_s("y", False), _s("z", False)])

    assert (nongold["status"], nongold["injected"], nongold["displaced"]) == (
        "nongold_swap", [_s("z", False)], [_s("y", False)])
    assert gain["status"] == "gold_in"
    assert loss["status"] == "gold_out"


def test_ledger_mixed_when_gold_enters_and_leaves():
    entry = ledger_entry([_s("x", True), _s("y", False)], [_s("g", True), _s("y", False)])
    assert entry["status"] == "gold_swap"


def test_ledger_appended_passage_is_injected_not_displacing():
    base = [_s("x", True)]
    entry = ledger_entry(base, [_s("x", True), _s("aux", True)])
    assert entry["status"] == "gold_in"
    assert entry["displaced"] == []


def test_summarize_counts_statuses():
    entries = {"q1": {"status": "identical"}, "q2": {"status": "gold_in"}, "q3": {"status": "gold_in"}}
    assert summarize_ledger(entries) == {"identical": 1, "gold_in": 2}


def test_ledger_without_gold_flags_does_not_guess():
    """Legacy runs carry no per-passage gold flag: a change is 'changed', not a non-gold swap."""
    entry = ledger_entry([{"id": "x"}], [{"id": "y"}])
    assert entry["status"] == "changed"
