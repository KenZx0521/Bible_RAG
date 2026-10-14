"""§8 E3 gates of two scored runs, C and GD at one k (private part of e3_raw.py).

Every per-question difference is GD − C, questions in sorted(qid) order.

1. vrec@k: bootstrap_ci(diffs, n_boot=10000, seed=20261014) of evaluation/src/ab_stats.py
   (not ab_compare's seed 0); passes when its lower bound is > −0.02.
2. MRR@k: a question is a win / loss when |Δ| > 1e−9; the two-sided 95% Clopper–Pearson
   lower bound of wins / (wins + losses) must be > 0.4. No win and no loss passes, recorded.
3. slot gold_out: S(·) = ruler.source_slots of a run's k sources on the GT v2 ruler that
   quick_retrieval_eval builds for the build (quick_retrieval_eval._run_context);
   lost(q) = gold_slots ∩ (S(C) − S(GD)), gained(q) = gold_slots ∩ (S(GD) − S(C));
   gold_out = #{lost ≠ ∅} must be ≤ 10 and ≤ 補回 = #{gained ≠ ∅}; a question with both
   counts on both sides. ab_stats.ledger_entry is not used.

k=10 is reported the same way without a gate. The statistics are pure functions on
in-memory values (gate_k); ruler_context() and run_sources() read a raw dir the way
quick_retrieval_eval.py --from-raw does.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

import gd_common as gd

_EVAL_DIR = gd.EXP_DIR.parents[1]                      # evaluation/
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

import quick_retrieval_eval as qre  # noqa: E402
import src.ab_stats as ab_stats  # noqa: E402

if Path(ab_stats.__file__).resolve().parent != _EVAL_DIR / "src":
    raise ImportError(f"src.ab_stats resolved to {ab_stats.__file__}, not {_EVAL_DIR / 'src'}")

__all__ = ["SEED", "N_BOOT", "VREC_LOWER_MIN", "MRR_TIE", "CP_ALPHA", "CP_LOWER_MIN", "GOLD_OUT_MAX",
           "K_GATED", "K_REPORTED", "binom_upper_tail", "cp_lower_bisect", "cp_lower", "paired_diffs",
           "vrec_stats", "mrr_stats", "slot_stats", "gate_k", "source_slots", "ruler_context",
           "run_sources"]

SEED = 20261014
N_BOOT = 10_000
VREC_LOWER_MIN = -0.02          # gate 1: bootstrap lower bound must be above this
MRR_TIE = 1e-9                  # gate 2: |Δ| at or below this is a tie
CP_ALPHA = 0.05                 # gate 2: two-sided 95% Clopper–Pearson
CP_LOWER_MIN = 0.4              # gate 2: its lower bound must be above this
GOLD_OUT_MAX = 10               # gate 3: at most this many questions lose a gold slot
K_GATED, K_REPORTED = 5, 10     # §8: gates at prod's k=5; k=10 only reported
_BISECT_STEPS = 200


class Ruler(Protocol):
    def source_slots(self, sources: Iterable[Any]) -> frozenset[str]: ...


# ------------------------------------------------------------------ Clopper–Pearson

def binom_upper_tail(x: int, n: int, p: float) -> float:
    """P(X ≥ x) for X ~ Binomial(n, p), summed in log space."""
    if x <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lp, lq, lf = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    return min(1.0, sum(math.exp(lf - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp
                                 + (n - i) * lq) for i in range(x, n + 1)))


def cp_lower_bisect(x: int, n: int, alpha: float = CP_ALPHA) -> float:
    """Exact Clopper–Pearson lower bound: the p with P(X ≥ x | n, p) = α/2, by bisection."""
    if x == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(_BISECT_STEPS):
        mid = (lo + hi) / 2
        if binom_upper_tail(x, n, mid) < alpha / 2:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return (lo + hi) / 2


def cp_lower(x: int, n: int, alpha: float = CP_ALPHA) -> tuple[float, str]:
    """(two-sided 1−α Clopper–Pearson lower bound of x/n, method): scipy's beta quantile
    Beta(α/2; x, n−x+1) when scipy is installed, else cp_lower_bisect."""
    if not (isinstance(x, int) and isinstance(n, int) and 0 <= x <= n and n >= 1):
        raise gd.GdError(f"Clopper–Pearson needs 0 ≤ x ≤ n, n ≥ 1 (got x={x}, n={n})")
    if x == 0:
        return 0.0, "x=0"
    try:
        from scipy.stats import beta
    except ImportError:
        return cp_lower_bisect(x, n, alpha), "binomial_bisection"
    return float(beta.ppf(alpha / 2, x, n - x + 1)), "scipy_beta_ppf"


# ------------------------------------------------------------------ the three statistics

def paired_diffs(ids: Iterable[str], c: Mapping[str, float], g: Mapping[str, float]) -> list[float]:
    """GD − C per question, in sorted(qid) order."""
    return [g[q] - c[q] for q in sorted(ids)]


def vrec_stats(ids: Sequence[str], c: Mapping[str, float], g: Mapping[str, float]) -> dict[str, Any]:
    diffs = paired_diffs(ids, c, g)
    lo, hi = ab_stats.bootstrap_ci(diffs, n_boot=N_BOOT, seed=SEED)
    return {"n": len(diffs), "mean_diff": sum(diffs) / len(diffs) if diffs else 0.0,
            "n_up": sum(d > 0 for d in diffs), "n_down": sum(d < 0 for d in diffs),
            "ci95": [lo, hi], "n_boot": N_BOOT, "seed": SEED, "lower_min": VREC_LOWER_MIN}


def mrr_stats(ids: Sequence[str], c: Mapping[str, float], g: Mapping[str, float]) -> dict[str, Any]:
    diffs = paired_diffs(ids, c, g)
    wins = sum(d > MRR_TIE for d in diffs)
    losses = sum(d < -MRR_TIE for d in diffs)
    out: dict[str, Any] = {"n": len(diffs), "wins": wins, "losses": losses,
                           "ties": len(diffs) - wins - losses, "tie_tol": MRR_TIE,
                           "no_discordant": wins + losses == 0, "lower_min": CP_LOWER_MIN}
    if wins + losses:
        out["win_share"] = wins / (wins + losses)
        out["cp_lower"], out["cp_method"] = cp_lower(wins, wins + losses)
    return out


def slot_stats(ids: Sequence[str], gold: Mapping[str, frozenset[str]],
               s_c: Mapping[str, frozenset[str]], s_g: Mapping[str, frozenset[str]]) -> dict[str, Any]:
    lost = {q: sorted(gold[q] & (s_c[q] - s_g[q])) for q in sorted(ids)}
    gained = {q: sorted(gold[q] & (s_g[q] - s_c[q])) for q in sorted(ids)}
    lost = {q: v for q, v in lost.items() if v}
    gained = {q: v for q, v in gained.items() if v}
    return {"gold_out": len(lost), "gained": len(gained), "both": sorted(set(lost) & set(gained)),
            "gold_out_max": GOLD_OUT_MAX, "lost_slots": lost, "gained_slots": gained}


def gate_k(ids: Sequence[str], c: Mapping[str, Mapping[str, float]], g: Mapping[str, Mapping[str, float]],
           gold: Mapping[str, frozenset[str]], s_c: Mapping[str, frozenset[str]],
           s_g: Mapping[str, frozenset[str]], gated: bool) -> dict[str, Any]:
    """The three statistics at one k; c / g map 'vrec' and 'mrr' to {qid: value}. gated adds
    each gate's pass flag and 'passed' (all three); otherwise the k is report-only."""
    out = {"vrec": vrec_stats(ids, c["vrec"], g["vrec"]), "mrr": mrr_stats(ids, c["mrr"], g["mrr"]),
           "slot": slot_stats(ids, gold, s_c, s_g), "gated": gated}
    if gated:
        v, m, s = out["vrec"], out["mrr"], out["slot"]
        v["pass"] = v["ci95"][0] > VREC_LOWER_MIN
        m["pass"] = m["no_discordant"] or m["cp_lower"] > CP_LOWER_MIN
        s["pass"] = s["gold_out"] <= GOLD_OUT_MAX and s["gold_out"] <= s["gained"]
        out["passed"] = v["pass"] and m["pass"] and s["pass"]
    return out


