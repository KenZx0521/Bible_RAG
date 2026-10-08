"""
k-aligned paired comparison of two quick_retrieval_eval runs, and the identity
check behind ab_compare.py --require-identical / d3_gate.py.

Inputs are quick_retrieval_eval output files (per_question metrics computed at
config.metric_k, with source_detail carrying per-passage gold flags). Every
run being compared must have been scored at the same metric k.

Every run compared must also have been scored against one ground truth: the
same gt_version and gt_sha in its meta (runs from before the meta record carry
neither, and pair only with each other). Runs of different data builds may be
compared — that is what an R1 comparison is — and each arm's data_build_id is
reported.

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
GT_KEYS = ("gt_version", "gt_sha")
_EPS = 1e-9


def same_gt(runs: dict[str, dict]) -> dict:
    """The shared ground truth and each arm's data_build_id; raise if the GT differs."""
    metas = {arm: run.get("meta") or {} for arm, run in runs.items()}
    gts = {arm: tuple(meta.get(k) for k in GT_KEYS) for arm, meta in metas.items()}
    if len(set(gts.values())) > 1:
        shown = ", ".join(f"{arm} {v}/{(sha or '-')[:12]}" for arm, (v, sha) in gts.items())
        raise ValueError(f"runs were scored against different ground truth ({shown}); "
                         "score every arm with one --gt")
    gt = dict(zip(GT_KEYS, next(iter(gts.values()))))
    return {"gt": gt, "builds": {arm: meta.get("data_build_id") for arm, meta in metas.items()}}


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


def _scoring(control: dict, treatment: dict, control_ext: dict | None) -> tuple[int, dict]:
    """The metric k the runs share and their GT/builds; raise unless they were scored alike."""
    arms = {"control": control, "treatment": treatment}
    if control_ext:
        arms["control_ext"] = control_ext
    provenance = same_gt(arms)
    ks = sorted({run_k(r) for r in arms.values()})
    if len(ks) > 1:
        raise ValueError(f"runs were scored at different metric k {ks}; rerun with one --metric-k")
    versions = {r.get("config", {}).get("metric_version") for r in arms.values()}
    if len(versions) > 1:
        raise ValueError(
            f"runs were scored with different metric version {sorted(map(str, versions))} "
            "(gold parsing or scoring code changed); rescore them with one version"
        )
    return ks[0], provenance


def _require_consistent_scores(qids: list[str], base: dict, pt: dict) -> None:
    for q in qids:
        if base[q]["sources"] == pt[q]["sources"] and any(
            base[q][m] != pt[q][m] for m in METRICS
        ):
            raise ValueError(
                f"{q}: identical source lists scored differently — the runs used "
                "different gold references or scoring code"
            )


def _subset_stats(subsets: dict[str, list[str]], pt: dict, base: dict) -> tuple[dict, dict]:
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
    return stats, holm_adj


def _subsets(same: list[str], touched: list[str], families: dict[str, str] | None) -> dict:
    subsets = {"all": same, "touched": [q for q in touched if q in set(same)]}
    if families:
        subsets["legacy"] = [q for q in same if families.get(q, "legacy_head") == "legacy_head"]
        subsets["expanded"] = [q for q in same if families.get(q, "legacy_head") != "legacy_head"]
    return subsets


def _with_strategy_errors(qids: list[str], *arms: dict) -> list[str]:
    """Questions where an arm reported a (non-fatal) strategy error."""
    return [q for q in qids if any(arm.get(q, {}).get("strategy_errors") for arm in arms)]


def compare(
    control: dict,
    treatment: dict,
    control_ext: dict | None = None,
    families: dict[str, str] | None = None,
) -> dict:
    """Paired treatment − control report: invariants, stats, negatives, ledger."""
    metric_k, provenance = _scoring(control, treatment, control_ext)
    top_k = _top_k(treatment)
    pc, pt = control["per_question"], treatment["per_question"]
    ext = control_ext["per_question"] if control_ext else {}
    qids = sorted(set(pc) & set(pt))
    excluded = [q for q in qids if any(arm.get(q, {}).get("invalid") for arm in (pc, pt, ext))]
    valid = [q for q in qids if q not in set(excluded)]

    base = compose_baseline(
        {"config": control.get("config", {}), "per_question": {q: pc[q] for q in valid}},
        {"config": treatment.get("config", {}), "per_question": {q: pt[q] for q in valid}},
        control_ext,
    )
    _require_consistent_scores(valid, base, pt)

    # Every arm a question's comparison uses must share its route: the intent
    # classifier samples at temperature 0.1, so routes drift between requests.
    route_mismatch = [
        q for q in valid
        if len({pc[q].get("route"), pt[q].get("route"), base[q].get("route")}) > 1
    ]
    same = [q for q in valid if q not in set(route_mismatch)]
    touched = [q for q in valid if _appended(pt[q], top_k)]
    core_mismatch = [q for q in same if pt[q]["sources"][:top_k] != pc[q]["sources"][:top_k]]
    invariants = {"core_identical": len(same) - len(core_mismatch),
                  "core_mismatch": core_mismatch, "touched": touched}
    stats, holm_adj = _subset_stats(_subsets(same, touched, families), pt, base)
    ledger = {q: ledger_entry(_detail(base[q]), _detail(pt[q])) for q in same}

    return {
        **provenance,
        "metric_k": metric_k,
        "top_k": top_k,
        "n": len(same),
        "excluded_invalid": excluded,
        "route_mismatch": route_mismatch,
        "with_strategy_errors": _with_strategy_errors(valid, pc, pt, ext),
        "invariants": invariants,
        "stats": stats,
        "holm": holm_adj,
        "negatives": {m: [q for q in same if pt[q][m] - base[q][m] < -_EPS] for m in METRICS},
        "ledger_summary": summarize_ledger(ledger),
        "ledger": ledger,
    }


