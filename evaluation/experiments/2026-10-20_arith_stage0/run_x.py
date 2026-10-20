"""Driver of the ordered-chain arithmetic stage-0 (prereg §1, §6, §11). Host python -B (the evaluation venv).

    python -B run_x.py build      # gen_layer, items, cards, jobs, arms_meta (store) and k0.json: K0-1..4, K0-6 (CPU)
    python -B run_x.py dry-run    # the whole flow with the fake chat into dry_run/: run, score, analyze (CPU)
    python -B appendix_x.py       # the repo's appendix.md from the store build; then commit harness + appendix
    python -B run_x.py smoke      # K0-5: 2 items per family × every arm × 1, token counts only (Ollama)
    python -B run_x.py run [--infra-fix ANCHOR]   # the formal run into formal/, resumable (Ollama)
    python -B run_x.py score   [--out DIR] [--jobs-unrecoverable]   # DIR/scores.json (default formal/; dry_run/
                                             # too, never smoke/)
    python -B run_x.py analyze [--out DIR] [--jobs-unrecoverable] [--pilot-authorized DYN=yes|no,GEN=yes|no]
                               [--pilot FILE]   # DIR/report.json, DIR/report.md (analyze_x)

Every output lies under the store's reports/arith_stage0_20261020/ (x_common.cli_out). ``build`` writes the
data files only when every K0 check passes (k0.json is always written), never over a differing earlier
build and never once a formal run exists. Each kind of run has one directory (dry_run/, smoke/, formal/)
and run_meta.json names its kind: a dry run never counts as formal, a directory never takes another kind,
job list, options, model, inputs or harness, and a void run is never resumed. A session holds an exclusive
lock on its directory (run.lock): a second run there is refused. Generation goes through
cards_common.run_jobs (3 rounds; an Ollama exception is retried, never a result); dry runs and tests swap
cards_common.chat for a fake only inside ``execute``. A last line of the generations cut by a kill is moved
to gen_arms.torn.jsonl (its job is redone) and recorded in run_meta.torn. A run whose jobs are all answered
and whose last after-check agrees opens no new session. Before and after every session: the model digest
from /api/ps (else /api/tags) must be x_common.EXPECTED_DIGEST and /api/version is recorded; before, no
other model may be loaded (§9 獨佔). Every check of a run has that digest and the version of its first
check (§1); a before-check that differs is refused before any call, and voids the run when it stands in
for the after-check of a session that has none (``report_segments``). The formal run's version must be
the smoke's. smoke and run refuse unless prereg.md carries no draft mark, prereg.md, every harness file
and every test file of this experiment are committed and unchanged, experiment A's frozen files and the
input pins match, k0.json passes and names the store files, a fresh build gives the same files and
appendix.md is appendix_x's for them; run also needs a passed smoke of the same jobs. The harness pin
covers prereg.md above its 「## 執行紀錄」 only (the log is append-only). An infrastructure fix between
formal sessions resumes with ``run --infra-fix "<anchor of its 執行紀錄 entry>"``: jobs, options, model and
inputs stay the run's, a fresh in-memory K0 must pass with k0.json's store files, and the change is kept
in run_meta.harness_history. A smoke truncation voids the experiment (§1); missing jobs after 3 rounds stop
the run for an infrastructure fix and a resume, and score/analyze refuse such a run (and an unfinished or
unknown one) unless --jobs-unrecoverable says the jobs cannot be done (the report is then 作廢). Only
counts, ids and sha256 values are printed.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arms_x as A  # noqa: E402
import engine_x as E  # noqa: E402
import gen_layer as G  # noqa: E402
import items_x as I  # noqa: E402
import keys_x as K  # noqa: E402
import score_x as S  # noqa: E402
import x_common as X  # noqa: E402
from score_a import truncated  # noqa: E402

cc = X.cc
# Ollama unreachable or failing, a broken HTTP exchange, an unreadable or unexpected body
CHECK_ERRORS = (OSError, ValueError, http.client.HTTPException, AttributeError)
DATA_FILES = ("gen_layer.json", "items.json", "cards.json", "jobs.json", "arms_meta.json")
K0_FILE, SMOKE_FILE, RUN_META, GEN = "k0.json", "smoke.json", "run_meta.json", S.GEN_ARMS[0]
TORN, LOCK = "gen_arms.torn.jsonl", "run.lock"      # a cut last line of GEN goes to TORN (never scored)
KINDS = ("dry_run", "smoke", "formal")
SMOKE_PER_FAMILY = 2
K0_TESTS = ("evaluation/tests/test_arith_stage0_keys.py", "evaluation/tests/test_arith_stage0_score.py")
K0_4_GAINED = {"QJ1s2a2": 8, "QJ3s2a1": 1}       # prereg K0-4: the 9 bare-number answers that become correct


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def store(name: str) -> Path:
    return Path(X.OUT_ROOT) / name


def run_dir(kind: str) -> Path:
    return store(kind)


def code_sha256() -> dict:
    """The harness and test files' sha256 (x_common.harness_files_sha256) without appendix.md (which lists
    k0.json's sha and so cannot be in it)."""
    return {n: v for n, v in X.harness_files_sha256().items() if n != "appendix.md"}


def doc_sha(obj) -> str:
    """sha256 of the file x_common.write_json writes for obj."""
    return X.sha256_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


