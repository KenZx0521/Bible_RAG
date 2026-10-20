"""Driver of the GEN confirmation set's generation side (prereg §4, §6, §8.1-11/12). Host python -B (the evaluation venv).

    python -B run_g.py harness-k0                  # the K0 harness record (store harness_record.json, once)
    python -B run_g.py harness-change --anchor A   # a logged change of the harness after K0 (A: its log line)
    python -B run_g.py build      # F3: items, cards, jobs, arms_meta (run/) and f3.json, from questions_frozen.json
    python -B run_g.py dry-run    # the whole flow with the fake chat into run/dry_run/: run, score, analyze (CPU)
    python -B run_g.py smoke [--redo A | --void-truncated A]   # §4.4 (smoke_g): the 2 longest prompts per arm,
                                                   # rep 1, token counts only (Ollama)
    python -B run_g.py run [--infra-fix A] [--canary-fixed NOTE]   # canary (first 30 calls, as A), then
                                                   # the formal run (Ollama)
    python -B run_g.py score   [--out DIR] [--jobs-unrecoverable]
    python -B run_g.py analyze [--out DIR] [--jobs-unrecoverable]

Outputs: the store's reports/gen_confirm_20261020/run/ (cli_out); the harness record next to it. run_x (stage-0)
copied and changed: store root, inputs, §4.5's gates, the pinned Ollama version, the canary. ``build`` (F3) runs
only after F2 (f2.json of these questions, K-a and parity passed; gencard never sees a frozen question before F2's
step 5, §5.5), reads questions_frozen.json (arms_g's contract, checked against order.json), pool.json, the layer
and gen_names.json and writes only when the F3 checks pass (arms_g.card_problems, job_problems) and its prompts are
the ones F2's parity checked, never over a differing build, never once a formal run exists.
One directory per run kind, named in run_meta.json; a directory never takes another kind, job list, options,
model, inputs or harness, a void run is never resumed, a session holds run.lock. cards_common.run_jobs (3 rounds;
an Ollama exception is retried, never a result) with stage-0's options (temperature 0.1, num_predict 10000,
num_ctx 131072); dry runs and tests swap cards_common.chat for a fake inside ``execute`` only; a torn last line
is moved aside and its job redone. Before and after every session the digest (/api/ps, else /api/tags) must be
EXPECTED_DIGEST and /api/version OLLAMA_VERSION (0.32.5), and before it no other model may be loaded; a check
that differs voids the run (§4.5) or is refused before any call.
Anchors and the harness record are f1_g's (a smoke redo's or void's anchor must be newer than K0 and every redo).
An infrastructure fix of the harness between formal sessions: commit it, ``harness-change --anchor A``, then ``run
--infra-fix A`` (A the record's last change, unused by an earlier session; the run keeps it in harness_history).
Gates before any Ollama call (§4.5, all; ``gate_problems``): A's frozen pins (c_common.frozen_mismatches);
stage-0's input pins (x_common.check_pins) and harness (its formal run's record); metric_version() =
4d0826bb8d14 (a fresh interpreter); this experiment's harness (every .py here and in gencard/, every
tests/test_gen_confirm_*.py, prereg.md above 「## 執行紀錄」) equal to the harness record and committed unchanged;
the F1 manifest's files (gencard/*.py, gen_names.json, mech_g.py, F1's own files, backend_pins() and
trigger_pins(): f1_g.prod_pins) unchanged; no void record (void_g: a prompt-parity or truncation void);
gen_layer.json's prefix 46d87abb2900 and pool.json's sha256; the manifest's, order.json's (drawn from it),
questions_frozen.json's and the P2 near-miss record's sha256 in the log; f2.json of these questions and this
manifest with K-a and parity passed on the build's prompts; the store build equal to a fresh one passing F3.
smoke (smoke_g, which reads this module's paths and gates): a truncation keeps the formal run from starting (an
infrastructure problem, §4.4); a void (digest or Ollama version) or truncated smoke is set aside by ``smoke --redo
A`` after a logged fix (a truncated one only when it ran with §4.3's options), and a truncation with no
infrastructure cause is recorded by ``smoke --void-truncated A`` (作廢). Once void_g's record exists, smoke, run,
score and dry-run refuse and analyze writes the void sentence only. run: the canary is the formal run's first
session (the first 30 calls; all answered, no
error line), else a stop for an infrastructure fix and a rerun with --canary-fixed NOTE, setting the error lines
so far aside (A's run_c); truncations are listed. Jobs missing after 3 rounds stop the run; score and analyze
refuse it (and an unfinished or unknown run) unless --jobs-unrecoverable (作廢). For a formal run score and analyze
also refuse a harness that is uncommitted or not its record, and report the harness files changed since the run.
analyze reads §9's release-clause count only from the store P2 record qset/p2_near_miss.json {"fired": k,
"n": 20}, its sha256 in the log (the qset runner writes it at P2, §8.1-5), f2.json's measures and the failed slots
by why from freeze_g's HO_ROOT/freeze.json beside the run root (``freeze_file``, D24). Prints counts, ids, sha.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_g as AG  # noqa: E402
import arms_g as A  # noqa: E402
import f1_g as F1  # noqa: E402
import g_common as GC  # noqa: E402
import gencard  # noqa: E402
import score_g as SG  # noqa: E402
import void_g as V  # noqa: E402

S = A.S
X, cc = S.x_common, A.cc
now = F1.now
OPTIONS = dict(GC.OLLAMA_OPTIONS)                   # §4.3 (stage-0's): temperature 0.1, num_predict 10000, num_ctx 131072
CHECK_ERRORS = (OSError, ValueError, http.client.HTTPException, AttributeError)
RUN_ROOT = GC.RUN_ROOT
F2_FILE = GC.F2_FILE
P2_RESULT = GC.P2_NEAR_MISS
P2_N = GC.N_NEAR                                    # §5.4, §9: the P2 near-miss items
STAGE0_RUN_META = GC.STAGE0_RUN_META
DATA_FILES = GC.RUN_DATA_FILES
F3_FILE, SMOKE_FILE, CANARY_FILE, RUN_META, GEN = GC.RUN_F3, GC.RUN_SMOKE, GC.RUN_CANARY, GC.RUN_META, SG.GEN
SMOKE_HISTORY, SMOKE_SET_ASIDE = GC.SMOKE_HISTORY, GC.SMOKE_SET_ASIDE
TORN, LOCK = GC.RUN_TORN, GC.RUN_LOCK
KINDS = GC.RUN_KINDS
SMOKE_PER_ARM, CANARY_CALLS = GC.SMOKE_PER_ARM, GC.CANARY_CALLS
PREREG = F1.PREREG
EVAL_DIR = GC.EVAL_DIR
MV_PROBE = ("import sys; sys.argv = ['probe']; sys.path.insert(0, {d!r}); import quick_retrieval_eval as q; "
            "print(q.metric_version())")
INFRA_NOT_LAST = "--infra-fix: the anchor is not the harness record's last change (harness-change --anchor first)"


def store(name: str) -> Path:
    return Path(RUN_ROOT) / name


def void_file() -> Path:
    """void_g's record beside the run root (OUT_ROOT/void.json; a test's run root keeps its own)."""
    return Path(RUN_ROOT).parent / GC.VOID_FILE.name


def freeze_file() -> Path:
    """freeze_g's record beside the run root (OUT_ROOT/ho/freeze.json; a test's run root keeps its own)."""
    return Path(RUN_ROOT).parent / GC.HO_ROOT.relative_to(GC.OUT_ROOT) / GC.FREEZE_FILE


def cli_out(path: Path | str, allow_root: bool = False) -> Path:
    """A command-line output path: strictly under RUN_ROOT (RUN_ROOT itself only with allow_root)."""
    p, root = GC.writable(path), Path(RUN_ROOT).resolve()
    if not (root in p.parents or (allow_root and p == root)):
        raise SystemExit(f"{p}: the command line writes only under {root}")
    return p


def doc_sha(obj) -> str:
    """sha256 of the file g_common.write_json writes for obj."""
    return GC.sha256_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


# ---------------------------------------------------------------- the harness record (f1_g) and --infra-fix
def infra_fix_problems(fix: str, *, record: Path | None = None) -> list[str]:
    """run --infra-fix A: A is the harness record's last change, a formal run exists, no earlier session used A."""
    record, a = Path(record or F1.HARNESS_RECORD), (fix or "").strip()
    changes = GC.read_json(record)["changes"] if record.is_file() else []
    out = [] if changes and changes[-1]["note"] == a else [INFRA_NOT_LAST]
    meta_p = store("formal") / RUN_META
    if not meta_p.is_file():
        return out + ["--infra-fix resumes a formal run and there is none"]
    used = {h["note"] for h in GC.read_json(meta_p).get("harness_history", [])}
    return out + (["--infra-fix: an earlier session of the formal run used this anchor"] if a in used else [])