# --- identity gate (D3: a data or image change must not move default retrieval) --

# Request settings two runs must share for their passages to be comparable.
_REQUEST_KEYS = ("top_k", "use_graph", "fusion_alpha", "graph_strategies_requested")


def _require_context(run: dict, arm: str) -> None:
    lacking = sorted(q for q, e in run["per_question"].items()
                     if not isinstance(e.get("context_sha"), str))
    if not run.get("config", {}).get("include_context") or lacking:
        raise ValueError(
            f"{arm} run carries no context digests ({len(lacking)} questions without "
            "context_sha); rerun quick_retrieval_eval.py with --include-context"
        )


def _context_positions(control: dict, treatment: dict) -> list[int]:
    """Passages whose own block changed; only meaningful when the ids match."""
    if control["sources"] != treatment["sources"]:
        return []
    pairs = zip(control.get("source_detail") or [], treatment.get("source_detail") or [])
    return [i for i, (a, b) in enumerate(pairs)
            if a.get("context_sha256") != b.get("context_sha256")]


def passage_diff(control: dict, treatment: dict, top_k: int) -> dict:
    """What differs between two answers to one question: core, appended, context."""
    diff: dict[str, dict] = {}
    for part, cut in (("core", slice(None, top_k)), ("appended", slice(top_k, None))):
        a, b = control["sources"][cut], treatment["sources"][cut]
        if a != b:
            diff[part] = {"control": a, "treatment": b}
    if control["context_sha"] != treatment["context_sha"]:
        diff["context_sha"] = {
            "control": control["context_sha"],
            "treatment": treatment["context_sha"],
            "positions": _context_positions(control, treatment),
        }
    return diff


def _strategies_check(control: dict, treatment: dict, qids: list[str]) -> dict:
    pc, pt = control["per_question"], treatment["per_question"]
    ca = control.get("config", {}).get("graph_strategies_applied")
    ta = treatment.get("config", {}).get("graph_strategies_applied")
    unreported = [q for q in qids
                  if pc[q].get("graph_strategies") is None or pt[q].get("graph_strategies") is None]
    differing = [q for q in qids if pc[q].get("graph_strategies") != pt[q].get("graph_strategies")]
    return {
        "identical": ca == ta and not differing and not unreported,
        "control": ca,
        "treatment": ta,
        "per_question_mismatch": differing,
        # A backend that does not report what it applied cannot be vouched for.
        "unreported": unreported,
    }


def _require_same_request(control: dict, treatment: dict) -> None:
    cc, tc = control.get("config", {}), treatment.get("config", {})
    differing = [k for k in _REQUEST_KEYS if cc.get(k) != tc.get(k)]
    if differing:
        raise ValueError(
            f"runs were requested with different {differing}: "
            + ", ".join(f"{k} {cc.get(k)!r} vs {tc.get(k)!r}" for k in differing)
        )


def identity_report(control: dict, treatment: dict) -> dict:
    """Do two runs retrieve identically? (ab_compare --require-identical, d3_gate).

    Same-route questions must agree on the top_k core passages, the passages
    appended after it, and the context digest. Route mismatches (the intent
    classifier samples at temperature 0.1) are listed apart for d3_gate to
    re-ask. Invalid or unpaired questions and differing applied graph
    strategies also fail. Runs without context digests are refused.
    """
    _require_context(control, "control")
    _require_context(treatment, "treatment")
    provenance = same_gt({"control": control, "treatment": treatment})
    _require_same_request(control, treatment)

    pc, pt = control["per_question"], treatment["per_question"]
    qids = sorted(set(pc) & set(pt))
    if not qids:
        raise ValueError("the runs share no question; nothing to compare")
    top_k = control.get("config", {}).get("top_k", 5)
    invalid = [q for q in qids if pc[q].get("invalid") or pt[q].get("invalid")]
    valid = [q for q in qids if q not in set(invalid)]
    route_mismatch = [q for q in valid if pc[q].get("route") != pt[q].get("route")]
    same = [q for q in valid if q not in set(route_mismatch)]
    mismatches = {q: d for q in same if (d := passage_diff(pc[q], pt[q], top_k))}
    unpaired = {"control_only": sorted(set(pc) - set(pt)),
                "treatment_only": sorted(set(pt) - set(pc))}
    strategies = _strategies_check(control, treatment, qids)

    return {
        **provenance,
        "top_k": top_k,
        "n_paired": len(qids),
        "unpaired": unpaired,
        "invalid": invalid,
        "route_mismatch": route_mismatch,
        "routes": {q: {"control": pc[q].get("route"), "treatment": pt[q].get("route")}
                   for q in route_mismatch},
        "same_route": len(same),
        "identical": len(same) - len(mismatches),
        "mismatches": mismatches,
        "strategies": strategies,
        # Route mismatches do not fail here; d3_gate re-asks them.
        "passed": (not mismatches and not invalid and strategies["identical"]
                   and not unpaired["control_only"] and not unpaired["treatment_only"]),
    }