# ---------------------------------------------------------------- build (CPU)
def build_docs(text_dir=X.TEXT) -> dict:
    """{file name: document} of a fresh build: the Genesis layer, the items, the cards, the jobs, the arms meta."""
    gen = G.build(text_dir)
    idoc = I.build_items(gen=gen)
    cards = A.build_cards(idoc["items"], gen)
    jobs, meta = A.build_arms(idoc["items"], cards)
    cards_doc = {"schema": A.SCHEMA_CARDS, "items_sha256": I.items_sha256(idoc), "gen_layer_sha256": G.sha256(gen),
                 "r4_sha256": X.R4_LAYER_SHA256, "cap_chars": X.CAP_CHARS, "cards": cards}
    meta_doc = {"schema": "arith.arms_meta.v1", "summary": A.summary(jobs), "meta": meta}
    return {"gen_layer.json": gen, "items.json": idoc, "cards.json": cards_doc, "jobs.json": jobs,
            "arms_meta.json": meta_doc}


def k0_tests(repo: Path = X.REPO) -> dict:
    """K0-4 合成測試: the keys and score test files, run by pytest (timing stripped from the summary), with
    the sha256 of the files run (k0.json pins them; the git gate wants them committed)."""
    files_sha = {f: X.sha256_file(Path(repo) / f) for f in K0_TESTS}
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", *K0_TESTS, "-q", "-p", "no:cacheprovider"],
                       cwd=repo, capture_output=True, text=True)
    last = next((ln for ln in reversed(r.stdout.splitlines()) if ln.strip()), "")
    return {"files": list(K0_TESTS), "files_sha256": files_sha, "returncode": r.returncode,
            "summary": re.sub(r" in [0-9.]+s.*$", "", last).strip("= "), "pass": r.returncode == 0}


def _fails(d: dict) -> dict:
    return {k: v for k, v in d.items() if v}


def k0_regress() -> dict:
    """K0-4 on experiment A's stored records: no correct key lost, no record score down, exactly the 9 gained."""
    r = S.regress_a()
    gained = Counter(t.split("|")[1] for t in r["gained"])
    return {**{k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}, "gained_items": dict(gained),
            "lost_tags": r["lost"], "score_down_tags": r["score_down"],
            "pass": not r["lost"] and not r["score_down"] and dict(gained) == K0_4_GAINED}


def k0_checks(docs: dict, run_tests=k0_tests, regress=k0_regress) -> dict:
    """prereg §6 K0-1..4 and K0-6 on a build (K0-5 is the smoke); every section has "pass"."""
    gen, idoc = docs["gen_layer.json"], docs["items.json"]
    items, cards = idoc["items"], docs["cards.json"]["cards"]
    meta, jobs = docs["arms_meta.json"]["meta"], docs["jobs.json"]
    dyn = [it for it in items if it["family"] != "GEN"]
    gn = [it for it in items if it["family"] == "GEN"]
    k01 = _fails({it["id"]: I.k0_fields(it) + I.verify_gold(it) for it in dyn})
    layer, k02 = G.check(gen), _fails({it["id"]: I.verify_gold(it) for it in gn})
    out = {"schema": "arith.k0.v1",
           "K0_1": {"pass": not k01, "n_items": len(dyn), "problems": k01},
           "K0_2": {"pass": not layer and not k02, "n_items": len(gn), "layer_problems": layer,
                    "layer_checks": gen["checks"], "gold_problems": k02}}
    k03 = {}
    for part, its in (("dynasty", dyn), ("genesis", gn)):
        lines = _fails({it["id"]: E.check_lines(it, cards[it["id"]], gen) for it in its})
        unc = [it["id"] for it in its if not cards[it["id"]]["covered"]]
        k03[part] = {"pass": not lines and not unc, "a": f"{len(its) - len(unc)}/{len(its)}", "uncovered": unc,
                     "line_problems": lines}
    out["K0_3"] = {"pass": all(p["pass"] for p in k03.values()), **k03}
    copies = {it["id"]: K.copy_cases(it, cards[it["id"]]) for it in items}
    bad_copies = _fails({i: [c for c in cs if c["got"] != c["want"]] for i, cs in copies.items()})
    tests, reg = run_tests(), regress()
    out["K0_4"] = {"pass": tests["pass"] and not bad_copies and reg["pass"], "tests": tests,
                   "copy_cases": {"n": sum(map(len, copies.values())), "mismatch": bad_copies},
                   "f3_echo": K.f3_echo_table(), "regress_a": reg}
    k06, jp = A.card_problems(items, cards, meta), A.job_problems(items, jobs)
    chars = {a: max((m["block_chars"][a] for m in meta.values() if a in m["block_chars"]), default=None)
             for a in ("G", "T-rows", "T-canon", "B0", X.B0_BARE)}
    out["K0_6"] = {"pass": not k06 and not jp, "problems": k06, "job_problems": jp, "block_chars_max": chars,
                   "cap": X.CAP_CHARS}
    item_checks = _fails(idoc["checks"])
    out["items"] = {"pass": not item_checks, "n_items": len(items), "problems": item_checks}
    out["pins"], out["frozen"] = X.check_pins(), X.frozen_problems()
    sections = ("K0_1", "K0_2", "K0_3", "K0_4", "K0_6", "items")
    out["pass"] = all(out[s]["pass"] for s in sections) and not out["pins"] and not out["frozen"]
    out["sha256"] = {name: doc_sha(obj) for name, obj in docs.items()}
    out["prompts_sha256"] = A.prompts_sha256(jobs)
    out["harness_sha256"] = code_sha256()
    return out


