"""Plan A4 (docs/records/2026-10-21_gen_card_integration_plan.md §3.2) and the post-switch prod check: the GEN
confirmation set's 58 questions through /query under prod retrieval. Host python -B (the evaluation venv).

    python -B a4_g.py a4 --build B [--run a4]                   # staging :8002, four arms × 3 reps (Ollama ≈ 3 h)
    python -B a4_g.py prod-check --build B [--run prod_check]   # prod :8000, ON × 1, card parity
    python -B a4_g.py dry-run --out DIR [--build B]             # a4 with fake /query, Ollama, /health and docker

Arms: ON = /query without use_gen_card (the deployed default path); OFF = /query with use_gen_card false; B0-prod
and T-rows-prod = Ollama /api/chat directly, cards_common.SYSTEM_PROMPT + build_user(ctx_on, question, None | the
card's t_block), cards_common.MODEL and the backend's options (temperature 0.1, num_predict 10000, no num_ctx);
ctx_on = the same ON call's source context blocks joined by a blank line (what the generator joined). T-rows-prod
runs on the fired items only. Order: rep → items by sid → ON, then B0-prod, T-rows-prod and OFF rotated by the item's
index (arms_c.arm_jobs' rule; an arm without a call is skipped after the rotation). A unit is an ON (q, r) and its
direct calls: a void ON is rerun before its direct calls, which then use the new ctx_on; a void direct call reruns on
the same ctx_on (its record names the ON attempt it was paired with). Per-call voids: an HTTP error, an answer with
the generator's error prefix, validity.infra_failed, a call ≥ 120 s, a response without a source or with a source
lacking its context block; a direct call that raised or came back empty. At most 2 reruns per call (after 5 s, 10 s);
past that the run is void. Run-level voids: a source whose build_id is not --build, a gemma digest or Ollama version
other than the pinned ones before or after a session (a mismatch before a session that follows an unclosed one), a
call past its rerun cap, and in a4_score /api/ps readings (after each session's first and last call) that differ in
model or context_length, a direct arm truncated ≥ 2 times. A wiring failure (an ON card that is not run/cards.json's
``g`` card, an OFF card) is deterministic: it stops the run at once. A void run is never resumed; a rerun after a
logged fix goes to a new --run directory, and the report lists the mode's other runs (§3.0: only the first complete
valid run is judged).
Before a session (refused, no call): the inputs (store run/items.json and run/cards.json by full sha256), --build not
the old prod build, /api/v1/health (status ok, build_id --build); for a4 a read-only ``docker inspect`` of the staging
container (running; LLM_TEMPERATURE, LLM_MAX_TOKENS and OLLAMA_MODEL equal to the direct calls' options and model,
RAG_GEN_CARD unset or true; only these four values are kept) and the Ollama digest and version (run_g's ollama_check
rule, written here: /api/ps, else /api/tags). The run's code (this folder, score_g.py, keys_x.py, cards_common.py)
must be the run's at every session. Outputs: the store's reports/gen_card_20261021/<run>/ only (``Writer`` refuses
any other path; a dry run writes DIR, never in the store or the repository): run_meta.json, calls.jsonl (every
attempt, append-only; answers and contexts stay there) and report.json. Resumable per call (a last line cut by a
kill moves to calls.torn.jsonl and its call is redone); a session holds run.lock. Prints ids, numbers and sha256 only.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import a4_score as SC  # noqa: E402
from src.validity import GENERATION_ERROR_PREFIX, infra_failed  # noqa: E402

HERE, REPO, GEN_CONFIRM = SC.HERE, SC.REPO, SC.GEN_CONFIRM
SG, cc = SC.SG, SC.cc
GC = SG.GC
STORE = GC.STORE
OUT_ROOT = STORE / "reports/gen_card_20261021"
INPUT_SHA256 = {GC.RUN_ITEMS: "d52474c2d6d6f40cf2d0311df334adb5c918f2ef294d90cd3a98cc0941734fe5",
                GC.RUN_CARDS: "084a38d6d9e8cc1321b45e07ae8880b92ab2e5d24b19b1190e2be32a72955969"}
OLD_BUILD = "b20261019_a86f2b06"                   # prod before the switch: never "the new build"
DRY_BUILD = "b_dry_run"
STAGING_CONTAINER = "bible_rag_backend_stg"
MODEL = cc.MODEL
OPTIONS = {"temperature": 0.1, "num_predict": 10000}    # backend utils/llm/ollama_client: no num_ctx
ENV_KEYS = ("LLM_TEMPERATURE", "LLM_MAX_TOKENS", "OLLAMA_MODEL", "RAG_GEN_CARD")
TRUE = ("1", "true", "t", "yes", "y", "on")         # pydantic's true strings
QUERY_TIMEOUT_S = 300
SLOW_S = SG.SLOW_S                                  # 120 s: the backend's Ollama client timeout
MAX_RERUNS, BACKOFF_S = 2, 5
RUN_VOIDS = ("build_id",)                           # a per-call check that voids the whole run
RUN_META, CALLS, REPORT, LOCK, TORN = "run_meta.json", "calls.jsonl", "report.json", "run.lock", "calls.torn.jsonl"
GUARDED = ("mode", "dry_run", "url", "build", "arms", "reps", "inputs_sha256", "code_sha256", "options", "model")
CHECK_ERRORS = (OSError, ValueError, http.client.HTTPException, AttributeError)
CALL_ERRORS = (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException)


@dataclass(frozen=True)
class Mode:
    name: str
    url: str
    arms: tuple[str, ...]
    reps: int
    staging: bool                                   # docker env, Ollama digest / version and /api/ps readings
    run: str                                        # default run directory


MODES = {"a4": Mode("a4", "http://localhost:8002", SC.ARMS, 3, True, "a4"),
         "prod-check": Mode("prod-check", "http://localhost:8000", ("ON",), 1, False, "prod_check")}


class RunVoid(Exception):
    """A run-level void: the run stops here and is never resumed."""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------- the writer and the inputs
def _under(p: Path, root: Path) -> bool:
    root = root.resolve()
    return p == root or root in p.parents


class Writer:
    """Writes files directly in its root only: a run directory of OUT_ROOT, or (a dry run) a directory outside the
    store and the repository."""

    def __init__(self, root: Path | str, *, dry: bool = False):
        root = Path(root).resolve()
        if dry and (_under(root, STORE) or any(_under(root, r) for r in GC.repo_roots())):
            raise SystemExit(f"{root}: a dry run writes outside the store and the repository")
        if not dry and root.parent != OUT_ROOT.resolve():
            raise SystemExit(f"{root}: the store is written only in a run directory of {OUT_ROOT}")
        self.root = root

    def path(self, name: str) -> Path:
        p = (self.root / name).resolve()
        if p.parent != self.root:
            raise SystemExit(f"{p}: written only in {self.root}")
        return p

    def write_json(self, name: str, obj) -> Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)
        return p

    def append(self, name: str, rec: dict) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read_json(self, name: str):
        p = self.path(name)
        return GC.read_json(p) if p.is_file() else None

    def jsonl(self, name: str) -> list[dict]:
        """A record per "\\n"-ended line (repair_tail's rule): splitlines() would also split at U+2028, U+2029 or
        U+0085, which json.dumps(ensure_ascii=False) leaves as they are in an answer or a context."""
        p = self.path(name)
        return [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x.strip()] if p.is_file() else []


def load_inputs(root: Path = GC.RUN_ROOT) -> tuple[list[dict], dict]:
    """run/items.json (items by sid) and run/cards.json's cards, each by its full sha256 (run/formal/run_meta.json)."""
    bad = [n for n, want in INPUT_SHA256.items() if not (root / n).is_file() or GC.sha256_file(root / n) != want]
    if bad:
        raise SystemExit(f"{bad}: not the pinned input")
    items = sorted(GC.read_json(root / GC.RUN_ITEMS)["items"], key=lambda it: it["sid"])
    cards = GC.read_json(root / GC.RUN_CARDS)["cards"]
    if [it["sid"] for it in items] != sorted(cards):
        raise SystemExit("run/items.json and run/cards.json name different sids")
    return items, cards


def code_sha256() -> dict:
    files = sorted(HERE.glob("*.py")) + [GEN_CONFIRM / "score_g.py", GC.STAGE0_DIR / "keys_x.py", Path(cc.__file__)]
    return {p.resolve().relative_to(REPO).as_posix(): GC.sha256_file(p) for p in files}


# ---------------------------------------------------------------- services (injected: Io)
def post_query(url: str, body: dict, timeout: float) -> tuple[dict | None, str | None, float]:
    req = urllib.request.Request(url + "/api/v1/query", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), None, round(time.time() - t0, 2)
    except CALL_ERRORS as e:
        return None, repr(e)[:300], round(time.time() - t0, 2)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def docker_inspect(name: str) -> list:
    try:
        r = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


@dataclass
class Io:
    post: Callable[[str, dict, float], tuple]       # /api/v1/query → (data, error, elapsed_s)
    chat: Callable[[str, str, dict], dict]          # cards_common.chat
    ollama: Callable[[str], dict]                   # GET an Ollama path
    health: Callable[[str], dict]                   # GET <backend>/api/v1/health
    inspect: Callable[[str], list]                  # docker inspect (read-only)
    sleep: Callable[[float], None] = time.sleep
    log: Callable[..., None] = print


def real_io() -> Io:
    return Io(post=post_query, chat=cc.chat, ollama=lambda p: get_json(cc.OLLAMA + p),
              health=lambda u: get_json(u + "/api/v1/health"), inspect=docker_inspect)


# ---------------------------------------------------------------- checks before and after a session
def health_problems(io: Io, url: str, build: str) -> list[str]:
    try:
        doc = io.health(url)
    except CHECK_ERRORS:
        return ["/api/v1/health did not answer 200"]
    out = [] if doc.get("status") == "ok" else [f"/api/v1/health status {doc.get('status')}"]
    return out + ([] if doc.get("build_id") == build else [f"/api/v1/health build_id {doc.get('build_id')} is not {build}"])


def env_check(doc: list) -> dict:
    """The staging container's env, read-only: only ENV_KEYS are kept (the env holds secrets)."""
    c = doc[0] if doc else {}
    env = {}
    for e in (c.get("Config") or {}).get("Env") or []:
        k, _, v = e.partition("=")
        env[k.upper()] = v
    got = {k: env.get(k) for k in ENV_KEYS}
    out = [] if (c.get("State") or {}).get("Running") else [f"{STAGING_CONTAINER} is not running"]
    try:
        ok = float(got["LLM_TEMPERATURE"]) == OPTIONS["temperature"] and int(got["LLM_MAX_TOKENS"]) == OPTIONS["num_predict"]
    except (TypeError, ValueError):
        ok = False
    out += [] if ok else ["LLM_TEMPERATURE / LLM_MAX_TOKENS are not the direct calls' options"]
    out += [] if got["OLLAMA_MODEL"] == MODEL else [f"OLLAMA_MODEL is not {MODEL}"]
    gen = got["RAG_GEN_CARD"]
    out += [] if gen is None or gen.strip().lower() in TRUE else ["RAG_GEN_CARD is not unset or true"]
    return {"container": STAGING_CONTAINER, "image": c.get("Image"), "env": got, "problems": out}


def _is_model(m: dict) -> bool:
    return MODEL in (m.get("name"), m.get("model"))


def ollama_check(get, when: str) -> dict:
    """run_g.ollama_check's rule: the model digest (/api/ps, else /api/tags), /api/version, the other loaded models."""
    out = {"when": when, "t": now(), "digest": None, "where": None, "version": None, "others": None}
    try:
        ps = get("/api/ps").get("models", [])
        out["others"] = sorted(m.get("name") or m.get("model") or "?" for m in ps if not _is_model(m))
        hit = [m.get("digest") for m in ps if _is_model(m)] or \
              [m.get("digest") for m in get("/api/tags").get("models", []) if _is_model(m)]
        if hit and hit[0]:
            out["digest"], out["where"] = hit[0], "ps" if any(_is_model(m) for m in ps) else "tags"
    except CHECK_ERRORS:
        pass
    try:
        out["version"] = get("/api/version").get("version")
    except CHECK_ERRORS:
        pass
    return out


def pin_problems(c: dict) -> list[str]:
    out = [] if c["digest"] == GC.EXPECTED_DIGEST else [f"{c['when']}: model digest {c['digest']}"]
    return out + ([] if c["version"] == GC.OLLAMA_VERSION else [f"{c['when']}: Ollama version {c['version']}"])


def ps_reading(get, when: str) -> dict:
    out = {"when": when, "t": now(), "model": None, "digest": None, "context_length": None}
    try:
        for m in get("/api/ps").get("models", []):
            if _is_model(m):
                out.update(model=m.get("name") or m.get("model"), digest=m.get("digest"),
                           context_length=m.get("context_length"))
                break
    except CHECK_ERRORS:
        pass
    return out


# ---------------------------------------------------------------- one call
def ctx_on(sources: list[dict]) -> str:
    return "\n\n".join(s["context"] for s in sources)


def query_void(data, err: str | None, sec: float, build: str) -> str | None:
    if err is not None or not isinstance(data, dict):
        return "http"
    srcs = data.get("sources") or []
    if any(s.get("build_id") != build for s in srcs):
        return "build_id"
    answer = data.get("answer")
    if not isinstance(answer, str) or answer.startswith(GENERATION_ERROR_PREFIX):
        return "generation_error"
    if infra_failed([s.get("strategy") for s in srcs], (data.get("retrieval_stats") or {}).get("strategy_errors") or {}):
        return "infra_failed"
    if sec >= SLOW_S:
        return "slow"
    if not srcs:
        return "no_source"
    return "no_context" if any(not isinstance(s.get("context"), str) for s in srcs) else None


@dataclass
class Ctx:
    mode: Mode
    w: Writer
    cards: dict
    build: str
    io: Io
    calls: list[dict]
    meta: dict
    session: dict                                   # the meta's last session
    n_planned: int
    n_calls: int = 0
    n_valid: int = 0


def query_call(c: Ctx, it: dict, arm: str) -> dict:
    body = {"question": it["question"], "include_context": True, **({"use_gen_card": False} if arm == "OFF" else {})}
    data, err, sec = c.io.post(c.mode.url, body, QUERY_TIMEOUT_S)
    d = data if isinstance(data, dict) else {}
    srcs = d.get("sources") or []
    rec = {"request_flags": {k: v for k, v in body.items() if k != "question"}, "elapsed_s": sec, "error": err,
           "answer": d.get("answer"), "aux_card": d.get("aux_card"), "sources": srcs, "intent": d.get("intent"),
           "retrieval_stats": d.get("retrieval_stats"), "void": query_void(data, err, sec, c.build)}
    if rec["void"] is None and arm == "ON":
        rec["ctx_sha256"] = SC.sha(ctx_on(srcs))
    return rec


def direct_call(c: Ctx, it: dict, arm: str, on: dict) -> dict:
    block = None if arm == "B0-prod" else c.cards[it["sid"]]["g"]["t_block"]
    user = cc.build_user(ctx_on(on["sources"]), it["question"], block)
    rec = {"on_attempt": on["attempt"], "ctx_sha256": on["ctx_sha256"], "user_sha256": SC.sha(user)}
    try:
        res = c.io.chat(cc.SYSTEM_PROMPT, user, dict(OPTIONS))
    except CALL_ERRORS as e:
        return {**rec, "error": repr(e)[:300], "elapsed_s": None, "void": "error"}
    void = "empty" if not res.get("content") else "slow" if (res.get("elapsed_s") or 0) >= SLOW_S else None
    return {**rec, **res, "error": None, "void": void}


def valid(calls: list[dict], sid: str, arm: str, rep: int, on: dict | None = None) -> tuple[dict | None, int]:
    """(the valid record, the attempts so far) of one call; a direct call counts only those paired with ``on``."""
    tries = [x for x in calls if (x["sid"], x["arm"], x["rep"]) == (sid, arm, rep)
             and (arm not in SC.DIRECT or x.get("on_attempt") == on["attempt"])]
    ok = [x for x in tries if x["void"] is None]
    return (ok[-1] if ok else None), len(tries)


def wiring_problem(c: Ctx, rec: dict) -> str | None:
    if rec["arm"] == "ON" and not SC.card_ok(rec.get("aux_card"), c.cards[rec["sid"]]):
        return f"wiring: ON card parity fails on {rec['sid']} r{rec['rep']}"
    if rec["arm"] == "OFF" and rec.get("aux_card") is not None:
        return f"wiring: OFF has a card on {rec['sid']} r{rec['rep']}"
    return None


def record(c: Ctx, rec: dict) -> None:
    c.w.append(CALLS, rec)
    c.calls.append(rec)
    c.n_calls += 1
    c.n_valid += rec["void"] is None
    c.io.log(f"[{len(c.calls)}] {rec['sid']} {rec['arm']} r{rec['rep']} a{rec['attempt']} {rec.get('elapsed_s')}s "
             f"{rec['void'] or 'ok'}")
    if c.mode.staging and c.n_valid == 1 and rec["void"] is None:     # after the session's first valid call
        c.session["ps"].append(ps_reading(c.io.ollama, "first"))
        c.w.write_json(RUN_META, c.meta)


def call(c: Ctx, it: dict, arm: str, rep: int, make: Callable[[], dict], on: dict | None = None) -> dict:
    """One call's attempts until one is valid (≤ 1 + MAX_RERUNS)."""
    rec, n = valid(c.calls, it["sid"], arm, rep, on)
    while rec is None:
        if n > MAX_RERUNS:
            raise RunVoid(f"{it['sid']} {arm} r{rep}: {n} void attempts (at most {MAX_RERUNS} reruns)")
        if n:
            c.io.sleep(BACKOFF_S * n)
        rec = {"type": "call", "sid": it["sid"], "arm": arm, "rep": rep, "attempt": n + 1, "t": now(), **make()}
        record(c, rec)
        if rec["void"] in RUN_VOIDS:
            raise RunVoid(f"{it['sid']} {arm} r{rep}: {rec['void']}")
        rec, n = (rec if rec["void"] is None else None), n + 1
    if bad := wiring_problem(c, rec):
        raise RunVoid(bad)
    return rec


def plan(items: list[dict], cards: dict, mode: Mode) -> list[tuple[int, dict, list[str]]]:
    """(rep, item, arms in call order): ON first, then the rotated rest (an arm without a call skipped after it)."""
    out = []
    for rep in range(1, mode.reps + 1):
        for i, it in enumerate(items):
            rot = SC.ROTATED[i % 3:] + SC.ROTATED[:i % 3]
            rest = [a for a in rot if a in mode.arms and (a != "T-rows-prod" or SC.fired(cards, it["sid"]))]
            out.append((rep, it, ["ON", *rest]))
    return out


def run_units(c: Ctx, units: list) -> None:
    for rep, it, arms in units:
        on = call(c, it, "ON", rep, lambda: query_call(c, it, "ON"))
        for arm in arms[1:]:
            if arm == "OFF":
                call(c, it, arm, rep, lambda: query_call(c, it, "OFF"))
            else:
                call(c, it, arm, rep, lambda: direct_call(c, it, arm, on), on=on)


def finals(calls: list[dict], units: list) -> dict | None:
    """{(sid, arm, rep): valid record} for every planned call, None while one is missing."""
    out = {}
    for rep, it, arms in units:
        on = valid(calls, it["sid"], "ON", rep)[0]
        if on is None:
            return None
        out[it["sid"], "ON", rep] = on
        for arm in arms[1:]:
            rec = valid(calls, it["sid"], arm, rep, on if arm in SC.DIRECT else None)[0]
            if rec is None:
                return None
            out[it["sid"], arm, rep] = rec
    return out


# ---------------------------------------------------------------- a session and the report
def fresh_meta(mode: Mode, build: str, dry: bool) -> dict:
    return {"schema": "gen_card.a4_run.v1", "mode": mode.name, "dry_run": dry, "url": mode.url, "build": build,
            "arms": list(mode.arms), "reps": mode.reps, "inputs_sha256": dict(INPUT_SHA256), "code_sha256": code_sha256(),
            "options": dict(OPTIONS), "model": MODEL, "expected_digest": GC.EXPECTED_DIGEST,
            "ollama_version": GC.OLLAMA_VERSION, "started": now(), "state": "running", "void": [], "sessions": []}


def resume_meta(old: dict | None, new: dict) -> dict:
    if old is None:
        return new
    if old.get("state") == "void":
        raise SystemExit(f"the run is void ({len(old['void'])} reasons): never resumed; a rerun goes to a new --run")
    diff = [k for k in GUARDED if old.get(k) != new[k]]
    if diff:
        raise SystemExit(f"{diff} differ from the run in this directory")
    return old


def repair_tail(w: Writer) -> int:
    """A last line cut by a kill (no final newline) moves to calls.torn.jsonl and is cut off: its call is redone."""
    p = w.path(CALLS)
    raw = p.read_bytes() if p.is_file() else b""
    if not raw or raw.endswith(b"\n"):
        return 0
    head, nl, tail = raw.rpartition(b"\n")
    with w.path(TORN).open("ab") as f:
        f.write(tail + b"\n")
    with p.open("r+b") as f:
        f.truncate(len(head) + len(nl))
    return len(tail)


@contextlib.contextmanager
def run_lock(w: Writer):
    p = w.path(LOCK)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"{p}: another session holds this run") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def void_counts(calls: list[dict]) -> dict:
    """{arm: {reason: attempts}} over every void attempt."""
    n = Counter((x["arm"], x["void"]) for x in calls if x["void"] is not None)
    return {a: {v: k for (b, v), k in sorted(n.items()) if b == a} for a in sorted({a for a, _v in n})}


