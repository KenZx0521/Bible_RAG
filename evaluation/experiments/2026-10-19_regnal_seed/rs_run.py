"""Runner of the rule-seed regression (prereg.md §4, §6): model check, resume guard, one call per job.

A fork of cards_common.run_jobs with the chat injected (``cards_common.chat`` for the formal run, the
fake for dry runs and tests) and no retry rounds: an Ollama exception or an unreadable response is an
error line, final (R3 counts it; it is never run again), and MAX_CONSECUTIVE_ERRORS in a row stop the
run. Resuming skips every job with an answer or an error line. An output directory serves one job list
only (run_meta.json jobs_sha256, options and model must match; a gen.jsonl without run_meta is refused).

Before any call the model's digest (/api/ps, else /api/tags) must be EXPECTED_DIGEST, and it is checked
again after the run; every check is kept in run_meta. A rerun (a new directory, the same jobs) is allowed
once, and only of a run whose digest check failed after it started (``--rerun-of``).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import rs_common as C
from rs_common import EXPECTED_DIGEST, MODEL, OPTIONS, cc
from rs_jobs import jobs_sha256

GEN, RUN_META = "gen.jsonl", "run_meta.json"
MAX_CONSECUTIVE_ERRORS = 3
CALL_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- model digest
def api_get(path: str) -> dict:
    with urllib.request.urlopen(cc.OLLAMA + path, timeout=30) as resp:
        return json.loads(resp.read())


def _find(doc: dict) -> str | None:
    hit = [m for m in (doc or {}).get("models", []) if MODEL in (m.get("name"), m.get("model"))]
    return hit[0].get("digest") if hit else None


def model_digest(get=api_get) -> tuple[str | None, str | None]:
    """(digest, "ps" | "tags") of MODEL; (None, None) when Ollama does not answer or lacks the model."""
    try:
        d = _find(get("/api/ps"))
        if d:
            return d, "ps"
        d = _find(get("/api/tags"))
        return (d, "tags") if d else (None, None)
    except CALL_ERRORS:
        return None, None


def digest_ok(meta: dict) -> bool:
    checks = meta.get("digest_checks") or []
    return bool(checks) and all(c["digest"] == EXPECTED_DIGEST for c in checks) and \
        any(c["when"] == "after" for c in checks) and (meta.get("dry_run") or not any(c.get("fake") for c in checks))


def _check(get, when: str, fake: bool = False) -> dict:
    d, where = model_digest(get)
    return {"when": when, "t": now(), "digest": d, "where": where, **({"fake": True} if fake else {})}


# ---------------------------------------------------------------- outputs
def records(path: Path) -> list[dict]:
    return C.jsonl(path)


def done_ids(path: Path) -> set[str]:
    return {r["job_id"] for r in records(path) if r.get("type") == "answer"}


def error_lines(path: Path) -> list[dict]:
    return [r for r in records(path) if r.get("type") == "error"]


def answers(path: Path) -> dict[str, dict]:
    return {r["job_id"]: r for r in records(path) if r.get("type") == "answer"}


def _append(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- guard
def _rerun(out: Path, sha: str, rerun_of) -> dict:
    old_dir = Path(rerun_of).resolve()
    old_p = old_dir / RUN_META
    if not old_p.is_file() or old_dir == out:
        raise SystemExit(f"--rerun-of {old_dir}: no earlier run there")
    old = C.read_json(old_p)
    if old.get("attempt", 1) != 1 or old.get("rerun_by") not in (None, str(out)):
        raise SystemExit(f"{old_dir}: a run is redone at most once")
    after = [c for c in old.get("digest_checks", []) if c["when"] == "after"]
    if not after or digest_ok(old):
        raise SystemExit(f"{old_dir}: its digest checks passed (or it never finished); a rerun is only for a digest "
                         "mismatch after the run started")
    if old["jobs_sha256"] != sha:
        raise SystemExit(f"{old_dir}: a rerun must run the same jobs (jobs_sha256 differs)")
    C.write_json(old_p, {**old, "rerun_by": str(out)})
    return {"attempt": 2, "rerun_of": str(old_dir)}


def guard(out: Path, sha: str, opts: dict, rerun_of=None, dry_run: bool = False) -> dict:
    """The run_meta to continue (resume) or start; refuses another job list, options or model."""
    meta_p = out / RUN_META
    if meta_p.exists():
        old = C.read_json(meta_p)
        if old["jobs_sha256"] != sha or old["options"] != opts or old["model"] != MODEL:
            raise SystemExit(f"{meta_p}: jobs, options or model differ from the run in this directory")
        if rerun_of is not None and old.get("rerun_of") != str(Path(rerun_of).resolve()):
            raise SystemExit(f"{meta_p}: this directory is not a rerun of {rerun_of}")
        if any(c["digest"] != EXPECTED_DIGEST for c in old.get("digest_checks", [])):
            raise SystemExit(f"{meta_p}: a digest check failed, the run is void and not resumed "
                             "(a rerun goes to a new directory with --rerun-of)")
        keep = {k: v for k, v in old.items() if k not in ("finished", "n_done", "n_errors")}
        return {**keep, "resumed": old.get("resumed", []) + [now()]}
    if (out / GEN).exists():
        raise SystemExit(f"{out / GEN} exists without {RUN_META}")
    meta = {"jobs_sha256": sha, "options": dict(opts), "model": MODEL, "expected_digest": EXPECTED_DIGEST,
            "attempt": 1, "dry_run": dry_run, "started": now(), "digest_checks": [], "resumed": []}
    if rerun_of is not None:
        meta.update(_rerun(out, sha, rerun_of))
    return meta


# ---------------------------------------------------------------- calls
def run_jobs(jobs: list[dict], path: Path, chat, opts: dict, log=print) -> None:
    """Every job without an answer or error line, once, in order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {r["job_id"] for r in records(path)}
    todo = [j for j in jobs if j["job_id"] not in seen]
    log(f"{len(seen)} done or failed, {len(todo)} to do")
    streak = 0
    for job in todo:
        try:
            res = chat(job["system"], job["user"], opts)
        except CALL_ERRORS as e:
            _append(path, {"type": "error", "job_id": job["job_id"], "t": now(), "error": repr(e)[:300]})
            streak += 1
            if streak >= MAX_CONSECUTIVE_ERRORS:
                raise SystemExit(f"{streak} consecutive errors: stopped (errors are final, R3 counts them)") from e
            continue
        streak = 0
        _append(path, {"type": "answer", "job_id": job["job_id"], "exp": job.get("exp"), "set": job.get("set"),
                       "item": job.get("item"), "arm": job.get("arm"), "rep": job.get("rep"),
                       "kind": job.get("kind", "gen"), "user_chars": len(job["user"]), **res})


