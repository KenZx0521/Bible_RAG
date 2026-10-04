"""
k-aligned paired comparison of two quick_retrieval_eval runs.

Inputs are quick_retrieval_eval output files (per_question metrics computed at
config.metric_k, with source_detail carrying per-passage gold flags). Every
run being compared must have been scored at the same metric k.

Auxiliary arms (event_registry) append passages after the top-k, so on those
questions the treatment holds k+1 passages. Comparing it with the control's k
would make the treatment unable to lose; such questions are instead compared
with an extended control: an independent request at top_k=k+1 (a prefix of a
larger run is not equivalent — chapter-pin depends on top_k).
"""

from __future__ import annotations

from .ab_stats import (
    bootstrap_ci,
    holm,
    ledger_entry,
    sign_flip_p,
    sign_test_p,
    summarize_ledger,
)

METRICS = ("verse_recall_at_k", "anchor_coverage_at_k", "mrr", "hit_rate")
_EPS = 1e-9


def run_k(run: dict) -> int:
    """The k a run's metrics were computed at (legacy files: their top_k)."""
    cfg = run.get("config", {})
    return cfg.get("metric_k") or cfg.get("top_k", 5)


def _top_k(run: dict) -> int:
    return run.get("config", {}).get("top_k", 5)


def _appended(entry: dict, top_k: int) -> bool:
    return len(entry.get("sources", [])) > top_k


def _detail(entry: dict) -> list[dict]:
    return entry.get("source_detail") or [{"id": s} for s in entry.get("sources", [])]


def compose_baseline(control: dict, treatment: dict, control_ext: dict | None = None) -> dict:
    """Per-question control entry, k-aligned with the treatment.

    Questions where the treatment appended passages take the extended control;
    all others the regular control. Raises if an appended question has no
    k-aligned control, or one shorter than the treatment (a control_ext run
    without --top-k k+1 would let the treatment never lose).
    """
    top_k = _top_k(treatment)
    pc, pt = control["per_question"], treatment["per_question"]
    ext = control_ext["per_question"] if control_ext else {}
    base: dict[str, dict] = {}
    missing: list[str] = []
    short: list[str] = []
    for qid in sorted(set(pc) & set(pt)):
        if _appended(pt[qid], top_k):
            if qid not in ext:
                missing.append(qid)
                continue
            if len(ext[qid].get("sources", [])) < len(pt[qid]["sources"]):
                short.append(qid)
            base[qid] = ext[qid]
        else:
            base[qid] = pc[qid]
    if missing:
        raise ValueError(
            f"treatment appended passages beyond top_k={top_k} on {missing} but no "
            "extended control (independent top_k+1 run) covers them"
        )
    if short:
        raise ValueError(
            f"extended control is shorter than the treatment on {short}; "
            "it must be an independent request at the treatment's length"
        )
    return base


def _metric_stats(diffs: list[float]) -> dict:
    lo, hi = bootstrap_ci(diffs)
    wins = sum(d > _EPS for d in diffs)
    losses = sum(d < -_EPS for d in diffs)
    return {
        "n": len(diffs),
        "mean_delta": round(sum(diffs) / len(diffs), 5) if diffs else 0.0,
        "ci95": [round(lo, 5), round(hi, 5)],
        "wins": wins,
        "losses": losses,
        "sign_flip_p": round(sign_flip_p(diffs), 5),
        "sign_test_p": round(sign_test_p(wins, losses), 5),
    }


def compare(
    control: dict,
    treatment: dict,
    control_ext: dict | None = None,
    families: dict[str, str] | None = None,
) -> dict:
    """Paired treatment − control report: invariants, stats, negatives, ledger."""
    runs = [control, treatment] + ([control_ext] if control_ext else [])
    ks = sorted({run_k(r) for r in runs})
    if len(ks) > 1:
        raise ValueError(f"runs were scored at different metric k {ks}; rerun with one --metric-k")
    versions = {r.get("config", {}).get("metric_version") for r in runs}
    if len(versions) > 1:
        raise ValueError(
            f"runs were scored with different metric version {sorted(map(str, versions))} "
            "(gold parsing or scoring code changed); rescore them with one version"
        )

    top_k = _top_k(treatment)
    pc, pt = control["per_question"], treatment["per_question"]
    ext = control_ext["per_question"] if control_ext else {}
    qids = sorted(set(pc) & set(pt))

    def invalid(qid: str) -> bool:
        return any(arm.get(qid, {}).get("invalid") for arm in (pc, pt, ext))

    excluded = [q for q in qids if invalid(q)]
    valid = [q for q in qids if not invalid(q)]

    base = compose_baseline(
        {"config": control.get("config", {}), "per_question": {q: pc[q] for q in valid}},
        {"config": treatment.get("config", {}), "per_question": {q: pt[q] for q in valid}},
        control_ext,
    )
    for q in valid:
        if base[q]["sources"] == pt[q]["sources"] and any(
            base[q][m] != pt[q][m] for m in METRICS
        ):
            raise ValueError(
                f"{q}: identical source lists scored differently — the runs used "
                "different gold references or scoring code"
            )

    # Every arm a question's comparison uses must share its route: the intent
    # classifier samples at temperature 0.1, so routes drift between requests.
    route_mismatch = [
        q for q in valid
        if len({pc[q].get("route"), pt[q].get("route"), base[q].get("route")}) > 1
    ]
    same = [q for q in valid if q not in set(route_mismatch)]

    touched = [q for q in valid if _appended(pt[q], top_k)]
    core_mismatch = [q for q in same if pt[q]["sources"][:top_k] != pc[q]["sources"][:top_k]]

    subsets = {"all": same, "touched": [q for q in touched if q in set(same)]}
    if families:
        subsets["legacy"] = [q for q in same if families.get(q, "legacy_head") == "legacy_head"]
        subsets["expanded"] = [q for q in same if families.get(q, "legacy_head") != "legacy_head"]

    stats: dict[str, dict] = {}
    holm_adj: dict[str, dict] = {}
    for name, members in subsets.items():
        stats[name] = {
            m: _metric_stats([pt[q][m] - base[q][m] for q in members]) for m in METRICS
        }
        holm_adj[name] = {
            m: round(p, 5)
            for m, p in holm({m: s["sign_flip_p"] for m, s in stats[name].items()}).items()
        }

    negatives = {
        m: [q for q in same if pt[q][m] - base[q][m] < -_EPS] for m in METRICS
    }
    ledger = {q: ledger_entry(_detail(base[q]), _detail(pt[q])) for q in same}

    return {
        "metric_k": ks[0],
        "top_k": top_k,
        "n": len(same),
        "excluded_invalid": excluded,
        "route_mismatch": route_mismatch,
        # Questions where an arm reported a (non-fatal) strategy error.
        "with_strategy_errors": [
            q for q in valid
            if any(arm.get(q, {}).get("strategy_errors") for arm in (pc, pt, ext))
        ],
        "invariants": {
            "core_identical": len(same) - len(core_mismatch),
            "core_mismatch": core_mismatch,
            "touched": touched,
        },
        "stats": stats,
        "holm": holm_adj,
        "negatives": negatives,
        "ledger_summary": summarize_ledger(ledger),
        "ledger": ledger,
    }