def other_runs(w: Writer, meta: dict) -> list[dict]:
    """The mode's other run directories beside this one (§3.0: every run is reported, the first valid one judged)."""
    out = []
    for p in sorted(w.root.parent.glob(f"*/{RUN_META}")):
        m = GC.read_json(p)
        if p.parent != w.root and (m.get("mode"), m.get("dry_run")) == (meta["mode"], meta["dry_run"]):
            r = GC.read_json(p.with_name(REPORT)) if p.with_name(REPORT).is_file() else {}
            out.append({"run": p.parent.name, "started": m.get("started"), "state": m.get("state"),
                        "judged": bool(r.get("judged") or r.get("pass"))})
    return sorted(out, key=lambda x: x["started"] or "")


def write_report(mode: Mode, w: Writer, items: list[dict], cards: dict, meta: dict, units: list) -> dict:
    calls = w.jsonl(CALLS)
    fin = finals(calls, units)
    head = {"run": w.root.name, "mode": mode.name, "build": meta["build"], "voids": void_counts(calls),
            "n_planned": sum(len(a) for _r, _i, a in units), "n_attempts": len(calls)}
    if fin is None:
        rep = {"schema": "gen_card.a4_report.v1", "state": meta["state"], "void": meta["void"], "judged": False,
               "complete": False, "n_valid": sum(x["void"] is None for x in calls)}
    elif mode.name == "prod-check":
        rep = SC.prod_check_report(items, cards, fin, meta["void"])
    else:
        readings = [r for s in meta["sessions"] for r in s.get("ps", [])]
        num_ctx = readings[0]["context_length"] if readings else None
        rep = SC.report(items, cards, fin, reps=mode.reps, num_ctx=num_ctx, readings=readings, void=meta["void"])
    others = other_runs(w, meta)
    rep = {**rep, **head, "other_runs": others,
           "first_judged_run": bool(rep.get("judged") or rep.get("pass"))
           and not any(o["judged"] and (o["started"] or "") < meta["started"] for o in others)}
    if fin is not None and rep["state"] == "void" and meta["state"] != "void":
        meta.update(state="void", void=list(rep["void"]))
    elif fin is not None and meta["state"] != "void":
        meta["state"] = "complete"
    w.write_json(RUN_META, meta)
    w.write_json(REPORT, rep)
    return rep


