"""
R1 non-inferiority gates, exactly as pre-registered in
experiments/2026-10-08_r1/prereg.md: G-NONINF (retrieval) and G-ANS (answers).

Pure functions over saved runs — quick_retrieval_eval.py results for
retrieval, quick_faithfulness_eval.py reports for answers; r1_gate.py is the
CLI. Every statistic is a paired mean over questions with a percentile 95%
bootstrap CI: questions resampled with replacement, B = 10,000, seed
20261008 (ab_stats.bootstrap_ci; each statistic restarts the seed, so equal
inputs give equal reports).

Retrieval (500 questions; the control is fixed to L1, the first A/A run):
  * A/A L2 − L1 sets the margins: δ = max(0.02, 2B), B = max |CI bound| of
    mean Δvrec@6; δ_wl = max(0.02, 2·B_wl), B_wl = MRR (wins + losses) / n.
  * C1: CI lower of mean Δvrec@6 (R − L1) > −δ.
  * C2: CI lower of mean sign(MRR_R − MRR_L1) > −δ_wl.
  * C3: mean Δvrec@6 (R − L1) over the frozen damaged union (64) ≥ 0.
  * A question invalid in either run of a pair is dropped and listed; a pair
    left with fewer than 495 questions fails the gate ("rerun arm").
Answers (the frozen 200-question subset):
  * δ_ans = max(0.01, 2·B_ans), B_ans = max |CI bound| of mean Δstrict
    (A2 − A1). Pass iff CI lower of mean Δstrict (R − A1) > −δ_ans and no
    arm has an invalid question (prereg n_invalid: 未判出, 生成失敗): a subset
    id without a row, a row the tool flags "invalid" (infrastructure failure
    or the backend's HTTP 200 generation-error answer, src/validity.py
    answer_failure), or a strict faithfulness of None / NaN (the tool leaves
    unjudged samples None). Invalid rows carry no value into any Δ.
  * A row outside the subset means another subset was judged, and rows
    without the "invalid" flag come from a tool that could not see
    generation failures: both refused.
Both gates: the A/A runs share a data build, the treatment runs another, and
all three report one encoder fingerprint (the /health query-tokenizer probe;
prod :8000 reports none and serves the same legacy build id as the control).
Everything under "report_only" is descriptive and never decides a verdict.
The frozen sets are r1_frozen.load_frozen's (FrozenR1); their sizes are
checked against the prereg. Inputs that do not match the protocol raise
GateInputError and get no verdict.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Collection, Mapping, NamedTuple, Sequence

from .ab_stats import bootstrap_ci, sign_test_p
from .r1_frozen import SUB_SLICES, FrozenR1

N_BOOT = 10_000
SEED = 20261008
LEVEL = 0.95
MIN_PAIRED = 495
GT_VERSION = "v2"
TOP_K, METRIC_K = 5, 6
DELTA_FLOOR = 0.02          # δ and δ_wl
DELTA_ANS_FLOOR = 0.01      # δ_ans
LARGE_DROP = -0.3           # report questions with Δvrec@6 at or below this
STRICT_REFERENCE = 0.97
COVERAGE_NOISE_FLOOR = 0.060    # Round 3 |Δ coverage| noise floor (reference only)
LEGACY_HEAD = "legacy_head"
CONTEXT_FORMAT = "generator_blocks"

# Frozen sets (frozen_r1.json, read by r1_frozen.load_frozen); sizes fixed by the prereg.
SLICE_SIZES = {"G01": 56, "G15": 11, "G02": 9}
DAMAGED_UNION_SIZE = 64
GANS_SUBSET_SIZE = 200

VREC, MRR = "verse_recall_at_k", "mrr"
ANCHOR, HIT = "anchor_coverage_at_k", "hit_rate"
STRICT, ZH, COVERAGE = "ragas_faithfulness_strict", "ragas_faithfulness", "coverage"
INVALID = "invalid"     # quick_faithfulness_eval row flag: "infra" / "generation" / None

# Request overrides the prereg forbids ("backend 預設設定，不覆寫 graph 策略、α").
_OVERRIDES = ("fusion_alpha", "graph_strategies_requested")
_EPS = 1e-12


class GateInputError(ValueError):
    """Inputs that do not match the pre-registered protocol; nothing is judged."""


class Label(NamedTuple):
    question_type: str
    family: str


@dataclass(frozen=True)
class GtLabels:
    """GT v2 as the gate needs it: its sha256 and each question's type and family."""
    sha256: str
    labels: Mapping[str, Label]


