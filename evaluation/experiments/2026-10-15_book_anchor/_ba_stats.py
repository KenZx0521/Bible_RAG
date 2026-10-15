"""Statistics and the written-down decision rules of the book_anchor ablation (prereg §5, §7, §8).

Host only. Per question, an arm's coverage is the mean of its valid r1–r6 (at least 4 of 6)
and its strict faithfulness the mean of its valid r1–r3 (at least 2 of 3); otherwise the
question leaves that pair's metric and is listed. A pair x:y is judged on its population
(nopin:ctrl on D_nopin, off:ctrl on D_off, off:nopin on U) by Δ_q = x̄(q) − ȳ(q):

  decision  two-sided t-CI at 97.5% (95% also reported); sign-flip p (evaluation/src/
            ab_stats, exact up to 16 non-zero differences, else 20,000 draws, seed
            20261015); Holm within each metric family {nopin:ctrl, off:ctrl, off:nopin}
  describe  percentile bootstrap 95% (ab_stats.bootstrap_ci, B=10,000, seed 20261015),
            W:L, the MDE at 97.5% / power 0.8, conversions to U and to 500 questions

verdict(): invalid (an invariant failed, or more than 2 questions excluded) → harm (cov,
strict or vrec@5 with Holm p < 0.05 and Δ̄ < 0) → adoptable (cov 97.5% lower bound > −0.05,
strict's > −0.04, and for x:ctrl the 500-question strict ≥ 0.97; "improved" when cov's
Holm p < 0.05 and Δ̄ > 0) → inconclusive. prod_action(): §8's table in order.
"""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

_EVAL_ROOT = Path(__file__).resolve().parents[2]
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))

from scipy import stats as _scipy_stats  # noqa: E402

from src import ab_stats  # noqa: E402

__all__ = ["SEED", "METRICS", "PAIRS", "ALPHA", "COV_MARGIN", "STRICT_MARGIN", "STRICT_500_MIN",
           "MAX_EXCLUDED", "LABELS_ZH", "ACTIONS_ZH", "unit_mean", "paired_diffs", "t_ci",
           "mde", "describe", "compare", "add_holm", "scale", "strict_500", "verdict",
           "prod_action", "refusal_compare", "ab_stats"]

SEED = 20261015
N_BOOT = 10_000
N_PERM = 20_000
METRICS = ("cov", "strict", "vrec5")
PAIRS = (("nopin", "ctrl"), ("off", "ctrl"), ("off", "nopin"))
ALPHA = 0.05
DECISION_LEVEL, DESCRIBE_LEVEL = 0.975, 0.95
COV_MARGIN, STRICT_MARGIN, STRICT_500_MIN = -0.05, -0.04, 0.97
MAX_EXCLUDED = 2
REPS = {"cov": 6, "strict": 3}
MIN_VALID = {"cov": 4, "strict": 2}
POWER = 0.8
N_TOTAL = 500
LABELS_ZH = {"invalid": "無效", "harm": "傷害", "adoptable": "可改", "inconclusive": "無法判定"}
ACTIONS_ZH = {"keep": "維持現行", "nopin": "採 nopin（只刪單書釘選）", "off": "採 off（刪除整個功能）",
              "rerun": "不判定，先補跑"}


def unit_mean(values: Sequence[float | None], metric: str) -> float | None:
    """One question's arm value: the mean of its valid repetitions, or None below the minimum."""
    if len(values) != REPS[metric]:
        raise ValueError(f"{metric} expects {REPS[metric]} repetitions, got {len(values)}")
    valid = [v for v in values if v is not None]
    return statistics.fmean(valid) if len(valid) >= MIN_VALID[metric] else None


def paired_diffs(x: Mapping[str, float | None], y: Mapping[str, float | None],
                 population: Iterable[str]) -> tuple[dict[str, float], list[str]]:
    """({q: x − y} where both are valid, [questions excluded])."""
    diffs, excluded = {}, []
    for q in sorted(population):
        a, b = x.get(q), y.get(q)
        if a is None or b is None:
            excluded.append(q)
        else:
            diffs[q] = a - b
    return diffs, excluded


