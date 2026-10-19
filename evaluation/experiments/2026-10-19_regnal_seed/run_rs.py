"""Driver of the rule-seed regression (prereg.md). Host python -B (the evaluation venv).

    python -B run_rs.py build   --layer L --lexicon X --out DIR    # cards.json, jobs.json (CPU)
    python -B run_rs.py repro   --out DIR                          # scorers on experiment A's records (CPU)
    python -B run_rs.py dry-run --layer L --lexicon X [--out DIR]  # the whole flow with the fake chat
    python -B run_rs.py run     --layer L --lexicon X --out DIR [--rerun-of OLD]   # Ollama
    python -B run_rs.py score   --out DIR                          # scores.json, verdict.json (CPU)

Every --out must lie under the store's reports/regnal_seed_20261019/ (``rs_common.cli_out``; repro may
write to that directory itself). ``build`` writes only to a directory without a run. ``run`` is the only
command that calls Ollama, and it refuses unless prereg.md is the committed formal version naming the
layer's, the lexicon's and the backend files' sha256 (no draft mark, no placeholder), the harness
directory is committed and unchanged, experiment A's frozen files and prompts match, the directory's
jobs.json and cards.json (when there) are this build's, the directory is not a dry run's, no other
formal run of these jobs or this layer exists (but for one --rerun-of after a digest mismatch) and the
model digest is the expected one. ``score`` refuses an uncommitted harness and cards or jobs that are
not the run's. Only counts, ids and sha256 values are printed, never a question, a card or an answer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rs_common as C  # noqa: E402
import rs_jobs as J  # noqa: E402
import rs_run as R  # noqa: E402


def _build(args) -> tuple[dict, list[dict], dict]:
    bad = C.frozen_problems()
    if bad:
        raise SystemExit(f"experiment A's frozen files or prompts differ: {bad}")
    return R.build(args.layer, args.lexicon)


def _counts(doc: dict, jobs: list[dict]) -> dict:
    return {"layer_sha256": doc["header"]["layer_sha256"], "lexicon_sha256": doc["header"]["lexicon_sha256"],
            "backend_sha256": doc["header"]["backend_sha256"], "taken": {s: len(v) for s, v in doc["items"].items()},
            "not_taken": doc["not_fired"], **J.summary(jobs)}


def _norm(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def build(args) -> None:
    out = C.cli_out(args.out)
    if (out / R.RUN_META).exists() or (out / R.GEN).exists():
        raise SystemExit(f"{out} holds a run: build writes only to a directory without one")
    doc, jobs, _ = _build(args)
    C.write_json(out / "cards.json", doc)
    C.write_json(out / "jobs.json", jobs)
    rep = _counts(doc, jobs)
    C.write_json(out / "build_report.json", rep)
    print(rep)


def run(args) -> None:
    out = C.cli_out(args.out)
    doc, jobs, _ = _build(args)
    h = doc["header"]
    bad = C.prereg_problems(C.PREREG.read_text(encoding="utf-8"), h["layer_sha256"],
                            lexicon_sha=h["lexicon_sha256"], backend_files=h["backend_files_sha256"])
    bad += C.prereg_git_problems()
    if bad:
        raise SystemExit(f"prereg.md is not the committed formal version for layer {h['layer_sha256']}: {bad}")
    if (out / "jobs.json").exists() and J.jobs_sha256(C.read_json(out / "jobs.json")) != J.jobs_sha256(jobs):
        raise SystemExit(f"{out / 'jobs.json'} is another job list than this build's")
    if (out / "cards.json").exists() and C.read_json(out / "cards.json") != _norm(doc):
        raise SystemExit(f"{out / 'cards.json'} holds other cards than this build's")
    meta = R.execute(jobs, out, R.real_chat, R.api_get, rerun_of=args.rerun_of, pins=R.pins_of(doc),
                     runs_root=C.OUT_ROOT, write={"cards.json": doc, "jobs.json": jobs})
    print({k: meta.get(k) for k in ("n_jobs", "n_done", "n_errors", "digest_before", "digest_after", "attempt")})


def score(args) -> None:
    import rs_cards as K
    import rs_score as S
    out = C.cli_out(args.out)
    _, v = S.score_run(out, C.read_json(out / "cards.json"), C.read_json(out / "jobs.json"), K.store_items(),
                       require_clean=True)
    print(v["result"], "|", v["wording"])


def repro(args) -> None:
    import rs_score as S
    out = C.cli_out(args.out, allow_root=True)
    rep = S.reproduce()
    C.write_json(out / "repro.json", rep)
    print({k: {kk: vv for kk, vv in v.items() if kk != "missing"} for k, v in rep.items()})


def dry_run(args) -> None:
    out = C.cli_out(args.out or C.OUT_ROOT / "dry_run")
    bad = C.frozen_problems()
    if bad:
        raise SystemExit(f"experiment A's frozen files or prompts differ: {bad}")
    rep = R.dry_run(args.layer, args.lexicon, out)
    print({k: rep[k] for k in ("layer_sha256", "n_jobs", "by_set_arm", "jobs_sha256", "estimate")})
    print({k: v for k, v in rep["verdict"].items() if k in ("result", "pass", "dry_judgment")}, "(假 chat，分數無意義)")


CMDS = {"build": build, "run": run, "score": score, "repro": repro, "dry-run": dry_run}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="年表卡規則種子的樣本內回歸（prereg.md）")
    ap.add_argument("cmd", choices=list(CMDS))
    ap.add_argument("--layer", type=Path, help="regnal_layer.json（build、run、dry-run 必填）")
    ap.add_argument("--lexicon", type=Path, help="routing_lexicon.json（build、run、dry-run 必填）")
    ap.add_argument("--out", type=Path, help="store reports/regnal_seed_20261019/ 下的目錄（只准寫在那裡）")
    ap.add_argument("--rerun-of", type=Path, default=None, help="run：digest 不符後的唯一一次重跑")
    args = ap.parse_args(argv)
    if args.cmd in ("build", "run", "dry-run") and not (args.layer and args.lexicon):
        ap.error(f"{args.cmd} needs --layer and --lexicon")
    if args.cmd != "dry-run" and not args.out:
        ap.error(f"{args.cmd} needs --out")
    CMDS[args.cmd](args)


if __name__ == "__main__":
    main()