# ---------------------------------------------------------------- inputs and the build (F3)
def load_sources() -> SimpleNamespace:
    """The store inputs of the build: questions_frozen.json, pool.json, order.json, the layer and gen_names.json."""
    if GC.sha256_file(GC.POOL) != GC.POOL_SHA256 or not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise SystemExit("pool.json or gen_layer.json is not the pinned file (prereg §2, §4.5)")
    if not GC.ORDER.is_file():
        raise SystemExit(f"{GC.ORDER} missing: no writing order (prereg §2.3)")
    pool = GC.read_json(GC.POOL)["pool"]
    return SimpleNamespace(frozen=GC.read_json(GC.QUESTIONS_FROZEN), frozen_sha256=GC.sha256_file(GC.QUESTIONS_FROZEN),
                           pool=pool, gen=S.gen_layer.load(), item_of=A.stage0_item, order=GC.read_json(GC.ORDER)["order"],
                           L=gencard.parse(GC.read_json(GC.GEN_LAYER), GC.read_json(GC.GEN_NAMES)))


def build_docs(src: SimpleNamespace) -> dict:
    """{file name: document} of a fresh build."""
    b = A.build(src.frozen, src.pool, src.L, src.gen, src.item_of, order=src.order)
    att = {c: list(src.frozen["attrition"][c]) for c in A.ATTRITION}
    return {GC.RUN_ITEMS: {"schema": "gen_confirm.items.v1", "questions_frozen_sha256": src.frozen_sha256,
                           "n_target": src.frozen["n_target"], "attrition": att,
                           "questions": [{"sid": it["sid"]} for it in b["items"]],
                           "pool": [{"sid": p["sid"], "stratum": p["stratum"]} for p in src.pool], "items": b["items"]},
            GC.RUN_CARDS: {"schema": A.SCHEMA_CARDS, "cap_chars": A.CAP_CHARS, "cards": b["cards"]},
            GC.RUN_JOBS: b["jobs"],
            GC.RUN_ARMS_META: {"schema": "gen_confirm.arms_meta.v1", "summary": A.summary(b["jobs"]), "meta": b["meta"]}}


