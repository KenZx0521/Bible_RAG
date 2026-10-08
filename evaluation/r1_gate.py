#!/usr/bin/env python3
"""R1 gates, as pre-registered in experiments/2026-10-08_r1/prereg.md.

  retrieval  G-NONINF over three quick_retrieval_eval.py results: the A/A pair
             of the control arm (L1, L2; L1 is the control) and the treatment
             R. C1 Δvrec@6, C2 MRR win/loss sign, C3 damaged slice.
  answer     G-ANS over three quick_faithfulness_eval.py reports on the frozen
             200-question subset: A/A (A1, A2; A1 is the control) and R.

The frozen sets come from frozen_r1.json through src.r1_frozen.load_frozen;
question types and families from GT v2 (ground_truth.v2.json, whose sha must
be the runs'). Statistics and verdicts are src/noninf.py's. The report JSON
holds every number; stdout shows a summary. Nothing is queried or judged.

Exit code: 0 PASS, 1 FAIL, 2 input error (refused before judging).

Usage (from evaluation/):
    .venv/bin/python r1_gate.py retrieval \\
        --aa results_quick/r1_L1.json results_quick/r1_L2.json \\
        --treatment results_quick/r1_R.json \\
        --frozen experiments/2026-10-08_r1/frozen_r1.json \\
        --out experiments/2026-10-08_r1/gate_retrieval.json
    .venv/bin/python r1_gate.py answer \\
        --aa results_quick/r1_ans_A1.json results_quick/r1_ans_A2.json \\
        --treatment results_quick/r1_ans_R.json \\
        --frozen experiments/2026-10-08_r1/frozen_r1.json \\
        --out experiments/2026-10-08_r1/gate_answer.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import noninf  # noqa: E402
from src.data_loader import load_gt  # noqa: E402
from src.r1_frozen import load_frozen  # noqa: E402

PREREG = "evaluation/experiments/2026-10-08_r1/prereg.md"
EXIT_PASS, EXIT_FAIL, EXIT_INPUT = 0, 1, 2


def gt_labels() -> noninf.GtLabels:
    """GT v2 (frozen sha checked by the loader): its sha and each question's type and family."""
    gt = load_gt("v2")
    return noninf.GtLabels(gt.sha256, {
        item.question_id: noninf.Label(item.question_type, item.family or noninf.LEGACY_HEAD)
        for item in gt.items})


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise noninf.GateInputError(f"{path}: not a JSON object")
    return data


def _check_out(out: Path, inputs: Sequence[Path], overwrite: bool) -> None:
    """Never replace an input; replace an earlier report only with --overwrite."""
    for path in inputs:
        if out.exists() and out.resolve() == path.resolve():
            raise noninf.GateInputError(f"--out {out} is an input file")
    if out.exists() and not overwrite:
        raise noninf.GateInputError(f"{out} exists; pass --overwrite to replace it")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="gate", required=True)
    for name, what in (("retrieval", "quick_retrieval_eval.py result"),
                       ("answer", "quick_faithfulness_eval.py report")):
        p = sub.add_parser(name, help=f"gate over three {what}s")
        p.add_argument("--aa", nargs=2, type=Path, required=True, metavar=("CONTROL", "REPEAT"),
                       help=f"the control arm's two {what}s; the first is the control")
        p.add_argument("--treatment", type=Path, required=True, help=f"the treatment {what}")
        p.add_argument("--frozen", type=Path, required=True, help="frozen_r1.json")
        p.add_argument("--out", type=Path, required=True, help="report JSON path")
        p.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    return parser.parse_args(argv)


def run_gate(args: argparse.Namespace) -> dict:
    """Load the inputs and judge them; raises on inputs the protocol refuses."""
    inputs = [*args.aa, args.treatment]
    _check_out(args.out, [*inputs, args.frozen], args.overwrite)
    runs = [_load_json(path) for path in inputs]
    frozen = load_frozen(args.frozen)
    judge = noninf.retrieval_gate if args.gate == "retrieval" else noninf.answer_gate
    report = judge(*runs, frozen, gt_labels())
    names = ("L1", "L2", "R") if args.gate == "retrieval" else ("A1", "A2", "R")
    return {"prereg": PREREG,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inputs": {**{n: str(p) for n, p in zip(names, inputs)}, "frozen": str(args.frozen)},
            **report}


# ---------------------------------------------------------------- stdout

def _f(x: float | None, sign: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.4f}" if sign else f"{x:.4f}"


def _ci(summary: dict) -> str:
    ci = summary.get("ci")
    return "[n/a]" if ci is None else f"[{_f(ci[0])}, {_f(ci[1])}]"


def _stat(summary: dict) -> str:
    return f"{_f(summary['mean'])} {_ci(summary)}  n={summary['n']}"


def _ok(passed: bool) -> str:
    return "ok" if passed else "FAIL"


def _print_runs(report: dict) -> None:
    for name, run in report["runs"].items():
        invalid = run.get("invalid")
        extra = f"  invalid {len(invalid)}" if invalid is not None else ""
        print(f"  {name:3s} {run['data_build_id']}  gt {str(run['gt_sha'])[:12]}{extra}")


def _print_pairing(label: str, pairing: dict) -> None:
    print(f"  {label}: {pairing['n']} paired; dropped invalid {pairing['dropped_invalid'] or '-'}"
          + (f"; in one run only {pairing['missing']}" if pairing["missing"] else ""))


