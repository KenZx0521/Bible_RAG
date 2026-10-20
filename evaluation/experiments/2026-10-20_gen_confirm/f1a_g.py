"""The F1a freeze of the GEN confirmation set (prereg §3.8 F1a, §5.4, §5.6, §8.1-4): store f1a_pins.json, written once.

F1a comes after P1 and before P2. It pins the F1a group, f1_g.f1a_paths(): gencard/*.py, store gen_names.json,
mech_g.py and the P2 validity check mech_qg.py (§5.6), keyed as f1_g keys them (repo-relative for repository files,
store-relative for gen_names.json), and beside it the P2 path, ``p2_paths()``: the rest of what the P2 validity
check runs (prompts_g.py for the slot view and the names, transcript_g.py and banned_g.py for the blinding void,
qset.md §3) and P2's own scorer, spec and prompt (run_qg.py, spec_qg.py, prompt_qg.py, prompts_qg.md), the
constants module g_common.py (P2's counts, G1's n and the qset file names live there, §3.9) and the GT v1 / v2
files of the GT nail. The document is exactly
  {"files": f1_g.sha_map(f1_g.f1a_paths()), "p2_files": f1_g.sha_map(p2_paths()), "t": ..., "git_head": ...,
   "checks": {"p1_scores", "git", "tests", "test_files"}}
(f1_g.f1a_problems reads "files": the P2 runner and the F1 manifest refuse any group file that differs from it;
``p2_problems`` reads "p2_files": the P2 runner refuses any P2-path file that differs, so between F1a and P2's
score nothing that decides a P2 item's validity or count can change; the P2-path files stay out of the F1
manifest, where prompts_g.py and banned_g.py are F1's own files, frozen at F1).
It is refused when f1a_pins.json exists (once only); out of order (§8.1: no P1 score in qset/p1/scores.jsonl yet,
or anything of a P2 run under qset/p2/ but its spec and lock: a draft, transcript, prompts record, reservation or
record); when a group, P2-path or nail-test file is missing; when one of their repository files is untracked or
differs from HEAD (f1_g.uncommitted); unless §5.3's nail tests and the mech bank pass now in a fresh interpreter:
pytest on TEST_FILES (the gencard nails with the store pins, the mech bank, the names contract with the store
rebuild, and the qset tests), with no failure, error, skip, xfail, xpass or deselection (a skipped store test pins
nothing); or when any of those files changed while the tests ran (the sha are taken before and after). "checks"
records the P1 score count, git's verdict, the test counts and the nail tests' sha256. ``main`` prints the sha256
of f1a_pins.json and of each pinned file for 執行紀錄; nothing else. Nothing here calls an LLM.

    f1a_g.py            write store f1a_pins.json (once)
    f1a_g.py --check    the group and the P2 path now against the written f1a_pins.json (problems only)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import f1_g as F1
import g_common as GC

TEST_FILES = ("test_gen_confirm_gencard.py", "test_gen_confirm_mech.py", "test_gen_confirm_names.py",
              "test_gen_confirm_qset.py", "test_gen_confirm_qset_run.py")
TESTS_DIR = GC.TESTS_DIR
TEST_TIMEOUT_S = 3600
P2_FILES = ("prompts_g.py", "banned_g.py", "transcript_g.py", "run_qg.py", "spec_qg.py", "prompt_qg.py",
            "prompts_qg.md", "g_common.py")
GT_FILES = GC.GT_FILES
P2_SPARE = frozenset({GC.QSET_SPEC, GC.QSET_LOCK})      # qset/p2 files that are not a P2 run
P1, P2 = GC.QSET_SETS
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)")
NOT_RUN = ("failed", "errors", "skipped", "xfailed", "xpassed", "deselected")
Paths = Mapping[str, Path]


def _keyed(files: Sequence[Path], repo: Path) -> dict[str, Path]:
    """{repo-relative key: file}, unresolved (HERE and REPO are resolved; a symlinked checkout file stays keyed)."""
    return {Path(p).relative_to(repo).as_posix(): Path(p) for p in files}


def p2_paths(here: Path = GC.HERE, repo: Path = GC.REPO, gt: Sequence[Path] = GT_FILES) -> dict[str, Path]:
    """{repo-relative key: file} of the P2 path (module docstring)."""
    return _keyed([Path(here) / n for n in P2_FILES] + [Path(g) for g in gt], repo)


def nail_paths(files: Sequence[str] = TEST_FILES, tests_dir: Path = TESTS_DIR, repo: Path = GC.REPO) -> dict[str, Path]:
    return _keyed([Path(tests_dir) / f for f in files], repo)


def p2_problems(now: Mapping[str, str | None], doc: Mapping[str, Any] | None) -> list[str]:
    """The P2 path now (sha256 or None) against f1a_pins.json's "p2_files" (paths only in the messages)."""
    if not isinstance(doc, Mapping) or not isinstance(doc.get("p2_files"), dict):
        return ["f1a_pins.json has no p2_files map"]
    return F1.f1a_problems(dict(now), {"files": doc["p2_files"]})


def pytest_counts(last_line: str) -> dict[str, int]:
    """{passed, failed, skipped, errors, ...} of pytest's summary line."""
    out = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for n, what in _COUNT.findall(last_line or ""):
        out["errors" if what.startswith("error") else what] = int(n)
    return out