def f3_checks(docs: dict) -> dict:
    items, cards = docs[GC.RUN_ITEMS]["items"], docs[GC.RUN_CARDS]["cards"]
    meta, jobs = docs[GC.RUN_ARMS_META]["meta"], docs[GC.RUN_JOBS]
    cp, jp = A.card_problems(items, cards, meta), A.job_problems(items, jobs, meta)
    return {"schema": "gen_confirm.f3.v1", "pass": not cp and not jp, "card_problems": cp, "job_problems": jp,
            "sha256": {n: doc_sha(o) for n, o in docs.items()}, "prompts_sha256": A.prompts_sha256(jobs),
            "contexts_sha256": {i: m["context_sha256"] for i, m in meta.items()},
            "questions_frozen_sha256": docs[GC.RUN_ITEMS]["questions_frozen_sha256"], "measures": A.rule_measures(meta)}


def build(_args=None, *, src: SimpleNamespace | None = None, log=print) -> dict:
    if (store("formal") / RUN_META).exists():
        raise SystemExit("a formal run exists: its inputs are frozen, build is refused")
    if bad := f2_problems():
        raise SystemExit(f"build refused, nothing written (F2 steps 5–7 first, §5.5): {bad}")
    docs = build_docs(src or load_sources())
    differ = [n for n, o in docs.items() if store(n).exists() and GC.sha256_file(store(n)) != doc_sha(o)]
    if differ:
        raise SystemExit(f"{differ} exist and differ from this build: not overwritten (nothing written)")
    f3 = f3_checks(docs)
    if not f3["pass"]:
        raise SystemExit(f"F3 checks failed (cards {sorted(f3['card_problems'])}, jobs {f3['job_problems']}): nothing written")
    if bad := f2_problems(prompts_sha=f3["prompts_sha256"]):
        raise SystemExit(f"build refused, nothing written: {bad}")
    for n, o in docs.items():
        GC.write_json(cli_out(store(n)), o)
    GC.write_json(cli_out(store(F3_FILE)), f3)
    log({"n_items": len(docs[GC.RUN_ITEMS]["items"]), "n_jobs": len(docs[GC.RUN_JOBS]), "prompts_sha256": f3["prompts_sha256"]})
    return f3


def load_inputs() -> dict:
    """The store build ({file name: document}, plus f3.json), each file's sha256 checked against f3.json."""
    if not store(F3_FILE).is_file():
        raise SystemExit(f"{store(F3_FILE)} missing: run build first")
    f3 = GC.read_json(store(F3_FILE))
    out = {F3_FILE: f3}
    for n in DATA_FILES:
        p = store(n)
        if not p.is_file() or GC.sha256_file(p) != f3["sha256"].get(n):
            raise SystemExit(f"{p} missing or not the file f3.json names")
        out[n] = GC.read_json(p)
    return out


def inputs_sha() -> dict:
    return {n: GC.sha256_file(store(n)) for n in (*DATA_FILES, F3_FILE)}


# ---------------------------------------------------------------- Ollama checks
def api_get(path: str) -> dict:
    with urllib.request.urlopen(cc.OLLAMA + path, timeout=30) as resp:
        return json.loads(resp.read())


def _is_model(m: dict) -> bool:
    return GC.MODEL in (m.get("name"), m.get("model"))


def ollama_check(get, when: str) -> dict:
    """The model digest (/api/ps, else /api/tags), /api/version and the other loaded models; None = no answer."""
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


def before_problems(c: dict) -> list[str]:
    out = [] if c["digest"] == GC.EXPECTED_DIGEST else [f"model digest {c['digest']} ({c['where']}) is not {GC.EXPECTED_DIGEST}"]
    if c["version"] != GC.OLLAMA_VERSION:
        out.append(f"Ollama version {c['version']} is not {GC.OLLAMA_VERSION}")
    if c["others"] is None or c["others"]:
        out.append(f"Ollama is not ours alone: /api/ps lists {c['others']}")
    return out


def run_state(meta: dict) -> tuple[str, list[str]]:
    """("void" | "unfinished" | "unknown" | "ok", why void): a digest or version other than the pinned one voids
    the run; no after-check since the last start = unfinished; an after-check without an answer = unknown."""
    checks = meta.get("checks") or []
    why = [f"{c['when']} {c['t']}: digest {c['digest']}" for c in checks
           if c["digest"] is not None and c["digest"] != GC.EXPECTED_DIGEST]
    why += [f"{c['when']} {c['t']}: Ollama version {c['version']}" for c in checks
            if c["version"] is not None and c["version"] != GC.OLLAMA_VERSION]
    if why:
        return "void", why
    if not checks or checks[-1]["when"] != "after":
        return "unfinished", []
    last = checks[-1]
    return ("unknown" if last["digest"] is None or last["version"] is None else "ok"), []


