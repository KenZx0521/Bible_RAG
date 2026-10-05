#!/usr/bin/env python3
"""Opt-in xref A/B slice report (KG batch 1 plan §5.2), report only.

One W1 image answers with --graph-strategies cross_ref_expand cross_reference
twice: on the old data (control) and on the new data (treatment). Both runs
must share graph_strategies_applied, top_k, metric_k and metric_version, and
every passage must carry gold and found_by (exit 2 otherwise: a run from
before found_by would read as "no question reached gold via xref").
Questions invalid on either side are skipped, and questions in one run only
are listed as unpaired; the report then gives

  * touched: questions whose ordered sources differ (route mismatches are
    listed as well, but still counted);
  * the kg_xref slice (--ids, default the 68 questions of the KG audit):
    which questions reach a gold passage only via xref, i.e. some gold
    source_detail entry whose found_by is non-empty and contains nothing but
    cross_ref_expand / cross_reference, on each side, and which were gained
    or lost. An --ids file that is not a list of qids, or a slice with no
    question valid in both runs, exits 2 without a report (an empty slice
    would print "0 → 0", the expected no gain); a partial slice warns.

More than --max-touched (34) touched questions is the plan's "stop and
investigate" signal: exit code 3. It is not a gate.

Usage (from evaluation/):
    uv run python xref_ab_slice.py results_quick/xref_old_w1.json \\
        results_quick/xref_new_w1.json --label w1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
_OUT_DIR = _EVAL_DIR / "results_quick"
DEFAULT_IDS = _EVAL_DIR.parent / "docs/records/2026-10-04_kg_fix/batch1/inputs/kg_xref/sel.json"

XREF_STRATEGIES = frozenset({"cross_ref_expand", "cross_reference"})
GUARD_KEYS = ("graph_strategies_applied", "top_k", "metric_k", "metric_version")
MAX_TOUCHED = 34


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_slice_id(item: object) -> bool:
    return isinstance(item, str) or (isinstance(item, dict) and isinstance(item.get("qid"), str))


def load_slice_ids(path: Path) -> list[str]:
    """Sorted unique qids from a JSON list of qids or of objects with 'qid',
    or from a one-id-per-line text file. Any other JSON raises ValueError: a
    JSON object (per_question.json, gold.json) is no list of qids."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text.startswith(("[", "{")):
        return sorted(set(text.split()))
    items = json.loads(text)
    if not isinstance(items, list) or not all(map(_is_slice_id, items)):
        raise ValueError("expected a JSON list of qids or of objects with a string 'qid'")
    return sorted({i["qid"] if isinstance(i, dict) else i.strip() for i in items} - {""})


def config_mismatch(control: dict, treatment: dict) -> dict[str, list]:
    """Guarded config keys whose values differ: {key: [control, treatment]}."""
    cc, tc = control.get("config", {}), treatment.get("config", {})
    return {k: [cc.get(k), tc.get(k)] for k in GUARD_KEYS if cc.get(k) != tc.get(k)}


def missing_provenance(run: dict) -> list[str]:
    """qids with a passage lacking gold or found_by, or no source_detail at all."""
    return sorted(
        q for q, e in run["per_question"].items()
        if len(e.get("source_detail") or ()) != len(e.get("sources") or ())
        or any("gold" not in s or s.get("found_by") is None
               for s in e.get("source_detail") or ())
    )


def guard_errors(control: dict, treatment: dict) -> list[str]:
    """Why the two runs cannot be sliced; empty when they can."""
    errors = [f"config.{k} differs: control={c} treatment={t}"
              for k, (c, t) in config_mismatch(control, treatment).items()]
    for arm, run in (("control", control), ("treatment", treatment)):
        if qids := missing_provenance(run):
            errors.append(f"{arm}: {len(qids)} questions have passages without gold/found_by "
                          f"(e.g. {qids[0]}); rerun quick_retrieval_eval.py against a backend "
                          "that reports found_by")
    return errors


def _only_via_xref(src: dict) -> bool:
    found_by = set(src.get("found_by") or ())
    return bool(src.get("gold")) and bool(found_by) and found_by <= XREF_STRATEGIES


def gold_via_xref(run: dict, qids: list[str]) -> list[str]:
    """qids with a gold passage that only the cross-reference strategies found."""
    pq = run["per_question"]
    return [q for q in qids if any(_only_via_xref(s) for s in pq[q].get("source_detail") or ())]


def _kg_xref(control: dict, treatment: dict, ids: list[str], valid: list[str],
             touched: list[str]) -> dict:
    wanted = set(ids)
    members = [q for q in valid if q in wanted]
    via_c, via_t = gold_via_xref(control, members), gold_via_xref(treatment, members)
    touched_ids = [q for q in touched if q in wanted]
    return {
        "n_ids": len(ids),
        "n": len(members),
        "touched": len(touched_ids),
        "touched_ids": touched_ids,
        "gold_via_xref": {"control": via_c, "treatment": via_t},
        "gained": sorted(set(via_t) - set(via_c)),
        "lost": sorted(set(via_c) - set(via_t)),
    }


def slice_report(control: dict, treatment: dict, ids: list[str]) -> dict:
    """touched over all common valid questions, plus the kg_xref slice."""
    pc, pt = control["per_question"], treatment["per_question"]
    common = sorted(set(pc) & set(pt))
    invalid = [q for q in common if pc[q].get("invalid") or pt[q].get("invalid")]
    valid = sorted(set(common) - set(invalid))
    touched = [q for q in valid if pc[q]["sources"] != pt[q]["sources"]]
    return {
        "n_common": len(valid),
        "unpaired": {"control_only": sorted(set(pc) - set(pt)),
                     "treatment_only": sorted(set(pt) - set(pc))},
        "invalid": invalid,
        "route_mismatch": [q for q in valid if pc[q].get("route") != pt[q].get("route")],
        "touched_all": len(touched),
        "touched_ids": touched,
        "kg_xref": _kg_xref(control, treatment, ids, valid, touched),
    }


def _ids(qids: list[str]) -> str:
    return ", ".join(qids) or "-"


def print_report(report: dict) -> None:
    kg, via = report["kg_xref"], report["kg_xref"]["gold_via_xref"]
    print(f"\ncommon valid n={report['n_common']}  invalid: {_ids(report['invalid'])}")
    c_only, t_only = report["unpaired"]["control_only"], report["unpaired"]["treatment_only"]
    print(f"unpaired: control only {len(c_only)} ({_ids(c_only)}), "
          f"treatment only {len(t_only)} ({_ids(t_only)})")
    print(f"route mismatch ({len(report['route_mismatch'])}): {_ids(report['route_mismatch'])}")
    print(f"touched (ordered sources differ): {report['touched_all']}/{report['n_common']}"
          f"  {_ids(report['touched_ids'])}")
    print(f"\nkg_xref slice: {kg['n']}/{kg['n_ids']} ids in both runs, "
          f"touched {kg['touched']}: {_ids(kg['touched_ids'])}")
    print(f"  gold only via xref: control {len(via['control'])} → treatment {len(via['treatment'])}"
          f"  gained: {_ids(kg['gained'])}  lost: {_ids(kg['lost'])}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("control", type=Path, help="quick eval run on the old data")
    parser.add_argument("treatment", type=Path, help="quick eval run on the new data")
    parser.add_argument("--ids", type=Path, default=DEFAULT_IDS,
                        help="kg_xref slice: JSON list of qids or of objects with 'qid', or one "
                             "id per line (default: the 68 questions of kg_xref/sel.json)")
    parser.add_argument("--label", default=None,
                        help="save the report to results_quick/xref_ab_<label>.json")
    parser.add_argument("--max-touched", type=int, default=MAX_TOUCHED,
                        help="exit 3 when more questions are touched (investigate; not a gate)")
    return parser.parse_args(argv)


def _fail(errors: list[str]) -> int:
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        ids = load_slice_ids(args.ids)
    except ValueError as exc:
        return _fail([f"--ids {args.ids}: {exc}"])
    control, treatment = _load_json(args.control), _load_json(args.treatment)
    if errors := guard_errors(control, treatment):
        return _fail(errors)
    report = slice_report(control, treatment, ids)
    kg = report["kg_xref"]
    if kg["n"] == 0:  # "gold only via xref: 0 → 0" would read like the expected no gain
        return _fail([f"kg_xref slice: none of the {kg['n_ids']} --ids is a valid question in both runs"])
    if kg["n"] < kg["n_ids"]:
        print(f"warning: {kg['n_ids'] - kg['n']} of the {kg['n_ids']} --ids are missing or invalid "
              "in at least one run", file=sys.stderr)
    report["inputs"] = {"control": str(args.control), "treatment": str(args.treatment),
                        "ids": str(args.ids)}
    report["config"] = {k: control.get("config", {}).get(k) for k in GUARD_KEYS}
    report["max_touched"] = args.max_touched
    print_report(report)
    if args.label:
        _OUT_DIR.mkdir(exist_ok=True)
        out = _OUT_DIR / f"xref_ab_{args.label}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nsaved → {out}")
    if report["touched_all"] > args.max_touched:
        print(f"\ntouched {report['touched_all']} > {args.max_touched}: stop and investigate "
              "before reading the A/B (plan §5.2; not a gate)")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
