"""The smoke of the GEN confirmation set's Ollama runs (prereg §4.4, §4.5, §9): run_g's ``smoke`` command.

    python -B run_g.py smoke                       # §4.4: the 2 longest rep-1 prompts per arm, token counts only
    python -B run_g.py smoke --redo A              # set a void or truncated smoke aside after a logged fix, smoke again
    python -B run_g.py smoke --void-truncated A    # a truncated smoke with no infrastructure cause found: 作廢

Moved out of run_g, which keeps the command line, the gates, ``execute``, the run checks and the store paths; this
module reads them from run_g when it runs (so a test's run root holds here too). Per arm the SMOKE_PER_ARM rep-1
jobs with the longest user prompt (ties: job order), in job order; only token counts are kept, never an answer. A
truncation keeps the formal run from starting (§4.4: an infrastructure problem), and so does anything but every
call answered in a session whose checks agree.
``smoke --redo A`` sets the smoke aside (run/smoke_set_aside/<k>, its record in run/smoke_history.json with kind
"void" or "truncated") and smokes again: a void smoke (digest or Ollama version), or a truncated one only when the
Ollama options it recorded are §4.3's (g_common.OLLAMA_OPTIONS: temperature 0.1, num_predict 10000, num_ctx 131072),
the ones the redo uses (options never change). ``smoke --void-truncated A`` writes void_g's one void record (why
truncation: 「作廢（截斷），不構成任何方向的證據」) when the smoke of the store build truncated and no infrastructure cause
was found: it ran with §4.3's options, every call was answered and its checks agree (state ok; a void smoke, other
options or an unfinished session are an infrastructure cause or no finished smoke: fixed and redone, or resumed,
never voided); it calls no Ollama and needs no gate. Either anchor A is one whole line of prereg.md's 執行紀錄 (f1_g's
rule), used by no redo, and newer than the log at K0 and at every redo (each record keeps the log's line sha256).
Once the line is void, smoke refuses (run, score and dry-run too, run_g) and analyze writes only the void sentence.
Prints counts, ids and sha only. Nothing here calls an LLM.
"""
from __future__ import annotations

from pathlib import Path

import arms_g as A
import f1_g as F1
import g_common as GC
import run_g as R
import score_g as SG
import void_g as V

cc = A.cc
VOID, TRUNCATED = "void", "truncated"


def smoke_jobs(jobs: list[dict]) -> list[dict]:
    """§4.4: per arm the 2 rep-1 jobs with the longest user prompt (ties: job order), in job order."""
    keep = set()
    for arm in A.ARMS:
        js = [j for j in jobs if j["arm"] == arm and j["rep"] == 1]
        keep |= {j["job_id"] for j in sorted(js, key=lambda j: -len(j["user"]))[:GC.SMOKE_PER_ARM]}
    return [j for j in jobs if j["job_id"] in keep]


def truncated_ids(d: Path) -> list[str]:
    """The smoke's answered calls that truncated (score_g's rule at the run's num_ctx)."""
    return sorted(i for i, r in cc.done_jobs(d / R.GEN).items() if SG.truncated(r, R.OPTIONS["num_ctx"]))


def smoke_status(d: Path, jobs: list[dict], meta: dict) -> dict:
    """Token counts only (never an answer), from the records and the run's checks; a truncation keeps the formal
    run from starting, and so does anything but every call answered in a run whose checks agree."""
    recs, nc = cc.done_jobs(d / R.GEN), R.OPTIONS["num_ctx"]
    state, why = R.run_state(meta)
    tok = {j["job_id"]: {k: recs[j["job_id"]].get(k) for k in ("prompt_eval_count", "eval_count", "done_reason")}
           for j in jobs if j["job_id"] in recs}
    trunc = sorted(i for i in tok if SG.truncated(recs[i], nc))
    used = [(t["prompt_eval_count"] or 0) + (t["eval_count"] or 0) for t in tok.values()]
    missing = [j["job_id"] for j in jobs if j["job_id"] not in recs]
    return {"kind": "smoke", "n_jobs": len(jobs), "jobs_sha256": A.prompts_sha256(jobs), "num_ctx": nc,
            "missing": missing, "truncated": trunc, "state": state, "void_why": why,
            "max_prompt_plus_eval": max(used, default=None), "tokens": tok, "infra_problem": bool(trunc),
            "pass": not trunc and not missing and state == "ok"}