# ---------------------------------------------------------------- runs (run_x's, unchanged in kind)
def guard(out: Path, kind: str, sha: str, n_jobs: int, pins: dict, infra_fix: str | None = None) -> dict:
    meta_p = out / RUN_META
    if infra_fix is not None and kind != "formal":
        raise SystemExit("--infra-fix is for resuming the formal run only")
    if meta_p.exists():
        old = GC.read_json(meta_p)
        if old.get("kind") != kind:
            raise SystemExit(f"{out} is a {old.get('kind')} directory, not {kind}")
        if (old["jobs_sha256"], old["options"], old["model"], old["inputs_sha256"]) != \
                (sha, OPTIONS, GC.MODEL, pins["inputs_sha256"]):
            raise SystemExit(f"{meta_p}: jobs, options, model or inputs differ from the run in this directory")
        changed = old["harness"]["sha256"] != pins["harness"]["sha256"]
        if infra_fix is not None and not changed:
            raise SystemExit(f"--infra-fix: the harness files are the run's ({meta_p}); resume without it")
        if changed and kind != "dry_run" and infra_fix is None:
            raise SystemExit(f"{meta_p}: the harness differs from the run in this directory (after an "
                             "infrastructure fix a formal run resumes with --infra-fix)")
        state, why = run_state(old)
        if state == "void":
            raise SystemExit(f"{meta_p}: the run is void ({why}); it is not resumed")
        keep = {k: v for k, v in old.items() if k not in ("finished", "n_done", "missing", "state", "void", "error_lines")}
        if infra_fix is not None:
            keep = {**keep, "harness": pins["harness"],
                    "harness_history": old.get("harness_history", []) + [F1.harness_change(old["harness"], pins["harness"],
                                                                                           infra_fix.strip())]}
        return {**keep, "resumed": old.get("resumed", []) + [now()]}
    if infra_fix is not None:
        raise SystemExit(f"--infra-fix resumes a formal run: {meta_p} does not exist")
    if (out / GEN).exists():
        raise SystemExit(f"{out / GEN} exists without {RUN_META}")
    return {"kind": kind, "jobs_sha256": sha, "n_jobs": n_jobs, "options": OPTIONS, "model": GC.MODEL,
            "expected_digest": GC.EXPECTED_DIGEST, "ollama_version": GC.OLLAMA_VERSION, **pins, "started": now(),
            "checks": [], "resumed": []}


@contextlib.contextmanager
def run_lock(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with cli_out(out / LOCK).open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"{out / LOCK}: another run holds this directory; refused") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def repair_tail(p: Path, side: Path) -> dict | None:
    """A last line cut by a kill: unparsable, it goes to side and is cut off p (its job is redone)."""
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if not raw or raw.endswith(b"\n"):
        return None
    head, nl, tail = raw.rpartition(b"\n")
    try:
        json.loads(tail)
    except ValueError:
        with cli_out(side).open("ab") as f:
            f.write(tail + b"\n")
        with p.open("r+b") as f:
            f.truncate(len(head) + len(nl))
        return {"action": "moved_to_side", "bytes": len(tail)}
    with p.open("ab") as f:
        f.write(b"\n")
    return {"action": "newline_added", "bytes": len(tail)}


def repair_torn(out: Path, meta: dict, log=print) -> dict:
    if (fix := repair_tail(out / GEN, out / TORN)) is None:
        return meta
    rec = {"t": now(), **fix}
    log(f"torn last line of {GEN}: {fix['action']} ({fix['bytes']} bytes)")
    disk = GC.read_json(out / RUN_META)
    GC.write_json(out / RUN_META, {**disk, "torn": disk.get("torn", []) + [rec]})
    return {**meta, "torn": meta.get("torn", []) + [rec]}


def refuse_before_call(out: Path, meta: dict, before: dict, want_version: str | None) -> None:
    state, why = run_state({**meta, "checks": meta["checks"] + [before]})
    if state == "void":
        last = meta["checks"][-1] if meta["checks"] else None
        if last and not (last["when"] == "after" and last["digest"] is not None and last["version"] is not None):
            GC.write_json(out / RUN_META, {**GC.read_json(out / RUN_META), **meta, "checks": meta["checks"] + [before],
                                           "state": "void", "void": why})
            raise SystemExit(f"refused before any call: {why}; this check stands in for the after-check of the "
                             "unclosed last session, so the run is void")
        raise SystemExit(f"refused before any call: {why} (restore the run's model and Ollama version to resume)")
    bad = before_problems(before)
    if bad:
        raise SystemExit(f"refused before any call: {bad}")
    if want_version is not None and before["version"] != want_version:
        raise SystemExit(f"refused before any call: Ollama version {before['version']} is not the smoke's {want_version}")


@contextlib.contextmanager
def chat_as(fn):
    """cards_common.run_jobs with fn in place of cards_common.chat (None: the real chat)."""
    old = cc.chat
    cc.chat = fn or old
    try:
        yield
    finally:
        cc.chat = old


def execute(out: Path, jobs: list[dict], kind: str, *, chat=None, get=None, log=print, infra_fix: str | None = None,
            want_version: str | None = None, limit: int | None = None) -> dict:
    """One session of a run on ``jobs`` (its first ``limit`` only, for the canary): lock, guard, torn-line repair,
    before-check, cards_common.run_jobs, after-check; returns run_meta. Nothing to do: no session."""
    if kind not in KINDS:
        raise ValueError(kind)
    out, get = cli_out(out), get or api_get
    todo = jobs[:limit] if limit else jobs
    with run_lock(out):
        pins = {"inputs_sha256": inputs_sha(), "harness": F1.harness_pins()}
        meta = guard(out, kind, A.prompts_sha256(jobs), len(jobs), pins, infra_fix)
        meta = repair_torn(out, meta, log)
        if run_state(meta)[0] == "ok" and all(j["job_id"] in cc.done_jobs(out / GEN) for j in todo):
            log("nothing to do: every job is answered and the last after-check agrees; no new session")
            return GC.read_json(out / RUN_META)
        before = ollama_check(get, "before")
        refuse_before_call(out, meta, before, want_version)
        meta = {**meta, "checks": meta["checks"] + [before]}
        GC.write_json(out / GC.RUN_JOBS, jobs)
        GC.write_json(out / RUN_META, meta)
        with chat_as(chat):
            done = cc.run_jobs(todo, cli_out(out / GEN), log=log, options=dict(OPTIONS))
        meta = {**meta, "checks": meta["checks"] + [ollama_check(get, "after")]}
        missing = [j["job_id"] for j in jobs if j["job_id"] not in done]
        state, why = run_state(meta)
        meta = {**meta, "n_done": len(jobs) - len(missing), "missing": missing, "state": state, "void": why,
                "error_lines": sum(r.get("type") == "error" for r in X.jsonl(out / GEN)), "finished": now()}
        GC.write_json(out / RUN_META, meta)
        return meta