def run(mode: Mode, w: Writer, items: list[dict], cards: dict, build: str, io: Io, *, dry: bool = False) -> dict:
    """One session: guard, checks, the calls still to make, the after-checks, the report."""
    if build == OLD_BUILD:
        raise SystemExit(f"--build {build} is the old prod build, not the new one")
    units = plan(items, cards, mode)
    with run_lock(w):
        meta = resume_meta(w.read_json(RUN_META), fresh_meta(mode, build, dry))
        torn = repair_tail(w)
        closed = not meta["sessions"] or "t_end" in meta["sessions"][-1]
        if closed and finals(w.jsonl(CALLS), units) is not None:
            return write_report(mode, w, items, cards, meta, units)       # nothing to call: report again
        sess, bad = {"t_start": now(), "ps": [], "torn_bytes": torn}, health_problems(io, mode.url, build)
        if mode.staging:
            sess["env"] = env_check(io.inspect(STAGING_CONTAINER))
            sess["before"] = ollama_check(io.ollama, "before")
            pins = pin_problems(sess["before"])
            if pins and not closed:
                meta.update(state="void", void=meta["void"] + [f"{p} (stands in for the unclosed session's after-check)"
                                                               for p in pins])
                write_report(mode, w, items, cards, meta, units)
                raise SystemExit(f"void: {meta['void']}")
            bad += sess["env"]["problems"] + pins
        if bad:
            raise SystemExit(f"refused before any call: {bad}")
        meta["sessions"].append(sess)
        w.write_json(RUN_META, meta)
        c = Ctx(mode, w, cards, build, io, w.jsonl(CALLS), meta, sess, sum(len(a) for _r, _i, a in units))
        io.log({"run": w.root.name, "planned": c.n_planned, "attempts_so_far": len(c.calls)})
        void = []
        try:
            run_units(c, units)
        except RunVoid as e:
            void.append(str(e))
        unknown = False
        if mode.staging:
            if c.n_valid:
                sess["ps"].append(ps_reading(io.ollama, "last"))
            sess["after"] = ollama_check(io.ollama, "after")
            unknown = sess["after"]["digest"] is None or sess["after"]["version"] is None
            void += [] if unknown else pin_problems(sess["after"])
        if not unknown:
            sess.update(t_end=now(), n_calls=c.n_calls)
        if void:
            meta.update(state="void", void=meta["void"] + void)
        elif unknown:                               # the session stays unclosed: the next before-check stands in
            w.write_json(RUN_META, meta)
            raise SystemExit("the after-check got no answer from Ollama: run again (it resumes and checks again)")
        return write_report(mode, w, items, cards, meta, units)


