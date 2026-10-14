"""§8 E3 (500-question harm check) of the GD experiment: offline raw files, scoring, gates.

prereg.md in this directory is the only spec; § numbers refer to it.

  e3_raw.py build --lists L.json --scores S.jsonl --k K --arm C|GD --out DIR
      GT v2 lists (arms.py --set gtv2) and their scores (score.py) -> DIR/raw_responses.json,
      DIR/run_meta.json and DIR/e3_build.json (format: _e3_build.py). Raw outputs belong in
      the store (reports/graph_gd_20261014/), and are never overwritten.
  e3_raw.py run --raw DIR --k K --arm C|GD [--dest D] [--allow-unpinned]
      quick_retrieval_eval.py --from-raw DIR/raw_responses.json --gt v2 --top-k K --metric-k K
      (metric_version must be 4d0826bb8d14); its output moves from results_quick/ to
      D/quick_eval.json, beside the run record D/e3_run.json (_e3_run.py). D defaults to
      e3/<arm>_k<K>/ in this directory.
  e3_raw.py gates --c5 D --gd5 D [--c10 D --gd10 D] [--out F] [--allow-unpinned]
      The three §8 gates on GD−C at k=5, k=10 reported only (_e3_gates.py); F defaults to
      e3/e3_gates.json. Gate 3 uses this process's GT v2 slot ruler, so gates first checks
      that quick_retrieval_eval.metric_version() is 4d0826bb8d14 here too (recorded in
      meta). Exit 0 when the gates pass, 1 when they do not, 2 on any error.

Guard: build reads GT v2 lists and scores, so it always needs gd.assert_set_allowed("gtv2")
(附錄 A filled, 驗收 A/B passed). run and gates retrieve nothing, but their official outputs
(anything under e3/) need the same guard and pinned inputs: a raw dir with the e3_build.json
that wrote it, and for gates a C and a GD run built from one lists and one scores file.
--allow-unpinned lets synthetic raw dirs (pipeline checks, no build record) be scored and
gated outside e3/ only. Every output carries the §10 meta (gd.collect_meta with SOURCE_FILES
and the data files' sha256). Errors exit 2 with one line.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _e3_build as B  # noqa: E402
import _e3_gates as G  # noqa: E402
import _e3_run as R  # noqa: E402
import _eval_inputs as I  # noqa: E402,E741
import _score_io as sio  # noqa: E402
import gd_common as gd  # noqa: E402

E3_DIR = _HERE / "e3"
GATES_OUT = E3_DIR / "e3_gates.json"
_SRC = R.EVAL_DIR / "src"
SOURCE_FILES = {
    "e3_raw.py": Path(__file__).resolve(),
    **{n: _HERE / n for n in ("_e3_build.py", "_e3_run.py", "_e3_gates.py", "_eval_inputs.py",
                              "_score_w.py")},                  # _eval_inputs imports _score_w
    "_score_io.py": Path(sio.__file__).resolve(),
    "quick_retrieval_eval.py": R.QRE_PATH,
    **{f"src/{n}": _SRC / n for n in (
        "__init__.py", "ab_stats.py", "book_names.py", "config.py", "data_loader.py", "gt_v2.py",
        "metrics/__init__.py", "metrics/retrieval.py", "models.py", "provenance.py",
        "rag_client.py", "reference_parser.py", "relevance_judge.py", "slot_coverage.py",
        "validity.py", "verse_coverage.py")}}


def is_official(path: Path) -> bool:
    """True for paths under e3/ (the outputs §8 keeps in this directory)."""
    return Path(path).resolve().is_relative_to(E3_DIR.resolve())


def guard_output(path: Path, allow_unpinned: bool) -> None:
    """Official outputs need the gtv2 guard and pinned inputs; scratch outputs need neither."""
    if not is_official(path):
        return
    if allow_unpinned:
        raise gd.GdError(f"--allow-unpinned never writes under {E3_DIR}; pass another output path")
    gd.assert_set_allowed(gd.GTV2)


def meta(command: str, files: Mapping[str, Path], **extra: Any) -> dict[str, Any]:
    return gd.collect_meta({**SOURCE_FILES, **files}, script=f"e3_raw.py {command}",
                           metric_version_required=R.METRIC_VERSION, **extra)


# ------------------------------------------------------------------ build

def _scores_arms(scores: I.Scores, arm: str) -> list[str] | None:
    """The arms the scores file scored (host "arms" of score.py rerank --arms; None = every
    arm of its lists); `arm` must be one of them."""
    recorded = {tuple((m.get("host") or {}).get("arms") or ()) for m in scores.metas}
    if len(recorded) != 1:
        raise gd.IntegrityError(f"{scores.path}: meta lines record different scored arms {sorted(recorded)}")
    arms = list(recorded.pop()) or None
    if arms is not None and arm not in arms:
        raise gd.GdError(f"{scores.path} scored arms {arms}, not {arm}")
    return arms


def build(lists_path: Path, scores_path: Path, k: int, arm: str, out: Path) -> dict[str, Any]:
    gd.assert_set_allowed(gd.GTV2)                       # before reading anything
    qset = gd.load_question_set(gd.GTV2)
    lists = I.Lists(lists_path, qset)
    scores = I.Scores(scores_path, qset, lists.content_sha256)
    if arm not in lists.arms:
        raise gd.GdError(f"{lists_path} has no arm {arm} (arms: {list(lists.arms)})")
    scored_arms = _scores_arms(scores, arm)
    items = B.arm_items(qset, lists.pools[arm], scores.by_qid, arm, k, B.load_source_rows())
    B.check_raw(items, qset, k, arm)
    shas = B.write_raw_dir(out, items)
    doc = {"meta": meta("build", {"lists": lists_path, "scores": scores_path,
                                  **{n: Path(out) / n for n in shas}}),
           "set": qset.name, "ids_sha256": qset.ids_sha256, "arm": arm, "k": k,
           "lists": str(Path(lists_path).resolve()), "lists_sha256": lists.content_sha256,
           "scores": str(Path(scores_path).resolve()), "scores_sha256": gd.file_sha256(scores_path),
           "scores_arms": scored_arms, "raw_sha256": shas}
    B.write_json(Path(out) / B.BUILD_NAME, doc)
    print(f"build gtv2 {arm}@{k}: {len(items)} questions -> {Path(out) / B.RAW_NAME}")
    return doc


# ------------------------------------------------------------------ run

def _build_record(raw_dir: Path, shas: Mapping[str, str], arm: str, k: int,
                  qset: gd.QuestionSet) -> dict[str, Any] | None:
    """The raw dir's e3_build.json, checked against these files, or None when it has none."""
    path = Path(raw_dir) / B.BUILD_NAME
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    got = {key: doc.get(key) for key in ("set", "ids_sha256", "arm", "k", "raw_sha256")}
    gd.expect(f"{path} vs the raw files", got, {"set": qset.name, "ids_sha256": qset.ids_sha256,
                                                 "arm": arm, "k": k, "raw_sha256": dict(shas)})
    return {key: doc.get(key) for key in ("lists", "lists_sha256", "scores", "scores_sha256",
                                          "scores_arms")} | {"sha256": gd.file_sha256(path)}


