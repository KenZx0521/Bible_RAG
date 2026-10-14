"""§5 statistics of the GD experiment (private part of evaluate.py).

Clusters (union-find on shared gold passages, optionally on a shared core), unit values,
the unit mean difference Δ̄ and unit W:L, the two-sided sign-flip p-value (exact
Fraction DP; seeded Monte Carlo beyond 10^7 DP states), the unit bootstrap CI from
evaluation/src/ab_stats.py and the H1 → Holm(H2, H3) gate. Pure functions on in-memory
values; nothing here reads the store.
"""
from __future__ import annotations

import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Mapping, Sequence

_EVAL_DIR = Path(__file__).resolve().parents[2]          # evaluation/
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

import src.ab_stats as _ab_stats  # noqa: E402

if Path(_ab_stats.__file__).resolve().parent != _EVAL_DIR / "src":
    raise ImportError(f"src.ab_stats resolved to {_ab_stats.__file__}, not {_EVAL_DIR / 'src'}")

SEED = 20261014
N_BOOT = 10_000
MC_DRAWS = 10 ** 6
DP_MAX_STATES = 10 ** 7
ALPHA = Fraction(1, 20)

__all__ = ["SEED", "N_BOOT", "MC_DRAWS", "DP_MAX_STATES", "ALPHA", "SignFlip", "UnitSummary",
           "clusters", "unit_values", "summarize", "sign_flip", "bootstrap", "holm", "gate"]


# ------------------------------------------------------------------ clusters (§5)