def execute(jobs: list[dict], out, chat, get, opts: dict = OPTIONS, rerun_of=None, dry_run: bool = False,
            log=print) -> dict:
    """``chat(system, user, options)`` and ``get(path)`` are given explicitly: cards_common.chat and api_get
    for the formal run only, the fakes everywhere else."""
    out = C.writable(out)
    sha = jobs_sha256(jobs)
    meta = guard(out, sha, opts, rerun_of, dry_run)
    before = _check(get, "before", dry_run)
    if before["digest"] != EXPECTED_DIGEST:
        raise SystemExit(f"model digest {before['digest']} ({before['where']}) is not {EXPECTED_DIGEST}: refused")
    meta = {**meta, "digest_checks": meta["digest_checks"] + [before], "n_jobs": len(jobs)}
    C.write_json(out / RUN_META, meta)
    run_jobs(jobs, out / GEN, chat, opts, log)
    after = _check(get, "after", dry_run)
    checks = meta["digest_checks"] + [after]
    meta = {**meta, "digest_checks": checks, "digest_before": checks[0]["digest"], "digest_after": after["digest"],
            "n_done": len(done_ids(out / GEN)), "n_errors": len(error_lines(out / GEN)), "finished": now()}
    C.write_json(out / RUN_META, meta)
    log(f"done {meta['n_done']} of {len(jobs)}, errors {meta['n_errors']}, digest ok {digest_ok(meta)}")
    return meta


