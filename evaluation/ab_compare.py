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

Usage (from evaluation/):
    uv run python ab_compare.py results_quick/dense5.json results_quick/aux.json \\
        --control-ext results_quick/dense6.json --label aux_vs_dense
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.ab_compare import METRICS, compare  # noqa: E402
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("control", type=Path)
    parser.add_argument("treatment", type=Path)
    parser.add_argument("--control-ext", type=Path, default=None,
                        help="independent control run at top_k+1 for questions the treatment appended to")
    parser.add_argument("--label", default=None, help="save the full report to results_quick/ab_<label>.json")
    args = parser.parse_args()

    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
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
    if args.label:
        out = _OUT_DIR / f"ab_{args.label}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
