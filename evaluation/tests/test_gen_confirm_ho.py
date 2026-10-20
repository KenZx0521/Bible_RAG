"""GEN confirmation set: the blind question-writing executor (prereg §2.3, §3, §8.1-7..10.4): state_g, runs_g, run_ho_g,
kay_g, freeze_g. No claude, no Ollama: claude_g.run_reserved is a scripted fake that takes the real ledger reservation,
writes the prompts record and a stream-json transcript as claude_g.launch would (transcript_g and ledger_g run on them
unchanged) and returns a RunResult from claude_g.outcome. Store files live in a tmp out root, the 執行紀錄 anchors in a
tmp prereg; chain, pool, names, questions and numbers are made up (test_gen_confirm_ho_edges.py's scan checks these
files against the text layer and the real question sets). Store tests skip when the store is not mounted and assert on
counts and booleans only (no scripture printed). The edge paths are in test_gen_confirm_ho_edges.py.
"""
from __future__ import annotations

import json
import random
import importlib
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import arms_g as A  # noqa: E402
import banned_g as B  # noqa: E402
import claude_g as CL  # noqa: E402
import freeze_g as FZ  # noqa: E402
import g_common as GC  # noqa: E402
import gencard  # noqa: E402
import kay_g as K  # noqa: E402
import ledger_g as L  # noqa: E402
import power_g as PW  # noqa: E402
import prompts_g as P  # noqa: E402
import run_ho_g as R  # noqa: E402
import runs_g as RU  # noqa: E402
import state_g as S  # noqa: E402
from hog_common import BudgetRefused, CliChanged, CliUnavailable, HoError  # noqa: E402

REAL_RUN_RESERVED, REAL_LAUNCH = CL.run_reserved, CL.launch
STAND_IN_CUES = ("出生", "去世", "幾歲", "嗎")
CH5 = ("柯梅", "柏羅丹", "茵德", "瓦勒", "梅洛撒蒂", "賽琳", "洛珊")
CH11 = ("歐芙", "葛林", "蘇倫", "泰朵", "魯斐")
CHAIN = [(f"Z05.{i:02d}", n, 5) for i, n in enumerate(CH5)] + [(f"Z11.{i:02d}", n, 11) for i, n in enumerate(CH11)]
# (qtype, chapter, x index, y index, marker required)
SLOTS = (("F1", 5, 0, 2, False), ("F1", 5, 1, 3, False), ("F1", 5, 2, 5, True), ("F1", 5, 3, 6, False),
         ("F1", 11, 0, 2, False), ("F1", 11, 0, 3, True), ("F1", 11, 1, 4, False), ("F5", 5, 0, 2, False),
         ("F5", 5, 0, 4, False), ("F5", 5, 1, 4, False), ("F5", 5, 2, 6, False), ("F5", 5, 3, 5, False),
         ("F5", 5, 1, 6, False), ("F5", 11, 0, 2, False), ("F5", 11, 1, 3, False), ("F5", 11, 2, 4, False))
ORDER = [f"S{k:02d}" for k in (0, 7, 13, 1, 8, 4, 2, 9, 14, 3, 10, 5, 11, 15, 6, 12)]
QID = {sid: S.qid_of(i) for i, sid in enumerate(ORDER, 1)}
SID = {q: s for s, q in QID.items()}
OK = lambda paths: []  # noqa: E731
G1_PASS = lambda rc, rw, nv, n: {"n": n, "pow_H1_and_H2": 0.9, "pass": True}  # noqa: E731
TEXT = GC.STORE / "layers/text/text@247eafe44b02/verse_units.jsonl"
needs_store = pytest.mark.skipif(not (TEXT.is_file() and GC.R4_LAYER.is_file()), reason="store not mounted")


def pool_rows() -> list[dict]:
    rows = []
    for k, (qt, ch, i, j, mk) in enumerate(SLOTS):
        p = [c[0] for c in CHAIN if c[2] == ch][i:j + 1]
        rows.append(dict(sid=f"S{k:02d}", qtype=qt, chapter=ch, stratum=f"{qt}c{ch}", d=len(p) - 1, x=p[0], y=p[-1],
                         pair=f"{p[0]}>{p[-1]}", persons=p, edges=[f"{p[t]}>{p[t + 1]}" for t in range(len(p) - 1)],
                         gold=4101 + 17 * k, marker_required=mk, homonym=mk, shem_x=False, coincide=False,
                         dup_gold=False))
    return rows


ROWS = {r["sid"]: r for r in pool_rows()}
NAMES_DOC = {"schema": "gen_confirm.gen_names.v1", "chain": [{"id": i, "name": n, "chapter": c} for i, n, c in CHAIN],
             "cain_line": ["卡斯", "茉妮"], "abram_family": ["多芮"], "extra_persons": ["卡斯", "茉妮", "多芮", "弗朗"],
             "other_books": ["路加"], "lexicon_blockers": ["瓦勒斯"]}
NAMES = P.Names.from_doc(NAMES_DOC)


def spec_of(qid: str) -> P.SlotSpec:
    return P.slot_spec(ROWS[SID[qid]], NAMES, qid)


def gold(qid: str) -> int:
    return ROWS[SID[qid]]["gold"]


def question(qid: str, variant: str = "") -> str:
    sp = spec_of(qid)
    y = sp.marker or sp.y
    q = f"就創世記來看，{y}出生那一年，{sp.x}幾歲？" if sp.qtype == "age_at_birth" else f"照創世記所記，{sp.x}去世的時候，{y}多大？"
    return q.replace("創世記", f"創世記{variant}") if variant else q


def item(qid: str, value: int | None = None, q: str | None = None) -> dict:
    sp = spec_of(qid)
    return {"id": qid, "slot": qid, "qtype": sp.qtype, "X": sp.x, "Y": sp.y, "marker": sp.marker,
            "question": q or question(qid), "answer": {"value": gold(qid) if value is None else value, "unit": "歲"},
            "steps": [{"person": sp.x, "fact": f"{qid} fact one", "verse": "gen.5.3"},
                      {"person": sp.y, "fact": f"{qid} fact two", "verse": "gen.5.6"}],
            "convention": "", "notes": ""}