def clusters(ids: Iterable[str], gold: Mapping[str, frozenset[str]],
             core: Mapping[str, str | None] | None = None) -> tuple[tuple[str, ...], ...]:
    """Connected components of 'gold passage unions intersect' (and 'same core', when given).

    Units and their members are sorted; units are ordered by their smallest question id."""
    ids = sorted(ids)
    parent = {q: q for q in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def link(keys: Mapping[str, Iterable[str]]) -> None:
        owner: dict[str, str] = {}
        for q in ids:
            for key in keys[q]:
                if key in owner:
                    parent[find(q)] = find(owner[key])
                else:
                    owner[key] = q

    link(gold)
    if core is not None:
        link({q: () if core.get(q) is None else (core[q],) for q in ids})
    groups: dict[str, list[str]] = defaultdict(list)
    for q in ids:
        groups[find(q)].append(q)
    return tuple(sorted((tuple(g) for g in groups.values()), key=lambda g: g[0]))


def unit_values(units: Sequence[Sequence[str]], d: Mapping[str, Fraction]) -> tuple[Fraction, ...]:
    """v_u: unweighted mean of d(q) over the unit's questions (zeros included)."""
    return tuple(Fraction(sum((d[q] for q in u), Fraction(0)), len(u)) for u in units)


@dataclass(frozen=True)
class UnitSummary:
    n_units: int
    wins: int                # v_u > 0
    losses: int              # v_u < 0
    total: Fraction          # Σv: its sign is the direction
    mean: Fraction           # Δ̄ = Σv / n_units

    @property
    def direction(self) -> int:
        return (self.total > 0) - (self.total < 0)


def summarize(values: Sequence[Fraction]) -> UnitSummary:
    if not values:
        raise ValueError("no units to summarize")
    total = sum(values, Fraction(0))
    return UnitSummary(len(values), sum(v > 0 for v in values), sum(v < 0 for v in values),
                       total, total / len(values))


# ------------------------------------------------------------------ sign-flip (§5)

@dataclass(frozen=True)
class SignFlip:
    p: Fraction
    method: str              # "exact_dp" | "monte_carlo" | "no_discordant_unit"
    n_nonzero: int
    states: int | None       # largest DP state count (None when the DP was abandoned)


def _scaled(values: Sequence[Fraction]) -> list[int]:
    """Exact integers proportional to the nonzero values (common denominator)."""
    den = math.lcm(*(v.denominator for v in values)) if values else 1
    return [int(v * den) for v in values]


def _dp_tail(ints: Sequence[int], threshold: int, max_states: int) -> tuple[int, int] | None:
    """(#sign vectors with |Σ s·a| ≥ threshold, max states), or None past max_states."""
    dist = {0: 1}
    peak = 1
    for a in ints:
        nxt: dict[int, int] = defaultdict(int)
        for s, c in dist.items():
            nxt[s + a] += c
            nxt[s - a] += c
        if len(nxt) > max_states:
            return None
        dist, peak = nxt, max(peak, len(nxt))
    return sum(c for s, c in dist.items() if abs(s) >= threshold), peak


def _monte_carlo(ints: Sequence[int], threshold: int, draws: int, seed: int) -> Fraction:
    """ab_stats.sign_flip_p's draw (one rng.random() per value, in order); p=(hits+1)/(R+1)."""
    rng = random.Random(seed)
    hits = sum(abs(sum(a if rng.random() < 0.5 else -a for a in ints)) >= threshold
               for _ in range(draws))
    return Fraction(hits + 1, draws + 1)


def sign_flip(values: Sequence[Fraction], max_states: int = DP_MAX_STATES,
              draws: int = MC_DRAWS, seed: int = SEED) -> SignFlip:
    """Two-sided sign-flip p of Σv: v=0 units dropped, T=|Σv|, p=#{|Σs·v| ≥ T}/2^n, exact."""
    if not all(isinstance(v, (int, Fraction)) for v in values):
        raise TypeError("sign_flip needs exact (Fraction) unit values")
    nonzero = [Fraction(v) for v in values if v != 0]
    if not nonzero:
        return SignFlip(Fraction(1), "no_discordant_unit", 0, 0)
    ints = _scaled(nonzero)
    threshold = abs(sum(ints))
    exact = _dp_tail([abs(a) for a in ints], threshold, max_states)
    if exact is None:
        return SignFlip(_monte_carlo(ints, threshold, draws, seed), "monte_carlo", len(ints), None)
    tail, peak = exact
    return SignFlip(Fraction(tail, 2 ** len(ints)), "exact_dp", len(ints), peak)


def bootstrap(values: Sequence[Fraction]) -> tuple[float, float]:
    """95% CI of Δ̄: ab_stats.bootstrap_ci(unit values, n_boot=10000, seed=20261014)."""
    return _ab_stats.bootstrap_ci([float(v) for v in values], n_boot=N_BOOT, seed=SEED)


# ------------------------------------------------------------------ gate (§5 把關順序)

def holm(pvalues: Mapping[str, Fraction], alpha: Fraction = ALPHA) -> dict[str, bool]:
    """Holm step-down rejections: the i-th smallest p (0-based) is tested at α/(m−i)."""
    order = sorted(pvalues, key=lambda h: (pvalues[h], h))
    rejected = dict.fromkeys(pvalues, False)
    for i, h in enumerate(order):
        if not pvalues[h] < alpha / (len(order) - i):
            break
        rejected[h] = True
    return rejected


def gate(h1: tuple[Fraction, Fraction], h2: tuple[Fraction, Fraction],
         h3: Sequence[tuple[Fraction, Fraction]], alpha: Fraction = ALPHA) -> dict[str, dict]:
    """§5: H1 at α; only if H1 passes, H2 and H3 by Holm. Each arg is (p, Σv); H3 takes
    p = max over its parts and passes only when every part has Σv > 0."""
    p1, s1 = h1
    h1_pass = p1 < alpha and s1 > 0
    p3 = max(p for p, _ in h3)
    h3_dir = all(s > 0 for _, s in h3)
    out = {"H1": {"pass": h1_pass, "rejected": p1 < alpha, "direction_positive": s1 > 0}}
    if not h1_pass:
        for name, direction in (("H2", h2[1] > 0), ("H3", h3_dir)):
            out[name] = {"tested": False, "pass": False, "direction_positive": direction}
        return out
    rejected = holm({"H2": h2[0], "H3": p3}, alpha)
    out["H2"] = {"tested": True, "rejected": rejected["H2"], "direction_positive": h2[1] > 0,
                 "pass": rejected["H2"] and h2[1] > 0}
    out["H3"] = {"tested": True, "p": p3, "rejected": rejected["H3"], "direction_positive": h3_dir,
                 "pass": rejected["H3"] and h3_dir}
    return out
