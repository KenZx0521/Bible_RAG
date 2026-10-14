"""§4 metrics, §5 tests and the §6 V1 stop rule of the GD experiment, from arms.py lists and
score.py scores.

prereg.md in this directory is the only spec; § numbers refer to it. The metric version
of §4 is this file's sha256 (meta.metric_version); its helpers (_eval_inputs.py: lists /
scores and their provenance; _eval_metrics.py: top-k, f(q), D5≈, density; _eval_report.py:
items, comparisons, gate, strata, V1; _eval_stats.py: clusters, sign-flip, bootstrap, Holm;
_eval_accept.py: acceptance B), _score_io.py and evaluation/src/ab_stats.py are hashed
into meta.sha256 next to it.

    evaluate.py report --set new82 --lists L.json --scores S.jsonl --out new82_report.json
    evaluate.py report --set old31+ho --lists L_old31 L_ho --scores S_old31 S_ho --out e2.json
    evaluate.py v1 --lists <store>/old31/lists.json --scores <store>/old31/scores.jsonl
    evaluate.py units --set old31 --out units.json         # gold-only cluster table, density
    evaluate.py build-ref --out <store>/new82/accept_b_reference.json
    evaluate.py accept-b --lists L.json --scores S.jsonl --ref R.json [--out accept/accept_b.json]

report runs on NEW82 (探索, §2) or on the E2 pool OLD31 ∪ HO only: OLD31 alone goes through
v1, which prints and writes nothing but the stop decision and the unit W:L (§6). Every
command except units refuses a set whose appendix is 待追加 or whose acceptance files have
not passed (gd.assert_set_allowed). Inputs must be pinned (_eval_inputs.py); report and
accept-b on NEW82 take --allow-unpinned for chain checks with converted archive files.
Errors exit 2 with one line.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _eval_accept as acc  # noqa: E402
import _eval_inputs as I  # noqa: E402,E741
import _eval_metrics as M  # noqa: E402
import _eval_report as R  # noqa: E402
import _eval_stats as st  # noqa: E402
import _score_io as sio  # noqa: E402
import gd_common as gd  # noqa: E402
from _eval_report import (DESCRIPTIVE, H_PAIRS, Item, Table, arm_metrics,  # noqa: E402,F401
                          attached_notes, compare, descriptive, hypotheses, items_of, sensitivity,
                          subsets, unit_table)

SOURCE_FILES = {"evaluate.py": Path(__file__).resolve(),
                **{n: _HERE / n for n in ("_eval_inputs.py", "_eval_metrics.py", "_eval_report.py",
                                          "_eval_stats.py", "_eval_accept.py")},
                "_score_io.py": Path(sio.__file__).resolve(),
                "src/__init__.py": Path(st._ab_stats.__file__).resolve().parent / "__init__.py",
                "src/ab_stats.py": Path(st._ab_stats.__file__).resolve()}
REPORT_SETS = {"new82": ("new82",), "old31+ho": ("old31", "ho")}
EXPLORATORY = {"new82": "NEW82 只當探索集（§2）：結果只能標為探索性，不得作證據"}
ACCEPT_B_OUT = _HERE / "accept" / "accept_b.json"
V1_OUT = _HERE / "v1_old31.json"


@dataclass(frozen=True)
class Part:
    """One question set with its lists and scores."""
    qset: gd.QuestionSet
    lists: I.Lists
    scores: I.Scores


def load_part(name: str, lists_path: Path, scores_path: Path, pinned: bool = True) -> Part:
    qset = gd.load_question_set(name)
    lists = I.Lists(lists_path, qset, pinned=pinned)
    return Part(qset, lists, I.Scores(scores_path, qset, lists.content_sha256 if pinned else None))


def merge(parts: Sequence[Part]) -> tuple[tuple[Item, ...], Table]:
    """Items of every part (missing hops by §4) and one Table over their joined pools."""
    ids = [q for p in parts for q in p.qset.ids]
    if len(set(ids)) != len(ids):
        raise gd.IntegrityError("question ids repeat across the merged sets")
    arms = {p.lists.arms for p in parts}
    if len(arms) != 1:
        raise gd.GdError(f"the merged sets carry different arms: {sorted(arms)}")
    items = tuple(it for p in parts for it in items_of(p.qset, p.lists.r20, p.scores.by_qid))
    pools = {a: {q: pool for p in parts for q, pool in p.lists.pools[a].items()}
             for a in parts[0].lists.arms}
    scores = {q: s for p in parts for q, s in p.scores.by_qid.items()}
    return items, Table(items, pools, scores)


def d5_check(part: Part, items: Sequence[Item]) -> dict[str, Any] | None:
    """NEW82: D5≈ from R20 and these scores against the stored missing_rr (§4 says they agree)."""
    if part.qset.name != "new82" or not all(part.lists.r20.values()):
        return None
    got = {it.qid: M.d5_missing(it.gold, part.lists.r20[it.qid], part.scores.by_qid[it.qid])
           for it in items if it.set_name == "new82"}
    return {"d5approx_hops": sum(map(len, got.values())),
            "d5approx_questions": sum(bool(v) for v in got.values()),
            "equal_to_stored": sum(got[it.qid] == it.missing for it in items if it.qid in got),
            "of": len(got)}


# ------------------------------------------------------------------ commands

def _meta(script: str, qsets: Sequence[gd.QuestionSet], files: Mapping[str, Path], **extra: Any) -> dict:
    return gd.collect_meta({**SOURCE_FILES, **files}, script=script,
                           metric_version=gd.file_sha256(__file__),
                           question_sets=[{"name": q.name, "ids_sha256": q.ids_sha256,
                                           "sources": dict(q.sources)} for q in qsets], **extra)


def _paths(value: Path | Sequence[Path]) -> list[Path]:
    return [Path(value)] if isinstance(value, (str, Path)) else [Path(v) for v in value]


def _report_parts(set_name: str, lists_paths: list[Path], scores_paths: list[Path],
                  pinned: bool) -> list[Part]:
    if set_name not in REPORT_SETS:
        raise gd.ConfirmationLockedError(
            f"report runs on {sorted(REPORT_SETS)} only: OLD31 alone goes through v1 (§6, blinded), "
            "HO only inside the E2 pool old31+ho")
    names = REPORT_SETS[set_name]
    for name in names:
        gd.assert_set_allowed(name)
    if not (len(lists_paths) == len(scores_paths) == len(names)):
        raise gd.GdError(f"--set {set_name} needs {len(names)} --lists and --scores, in order {names}")
    if not pinned and set_name != "new82":
        raise gd.GdError("confirmation data are only read pinned (--allow-unpinned is for NEW82)")
    return [load_part(n, lp, sp, pinned) for n, lp, sp in zip(names, lists_paths, scores_paths)]


def report(set_name: str, lists_paths: Path | Sequence[Path], scores_paths: Path | Sequence[Path],
           pinned: bool = True) -> dict[str, Any]:
    parts = _report_parts(set_name, _paths(lists_paths), _paths(scores_paths), pinned)
    items, table = merge(parts)
    lacking = [a for a in M.TESTED_ARMS if a not in table.arms]
    if lacking:
        raise gd.GdError(f"tested arms {lacking} are absent from the lists")
    hyp = hypotheses(table)
    ids = [it.qid for it in items]
    files = {f"{kind}:{p.qset.name}": getattr(p, kind).path for p in parts for kind in ("lists", "scores")}
    inputs = {p.qset.name: {"lists": {"content_sha256": p.lists.content_sha256, **dict(p.lists.meta)},
                            "scores": list(p.scores.metas), "refchecks": len(p.scores.refchecks)}
              for p in parts}
    return {"meta": _meta("evaluate.py report", [p.qset for p in parts], files, report_set=set_name,
                          pinned=pinned, inputs_meta=inputs),
            "exploratory": EXPLORATORY.get(set_name), "sets": [p.qset.name for p in parts],
            "arms": list(table.arms), "arms_absent": [a for a in M.ARMS if a not in table.arms],
            "units": unit_table(items),
            "missing_hops": {"by_set": R.missing_summary(items),
                             "new82_d5approx_check": d5_check(parts[0], items)},
            "pools": {a: {"lt_30": sum(len(table.pools[a][q]) < M.FULL_POOL for q in ids),
                          "min": min(len(table.pools[a][q]) for q in ids)} for a in table.arms},
            "metrics": {f"@{k}": {a: arm_metrics(table, a, k) for a in table.arms} for k in M.KS},
            "cut_gaps": M.cut_gap_table(table.pools, table.scores, table.arms, ids),
            "hypotheses": hyp, "attached_notes": attached_notes(table, hyp),
            "descriptive": descriptive(table), "sensitivity": sensitivity(table),
            "per_question": {it.qid: {f"@{k}": {a: str(table.cov(a, k)[it.qid]) for a in table.arms}
                                      for k in M.KS} for it in items}}


def v1(lists_path: Path, scores_path: Path) -> dict[str, Any]:
    """§6 V1 on OLD31: the stop decision and GD−C@10 unit W:L, nothing else."""
    gd.assert_set_allowed("old31")
    part = load_part("old31", Path(lists_path), Path(scores_path))
    _, table = merge([part])
    decision = R.v1(table)
    return {"meta": _meta("evaluate.py v1", [part.qset],
                          {"lists:old31": part.lists.path, "scores:old31": part.scores.path}),
            "stage": "V1", "set": "old31", **decision}


def units(set_name: str) -> dict[str, Any]:
    """Gold-only cluster table and density layers (no lists or scores: §2 allows it for OLD31)."""
    qset = gd.load_question_set(set_name)
    items = items_of(qset, gold_only=True)
    out = {"meta": _meta("evaluate.py units", [qset], {}), **unit_table(items)}
    if set_name == "old31":
        shared = R.new82_gold()
        out["shares_gold_with_new82"] = sorted(it.qid for it in items if it.gold_union & shared)
    return out


def accept(lists: Path, scores: Path, ref: Path, pinned: bool = True,
           out: Path = ACCEPT_B_OUT) -> tuple[dict[str, Any], int]:
    if not pinned and Path(out).resolve() == ACCEPT_B_OUT.resolve():
        raise gd.GdError(f"an unpinned chain check never writes {ACCEPT_B_OUT}; pass another --out")
    doc, code = acc.accept_b(lists, scores, ref, pinned=pinned)
    files = {"lists": lists, "scores": scores, "ref": ref}
    return {"meta": _meta("evaluate.py accept-b", [gd.load_new82()], files, pinned=pinned), **doc}, code


def _write(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report")
    p.add_argument("--set", required=True, help=f"one of {sorted(REPORT_SETS)}")
    p.add_argument("--lists", type=Path, nargs="+", required=True)
    p.add_argument("--scores", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--allow-unpinned", action="store_true", help="NEW82 chain checks only")
    p = sub.add_parser("v1")
    p.add_argument("--lists", type=Path, required=True)
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--out", type=Path, default=V1_OUT)
    p = sub.add_parser("units")
    p.add_argument("--set", required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("build-ref")
    p.add_argument("--out", type=Path, default=acc.REF_PATH)
    p = sub.add_parser("accept-b")
    for name in ("lists", "scores", "ref"):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--out", type=Path, default=ACCEPT_B_OUT)
    p.add_argument("--allow-unpinned", action="store_true", help="chain checks with converted archives")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    pinned = not getattr(a, "allow_unpinned", False)
    commands: dict[str, Callable[[], tuple[dict, int]]] = {
        "report": lambda: (report(a.set, a.lists, a.scores, pinned), 0),
        "v1": lambda: (v1(a.lists, a.scores), 0),
        "units": lambda: (units(a.set), 0),
        "build-ref": lambda: ({"meta": _meta("evaluate.py build-ref", [gd.load_new82()], {}),
                               **acc.build_reference()}, 0),
        "accept-b": lambda: accept(a.lists, a.scores, a.ref, pinned, a.out)}
    doc, code = commands[a.cmd]()
    _write(a.out, doc)
    if a.cmd == "v1":
        print(f"V1 OLD31: stop={doc['stop']}  GD-C@10 unit W:L {doc['unit_W:L']} "
              f"({doc['discordant_units']} discordant of {doc['n_units']} units) -> {a.out}")
    else:
        print(f"{a.cmd}: wrote {a.out}" + ("" if code == 0 else " (FAILED)"))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gd.GdError as err:          # same exit convention as arms.py / score.py: one line, code 2
        print(f"evaluate.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