# ---------------------------------------------------------------- dry run (fakes)
class FakeBackend:
    """/query from the item's gold: ON with a card answers the gold, every other call gold + 1 (OFF without an answer
    line, as prod's ordinary prompt); one source, the item's context_from; ON carries run/cards.json's card."""

    def __init__(self, items: list[dict], cards: dict, build: str):
        self.by_q, self.cards, self.build, self.calls = {it["question"]: it for it in items}, cards, build, 0

    def __call__(self, url: str, body: dict, timeout: float):
        self.calls += 1
        it = self.by_q[body["question"]]
        g = self.cards[it["sid"]]["g"] if "use_gen_card" not in body else None
        aux = None if g is None else {"kind": "gen", "text": g["g_block"], "layer_sha256": SC.GEN_LAYER_SHA256,
                                      "seed_source": "rule"}
        answer = f"（假生成）\n答案：{it['gold']}歲" if g else \
            f"（假生成）{it['gold'] + 1}歲" if "use_gen_card" in body else f"（假生成）\n答案：{it['gold'] + 1}歲"
        src = {"id": it["context_from"], "context": "[1] 假 第1章\n假", "build_id": self.build,
               "strategy": "hybrid_hybrid", "passage_id": it["context_from"], "split_passage_ids": []}
        return {"answer": answer, "sources": [src], "aux_card": aux, "intent": {"type": "fake"},
                "retrieval_stats": {"strategy_errors": {}}}, None, 0.0