def run_meta(d: Path) -> dict:
    if not (d / RUN_META).is_file():
        raise SystemExit(f"{d / RUN_META} missing: not a run directory")
    return GC.read_json(d / RUN_META)


# ---------------------------------------------------------------- gates before Ollama (§4.5)
def metric_version() -> str:
    """quick_retrieval_eval.metric_version() as a fresh interpreter computes it."""
    r = subprocess.run([sys.executable, "-B", "-c", MV_PROBE.format(d=str(EVAL_DIR))], cwd=EVAL_DIR,
                       capture_output=True, text=True, timeout=600)
    return r.stdout.strip() if r.returncode == 0 else "probe failed"


def stage0_problems(record: Path = STAGE0_RUN_META) -> list[str]:
    """stage-0's input pins and its harness (the five imported files included) against its formal run's record."""
    out = [f"stage-0 pin: {p}" for p in X.check_pins()]
    if not Path(record).is_file():
        return out + ["stage-0's formal run_meta.json missing"]
    rec, cur = GC.read_json(record)["harness"]["files_sha256"], X.harness_files_sha256()
    diff = sorted(n for n in rec.keys() | cur.keys() if rec.get(n) != cur.get(n))
    return out + ([f"stage-0 harness differs from its formal run: {diff}"] if diff else [])


def p2_problems(path: Path | None = None, prereg: Path | None = None) -> list[str]:
    """The P2 near-miss record (§8.1-5): {"fired": k, "n": 20} with 0 ≤ k ≤ 20, its sha256 in the log."""
    p = Path(path or P2_RESULT)
    if not p.is_file():
        return ["no P2 near-miss record (store qset/p2_near_miss.json, §8.1-5)"]
    doc = GC.read_json(p)
    k, n = (doc.get("fired"), doc.get("n")) if isinstance(doc, dict) else (None, None)
    ok = all(isinstance(v, int) and not isinstance(v, bool) for v in (k, n)) and n == P2_N and 0 <= k <= n
    out = [] if ok else [f"the P2 near-miss record is not {{fired: k, n: {P2_N}}}"]
    return out + ([] if GC.sha256_file(p) in F1.log_text(prereg or F1.PREREG) else
                  ["the P2 near-miss record's sha256 is not in the log"])


def p2_near_miss(path: Path | None = None, prereg: Path | None = None) -> tuple[int, int]:
    """(k, 20) from the store P2 record only (no command-line override: §9's release clause is P2's count)."""
    if bad := p2_problems(path, prereg):
        raise SystemExit(f"analyze refused: {bad}")
    doc = GC.read_json(Path(path or P2_RESULT))
    return doc["fired"], doc["n"]


def pin_problems(prereg: Path = PREREG, *, group: dict[str, Path] | None = None) -> list[str]:
    """§4.5's file pins: the layer, pool.json, the F1 manifest (its sha256 logged, its files unchanged), order.json
    and questions_frozen.json (logged, the order drawn from this manifest) and the P2 near-miss record."""
    out, log = [], F1.log_text(prereg)
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        out.append(f"gen_layer.json is not {GC.GEN_LAYER_SHA256_PREFIX}")
    if GC.sha256_file(GC.POOL) != GC.POOL_SHA256:
        out.append("pool.json is not the pinned one")
    if not GC.F1_MANIFEST.is_file():
        return out + ["no F1 manifest"] + p2_problems(prereg=prereg)
    man_sha, files = GC.sha256_file(GC.F1_MANIFEST), GC.read_json(GC.F1_MANIFEST)["files"]
    out += [] if man_sha in log else ["the F1 manifest's sha256 is not in the log"]
    now_files = {**F1.sha_map(F1.frozen_paths() if group is None else group), **F1.prod_pins()}
    out += [f"F1 manifest: {p}" for p in F1.manifest_problems(files, now_files)]
    for path in (GC.ORDER, GC.QUESTIONS_FROZEN):
        if not path.is_file() or GC.sha256_file(path) not in log:
            out.append(f"{path.name} missing or its sha256 not in the log")
    if GC.ORDER.is_file() and GC.read_json(GC.ORDER).get("f1_manifest_sha256") != man_sha:
        out.append("order.json was drawn from another F1 manifest")
    return out + p2_problems(prereg=prereg)


def f2_problems(f2_file: Path | None = None, prompts_sha: str | None = None) -> list[str]:
    """f2.json (F2 steps 5–7) of these questions and this manifest, K-a and parity passed, and (given) these prompts."""
    p = Path(f2_file or F2_FILE)
    if not p.is_file():
        return ["no f2.json (F2 steps 5–7)"]
    f2, out = GC.read_json(p), []
    q = GC.sha256_file(GC.QUESTIONS_FROZEN) if GC.QUESTIONS_FROZEN.is_file() else None
    out += [] if q and f2.get("questions_frozen_sha256") == q else ["f2.json is of other questions"]
    m = GC.sha256_file(GC.F1_MANIFEST) if GC.F1_MANIFEST.is_file() else None
    out += [] if m and f2.get("f1_manifest_sha256") == m else ["f2.json names another F1 manifest"]
    out += [] if f2["K_a"]["pass"] else ["K-a stopped the line: " + str(f2["K_a"]["sentence"])]
    if not f2["parity"]["pass"]:
        out.append("prompt parity failed")
    if prompts_sha is not None and f2.get("prompts_sha256") != prompts_sha:
        out.append("the build's prompts are not the ones F2's parity checked")
    return out