# ---------------------------------------------------------------- fake chat (dry runs, tests)
def fake_chat(system: str, user: str, options: dict) -> dict:
    """Answers the card's first derivation line, or 「無法判斷」 without a card. Its numbers mean nothing."""
    from_card = None
    if cc.AUX_LABEL in user:
        lines = user.split(cc.AUX_LABEL, 1)[1].splitlines()
        hdr = C.backend().engine.DERIVED_HEADER
        if hdr in lines:
            nxt = lines[lines.index(hdr) + 1]
            from_card = nxt.split("：", 1)[1] if "：" in nxt else nxt
    content = f"（假生成）\n答案：{from_card or '無法判斷'}"
    return {"content": content, "thinking_chars": 0, "prompt_eval_count": len(user) // 2, "eval_count": 50,
            "done_reason": "stop", "elapsed_s": 0.0}


def fake_get(path: str) -> dict:
    return {"models": [{"name": MODEL, "model": MODEL, "digest": EXPECTED_DIGEST}]}


def real_chat(system: str, user: str, options: dict) -> dict:
    return cc.chat(system, user, options)


# ---------------------------------------------------------------- estimate and dry run
def seconds_per_call(meta_path: Path) -> float:
    m = C.read_json(meta_path)
    t0, t1 = (time.mktime(time.strptime(m[k], "%Y-%m-%dT%H:%M:%S")) for k in ("started", "finished"))
    return (t1 - t0) / m["n_jobs"]


def estimate(jobs: list[dict]) -> dict:
    """Ollama time from experiment A's run_meta_arms.json (wall time / calls): confirm jobs at the
    confirmation run's rate, dev jobs at stage-0's (an estimate, not a measurement)."""
    rate = {"confirm": seconds_per_call(C.A_CONFIRM / "run_meta_arms.json"),
            "dev": seconds_per_call(C.A_DEV / "run_meta_arms.json")}
    n = {s: sum(j["set"] == s for j in jobs) for s in rate}
    sec = sum(n[s] * rate[s] for s in rate)
    return {"seconds_per_call": {s: round(v, 3) for s, v in rate.items()}, "jobs": n, "seconds": round(sec),
            "minutes": round(sec / 60, 1), "source": "A_confirm/run_meta_arms.json, A/run_meta_arms.json"}


def build(layer_path, lexicon_path) -> tuple[dict, list[dict], dict]:
    import rs_cards as K
    from rs_jobs import build_jobs
    layer, info = C.load_layer(layer_path, lexicon_path)
    doc = K.build_cards(layer, info, K.store_sets())
    items = K.store_items()
    return doc, build_jobs(doc, items), items


def dry_run(layer_path, lexicon_path, out) -> dict:
    """The whole flow with the fake chat: cards -> jobs -> fake generation -> scores -> verdict."""
    import rs_score as S
    from rs_jobs import summary
    out = C.writable(out)
    meta_p = out / RUN_META
    if meta_p.exists():
        if not C.read_json(meta_p).get("dry_run"):
            raise SystemExit(f"{out} holds a real run: not a dry-run directory")
        for name in (GEN, RUN_META, "scores.json", "verdict.json", "dry_run_report.json"):
            (out / name).unlink(missing_ok=True)
    doc, jobs, items = build(layer_path, lexicon_path)
    C.write_json(out / "cards.json", doc)
    C.write_json(out / "jobs.json", jobs)
    meta = execute(jobs, out, fake_chat, fake_get, dry_run=True, log=lambda *_a: None)
    scores, verdict = S.score_run(out, doc, jobs, items)
    rep = {"dry_run": True, "note": "假 chat；分數無意義，只驗流程", "layer_sha256": doc["header"]["layer_sha256"],
           "lexicon_sha256": doc["header"]["lexicon_sha256"], **summary(jobs), "estimate": estimate(jobs),
           "run_meta": {k: meta[k] for k in ("n_done", "n_errors", "digest_before", "digest_after")},
           "describe": verdict["describe"], "verdict": {k: verdict[k] for k in ("result", "pass", "R1", "R2", "R3")}}
    C.write_json(out / "dry_run_report.json", rep)
    return rep