def build(_args=None, *, run_tests=k0_tests, regress=k0_regress, log=print) -> dict:
    if (run_dir("formal") / RUN_META).exists():
        raise SystemExit("a formal run exists: its inputs are frozen, build is refused")
    docs = build_docs()
    differ = [n for n, obj in docs.items() if store(n).exists() and X.sha256_file(store(n)) != doc_sha(obj)]
    if differ:
        raise SystemExit(f"{differ} exist in the store and differ from this build: not overwritten (nothing written)")
    k0 = k0_checks(docs, run_tests, regress)
    X.write_json(X.cli_out(store(K0_FILE)), k0)
    if not k0["pass"]:
        failed = [s for s in ("K0_1", "K0_2", "K0_3", "K0_4", "K0_6", "items") if not k0[s]["pass"]]
        raise SystemExit(f"K0 failed {failed} (pins {k0['pins']}, frozen {k0['frozen']}): data files not written")
    G.write(docs["gen_layer.json"], X.cli_out(store("gen_layer.json")))
    I.write(docs["items.json"], X.cli_out(store("items.json")))
    for n in ("cards.json", "jobs.json", "arms_meta.json"):
        X.write_json(X.cli_out(store(n)), docs[n])
    log({"n_items": docs["items.json"]["n_items"], "n_jobs": len(docs["jobs.json"]), "k0": "pass",
         "prompts_sha256": k0["prompts_sha256"]})
    return k0


def load_inputs(require_pass: bool = True) -> dict:
    """The store build ({file name: document}, plus k0.json), each file's sha256 checked against k0.json."""
    if not store(K0_FILE).is_file():
        raise SystemExit(f"{store(K0_FILE)} missing: run build first")
    k0 = X.read_json(store(K0_FILE))
    if require_pass and not k0.get("pass"):
        raise SystemExit("k0.json does not pass")
    out = {K0_FILE: k0}
    for n in DATA_FILES:
        p = store(n)
        if not p.is_file() or X.sha256_file(p) != (k0.get("sha256") or {}).get(n):
            raise SystemExit(f"{p} missing or not the file k0.json names")
        out[n] = X.read_json(p)
    return out


def inputs_sha() -> dict:
    return {n: X.sha256_file(store(n)) for n in (*DATA_FILES, K0_FILE)}


# ---------------------------------------------------------------- Ollama checks
def api_get(path: str) -> dict:
    with urllib.request.urlopen(cc.OLLAMA + path, timeout=30) as resp:
        return json.loads(resp.read())


def _is_model(m: dict) -> bool:
    return X.MODEL in (m.get("name"), m.get("model"))


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
    out = [] if c["digest"] == X.EXPECTED_DIGEST else [f"model digest {c['digest']} ({c['where']}) is not {X.EXPECTED_DIGEST}"]
    if c["version"] is None:
        out.append("/api/version did not answer")
    if c["others"] is None or c["others"]:
        out.append(f"Ollama is not ours alone: /api/ps lists {c['others']}")
    return out


def run_state(meta: dict) -> tuple[str, list[str]]:
    """("void" | "unfinished" | "unknown" | "ok", why void): a digest other than the expected one or a version
    other than the first voids the run; no after-check since the last start = unfinished; an after-check
    that got no answer = unknown (resume to check again)."""
    checks = meta.get("checks") or []
    why = [f"{c['when']} {c['t']}: digest {c['digest']}" for c in checks
           if c["digest"] is not None and c["digest"] != X.EXPECTED_DIGEST]
    versions = [c["version"] for c in checks if c["version"] is not None]
    why += [f"Ollama version {v} after {versions[0]}" for v in dict.fromkeys(versions[1:]) if v != versions[0]]
    if why:
        return "void", why
    if not checks or checks[-1]["when"] != "after":
        return "unfinished", []
    last = checks[-1]
    return ("unknown" if last["digest"] is None or last["version"] is None else "ok"), []


def closed(check: dict) -> bool:
    """An after-check that got an answer (digest and version): the session it ends needs no stand-in."""
    return check["when"] == "after" and check["digest"] is not None and check["version"] is not None


# ---------------------------------------------------------------- runs
def harness_pins() -> dict:
    files = X.harness_files_sha256()
    return {"files_sha256": files, "sha256": X.sha256_text(json.dumps(files, sort_keys=True))}


def harness_change(old: dict, new: dict, note: str) -> dict:
    """A run_meta.harness_history entry: when, from and to which harness sha, the files changed, the
    執行紀錄 anchor and the git HEAD."""
    a, b = old["files_sha256"], new["files_sha256"]
    head = _git(X.REPO, "rev-parse", "HEAD").stdout.strip() or None
    return {"t": now(), "from": old["sha256"], "to": new["sha256"],
            "files": sorted(n for n in a.keys() | b.keys() if a.get(n) != b.get(n)), "note": note, "git_head": head}