class FakeChat:
    """A direct call answers gold + 1 (made-up token counts, done_reason stop)."""

    def __init__(self, items: list[dict]):
        self.items, self.calls = items, 0

    def __call__(self, system: str, user: str, options=None) -> dict:
        self.calls += 1
        it = next(x for x in self.items if user.endswith("\n" + x["question"]))
        return {"content": f"（假生成）\n答案：{it['gold'] + 1}歲", "thinking_chars": 0, "prompt_eval_count": len(user) // 2,
                "eval_count": 40, "done_reason": "stop", "elapsed_s": 0.0}


def fake_ollama(path: str) -> dict:
    if path == "/api/version":
        return {"version": GC.OLLAMA_VERSION}
    return {"models": [{"name": MODEL, "model": MODEL, "digest": GC.EXPECTED_DIGEST, "context_length": 131072}]}


def fake_io(items: list[dict], cards: dict, build: str) -> Io:
    env = [f"LLM_TEMPERATURE={OPTIONS['temperature']}", f"LLM_MAX_TOKENS={OPTIONS['num_predict']}", f"OLLAMA_MODEL={MODEL}"]
    return Io(post=FakeBackend(items, cards, build), chat=FakeChat(items), ollama=fake_ollama,
              health=lambda u: {"status": "ok", "build_id": build},
              inspect=lambda n: [{"Config": {"Env": env}, "State": {"Running": True}, "Image": "fake"}],
              sleep=lambda s: None, log=lambda *a: None)