def run(raw_dir: Path, k: int, arm: str, dest: Path | None, allow_unpinned: bool) -> dict[str, Any]:
    dest = Path(dest) if dest else E3_DIR / f"{arm}_k{k}"
    guard_output(dest, allow_unpinned)
    qset = gd.load_question_set(gd.GTV2)
    items, run_meta, shas = B.read_raw(raw_dir)
    B.check_raw(items, qset, k, arm)
    built = _build_record(raw_dir, shas, arm, k, qset)
    if built is None and not allow_unpinned:
        raise gd.GdError(f"{raw_dir} has no {B.BUILD_NAME} (not written by e3_raw.py build); "
                         "--allow-unpinned scores it outside e3/ only")
    scored = R.score_raw(raw_dir, items, run_meta, k, arm, dest)
    raw_files = {n: Path(raw_dir) / n for n in shas}
    doc = {"meta": meta("run", {**raw_files, R.QUICK_NAME: dest / R.QUICK_NAME}),
           **R.run_record(arm, k, built, shas, scored)}
    B.write_json(dest / R.RECORD_NAME, doc)
    o = scored["summary"]["overall"]
    print(f"run {arm}@{k}: vrec {o.get('verse_recall_at_k')} mrr {o.get('mrr')} "
          f"(metric_version {scored['metric_version']}, results_quick unchanged) -> {dest}")
    return doc


# ------------------------------------------------------------------ gates

def _check_runs(runs: Mapping[int, tuple[R.Run, R.Run]], pinned: bool) -> None:
    """Each pair is (C, GD) at its k; all runs scored raw dirs with one run_meta.json and, when
    pinned, raw dirs that e3_raw.py build wrote from one lists and one scores file."""
    for k, (c, g) in runs.items():
        gd.expect(f"arms and k of {c.dest} / {g.dest}", ((c.arm, c.k), (g.arm, g.k)),
                  (("C", k), ("GD", k)))
    flat = [r for pair in runs.values() for r in pair]
    gd.expect("run_meta.json sha256 of every raw dir", {r.raw_sha256[B.RUN_META_NAME] for r in flat},
              {flat[0].raw_sha256[B.RUN_META_NAME]})
    if not pinned:
        return
    unpinned = [str(r.dest) for r in flat if not r.pinned]
    if unpinned:
        raise gd.GdError(f"{unpinned} scored raw dirs without {B.BUILD_NAME}; gates without "
                         "--allow-unpinned need raw dirs written by e3_raw.py build")
    sources = {(r.build["lists_sha256"], r.build["scores_sha256"]) for r in flat}
    if len(sources) != 1:
        raise gd.IntegrityError(f"the runs come from different lists / scores files: {sorted(sources)}")


def _inputs(runs: Sequence[R.Run]) -> dict[str, Any]:
    return {f"{r.arm}@{r.k}": {"dest": str(r.dest), "raw": str(r.raw_path), "pinned": r.pinned,
                               "raw_sha256": dict(r.raw_sha256), "build": r.build} for r in runs}


