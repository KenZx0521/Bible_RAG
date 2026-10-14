"""§7 凍結: write heldout_ho.json and the 附錄 B list, before any HO arm runs.

Refuses a pilot root or pilot output path, a selection that is not complete (every
category 30, or 60 drafts reached), a Kay sample not drawn or not settled, any
error-level mechanical violation of the selected questions (mech_check full run) or of
their agents' transcripts (an infrastructure failure that was rerun only loses its
t_result), and an existing output file. The written file must then load with
gd.load_ho(path, sha256) (gd.check_ho_items, the authoritative §7 check).

The 附錄 B list (manifest JSON) holds: sha256 and ids sha of heldout_ho.json, the gold
cluster table and density layers (evaluate.py units: _eval_report.items_of / unit_table),
the core table and core clusters (_eval_stats.clusters), the density distribution, the
[SHORTCUT] list, per category the drafts and the drafts blocked by §7 不重疊, the
selection counts and the Kay sample. Nothing is left behind when a check fails. The
blocked count only covers drafts the mechanical check stopped; overlap_avoided (描述性)
adds, per category, how often the drafting agents met the rule first: distinct passages
`bt old --gold` reported as 衝突 in the gen / fix runs, the runs that met one, and the
abandoned or dropped drafts whose reason cites 衝突 or 重疊. transcript_breaches counts
the drafts dropped at commit for a blinding error in one of their runs.

    freeze.py --root <store>/reports/graph_gd_20261014/ho [--out heldout_ho.json]
              [--manifest heldout_ho_freeze.json]

Exit 0 written, 2 refused (one line).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import (CATEGORY_ORDER, EXP_DIR, HO_DIR, PILOT_ROOT, HoToolError, gd,  # first: sys.path
                        ho_meta, is_pilot_root, under)

import _eval_report as R  # noqa: E402  evaluate.py units: items_of, unit_table
import _eval_stats as st  # noqa: E402
import _ho_state as S  # noqa: E402
import _ho_transcript as TR  # noqa: E402
import mech_check as M  # noqa: E402

__all__ = ["MANIFEST_PATH", "EXTRA_KEYS", "ho_item", "check_ready", "density_distribution",
           "overlap_avoided", "manifest", "freeze", "main", "SCRIPT_FILES"]

MANIFEST_PATH = EXP_DIR / "heldout_ho_freeze.json"
EXTRA_KEYS = ("notes", "n_passages", "books", "cross_book")
SCRIPT_FILES = (*M.SCRIPT_FILES, HO_DIR / "freeze.py",
                *(EXP_DIR / n for n in ("_eval_report.py", "_eval_metrics.py", "_eval_stats.py",
                                        "_score_w.py", "_score_io.py")),  # _eval_report loads _score_w
                Path(st._ab_stats.__file__).resolve().parent / "__init__.py",
                Path(st._ab_stats.__file__).resolve())
DENSITY_BINS = 10
DRAFTING_KINDS = ("gen", "fix")
OVERLAP_REASON = re.compile(r"衝突|重疊|已被.{0,8}使用")


def ho_item(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen form of a selected record: §7 fields, a few annotate keys, last audit."""
    item = rec["item"]
    last = (rec.get("audits") or [{}])[-1]
    fields = {k: item[k] for k in gd.HO_FIELDS}
    fields["core"] = str(item["core"]).strip()          # mech_check compares stripped cores
    return {**fields, **{k: item.get(k) for k in EXTRA_KEYS},
            "audit": {"severity": last.get("severity"), "run": last.get("run"),
                      "fixes": len(rec.get("fixes") or ())}}


def _refuse_pilot(root: Path, paths: Sequence[Path]) -> None:
    for p in (root, *paths):
        if is_pilot_root(p) or under(p, PILOT_ROOT):
            raise HoToolError(f"freeze refuses pilot data ({p}): pilot results are discarded")


def _transcript_errors(root: Path, state: Mapping[str, Any], recs: Sequence[Mapping]) -> list[str]:
    out = []
    for r in recs:
        for run in r["runs"]:
            rerun = (state["runs"].get(run) or {}).get("error") is not None
            out += [f"{run}: {v.rule} {v.detail}" for v in TR.check_run(root, run)
                    if v.level == "error" and not (rerun and v.rule == "t_result")]
    return out


