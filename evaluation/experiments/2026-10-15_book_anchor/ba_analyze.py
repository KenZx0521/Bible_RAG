"""Host-side steps of the book_anchor ablation (prereg §6, §9, §11).

    ba_analyze.py smoke --out $OUT/smoke       smoke 3: I0/I1/I2/I3/I4 + the §6 expectations;
                                               on pass gen_plan.json and checks/judge_ids_*
    ba_analyze.py check --out $OUT --partial   3.1: I0–I4 on batch A → checks/invariants_partial.json
    ba_analyze.py check --out $OUT             3.3: I0–I5, completeness, subsets, mechanisms,
                                               overlap, gen_plan, judge_ids, judge_order, freeze
    ba_analyze.py export-retr --out $OUT       3.4: retr/{ctrl,nopin,off}/
    ba_analyze.py export-ans --out $OUT        3.6 / smoke 5: ans/{arm}_r{k}/
    ba_analyze.py judge-order --out $OUT --kind strict|coverage   one directory per line
    ba_analyze.py report --out $OUT            3.9: report/report.json and report.md
    ba_analyze.py trim FILE                    cut a JSON-lines file back to its last newline
    ba_analyze.py make-ref [--ba39 PATH]       rebuild the frozen eval3c_ref.json

Exit 0 pass, 1 a check failed (stop the line), 2 bad input. The frozen files are written
once; a later check (a resume) recomputes them and refuses any difference.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
EVAL_ROOT = _HERE.parents[1]
for _p in (str(_HERE), str(EVAL_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import src  # noqa: E402,F401  (puts packages/ — ragcommon — on sys.path)
import _ba_checks as ck  # noqa: E402
import _ba_export as bex  # noqa: E402
import _ba_io as bio  # noqa: E402

STORE = Path("/mnt/ollama-data/bible_rag_store")
EVAL3C = STORE / "reports" / "eval3c_20261014"
PATHS = {"raw": EVAL3C / "full" / "raw_responses.json",
         "run_meta": EVAL3C / "full" / "run_meta.json",
         "faith": EVAL3C / "full.faith_cov.json",
         "lexicon": STORE / "contracts" / ck.BUILD_ID / "routing_lexicon.json",
         "refusal": STORE / "reports" / "eval3c_20261014_analysis" / "refusal_v2.py"}
REF = _HERE / "eval3c_ref.json"
SMOKE_QID = "GENERAL_BIBLE_QUESTION_024"


class AnalyzeError(RuntimeError):
    pass


def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnalyzeError(f"cannot read {path}: {exc}") from None


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ck.dumps(doc), encoding="utf-8")


def load_ref() -> dict[str, Any]:
    """eval3c_ref.json, refusing when an eval3c source it was built from has changed."""
    ref = _json(REF)
    for key, path in (("raw", PATHS["raw"]), ("run_meta", PATHS["run_meta"]),
                      ("faith", PATHS["faith"])):
        if bio.sha256_file(path) != ref["meta"][f"{key}_sha256"]:
            raise AnalyzeError(f"{path} changed since eval3c_ref.json was built")
    return ref


def eval3c_raw() -> dict[str, dict]:
    return {x["question_id"]: x for x in _json(PATHS["raw"])}


def invariants(metas, rows, exp_meta) -> dict[str, Any]:
    i0 = ck.check_i0(metas, backend_expected=exp_meta.get("backend_sha256") or {},
                     exp_expected=exp_meta.get("exp_sha256") or {},
                     encoder_expected=_json(PATHS["run_meta"])["encoder_fingerprint"],
                     exp_meta=exp_meta)
    subs = ck.subsets(rows)
    return {"I0": {"ok": not i0, "problems": i0}, "I1": ck.check_i1(rows, eval3c_raw()),
            "I2": ck.check_i2(rows), "I3": ck.check_i3(subs), "I4": ck.check_i4(rows)}


def _summary(inv: dict[str, Any]) -> str:
    return "  ".join(f"{k}={'ok' if v.get('ok') else 'FAIL'}" for k, v in inv.items()
                     if "ok" in v)


# ---------------------------------------------------------------- smoke / check

def cmd_smoke(out: Path) -> int:
    metas, rows = ck.load_retrieval(out / "retrieval.jsonl")
    ref = load_ref()
    inv = invariants(metas, rows, _json(out / "exp_meta.json"))
    problems = ck.smoke_problems(rows, ref["first_r1"])
    ok = all(v["ok"] for v in inv.values()) and not problems
    _write(out / "smoke_check.json", {"ok": ok, "invariants": inv, "expectations": problems})
    print(f"smoke: {_summary(inv)}  expectations={'ok' if not problems else problems}")
    if inv["I1"]["route_diff"]:
        print(f"smoke: routes differ from eval3c (listed, not judged): {inv['I1']['route_diff']}")
    if not ok:
        return 1
    _write(out / "gen_plan.json", ck.smoke_plan(rows, SMOKE_QID))
    for arm in ck.ARMS:
        _write(out / "checks" / f"judge_ids_{arm}.json", [SMOKE_QID])
    return 0


def frozen_docs(rows: dict, subs: dict) -> dict[str, Any]:
    ids = ck.judge_ids(subs)
    return {"subsets.json": subs, "gen_plan.json": ck.gen_plan(rows, subs),
            **{f"judge_ids_{a}.json": ids[a] for a in ck.ARMS},
            "judge_order.json": ck.judge_order(ids)}


def _freeze(checks: Path, docs: dict[str, Any]) -> None:
    record_path = checks / "freeze.json"
    if record_path.exists():
        for name, doc in docs.items():
            if (checks / name).read_text(encoding="utf-8") != ck.dumps(doc):
                raise AnalyzeError(f"frozen {name} would change: retrieval.jsonl differs from "
                                   "the one checked before")
        bad = ck.verify_freeze(checks, _json(record_path))
        if bad:
            raise AnalyzeError(f"frozen files changed: {bad}")
        return
    for name, doc in docs.items():
        _write(checks / name, doc)
    _write(record_path, ck.freeze_record(checks))


def cmd_check(out: Path, partial: bool) -> int:
    metas, rows = ck.load_retrieval(out / "retrieval.jsonl")
    exp_meta = _json(out / "exp_meta.json")
    if exp_meta.get("mode") != "run":
        raise AnalyzeError(f"{out}/exp_meta.json is not a run's (mode {exp_meta.get('mode')})")
    load_ref()
    inv = invariants(metas, rows, exp_meta)
    checks = out / "checks"
    if partial:
        ok = all(v["ok"] for v in inv.values())
        _write(checks / "invariants_partial.json", {"ok": ok, **inv})
        print(f"check --partial ({len(rows)} questions): {_summary(inv)}")
        return 0 if ok else 1
    wanted = {q["question_id"] for q in _json(out / "questions.json")}
    inv["complete"] = {"ok": set(rows) == wanted, "missing": sorted(wanted - set(rows)),
                       "unexpected": sorted(set(rows) - wanted)}
    ok = all(v["ok"] for v in inv.values())
    inv["I5"] = ck.check_i5(rows)
    _write(checks / "invariants.json", inv)
    print(f"check ({len(rows)} questions): {_summary(inv)}")
    if not ok:
        return 1
    subs = ck.subsets(rows)
    mech = {q: ck.mechanisms(rows[q]) for q in subs["D_off"]}
    _write(checks / "mechanisms.json", {"by_qid": mech, "only_ii": sorted(
        q for q, m in mech.items() if m["tags"] == ["ii"])})
    _write(checks / "overlap_eval3c.json", ck.overlap(rows, subs, load_ref()))
    _freeze(checks, frozen_docs(rows, subs))
    print("check: " + "  ".join(f"{k}={len(v)}" for k, v in subs.items()))
    return 0


# ---------------------------------------------------------------- export, order, report

def _require_checked(out: Path) -> None:
    record = out / "checks" / "freeze.json"
    if record.exists():
        bad = ck.verify_freeze(out / "checks", _json(record))
        if bad:
            raise AnalyzeError(f"frozen files changed: {bad}")
        return
    smoke = out / "smoke_check.json"
    if not (smoke.exists() and _json(smoke).get("ok")):
        raise AnalyzeError(f"{out}: run `check` (or `smoke`) first")


def cmd_export_retr(out: Path) -> int:
    _require_checked(out)
    metas, rows = ck.load_retrieval(out / "retrieval.jsonl")
    written = bex.export_retr(metas, rows, out / "retr")
    print(f"export-retr: {len(rows)} questions → {sorted(written)}")
    return 0


def cmd_export_ans(out: Path) -> int:
    _require_checked(out)
    plan_path = out / "checks" / "gen_plan.json"
    plan = _json(plan_path if plan_path.exists() else out / "gen_plan.json")["items"]
    metas, rows = ck.load_retrieval(out / "retrieval.jsonl")
    gens = bio.read_jsonl(out / "gen.jsonl")
    latest = bio.latest_gens(gens)
    mismatched = [k for k, g in latest.items() if g.get("messages_match") is False]
    if mismatched:
        raise AnalyzeError(f"I7: messages sent differ from the context for {mismatched[:5]}")
    written = bex.export_ans(metas, rows, gens, plan, out / "ans")
    failed = sorted(k for k, g in latest.items() if not g.get("ok"))
    print(f"export-ans: {len(plan)} answers → {len(written)} directories; "
          f"failed generations kept as they are: {failed or '-'}")
    return 0


def cmd_judge_order(out: Path, kind: str) -> int:
    print("\n".join(_json(out / "checks" / "judge_order.json")[kind]))
    return 0


def cmd_report(out: Path) -> int:
    import _ba_report as rep

    load_ref()            # eval3c raw / run_meta / faith_cov (G1's strict) unchanged since make-ref
    doc = rep.build(out, eval3c_faith=PATHS["faith"], refusal=PATHS["refusal"],
                    refusal_sha=ck.REFUSAL_SHA_PREFIX)
    _write(out / "report" / "report.json", doc)
    (out / "report" / "report.md").write_text(rep.render_md(doc), encoding="utf-8")
    act = doc["prod_action"]
    print(f"report: {act['action']} (rule {act['rule']}); verdicts "
          + ", ".join(f"{k}={v['verdict']}" for k, v in doc["verdicts"].items()))
    return 0


def cmd_trim(path: Path) -> int:
    print(f"trim: {bio.truncate_to_last_newline(path)} bytes cut from {path}")
    return 0


def cmd_make_ref(ba39: Path | None) -> int:
    from ragcommon import routing

    lexicon = routing.parse_lexicon(_json(PATHS["lexicon"]))
    ref = ck.build_eval3c_ref(_json(PATHS["raw"]), lexicon.match_books,
                              _json(ba39) if ba39 else None)
    ref["meta"] = {"built_by": "ba_analyze.py make-ref (_ba_checks.build_eval3c_ref)",
                   "rule": "c43: strategies_used has book_anchor; ba39: a source with "
                           "strategy book_anchor; pinned: pin_count(scores) > 0; single: "
                           "routing lexicon match_books(question) names ≤ 1 book",
                   **{f"{k}_sha256": bio.sha256_file(PATHS[k])
                      for k in ("raw", "run_meta", "faith", "lexicon")},
                   "ba39_sha256": bio.sha256_file(ba39) if ba39 else None,
                   "sources": {k: str(PATHS[k]) for k in ("raw", "run_meta", "faith", "lexicon")}}
    _write(REF, ref)
    print(f"make-ref: c43={len(ref['c43'])} ba39={len(ref['ba39'])} "
          f"pinned={len(ref['pinned20'])} single={len(ref['pinned_single19'])} → {REF}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("smoke", "check", "export-retr", "export-ans", "report", "judge-order"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        if name == "check":
            p.add_argument("--partial", action="store_true")
        if name == "judge-order":
            p.add_argument("--kind", choices=("strict", "coverage"), required=True)
    sub.add_parser("trim").add_argument("file", type=Path)
    sub.add_parser("make-ref").add_argument("--ba39", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    commands = {"smoke": lambda: cmd_smoke(args.out),
                "check": lambda: cmd_check(args.out, args.partial),
                "export-retr": lambda: cmd_export_retr(args.out),
                "export-ans": lambda: cmd_export_ans(args.out),
                "judge-order": lambda: cmd_judge_order(args.out, getattr(args, "kind", "")),
                "report": lambda: cmd_report(args.out), "trim": lambda: cmd_trim(args.file),
                "make-ref": lambda: cmd_make_ref(args.ba39)}
    try:
        return commands[args.cmd]()
    except (AnalyzeError, ck.CheckError, bex.ExportError, bio.BaIoError, OSError,
            KeyError) as exc:
        print(f"ba_analyze {args.cmd}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — _ba_report.ReportError and friends
        if type(exc).__name__ == "ReportError":
            print(f"ba_analyze {args.cmd}: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