def drafted(qid: str, value: int | None = None, q: str | None = None, status: str = "drafted") -> dict:
    return {"status": status, "reason": "", "item": item(qid, value, q)}


def revised(qid: str, value: int | None = None, q: str | None = None) -> dict:
    return drafted(qid, value, q, "revised")


def audit(qid: str, value: int | None = None, severity: str | None = None) -> dict:
    fs = [{"severity": severity, "issue": "the wording is unclear", "suggested_fix": "say it plainly"}] if severity else []
    return {"id": qid, "value": gold(qid) if value is None else value, "reading": "read both lines", "findings": fs,
            "checked": "bt v"}


BAD_Q = "二十"                                       # a numeral run: mech_g v_number


@dataclass
class Reply:
    output: dict | None = None
    mode: str = "ok"            # ok limit infra fallback fallback_init nostart breach cli_changed unavailable; a+b
    cost: float = 0.1


class Fake:
    """claude_g.run_reserved, scripted per (qid, job label); the default writer and auditor are right."""

    def __init__(self) -> None:
        self.queue: dict[tuple[str, str], list[Reply]] = defaultdict(list)
        self.calls: list[dict] = []
        self.cost: dict[str, float] = {}
        self.delay: dict[str, float] = {}
        self.active = self.max_active = 0
        self.lock = threading.Lock()

    def on(self, qid: str, label: str, *replies: Reply) -> None:
        self.queue[(qid, label)].extend(replies)

    def default(self, job: dict, label: str) -> Reply:
        out = audit(job["qid"]) if label == "audit" else (drafted if label == "draft" else revised)(job["qid"])
        return Reply(out, cost=self.cost.get(label, 0.1))

    def __call__(self, kind, root, run_id, system, user, schema, budget_usd, model, pin, *, user_scope, out_root, **kw):
        job = kw["extra_record"]["job"]
        label = f"fix-{job['source']}" if job["kind"] == "fix" else job["kind"]
        ledger = L.Ledger(out_root)
        ledger.reserve(kind, root, run_id, budget_usd)
        q = self.queue.get((job["qid"], label))
        reply = q.pop(0) if q else self.default(job, label)
        self.calls.append({"job": job, "label": label, "run_id": run_id, "root": Path(root), "system": system,
                           "user": user, "scope": user_scope, "budget": budget_usd, "model": model, "kw": kw})
        if reply.mode in ("cli_changed", "unavailable"):
            ledger.release(root, run_id)
            raise (CliChanged if reply.mode == "cli_changed" else CliUnavailable)("fake CLI trouble")
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay.get(job["qid"], 0.0))
        with self.lock:
            self.active -= 1
        return write_run(Path(root), run_id, system, user, schema, budget_usd, model, pin, user_scope, kw, reply)


def write_run(root, run_id, system, user, schema, budget, model, pin, scope, kw, reply) -> CL.RunResult:
    rec = {"run_id": run_id, "system": system, "user": user, "schema": dict(schema), "argv": [], "cwd": str(kw["cwd"]),
           "budget_usd": budget, "model": model, "effort": kw["effort"], "tools_mode": kw["tools_mode"],
           "user_scope": scope, "tool_values": dict(kw.get("tool_values") or {}), "pin": pin.as_dict(), "env_keys": [],
           "utc": "t", **kw["extra_record"]}
    GC.write_json(root / "prompts" / f"{run_id}.json", rec)
    out, modes, t = reply.output or {}, set(reply.mode.split("+")), root / "transcripts" / f"{run_id}.jsonl"
    t.parent.mkdir(parents=True, exist_ok=True)
    if "nostart" in modes:                          # launch's OSError path: an empty transcript
        t.write_text("", encoding="utf-8")
        error, limit, fallback = CL.outcome(-1, None, [], model, budget, "cannot start claude: fake")
        return CL.RunResult(run_id, t, -1, 0.0, None, error, CL.usage_of(None, []), limit, fallback, model, "bt")
    cmd = "cat notes" if "breach" in modes else "bt books"
    use = lambda i, name, inp: {"type": "assistant", "message": {"content": [  # noqa: E731
        {"type": "tool_use", "id": i, "name": name, "input": inp}]}}
    other = "claude-other-0"
    events = [{"type": "system", "subtype": "init", "cwd": str(kw["cwd"]),
               "model": other if "fallback_init" in modes else model, "mcp_servers": [],
               "claude_code_version": pin.claude_version, "tools": ["Bash", "StructuredOutput"],
               "permissionMode": "dontAsk"}, use("t1", "Bash", {"command": cmd}),
              {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "甲 乙"}]}}]
    used = {model: {"costUSD": reply.cost}} | ({other: {"costUSD": 0.0}} if modes & {"fallback", "fallback_init"} else {})
    end = {"type": "result", "subtype": "success", "is_error": False, "result": "done", "structured_output": out,
           "total_cost_usd": reply.cost, "modelUsage": used}
    if "limit" in modes:
        end = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": budget,
               "modelUsage": used}
    rc = 1 if "infra" in modes else 0
    events += [] if rc else [use("t2", "StructuredOutput", out), end]
    t.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    result = CL.result_event(events)
    error, limit, fallback = CL.outcome(rc, result, events, model, budget)
    return CL.RunResult(run_id, t, rc, 0.5, result, error, CL.usage_of(result, events), limit, fallback, model, "bt")


def fake_trace(agrees: bool = True):
    return lambda row, it, aud: {
        "gold": row["gold"], "reader_value": row["gold"] + (not agrees), "reader_problems": [] if agrees else ["x"],
        "agrees": agrees, "reader_verses": ["gen.5.3"], "cited_verses": ["gen.5.3", "gen.5.6"], "unresolved_cited": [],
        "cited_units": ["gen.5.3", "gen.5.6"], "cited_not_read": ["gen.5.6"], "read_not_cited": [],
        "numbers": {"gen.5.3": [7]}, "writer_value": RU.writer_value(it), "auditor_value": aud.get("value")}