# ------------------------------------------------------------------ ruler and sources

def source_slots(ruler: Ruler, sources: Mapping[str, Sequence[Any]]) -> dict[str, frozenset[str]]:
    """S(·) per question: ruler.source_slots of its sources."""
    return {q: ruler.source_slots(srcs) for q, srcs in sources.items()}


def ruler_context(raw_path: Path) -> Any:
    """quick_retrieval_eval's run context for `--from-raw raw_path --gt v2` (GT v2 + the ruler
    of the build its run_meta.json names); src errors become IntegrityError."""
    args = argparse.Namespace(gt="v2", from_raw=Path(raw_path), contracts_dir=None)
    try:
        ctx = qre._run_context(args)
    except ValueError as err:          # ProvenanceError, SlotCoverageError, GtV2Error
        raise gd.IntegrityError(f"GT v2 ruler for {raw_path}: {err}") from None
    gd.expect("ruler build", ctx.ruler.build_id if ctx.ruler else None, gd.BUILD_ID)
    gd.expect("ruler GT sha", ctx.gt.sha256, gd.GTV2_SHA256)
    return ctx


def run_sources(raw_path: Path, ctx: Any, k: int) -> dict[str, list[Any]]:
    """Each question's first k sources as quick_retrieval_eval --from-raw rebuilds them."""
    try:
        samples = qre.samples_from_raw(Path(raw_path), ctx.gt.by_id())
        out = {s.question_id: list(s.sources[:k]) for s in samples}
    except ValueError as err:          # pydantic ValidationError
        raise gd.IntegrityError(f"{raw_path}: {err}") from None
    if len(out) != len(samples) or any(len(v) != k for v in out.values()):
        raise gd.IntegrityError(f"{raw_path}: duplicate questions or not k={k} sources each")
    return out
