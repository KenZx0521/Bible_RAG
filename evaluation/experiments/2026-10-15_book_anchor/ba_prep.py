"""Inputs and run-start record of the book_anchor ablation (prereg §9 step 3.0 and smoke 1).

    ba_prep.py --out $OUT            # run_ba.sh 3.0 (also on every resume)
    ba_prep.py --out $OUT/smoke --smoke

Writes into --out (the container reads it as /in):
  questions.json   [{question_id, question}] of GT v2 (smoke: the six §6 questions)
  batch_a.json     eval3c's 43 ∪ {GBQ_073, EVENT_QUESTION_098} ∪ 40 random others (seed
                   20261015) ∪ eval3c full's first R1 question (by id)        [not in smoke]
  force_ids.json   the questions M1 runs every arm on although _book_anchor was not called:
                   the 40 random ones and the R1 question (smoke: the R1 question)
  exp_meta.json    HEAD, porcelain, image id, Ollama digests of e4b / 26b, refusal_v2 sha,
                   the 18 backend files' and this directory's *.py sha256 (HEAD's; smoke:
                   the working tree's, nothing being committed yet)
Not smoke: `git diff --quiet HEAD -- <this dir> evaluation/tests/test_ba_*.py` and no
untracked file there, else exit 2. A resumed run re-derives everything and requires it
unchanged (same HEAD, image, digests, inputs); nothing is overwritten.
The "random 40 non-C" are drawn outside eval3c's 43 (C itself only exists after retrieval).
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[2]
EVAL_ROOT = REPO / "evaluation"
for _p in (str(_HERE), str(EVAL_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _ba_checks as ck  # noqa: E402
import _ba_io as bio  # noqa: E402

EXP_REL = str(_HERE.relative_to(REPO))
TESTS_GLOB = "evaluation/tests/test_ba_*.py"
STORE = Path("/mnt/ollama-data/bible_rag_store")
REFUSAL = STORE / "reports" / "eval3c_20261014_analysis" / "refusal_v2.py"
IMAGE = "bible_rag-backend:r2"
OLLAMA = "http://localhost:11434"
REF = _HERE / "eval3c_ref.json"
SEED = 20261015
N_RANDOM = 40
GBQ = "GENERAL_BIBLE_QUESTION_"
EXTRA_A = (f"{GBQ}073", "EVENT_QUESTION_098")
SMOKE = tuple(f"{GBQ}{n}" for n in ("024", "096", "001", "050", "013"))


class PrepError(RuntimeError):
    pass


def _run(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, check=check)


def git(*args: str) -> bytes:
    return _run("git", "-C", str(REPO), *args).stdout


def assert_committed() -> None:
    """The experiment directory and its tests equal HEAD, with nothing untracked (§9 3.0)."""
    if _run("git", "-C", str(REPO), "diff", "--quiet", "HEAD", "--", EXP_REL, TESTS_GLOB,
            check=False).returncode:
        raise PrepError(f"{EXP_REL} or {TESTS_GLOB} differ from HEAD: commit ① first")
    untracked = git("ls-files", "--others", "--exclude-standard", "--", EXP_REL, TESTS_GLOB)
    if untracked.strip():
        raise PrepError(f"untracked files: {untracked.decode().split()}")


def head_sha(rel: str) -> str:
    return bio.sha256_bytes(git("show", f"HEAD:{rel}"))


def exp_shas(committed: bool) -> dict[str, str]:
    """This directory's *.py: HEAD's blobs (committed) or the working tree's."""
    if not committed:
        return {p.name: bio.sha256_file(p) for p in sorted(_HERE.glob("*.py"))}
    names = git("ls-tree", "--name-only", "HEAD", f"{EXP_REL}/").decode().split()
    return {Path(n).name: head_sha(n) for n in sorted(names) if n.endswith(".py")}


def image_id() -> str:
    out = _run("docker", "image", "inspect", "--format", "{{.Id}}", IMAGE).stdout.decode().strip()
    if not out.startswith(ck.IMAGE_PREFIX):
        raise PrepError(f"{IMAGE} is {out}, not {ck.IMAGE_PREFIX}…")
    return out


