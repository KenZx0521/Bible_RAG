"""§3 top-k, §4 metrics (f(q), D5≈ missing hops) and the §7 name-density strata
(private part of evaluate.py).

Every top-k is sorted(pool, key=(−score, pid))[:k]; coverage f(q) is an exact Fraction;
D5≈ is the top 5 of the record-level R20 passages by (−reranker score, pid). Pools and
scores come from _eval_inputs.py. Pure functions apart from the cached degree table.
"""
from __future__ import annotations

import bisect
import functools
from collections import defaultdict
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import gd_common as gd

ARMS = gd.ARMS
TESTED_ARMS = ("C", "GD", "L", "LEXPRF")       # H1–H3 cannot run without them
KS = (10, 5)                                    # §3: k=10 primary, k=5 secondary
FULL_POOL = gd.N_BASE + gd.N_EXTRA
LOW_DENSITY = Fraction(4, 5)                    # §7: question value < 0.8 is the low stratum
BOUNDARY_GAP = gd.DRIFT_TOL                     # §10: a top-k cut gap below 1e-5 is a boundary question

__all__ = ["ARMS", "TESTED_ARMS", "KS", "FULL_POOL", "LOW_DENSITY", "BOUNDARY_GAP", "top_k",
           "cut_gap", "cut_gap_table", "hop_hits", "coverage", "d5_approx", "d5_missing",
           "passage_degrees", "density_value"]


# ------------------------------------------------------------------ §3 top-k

def _ranked(pool_ids: Sequence[str], scores: Mapping[str, float]) -> list[str]:
    absent = [p for p in pool_ids if p not in scores]
    if absent:
        raise gd.GdError(f"pool passages without a reranker score: {absent}")
    return sorted(pool_ids, key=lambda p: (-scores[p], p))


def top_k(pool_ids: Sequence[str], scores: Mapping[str, float], k: int) -> tuple[str, ...]:
    """§3: sorted(pool, key=(−score, pid))[:k]."""
    return tuple(_ranked(pool_ids, scores)[:k])


def cut_gap(pool_ids: Sequence[str], scores: Mapping[str, float], k: int) -> float | None:
    """Score of the k-th minus the (k+1)-th pool passage; None when the pool has ≤ k."""
    ranked = _ranked(pool_ids, scores)
    if len(ranked) <= k:
        return None
    return scores[ranked[k - 1]] - scores[ranked[k]]


def cut_gap_table(pools: Mapping[str, Mapping[str, Sequence[str]]],
                  scores: Mapping[str, Mapping[str, float]], arms: Sequence[str],
                  ids: Sequence[str]) -> dict[str, Any]:
    """§10: per arm and k, the smallest top-k cut gap and the questions below BOUNDARY_GAP."""
    out = {}
    for arm in arms:
        for k in KS:
            gaps = {q: cut_gap(pools[arm][q], scores[q], k) for q in ids}
            known = {q: g for q, g in gaps.items() if g is not None}
            out[f"{arm}@{k}"] = {"min": min(known.values(), default=None),
                                 "boundary_lt_1e-5": sorted(q for q, g in known.items()
                                                            if g < BOUNDARY_GAP)}
    return out


# ------------------------------------------------------------------ §4 metrics

def hop_hits(gold: Sequence[frozenset[str]], top: Sequence[str], strict: bool = False) -> tuple[bool, ...]:
    """Per hop: gold_h ∩ top ≠ ∅ (strict: gold_h ⊆ top)."""
    chosen = frozenset(top)
    return tuple((g <= chosen) if strict else bool(g & chosen) for g in gold)


def coverage(gold: Sequence[frozenset[str]], top: Sequence[str], strict: bool = False) -> Fraction:
    """§4 f(q) = (1/H)·Σ_h hit_h as an exact Fraction."""
    if not gold:
        raise gd.GoldError("a question without hops has no coverage")
    return Fraction(sum(hop_hits(gold, top, strict)), len(gold))


def d5_approx(r20: Sequence[str], scores: Mapping[str, float]) -> tuple[str, ...]:
    """§4 D5≈: the record-level top-20 passages (R20) by (−whole-passage score, pid), top 5."""
    if not r20:
        raise gd.GdError("D5≈ needs the R20 list of arms.py (lists.json lacks it)")
    return top_k(r20, scores, gd.N_D5)


def d5_missing(gold: Sequence[frozenset[str]], r20: Sequence[str],
               scores: Mapping[str, float]) -> frozenset[int]:
    """§4 missing hops: the hops whose gold is not in D5≈."""
    d5 = frozenset(d5_approx(r20, scores))
    return frozenset(h for h, g in enumerate(gold) if not g & d5)


# ------------------------------------------------------------------ §7 name density

@functools.cache
def passage_degrees() -> Mapping[str, int]:
    """deg(p): distinct body norm_keys whose span unit maps (passage_id only) to p; 0 if none."""
    vi = gd.load_verse_index().passage_of
    names: dict[str, set[str]] = defaultdict(set)
    for s in gd.load_body_spans():
        names[vi[s.container_id]].add(s.norm_key)
    return MappingProxyType({p.passage_id: len(names[p.passage_id]) for p in gd.load_passages()})


@functools.cache
def _sorted_degrees() -> tuple[int, ...]:
    return tuple(sorted(passage_degrees().values()))


def _pct(pid: str) -> Fraction:
    """pct(deg) = #{passages with deg ≤ d} / 2773."""
    values = _sorted_degrees()
    return Fraction(bisect.bisect_right(values, passage_degrees()[pid]), len(values))


def density_value(gold: Sequence[frozenset[str]]) -> Fraction:
    """§7 question value: min over hops of (max pct over the hop's gold passages)."""
    return min(max(_pct(p) for p in hop) for hop in gold)
