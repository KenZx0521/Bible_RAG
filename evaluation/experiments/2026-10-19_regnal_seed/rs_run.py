"""Runner of the rule-seed regression (prereg.md §4, §6): model check, resume guard, one call per job.

A fork of cards_common.run_jobs with the chat injected (``cards_common.chat`` for the formal run, the
fake for dry runs and tests) and no retry rounds: an Ollama exception or an unreadable response (HTTP,
connection or JSON error) is an error line, final (R3 counts it; it is never run again), and
MAX_CONSECUTIVE_ERRORS in a row stop the run. Resuming skips every job with an answer or an error line.
An output directory serves one job list and one kind of run only: run_meta.json's jobs_sha256, options,
model, pins and dry_run must match (a dry run's directory never takes a formal run, nor the reverse; a
gen.jsonl without run_meta is refused).

Before any call the model's digest (/api/ps, else /api/tags) must be EXPECTED_DIGEST, and it is checked
again after the run; every check is kept in run_meta (``digest_state``: ok, mismatch, unknown when Ollama
did not answer the after-check, unfinished when the run stopped before it). A formal run is started once:
a new directory is refused while another formal run of the same jobs or the same layer exists under the
runs root (and the new directory's parent), but for the one rerun allowed of a run whose digest did not
match after it started (``--rerun-of``). An unfinished or unknown run is resumed in its own directory.
"""
from __future__ import annotations

import http.client
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
# Ollama unreachable or failing (URLError, OSError), a broken HTTP exchange (IncompleteRead,
# BadStatusLine: not OSErrors), an unreadable body (ValueError: JSON)
CALL_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException, ValueError)


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


def digest_state(meta: dict) -> str:
    """"fake": a formal run holding a fake check; "mismatch": a check found another digest (the run is
    void, a rerun may follow); "unfinished": no after-check since the last start (stopped, resume it);
    "unknown": the last after-check got no answer (resume it to check again); else "ok"."""
    checks = meta.get("digest_checks") or []
    if not meta.get("dry_run") and any(c.get("fake") for c in checks):
        return "fake"
    if any(c["digest"] is not None and c["digest"] != EXPECTED_DIGEST for c in checks):
        return "mismatch"
    if not checks or checks[-1]["when"] != "after":
        return "unfinished"
    return "unknown" if checks[-1]["digest"] is None else "ok"


def digest_ok(meta: dict) -> bool:
    return digest_state(meta) == "ok"


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
def _rerun_of(out: Path, sha: str, rerun_of) -> tuple[Path, dict]:
    """The run that --rerun-of names, when it may be redone: a formal first attempt, not redone yet,
    the same jobs, and a digest that did not match after it started."""
    old_dir = Path(rerun_of).resolve()
    old_p = old_dir / RUN_META
    if not old_p.is_file() or old_dir == out:
        raise SystemExit(f"--rerun-of {old_dir}: no earlier run there")
    old = C.read_json(old_p)
    if old.get("dry_run"):
        raise SystemExit(f"{old_dir}: a dry run is never redone as a formal run")
    if old.get("attempt", 1) != 1 or old.get("rerun_by") not in (None, str(out)):
        raise SystemExit(f"{old_dir}: a run is redone at most once")
    state = digest_state(old)
    if state != "mismatch":
        raise SystemExit(f"{old_dir}: its digest checks show no mismatch (state {state}); a rerun is only for a "
                         "digest mismatch after the run started (an unfinished or unknown run is resumed in place)")
    if old["jobs_sha256"] != sha:
        raise SystemExit(f"{old_dir}: a rerun must run the same jobs (jobs_sha256 differs)")
    return old_dir, old


def runs_dirs(roots) -> list[tuple[Path, dict]]:
    """Every run directory (run_meta.json) under the roots, at any depth."""
    seen, out = set(), []
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            continue
        for p in sorted(root.rglob(RUN_META)):
            d = p.parent.resolve()
            if d not in seen:
                seen.add(d)
                out.append((d, C.read_json(p)))
    return out


def other_formal_runs(roots, out: Path, sha: str, pins: dict | None) -> list[Path]:
    """Formal runs other than out of the same jobs, or on the same layer."""
    layer = (pins or {}).get("layer_sha256")
    return [d for d, m in runs_dirs(roots) if d != out and not m.get("dry_run")
            and (m.get("jobs_sha256") == sha or (layer and (m.get("pins") or {}).get("layer_sha256") == layer))]