def _print_strata(strata: dict) -> None:
    for group in ("by_type", "head_vs_expanded", "by_family"):
        print(f"  {group}:  {'n':>4s}  {'Δvrec@6':>8s}  {'ΔMRR':>8s}")
        for key, row in strata[group].items():
            print(f"    {key:26s} {row['n']:4d}  {_f(row['delta_vrec']):>8s}  "
                  f"{_f(row['delta_mrr']):>8s}")


def _print_retrieval_report_only(ro: dict) -> None:
    print("report only (R − L1):")
    _print_strata(ro["strata"])
    for metric, d in ro["deltas"].items():
        print(f"  Δ{metric}: R−L1 {_stat(d['r_vs_l1'])};  A/A {_stat(d['aa'])}")
    routes = ro["route_differs"]
    print(f"  route differs: A/A {routes['aa']['n']}, R−L1 {routes['r_vs_l1']['n']}")
    print(f"  Δvrec@6 ≤ {noninf.LARGE_DROP}: {len(ro['large_drops'])}")
    for row in ro["large_drops"]:
        print(f"    {row['question_id']:28s} {row['question_type']:22s} {row['family']:20s} "
              f"{row['route_l1']}->{row['route_r']}  "
              f"{_f(row['vrec_l1'], False)}->{_f(row['vrec_r'], False)}")


def print_retrieval(report: dict) -> None:
    aa, crit = report["aa"], report["criteria"]
    c1, c2, c3 = crit["C1"], crit["C2"], crit["C3"]
    print("G-NONINF (retrieval), control L1")
    _print_runs(report)
    _print_pairing("A/A L1–L2", aa["pairing"])
    _print_pairing("R–L1", report["pairing"])
    wl = aa["mrr_win_loss"]
    print(f"A/A  Δvrec@6 {_stat(aa['delta_vrec'])}  B={_f(aa['B'], False)}  "
          f"δ={_f(aa['delta'], False)}")
    print(f"     MRR wins {wl['wins']} losses {wl['losses']}  B_wl={_f(aa['B_wl'], False)}  "
          f"δ_wl={_f(aa['delta_wl'], False)}")
    print(f"C1   Δvrec@6 {_stat(c1)}  lower > {_f(c1['threshold'])}  {_ok(c1['passed'])}")
    print(f"C2   mean sign(ΔMRR) {_stat(c2['mean_sign'])}  lower > {_f(c2['threshold'])}  "
          f"{_ok(c2['passed'])}")
    print(f"     ΔMRR {_stat(c2['delta_mrr'])}; wins {c2['wins']} losses {c2['losses']} "
          f"ties {c2['ties']}; sign test p {c2['sign_test_p']:.4g}")
    print(f"C3   damaged union Δvrec@6 {_stat(c3['union'])}  mean ≥ 0  {_ok(c3['passed'])}")
    for name, s in c3["sub_slices"].items():
        print(f"       {name} {_stat(s)}" + (f"  unpaired {s['unpaired']}" if s["unpaired"] else ""))
    _print_retrieval_report_only(report["report_only"])
    _print_verdict(report)


def _print_field(label: str, block: dict) -> None:
    means = "  ".join(f"{n} {_f(m, False)}" for n, m in block["mean"].items())
    print(f"  {label}: {means};  Δ R−A1 {_stat(block['delta_r_vs_a1'])};  "
          f"Δ A/A {_stat(block['delta_aa'])}")


def print_answer(report: dict) -> None:
    aa, crit, ro = report["aa"], report["criteria"], report["report_only"]
    ds = crit["delta_strict"]
    print("G-ANS (answers, frozen 200-question subset), control A1")
    for name, run in report["runs"].items():
        print(f"  {name:3s} {run['data_build_id']}  judge {run['judge_model']}  "
              f"invalid {len(report['invalid'][name])}")
    print(f"A/A  Δstrict {_stat(aa['delta_strict'])}  B_ans={_f(aa['B_ans'], False)}  "
          f"δ_ans={_f(aa['delta_ans'], False)}")
    print(f"     Δstrict (R − A1) {_stat(ds)}  lower > {_f(ds['threshold'])}  {_ok(ds['passed'])}")
    print(f"     n_invalid {crit['no_invalid']['n_invalid']}  {_ok(crit['no_invalid']['passed'])}")
    print("report only:")
    strict = "  ".join(f"{n} {_f(v['mean'], False)}" for n, v in ro["strict_absolute"].items())
    print(f"  strict (reference {noninf.STRICT_REFERENCE}): {strict}")
    _print_field("zh faithfulness", ro["zh_faithfulness"])
    if "coverage" in ro:
        _print_field(f"coverage (noise floor |Δ| {noninf.COVERAGE_NOISE_FLOOR})", ro["coverage"])
    _print_verdict(report)


def _print_verdict(report: dict) -> None:
    print(f"\n{report['gate']}: {'PASS' if report['passed'] else 'FAIL'}")
    for reason in report["fail_reasons"]:
        print(f"  - {reason}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_gate(args)
    except (ValueError, OSError) as exc:     # GateInputError, FrozenR1Error, GtV2Error, JSON
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    (print_retrieval if args.gate == "retrieval" else print_answer)(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {args.out}")
    return EXIT_PASS if report["passed"] else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