def gate_problems(infra_fix: str | None = None, *, prereg: Path = PREREG) -> list[str]:
    """Why no Ollama call may be made yet (empty = smoke may run)."""
    out = V.problems(void_file()) + F1.git_problems(prereg)
    out += [f"experiment A frozen: {p}" for p in X.c_common.frozen_mismatches()] + stage0_problems()
    mv = metric_version()
    out += [] if mv == GC.METRIC_VERSION else [f"metric_version {mv} is not {GC.METRIC_VERSION}"]
    out += pin_problems(prereg)
    out += F1.harness_problems(prereg=prereg)
    out += [] if infra_fix is None else infra_fix_problems(infra_fix)
    try:
        inp = load_inputs()
    except SystemExit as e:
        return out + f2_problems() + [str(e)]
    out += f2_problems(prompts_sha=inp[F3_FILE]["prompts_sha256"])
    docs = build_docs(load_sources())
    out += [f"{n}: a fresh build differs from the store" for n in DATA_FILES if doc_sha(docs[n]) != inp[F3_FILE]["sha256"][n]]
    return out + ([] if f3_checks(docs)["pass"] else ["the F3 checks fail on a fresh build"])


# ---------------------------------------------------------------- the canary (the smoke is smoke_g's)
def canary_errors(d: Path, jobs: list[dict]) -> int:
    ids = {j["job_id"] for j in jobs[:CANARY_CALLS]}
    return sum(r.get("type") == "error" and r.get("job_id") in ids for r in X.jsonl(d / GEN))


def canary_status(d: Path, jobs: list[dict], ignore: int = 0) -> dict:
    """A's canary: the first 30 calls answered, no error line among them (beyond the ``ignore`` error lines a
    --canary-fixed rerun sets aside, as A's run_c); truncations listed, not a failure."""
    ids = {j["job_id"] for j in jobs[:CANARY_CALLS]}
    done = cc.done_jobs(d / GEN)
    st = {"n_canary": len(ids), "missing": sorted(ids - set(done)), "errors": canary_errors(d, jobs) - ignore,
          "ignored_errors": ignore,
          "truncated": sorted(i for i in ids & set(done) if SG.truncated(done[i], OPTIONS["num_ctx"]))}
    return {**st, "pass": not st["missing"] and not st["errors"]}


def record_canary(p: Path, st: dict, note: str | None) -> None:
    old = GC.read_json(p) if Path(p).is_file() else {}
    rec = {**st, "note": note, "t": now()}
    GC.write_json(cli_out(p), {**rec, "history": old.get("history", []) + [rec]})


def smoke_module():
    """smoke_g, which imports this module (so it is imported when a command needs it, not at load time)."""
    import smoke_g
    return smoke_g


def smoke(args=None, *, get=None, log=print) -> dict:
    return smoke_module().smoke(args, get=get, log=log)


def run(args=None, *, get=None, log=print, chat=None) -> dict:
    if bad := V.problems(void_file()):
        raise SystemExit(f"formal run refused: {bad}")
    SM = smoke_module()
    fix = getattr(args, "infra_fix", None)
    bad = gate_problems(infra_fix=fix)
    inp = None if bad else load_inputs()
    bad += SM.smoke_problems(inp[GC.RUN_JOBS]) if inp else []
    if bad:
        raise SystemExit(f"formal run refused: {bad}")
    d, jobs, ver = store("formal"), inp[GC.RUN_JOBS], SM.smoke_version()
    cp, note = d / CANARY_FILE, getattr(args, "canary_fixed", None)
    if not (cp.is_file() and GC.read_json(cp).get("pass")):
        ignore = canary_errors(d, jobs) if note else 0
        execute(d, jobs, "formal", chat=chat, get=get, log=log, infra_fix=fix, want_version=ver, limit=CANARY_CALLS)
        st = canary_status(d, jobs, ignore)
        record_canary(cp, st, note)
        if not st["pass"]:
            raise SystemExit(f"canary not passed (missing {len(st['missing'])}, errors {st['errors']}): fix the "
                             "infrastructure first (no answer is read), then run --canary-fixed NOTE")
        fix = None
    elif note:
        raise SystemExit("--canary-fixed: the canary has passed")
    meta = execute(d, jobs, "formal", chat=chat, get=get, log=log, infra_fix=fix, want_version=ver)
    log({k: meta[k] for k in ("n_jobs", "n_done", "state", "error_lines")} | {"missing": len(meta["missing"])})
    if meta["state"] == "void":
        raise SystemExit(f"作廢（digest／Ollama 版本）：{meta['void']}")
    if meta["state"] == "unknown":
        raise SystemExit("the after-check got no answer from Ollama: run again (it resumes and checks again)")
    if meta["missing"]:
        raise SystemExit(f"{len(meta['missing'])} jobs missing after 3 rounds: fix the infrastructure, then run again")
    return meta


# ---------------------------------------------------------------- score and analyze
def harness_since_run(meta: dict) -> dict:
    """The harness now against the run's (its last session's), with the files changed since."""
    cur, ran = F1.harness_pins(), meta["harness"]
    a, b = ran["files_sha256"], cur["files_sha256"]
    return {"run_sha256": ran["sha256"], "sha256": cur["sha256"],
            "changed_since_run": sorted(n for n in a.keys() | b.keys() if a.get(n) != b.get(n))}