@pytest.fixture(autouse=True)
def stand_in_cues():
    with B.override_cue_literals(STAND_IN_CUES):
        yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "out"
    pool = GC.write_json(out / "pool.json", {"schema": "gen_confirm.pool.v1", "pool": pool_rows()})
    pin = CL.CliPin("9.9.9", "a" * 64, str(tmp_path / "claude"), True, dict(CL.MODELS))
    pin_file = GC.write_json(out / "cli_pin.json", pin.as_dict())
    man = GC.write_json(out / "f1_manifest.json", {"files": {"synthetic": "0" * 64,
                                                             R.CLI_KEY: GC.sha256_file(pin_file)}})
    GC.write_json(out / "order.json", {"schema": "gen_confirm.order.v1", "f1_files_digest": "0" * 64,
                                       "f1_manifest_sha256": GC.sha256_file(man), "pool_sha256": GC.sha256_file(pool),
                                       "pilot": GC.PILOT, "order": ORDER})
    GC.write_json(out / "gen_names.json", NAMES_DOC)
    f1a = GC.write_json(out / "f1a_pins.json", {"files": {}})
    GC.write_json(out / "qset/g1.json", {"schema": S.G1_SCHEMA, "R_card": 45, "R_wrong": 1, "n_v": 50, "g1": 0.9,
                                         "pass": True, "gt_zero_trigger": True, "f1a_pins_sha256": GC.sha256_file(f1a),
                                         "p2_spec_sha256": "0" * 64, "sentence": None, "t": "t"})
    prereg = tmp_path / "prereg.md"
    prereg.write_text("# synthetic prereg\n\n## 執行紀錄\n\n- K0 synthetic log line one\n", encoding="utf-8")
    fake = Fake()
    monkeypatch.setattr(CL, "run_reserved", fake)
    return SimpleNamespace(paths=S.Paths(out, GC.sha256_file(pool)), fake=fake, out=out, trace=fake_trace(),
                           prereg=prereg)


def log_line(env, line: str) -> str:
    """Append a line to the synthetic prereg's 執行紀錄 (an anchor for a logged fix)."""
    with env.prereg.open("a", encoding="utf-8") as f:
        f.write(f"- {line}\n")
    return line


def repin(env, version: str = "9.9.10") -> dict:
    """A re-probe's new pin (a synthetic CLI copy and its passing verdict in the store), logged and re-pinned."""
    exe = env.out / "cli" / version / "claude"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(f"a synthetic CLI copy {version}", encoding="utf-8")
    pin = CL.CliPin(version, GC.sha256_file(exe), str(exe), True, dict(CL.MODELS))
    v = GC.write_json(env.out / "probe" / f"verdict_{version}.json",
                      {"action": "pin", "claude_version_expected": version, "cli_sha256": pin.cli_sha256})
    CL.write_pin(pin, env.paths.cli_pin, verdict=v.name, verdict_sha256=GC.sha256_file(v))
    return R.repin(env.paths, log_line(env, f"re-probe after a CLI change: pinned {version}"), prereg=env.prereg)


def ctx(env, **kw) -> RU.Ctx:
    return R.make_ctx(env.paths, S.load_plan(env.paths), gold_trace=env.trace, prereg=env.prereg, **kw)


def pilot(env, **kw):
    return R.pilot(env.paths, ctx(env), f1_check=OK, **kw)


def through_main(env, g1_fn=G1_PASS):
    pilot(env)
    doc = R.kp(env.paths, g1_fn=g1_fn)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    return doc


def state(env) -> dict:
    return S.load_state(env.paths, S.load_plan(env.paths))


def rec_of(env, qid: str) -> dict:
    return S.slot(state(env), SID[qid])


def labels(env, att: dict) -> list[str]:
    st = state(env)
    return [f"fix-{st['runs'][k]['source']}" if st["runs"][k]["kind"] == "fix" else st["runs"][k]["kind"]
            for k in att["runs"]]


def accept_all(env, **over) -> dict:
    kay = state(env)["kay"]
    q = {s: {"decision": "accept", "note": ""} for s in kay["sampled"]}
    d = {s: {"decision": "drop", "note": ""} for s in kay["disputes"]}
    return {"questions": {**q, **over.get("questions", {})}, "disputes": {**d, **over.get("disputes", {})}}


# ---------------------------------------------------------------- the plan and the state file
def test_plan_and_state_refuse_another_order_pool_or_runner(env):
    plan = S.load_plan(env.paths)
    assert plan.pilot == tuple(ORDER[:12]) and plan.main(16) == tuple(ORDER[12:]) and plan.slots["S07"].qid == "Q02"
    with pytest.raises(HoError, match="pinned"):
        S.load_plan(S.Paths(env.out, "f" * 64))
    S.save_state(env.paths, {**S.new_state(plan), "plan": {"order_sha256": "x"}})
    with pytest.raises(HoError, match="another order.json"):
        S.load_state(env.paths, plan)
    with S.locked(env.paths), pytest.raises(HoError, match="another HO runner"):
        with S.locked(env.paths):
            pass
    GC.write_json(env.paths.f1_manifest, {"files": {"other": "1" * 64}})
    with pytest.raises(HoError, match="not drawn from the F1 manifest"):
        S.load_plan(env.paths)


def test_pilot_refuses_without_g1_pass_or_with_changed_frozen_files(env):
    g1 = GC.read_json(env.paths.g1)
    GC.write_json(env.paths.g1, {**g1, "pass": False})
    with pytest.raises(HoError, match="G1 did not pass"):
        pilot(env)
    GC.write_json(env.paths.g1, g1)
    with pytest.raises(HoError, match="F1-frozen files changed"):
        R.pilot(env.paths, ctx(env), f1_check=lambda p: ["gen_g.md is not the F1 manifest's"])
    assert env.fake.calls == []


# ---------------------------------------------------------------- the full flow
def run_all(env, fires=lambda q: False) -> dict:
    kp = through_main(env)
    K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    K.apply(env.paths, accept_all(env))
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    return {"kp": kp, "freeze": FZ.freeze(env.paths, f1_check=OK, fires=fires)}