def guard(out: Path, sha: str, opts: dict, rerun_of=None, dry_run: bool = False, pins: dict | None = None,
          roots=()) -> tuple[dict, tuple[Path, dict] | None]:
    """(the run_meta to continue (resume) or start, the rerun mark to write on the redone run's run_meta
    once the new run may start, or None); refuses another job list, options, model, pins or kind of run,
    a void run, and a second formal run of the same jobs or layer."""
    meta_p = out / RUN_META
    if meta_p.exists():
        old = C.read_json(meta_p)
        if bool(old.get("dry_run")) != dry_run:
            kind = "a dry run's" if old.get("dry_run") else "a formal run's"
            raise SystemExit(f"{out} is {kind} directory: a dry run and a formal run never share one")
        if old["jobs_sha256"] != sha or old["options"] != opts or old["model"] != MODEL:
            raise SystemExit(f"{meta_p}: jobs, options or model differ from the run in this directory")
        if pins is not None and old.get("pins") is not None and old["pins"] != pins:
            raise SystemExit(f"{meta_p}: the pins (layer, lexicon, backend, harness) differ from the run here")
        if rerun_of is not None and old.get("rerun_of") != str(Path(rerun_of).resolve()):
            raise SystemExit(f"{meta_p}: this directory is not a rerun of {rerun_of}")
        if digest_state(old) in ("mismatch", "fake"):
            raise SystemExit(f"{meta_p}: a digest check failed, the run is void and not resumed "
                             "(a rerun goes to a new directory with --rerun-of)")
        keep = {k: v for k, v in old.items() if k not in ("finished", "n_done", "n_errors")}
        return {**keep, "resumed": old.get("resumed", []) + [now()]}, None
    if (out / GEN).exists():
        raise SystemExit(f"{out / GEN} exists without {RUN_META}")
    named = _rerun_of(out, sha, rerun_of) if rerun_of is not None else None
    if not dry_run:
        others = [d for d in other_formal_runs(roots, out, sha, pins) if named is None or d != named[0]]
        if others:
            raise SystemExit(f"a formal run of these jobs or this layer exists in {[str(d) for d in others]}: "
                             "resume it there (the same --out); a new directory only with --rerun-of after a "
                             "digest mismatch")
    meta = {"jobs_sha256": sha, "options": dict(opts), "model": MODEL, "expected_digest": EXPECTED_DIGEST,
            "attempt": 1, "dry_run": dry_run, "pins": pins, "harness": C.harness_pins(), "started": now(),
            "digest_checks": [], "resumed": []}
    if named is None:
        return meta, None
    old_dir, old = named
    return {**meta, "attempt": 2, "rerun_of": str(old_dir)}, (old_dir / RUN_META, {**old, "rerun_by": str(out)})


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
            log=print, pins: dict | None = None, runs_root=None, write: dict | None = None) -> dict:
    """``chat(system, user, options)`` and ``get(path)`` are given explicitly: cards_common.chat and api_get
    for the formal run only, the fakes everywhere else. Other formal runs are looked for under runs_root
    (default OUT_ROOT) and out's parent. ``write`` ({name: json}) is written into out once the guard and
    the digest check have passed, before the first call."""
    out = C.writable(out)
    sha = jobs_sha256(jobs)
    roots = (runs_root if runs_root is not None else C.OUT_ROOT, out.parent)
    meta, mark = guard(out, sha, opts, rerun_of, dry_run, pins, roots)
    before = _check(get, "before", dry_run)
    if before["digest"] != EXPECTED_DIGEST:
        raise SystemExit(f"model digest {before['digest']} ({before['where']}) is not {EXPECTED_DIGEST}: refused")
    if mark is not None:
        C.write_json(*mark)
    meta = {**meta, "digest_checks": meta["digest_checks"] + [before], "n_jobs": len(jobs)}
    for name, obj in (write or {}).items():
        C.write_json(out / name, obj)
    C.write_json(out / RUN_META, meta)
    run_jobs(jobs, out / GEN, chat, opts, log)
    after = _check(get, "after", dry_run)
    checks = meta["digest_checks"] + [after]
    meta = {**meta, "digest_checks": checks, "digest_before": checks[0]["digest"], "digest_after": after["digest"],
            "n_done": len(done_ids(out / GEN)), "n_errors": len(error_lines(out / GEN)), "finished": now()}
    C.write_json(out / RUN_META, meta)
    log(f"done {meta['n_done']} of {len(jobs)}, errors {meta['n_errors']}, digest {digest_state(meta)}")
    return meta