# ---------------------------------------------------------------- frozen sets

def frozen_problems(frozen: FrozenR1, known_ids: Collection[str]) -> list[str]:
    """What in r1_frozen.load_frozen's sets contradicts the prereg sizes or GT v2."""
    subs = frozen.sub_slices
    problems = [f"sub-slice {n} has {len(subs.get(n, ()))} questions, prereg {k}"
                for n, k in SLICE_SIZES.items() if len(subs.get(n, ())) != k]
    if len(frozen.damaged_union) != DAMAGED_UNION_SIZE:
        problems.append(f"damaged union has {len(frozen.damaged_union)} questions, "
                        f"prereg {DAMAGED_UNION_SIZE}")
    if len(frozen.gans_subset) != GANS_SUBSET_SIZE:
        problems.append(f"gans_subset has {len(frozen.gans_subset)} questions, "
                        f"prereg {GANS_SUBSET_SIZE}")
    unknown = sorted((frozen.damaged_union | frozen.gans_subset) - set(known_ids))
    if unknown:
        problems.append(f"frozen ids not in GT v2: {unknown}")
    return [f"frozen sets: {p}" for p in problems]


# ---------------------------------------------------------------- statistics

def _number(value: Any) -> float | None:
    """A finite metric value, or None (missing, non-numeric, NaN)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        return None
    return float(value)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(diffs: Sequence[float], n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """n, mean and percentile 95% bootstrap CI of paired differences (None when empty)."""
    if not diffs:
        return {"n": 0, "mean": None, "ci": None}
    lo, hi = bootstrap_ci(list(diffs), n_boot=n_boot, seed=seed, level=LEVEL)
    return {"n": len(diffs), "mean": _mean(diffs), "ci": [lo, hi]}


def noise_band(ci: Sequence[float] | None) -> float | None:
    """B = max(|lower|, |upper|) of an A/A CI."""
    return None if ci is None else max(abs(ci[0]), abs(ci[1]))


def margin(band: float | None, floor: float) -> float | None:
    """max(floor, 2·band)."""
    return None if band is None else max(floor, 2 * band)


def sign(x: float) -> int:
    return 0 if abs(x) <= _EPS else (1 if x > 0 else -1)


def win_loss(diffs: Sequence[float]) -> dict[str, int]:
    signs = Counter(sign(d) for d in diffs)
    return {"wins": signs[1], "losses": signs[-1], "ties": signs[0]}


def _ci_lower_above(summary: dict, threshold: float | None) -> bool:
    return summary["ci"] is not None and threshold is not None and summary["ci"][0] > threshold


# ---------------------------------------------------------------- pairing

def invalid_ids(per_question: Mapping[str, dict]) -> list[str]:
    return sorted(q for q, e in per_question.items() if e.get("invalid"))


def pair_runs(control: Mapping[str, dict], treatment: Mapping[str, dict]) -> dict:
    """Questions valid in both runs; those invalid in either, or in one run only, are dropped."""
    common = control.keys() & treatment.keys()
    dropped = sorted(q for q in common
                     if control[q].get("invalid") or treatment[q].get("invalid"))
    ids = sorted(common - set(dropped))
    return {"n": len(ids), "ids": ids, "dropped_invalid": dropped,
            "missing": sorted(control.keys() ^ treatment.keys())}


def metric_diffs(control: Mapping[str, dict], treatment: Mapping[str, dict],
                 ids: Sequence[str], metric: str) -> list[float]:
    """treatment − control of ``metric`` per paired question."""
    diffs = []
    for q in ids:
        a, b = _number(control[q].get(metric)), _number(treatment[q].get(metric))
        if a is None or b is None:
            raise GateInputError(f"{q}: {metric} missing in a valid paired question")
        diffs.append(b - a)
    return diffs


def route_differs(control: Mapping[str, dict], treatment: Mapping[str, dict],
                  ids: Sequence[str]) -> dict:
    differ = [q for q in ids if control[q].get("route") != treatment[q].get("route")]
    return {"n": len(differ), "ids": differ}


# ---------------------------------------------------------------- validation

def _retrieval_run_problems(name: str, run: Mapping) -> list[str]:
    meta, config = run.get("meta") or {}, run.get("config") or {}
    problems = []
    if not isinstance(run.get("per_question"), Mapping):
        problems.append(f"{name}: no per_question")
    if meta.get("gt_version") != GT_VERSION:
        problems.append(f"{name}: gt_version {meta.get('gt_version')!r}, the gate needs GT v2")
    if not meta.get("data_build_id"):
        problems.append(f"{name}: meta has no data_build_id")
    for key, want in (("top_k", TOP_K), ("metric_k", METRIC_K)):
        if config.get(key) != want:
            problems.append(f"{name}: {key} {config.get(key)!r}, prereg {want}")
    overridden = [k for k in _OVERRIDES if config.get(k) is not None]
    if config.get("use_graph") is False:
        overridden.append("use_graph")
    if overridden:
        problems.append(f"{name}: overrides backend defaults {overridden}")
    return problems


def _cross_problems(metas: Mapping[str, Mapping], control: str, aa: str, treatment: str,
                    gt: GtLabels) -> list[str]:
    """One GT (the loaded v2), A/A on one build, the treatment on another."""
    problems = []
    shas = {n: m.get("gt_sha") for n, m in metas.items()}
    if len(set(shas.values())) != 1:
        problems.append(f"gt_sha differs across runs: {shas}")
    elif shas[control] != gt.sha256:
        problems.append(f"runs scored GT sha {shas[control]}, ground_truth.v2.json is {gt.sha256}")
    builds = {n: m.get("data_build_id") for n, m in metas.items()}
    if builds[control] != builds[aa]:
        problems.append(f"A/A runs {control} and {aa} must share a data build: {builds}")
    if builds[treatment] == builds[control]:
        problems.append(f"treatment {treatment} runs the control's build {builds[control]}")
    return problems + _encoder_problems(metas, control)


def _encoder_problems(metas: Mapping[str, Mapping], control: str) -> list[str]:
    """Every run on the control's encoder. The build id alone does not tell prod (:8000, no
    encoder report) from the control arm (:8001, E0b): both serve legacy-20261004."""
    encoders = {n: m.get("encoder_fingerprint") for n, m in metas.items()}
    missing = [n for n, e in encoders.items() if not e]
    if missing:
        return [f"{', '.join(missing)}: meta has no encoder_fingerprint (a backend without "
                "the query-tokenizer probe, e.g. prod :8000)"]
    return [f"{n} ran another encoder than the control {control}"
            for n, e in encoders.items() if e != encoders[control]]


def _same(configs: Mapping[str, Mapping], key: str) -> list[str]:
    values = {n: c.get(key) for n, c in configs.items()}
    return [] if len(set(map(repr, values.values()))) == 1 else [f"{key} differs: {values}"]


def validate_retrieval_runs(runs: Mapping[str, Mapping], gt: GtLabels, frozen: FrozenR1) -> None:
    """Refuse L1 / L2 / R runs that the prereg does not allow to be compared."""
    problems = [p for name, run in runs.items() for p in _retrieval_run_problems(name, run)]
    problems += frozen_problems(frozen, gt.labels)
    if not problems:
        metas = {n: run.get("meta") or {} for n, run in runs.items()}
        configs = {n: run.get("config") or {} for n, run in runs.items()}
        problems += _cross_problems(metas, "L1", "L2", "R", gt)
        problems += _same(configs, "metric_version")
        unknown = sorted({q for run in runs.values() for q in run["per_question"]}
                         - set(gt.labels))
        if unknown:
            problems.append(f"question ids not in GT v2: {unknown}")
    if problems:
        raise GateInputError("; ".join(problems))


# ---------------------------------------------------------------- retrieval gate

def aa_noise(l1: Mapping[str, dict], l2: Mapping[str, dict],
             n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """The A/A noise bands and the margins δ, δ_wl they set."""
    pairing = pair_runs(l1, l2)
    ids = pairing["ids"]
    vrec = summarize(metric_diffs(l1, l2, ids, VREC), n_boot, seed)
    mrr = metric_diffs(l1, l2, ids, MRR)
    wl = win_loss(mrr)
    band = noise_band(vrec["ci"])
    band_wl = (wl["wins"] + wl["losses"]) / len(ids) if ids else None
    return {"pairing": pairing, "delta_vrec": vrec, "B": band, "delta": margin(band, DELTA_FLOOR),
            "mrr_win_loss": wl, "B_wl": band_wl, "delta_wl": margin(band_wl, DELTA_FLOOR),
            "delta_mrr": summarize(mrr, n_boot, seed)}


def c1_vrec(l1, r, ids, delta, n_boot=N_BOOT, seed=SEED) -> dict:
    summary = summarize(metric_diffs(l1, r, ids, VREC), n_boot, seed)
    threshold = None if delta is None else -delta
    return {**summary, "threshold": threshold, "passed": _ci_lower_above(summary, threshold)}


def c2_mrr(l1, r, ids, delta_wl, n_boot=N_BOOT, seed=SEED) -> dict:
    """Mean per-question sign of ΔMRR against −δ_wl; ΔMRR and the sign test are reported."""
    diffs = metric_diffs(l1, r, ids, MRR)
    summary = summarize([sign(d) for d in diffs], n_boot, seed)
    threshold = None if delta_wl is None else -delta_wl
    wl = win_loss(diffs)
    return {"mean_sign": summary, "threshold": threshold,
            "passed": _ci_lower_above(summary, threshold),
            "delta_mrr": summarize(diffs, n_boot, seed), **wl,
            "sign_test_p": sign_test_p(wl["wins"], wl["losses"])}


def c3_damaged(l1, r, ids, frozen: FrozenR1, n_boot=N_BOOT, seed=SEED) -> dict:
    """Mean Δvrec@6 on the damaged union ≥ 0 (float noise tolerated); sub-slices reported."""
    paired = set(ids)

    def _slice(members: frozenset[str]) -> dict:
        qs = sorted(members & paired)
        return {**summarize(metric_diffs(l1, r, qs, VREC), n_boot, seed),
                "unpaired": sorted(members - paired)}

    union = _slice(frozen.damaged_union)
    return {"union": union, "threshold": 0.0,
            "passed": union["mean"] is not None and union["mean"] >= -_EPS,
            "sub_slices": {name: _slice(frozen.sub_slices[name]) for name in SUB_SLICES}}


def _rerun_reason(pair: str, pairing: dict, arms: Mapping[str, Mapping[str, dict]]) -> list[str]:
    if pairing["n"] >= MIN_PAIRED:
        return []
    culprits = [f"{n} invalid {len(invalid_ids(pq))}" for n, pq in arms.items() if invalid_ids(pq)]
    if pairing["missing"]:
        culprits.append(f"{len(pairing['missing'])} questions in one run only")
    return [f"rerun arm: {pair} has {pairing['n']} paired questions (< {MIN_PAIRED}; "
            f"{', '.join(culprits) or 'questions missing from both runs'})"]


def _retrieval_fail_reasons(aa: dict, pairing: dict, criteria: dict,
                            pq: Mapping[str, Mapping[str, dict]]) -> list[str]:
    reasons = _rerun_reason("A/A L1–L2", aa["pairing"], {"L1": pq["L1"], "L2": pq["L2"]})
    reasons += _rerun_reason("R–L1", pairing, {"L1": pq["L1"], "R": pq["R"]})
    c1, c2, c3 = criteria["C1"], criteria["C2"], criteria["C3"]
    if not c1["passed"]:
        reasons.append(f"C1: CI lower of Δvrec@6 {_fmt(_lower(c1))} not > {_fmt(c1['threshold'])}")
    if not c2["passed"]:
        reasons.append(f"C2: CI lower of mean sign(ΔMRR) {_fmt(_lower(c2['mean_sign']))} "
                       f"not > {_fmt(c2['threshold'])}")
    if not c3["passed"]:
        reasons.append(f"C3: damaged-union mean Δvrec@6 {_fmt(c3['union']['mean'])} < 0")
    return reasons


def _lower(summary: dict) -> float | None:
    return None if summary["ci"] is None else summary["ci"][0]


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.4f}"


def retrieval_gate(l1: Mapping, l2: Mapping, treatment: Mapping, frozen: FrozenR1, gt: GtLabels,
                   n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """G-NONINF over three quick_retrieval_eval results (control L1, A/A L2, treatment R)."""
    runs = {"L1": l1, "L2": l2, "R": treatment}
    validate_retrieval_runs(runs, gt, frozen)
    pq = {name: run["per_question"] for name, run in runs.items()}
    aa = aa_noise(pq["L1"], pq["L2"], n_boot, seed)
    pairing = pair_runs(pq["L1"], pq["R"])
    ids = pairing["ids"]
    criteria = {
        "C1": c1_vrec(pq["L1"], pq["R"], ids, aa["delta"], n_boot, seed),
        "C2": c2_mrr(pq["L1"], pq["R"], ids, aa["delta_wl"], n_boot, seed),
        "C3": c3_damaged(pq["L1"], pq["R"], ids, frozen, n_boot, seed),
    }
    reasons = _retrieval_fail_reasons(aa, pairing, criteria, pq)
    return {
        "gate": "G-NONINF",
        "params": _params(n_boot, seed, delta_floor=DELTA_FLOOR, min_paired=MIN_PAIRED,
                          top_k=TOP_K, metric_k=METRIC_K),
        "runs": {name: _run_summary(run) for name, run in runs.items()},
        "aa": aa, "pairing": pairing, "criteria": criteria,
        "passed": not reasons, "fail_reasons": reasons,
        "report_only": retrieval_report_only(pq, aa["pairing"]["ids"], ids, gt.labels,
                                             n_boot, seed),
    }


def _params(n_boot: int, seed: int, **extra) -> dict:
    return {"n_boot": n_boot, "seed": seed, "level": LEVEL, "ci": "percentile",
            "resample": "questions with replacement", **extra}


def _run_summary(run: Mapping) -> dict:
    meta, config = run.get("meta") or {}, run.get("config") or {}
    keys = ("data_build_id", "gt_version", "gt_sha", "encoder_fingerprint")
    return {**{k: meta.get(k) for k in keys}, "metric_version": config.get("metric_version"),
            "n": len(run.get("per_question") or {}),
            "invalid": invalid_ids(run.get("per_question") or {})}


# ---------------------------------------------------------------- retrieval report-only

def strata(l1, r, ids, labels: Mapping[str, Label]) -> dict:
    """Mean Δvrec@6 and ΔMRR (R − L1) by question type, family, legacy_head vs expanded."""
    groups: dict[str, dict[str, list[str]]] = {
        "by_type": defaultdict(list), "by_family": defaultdict(list),
        "head_vs_expanded": defaultdict(list)}
    for q in ids:
        label = labels[q]
        groups["by_type"][label.question_type].append(q)
        groups["by_family"][label.family].append(q)
        head = "legacy_head" if label.family == LEGACY_HEAD else "expanded"
        groups["head_vs_expanded"][head].append(q)
    return {
        group: {key: {"n": len(qs), "delta_vrec": _mean(metric_diffs(l1, r, qs, VREC)),
                      "delta_mrr": _mean(metric_diffs(l1, r, qs, MRR))}
                for key, qs in sorted(by_key.items())}
        for group, by_key in groups.items()
    }


def large_drops(l1, r, ids, labels: Mapping[str, Label]) -> list[dict]:
    """Questions whose vrec@6 fell by 0.3 or more, worst first, for diagnosis."""
    rows = []
    for q in ids:
        a, b = l1[q][VREC], r[q][VREC]
        if b - a <= LARGE_DROP + _EPS:
            rows.append({"question_id": q, "question_type": labels[q].question_type,
                         "family": labels[q].family, "route_l1": l1[q].get("route"),
                         "route_r": r[q].get("route"), "vrec_l1": a, "vrec_r": b,
                         "delta_vrec": b - a})
    return sorted(rows, key=lambda row: (row["delta_vrec"], row["question_id"]))


def retrieval_report_only(pq: Mapping[str, Mapping[str, dict]], aa_ids, ids,
                          labels: Mapping[str, Label], n_boot=N_BOOT, seed=SEED) -> dict:
    l1, l2, r = pq["L1"], pq["L2"], pq["R"]
    return {
        "strata": strata(l1, r, ids, labels),
        "deltas": {m: {"aa": summarize(metric_diffs(l1, l2, aa_ids, m), n_boot, seed),
                       "r_vs_l1": summarize(metric_diffs(l1, r, ids, m), n_boot, seed)}
                   for m in (ANCHOR, HIT)},
        "route_differs": {"aa": route_differs(l1, l2, aa_ids),
                          "r_vs_l1": route_differs(l1, r, ids)},
        "large_drops": large_drops(l1, r, ids, labels),
    }


# ---------------------------------------------------------------- answer gate

def _answer_run_problems(name: str, run: Mapping, subset: frozenset[str]) -> list[str]:
    meta, rows = run.get("meta") or {}, run.get("samples")
    if not isinstance(rows, list):
        return [f"{name}: no samples rows"]
    problems = []
    if meta.get("gt_version") != GT_VERSION:
        problems.append(f"{name}: gt_version {meta.get('gt_version')!r}, the gate needs GT v2")
    if not meta.get("data_build_id"):
        problems.append(f"{name}: meta has no data_build_id")
    if meta.get("strict_enabled") is not True:
        problems.append(f"{name}: the strict judge did not run (strict_enabled "
                        f"{meta.get('strict_enabled')!r})")
    if meta.get("context_format") != CONTEXT_FORMAT:
        problems.append(f"{name}: context_format {meta.get('context_format')!r}, prereg "
                        f"{CONTEXT_FORMAT} (include_context)")
    if any(INVALID not in row for row in rows):
        problems.append(f"{name}: rows carry no {INVALID!r} flag, so generation failures "
                        "cannot be told from answers (rejudge with the current "
                        "quick_faithfulness_eval.py)")
    ids = Counter(str(row.get("question_id")) for row in rows)
    dups = sorted(q for q, k in ids.items() if k > 1)
    extra = sorted(set(ids) - subset)
    if dups:
        problems.append(f"{name}: repeated rows {dups}")
    if extra:
        problems.append(f"{name}: rows outside the frozen 200-question subset {extra}")
    return problems


def validate_answer_runs(runs: Mapping[str, Mapping], frozen: FrozenR1, gt: GtLabels) -> None:
    """Refuse A1 / A2 / R reports that the prereg does not allow to be compared."""
    problems = [p for name, run in runs.items()
                for p in _answer_run_problems(name, run, frozen.gans_subset)]
    problems += frozen_problems(frozen, gt.labels)
    if not problems:
        metas = {n: run.get("meta") or {} for n, run in runs.items()}
        problems += _cross_problems(metas, "A1", "A2", "R", gt)
        problems += _same(metas, "judge_provider") + _same(metas, "judge_model")
    if problems:
        raise GateInputError("; ".join(problems))


def row_values(run: Mapping, field: str, subset: Collection[str]) -> dict[str, float | None]:
    """``field`` per subset question; None for a missing row, a row flagged invalid, or a
    None / NaN value."""
    rows = {row.get("question_id"): row for row in run["samples"]}
    return {q: _number(rows[q].get(field)) if q in rows and not rows[q].get(INVALID) else None
            for q in sorted(subset)}


def invalid_rows(run: Mapping, subset: Collection[str]) -> dict[str, str]:
    """Each invalid subset question and why: "no row", the row's flag ("infra",
    "generation"), or "unjudged" (strict None / NaN)."""
    rows = {row.get("question_id"): row for row in run["samples"]}
    reasons = {}
    for q in sorted(subset):
        row = rows.get(q)
        if row is None:
            reasons[q] = "no row"
        elif row.get(INVALID):
            reasons[q] = str(row[INVALID])
        elif _number(row.get(STRICT)) is None:
            reasons[q] = "unjudged"
    return reasons


def paired_values(base: Mapping[str, float | None],
                  treat: Mapping[str, float | None]) -> list[float]:
    """treat − base over questions with a value in both."""
    return [treat[q] - base[q] for q in sorted(base)
            if base[q] is not None and treat.get(q) is not None]


def answer_gate(a1: Mapping, a2: Mapping, treatment: Mapping, frozen: FrozenR1, gt: GtLabels,
                n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """G-ANS over three quick_faithfulness_eval reports (control A1, A/A A2, treatment R)."""
    runs = {"A1": a1, "A2": a2, "R": treatment}
    validate_answer_runs(runs, frozen, gt)
    strict = {n: row_values(run, STRICT, frozen.gans_subset) for n, run in runs.items()}
    invalid = {n: invalid_rows(run, frozen.gans_subset) for n, run in runs.items()}
    aa = summarize(paired_values(strict["A1"], strict["A2"]), n_boot, seed)
    band = noise_band(aa["ci"])
    delta = margin(band, DELTA_ANS_FLOOR)
    treat = summarize(paired_values(strict["A1"], strict["R"]), n_boot, seed)
    threshold = None if delta is None else -delta
    criteria = {"delta_strict": {**treat, "threshold": threshold,
                                 "passed": _ci_lower_above(treat, threshold)},
                "no_invalid": {"n_invalid": {n: len(v) for n, v in invalid.items()},
                               "passed": not any(invalid.values())}}
    reasons = [f"{n} has {len(v)} invalid questions (rerun arm): {v}"
               for n, v in invalid.items() if v]
    if not criteria["delta_strict"]["passed"]:
        reasons.append(f"CI lower of Δstrict (R − A1) {_fmt(_lower(treat))} "
                       f"not > {_fmt(threshold)}")
    return {
        "gate": "G-ANS",
        "params": _params(n_boot, seed, delta_floor=DELTA_ANS_FLOOR,
                          subset_size=GANS_SUBSET_SIZE),
        "runs": {n: _answer_summary(run) for n, run in runs.items()},
        "aa": {"delta_strict": aa, "B_ans": band, "delta_ans": delta},
        "invalid": invalid, "criteria": criteria,
        "passed": not reasons, "fail_reasons": reasons,
        "report_only": answer_report_only(runs, frozen.gans_subset, strict, n_boot, seed),
    }


def _answer_summary(run: Mapping) -> dict:
    meta = run.get("meta") or {}
    keys = ("data_build_id", "gt_version", "gt_sha", "encoder_fingerprint", "judge_provider",
            "judge_model", "context_format", "unjudged_samples", "invalid_samples", "n_samples",
            "n_scored")
    return {k: meta.get(k) for k in keys}


def _field_report(runs: Mapping[str, Mapping], field: str, subset, n_boot, seed) -> dict:
    vals = {n: row_values(run, field, subset) for n, run in runs.items()}
    return {"mean": {n: _mean([x for x in v.values() if x is not None]) for n, v in vals.items()},
            "delta_r_vs_a1": summarize(paired_values(vals["A1"], vals["R"]), n_boot, seed),
            "delta_aa": summarize(paired_values(vals["A1"], vals["A2"]), n_boot, seed)}


def answer_report_only(runs: Mapping[str, Mapping], subset, strict, n_boot=N_BOOT,
                       seed=SEED) -> dict:
    """Absolute strict vs 0.97, zh faithfulness, and coverage when rows carry it.

    Refusals are not derivable from quick_faithfulness_eval rows and are omitted.
    """
    out: dict[str, Any] = {"strict_absolute": {
        n: {"mean": (m := _mean([x for x in v.values() if x is not None])),
            "reference": STRICT_REFERENCE,
            "below_reference": None if m is None else m < STRICT_REFERENCE}
        for n, v in strict.items()}}
    out["zh_faithfulness"] = _field_report(runs, ZH, subset, n_boot, seed)
    if any(COVERAGE in row for run in runs.values() for row in run["samples"]):
        out["coverage"] = {**_field_report(runs, COVERAGE, subset, n_boot, seed),
                           "noise_floor": COVERAGE_NOISE_FLOOR}
    return out