def test_full_flow_pilot_kp_main_kay_and_freeze(env):
    pilot(env)
    st, plan = state(env), S.load_plan(env.paths)
    assert S.with_status(st, plan.pilot, S.PASSED) == list(plan.pilot)
    calls = env.fake.calls
    assert len(calls) == 24 and {c["label"] for c in calls} == {"draft", "audit"}
    assert all(c["root"] == env.paths.root("pilot") and c["model"] == CL.MODELS["opus"] for c in calls)
    assert all(c["kw"]["tools_mode"] == "bt" and c["kw"]["effort"] == "xhigh" for c in calls)
    assert {(c["label"], c["scope"], c["budget"]) for c in calls} == {("draft", "prompt", 2.0), ("audit", "agent", 1.0)}
    assert all(c["kw"]["tool_values"] and c["kw"]["tool_values"]["qid"] == c["job"]["qid"] for c in calls)
    spy = []
    doc = R.kp(env.paths, g1_fn=lambda *a: spy.append(a) or G1_PASS(*a))
    assert (doc["n_target"], doc["n_kp"], doc["go"]) == (16, PW.kp_n(12, 12, 16), True) and spy == [(45, 1, 50, 15)]
    assert doc["pilot_spent_usd"] == pytest.approx(2.4) and doc["per_slot_usd"] == pytest.approx(0.2)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    assert S.with_status(state(env), plan.order, S.PASSED) == list(plan.order)
    assert {c["root"] for c in env.fake.calls[24:]} == {env.paths.root("main")}
    sample = K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    assert sample["sampled"] == random.Random(GC.KAY_SAMPLE_SEED).sample(sorted(plan.order), 10)
    page = (env.paths.kay_dir / K.PAGE).read_text(encoding="utf-8")
    assert sample["disputes"] == [] and "某段經文" in page and all(question(QID[s]) in page for s in sample["sampled"])
    assert str(ROWS[sample["sampled"][0]]["gold"]) in page and "read both lines" in page
    K.apply(env.paths, accept_all(env))
    assert GC.read_json(env.paths.kay)["final"] and not GC.read_json(env.paths.kay)["stop"]
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    out = FZ.freeze(env.paths, f1_check=OK, fires=lambda q: q == question(QID["S03"]))
    frozen = GC.read_json(env.paths.frozen)
    assert A.frozen_problems(frozen, pool_rows(), ORDER) == []
    assert [q["sid"] for q in frozen["questions"]] == sorted(set(ORDER) - {"S03"})
    assert frozen["attrition"]["dynasty_trigger"] == ["S03"] and out["counts"]["by_cause"]["frozen"] == 15
    assert out["questions_frozen_sha256"] == GC.sha256_file(env.paths.frozen)
    assert set(out["counts"]["by_stratum"]) == {"F1c5", "F1c11", "F5c5", "F5c11"}
    with pytest.raises(HoError, match="never rewritten"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)


def test_no_prompt_holds_another_slots_question_and_audits_see_no_value(env):
    run_all(env)
    texts = {qid: question(qid) for qid in QID.values()}
    for c in env.fake.calls:
        prompt = c["system"] + c["user"]
        assert [q for q, t in texts.items() if q != c["job"]["qid"] and t in prompt] == []
        if c["label"] == "audit":
            assert str(gold(c["job"]["qid"])) not in prompt and "fact one" not in prompt