def ollama_digests() -> dict[str, str]:
    with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=30) as resp:  # noqa: S310
        models = json.loads(resp.read().decode("utf-8")).get("models", [])
    found = {m.get("name"): m.get("digest") for m in models}
    missing = [m for m in (ck.GEN_MODEL, ck.JUDGE_MODEL) if not found.get(m)]
    if missing:
        raise PrepError(f"Ollama has no digest for {missing}")
    return {m: found[m] for m in (ck.GEN_MODEL, ck.JUDGE_MODEL)}


def load_ref() -> dict[str, Any]:
    return json.loads(REF.read_text(encoding="utf-8"))


def questions(ids: list[str] | None = None) -> list[dict[str, str]]:
    from src.data_loader import load_gt

    items = load_gt("v2").items
    wanted = None if ids is None else set(ids)
    out = [{"question_id": i.question_id, "question": i.question} for i in items
           if wanted is None or i.question_id in wanted]
    if wanted is not None and len(out) != len(wanted):
        raise PrepError(f"not in GT v2: {sorted(wanted - {q['question_id'] for q in out})}")
    return out


def batch_a(all_ids: list[str], ref: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(batch_a, the 40 random non-C ids + the first R1 question)."""
    fixed = set(ref["c43"]) | set(EXTRA_A) | {ref["first_r1"]}
    pool = sorted(set(all_ids) - fixed)
    drawn = sorted(random.Random(SEED).sample(pool, N_RANDOM))
    return sorted(fixed | set(drawn)), sorted(set(drawn) | {ref["first_r1"]})


def build(smoke: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """(input files, exp_meta) of a run."""
    ref = load_ref()
    if smoke:
        qs = questions([*SMOKE, ref["first_r1"]])
        files = {"questions.json": qs, "force_ids.json": [ref["first_r1"]]}
    else:
        qs = questions()
        batch, force = batch_a([q["question_id"] for q in qs], ref)
        files = {"questions.json": qs, "batch_a.json": batch, "force_ids.json": force}
    meta = {"mode": "smoke" if smoke else "run", "head": git("rev-parse", "HEAD").decode().strip(),
            "image": IMAGE, "image_id": image_id(), "ollama_digests": ollama_digests(),
            "refusal_v2": str(REFUSAL), "refusal_v2_sha256": bio.sha256_file(REFUSAL),
            "backend_sha256": {f: head_sha(f"backend/{f}") for f in ck.BACKEND_FILES},
            "exp_sha256": exp_shas(committed=not smoke),
            "eval3c_ref_sha256": bio.sha256_file(REF),
            "inputs_sha256": {n: bio.sha256_bytes(_dump(d).encode()) for n, d in files.items()}}
    return files, meta


def _dump(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


STABLE = ("mode", "head", "image_id", "ollama_digests", "refusal_v2_sha256", "backend_sha256",
          "exp_sha256", "eval3c_ref_sha256", "inputs_sha256")


def write(out: Path, files: dict[str, Any], meta: dict[str, Any]) -> bool:
    """Write the inputs and exp_meta.json; on a resume require them unchanged. True: fresh."""
    old_path = out / "exp_meta.json"
    if old_path.exists():
        old = json.loads(old_path.read_text(encoding="utf-8"))
        changed = [k for k in STABLE if old.get(k) != meta.get(k)]
        if changed:
            raise PrepError(f"{old_path} records other {changed}: a resume must not change them")
        for name, doc in files.items():
            if (out / name).read_text(encoding="utf-8") != _dump(doc):
                raise PrepError(f"{out / name} differs from what prep derives now")
        return False
    out.mkdir(parents=True, exist_ok=True)
    for name, doc in files.items():
        (out / name).write_text(_dump(doc), encoding="utf-8")
    porcelain = git("status", "--porcelain").decode()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old_path.write_text(_dump({**meta, "created_at": stamp, "porcelain": porcelain}),
                        encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.smoke:
            assert_committed()
        files, meta = build(args.smoke)
        fresh = write(args.out, files, meta)
    except (PrepError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"ba_prep: {exc}", file=sys.stderr)
        return 2
    print(f"ba_prep: {'wrote' if fresh else 'verified'} {args.out} "
          f"({len(files['questions.json'])} questions, HEAD {meta['head'][:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