def scored_dir(out, jobs_unrecoverable: bool = False) -> tuple[Path, dict]:
    d = cli_out(out or store("formal"))
    meta = run_meta(d)
    if meta["kind"] == "smoke":
        raise SystemExit("the smoke is never scored (token counts only)")
    state = run_state(meta)[0]
    if state in ("unfinished", "unknown"):
        raise SystemExit(f"{d}: the run is {state}: resume it first")
    if jobs_unrecoverable and not meta.get("missing"):
        raise SystemExit(f"{d}: --jobs-unrecoverable, but no job is missing")
    if state == "ok" and meta.get("missing") and not jobs_unrecoverable:
        raise SystemExit(f"{d}: {len(meta['missing'])} jobs missing: fix the infrastructure and resume; only if they "
                         "cannot be done, pass --jobs-unrecoverable (the report is then 作廢)")
    if meta["inputs_sha256"] != inputs_sha():
        raise SystemExit(f"{d}: the store build is not the one this run used")
    if meta["kind"] == "formal" and (bad := F1.git_problems() + F1.harness_problems()):
        raise SystemExit(f"{d}: the harness is uncommitted or not its record ({bad}): no score or report")
    return d, meta


def score(args=None) -> dict:
    if bad := V.problems(void_file()):
        raise SystemExit(f"score refused: {bad}")
    unrec = bool(getattr(args, "jobs_unrecoverable", False))
    d, meta = scored_dir(getattr(args, "out", None), unrec)
    inp, jobs = load_inputs(), GC.read_json(d / GC.RUN_JOBS)
    if A.prompts_sha256(jobs) != meta["jobs_sha256"]:
        raise SystemExit(f"{d / GC.RUN_JOBS} is not the job list of this run")
    doc = SG.score_all(d, inp[GC.RUN_ITEMS]["items"], inp[GC.RUN_ARMS_META]["meta"], jobs,
                       num_ctx=meta["options"]["num_ctx"])
    doc = {**doc, "run": {"dir": str(d), "kind": meta["kind"], "state": run_state(meta)[0],
                          "jobs_sha256": meta["jobs_sha256"], "jobs_unrecoverable": unrec, "harness": harness_since_run(meta)}}
    GC.write_json(cli_out(d / GC.RUN_SCORES), doc)
    print({"kind": meta["kind"], "n_records": doc["n_records"], "missing": len(doc["missing_jobs"])})
    return doc


def report_segments(meta: dict) -> list[dict]:
    """One segment per session start; its after-values are the next check that got an answer."""
    cs, out = meta.get("checks") or [], []

    def later(i: int, key: str):
        return next(((c[key], c["t"]) for c in cs[i + 1:] if c[key] is not None), (None, None))
    for i, c in enumerate(cs):
        if c["when"] == "before":
            (dg, t), (v, _t) = later(i, "digest"), later(i, "version")
            out.append({"digest_before": c["digest"], "digest_after": dg, "version_before": c["version"],
                        "version_after": v, "t_before": c["t"], "t_after": t, "dry_run": meta["kind"] == "dry_run"})
    return out


def void_analyze(void: dict, out=None) -> dict:
    """A void line: report.json and report.md with §9's void sentence only (no run is read)."""
    rep = AG.void_report(void)
    AG.write_report(rep, cli_out(Path(out or store("formal")) / GC.RUN_REPORT).parent)
    print({"result": rep["verdict"]["result"], "void": void.get("why")})
    return rep


def analyze(args=None) -> dict:
    if (void := V.read(void_file())) is not None:
        return void_analyze(void, getattr(args, "out", None))
    unrec = bool(getattr(args, "jobs_unrecoverable", False))
    d, meta = scored_dir(getattr(args, "out", None), unrec)
    if not (d / GC.RUN_SCORES).is_file():
        raise SystemExit(f"{d / GC.RUN_SCORES} missing: run score first")
    scores = GC.read_json(d / GC.RUN_SCORES)
    if (scores.get("run") or {}).get("jobs_sha256") != meta["jobs_sha256"]:
        raise SystemExit(f"{d / GC.RUN_SCORES} is not this run's: run score again")
    inp, formal = load_inputs(), meta["kind"] == "formal"
    if formal and (bad := f2_problems(prompts_sha=inp[F3_FILE]["prompts_sha256"])):
        raise SystemExit(f"analyze refused: {bad}")
    idoc = inp[GC.RUN_ITEMS]
    rep = AG.analyze(scores, idoc["items"], inp[GC.RUN_ARMS_META]["meta"], idoc, idoc["pool"],
                     measures=GC.read_json(F2_FILE)["measures"] if formal else None, run_meta=report_segments(meta),
                     p2_near_miss=p2_near_miss() if formal else None, records=cc.done_jobs(d / GEN),
                     gen_dir=d, jobs_unrecoverable=unrec,
                     failed_by_why=AG.failed_breakdown(idoc["questions_frozen_sha256"], freeze_file()))
    rep = {**rep, "run": {"dir": str(d), "kind": meta["kind"], "state": run_state(meta)[0],
                          "harness": harness_since_run(meta)}}
    AG.write_report(rep, cli_out(d / GC.RUN_REPORT).parent)
    print({"kind": meta["kind"], "result": rep["verdict"]["result"]})
    return rep