def test_gencard_never_runs_before_f2(env, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("gencard ran before F2")
    for mod, names in ((gencard, ("card", "card_for_seeds", "trigger", "rule_seeds")),
                       (importlib.import_module("gencard.trigger"), ("trigger", "read")),
                       (importlib.import_module("gencard.seeds"), ("rule_seeds", "decide")),
                       (importlib.import_module("gencard.card"), ("card", "card_for_seeds"))):
        for n in names:
            monkeypatch.setattr(mod, n, boom)
    out = run_all(env)
    assert out["freeze"]["counts"]["n"] == 16


# ---------------------------------------------------------------- attempts, fix rounds, §3.6
def test_attempts_and_one_fix_round_per_source(env):
    f = env.fake
    f.on("Q01", "draft", Reply(drafted("Q01", q=question("Q01").replace("那一年", BAD_Q + "年"))))
    f.on("Q02", "draft", Reply(drafted("Q02", q=question("Q02") + BAD_Q)))
    f.on("Q02", "fix-mech", Reply(revised("Q02", q=question("Q02") + BAD_Q)))
    f.on("Q03", "draft", *[Reply({"status": "abandoned", "reason": "cannot verify", "item": None})] * 3)
    f.on("Q04", "audit", Reply(audit("Q04", severity="major")))
    f.on("Q05", "audit", Reply(audit("Q05", severity="critical")), Reply(audit("Q05", severity="major")))
    pilot(env)
    a = rec_of(env, "Q01")
    assert a["status"] == S.PASSED and labels(env, a["attempts"][0]) == ["draft", "fix-mech", "audit"]
    assert a["attempts"][0]["fixes"] == {"mech": 1, "audit": 0, "kay": 0}
    fix = next(c for c in f.calls if c["job"]["qid"] == "Q01" and c["label"] == "fix-mech")
    assert fix["scope"] == "agent" and "numeral" in fix["user"] and fix["budget"] == 1.5
    b = rec_of(env, "Q02")
    assert S.attempts_used(b) == 2 and b["attempts"][0]["step"] == S.ENDED and b["status"] == S.PASSED
    c = rec_of(env, "Q03")
    assert c["status"] == S.FAILED and c["close"]["cause"] == "failed" and S.attempts_used(c) == GC.MAX_ATTEMPTS
    d = rec_of(env, "Q04")
    assert labels(env, d["attempts"][0]) == ["draft", "audit", "fix-audit", "audit"] and d["status"] == S.PASSED
    assert "the wording is unclear" in next(x["user"] for x in f.calls if x["job"]["qid"] == "Q04" and x["label"] == "fix-audit")
    e = rec_of(env, "Q05")
    assert e["attempts"][0]["step"] == S.ENDED and "稽核輪已用完" in e["attempts"][0]["end"]["why"]
    assert len(e["attempts"]) == 2 and e["status"] == S.PASSED


def test_the_four_three_way_cases(env):
    f, g = env.fake, gold
    f.on("Q01", "draft", Reply(drafted("Q01", g("Q01") + 1)))                       # writer differs
    f.on("Q02", "audit", Reply(audit("Q02", g("Q02") + 5)))                         # auditor differs
    f.on("Q03", "draft", Reply(drafted("Q03", g("Q03") + 3)))                       # writer = auditor ≠ gold
    f.on("Q03", "audit", Reply(audit("Q03", g("Q03") + 3)))
    f.on("Q04", "draft", Reply(drafted("Q04", g("Q04") + 1)))                       # all differ
    f.on("Q04", "audit", Reply(audit("Q04", g("Q04") + 2)), Reply(audit("Q04", g("Q04") + 2)))
    f.on("Q04", "fix-audit", Reply(revised("Q04", g("Q04") + 1)))
    pilot(env)
    fixes = {c["job"]["qid"]: c["user"] for c in f.calls if c["label"] == "fix-audit"}
    assert P.GOLD_MISMATCH_HINT in fixes["Q01"] and P.AMBIGUITY_HINT not in fixes["Q01"]
    assert P.AMBIGUITY_HINT in fixes["Q02"] and P.GOLD_MISMATCH_HINT not in fixes["Q02"]
    assert P.GOLD_MISMATCH_HINT in fixes["Q04"] and P.AMBIGUITY_HINT in fixes["Q04"]
    assert str(g("Q02") + 5) not in fixes["Q02"] and str(g("Q04") + 2) not in fixes["Q04"]
    assert rec_of(env, "Q01")["status"] == rec_of(env, "Q02")["status"] == S.PASSED
    q3 = rec_of(env, "Q03")
    assert q3["status"] == S.DISPUTE and q3["dispute"]["kind"] == "program_differs" and q3["attempts"][0]["gold_trace"]
    assert len(q3["attempts"]) == 1 and "Q03" not in fixes
    q4 = rec_of(env, "Q04")
    assert q4["attempts"][0]["step"] == S.ENDED and q4["status"] == S.PASSED and len(q4["attempts"]) == 2
    R.kp(env.paths, g1_fn=G1_PASS)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    page = (env.paths.kay_dir / K.PAGE).read_text(encoding="utf-8")
    assert "value='keep' disabled" in page and "CPU 比對" in page
    keep = accept_all(env, disputes={SID["Q03"]: {"decision": "keep", "note": ""}})
    with pytest.raises(HoError, match="no keep"):
        K.apply(env.paths, keep)
    K.apply(env.paths, accept_all(env))
    assert rec_of(env, "Q03")["status"] == S.OTHER_QUANTITY and not GC.read_json(env.paths.kay)["stop"]
    out = FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    assert GC.read_json(env.paths.frozen)["attrition"]["other_quantity"] == [SID["Q03"]] and out["counts"]["n"] == 15


def test_a_program_gold_marked_wrong_is_k_gold_and_a_cpu_disagreement_stops_at_once(env):
    env.fake.on("Q03", "draft", Reply(drafted("Q03", gold("Q03") + 3)))
    env.fake.on("Q03", "audit", Reply(audit("Q03", gold("Q03") + 3)))
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    K.apply(env.paths, accept_all(env, disputes={SID["Q03"]: {"decision": "drop", "gold_wrong": True}}))
    rec = GC.read_json(env.paths.kay)
    assert rec["stop"] and rec["rule"] == "K-gold" and rec["sentence"].startswith("依事先規則停止（K-gold＝")
    with pytest.raises(HoError, match="stopped the line"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)


def test_cpu_trace_disagreeing_with_the_gold_stops_the_runner(env):
    env.trace = fake_trace(agrees=False)
    env.fake.on("Q03", "draft", Reply(drafted("Q03", gold("Q03") + 3)))
    env.fake.on("Q03", "audit", Reply(audit("Q03", gold("Q03") + 3)))
    with pytest.raises(RU.KGold):
        pilot(env)
    doc = GC.read_json(env.paths.ho_root / R.K_GOLD_FILE)
    assert doc["sids"] == [SID["Q03"]] and "K-gold" in doc["sentence"]
    with pytest.raises(HoError, match="K-gold"):
        pilot(env)


# ---------------------------------------------------------------- blinding, limits, infrastructure
def test_blinding_error_and_agent_limit_end_the_attempt_and_count(env):
    env.fake.on("Q01", "draft", Reply(drafted("Q01"), mode="breach"))
    env.fake.on("Q02", "audit", Reply(audit("Q02"), mode="breach"))
    env.fake.on("Q03", "draft", Reply(mode="limit"))
    env.fake.on("Q04", "audit", Reply(mode="limit"))
    pilot(env)
    for qid, why, runs in (("Q01", "盲化違規", ["draft"]), ("Q02", "盲化違規", ["draft", "audit"]),
                           ("Q03", "代理上限", ["draft"]), ("Q04", "代理上限", ["draft", "audit"])):
        r = rec_of(env, qid)
        assert S.attempts_used(r) == 2 and why in r["attempts"][0]["end"]["why"] and r["status"] == S.PASSED
        assert labels(env, r["attempts"][0]) == runs and r["attempts"][0]["counted"]


def test_infrastructure_failures_are_rerun_and_never_an_attempt(env):
    env.fake.on("Q01", "draft", Reply(mode="infra"), Reply(mode="fallback", output=drafted("Q01")))
    env.fake.on("Q02", "audit", Reply(audit("Q02", severity="minor") | {"id": "Q99"}))
    env.fake.on("Q03", "draft", *[Reply(mode="infra")] * (1 + GC.MAX_INFRA_RETRIES))
    with pytest.raises(RU.InfraStop, match="基礎設施失敗"):
        pilot(env)
    r = rec_of(env, "Q03")
    assert r["status"] == S.OPEN and not r["attempts"][0]["counted"] and S.attempts_used(r) == 0
    pilot(env, infra_fix=log_line(env, "infra fix: synthetic draft reruns of Q03"))
    a = rec_of(env, "Q01")["attempts"]
    assert len(a) == 1 and labels(env, a[0]) == ["draft", "draft", "draft", "audit"] and rec_of(env, "Q01")["status"] == S.PASSED
    assert [state(env)["runs"][k]["infra"] for k in a[0]["runs"]] == [True, True, False, False]
    assert labels(env, rec_of(env, "Q02")["attempts"][0]) == ["draft", "audit", "audit"]
    r = rec_of(env, "Q03")
    assert r["status"] == S.PASSED and len(r["attempts"]) == 2 and S.attempts_used(r) == 1


def test_cli_changed_stops_the_runner_and_cli_unavailable_is_retried(env):
    env.fake.on("Q01", "draft", Reply(mode="cli_changed"))
    env.fake.on("Q02", "draft", Reply(mode="unavailable"))
    with pytest.raises(CliChanged, match="重做 probe"):
        pilot(env)
    r = rec_of(env, "Q01")
    assert r["attempts"] == [] and r["inflight"] is None and r["events"][-1]["stopped"]
    assert not list(env.paths.root("pilot").glob("reserve/Q01_*"))
    with pytest.raises(HoError, match="repin"):
        pilot(env)
    repin(env)
    pilot(env)
    assert all(rec_of(env, q)["status"] == S.PASSED for q in ("Q01", "Q02"))
    assert any(e.get("stopped") == "fake CLI trouble" for e in rec_of(env, "Q02")["events"])


def test_waves_run_at_most_parallel_jobs_and_commit_in_writing_order(env):
    env.fake.delay.update({S.qid_of(i): 0.05 * (5 - i) for i in range(1, 5)})
    pilot(env)
    assert env.fake.max_active == GC.PARALLEL
    first = [k.split("/")[-1] for k in state(env)["runs"]][:4]
    assert first == [f"{S.qid_of(i)}_a1_draft_1" for i in range(1, 5)]


def test_cli_unavailable_every_wave_gives_up(env):
    for q in [S.qid_of(i) for i in range(1, 13)]:
        env.fake.on(q, "draft", *[Reply(mode="unavailable")] * RU.UNAVAILABLE_WAVES)
    with pytest.raises(CliUnavailable):
        pilot(env)
    assert all(not rec_of(env, S.qid_of(i))["attempts"] for i in range(1, 13))


def test_a_crashed_job_is_recovered_and_planned_again(env):
    plan = S.load_plan(env.paths)
    st = S.begin_job(S.new_state(plan), "S00", {"kind": "draft", "attempt": 1})
    S.save_state(env.paths, st)
    pilot(env)
    r = rec_of(env, "Q01")
    assert r["status"] == S.PASSED and any(e["what"] == "interrupted" for e in r["events"])


# ---------------------------------------------------------------- the hard cap and K-P
def inject_spend(env, usd: float) -> None:
    spent = L.Ledger(env.out).spent()
    GC.write_json(env.out / "qset/p2/reserve/injected.json", {"run_id": "injected", "budget_usd": round(usd - spent, 6)})


def test_hard_cap_stops_drafting_and_waiting_drafts_go_on_while_they_fit(env):
    pilot(env)
    R.kp(env.paths, g1_fn=G1_PASS)
    with pytest.raises(HoError, match="未達硬上限"):
        R.stop_drafting(env.paths)
    inject_spend(env, 46.0)
    env.fake.cost.update(draft=1.0, audit=0.5)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    st, main = state(env), ORDER[12:]
    assert S.statuses(st, main) == {main[0]: S.PASSED, **{s: S.CAP_STOPPED for s in main[1:]}}
    assert st["drafting_stopped"] and st["cap_stop"]["limit_usd"] == 49.0


def test_a_refused_job_cap_stops_its_slot(env):
    pilot(env)
    R.kp(env.paths, g1_fn=G1_PASS)
    inject_spend(env, 46.6)
    env.fake.cost.update(draft=1.5)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    st = state(env)
    assert set(S.statuses(st, ORDER[12:]).values()) == {S.CAP_STOPPED}
    assert S.slot(st, ORDER[12])["attempts"][0]["step"] == S.AUDIT and L.Ledger(env.out).spent() <= 49.0


def test_budget_refusal_in_the_pilot_starts_nothing(env):
    inject_spend(env, 47.5)
    with pytest.raises(BudgetRefused):
        pilot(env)
    assert env.fake.calls == [] and S.summary(state(env), ORDER[:12])["opened"] == 0


def test_kp_arithmetic_truncates_rounds_half_up_and_never_goes_below_the_pilot():
    g1 = {"R_card": 45, "R_wrong": 1, "n_v": 50}
    d = R.kp_decision(10.0, 6.0, 12, 11, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)
    assert (d["n_target"], d["n_kp"], d["go"]) == (58, 53, True) and d["projected_full_usd"] == pytest.approx(33.0)
    d = R.kp_decision(20.0, 12.0, 12, 10, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)
    assert (d["n_target"], d["n_kp"]) == (39, PW.kp_n(10, 12, 39)) and d["projected_n_target_usd"] <= 47
    d = R.kp_decision(40.0, 60.0, 12, 6, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)
    assert (d["n_target"], d["n_kp"]) == (13, 7) and PW.kp_n(6, 12, 13) == 7          # 6.5 rounds up
    d = R.kp_decision(48.0, 6.0, 12, 12, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)
    assert d["n_target"] == GC.PILOT
    spy = []
    d = R.kp_decision(10.0, 6.0, 12, 10, g1, k_gold=False, n_pool=58,
                      g1_fn=lambda *a: spy.append(a) or {"n": a[3], "pow_H1_and_H2": 0.69, "pass": False})
    assert spy == [(45, 1, 50, 48)] and d["stop"] and d["rule"] == "K-P" and "K-P＝" in d["sentence"]
    assert d["sentence"].endswith("盲集未凍結")
    d = R.kp_decision(10.0, 6.0, 12, 0, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)
    assert d["n_kp"] == 0 and d["stop"]
    d = R.kp_decision(10.0, 6.0, 12, 12, g1, k_gold=True, n_pool=58, g1_fn=G1_PASS)
    assert d["rule"] == "K-gold" and d["stop"]
    with pytest.raises(HoError):
        R.kp_decision(1.0, 0.0, 0, 0, g1, k_gold=False, n_pool=58, g1_fn=G1_PASS)


def test_kp_gate_uses_power_g_g1_itself():
    pool = PW.Pool(pool_rows())
    g1 = {"R_card": 44, "R_wrong": 2, "n_v": 50}
    d = R.kp_decision(5.0, 3.0, 12, 11, g1, k_gold=False, n_pool=16,
                      g1_fn=lambda rc, rw, nv, n: PW.g1(pool, rc, rw, nv, n=n))
    direct = PW.g1(pool, 44, 2, 50, n=PW.kp_n(11, 12, 16))
    assert d["g1"]["pow_H1_and_H2"] == direct["pow_H1_and_H2"] and d["go"] == direct["pass"]


def test_kp_once_after_the_pilot_and_main_needs_go(env):
    with pytest.raises(HoError, match="pilot is not done"):
        R.kp(env.paths, g1_fn=G1_PASS)
    with pytest.raises(HoError, match="kp.json missing"):
        R.main_phase(env.paths, ctx(env), f1_check=OK)
    pilot(env)
    R.kp(env.paths, g1_fn=lambda *a: {"n": a[3], "pow_H1_and_H2": 0.5, "pass": False})
    with pytest.raises(HoError, match="kp.json exists"):
        R.kp(env.paths, g1_fn=G1_PASS)
    with pytest.raises(HoError, match="K-P stopped"):
        R.main_phase(env.paths, ctx(env), f1_check=OK)
    with pytest.raises(HoError, match="kp.json exists"):
        pilot(env)


# ---------------------------------------------------------------- Kay's page
def test_kay_sample_is_the_seeded_draw():
    ids = [f"S{k:02d}" for k in range(30, 0, -1)]
    assert K.sample(ids) == random.Random(20261021).sample(sorted(ids), 10) == K.sample(list(reversed(ids)))
    assert sorted(K.sample(ids[:4])) == sorted(ids[:4])


def test_k_kay_counts_drops_and_failed_revisions(env):
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    s = state(env)["kay"]["sampled"]
    revise = {"decision": "revise", "note": "name the book once only"}
    dec = accept_all(env, questions={s[0]: {"decision": "drop"}, s[1]: {"decision": "drop"}, s[2]: revise, s[3]: revise})
    q2, q3 = QID[s[2]], QID[s[3]]
    env.fake.on(q2, "fix-kay", Reply(revised(q2, q=question(q2, "裏"))))
    env.fake.on(q3, "audit", Reply(audit(q3, severity="major")))
    with pytest.raises(HoError, match="not applied"):
        R.kay_work(env.paths, ctx(env), f1_check=OK)
    K.apply(env.paths, dec)
    rec = GC.read_json(env.paths.kay)
    assert not rec["stop"] and not rec["final"] and rec["revisions_pending"] == sorted([s[2], s[3]])
    with pytest.raises(HoError, match="not settled"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    kay_calls = [c for c in env.fake.calls if c["root"] == env.paths.root("kay")]
    fix = next(c for c in kay_calls if c["label"] == "fix-kay" and c["job"]["qid"] == q2)
    assert "name the book once only" in fix["user"] and fix["scope"] == "agent"
    st = state(env)
    assert S.slot(st, s[2])["status"] == S.PASSED and S.current(S.slot(st, s[2]))["item"]["question"] == question(q2, "裏")
    assert S.slot(st, s[3])["status"] == S.KAY_DROPPED and S.slot(st, s[2])["attempts"][-1]["fixes"]["kay"] == 1
    assert labels(env, S.current(S.slot(st, s[3])))[-2:] == ["fix-kay", "audit"]
    assert {c["root"] for c in kay_calls} == {env.paths.root("kay")} and len(kay_calls) == 4
    rec = GC.read_json(env.paths.kay)
    assert rec["final"] and rec["n_dropped"] == 3 and rec["rule"] == "K-Kay" and rec["revisions_failed"] == [s[3]]
    with pytest.raises(HoError, match="stopped the line"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)


def test_three_explicit_drops_stop_at_once(env):
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    s = state(env)["kay"]["sampled"]
    K.apply(env.paths, accept_all(env, questions={x: {"decision": "drop"} for x in s[:3]}))
    assert GC.read_json(env.paths.kay)["rule"] == "K-Kay"
    with pytest.raises(HoError, match="stopped the line"):
        R.kay_work(env.paths, ctx(env), f1_check=OK)


def test_kay_page_gates_and_decisions_are_validated(env):
    pilot(env)
    with pytest.raises(HoError, match="kp.json missing"):
        K.draw(env.paths, verses=lambda k: [])
    R.kp(env.paths, g1_fn=G1_PASS)
    with pytest.raises(HoError, match="questions not finished"):
        K.draw(env.paths, verses=lambda k: [])
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    with pytest.raises(HoError, match="no Kay page"):
        K.apply(env.paths, {})
    K.draw(env.paths, verses=lambda k: [])
    with pytest.raises(HoError, match="already drawn"):
        K.draw(env.paths, verses=lambda k: [])
    s = state(env)["kay"]["sampled"]
    for bad, why in (({"questions": {}}, "every sampled"), (accept_all(env, questions={s[0]: {"decision": "revise"}}),
                                                            "needs a note"),
                     (accept_all(env, questions={s[0]: {"decision": "revise", "note": "see gencard"}}), "reword"),
                     (accept_all(env, questions={s[0]: {"decision": "maybe"}}), "one of")):
        with pytest.raises(HoError, match=why):
            K.apply(env.paths, bad)
    assert state(env)["kay"]["applied"] is False


def test_disputes_keep_means_what_kay_g_says(env):
    f, g = env.fake, gold
    f.on("Q01", "draft", Reply(drafted("Q01", q=question("Q01") + BAD_Q)))                 # mech no_change
    f.on("Q01", "fix-mech", Reply({"status": "no_change", "reason": "the numeral is fine", "item": item("Q01")}))
    f.on("Q02", "audit", Reply(audit("Q02", severity="major")))                            # audit vs mech
    f.on("Q02", "fix-audit", Reply(revised("Q02", q=question("Q02") + BAD_Q)))
    f.on("Q02", "fix-mech", Reply(revised("Q02", q=question("Q02") + BAD_Q)))
    f.on("Q04", "draft", Reply(drafted("Q04", g("Q04") + 1)))                              # audit no_change
    f.on("Q04", "fix-audit", Reply({"status": "no_change", "reason": "my count holds", "item": item("Q04")}))
    f.on("Q05", "audit", Reply(audit("Q05", severity="major")))                            # no reason: ends
    f.on("Q05", "fix-audit", Reply({"status": "no_change", "reason": " ", "item": item("Q05")}))
    pilot(env)
    kinds = {q: (rec_of(env, q)["dispute"] or {}).get("kind") for q in ("Q01", "Q02", "Q04", "Q05")}
    assert kinds == {"Q01": "no_change", "Q02": "audit_mech_conflict", "Q04": "no_change", "Q05": None}
    assert labels(env, rec_of(env, "Q02")["attempts"][0]) == ["draft", "audit", "fix-audit", "fix-mech"]
    assert labels(env, rec_of(env, "Q01")["attempts"][0]) == ["draft", "fix-mech"]
    assert [rec_of(env, q)["dispute"]["source"] for q in ("Q01", "Q04")] == ["mech", "audit"]
    assert rec_of(env, "Q05")["status"] == S.PASSED and len(rec_of(env, "Q05")["attempts"]) == 2
    d2 = rec_of(env, "Q02")["dispute"]
    assert d2["candidate"]["question"] == question("Q02") + BAD_Q and d2["audited"]["question"] == question("Q02")
    R.kp(env.paths, g1_fn=G1_PASS)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    keep = {SID[q]: {"decision": "keep"} for q in ("Q01", "Q02", "Q04")}
    K.apply(env.paths, accept_all(env, disputes=keep))
    assert rec_of(env, "Q01")["status"] == rec_of(env, "Q02")["status"] == S.PENDING_AUDIT
    assert rec_of(env, "Q04")["status"] == S.FAILED and not GC.read_json(env.paths.kay)["final"]
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    a1 = S.current(rec_of(env, "Q01"))
    assert a1["step"] == S.STEP_PASSED and a1["root"] == "kay" and a1["kept_mech"]
    assert labels(env, a1) == ["draft", "fix-mech", "audit"]
    assert [c["root"] for c in env.fake.calls if c["job"]["qid"] == "Q01"][-1] == env.paths.root("kay")
    a2 = S.current(rec_of(env, "Q02"))
    assert a2["step"] == S.STEP_PASSED and {m["rule"] for m in a2["kept_mech"]} == {"v_number"}
    assert labels(env, a2) == ["draft", "audit", "fix-audit", "fix-mech", "audit"]
    out = FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    frozen = {q["sid"]: q["question"] for q in GC.read_json(env.paths.frozen)["questions"]}
    assert frozen[SID["Q01"]] == question("Q01") + BAD_Q and frozen[SID["Q02"]] == question("Q02") + BAD_Q
    assert GC.read_json(env.paths.frozen)["attrition"]["failed"] == [SID["Q04"]] and out["counts"]["n"] == 15


# ---------------------------------------------------------------- F2 steps 1-4
def test_freeze_refuses_a_changed_transcript_or_an_unsettled_line(env):
    with pytest.raises(HoError, match="kp.json missing"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    through_main(env)
    with pytest.raises(HoError, match="not applied"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    K.draw(env.paths, verses=lambda k: [])
    K.apply(env.paths, accept_all(env))
    att = S.current(rec_of(env, "Q01"))
    run = state(env)["runs"][att["runs"][0]]
    t = env.out / run["root"] / "transcripts" / f"{run['run_id']}.jsonl"
    t.write_text(t.read_text(encoding="utf-8").replace("bt books", "cat notes"), encoding="utf-8")
    with pytest.raises(HoError, match="t_tool"):
        FZ.freeze(env.paths, f1_check=OK, fires=lambda q: False)
    assert not env.paths.frozen.exists()


# ---------------------------------------------------------------- modules and the prod trigger
def test_runners_load_only_the_allowed_modules():
    code = (f"import sys, json; sys.path.insert(0, {str(H)!r}); import run_ho_g, kay_g, freeze_g, state_g, runs_g;"
            "from pathlib import Path;"
            "f = lambda m: Path(getattr(m, '__file__', None) or '/').resolve();"
            "kg = Path(run_ho_g.GC.REPO, 'evaluation/experiments/2026-10-18_kg_cards/A/confirm').resolve();"
            "a = sorted(n for n, m in list(sys.modules.items()) if kg in f(m).parents);"
            "bad = any('regnal_qset' in str(f(m)) or 'ho_a' in f(m).parts or 'graph_gd' in str(f(m)) and "
            "'ho_tools' not in f(m).parts for m in list(sys.modules.values()));"
            "print(json.dumps([a, bad, 'config' in sys.modules, 'utils' in sys.modules, 'ragcommon' in sys.modules]))")
    out = json.loads(subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                                    check=True).stdout)
    assert out == [["analyze_c", "c_common", "guards_c"], False, False, False, False]


@needs_store
def test_prod_dynasty_trigger_loads_by_path_after_the_pins():
    pins = {**GC.backend_pins(), **GC.trigger_pins()}                  # the F1 manifest's prod items (f1_g.prod_pins)
    fires = FZ.prod_trigger(pins)
    names = sys.modules["gen_confirm_prod_regnal_layer"].parse_layer(GC.R4_LAYER.read_bytes()).names
    qs = [question(q) for q in QID.values()]
    assert sum(map(fires, qs)) == 0 and fires(f"{names[0]}之後的第2位王是誰？")
    with pytest.raises(HoError, match="differ"):
        FZ.prod_trigger({**pins, FZ.TRIGGER_FILES[0]: "0" * 64})
