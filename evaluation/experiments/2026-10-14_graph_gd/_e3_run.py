"""§8 E3 scoring of one raw dir with quick_retrieval_eval.py (private part of e3_raw.py).

score_raw() runs, in a subprocess of this interpreter with bytecode writing off,
    quick_retrieval_eval.py --from-raw <dir>/raw_responses.json --gt v2 --top-k k --metric-k k
(evaluation/quick_retrieval_eval.py:436-498: the GT v2 ruler of the build named by the dir's
run_meta.json), after checking that its metric_version() is METRIC_VERSION. E3 runs hold
an exclusive lock (flock on results_quick's parent directory, no lock file) from the first
listing to the last, so they run one after another. The output quick_retrieval_eval
writes to evaluation/results_quick/<label>.json always leaves results_quick first, to
<dest>/failed/<label>.json; only when results_quick then lists exactly as it began (a
results_quick that did not exist is removed again) is it promoted to <dest>/quick_eval.json.
A failed quick_retrieval_eval, or a file someone else wrote beside it, leaves the output in
failed/ and stops the run (§8: results_quick 不留檔). The promoted output is checked
against the raw (build, GT v2 sha, encoder fingerprint, k, metric_version, every question
valid, the same source ids) before the run is accepted. The run record (e3_run.json,
written by e3_raw.py run) holds run_record(); load_run() reads a destination back for the
gates, re-checking the raw files' sha256 and the output against them.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

import gd_common as gd
from _e3_build import BUILD_NAME, RAW_NAME, check_raw, read_raw

__all__ = ["EVAL_DIR", "QRE_PATH", "RESULTS_QUICK", "METRIC_VERSION", "QUICK_NAME", "RECORD_NAME",
           "FAILED_DIR", "RECORD_KEYS", "Listing", "metric_version_now", "require_metric_version",
           "listing", "unique_label", "results_lock", "run_quick", "stage_output", "take_output",
           "verify_quick", "score_raw", "run_record", "Run", "load_run"]

EVAL_DIR = gd.EXP_DIR.parents[1]                       # evaluation/
QRE_PATH = EVAL_DIR / "quick_retrieval_eval.py"
RESULTS_QUICK = EVAL_DIR / "results_quick"
METRIC_VERSION = "4d0826bb8d14"                        # §4 / §8: the GT v2 metric code
QUICK_NAME = "quick_eval.json"                         # the moved quick_retrieval_eval output
RECORD_NAME = "e3_run.json"                            # §10 meta of the run step
FAILED_DIR = "failed"                                  # dest/failed/: outputs of runs that stopped
RECORD_KEYS = ("arm", "k", "pinned", "build", "raw_sha256", "raw_path", "metric_version",
               "quick_eval_sha256")
_ENV = {"PYTHONDONTWRITEBYTECODE": "1"}
_PROBE = ("import sys; sys.argv = ['probe']; sys.path.insert(0, {d!r}); "
          "import quick_retrieval_eval as q; print(q.metric_version())")

Listing = tuple[bool, tuple[str, ...]]                 # (directory existed, sorted entry names)


def _python(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", *args], cwd=EVAL_DIR, capture_output=True,
                          text=True, env={**os.environ, **_ENV})


def _last_line(text: str) -> str:
    lines = [s for s in text.strip().splitlines() if s.strip()]
    return lines[-1] if lines else "(no output)"


def metric_version_now() -> str:
    """quick_retrieval_eval.metric_version() as a fresh interpreter computes it now."""
    proc = _python(["-c", _PROBE.format(d=str(EVAL_DIR))])
    if proc.returncode != 0:
        raise gd.GdError(f"metric_version probe failed: {_last_line(proc.stderr)}")
    return proc.stdout.strip()


def require_metric_version(got: str, where: str) -> None:
    if got != METRIC_VERSION:
        raise gd.IntegrityError(f"{where}: metric_version {got!r} is not {METRIC_VERSION!r} (§8); stop")


def listing(directory: Path = RESULTS_QUICK) -> Listing:
    directory = Path(directory)
    return (directory.is_dir(), tuple(sorted(os.listdir(directory))) if directory.is_dir() else ())


def unique_label(arm: str, k: int) -> str:
    return f"gd_e3_{arm}_k{k}_{os.getpid()}_{time.time_ns()}"


def run_quick(raw_path: Path, k: int, label: str) -> str:
    """quick_retrieval_eval.py --from-raw … --gt v2 --top-k k --metric-k k; returns stdout."""
    proc = _python([str(QRE_PATH), "--from-raw", str(raw_path), "--gt", "v2", "--top-k", str(k),
                    "--metric-k", str(k), "--label", label])
    if proc.returncode != 0:
        raise gd.GdError(f"quick_retrieval_eval.py exited {proc.returncode}: {_last_line(proc.stderr)}")
    return proc.stdout


@contextlib.contextmanager
def results_lock(directory: Path = RESULTS_QUICK) -> Iterator[None]:
    """Exclusive flock on the parent of `directory` (evaluation/ for results_quick): one E3
    run at a time touches results_quick. Waits for a running one; no lock file is left."""
    fd = os.open(Path(directory).parent, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"e3_raw.py: waiting for another E3 run to finish with {directory}", file=sys.stderr)
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                                   # closing the descriptor drops the lock


def stage_output(label: str, dest: Path, before: Listing, directory: Path = RESULTS_QUICK) -> Path | None:
    """Move <directory>/<label>.json (when it exists) to dest/failed/<label>.json, before
    anything else is checked, and remove a directory the run created when it is empty again."""
    out = Path(directory) / f"{label}.json"
    staged = None
    if out.exists():
        staged = Path(dest) / FAILED_DIR / out.name
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(staged))
    if not before[0] and Path(directory).is_dir() and not os.listdir(directory):
        Path(directory).rmdir()
    return staged


def take_output(label: str, dest: Path, before: Listing, directory: Path = RESULTS_QUICK) -> Path:
    """This run's output out of `directory` first (stage_output), then promoted to
    dest/quick_eval.json only when the directory lists exactly as `before`; otherwise it
    stays in dest/failed/ and IntegrityError names what else appeared or vanished."""
    staged = stage_output(label, dest, before, directory)
    if staged is None:
        raise gd.GdError(f"quick_retrieval_eval.py wrote no {Path(directory) / label}.json")
    after = listing(directory)
    if after != before:
        gained = sorted(set(after[1]) - set(before[1]))
        lost = sorted(set(before[1]) - set(after[1]))
        raise gd.IntegrityError(f"{directory} gained {gained} and lost {lost} beside this run's output "
                                f"(kept in {staged}, not accepted); results_quick must not keep files (§8)")
    target = Path(dest) / QUICK_NAME
    shutil.move(str(staged), str(target))
    with contextlib.suppress(OSError):
        staged.parent.rmdir()                          # only when failed/ is empty
    return target


def _expected_meta(run_meta: Mapping[str, Any]) -> dict[str, Any]:
    return {"data_build_id": gd.BUILD_ID, "gt_version": "v2", "gt_sha": gd.GTV2_SHA256,
            "encoder_fingerprint": run_meta["encoder_fingerprint"]}


def verify_quick(doc: Mapping[str, Any], items: Sequence[Mapping[str, Any]], k: int,
                 raw_path: Path, run_meta: Mapping[str, Any]) -> dict[str, Any]:
    """The moved output scored these raw items: meta, config, validity and source ids."""
    require_metric_version((doc.get("config") or {}).get("metric_version"), "quick_eval.json")
    gd.expect("quick_eval meta", dict(doc.get("meta") or {}), _expected_meta(run_meta))
    cfg = {key: (doc.get("config") or {}).get(key) for key in ("from_raw", "top_k", "metric_k")}
    gd.expect("quick_eval config", cfg, {"from_raw": str(raw_path), "top_k": k, "metric_k": k})
    per_q = doc.get("per_question") or {}
    gd.expect("quick_eval questions (n, n_invalid)", (doc.get("n"), doc.get("n_invalid")),
              (len(items), 0))
    gd.expect("quick_eval question ids", sorted(per_q), sorted(i["question_id"] for i in items))
    for item in items:
        got = per_q[item["question_id"]].get("sources")
        gd.expect(f"{item['question_id']} scored sources", got, [s["id"] for s in item["sources"]])
    return {"n": doc["n"], "n_invalid": doc["n_invalid"], "overall": doc.get("overall")}


def score_raw(raw_dir: Path, items: Sequence[Mapping[str, Any]], run_meta: Mapping[str, Any],
              k: int, arm: str, dest: Path, directory: Path = RESULTS_QUICK) -> dict[str, Any]:
    """Run quick_retrieval_eval on raw_dir and leave its output in dest/quick_eval.json
    (`directory` is where it writes, results_quick; tests point it elsewhere)."""
    if (Path(dest) / QUICK_NAME).exists() or (Path(dest) / RECORD_NAME).exists():
        raise gd.GdError(f"{dest} already holds an E3 run; outputs are not overwritten")
    version = metric_version_now()
    require_metric_version(version, "quick_retrieval_eval.py")
    raw_path = Path(raw_dir).resolve() / RAW_NAME
    label = unique_label(arm, k)
    with results_lock(directory):
        before = listing(directory)
        if f"{label}.json" in before[1]:
            raise gd.GdError(f"{Path(directory) / label}.json exists already")
        try:
            stdout = run_quick(raw_path, k, label)
        except BaseException:                          # its output, if any, still leaves results_quick
            stage_output(label, dest, before, directory)
            raise
        target = take_output(label, dest, before, directory)
        unchanged = listing(directory) == before
    doc = json.loads(target.read_text(encoding="utf-8"))
    summary = verify_quick(doc, items, k, raw_path, run_meta)
    return {"label": label, "metric_version": version, "raw_path": str(raw_path),
            "quick_eval": str(target), "quick_eval_sha256": gd.file_sha256(target),
            "results_quick_unchanged": unchanged, "summary": summary,
            "stdout_tail": stdout.strip().splitlines()[-12:]}


def run_record(arm: str, k: int, build: Mapping[str, Any] | None, raw_sha256: Mapping[str, str],
               scored: Mapping[str, Any]) -> dict[str, Any]:
    """The body of e3_run.json (its §10 meta is added by e3_raw.py)."""
    return {"arm": arm, "k": k, "pinned": build is not None, "build": build,
            "raw_sha256": dict(raw_sha256), **scored}


@dataclass(frozen=True)
class Run:
    dest: Path
    arm: str
    k: int
    pinned: bool
    build: Mapping[str, Any] | None
    raw_path: Path
    raw_sha256: Mapping[str, str]
    values: Mapping[str, Mapping[str, float]]      # "vrec" / "mrr" -> {qid: value}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise gd.IntegrityError(f"cannot read {path}: {err}") from None


def load_run(dest: Path, qset: gd.QuestionSet) -> Run:
    """A finished E3 run: its record, the output it moved and the raw files it scored, all
    re-checked (sha256, raw shape, output vs raw)."""
    dest = Path(dest)
    rec = _read_json(dest / RECORD_NAME)
    absent = [key for key in RECORD_KEYS if not isinstance(rec, dict) or key not in rec]
    if absent:
        raise gd.IntegrityError(f"{dest / RECORD_NAME}: run record lacks {absent}")
    gd.expect(f"{dest / QUICK_NAME} sha256", gd.file_sha256(dest / QUICK_NAME), rec.get("quick_eval_sha256"))
    require_metric_version(rec.get("metric_version"), str(dest / RECORD_NAME))
    raw_path = Path(rec["raw_path"])
    items, run_meta, shas = read_raw(raw_path.parent)
    gd.expect(f"{raw_path.parent} raw files sha256", shas, rec.get("raw_sha256"))
    build = rec.get("build")
    if (build is not None) != (rec.get("pinned") is True):
        raise gd.IntegrityError(f"{dest / RECORD_NAME}: 'pinned' and 'build' disagree")
    if build is not None:
        gd.expect(f"{raw_path.parent / BUILD_NAME} sha256", gd.file_sha256(raw_path.parent / BUILD_NAME),
                  build.get("sha256"))
    check_raw(items, qset, rec["k"], rec["arm"])
    doc = _read_json(dest / QUICK_NAME)
    verify_quick(doc, items, rec["k"], raw_path, run_meta)
    per_q = doc["per_question"]
    values = {name: MappingProxyType({q: float(per_q[q][key]) for q in qset.ids})
              for name, key in (("vrec", "verse_recall_at_k"), ("mrr", "mrr"))}
    return Run(dest, rec["arm"], rec["k"], build is not None, build, raw_path,
               MappingProxyType(shas), MappingProxyType(values))