def check_ready(root: Path, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The selected records, after every §7 pre-freeze condition holds."""
    if state["pilot"]:
        raise HoToolError("freeze refuses a pilot state")
    if not S.is_complete(state):
        raise HoToolError(f"selection not complete: {S.summary(state)['selected']}")
    kay = state.get("kay") or {}
    if not kay.get("resolved"):
        raise HoToolError("the Kay sample is not drawn or not fully decided (§7)")
    open_ = [q for q in kay["sample_ids"] if S.record(state, q)["status"] in S.UNRESOLVED]
    if open_:
        raise HoToolError(f"Kay-sampled questions still unresolved: {open_}")
    recs = S.selection(state)
    found = M.check_set([r["item"] for r in recs], M.store_context())
    bad = sorted(q for q, vs in found.items() if any(v.level == "error" for v in vs))
    if bad:
        raise HoToolError(f"mechanical check fails for {bad}")
    errors = _transcript_errors(root, state, recs)
    if errors:
        raise HoToolError(f"transcript check fails: {errors[:5]}{' …' if len(errors) > 5 else ''}")
    return recs


def density_distribution(values: Mapping[str, Fraction]) -> dict[str, Any]:
    """§7 density values of HO: deciles of [0, 1], the low / high layer counts, sorted values."""
    bins = [0] * DENSITY_BINS
    for v in values.values():
        bins[min(int(v * DENSITY_BINS), DENSITY_BINS - 1)] += 1
    low = sum(v < R.M.LOW_DENSITY for v in values.values())
    return {"bins": {f"[{i / DENSITY_BINS:.1f},{(i + 1) / DENSITY_BINS:.1f})": n for i, n in enumerate(bins)},
            "low": low, "high": len(values) - low, "low_threshold": str(R.M.LOW_DENSITY),
            "sorted": sorted(float(v) for v in values.values())}


def overlap_avoided(root: Path, state: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """附錄 B（描述性）: per category, the §7 不重疊 rule as the drafting agents met it."""
    out = {}
    for cat in CATEGORY_ORDER:
        seen: set[str] = set()
        runs = 0
        recs = S.records(state, cat)
        for r in recs:
            for run in r["runs"]:
                if (state["runs"].get(run) or {}).get("kind") in DRAFTING_KINDS:
                    found = TR.run_conflicts(root, run)
                    seen |= found
                    runs += bool(found)
        gave_up = sum(r["status"] in (S.ABANDONED, S.DROPPED) and bool(OVERLAP_REASON.search(r["events"][-1]["note"]))
                      for r in recs)
        out[cat] = {"conflict_passages_reported": len(seen), "runs_meeting_conflicts": runs,
                    "gave_up_citing_overlap": gave_up}
    return out


def manifest(path: Path, sha: str, state: Mapping[str, Any], name: Path | None = None,
             root: Path | None = None) -> dict[str, Any]:
    """附錄 B list of the HO file at `path` (recorded under `name`, default `path`);
    overlap_avoided needs the run root's transcripts."""
    qset = gd.load_ho(path, expected_sha256=sha)
    items = R.items_of(qset, gold_only=True)
    cores: dict[str, list[str]] = {}
    for q in qset.questions:
        cores.setdefault(q.core, []).append(q.qid)
    core_units = st.clusters(qset.ids, {it.qid: it.gold_union for it in items},
                             {q.qid: q.core for q in qset.questions})
    summ = S.summary(state)
    return {"file": str(name or path), "sha256": sha, "ids_sha256": qset.ids_sha256, "n": len(qset.questions),
            "unit_table": R.unit_table(items),
            "core_table": {c: sorted(v) for c, v in sorted(cores.items())},
            "core_units": [list(u) for u in core_units],
            "density_layers": {"low": sorted(it.qid for it in items if it.low_density),
                               "high": sorted(it.qid for it in items if not it.low_density)},
            "density_distribution": density_distribution({it.qid: it.density for it in items}),
            "shortcut": sorted(q.qid for q in qset.questions if q.shortcut),
            "drafts": summ["drafts"], "blocked_by_overlap": summ["blocked_by_overlap"],
            "overlap_avoided": None if root is None else overlap_avoided(root, state),
            "transcript_breaches": summ["transcript_breaches"],
            "selected": summ["selected"], "kay": state["kay"]}


def freeze(root: Path, out: Path = gd.HO_PATH, manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    root, out, manifest_path = Path(root), Path(out), Path(manifest_path)
    _refuse_pilot(root, (out, manifest_path))
    for p in (out, manifest_path):
        if p.exists():
            raise HoToolError(f"{p} exists: a frozen HO file is never rewritten")
    state = S.load_state(root)
    recs = check_ready(root, state)
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_text(json.dumps({"questions": [ho_item(r) for r in recs]}, ensure_ascii=False,
                                  indent=1) + "\n", encoding="utf-8")
        sha = gd.file_sha256(tmp)
        doc = {"meta": ho_meta("freeze.py", SCRIPT_FILES, root=str(root)),
               **manifest(tmp, sha, state, name=out, root=root)}
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    manifest_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=gd.HO_PATH)
    ap.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    doc = freeze(a.root, a.out, a.manifest)
    print(f"freeze.py: {doc['n']} questions, sha256 {doc['sha256']} -> {a.out}, {a.manifest}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"freeze.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