def dry_run(out: Path, build: str = DRY_BUILD) -> dict:
    """a4 on the store inputs with the fakes into ``out`` (replaced each time): the flow, never a result."""
    w = Writer(out, dry=True)
    old = w.read_json(RUN_META)
    if old is not None and not old.get("dry_run"):
        raise SystemExit(f"{w.root} holds a run that is not a dry run")
    for n in (RUN_META, CALLS, REPORT):
        if w.path(n).is_file():
            w.path(n).unlink()
    items, cards = load_inputs()
    return run(MODES["a4"], w, items, cards, build, fake_io(items, cards, build), dry=True)


def summary(rep: dict) -> dict:
    keys = ("run", "mode", "state", "judged", "first_judged_run", "n_planned", "n_attempts", "voids", "void", "pass",
            "card_parity", "gen_cards", "n_items", "n_fired")
    out = {k: rep[k] for k in keys if k in rep}
    if "gates" in rep:
        out["gates"] = {k: v if k == "propose_prod" else v.get("pass", v.get("stop")) for k, v in rep["gates"].items()}
        out["delta"] = {k: {x: t[x] for x in ("delta", "ci95", "p", "W", "L", "T")} for k, t in rep["delta"].items()}
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="GEN 卡 A4（計畫 docs/records/2026-10-21_gen_card_integration_plan.md §3.2）")
    ap.add_argument("mode", choices=("a4", "prod-check", "dry-run"))
    ap.add_argument("--build", default=None, help="a4／prod-check：新 build 的 id（每個 source 的 build_id 都要是它）")
    ap.add_argument("--run", default=None, help="a4／prod-check：store reports/gen_card_20261021/ 下的 run 目錄名")
    ap.add_argument("--out", type=Path, default=None, help="dry-run：寫入的目錄（不可在 store 或 repo 裡）")
    args = ap.parse_args(argv)
    if args.mode == "dry-run":
        if args.out is None or args.run:
            ap.error("dry-run takes --out DIR (and no --run)")
        rep = dry_run(args.out, args.build or DRY_BUILD)
    else:
        if not args.build or args.out:
            ap.error(f"{args.mode} takes --build (and no --out)")
        mode = MODES[args.mode]
        items, cards = load_inputs()
        rep = run(mode, Writer(OUT_ROOT / (args.run or mode.run)), items, cards, args.build, real_io())
    print(json.dumps(summary(rep), ensure_ascii=False))


if __name__ == "__main__":
    main()