def smoke_problems(jobs: list[dict]) -> list[str]:
    d = R.store("smoke")
    if not (d / R.RUN_META).is_file():
        return ["no smoke yet (§4.4)"]
    meta, sj = R.run_meta(d), smoke_jobs(jobs)
    st = smoke_status(d, sj, meta)
    if st["truncated"]:
        return [f"the smoke truncated {len(st['truncated'])} calls: an infrastructure problem, no formal run (§4.4); "
                "after a logged fix smoke --redo ANCHOR, with no cause found smoke --void-truncated ANCHOR"]
    if st["state"] == "void":
        return [f"the smoke is void ({st['void_why']}): after a logged fix, smoke --redo ANCHOR"]
    if not st["pass"]:
        return [f"smoke not passed (missing {len(st['missing'])}, state {st['state']}): resume smoke"]
    return [] if meta["jobs_sha256"] == A.prompts_sha256(sj) else ["the smoke ran other jobs"]


def smoke_version() -> str:
    return R.run_meta(R.store("smoke"))["checks"][0]["version"]


# ---------------------------------------------------------------- the anchors of a redo and of the truncation void
def history() -> list[dict]:
    p = R.store(GC.SMOKE_HISTORY)
    return GC.read_json(p)["redo"] if p.is_file() else []


def anchor_basis() -> tuple[list[str], list[str]] | None:
    """(the anchors earlier redos used, the log's line sha256 at K0 and at every redo); None without a K0 record."""
    rec_p = Path(F1.HARNESS_RECORD)
    if not rec_p.is_file():
        return None
    hist = history()
    seen = set(GC.read_json(rec_p)["k0"]["log_lines_sha256"])
    for h in hist:
        seen |= set(h.get("log_lines_sha256") or ())
    return [h["anchor"] for h in hist], sorted(seen)


def anchor_problems(anchor: str, prereg: Path | None = None) -> list[str]:
    basis = anchor_basis()
    if basis is None:
        return ["no K0 harness record"]
    used, seen = basis
    return F1.anchor_problems(anchor, prereg or F1.PREREG, used=used, seen=seen)


def options_problems(meta: dict) -> list[str]:
    """A truncated smoke is redone only when it ran with §4.3's options, the ones the redo uses."""
    out = [] if R.OPTIONS == GC.OLLAMA_OPTIONS else ["the run's Ollama options are not §4.3's"]
    return out + ([] if meta.get("options") == R.OPTIONS else
                  ["the smoke's recorded Ollama options are not the ones a redo would use"])


def smoke_redo(anchor: str, *, prereg: Path | None = None, log=print) -> dict:
    """smoke --redo A: set a void smoke or a truncated one (§4.3's options) aside under a new anchor line."""
    d = R.store("smoke")
    meta = R.run_meta(d) if (d / R.RUN_META).is_file() else None
    trunc = truncated_ids(d) if meta else []
    state, why = R.run_state(meta) if meta else (None, [])
    if meta is None or not (trunc or state == "void"):
        raise SystemExit("smoke --redo: only a void smoke or a truncated one is set aside (resume any other smoke "
                         "without --redo)")
    bad = (options_problems(meta) if trunc else []) + anchor_problems(anchor, prereg)
    if bad:
        raise SystemExit(f"smoke --redo refused: {bad}")
    hist = history()
    name = f"{GC.SMOKE_SET_ASIDE}/{len(hist) + 1}"
    dst = R.cli_out(R.store(name))
    dst.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": R.now(), "anchor": anchor.strip(), "kind": TRUNCATED if trunc else VOID, "moved_to": name,
           "state": state, "void": why, "truncated": len(trunc), "options": meta.get("options"),
           "run_meta_sha256": GC.sha256_file(d / R.RUN_META),
           "log_lines_sha256": F1.lines_sha256(F1.log_lines(prereg or F1.PREREG))}
    R.cli_out(d).rename(dst)
    GC.write_json(R.cli_out(R.store(GC.SMOKE_HISTORY)),
                  {"schema": "gen_confirm.smoke_history.v1", "redo": hist + [rec]})
    log({"smoke set aside": name, "kind": rec["kind"]})
    return rec