def guard(out: Path, kind: str, sha: str, n_jobs: int, pins: dict, infra_fix: str | None = None) -> dict:
    """The run_meta to resume or start in out; refuses another kind, job list, options, model, inputs or
    harness (dry runs excepted for the harness; a resumed formal run takes a changed harness only with
    infra_fix, the 執行紀錄 anchor, kept in harness_history), a void run and outputs without run_meta."""
    meta_p = out / RUN_META
    if infra_fix is not None and kind != "formal":
        raise SystemExit("--infra-fix is for resuming the formal run only")
    if meta_p.exists():
        old = X.read_json(meta_p)
        if old.get("kind") != kind:
            raise SystemExit(f"{out} is a {old.get('kind')} directory, not {kind}")
        same = (old["jobs_sha256"], old["options"], old["model"], old["inputs_sha256"]) == \
               (sha, dict(X.OPTIONS), X.MODEL, pins["inputs_sha256"])
        if not same:
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
                    "harness_history": old.get("harness_history", []) + [harness_change(old["harness"], pins["harness"],
                                                                                        infra_fix)]}
        return {**keep, "resumed": old.get("resumed", []) + [now()]}
    if infra_fix is not None:
        raise SystemExit(f"--infra-fix resumes a formal run: {meta_p} does not exist")
    if (out / GEN).exists():
        raise SystemExit(f"{out / GEN} exists without {RUN_META}")
    return {"kind": kind, "jobs_sha256": sha, "n_jobs": n_jobs, "options": dict(X.OPTIONS), "model": X.MODEL,
            "expected_digest": X.EXPECTED_DIGEST, **pins, "started": now(), "checks": [], "resumed": []}


@contextlib.contextmanager
def run_lock(out: Path):
    """An exclusive flock on out/run.lock for one session: a second run on the same directory is refused."""
    out.mkdir(parents=True, exist_ok=True)
    with X.cli_out(out / LOCK).open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"{out / LOCK}: another run holds this directory; refused") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def repair_tail(p: Path, side: Path) -> dict | None:
    """A last line cut by a kill (no final newline): unparsable, it is appended to side and cut off p (its job
    is redone); parsable, its newline is added. Any other unparsable line is left (done_jobs raises)."""
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if not raw or raw.endswith(b"\n"):
        return None
    head, nl, tail = raw.rpartition(b"\n")
    try:
        json.loads(tail)
    except ValueError:                                  # JSONDecodeError and UnicodeDecodeError
        with X.cli_out(side).open("ab") as f:
            f.write(tail + b"\n")
        with p.open("r+b") as f:
            f.truncate(len(head) + len(nl))
        return {"action": "moved_to_side", "bytes": len(tail)}
    with p.open("ab") as f:
        f.write(b"\n")
    return {"action": "newline_added", "bytes": len(tail)}


def repair_torn(out: Path, meta: dict, log=print) -> dict:
    """repair_tail on out's generations, recorded at once in run_meta.json's "torn" (and in meta)."""
    fix = repair_tail(out / GEN, out / TORN)
    if fix is None:
        return meta
    rec = {"t": now(), **fix}
    log(f"torn last line of {GEN}: {fix['action']} ({fix['bytes']} bytes)")
    disk = X.read_json(out / RUN_META)
    X.write_json(out / RUN_META, {**disk, "torn": disk.get("torn", []) + [rec]})
    return {**meta, "torn": meta.get("torn", []) + [rec]}