def t_ci(diffs: Sequence[float], level: float) -> tuple[float, float] | None:
    """Two-sided t confidence interval of the mean (None below two values)."""
    n = len(diffs)
    if n < 2:
        return None
    mean = statistics.fmean(diffs)
    half = float(_scipy_stats.t.ppf(1 - (1 - level) / 2, n - 1)) * statistics.stdev(diffs) \
        / math.sqrt(n)
    return (mean - half, mean + half)


def mde(sd: float, n: int, level: float = DECISION_LEVEL, power: float = POWER) -> float | None:
    """Smallest |Δ| the paired t-test at ``level`` detects with ``power`` (descriptive)."""
    if n < 2:
        return None
    return float((_scipy_stats.t.ppf(1 - (1 - level) / 2, n - 1)
                  + _scipy_stats.t.ppf(power, n - 1)) * sd / math.sqrt(n))


def describe(diffs: Sequence[float]) -> dict[str, Any]:
    diffs = list(diffs)
    n = len(diffs)
    sd = statistics.stdev(diffs) if n > 1 else None
    return {
        "n": n, "mean": statistics.fmean(diffs) if n else None, "sd": sd,
        "ci975": t_ci(diffs, DECISION_LEVEL), "ci95": t_ci(diffs, DESCRIBE_LEVEL),
        "boot95": (ab_stats.bootstrap_ci(diffs, n_boot=N_BOOT, seed=SEED, level=DESCRIBE_LEVEL)
                   if n else None),
        "wins": sum(d > 0 for d in diffs), "losses": sum(d < 0 for d in diffs),
        "ties": sum(d == 0 for d in diffs),
        "p": ab_stats.sign_flip_p(diffs, n_perm=N_PERM, seed=SEED) if n else 1.0,
        "mde975": mde(sd, n) if sd is not None else None,
    }


def compare(x: str, y: str, population: Iterable[str],
            cov: Mapping[str, Mapping[str, float | None]],
            strict: Mapping[str, Mapping[str, float | None]],
            vrec: Mapping[str, Mapping[str, float | None]]) -> dict[str, Any]:
    """The pair x:y on its population: per metric diffs, description and exclusions."""
    population = sorted(population)
    out: dict[str, Any] = {"pair": f"{x}:{y}", "population": population}
    for name, table in (("cov", cov), ("strict", strict), ("vrec5", vrec)):
        diffs, excluded = paired_diffs(table[x], table[y], population)
        out[name] = {**describe(list(diffs.values())), "excluded": excluded, "diffs": diffs}
    out["excluded"] = sorted(set(out["cov"]["excluded"]) | set(out["strict"]["excluded"]))
    return out


