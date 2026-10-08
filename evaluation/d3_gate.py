#!/usr/bin/env python3
"""D3 non-inferiority gate: two backends must retrieve identically.

KG batch 1 (docs/records/2026-10-04_kg_batch1_plan.md §5.1): before a wave is
promoted, the staging backend (built from that wave's HEAD) and prod answer
all ground-truth questions with the default configuration, and

  * both apply the same graph strategies;
  * every same-route question keeps its core top-k, its appended passages and
    its context digest — 100% identical;
  * questions the intent classifier routed differently (it samples at
    temperature 0.1) are re-asked on both sides, at most two rounds; those
    still routed differently are the route residual, which must not exceed r0
    (--route-residual-max, measured by the W0 AA run with --calibrate);
  * no question is invalid.

Each arm is a quick_retrieval_eval.py run (--top-k 5 --metric-k 6
--include-context, and --gt when given) pointed at its backend through
BACKEND_URL. Both arms must score against one ground truth; their data builds
may differ and the report shows both; re-asks use
--ids-file and are merged into the run they patch only when still pairable.
The final runs, re-asked answers merged in, are saved as
results_quick/d3_<arm>_<label>_merged.json: file mode on them reproduces the
live verdict, while the raw arm files keep the first answers. The full report
goes to results_quick/d3_<label>.json; exit code 0 = pass. Existing outputs
are only replaced with --overwrite, and never when the report path is one of
the file-mode inputs.

Usage (from evaluation/):
    # W0 AA: prod vs backend-staging on the same data, measures r0
    .venv/bin/python d3_gate.py --label w0_aa --control-url http://localhost:8000 \\
        --treatment-url http://localhost:8001 --calibrate
    # W1/W2 gate
    .venv/bin/python d3_gate.py --label w1 --control-url http://localhost:8000 \\
        --treatment-url http://localhost:8001 --route-residual-max <r0>
    # re-judge the merged runs a live gate saved (no queries, no re-asks)
    .venv/bin/python d3_gate.py --label w1_files \\
        --control-file results_quick/d3_prod_w1_merged.json \\
        --treatment-file results_quick/d3_stg_w1_merged.json --route-residual-max <r0>
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ab_compare import print_identity  # noqa: E402
from quick_retrieval_eval import applied_counts  # noqa: E402
from src.ab_compare import identity_report  # noqa: E402

_EVAL_DIR = Path(__file__).resolve().parent
_OUT_DIR = _EVAL_DIR / "results_quick"
_QUICK_EVAL = _EVAL_DIR / "quick_retrieval_eval.py"

QUICK_EVAL_ARGS = ("--top-k", "5", "--metric-k", "6", "--include-context")
MAX_ROUNDS = 2

# Settings a re-asked run must share with the run it patches; otherwise the
# merged run would mix requests or scoring and stop being pairable.
_MERGE_KEYS = ("top_k", "metric_k", "metric_version", "include_context", "use_graph",
               "fusion_alpha", "graph_strategies_requested")
# The build and GT a re-ask must share with the run it patches.
_MERGE_META_KEYS = ("data_build_id", "gt_version", "gt_sha", "encoder_fingerprint")


class Arm(NamedTuple):
    name: str
    url: str
    label: str


# (backend url, run label, question ids or None for all) -> quick eval run
Runner = Callable[[str, str, list[str] | None], dict]


def quick_eval_command(label: str, ids_file: Path | None = None,
                       gt: str | None = None) -> list[str]:
    cmd = [sys.executable, str(_QUICK_EVAL), *QUICK_EVAL_ARGS, "--label", label]
    if gt is not None:
        cmd += ["--gt", gt]
    if ids_file is not None:
        cmd += ["--ids-file", str(ids_file)]
    return cmd


def subprocess_runner(url: str, label: str, ids: list[str] | None, gt: str | None = None) -> dict:
    """Run quick_retrieval_eval.py against one backend and load what it saved."""
    with tempfile.TemporaryDirectory() as tmp:
        ids_file = None
        if ids is not None:
            ids_file = Path(tmp) / "ids.txt"
            ids_file.write_text("\n".join(ids) + "\n", encoding="utf-8")
        subprocess.run(quick_eval_command(label, ids_file, gt),
                       env={**os.environ, "BACKEND_URL": url}, cwd=_EVAL_DIR, check=True)
    return json.loads((_OUT_DIR / f"{label}.json").read_text(encoding="utf-8"))


def merge_rerun(base: dict, rerun: dict, ids: list[str]) -> dict:
    """A copy of ``base`` whose ``ids`` entries come from ``rerun``.

    Raises unless the re-ask answered exactly the asked questions, all of
    which ``base`` holds, with the same request and scoring settings, build
    and ground truth. Run-level aggregates (overall / by_type) are dropped:
    they no longer describe the merged entries.
    """
    asked, got = set(ids), set(rerun["per_question"])
    if got != asked:
        raise ValueError(f"re-ask answered {sorted(got)}, asked {sorted(asked)}")
    unknown = sorted(asked - set(base["per_question"]))
    if unknown:
        raise ValueError(f"re-asked {unknown}, which the original run never asked")
    cb, cr = base.get("config", {}), rerun.get("config", {})
    differing = [k for k in _MERGE_KEYS if cb.get(k) != cr.get(k)]
    if differing:
        raise ValueError(f"re-ask ran with different {differing} than the run it patches")
    mb, mr = base.get("meta") or {}, rerun.get("meta") or {}
    differing = [k for k in _MERGE_META_KEYS if mb.get(k) != mr.get(k)]
    if differing:
        raise ValueError(f"re-ask ran against a different {differing} than the run it patches")

    per_question = {**base["per_question"], **{q: rerun["per_question"][q] for q in ids}}
    config = {
        **cb,
        "graph_strategies_applied": applied_counts(
            {q: e.get("graph_strategies") for q, e in per_question.items()}),
        "reasked": [*cb.get("reasked", []), sorted(ids)],
    }
    return {
        **({"meta": base["meta"]} if "meta" in base else {}),
        "config": config,
        "n": len(per_question),
        "n_invalid": sum(bool(e.get("invalid")) for e in per_question.values()),
        "per_question": per_question,
    }


def build_report(ident: dict, residual_max: int | None, rounds: list[dict]) -> dict:
    """Verdict on a final identity report. residual_max None = calibration run."""
    residual = ident["route_mismatch"]
    unpaired = ident["unpaired"]
    criteria = {
        "graph_strategies_identical": ident["strategies"]["identical"],
        "same_route_identical": not ident["mismatches"],
        "no_invalid": not ident["invalid"],
        "all_paired": not unpaired["control_only"] and not unpaired["treatment_only"],
        "route_residual_within_r0": None if residual_max is None else len(residual) <= residual_max,
    }
    report = {
        "params": {"quick_eval_args": list(QUICK_EVAL_ARGS), "max_rounds": MAX_ROUNDS,
                   "route_residual_max": residual_max, "calibrate": residual_max is None},
        "rounds": rounds,
        "route_residual": residual,
        "criteria": criteria,
        # None = not judged (calibration measures r0 instead).
        "passed": all(v is not False for v in criteria.values()),
        "identity": ident,
    }
    if residual_max is None:
        report["r0_measured"] = len(residual)
    return report


def run_live(runner: Runner, control: Arm, treatment: Arm, residual_max: int | None,
             max_rounds: int = MAX_ROUNDS,
             save: Callable[[Arm, dict], None] | None = None) -> dict:
    """Query both backends, re-ask route mismatches, judge the merged runs.

    ``save(arm, run)`` receives each arm's final run, re-asked answers merged
    in: the inputs on which file mode reproduces this verdict.
    """
    runs = [runner(arm.url, arm.label, None) for arm in (control, treatment)]
    ident = identity_report(*runs)
    rounds: list[dict] = []
    for rnd in range(1, max_rounds + 1):
        asked = ident["route_mismatch"]
        if not asked:
            break
        runs = [merge_rerun(run, runner(arm.url, f"{arm.label}_retry{rnd}", asked), asked)
                for run, arm in zip(runs, (control, treatment))]
        ident = identity_report(*runs)
        rounds.append({"round": rnd, "asked": asked, "routes": ident["routes"],
                       "still_route_mismatch": ident["route_mismatch"]})
    if save is not None:
        for arm, run in zip((control, treatment), runs):
            save(arm, run)
    return build_report(ident, residual_max, rounds)


def run_files(control: dict, treatment: dict, residual_max: int | None) -> dict:
    """Judge two saved runs as they are: no queries, no re-asks."""
    return build_report(identity_report(control, treatment), residual_max, rounds=[])


def print_summary(report: dict) -> None:
    print_identity(report["identity"])
    for rnd in report["rounds"]:
        print(f"re-ask round {rnd['round']}: asked {len(rnd['asked'])}, "
              f"still routed differently {rnd['still_route_mismatch'] or '-'}")
    r0 = report["params"]["route_residual_max"]
    print(f"route residual: {len(report['route_residual'])}"
          + (" (calibration: r0 measured)" if r0 is None else f" (r0 = {r0})"))
    for name, ok in report["criteria"].items():
        print(f"  {name:28s} {'-' if ok is None else 'ok' if ok else 'FAIL'}")
    print(f"\nD3 gate: {'PASS' if report['passed'] else 'FAIL'}")


def _merged_path(arm: Arm) -> Path:
    return _OUT_DIR / f"{arm.label}_merged.json"


def _write_json(path: Path, data: dict) -> None:
    _OUT_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_merged(arm: Arm, run: dict) -> None:
    _write_json(_merged_path(arm), run)
    print(f"saved {arm.name} merged run → {_merged_path(arm)}")


def _planned_outputs(arms: tuple[Arm, Arm], report_path: Path) -> list[Path]:
    labels = [arm.label for arm in arms]
    labels += [f"{arm.label}_retry{rnd}" for rnd in range(1, MAX_ROUNDS + 1) for arm in arms]
    return ([_OUT_DIR / f"{label}.json" for label in labels]
            + [_merged_path(arm) for arm in arms] + [report_path])


def _refuse_existing(outputs: list[Path], overwrite: bool) -> None:
    existing = [p for p in outputs if p.exists()]
    if existing and not overwrite:
        raise ValueError(f"outputs of an earlier run exist: {[str(p) for p in existing]}; "
                         "pick another --label or pass --overwrite")


def _same_file(a: Path, b: Path) -> bool:
    """Both exist and are one file, however the paths are spelled."""
    try:
        return a.samefile(b)
    except OSError:
        return False


def _refuse_report_over_inputs(report_path: Path, inputs: dict[str, Path]) -> None:
    """Even --overwrite must not replace a run the report is judging."""
    for flag, path in inputs.items():
        if _same_file(report_path, path):
            raise ValueError(f"the report path {report_path} is the {flag} input; "
                             "pick another --label")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True,
                        help="gate label (e.g. w1); report → results_quick/d3_<label>.json")
    parser.add_argument("--control-url", help="live mode: control backend (prod)")
    parser.add_argument("--treatment-url", help="live mode: treatment backend (staging)")
    parser.add_argument("--control-name", default="prod",
                        help="control run label d3_<name>_<label> (default prod)")
    parser.add_argument("--treatment-name", default="stg",
                        help="treatment run label d3_<name>_<label> (default stg)")
    parser.add_argument("--control-file", type=Path, help="file mode: saved control run")
    parser.add_argument("--treatment-file", type=Path, help="file mode: saved treatment run")
    r0 = parser.add_mutually_exclusive_group(required=True)
    r0.add_argument("--route-residual-max", type=int, metavar="R0",
                    help="most questions allowed to stay routed differently after re-asks")
    r0.add_argument("--calibrate", action="store_true",
                    help="W0 AA: measure the route residual as r0 instead of judging it")
    parser.add_argument("--gt", choices=("v1", "v2"), default=None,
                        help="live mode: ground truth both arms score with "
                             "(default: EVAL_GT_VERSION setting)")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow replacing earlier outputs of this label (never an input file)")
    args = parser.parse_args()
    live = (args.control_url, args.treatment_url)
    files = (args.control_file, args.treatment_file)
    if not (all(live) and not any(files)) and not (all(files) and not any(live)):
        parser.error("give --control-url and --treatment-url (live) "
                     "or --control-file and --treatment-file (files)")
    return args


def _gate_live(args: argparse.Namespace, residual_max: int | None,
               report_path: Path) -> tuple[dict, dict]:
    arms = (Arm(args.control_name, args.control_url, f"d3_{args.control_name}_{args.label}"),
            Arm(args.treatment_name, args.treatment_url, f"d3_{args.treatment_name}_{args.label}"))
    _refuse_existing(_planned_outputs(arms, report_path), args.overwrite)
    runner = functools.partial(subprocess_runner, gt=args.gt)
    report = run_live(runner, *arms, residual_max, save=_save_merged)
    merged = {"control": str(_merged_path(arms[0])), "treatment": str(_merged_path(arms[1]))}
    return ({**report, "merged_runs": merged},
            {"control": arms[0]._asdict(), "treatment": arms[1]._asdict()})


def _gate_files(args: argparse.Namespace, residual_max: int | None,
                report_path: Path) -> tuple[dict, dict]:
    _refuse_report_over_inputs(report_path, {"--control-file": args.control_file,
                                             "--treatment-file": args.treatment_file})
    _refuse_existing([report_path], args.overwrite)
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    report = run_files(load(args.control_file), load(args.treatment_file), residual_max)
    return report, {"control": str(args.control_file), "treatment": str(args.treatment_file)}


def main() -> int:
    args = _parse_args()
    residual_max = None if args.calibrate else args.route_residual_max
    report_path = _OUT_DIR / f"d3_{args.label}.json"
    mode, judge = ("live", _gate_live) if args.control_url else ("files", _gate_files)
    try:
        report, inputs = judge(args, residual_max, report_path)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = {"label": args.label, "mode": mode, "inputs": inputs,
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **report}
    print_summary(report)
    _write_json(report_path, report)
    print(f"saved → {report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