def pins_of(doc: dict) -> dict:
    """What a run is pinned to: the cards' layer, lexicon and backend, and the harness's files."""
    h = doc["header"]
    return {"layer_sha256": h["layer_sha256"], "lexicon_sha256": h["lexicon_sha256"],
            "backend_sha256": h["backend_sha256"], "harness_sha256": C.harness_pins()["sha256"]}


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


G_ARMS = ("G-auto", "G-ref")


def seconds_per_g_call(gen_path: Path) -> float:
    """Mean elapsed_s of experiment A's card arms' calls (G-auto, G-ref): the prompts this regression sends."""
    xs = [r["elapsed_s"] for r in C.jsonl(gen_path) if r.get("type") == "answer" and r.get("elapsed_s") is not None
          and r.get("arm") in G_ARMS]
    return sum(xs) / len(xs)


def estimate(jobs: list[dict]) -> dict:
    """Ollama time (an estimate, not a measurement). From experiment A's run_meta_arms.json (wall time /
    calls, every arm: T-canon and B0 are slower), confirm jobs at the confirmation run's rate, dev jobs at
    stage-0's; the lower bound from the card arms' own call times (gen_arms.jsonl elapsed_s, no gaps)."""
    n = {s: sum(j["set"] == s for j in jobs) for s in ("confirm", "dev")}
    gen = {"confirm": C.A_CONFIRM, "dev": C.A_DEV}

    def total(rate):
        sec = sum(n[s] * rate[s] for s in rate)
        return {"seconds_per_call": {s: round(v, 3) for s, v in rate.items()}, "seconds": round(sec),
                "minutes": round(sec / 60, 1)}
    wall = total({s: seconds_per_call(d / "run_meta_arms.json") for s, d in gen.items()})
    low = total({s: seconds_per_g_call(d / "gen_arms.jsonl") for s, d in gen.items()})
    return {**wall, "jobs": n, "source": "A_confirm/run_meta_arms.json, A/run_meta_arms.json",
            "lower_bound": {**low, "source": "A_confirm/gen_arms.jsonl, A/gen_arms.jsonl: G-auto, G-ref elapsed_s"}}


def build(layer_path, lexicon_path) -> tuple[dict, list[dict], dict]:
    import rs_cards as K
    from rs_jobs import build_jobs
    layer, info = C.load_layer(layer_path, lexicon_path)
    doc = K.build_cards(layer, info, K.store_sets())
    items = K.store_items()
    return doc, build_jobs(doc, items), items


def dry_run(layer_path, lexicon_path, out) -> dict:
    """The whole flow with the fake chat: cards -> jobs -> fake generation -> scores -> verdict (result
    "dry_run", never a pass). The directory holds dry runs only, and each dry run replaces the last."""
    import rs_score as S
    from rs_jobs import summary
    out = C.writable(out)
    meta_p = out / RUN_META
    if meta_p.exists() or (out / GEN).exists():
        if not meta_p.exists() or not C.read_json(meta_p).get("dry_run"):
            raise SystemExit(f"{out} holds a formal run: not a dry-run directory")
        for name in (GEN, RUN_META, "scores.json", "verdict.json", "dry_run_report.json"):
            (out / name).unlink(missing_ok=True)
    doc, jobs, items = build(layer_path, lexicon_path)
    meta = execute(jobs, out, fake_chat, fake_get, dry_run=True, log=lambda *_a: None, pins=pins_of(doc),
                   write={"cards.json": doc, "jobs.json": jobs})
    scores, verdict = S.score_run(out, doc, jobs, items)
    rep = {"dry_run": True, "note": "假 chat；分數無意義，只驗流程", "layer_sha256": doc["header"]["layer_sha256"],
           "lexicon_sha256": doc["header"]["lexicon_sha256"], **summary(jobs), "estimate": estimate(jobs),
           "run_meta": {k: meta[k] for k in ("n_done", "n_errors", "digest_before", "digest_after")},
           "describe": verdict["describe"],
           "verdict": {k: verdict[k] for k in ("result", "pass", "dry_judgment", "R1", "R2", "R3")}}
    C.write_json(out / "dry_run_report.json", rep)
    return rep
