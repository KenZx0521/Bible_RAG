#!/usr/bin/env python3
"""Paired, k-aligned comparison of quick_retrieval_eval runs.

Reports, for treatment − control on same-route questions:
  * invariants — how many treatment top-k lists equal the control's (an
    auxiliary arm must leave all of them untouched), which questions the
    treatment touched, which ones the intent classifier routed differently;
  * per metric (verse_recall / anchor_coverage / mrr / hit): mean Δ with a
    95% bootstrap CI, wins/losses, sign-flip p (primary), exact sign-test p,
    and Holm-adjusted p across the metric family — for all questions, the
    touched ones, and the legacy-100 / expanded-400 strata;
  * every question where a metric dropped;
  * the change ledger: identical / order_only / nongold_swap / gold_in /
    gold_out / gold_swap per question.

--require-identical replaces the report with the D3 identity check: every
same-route question must keep its core top-k, its appended passages and its
context digest (runs need quick_retrieval_eval.py --include-context), and both
runs must apply the same graph strategies. Differences are listed and the exit
code is 1. Route mismatches are listed apart and not judged: PASS (exit 0)
names how many there were, and only d3_gate.py re-asks them and holds the
residual to r0.

Usage (from evaluation/):
    uv run python ab_compare.py results_quick/dense5.json results_quick/aux.json \\
        --control-ext results_quick/dense6.json --label aux_vs_dense
    uv run python ab_compare.py results_quick/d3_prod_w1.json results_quick/d3_stg_w1.json \\
        --require-identical
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.ab_compare import METRICS, compare, identity_report  # noqa: E402
from src.data_loader import load_ground_truth  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parent / "results_quick"


def _fmt_p(p: float) -> str:
    return f"{p:.3f}" if p >= 0.001 else "<.001"


def print_report(report: dict) -> None:
    inv = report["invariants"]
    print(f"\nmetric k={report['metric_k']}  top_k={report['top_k']}  same-route n={report['n']}")
    print(f"excluded (invalid): {report['excluded_invalid'] or '-'}")
    print(f"route mismatch ({len(report['route_mismatch'])}): {report['route_mismatch'] or '-'}")
    print(f"with strategy errors: {report['with_strategy_errors'] or '-'}")
    print(f"core top-{report['top_k']} identical: {inv['core_identical']}/{report['n']}"
          f"  mismatch: {inv['core_mismatch'] or '-'}")
    print(f"touched (passages appended): {len(inv['touched'])}")
    for subset, by_metric in report["stats"].items():
        print(f"\n[{subset}]")
        for m in METRICS:
            s = by_metric[m]
            print(f"  {m:22s} n={s['n']:3d}  Δ={s['mean_delta']:+.4f} "
                  f"[{s['ci95'][0]:+.4f},{s['ci95'][1]:+.4f}]  W/L={s['wins']}/{s['losses']}  "
                  f"flip p={_fmt_p(s['sign_flip_p'])} (Holm {_fmt_p(report['holm'][subset][m])})  "
                  f"sign p={_fmt_p(s['sign_test_p'])}")
    print("\nnegatives:")
    for m, qids in report["negatives"].items():
        print(f"  {m}: {qids or '-'}")
    print(f"\nledger: {report['ledger_summary']}")


def print_identity(report: dict) -> None:
    """Identity check summary, then every difference in full."""
    strat = report["strategies"]
    print(f"\nidentity check (top_k={report['top_k']}): paired n={report['n_paired']}  "
          f"same-route {report['identical']}/{report['same_route']} identical")
    print(f"unpaired: control-only {report['unpaired']['control_only'] or '-'}  "
          f"treatment-only {report['unpaired']['treatment_only'] or '-'}")
    print(f"invalid: {report['invalid'] or '-'}")
    print(f"graph strategies applied: {'identical' if strat['identical'] else 'DIFFERENT'}"
          f"  control={strat['control']}  treatment={strat['treatment']}")
    if strat["per_question_mismatch"] or strat["unreported"]:
        print(f"  per-question mismatch: {strat['per_question_mismatch'] or '-'}"
              f"  unreported: {strat['unreported'] or '-'}")
    print(f"route mismatch ({len(report['route_mismatch'])}):")
    for qid, routes in report["routes"].items():
        print(f"  {qid}: {routes['control']} → {routes['treatment']}")
    print(f"same-route differences ({len(report['mismatches'])}):")
    for qid, diff in report["mismatches"].items():
        for part, d in diff.items():
            extra = f"  positions={d['positions']}" if part == "context_sha" else ""
            print(f"  {qid} {part}: {d['control']} → {d['treatment']}{extra}")


def _identity_verdict(report: dict) -> str:
    """PASS judges same-route questions only; say so when some were routed apart."""
    if not report["passed"]:
        return "FAIL"
    n = len(report["route_mismatch"])
    if not n:
        return "PASS"
    return f"PASS ({n} route mismatch{'es' if n > 1 else ''} not judged; run d3_gate.py)"


def _save(report: dict, label: str | None) -> None:
    if label:
        out = _OUT_DIR / f"ab_{label}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("control", type=Path)
    parser.add_argument("treatment", type=Path)
    parser.add_argument("--control-ext", type=Path, default=None,
                        help="independent control run at top_k+1 for questions the treatment appended to")
    parser.add_argument("--label", default=None, help="save the full report to results_quick/ab_<label>.json")
    parser.add_argument("--require-identical", action="store_true",
                        help="D3 identity check instead of the A/B report; exit 1 on any "
                             "same-route difference (needs --include-context runs)")
    args = parser.parse_args()
    if args.require_identical and args.control_ext:
        parser.error("--control-ext does not apply to --require-identical")

    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    if args.require_identical:
        try:
            report = identity_report(load(args.control), load(args.treatment))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        report["inputs"] = {"control": str(args.control), "treatment": str(args.treatment)}
        print_identity(report)
        print(f"\nidentity: {_identity_verdict(report)}")
        _save(report, args.label)
        return 0 if report["passed"] else 1

    families = {g.question_id: g.family or "legacy_head" for g in load_ground_truth()}
    report = compare(
        load(args.control), load(args.treatment),
        load(args.control_ext) if args.control_ext else None,
        families=families,
    )
    report["inputs"] = {
        "control": str(args.control), "treatment": str(args.treatment),
        "control_ext": str(args.control_ext) if args.control_ext else None,
    }
    print_report(report)
    _save(report, args.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