def add_holm(comparisons: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """A copy with "p_holm" per metric, Holm-adjusted across the pairs (one family per metric)."""
    out = {pair: {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in cmp.items()}
           for pair, cmp in comparisons.items()}
    for m in METRICS:
        adjusted = ab_stats.holm({pair: cmp[m]["p"] for pair, cmp in comparisons.items()})
        for pair, p in adjusted.items():
            out[pair][m]["p_holm"] = p
    return out


def scale(mean: float | None, n_subset: int, n_total: int = N_TOTAL) -> float | None:
    """Δ̄ · |D| / N: the subset effect on a population where the rest has Δ = 0."""
    return None if mean is None else mean * n_subset / n_total


def strict_500(eval3c_strict: Mapping[str, float | None],
               arm_strict: Mapping[str, float | None], subset: Iterable[str]) -> float | None:
    """§5 G1: eval3c full's strict outside D_x, the arm's s̄ inside, over valid questions."""
    subset = set(subset)
    vals = [arm_strict.get(q) if q in subset else v for q, v in eval3c_strict.items()]
    vals += [arm_strict.get(q) for q in subset - set(eval3c_strict)]
    vals = [v for v in vals if v is not None]
    return statistics.fmean(vals) if vals else None


def _lo(metric: Mapping[str, Any]) -> float | None:
    ci = metric.get("ci975")
    return None if ci is None else ci[0]


def verdict(cmp: Mapping[str, Any], *, invariants_ok: bool, strict500: float | None,
            vs_ctrl: bool) -> dict[str, Any]:
    """§8 verdict(pair): the first rule that holds."""
    excluded = list(cmp.get("excluded") or [])
    if not invariants_ok or len(excluded) > MAX_EXCLUDED:
        reason = "invariants" if not invariants_ok else f"{len(excluded)} questions excluded"
        return _v("invalid", reason=reason, excluded=excluded)
    harm = [m for m in METRICS if cmp[m].get("mean") is not None and cmp[m]["mean"] < 0
            and cmp[m].get("p_holm", 1.0) < ALPHA]
    if harm:
        return _v("harm", harm_metrics=harm, excluded=excluded)
    cov_lo, strict_lo = _lo(cmp["cov"]), _lo(cmp["strict"])
    checks = {"cov_lo975>-0.05": cov_lo is not None and cov_lo > COV_MARGIN,
              "strict_lo975>-0.04": strict_lo is not None and strict_lo > STRICT_MARGIN,
              "strict500>=0.97": (not vs_ctrl) or (strict500 is not None
                                                  and strict500 >= STRICT_500_MIN)}
    if all(checks.values()):
        improved = (cmp["cov"].get("mean") or 0) > 0 and cmp["cov"].get("p_holm", 1.0) < ALPHA
        return _v("adoptable", improved=improved, checks=checks, excluded=excluded)
    return _v("inconclusive", checks=checks, excluded=excluded)


def _v(name: str, **extra: Any) -> dict[str, Any]:
    return {"verdict": name, "label_zh": LABELS_ZH[name], "improved": False,
            "harm_metrics": [], **extra}


def prod_action(verdicts: Mapping[str, Mapping[str, Any]],
                off_nopin_cov_hi975: float | None) -> dict[str, Any]:
    """§8 prod action: the table's rows in order, the first that holds. An invalid verdict
    decides nothing (§8 verdict 1: rerun first), so "rerun" is returned only when the row
    being evaluated needs an invalid pair to decide; a row already decided by valid
    verdicts stands (e.g. a valid nopin:ctrl harm is row 1 whatever off's pairs are).
    Any invalid pair is listed in "invalid_pairs"."""
    names = ("nopin:ctrl", "off:ctrl", "off:nopin")
    nc, oc, on = (verdicts[p]["verdict"] for p in names)
    invalid = [p for p in names if verdicts[p]["verdict"] == "invalid"]
    note = {"invalid_pairs": invalid} if invalid else {}
    if nc == "invalid":                                     # row 1 needs nopin:ctrl
        return _a("rerun", 0, **note)
    if nc == "harm":
        return _a("keep", 1, **note)
    row2_ruled_out = any(v not in ("adoptable", "invalid") for v in (oc, on))
    if not row2_ruled_out:
        if "invalid" in (oc, on):                           # row 2 needs both off pairs
            return _a("rerun", 0, **note)
        if nc == "adoptable" and off_nopin_cov_hi975 is not None and off_nopin_cov_hi975 < 0:
            return _a("nopin", 2, note="off:nopin cov 97.5% upper bound < 0")
        return _a("off", 2)
    if nc == "adoptable":
        return _a("nopin", 3, **note)
    return _a("keep", 4, **note)


def _a(action: str, rule: int, **extra: Any) -> dict[str, Any]:
    return {"action": action, "label_zh": ACTIONS_ZH[action], "rule": rule, **extra}


def refusal_compare(answers: Mapping[str, Mapping[str, Sequence[str]]], x: str, y: str,
                    population: Iterable[str], is_refusal: Callable[[str], bool]) -> dict:
    """(descriptive) refusal counts of x and y over the population's answers and an exact
    sign test on the per-question count differences (wins: x refused more)."""
    population = sorted(population)
    count = {arm: {q: sum(bool(is_refusal(a)) for a in answers[arm].get(q, []))
                   for q in population} for arm in (x, y)}
    diffs = [count[x][q] - count[y][q] for q in population]
    wins, losses = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    return {x: sum(count[x].values()), y: sum(count[y].values()), "wins": wins,
            "losses": losses, "p_sign": ab_stats.sign_test_p(wins, losses)}