def gates(dirs: Mapping[int, tuple[Path, Path]], out: Path, allow_unpinned: bool) -> tuple[dict, int]:
    """dirs: k -> (C run dir, GD run dir); k=5 gated, k=10 reported."""
    guard_output(out, allow_unpinned)
    version = G.qre.metric_version()                 # gate 3 runs this process's slot ruler
    R.require_metric_version(version, "in-process quick_retrieval_eval (gates: GT v2 slot ruler)")
    qset = gd.load_question_set(gd.GTV2)
    runs = {k: tuple(R.load_run(d, qset) for d in pair) for k, pair in dirs.items()}
    _check_runs(runs, not allow_unpinned)
    ctx = G.ruler_context(runs[G.K_GATED][0].raw_path)
    ids = list(qset.ids)
    gold = {q: frozenset(item.gold_slots) for q, item in ctx.gt.by_id().items()}
    result: dict[str, Any] = {}
    for k, (c, g) in sorted(runs.items()):
        s_c, s_g = (G.source_slots(ctx.ruler, G.run_sources(r.raw_path, ctx, k)) for r in (c, g))
        result[f"k{k}"] = G.gate_k(ids, c.values, g.values, gold, s_c, s_g, gated=k == G.K_GATED)
    passed = result[f"k{G.K_GATED}"]["passed"]
    all_runs = [r for pair in runs.values() for r in pair]
    files = {f"{r.arm}@{r.k}/{n}": Path(r.dest) / n for r in all_runs for n in (R.QUICK_NAME, R.RECORD_NAME)}
    doc = {"meta": meta("gates", files, pinned=not allow_unpinned, ruler_build=ctx.ruler.build_id,
                        metric_version_in_process=version),
           "direction": "GD − C", "passed": passed, "inputs": _inputs(all_runs), **result}
    return doc, 0 if passed else 1


def _summary(doc: Mapping[str, Any]) -> str:
    g = doc[f"k{G.K_GATED}"]
    v, m, s = g["vrec"], g["mrr"], g["slot"]
    return (f"E3 gates k={G.K_GATED}: {'PASS' if doc['passed'] else 'FAIL'}  vrec CI lower "
            f"{v['ci95'][0]:+.4f} ({'ok' if v['pass'] else 'fail'}); MRR W:L {m['wins']}:{m['losses']} "
            f"CP lower {m.get('cp_lower', 'n/a')} ({'ok' if m['pass'] else 'fail'}); gold_out "
            f"{s['gold_out']} vs gained {s['gained']} ({'ok' if s['pass'] else 'fail'})")


# ------------------------------------------------------------------ CLI

def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return int(text)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="GT v2 lists + scores -> raw_responses.json + run_meta.json")
    p.add_argument("--lists", type=Path, required=True)
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--k", type=positive_int, required=True)
    p.add_argument("--arm", choices=B.E3_ARMS, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run", help="quick_retrieval_eval --from-raw on one raw dir")
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--k", type=positive_int, required=True)
    p.add_argument("--arm", choices=B.E3_ARMS, required=True)
    p.add_argument("--dest", type=Path, default=None, help="default: e3/<arm>_k<k>/")
    p.add_argument("--allow-unpinned", action="store_true", help="synthetic raw dirs, outside e3/")
    p = sub.add_parser("gates", help="the §8 gates on GD−C")
    for name in ("c5", "gd5"):
        p.add_argument(f"--{name}", type=Path, required=True)
    for name in ("c10", "gd10"):
        p.add_argument(f"--{name}", type=Path, default=None)
    p.add_argument("--out", type=Path, default=GATES_OUT)
    p.add_argument("--allow-unpinned", action="store_true", help="synthetic runs, outside e3/")
    return ap.parse_args(argv)


def _gate_dirs(a: argparse.Namespace) -> dict[int, tuple[Path, Path]]:
    if (a.c10 is None) != (a.gd10 is None):
        raise gd.GdError("--c10 and --gd10 come together")
    dirs = {G.K_GATED: (a.c5, a.gd5)}
    if a.c10 is not None:
        dirs[G.K_REPORTED] = (a.c10, a.gd10)
    return dirs


def _cmd_gates(a: argparse.Namespace) -> int:
    doc, code = gates(_gate_dirs(a), a.out, a.allow_unpinned)
    B.write_json(a.out, doc)
    print(f"{_summary(doc)} -> {a.out}")
    return code


def _cmd_build(a: argparse.Namespace) -> int:
    build(a.lists, a.scores, a.k, a.arm, a.out)
    return 0


def _cmd_run(a: argparse.Namespace) -> int:
    run(a.raw, a.k, a.arm, a.dest, a.allow_unpinned)
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "build": _cmd_build, "run": _cmd_run, "gates": _cmd_gates}


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        return COMMANDS[a.cmd](a)
    except (gd.GdError, OSError, ValueError, subprocess.SubprocessError,
            KeyError, TypeError, AttributeError) as err:   # never a traceback: exit 1 means FAIL
        print(f"e3_raw.py {a.cmd}: {type(err).__name__}: {' '.join(str(err).split())}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