# ---------------------------------------------------------------- dry run (fake chat)
class FakeChat:
    """Dry runs and tests: G answers the gold where its card covers it, G-ref the gold, every other arm gold + 1.
    Token counts are made up (prompt = chars / 2, output 40, done_reason stop)."""

    def __init__(self, jobs: list[dict], items: list[dict], meta: dict):
        gold = {it["id"]: it["gold"] for it in items}
        self.answers, self.calls = {}, 0
        for j in jobs:
            right = j["arm"] == "G-ref" or (j["arm"] == "G" and meta[j["item"]]["covered"])
            self.answers.setdefault(j["user"], f"{gold[j['item']] + (0 if right else 1)}歲")

    def __call__(self, system: str, user: str, options=None) -> dict:
        self.calls += 1
        return {"content": f"（假生成，無意義）\n答案：{self.answers.get(user) or '無法判斷'}", "thinking_chars": 0,
                "prompt_eval_count": len(user) // 2, "eval_count": 40, "done_reason": "stop", "elapsed_s": 0.0}


def fake_get(path: str) -> dict:
    if path == "/api/version":
        return {"version": GC.OLLAMA_VERSION}
    return {"models": [{"name": GC.MODEL, "model": GC.MODEL, "digest": GC.EXPECTED_DIGEST}] if path == "/api/tags" else []}


def fake_expectation(scores: dict, meta: dict) -> bool:
    """The fake chat's values: G 1 where covered (abstentions reuse B0: 0), G-ref 1, T-rows and B0 0."""
    for sid, row in scores["items"].items():
        want = {"G": int(meta[sid]["covered"]), "G-ref": 1, "T-rows": 0, "B0": 0}
        if any(SG.frac(row["mean"][a]) != w for a, w in want.items()):
            return False
    return True


def dry_run(_args=None, *, log=print) -> dict:
    """The store build's jobs → fake generation → score → analyze, in dry_run/ (replaced each time)."""
    if bad := V.problems(void_file()):
        raise SystemExit(f"dry-run refused: {bad}")
    inp = load_inputs()
    d = cli_out(store("dry_run"))
    if (d / RUN_META).exists() or (d / GEN).exists():
        if not (d / RUN_META).exists() or GC.read_json(d / RUN_META).get("kind") != "dry_run":
            raise SystemExit(f"{d} is not a dry-run directory")
        for p in d.iterdir():
            if p.is_file() and p.name != LOCK:
                cli_out(p).unlink()
    jobs, meta_items = inp[GC.RUN_JOBS], inp[GC.RUN_ARMS_META]["meta"]
    chat = FakeChat(jobs, inp[GC.RUN_ITEMS]["items"], meta_items)
    meta = execute(d, jobs, "dry_run", chat=chat, get=fake_get, log=lambda *_a: None)
    sc = score(argparse.Namespace(out=d))
    rr = analyze(argparse.Namespace(out=d))
    rep = {"kind": "dry_run", "note": "假 chat；分數無意義，只驗流程", **A.summary(jobs), "fake_calls": chat.calls,
           "run_meta": {k: meta[k] for k in ("n_done", "missing", "state", "error_lines")},
           "fake_expectation": fake_expectation(sc, meta_items), "missing_jobs": len(sc["missing_jobs"]),
           "analyze": {"dry_run": rr["dry_run"], "result": rr["verdict"]["result"]}}
    GC.write_json(cli_out(d / GC.DRY_RUN_REPORT), rep)
    log({k: rep[k] for k in ("n_jobs", "fake_calls", "fake_expectation", "missing_jobs", "analyze")})
    return rep


def harness_cmd(args) -> dict:
    doc = F1.record_change(args.anchor or "") if args.cmd == "harness-change" else F1.record_k0()
    print({"harness_sha256": doc["current"]["sha256"], "changes": len(doc["changes"])})
    return doc


CMDS = {"harness-k0": harness_cmd, "harness-change": harness_cmd, "build": build, "dry-run": dry_run, "smoke": smoke,
        "run": run, "score": score, "analyze": analyze}
FLAG_CMDS = {"out": ("score", "analyze"), "jobs_unrecoverable": ("score", "analyze"), "infra_fix": ("run",),
             "canary_fixed": ("run",), "anchor": ("harness-change",), "redo": ("smoke",), "void_truncated": ("smoke",)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="GEN 確認集（prereg.md）")
    ap.add_argument("cmd", choices=list(CMDS))
    ap.add_argument("--out", type=Path, default=None, help="score／analyze：run/ 下的 run 目錄（預設 formal/）")
    ap.add_argument("--jobs-unrecoverable", action="store_true", help="score／analyze：缺漏的 job 確定補不到，照算並判作廢")
    ap.add_argument("--infra-fix", default=None, metavar="ANCHOR",
                    help="run：修基礎設施後續跑；值是 harness-change 記下的最後一筆錨點")
    ap.add_argument("--anchor", default=None, help="harness-change：執行紀錄裡新加的一整行")
    ap.add_argument("--canary-fixed", default=None, metavar="NOTE", help="run：canary 修好後重跑，先前的錯誤行不再計")
    ap.add_argument("--redo", default=None, metavar="ANCHOR",
                    help="smoke：作廢或截斷的 smoke 移到一旁重做；值是執行紀錄的錨點")
    ap.add_argument("--void-truncated", default=None, metavar="ANCHOR",
                    help="smoke：截斷且查無基礎設施原因，記作廢；值是執行紀錄的錨點")
    args = ap.parse_args(argv)
    for flag, cmds in FLAG_CMDS.items():
        if getattr(args, flag) not in (None, False) and args.cmd not in cmds:
            ap.error(f"--{flag.replace('_', '-')} is for {' and '.join(cmds)} only")
    if args.redo and args.void_truncated:
        ap.error("--redo and --void-truncated exclude each other")
    CMDS[args.cmd](args)


if __name__ == "__main__":
    import run_g                                     # smoke_g imports run_g: the command runs in that one module
    run_g.main()
