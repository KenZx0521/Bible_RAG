"""GEN confirmation set: the P1/P2 runner run_qg with a fake CLI or launcher (prereg §3.8 F1a, §5.4, §5.6 G1,
§8.1-3..5, §8.2; qset.md §3). The synthetic layer, specs and helpers are test_gen_confirm_qset's.

Nothing here launches claude or calls Ollama: launches run a fake ``claude`` (a python script written into a tmp
versions/ dir that turns each slot block of its user prompt into a made-up question and prints canned stream-json;
its config can append a simplified character once, a memory marker once, or a simplified character to one near-miss
family always) or a monkeypatched launcher that writes a consistent transcript; every root is a tmp dir. Covered:
P1 and P2 end to end (P2 after the F1a pins only, once, its records written in order and rewritten only as
themselves after a crash, totals only, an invalid near miss counted as fired, a blinding error voiding a whole job,
a GT trigger failing G1, the P2-path sha in every record); P2's refusals (a changed F1a or P2-path file, existing
records); one command per set at a time; a finished run without a draft recovered, never rerun; infrastructure
reruns counted across invocations; P1's spend kept below the P2 reserve; gen_done only when every job has a draft.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_gen_confirm_qset import CH5, CH11, H, question_for, specs, syn  # noqa: F401 (fixtures)

if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import analyze_g as AG  # noqa: E402
import claude_g as CL  # noqa: E402
import f1_g as F1  # noqa: E402
import g_common as GC  # noqa: E402
import hog_common as HC  # noqa: E402
import ledger_g as LG  # noqa: E402
import prompt_qg as Q  # noqa: E402
import run_qg as R  # noqa: E402
import spec_qg as S  # noqa: E402

FAKE_VERSION = "9.9.9"
FAKE_CLAUDE = r'''#!__PYTHON__
import fcntl, json, os, re, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("__VERSION__ (Claude Code)")
    sys.exit(0)
def arg(name):
    return args[args.index(name) + 1] if name in args else None
cfg = json.loads(os.environ.get("QTEST_FAKE") or "{}")
user, model = arg("-p"), arg("--model")
def emit(e):
    print(json.dumps(e, ensure_ascii=False), flush=True)
def question(body):
    q = re.search(r"^quantity: (.*)$", body, re.M).group(1)
    m = re.search(r"^people: X = ([^;\n]+)(?:; Y = (.+))?$", body, re.M)
    x, y = m.group(1), m.group(2)
    book = re.search(r"name the book (\S+?)\.", body)
    src = book.group(1) if book else "創世記"
    if y and q.startswith(x + "'s age, in years, in the year " + y + " was born"):
        t = x + "幾歲時，" + y + "出生"
    elif y and q.startswith(y + "'s age") and " died" in q:
        t = x + "去世那年，" + y + "幾歲"
    else:
        t = x + "是怎樣的人"
    mk = re.search(r"identifying phrase (\S+) exactly", body)
    if mk:
        t = t.replace(y, mk.group(1), 1) if mk.group(1).endswith(y) else t.replace(x, mk.group(1), 1)
    return src, t
def locked(fn):
    with open(cfg["state"] + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return fn()
def once(path):
    """True the first time any fake asks (under the lock)."""
    def go():
        if not path or os.path.exists(path):
            return False
        open(path, "w").write("1")
        return True
    return locked(go)
def worded(pairs):
    """A new wording for every repeat of one base text (a counter per text, under the lock)."""
    lead = ("依", "根據", "按", "照", "依照", "按照", "", "在")
    tail = ("？", "呢？", "啊？")
    def go():
        seen = json.load(open(cfg["state"])) if os.path.exists(cfg["state"]) else {}
        out = []
        for src, t in pairs:
            k = seen.get(t, 0)
            seen[t] = k + 1
            out.append(lead[k % 8] + src + ("中" if k % 8 >= 6 else "") + "，" + t + tail[k // 8 % 3])
        json.dump(seen, open(cfg["state"], "w"))
        return out
    return locked(go)
blocks = re.findall(r"^\[(q\d+)\]\n(.*?)(?=^\[q\d+\]|\Z)", user, re.M | re.S)
texts = worded([question(body) for _lab, body in blocks])
items = [{"slot": lab, "question": t} for (lab, _b), t in zip(blocks, texts)]
if once(cfg.get("bad_first")):
    items[0]["question"] += "这"
if once(cfg.get("marker_first")):
    for it in items:
        it["question"] += "gen_confirm"
for (lab, body), it in zip(blocks, items):
    if cfg.get("invalid_quantity") and re.search("^quantity: " + re.escape(cfg["invalid_quantity"]), body, re.M):
        it["question"] += "这"
emit({"type": "system", "subtype": "init", "cwd": os.getcwd(), "model": model, "claude_code_version": "__VERSION__",
      "tools": ["StructuredOutput"], "mcp_servers": [], "permissionMode": arg("--permission-mode")})
out = {"items": items}
emit({"type": "assistant", "message": {"usage": {"input_tokens": 9, "output_tokens": 30}, "content": [
    {"type": "tool_use", "id": "t1", "name": "StructuredOutput", "input": out}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": "done", "structured_output": out,
      "total_cost_usd": 0.01, "usage": {"input_tokens": 9, "output_tokens": 30}, "modelUsage": {model: {"costUSD": 0.01}}})
'''


@pytest.fixture
def env(tmp_path, monkeypatch, syn, specs):  # noqa: F811
    versions, out_root, cwd, home = (tmp_path / d for d in ("versions", "out", "srv", "home"))
    for d in (versions, out_root, cwd, home):
        d.mkdir()
    exe = versions / FAKE_VERSION
    exe.write_text(FAKE_CLAUDE.replace("__PYTHON__", sys.executable).replace("__VERSION__", FAKE_VERSION),
                   encoding="utf-8")
    exe.chmod(0o755)
    path, sha = CL.copy_cli(FAKE_VERSION, versions, out_root / "cli", HC.sha256_file(exe))
    pin = CL.CliPin(FAKE_VERSION, sha, str(path), True, dict(CL.MODELS))
    fake = {"bad_first": str(tmp_path / "bad.once"), "state": str(tmp_path / "wording.json")}
    monkeypatch.setenv("QTEST_FAKE", json.dumps(fake))
    group = {f"x/gencard/{n}.py": tmp_path / f"{n}.py" for n in ("a", "b")}
    p2_group = {f"x/{n}": tmp_path / n for n in ("run_x.py", "prompts_x.md")}
    for p in [*group.values(), *p2_group.values()]:
        p.write_text("# made up\n", encoding="utf-8")
    gt, gt2 = tmp_path / "gt.json", tmp_path / "gt2.json"                 # GT v1 and v2 stand-ins
    gt.write_text(json.dumps({"questions": [{"question": "誰是某甲？"}]}), encoding="utf-8")
    gt2.write_text(json.dumps({"questions": [{"question": "誰是某乙？"}]}), encoding="utf-8")

    def ctx(s: str) -> R.Ctx:
        return R.Ctx(s, specs[s], syn.names, syn.L, out_root, pin, Q.load(),
                     {"cwd": cwd, "home": home, "timeout_s": 60}, tmp_path / "f1a_pins.json", group, [gt, gt2],
                     lambda rc, rw, nv: 0.8 if rc / nv >= 0.7 else 0.1, p2_group)
    return SimpleNamespace(ctx=ctx, out_root=out_root, group=group, p2_group=p2_group, f1a=tmp_path / "f1a_pins.json",
                           tmp=tmp_path, gt=gt, gt2=gt2, fake=fake)


def _pin_f1a(env) -> None:
    GC.write_json(env.f1a, {"files": F1.sha_map(env.group), "p2_files": F1.sha_map(env.p2_group), "t": "x",
                            "git_head": None, "checks": {}})


def _shown(res, *ctxs) -> str:
    return json.dumps(res, ensure_ascii=False) + "".join(
        (c.root / n).read_text(encoding="utf-8") for c in ctxs for n in (R.SCORE_DONE,) if (c.root / n).is_file())


def _no_text(text: str, its) -> None:
    assert not any(i["question"] and i["question"] in text for i in its)
    assert not any(n in text for n in (r[1] for r in CH5 + CH11)) and not re.search(r"\bS\d\d\b", text)


def test_end_to_end_p1_with_the_fake_cli(env):
    c1 = env.ctx("p1")
    out = R.cmd_gen(c1)
    assert (out["started"], out["ok"], out["failed"], out["stopped"], out["jobs_left"]) == (24, 24, 0, 0, 0)
    assert R.cmd_gen(c1)["started"] == 0                                 # P1: only jobs without a draft run
    ref = R.cmd_refill(c1)
    assert (ref["refill_jobs"], ref["ok"]) == (1, 1) and R.cmd_refill(c1)["started"] == 0
    s1 = R.cmd_score(c1)
    assert s1["n_v"] == 50 and s1["items"]["pos"]["refilled"] + s1["items"]["near"]["refilled"] == 1
    assert (s1["R_card"], s1["R_wrong"], s1["near"]["fired"]) == (50, 0, 0)   # the fake's forms, all in scope
    R.cmd_score(c1)
    lines = (c1.root / "scores.jsonl").read_text(encoding="utf-8").splitlines()
    sha = json.loads(lines[0])["sha256"]
    assert len(lines) == 2 and set(sha["rules"]) == set(env.group) and sha["p2_files"] == F1.sha_map(env.p2_group)
    shown = R.cmd_show(c1)
    assert len(shown) == 70 and all(r["question"] for r in shown)
    led = json.loads((env.out_root / "ledger.json").read_text(encoding="utf-8"))
    assert led["by_kind"]["qset"] == pytest.approx(0.01 * 25) and led["by_kind"]["ho"] == 0


def test_end_to_end_p2_runs_once_writes_totals_only_and_survives_a_crash(env, syn, monkeypatch):  # noqa: F811
    c2 = env.ctx("p2")
    with pytest.raises(HC.HoError, match="f1a_pins.json missing"):
        R.cmd_gen(c2)
    _pin_f1a(env)
    monkeypatch.setenv("QTEST_FAKE", json.dumps({**env.fake, "bad_first": None, "marker_first": str(env.tmp / "mk"),
                                                 "invalid_quantity": "How many generations"}))
    out = R.cmd_gen(c2)
    assert (out["ok"], out["failed"]) == (23, 1) and (c2.root / R.GEN_DONE).is_file()   # one job voided (blinding)
    with pytest.raises(HC.HoError, match="runs once"):
        R.cmd_gen(c2)
    with pytest.raises(HC.HoError, match="needs refill_done"):
        R.cmd_score(c2)
    voided = next(j for j in c2.spec["jobs"] if not R.read_draft(c2, j["job_id"])["ok"])
    assert R.read_draft(c2, voided["job_id"])["blinding"][0]["rule"] == "t_memory"
    gens = {j["job_id"] for j in c2.spec["jobs"] if any(s.get("source") == "gens" for s in j["slots"])}
    ref = R.cmd_refill(c2)
    assert ref["refill_jobs"] == len({voided["job_id"]} | gens) and (c2.root / R.REFILL_DONE).is_file()
    f1a, f1b = [r for r in syn.pool if r["qtype"] == "F1"][:2]                # D18: m counts every GT trigger
    env.gt.write_text(json.dumps({"questions": [{"question": question_for(syn, f)} for f in (f1a, f1b)]}), encoding="utf-8")
    env.gt2.write_text(json.dumps({"questions": [{"question": question_for(syn, f1a)}]}), encoding="utf-8")

    real, boom = GC.write_json, []

    def crash_once(path, doc):
        if Path(path).name == R.NEAR_FILE and not boom:
            boom.append(path)
            raise OSError("disk full (test)")
        return real(path, doc)
    monkeypatch.setattr(GC, "write_json", crash_once)
    with pytest.raises(OSError, match="disk full"):
        R.cmd_score(c2)
    g1_sha = GC.sha256_file(c2.qset_root / R.G1_FILE)
    assert not (c2.root / R.SCORE_DONE).exists() and not (c2.qset_root / R.NEAR_FILE).exists()
    res = R.cmd_score(c2)                                                  # the rerun completes, g1.json unchanged
    assert GC.sha256_file(c2.qset_root / R.G1_FILE) == g1_sha
    with pytest.raises(HC.HoError, match="runs once"):
        R.cmd_score(c2)

    g1, near = GC.read_json(c2.qset_root / "g1.json"), GC.read_json(c2.qset_root / "p2_near_miss.json")
    its = R.items(c2)
    rows = [R.score_row(syn.L, i) for i in its]
    nr = [r for r in rows if r["kind"] == "near"]
    invalid, fired = sum(not r["valid"] for r in nr), sum(bool(r.get("fired")) for r in nr if r["valid"])
    assert set(near) == {"fired", "n"} and near["n"] == 20 and invalid >= 1 and near["fired"] == fired + invalid
    assert (res["near_invalid"], res["near_valid_fired"]) == (invalid, fired)
    pos = [r for r in rows if r["kind"] == "pos" and r["valid"]]
    assert g1["n_v"] == 50 and g1["R_card"] == sum(r["card"] for r in pos) and g1["R_wrong"] == 0
    assert not g1["pass"] and not g1["gt_zero_trigger"] and res["gt"] == {"gt.json": 2, "gt2.json": 1}  # G1 fails
    detail = "GT 觸發 3 次" if g1["g1"] >= 0.70 else f"R_card＝{g1['R_card']}/50，R_wrong＝0/50；GT 觸發 3 次"
    assert g1["sentence"] == AG.stop_sentence("G1", detail, "未出題")         # D18: the sentence names the GT nail
    assert g1["f1a_pins_sha256"] == GC.sha256_file(env.f1a) and g1["p2_spec_sha256"] == S.spec_sha(c2.spec)
    v = next(i for i in its if i["job"] == voided["job_id"] and i.get("source") != "gens")
    assert v["valid"] and v["refilled"] and v["first_violations"][0]["rule"] == "v_blind"
    score = GC.read_json(c2.root / R.SCORE_DONE)
    assert set(score) == {"t", "sha256", "totals", "gt", "items", "f1a_pins_sha256"}
    assert not re.search(r'"(by_|abstain|rates|invalid_by_rule)', json.dumps(score))
    for rec in (GC.read_json(c2.root / R.GEN_DONE), GC.read_json(c2.root / R.REFILL_DONE), score["sha256"]):
        assert rec["p2_files"] == F1.sha_map(env.p2_group)
    status = R.cmd_status(env.out_root, {"p1": env.ctx("p1"), "p2": c2})
    assert "invalid_by_rule" not in json.dumps(status["p2"])
    _no_text(_shown(res, c2) + json.dumps(g1, ensure_ascii=False) + json.dumps(status, ensure_ascii=False), its)
    with pytest.raises(HC.HoError, match="P1 only"):
        R.cmd_show(c2)


def test_p2_refuses_a_changed_pinned_file_and_existing_records(env):
    c2 = env.ctx("p2")
    _pin_f1a(env)
    next(iter(env.group.values())).write_text("# changed\n", encoding="utf-8")
    with pytest.raises(HC.HoError, match="sha256 differs"):
        R.cmd_gen(c2)
    _pin_f1a(env)
    next(iter(env.p2_group.values())).write_text("# the scorer edited after F1a\n", encoding="utf-8")
    for cmd in (R.cmd_gen, R.cmd_refill, R.cmd_score):
        with pytest.raises(HC.HoError, match="run_x.py: sha256 differs"):
            cmd(c2)
    GC.write_json(env.f1a, {"files": F1.sha_map(env.group)})
    with pytest.raises(HC.HoError, match="no p2_files map"):
        R.cmd_gen(c2)
    _pin_f1a(env)
    GC.write_json(c2.root / R.SCORE_DONE, {"x": 1})
    GC.write_json(c2.root / R.REFILL_DONE, {"x": 1})
    with pytest.raises(HC.HoError, match="score.json exists"):
        R.cmd_score(c2)
    with pytest.raises(HC.HoError, match="needs gen_done"):
        R.cmd_refill(c2)


def _fake_launcher(script, calls, gate=None):
    """A launcher that writes a consistent transcript and prompts record and returns script's next RunResult
    ("ok", "infra", "limit", "marker": a memory marker in the output) or raises its error; ``gate`` (two events)
    holds a launch until released."""
    def launch(kind, root, run_id, system, user, schema, cap, model, pin, **kw):
        calls.append((run_id, kw["user_scope"], kw["tools_mode"], kind, cap, kw.get("qset_limit_usd")))
        if gate is not None:
            gate[0].set()
            gate[1].wait(10)
        step = script(len(calls))
        if isinstance(step, Exception):
            raise step
        t = Path(root) / "transcripts" / f"{run_id}.jsonl"
        t.parent.mkdir(parents=True, exist_ok=True)
        labels = schema["properties"]["items"]["items"]["properties"]["slot"]["enum"]
        out = {"items": [{"slot": lab, "question": "某甲？" + ("gen_confirm" if step == "marker" else "")}
                         for lab in labels]}
        init = {"type": "system", "subtype": "init", "cwd": "/srv", "model": model, "tools": ["StructuredOutput"],
                "mcp_servers": [], "permissionMode": "dontAsk"}
        res = None if step == "infra" else {
            "type": "result", "subtype": "error_max_budget_usd" if step == "limit" else "success",
            "is_error": step == "limit", "result": "", "total_cost_usd": 0.0,
            "structured_output": None if step == "limit" else out}
        events = [init] + ([res] if res else [])
        t.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
        GC.write_json(Path(root) / "prompts" / f"{run_id}.json", {"model": model, "tools_mode": "none", "cwd": "/srv",
                                                                 "user_scope": "prompt", "budget_usd": cap})
        error, limit, fallback = CL.outcome(0, res, events, model, cap)
        return CL.RunResult(run_id, t, 0, 0.1, res, error, {}, limit, fallback, model, "none")
    return launch


def test_infra_failures_rerun_and_count_across_invocations(env):
    c1, calls = env.ctx("p1"), []
    job = c1.spec["jobs"][0]
    r = Q.render_job(job, c1.names)
    rec = R.run_job(c1, job, r, _fake_launcher(lambda n: "infra" if n < 3 else "ok", calls))
    assert len(rec["runs"]) == 3 and rec["ok"] and rec["output_run"] == f"{job['job_id']}_3"
    assert calls[0][1:] == ("prompt", "none", "qset", GC.QSET_JOB_CAP_USD["gen"], R.P1_LIMIT_USD)
    job2, calls2 = c1.spec["jobs"][1], []
    R.run_job(c1, job2, Q.render_job(job2, c1.names), _fake_launcher(lambda n: "infra", calls2))
    rec = R.run_job(c1, job2, Q.render_job(job2, c1.names), _fake_launcher(lambda n: "ok", calls2))
    assert len(calls2) == 3 and rec["runs"] == [] and not rec["ok"] and len(rec["prior_runs"]) == 3
    limit = R.run_job(c1, c1.spec["jobs"][2], Q.render_job(c1.spec["jobs"][2], c1.names), _fake_launcher(lambda n: "limit", []))
    assert len(limit["runs"]) == 1 and not limit["ok"] and limit["limit"] == "error_max_budget_usd"
    _pin_f1a(env)
    c2, calls3 = env.ctx("p2"), []
    R.run_job(c2, c2.spec["jobs"][0], Q.render_job(c2.spec["jobs"][0], c2.names), _fake_launcher(lambda n: "ok", calls3))
    assert calls3[0][-1] is None                                         # the P1 limit is P1's only


def test_a_finished_run_without_a_draft_is_recovered_never_rerun(env, monkeypatch):
    c1, calls = env.ctx("p1"), []
    job = c1.spec["jobs"][0]
    r = Q.render_job(job, c1.names)
    first = R.run_job(c1, job, r, _fake_launcher(lambda n: "infra" if n == 1 else "ok", calls))
    again = R.run_job(c1, job, r, _fake_launcher(lambda n: "ok", calls))  # the draft was never written (a crash)
    assert len(calls) == 2 and again["recovered_from"] == f"{job['job_id']}_2" and again["runs"] == []
    assert again["ok"] and again["output"] == first["output"] and first["recovered_from"] is None
    _fake_launcher(lambda n: "ok", [])("qset", c1.root, f"{job['job_id']}_3", "", "", r.schema, 0.2, "m", None,
                                       user_scope="prompt", tools_mode="none")
    with pytest.raises(HC.HoError, match="finished runs"):
        R.run_job(c1, job, r, _fake_launcher(lambda n: "ok", calls))      # two outputs: one job ran twice
    c2, real, calls2, hit = env.ctx("p2"), R.write_draft, [], []
    _pin_f1a(env)

    def crash_once(ctx, job, rec, r):
        if job["job_id"] == "p2-j02" and not hit:
            hit.append(1)
            raise OSError("killed (test)")
        return real(ctx, job, rec, r)
    monkeypatch.setattr(R, "write_draft", crash_once)
    with pytest.raises(OSError, match="killed"):
        R.cmd_gen(c2, _fake_launcher(lambda n: "ok", calls2))
    out = R.cmd_gen(c2, _fake_launcher(lambda n: "ok", calls2))
    assert len(calls2) == 24 and out["started"] == 1 and (c2.root / R.GEN_DONE).is_file()
    assert R.read_draft(c2, "p2-j02")["recovered_from"] == "p2-j02_1"


def test_one_command_per_set_at_a_time(env):
    c2, calls, gate = env.ctx("p2"), [], (threading.Event(), threading.Event())
    _pin_f1a(env)
    err: list = []
    t = threading.Thread(target=lambda: err.append(R.cmd_gen(c2, _fake_launcher(lambda n: "ok", calls, gate))))
    t.start()
    assert gate[0].wait(10)
    with pytest.raises(HC.HoError, match="run.lock"):
        R.cmd_gen(c2, _fake_launcher(lambda n: "ok", calls))
    with pytest.raises(HC.HoError, match="run.lock"):
        R.cmd_refill(c2, _fake_launcher(lambda n: "ok", calls))
    gate[1].set()
    t.join(30)
    assert err and err[0]["ok"] == 24 and len(calls) == len({c[0] for c in calls}) == 24


def test_p1_keeps_the_p2_reserve_in_the_qset_budget(env, monkeypatch):
    c1 = env.ctx("p1")
    led = LG.Ledger(env.out_root)
    for k in range(7):                                                     # 1.4 USD of P1 runs in flight
        led.reserve("qset", c1.root, f"held_{k}", 0.2)
    launched = []
    monkeypatch.setattr(R.CL, "launch", lambda *a, **k: launched.append(a[1]) or "ran")
    args = ("qset", c1.root, "p1-j00_1", "s", "u", {}, 0.2, "m", None)
    with pytest.raises(HC.BudgetRefused, match="P2"):
        R.reserved_launch(*args, user_scope="prompt", out_root=env.out_root, qset_limit_usd=R.P1_LIMIT_USD)
    assert not (c1.root / "reserve" / "p1-j00_1.json").exists()
    c2 = env.ctx("p2")
    assert R.reserved_launch("qset", c2.root, "p2-j00_1", "s", "u", {}, 0.2, "m", None, user_scope="prompt",
                             out_root=env.out_root) == "ran"
    assert (c2.root / "reserve" / "p2-j00_1.json").is_file() and R.P1_LIMIT_USD + R.P2_RESERVE_USD == GC.QSET_CAP_USD

    def fails(*a, **k):
        raise HC.CliUnavailable("no answer")
    monkeypatch.setattr(R.CL, "launch", fails)
    with pytest.raises(HC.CliUnavailable):
        R.reserved_launch("qset", c2.root, "p2-j01_1", "s", "u", {}, 0.2, "m", None, user_scope="prompt",
                          out_root=env.out_root)
    assert not (c2.root / "reserve" / "p2-j01_1.json").exists()           # released: nothing ran


def test_a_blinding_error_voids_the_run_output(env):
    c1 = env.ctx("p1")
    job = c1.spec["jobs"][0]
    rec = R.run_job(c1, job, Q.render_job(job, c1.names), _fake_launcher(lambda n: "marker", []))
    assert not rec["ok"] and rec["output"] is None and {v["rule"] for v in rec["blinding"]} == {"t_memory"}
    draft = {"ok": True, "output_run": rec["output_run"]}                  # even an ok-looking draft is re-checked
    assert {v.rule for v in R.blind_of(c1)(draft)} == {"t_memory"}


def test_unavailable_budget_and_changed_cli(env):
    c1, calls = env.ctx("p1"), []
    out = R.cmd_gen(c1, _fake_launcher(lambda n: HC.CliUnavailable("no answer"), calls))
    assert out["stopped"] == 24 and out["stopped_why"] == {"CliUnavailable": 24}
    assert not list((c1.root / R.DRAFTS).glob("*.json")) if (c1.root / R.DRAFTS).exists() else True
    assert R.cmd_gen(c1, _fake_launcher(lambda n: HC.BudgetRefused("cap"), []))["stopped_why"] == {"BudgetRefused": 24}
    calls = []
    with pytest.raises(HC.CliChanged, match="probe again"):
        R.cmd_gen(c1, _fake_launcher(lambda n: HC.CliChanged("another version"), calls))
    assert len(calls) <= GC.PARALLEL and not (c1.root / R.DRAFTS).exists()
    assert R.cmd_gen(c1, _fake_launcher(lambda n: "ok", []))["ok"] == 24


def test_p2_gen_done_waits_for_every_job(env):
    c2 = env.ctx("p2")
    _pin_f1a(env)
    out = R.cmd_gen(c2, _fake_launcher(lambda n: HC.CliUnavailable("no answer") if n <= 3 else "ok", []))
    assert (out["stopped"], out["jobs_left"]) == (3, 3) and not (c2.root / R.GEN_DONE).exists()
    with pytest.raises(HC.HoError, match="needs gen_done"):
        R.cmd_refill(c2, _fake_launcher(lambda n: "ok", []))
    assert R.cmd_gen(c2, _fake_launcher(lambda n: "ok", []))["started"] == 3 and (c2.root / R.GEN_DONE).is_file()