def run_tests(files: Sequence[str] = TEST_FILES, tests_dir: Path = TESTS_DIR) -> dict[str, Any]:
    """The nail tests and the mech bank in a fresh interpreter: the return code and the counts."""
    paths = [str(Path(tests_dir) / f) for f in files]
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths], cwd=GC.REPO,
                       capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
    last = (r.stdout.strip().splitlines() or ["no output"])[-1]
    return {"files": list(files), "returncode": r.returncode, **pytest_counts(last), "summary": last[-200:]}


def nail_problems(rec: Mapping[str, Any]) -> list[str]:
    bad = [] if rec.get("returncode") == 0 else [f"pytest exit {rec.get('returncode')}"]
    bad += [f"{rec[k]} {k}" for k in NOT_RUN if rec.get(k)]
    return bad + ([] if rec.get("passed") else ["no test passed"])


def git_problems(paths: Paths, repo: Path = GC.REPO) -> list[str]:
    """Repository files among ``paths`` that are untracked or changed since HEAD (store files: by sha only)."""
    root = Path(repo).resolve()
    return F1.uncommitted([p for p in paths.values() if root in Path(p).resolve().parents], repo)


def order_problems(qset_root: Path = GC.QSET_ROOT) -> tuple[list[str], int]:
    """(why F1a is out of order, the number of P1 scores): F1a needs a P1 score and nothing of a P2 run (§8.1)."""
    scores = Path(qset_root) / P1 / GC.P1_SCORES
    n = len([ln for ln in scores.read_text(encoding="utf-8").splitlines() if ln.strip()]) if scores.is_file() else 0
    p2 = Path(qset_root) / P2
    ran = [f for f in p2.rglob("*") if f.is_file() and f.relative_to(p2).as_posix() not in P2_SPARE] if p2.is_dir() else []
    bad = [] if n else ["no P1 score yet (qset/p1/scores.jsonl): F1a comes after P1"]
    return bad + ([f"{len(ran)} file(s) of a P2 run under qset/p2: F1a comes before P2"] if ran else []), n


def build(paths: Paths | None = None, git: Callable[[Paths], list[str]] | None = None,
          tests: Callable[[], Mapping[str, Any]] | None = None, qset_root: Path = GC.QSET_ROOT, *,
          p2: Paths | None = None, test_paths: Paths | None = None) -> dict[str, Any]:
    """The f1a_pins.json document, or SystemExit with every reason it is refused."""
    groups = {"files": dict(F1.f1a_paths() if paths is None else paths), "p2_files": dict(p2_paths() if p2 is None else p2),
              "test_files": dict(nail_paths() if test_paths is None else test_paths)}
    every = {k: v for g in groups.values() for k, v in g.items()}
    before = F1.sha_map(every)
    bad, p1_scores = order_problems(qset_root)
    bad += [f"missing: {k}" for k, v in before.items() if v is None]
    bad += [f"not committed or changed since HEAD: {r}" for r in (git or git_problems)(every)]
    if bad:
        raise SystemExit(f"f1a_pins.json refused: {bad}")
    rec = dict((tests or run_tests)())
    if t := nail_problems(rec):
        raise SystemExit(f"f1a_pins.json refused: the nail tests and the mech bank do not pass now ({t})")
    if changed := sorted(k for k, v in F1.sha_map(every).items() if v != before[k]):
        raise SystemExit(f"f1a_pins.json refused: {changed} changed while the tests ran")
    head = subprocess.run(["git", "-C", str(GC.REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    sha = {g: {k: before[k] for k in m} for g, m in groups.items()}
    return {"files": sha["files"], "p2_files": sha["p2_files"], "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_head": head or None, "checks": {"p1_scores": p1_scores, "git": "committed and unchanged",
                                                 "tests": rec, "test_files": sha["test_files"]}}


def write(out: Path = GC.F1A_LOG, paths: Paths | None = None, git: Callable[[Paths], list[str]] | None = None,
          tests: Callable[[], Mapping[str, Any]] | None = None, qset_root: Path = GC.QSET_ROOT, *,
          p2: Paths | None = None, test_paths: Paths | None = None) -> dict[str, Any]:
    """Write f1a_pins.json once (prereg §3.8); refused when it exists or ``build`` refuses."""
    if Path(out).exists():
        raise SystemExit(f"{out} exists: F1a is written once (prereg §3.8)")
    doc = build(paths, git, tests, qset_root, p2=p2, test_paths=test_paths)
    GC.write_json(out, doc)
    return doc


def check() -> list[str]:
    if not GC.F1A_LOG.is_file():
        return [f"{GC.F1A_LOG.name} missing"]
    doc = GC.read_json(GC.F1A_LOG)
    return F1.f1a_problems(F1.sha_map(F1.f1a_paths()), doc) + p2_problems(F1.sha_map(p2_paths()), doc)


def main(argv: Sequence[str]) -> int:
    if "--check" in argv:
        bad = check()
        print(json.dumps({"problems": bad}, ensure_ascii=False))
        return 0 if not bad else 1
    doc = write()
    print(json.dumps({"f1a_pins.json": GC.sha256_file(GC.F1A_LOG), "files": doc["files"], "p2_files": doc["p2_files"],
                      "tests": {k: doc["checks"]["tests"][k] for k in ("passed", "failed", "skipped", "errors")}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