def cause_problems(d: Path, sj: list[dict], meta: dict) -> list[str]:
    """Why a truncated smoke is not voided: an infrastructure cause (a void session, other Ollama options than §4.3's)
    or an unfinished smoke (a call unanswered, no agreeing after-check)."""
    st = smoke_status(d, sj, meta)
    out = options_problems(meta) + ([f"the smoke is void ({st['void_why']})"] if st["state"] == "void" else [])
    if st["state"] in ("unfinished", "unknown") or st["missing"]:
        out.append(f"the smoke is not finished (state {st['state']}, missing {len(st['missing'])}): resume smoke")
    return out


def void_truncated(anchor: str, *, jobs: list[dict] | None = None, prereg: Path | None = None, log=print) -> dict:
    """smoke --void-truncated A: the smoke of the store build truncated, no infrastructure cause was found: the one
    void record (void_g, why truncation), under a new anchor line."""
    d = R.store("smoke")
    if not (d / R.RUN_META).is_file():
        raise SystemExit("smoke --void-truncated: there is no smoke")
    meta, trunc = R.run_meta(d), truncated_ids(d)
    if not trunc:
        raise SystemExit("smoke --void-truncated: the smoke did not truncate")
    sj = smoke_jobs(R.load_inputs()[GC.RUN_JOBS] if jobs is None else jobs)
    if meta["jobs_sha256"] != A.prompts_sha256(sj):
        raise SystemExit("smoke --void-truncated: the smoke ran other jobs than the store build's smoke jobs")
    if bad := cause_problems(d, sj, meta):
        raise SystemExit(f"smoke --void-truncated refused: {bad} (fix an infrastructure cause, then smoke --redo ANCHOR)")
    basis = anchor_basis()
    if basis is None:
        raise SystemExit("smoke --void-truncated refused: no K0 harness record")
    used, seen = basis
    rec = V.write("truncation", anchor, path=R.void_file(), prereg=prereg or F1.PREREG, seen=seen, used=used,
                  detail={"smoke_run_meta_sha256": GC.sha256_file(d / R.RUN_META), "jobs_sha256": meta["jobs_sha256"],
                          "truncated": len(trunc), "n_jobs": len(sj)})
    log({"void": rec["why"], "truncated": len(trunc)})
    return rec


def smoke(args=None, *, get=None, log=print) -> dict:
    if bad := V.problems(R.void_file()):
        raise SystemExit(f"smoke refused: {bad}")
    if anchor := getattr(args, "void_truncated", None):
        return void_truncated(anchor, log=log)
    if bad := R.gate_problems():
        raise SystemExit(f"smoke refused: {bad}")
    if redo := getattr(args, "redo", None):
        smoke_redo(redo, log=log)
    d, jobs = R.store("smoke"), smoke_jobs(R.load_inputs()[GC.RUN_JOBS])
    meta = R.execute(d, jobs, "smoke", get=get, log=log)
    st = smoke_status(d, jobs, meta)
    GC.write_json(R.cli_out(d / R.SMOKE_FILE), st)
    log({k: st[k] for k in ("n_jobs", "missing", "truncated", "state", "max_prompt_plus_eval", "pass")})
    return st