def refuse_before_call(out: Path, meta: dict, before: dict, want_version: str | None) -> None:
    """Raise unless the before-check agrees with the run's earlier checks (digest and version, run_state), has
    no before_problems and, for the formal run, has the smoke's version. A disagreeing check that stands in
    for the after-check of a session without an answered one (report_segments) is recorded: the run is void."""
    state, why = run_state({**meta, "checks": meta["checks"] + [before]})
    if state == "void":
        if meta["checks"] and not closed(meta["checks"][-1]):
            X.write_json(out / RUN_META, {**X.read_json(out / RUN_META), **meta, "checks": meta["checks"] + [before],
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
    """cards_common.run_jobs with ``fn`` in place of cards_common.chat (None: the real chat)."""
    if fn is None:
        yield
        return
    old = cc.chat
    cc.chat = fn
    try:
        yield
    finally:
        cc.chat = old


def execute(out: Path, jobs: list[dict], kind: str, *, chat=None, get=None, log=print, infra_fix: str | None = None,
            want_version: str | None = None) -> dict:
    """One session of a run: lock, guard, torn-line repair, before-check (refuse_before_call), cards_common.run_jobs,
    after-check; returns run_meta. Every job answered and an agreeing last after-check: no session (no call,
    no check), run_meta as it is."""
    if kind not in KINDS:
        raise ValueError(kind)
    out, get = X.cli_out(out), get or api_get
    sha = A.prompts_sha256(jobs)
    with run_lock(out):
        meta = guard(out, kind, sha, len(jobs), {"inputs_sha256": inputs_sha(), "harness": harness_pins()}, infra_fix)
        meta = repair_torn(out, meta, log)
        if run_state(meta)[0] == "ok" and all(j["job_id"] in cc.done_jobs(out / GEN) for j in jobs):
            log("nothing to do: every job is answered and the last after-check agrees; no new session")
            return X.read_json(out / RUN_META)
        before = ollama_check(get, "before")
        refuse_before_call(out, meta, before, want_version)
        meta = {**meta, "checks": meta["checks"] + [before]}
        X.write_json(out / "jobs.json", jobs)
        X.write_json(out / RUN_META, meta)
        with chat_as(chat):
            done = cc.run_jobs(jobs, X.cli_out(out / GEN), log=log, options=dict(X.OPTIONS))
        meta = {**meta, "checks": meta["checks"] + [ollama_check(get, "after")]}
        missing = [j["job_id"] for j in jobs if j["job_id"] not in done]
        state, why = run_state(meta)
        meta = {**meta, "n_done": len(jobs) - len(missing), "missing": missing, "state": state, "void": why,
                "error_lines": sum(r.get("type") == "error" for r in X.jsonl(out / GEN)), "finished": now()}
        X.write_json(out / RUN_META, meta)
        return meta


def run_meta(d: Path) -> dict:
    p = d / RUN_META
    if not p.is_file():
        raise SystemExit(f"{p} missing: not a run directory")
    return X.read_json(p)


# ---------------------------------------------------------------- gates before Ollama
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def git_problems(prereg: Path = X.PREREG, harness_dir: Path = X.HERE, tests_dir: Path = X.TESTS_DIR) -> list[str]:
    """prereg.md committed and unchanged; no edited or untracked file in the harness directory or among the
    experiment's test files (x_common.TESTS_GLOB, the K0-4 tests included)."""
    out = []
    if _git(prereg.parent, "ls-files", "--error-unmatch", prereg.name).returncode != 0:
        out.append("prereg.md not committed")
    elif _git(prereg.parent, "diff", "--quiet", "HEAD", "--", prereg.name).returncode != 0:
        out.append("prereg.md changed since the last commit")
    st = _git(harness_dir, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if st.returncode != 0 or st.stdout.strip():
        out.append("harness files changed or untracked since the last commit")
    ts = _git(tests_dir, "status", "--porcelain", "--untracked-files=all", "--", X.TESTS_GLOB)
    if ts.returncode != 0 or ts.stdout.strip():
        out.append("test files changed or untracked since the last commit")
    return out


def infra_fix_problems(prereg: Path, note: str, k0: dict, docs: dict, *, run_tests=k0_tests,
                       regress=k0_regress) -> list[str]:
    """run --infra-fix "<anchor>": the anchor is in prereg.md's 執行紀錄, a formal run exists to resume, and a
    fresh in-memory K0 (K0-1..4, K0-6 on the harness as it is now) passes with k0.json's store files."""
    out = []
    if not note.strip() or note.strip() not in X.prereg_log_text(prereg.read_text(encoding="utf-8")):
        out.append("--infra-fix: the anchor is not in prereg.md's 執行紀錄")
    if not (run_dir("formal") / RUN_META).is_file():
        out.append("--infra-fix resumes a formal run and there is none (before it starts, rerun build)")
    fresh = k0_checks(docs, run_tests, regress)
    if not fresh["pass"]:
        failed = [s for s in ("K0_1", "K0_2", "K0_3", "K0_4", "K0_6", "items") if not fresh[s]["pass"]]
        out.append(f"--infra-fix: a fresh K0 on the harness as it is now fails {failed} "
                   f"(pins {fresh['pins']}, frozen {fresh['frozen']})")
    if fresh["sha256"] != k0.get("sha256"):
        out.append("--infra-fix: a fresh K0 names other store files than k0.json")
    return out


def gate_problems(prereg: Path = X.PREREG, infra_fix: str | None = None, *, run_tests=k0_tests,
                  regress=k0_regress) -> list[str]:
    """Why no Ollama call may be made yet (empty = smoke may run). With infra_fix (a resumed formal run after
    an infrastructure fix) a fresh K0 stands in for k0.json's harness pin (infra_fix_problems)."""
    import appendix_x
    out = ["prereg.md carries the draft mark"] if X.DRAFT_MARK in prereg.read_text(encoding="utf-8") else []
    out += git_problems(prereg)
    out += [f"experiment A frozen: {p}" for p in X.frozen_problems()] + [f"pin: {p}" for p in X.check_pins()]
    try:
        inp = load_inputs()
    except SystemExit as e:
        return out + [str(e)]
    docs = build_docs()
    fresh = {n: doc_sha(obj) for n, obj in docs.items()}
    out += [f"{n}: a fresh build differs from the store" for n in DATA_FILES if fresh[n] != inp[K0_FILE]["sha256"][n]]
    if infra_fix is not None:
        out += infra_fix_problems(prereg, infra_fix, inp[K0_FILE], docs, run_tests=run_tests, regress=regress)
    elif inp[K0_FILE].get("harness_sha256") != code_sha256():
        out.append("k0.json was built with other harness files: rerun build")
    out += [f"appendix: {p}" for p in appendix_x.check()]
    return out


def smoke_jobs(items: list[dict], jobs: list[dict], meta: dict) -> list[dict]:
    """prereg §1 smoke: per family the 2 items with the longest G prompt (ties: item order), every arm, rep 1."""
    keep = set()
    for fam in X.ARMS:
        its = [it for it in items if it["family"] == fam]
        its = sorted(its, key=lambda it: -meta[it["id"]]["user_chars"]["G"])[:SMOKE_PER_FAMILY]
        keep |= {it["id"] for it in its}
    return [j for j in jobs if j["item"] in keep and j["rep"] == 1]


def smoke_status(d: Path, jobs: list[dict], meta: dict) -> dict:
    """Token counts only (never an answer): truncated (score_a.truncated at num_ctx) = void (§1)."""
    recs = cc.done_jobs(d / GEN)
    nc = X.OPTIONS["num_ctx"]
    tok = {j["job_id"]: {k: recs[j["job_id"]].get(k) for k in ("prompt_eval_count", "eval_count", "done_reason")}
           for j in jobs if j["job_id"] in recs}
    trunc = sorted(i for i in tok if truncated(recs[i], nc))
    used = [(t["prompt_eval_count"] or 0) + (t["eval_count"] or 0) for t in tok.values()]
    state = meta["state"]
    return {"kind": "smoke", "n_jobs": len(jobs), "jobs_sha256": A.prompts_sha256(jobs), "num_ctx": nc,
            "missing": meta["missing"], "truncated": trunc, "state": state, "void_why": meta["void"],
            "max_prompt_eval": max((t["prompt_eval_count"] or 0 for t in tok.values()), default=None),
            "max_eval": max((t["eval_count"] or 0 for t in tok.values()), default=None),
            "max_prompt_plus_eval": max(used, default=None), "tokens": tok,
            "void": bool(trunc) or state == "void",
            "pass": not trunc and not meta["missing"] and state == "ok"}


def smoke_problems(items: list[dict], jobs: list[dict], meta: dict) -> list[str]:
    p = run_dir("smoke") / SMOKE_FILE
    if not p.is_file():
        return ["no smoke yet (K0-5)"]
    st = X.read_json(p)
    if st.get("void"):
        return [f"the smoke voided the experiment (truncated {st['truncated']}, state {st['state']})"]
    if not st.get("pass"):
        return [f"smoke not passed (missing {len(st['missing'])}, state {st['state']}): resume smoke"]
    if st["jobs_sha256"] != A.prompts_sha256(smoke_jobs(items, jobs, meta)):
        return ["the smoke ran other jobs"]
    return []


def smoke(_args=None, *, get=None, log=print) -> dict:
    bad = gate_problems()
    if bad:
        raise SystemExit(f"smoke refused: {bad}")
    inp = load_inputs()
    d = run_dir("smoke")
    if (d / SMOKE_FILE).is_file() and X.read_json(d / SMOKE_FILE).get("void"):
        raise SystemExit("the smoke voided the experiment: not run again")
    jobs = smoke_jobs(inp["items.json"]["items"], inp["jobs.json"], inp["arms_meta.json"]["meta"])
    meta = execute(d, jobs, "smoke", get=get, log=log)
    st = smoke_status(d, jobs, meta)
    X.write_json(X.cli_out(d / SMOKE_FILE), st)
    log({k: st[k] for k in ("n_jobs", "missing", "truncated", "state", "max_prompt_plus_eval", "pass", "void")})
    return st


def smoke_version() -> str:
    """The Ollama version of the smoke's first check (every check of a passed smoke has it)."""
    return run_meta(run_dir("smoke"))["checks"][0]["version"]


def run(args=None, *, get=None, log=print) -> dict:
    fix = getattr(args, "infra_fix", None)
    bad = gate_problems(infra_fix=fix)
    inp = None if bad else load_inputs()
    if inp:
        bad += smoke_problems(inp["items.json"]["items"], inp["jobs.json"], inp["arms_meta.json"]["meta"])
    if bad:
        raise SystemExit(f"formal run refused: {bad}")
    meta = execute(run_dir("formal"), inp["jobs.json"], "formal", get=get, log=log, infra_fix=fix,
                   want_version=smoke_version())
    log({k: meta[k] for k in ("n_jobs", "n_done", "state", "error_lines")} | {"missing": len(meta["missing"])})
    if meta["state"] == "void":
        raise SystemExit(f"作廢（全部，digest／Ollama 版本）：{meta['void']}")
    if meta["state"] == "unknown":
        raise SystemExit("the after-check got no answer from Ollama: run again (it resumes and checks again)")
    if meta["missing"]:
        raise SystemExit(f"{len(meta['missing'])} jobs missing after 3 rounds: fix the infrastructure, then run again "
                         "(resumes); if they cannot be done the run is void (prereg §1)")
    return meta


# ---------------------------------------------------------------- score and analyze
def scored_dir(out, jobs_unrecoverable: bool = False) -> tuple[Path, dict]:
    """The run directory to score or analyze: never the smoke, an unfinished or unknown run (resume it), or a
    finished run with missing jobs unless jobs_unrecoverable (they cannot be done: the report is 作廢)."""
    d = X.cli_out(out or run_dir("formal"))
    meta = run_meta(d)
    if meta["kind"] == "smoke":
        raise SystemExit("the smoke is never scored (token counts only)")
    state = run_state(meta)[0]
    if state in ("unfinished", "unknown"):
        raise SystemExit(f"{d}: the run is {state} (no answered after-check since the last start): resume it first")
    if jobs_unrecoverable and not meta.get("missing"):
        raise SystemExit(f"{d}: --jobs-unrecoverable, but no job is missing")
    if state == "ok" and meta.get("missing") and not jobs_unrecoverable:
        raise SystemExit(f"{d}: {len(meta['missing'])} jobs missing: fix the infrastructure and resume (prereg §1); "
                         "only if they cannot be done, pass --jobs-unrecoverable (the report is then 作廢)")
    if meta["inputs_sha256"] != inputs_sha():
        raise SystemExit(f"{d}: the store build is not the one this run used")
    return d, meta


def score(args=None) -> dict:
    unrec = bool(getattr(args, "jobs_unrecoverable", False))
    d, meta = scored_dir(getattr(args, "out", None), unrec)
    inp, jobs = load_inputs(), X.read_json(d / "jobs.json")
    if A.prompts_sha256(jobs) != meta["jobs_sha256"]:
        raise SystemExit(f"{d / 'jobs.json'} is not the job list of this run")
    gen_sha = X.sha256_file(d / GEN)
    doc = S.score_all(d, inp["items.json"], jobs, num_ctx=meta["options"]["num_ctx"])
    doc = {**doc, "run": {"dir": str(d), "kind": meta["kind"], "state": run_state(meta)[0],
                          "jobs_sha256": meta["jobs_sha256"], "gen_sha256": gen_sha, "jobs_unrecoverable": unrec}}
    X.write_json(X.cli_out(d / "scores.json"), doc)
    print({"kind": meta["kind"], "n_records": doc["n_records"], "missing": len(doc["missing_jobs"])})
    return doc


def k0_for_report(k0: dict, smoke: dict | None, kind: str) -> dict:
    """k0.json (and smoke.json for K0-5) in analyze_x's form: {"K0-n": {"pass"[, "dyn", "gen"]}}."""
    out = {f"K0-{n}": {"pass": k0[f"K0_{n}"]["pass"]} for n in (1, 2, 4, 6)}
    # analyze_x reads K0-3 by part ("pass" True = the record is there; "dyn"/"gen" void DYN-side or GEN only)
    out["K0-3"] = {"pass": True, "dyn": k0["K0_3"]["dynasty"]["pass"], "gen": k0["K0_3"]["genesis"]["pass"]}
    if smoke is not None:
        out["K0-5"] = {"pass": bool(smoke["pass"]) and not smoke["void"]}
    else:
        out["K0-5"] = {"pass": kind == "dry_run", "note": "no smoke" + ("（dry run 不需要）" if kind == "dry_run" else "")}
    return dict(sorted(out.items()))


def report_segments(meta: dict) -> list[dict]:
    """analyze_x's run_meta: one segment per session start; its after-values are the next check that got an
    answer (that session's after-check, else a later session's before- or after-check; None if none did)."""
    cs, out = meta.get("checks") or [], []

    def later(i: int, key: str):
        return next(((c[key], c["t"]) for c in cs[i + 1:] if c[key] is not None), (None, None))
    for i, c in enumerate(cs):
        if c["when"] == "before":
            (d, t), (v, _t) = later(i, "digest"), later(i, "version")
            out.append({"digest_before": c["digest"], "digest_after": d, "version_before": c["version"],
                        "version_after": v, "t_before": c["t"], "t_after": t, "dry_run": meta["kind"] == "dry_run"})
    return out


def pilot_args(auth: str | None, pilot: Path | None) -> tuple[dict | None, dict | None]:
    """--pilot-authorized DYN=yes,GEN=no (a family left out: Kay has not decided); --pilot a JSON
    {family: {"pR": "a/b", "gap": "a/b"}} of an authorized blind pilot."""
    out = None
    if auth:
        out = {}
        for part in auth.split(","):
            fam, _, v = part.partition("=")
            if fam not in X.JUDGED or v not in ("yes", "no"):
                raise SystemExit(f"--pilot-authorized {auth}: use DYN=yes|no,GEN=yes|no")
            out[fam] = v == "yes"
    return out, (X.read_json(pilot) if pilot else None)


def analyze(args=None, *, nsim: int | None = None) -> dict:
    """analyze_x.analyze on the run's scores → report.json, report.md (analyze_x.write_report)."""
    import analyze_x
    unrec = bool(getattr(args, "jobs_unrecoverable", False))
    d, meta = scored_dir(getattr(args, "out", None), unrec)
    if not (d / "scores.json").is_file():
        raise SystemExit(f"{d / 'scores.json'} missing: run score first")
    scores = X.read_json(d / "scores.json")
    run = scores.get("run") or {}
    if run.get("jobs_sha256") != meta["jobs_sha256"] or run.get("gen_sha256") != X.sha256_file(d / GEN):
        raise SystemExit(f"{d / 'scores.json'} is not this run's (job list or generations): run score again")
    inp, sp = load_inputs(), run_dir("smoke") / SMOKE_FILE
    auth, pilot = pilot_args(getattr(args, "pilot_authorized", None), getattr(args, "pilot", None))
    rep = analyze_x.analyze(scores, inp["items.json"], inp["arms_meta.json"]["meta"],
                            pilot_authorized=auth, pilot=pilot, jobs_unrecoverable=unrec, gen_dir=d,
                            k0=k0_for_report(inp[K0_FILE], X.read_json(sp) if sp.is_file() else None, meta["kind"]),
                            run_meta=report_segments(meta), records=cc.done_jobs(d / GEN),
                            **({"nsim": nsim} if nsim else {}))
    rep = {**rep, "run": {"dir": str(d), "kind": meta["kind"], "state": run_state(meta)[0]}}
    analyze_x.write_report(rep, X.cli_out(d))
    print({"kind": meta["kind"], "sentences": rep["sentences"]})
    return rep


# ---------------------------------------------------------------- dry run (fake chat)
def covering_line(item: dict, card: dict) -> str | None:
    """The first derived line holding the gold (engine_x.covered's rule), as the card writes it."""
    gold = item["gold"]
    classes = next((k["classes"] for k in item["keys"] if k["type"] == "arith"), ())
    for (h, p), tag in zip(card["lines"], card["tags"]):
        if (tag["kind"] == "succ" and tag["value"] == gold) if isinstance(gold, dict) else \
                (tag["unit"] in classes and tag["value"] == gold and str(gold) in p):
            return E.line_text(h, p)
    return None


def wrong_answer(item: dict) -> str:
    """A plausible wrong answer: the first distractor (else gold + 1) in the key's unit; SYNC: the (k−1)-th king."""
    gold = item["gold"]
    if isinstance(gold, dict):
        return f"{X.r4_view().nodes[item['path'][-2]]['name']}；{gold['Z']}"
    v = next((d["value"] for d in item.get("distractors") or []), gold + 1)
    return f"{v}{'歲' if item['keys'][0]['classes'][0] == 'A' else '年'}"


class FakeChat:
    """Dry runs and tests: G answers its card's covering derived line, every other arm a plausible wrong value.
    Token counts are made up (prompt = chars / 2, output 40, done_reason stop)."""

    def __init__(self, jobs: list[dict], items: list[dict], cards: dict):
        by_id = {it["id"]: it for it in items}
        self.answers, self.calls = {}, 0
        for j in jobs:
            it = by_id[j["item"]]
            ans = covering_line(it, cards[j["item"]]) if j["arm"] == "G" else wrong_answer(it)
            self.answers.setdefault(j["user"], ans)

    def __call__(self, system: str, user: str, options=None) -> dict:
        self.calls += 1
        return {"content": f"（假生成，無意義）\n答案：{self.answers.get(user) or '無法判斷'}", "thinking_chars": 0,
                "prompt_eval_count": len(user) // 2, "eval_count": 40, "done_reason": "stop", "elapsed_s": 0.0}


def fake_get(path: str) -> dict:
    if path == "/api/version":
        return {"version": "fake"}
    return {"models": [{"name": X.MODEL, "model": X.MODEL, "digest": X.EXPECTED_DIGEST}] if path == "/api/tags" else []}


def dry_run(_args=None, *, log=print, nsim: int | None = None) -> dict:
    """build's store files → jobs → fake generation → score → analyze, in dry_run/ (replaced each time)."""
    inp = load_inputs()
    d = X.cli_out(run_dir("dry_run"))
    if (d / RUN_META).exists() or (d / GEN).exists():
        if not (d / RUN_META).exists() or X.read_json(d / RUN_META).get("kind") != "dry_run":
            raise SystemExit(f"{d} is not a dry-run directory")
        for p in d.iterdir():
            if p.is_file() and p.name != LOCK:
                X.cli_out(p).unlink()
    items, jobs = inp["items.json"]["items"], inp["jobs.json"]
    chat = FakeChat(jobs, items, inp["cards.json"]["cards"])
    meta = execute(d, jobs, "dry_run", chat=chat, get=fake_get, log=lambda *_a: None)
    sc = score(argparse.Namespace(out=d))
    fam = {f: {a: (v or {}).get("float") for a, v in arms.items()} for f, arms in sc["families"].items()}
    rep = {"kind": "dry_run", "note": "假 chat；分數無意義，只驗流程", **A.summary(jobs), "fake_calls": chat.calls,
           "run_meta": {k: meta[k] for k in ("n_done", "missing", "state", "error_lines")},
           "families": fam, "fake_expectation": all(v == (1.0 if a == "G" else 0.0)
                                                     for arms in fam.values() for a, v in arms.items()),
           "missing_jobs": len(sc["missing_jobs"])}
    rr = analyze(argparse.Namespace(out=d), nsim=nsim)
    rep["analyze"] = {"dry_run": rr["dry_run"], "sentences": rr["sentences"]}
    X.write_json(X.cli_out(d / "dry_run_report.json"), rep)
    log({k: rep[k] for k in ("n_jobs", "fake_calls", "fake_expectation", "missing_jobs", "analyze")})
    return rep


CMDS = {"build": build, "dry-run": dry_run, "smoke": smoke, "run": run, "score": score, "analyze": analyze}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="有序鏈算術 stage-0（prereg.md）")
    ap.add_argument("cmd", choices=list(CMDS))
    ap.add_argument("--out", type=Path, default=None, help="score／analyze：store 下的 run 目錄（預設 formal/）")
    ap.add_argument("--pilot-authorized", default=None, help="analyze：Kay 對灰區族盲 pilot 的裁決，如 DYN=yes,GEN=no")
    ap.add_argument("--pilot", type=Path, default=None, help="analyze：已授權盲 pilot 的結果 JSON {族: {pR, gap}}")
    ap.add_argument("--jobs-unrecoverable", action="store_true",
                    help="score／analyze：缺漏的 job 確定補不到（§1），照算並判作廢")
    ap.add_argument("--infra-fix", default=None, metavar="ANCHOR",
                    help="run：修基礎設施後續跑正式跑；值是該修正在 prereg.md「執行紀錄」的錨點文字")
    args = ap.parse_args(argv)
    if args.out is not None and args.cmd not in ("score", "analyze"):
        ap.error("--out is for score and analyze only (each run kind has one directory)")
    if (args.pilot_authorized or args.pilot) and args.cmd != "analyze":
        ap.error("--pilot-authorized and --pilot are for analyze only")
    if args.jobs_unrecoverable and args.cmd not in ("score", "analyze"):
        ap.error("--jobs-unrecoverable is for score and analyze only")
    if args.infra_fix is not None and args.cmd != "run":
        ap.error("--infra-fix is for run only")
    CMDS[args.cmd](args)


if __name__ == "__main__":
    main()
