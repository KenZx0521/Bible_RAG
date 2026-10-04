"""
Paired statistics and the top-k change ledger for retrieval A/B runs.

Retrieval is near-deterministic, so two arms are compared question by
question. Following the 2026-10 graph audit:
  * primary test: sign-flip permutation on the mean paired difference
    (exact when few questions differ, seeded Monte Carlo otherwise);
  * also an exact sign test on win/loss counts — the mean test missed the
    graph's MRR harm (19 wins : 42 losses) that the sign test caught;
  * Holm across the metric family;
  * a ledger of what each question's top-k change was: half of Round 3's
    graph changes swapped non-gold passages and moved no metric at all.
"""

from __future__ import annotations

import itertools
import math
import random

_EXACT_MAX_NONZERO = 16
_EPS = 1e-12


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided binomial sign test (ties already dropped)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def sign_flip_p(diffs: list[float], n_perm: int = 20000, seed: int = 0) -> float:
    """Two-sided paired sign-flip permutation p-value for the mean difference.

    Zero differences cannot change sign and are dropped. Exact enumeration up
    to 16 non-zero differences; seeded Monte Carlo (add-one) beyond that.
    """
    nonzero = [d for d in diffs if abs(d) > _EPS]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    if len(nonzero) <= _EXACT_MAX_NONZERO:
        hits = total = 0
        for signs in itertools.product((1, -1), repeat=len(nonzero)):
            total += 1
            if abs(sum(s * d for s, d in zip(signs, nonzero))) >= observed - _EPS:
                hits += 1
        return hits / total
    rng = random.Random(seed)
    hits = sum(
        abs(sum(d if rng.random() < 0.5 else -d for d in nonzero)) >= observed - _EPS
        for _ in range(n_perm)
    )
    return (hits + 1) / (n_perm + 1)


def bootstrap_ci(
    diffs: list[float], n_boot: int = 10000, seed: int = 0, level: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean paired difference."""
    if not diffs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_boot))
    alpha = (1 - level) / 2
    lo = means[int(math.floor(alpha * (n_boot - 1)))]
    hi = means[int(math.ceil((1 - alpha) * (n_boot - 1)))]
    return (lo, hi)


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values (family-wise error control)."""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[name] = running
    return adjusted


def ledger_entry(base: list[dict], treat: list[dict]) -> dict:
    """What changed between two top-k lists of {"id", "gold", ...} sources.

    status: identical | order_only | nongold_swap | gold_in | gold_out | gold_swap
    (appended passages count as injected with nothing displaced), or
    "changed" when a moved passage has no gold flag (legacy runs).
    """
    base_ids = [s["id"] for s in base]
    treat_ids = [s["id"] for s in treat]
    if base_ids == treat_ids:
        return {"status": "identical", "injected": [], "displaced": []}
    if sorted(base_ids) == sorted(treat_ids):
        return {"status": "order_only", "injected": [], "displaced": []}
    injected = [s for s in treat if s["id"] not in set(base_ids)]
    displaced = [s for s in base if s["id"] not in set(treat_ids)]
    if any("gold" not in s for s in injected + displaced):
        return {"status": "changed", "injected": injected, "displaced": displaced}
    gold_in = any(s.get("gold") for s in injected)
    gold_out = any(s.get("gold") for s in displaced)
    status = {
        (False, False): "nongold_swap",
        (True, False): "gold_in",
        (False, True): "gold_out",
        (True, True): "gold_swap",
    }[(gold_in, gold_out)]
    return {"status": status, "injected": injected, "displaced": displaced}


def summarize_ledger(entries: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return counts
