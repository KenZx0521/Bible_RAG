"""GEN confirmation set, the blind question-writing executor's edge paths (prereg §2.3, §3.1, §3.4, §3.6, §3.7,
§8.1-7..10): runs that never started or fell back (infrastructure, not a blinding breach), the audit-vs-mech conflict
rule, logged re-pins after a CLI change and logged infrastructure fixes, K-Kay reached during Kay's work, the K-P
inputs, the G1 contract, F2 steps 1–3, the paths after Kay's page, and a store smoke of the CPU gold trace. The fake
launcher, the synthetic pool and the env fixture are test_gen_confirm_ho's (made-up names and numbers); the scan at the
end checks both test files and the five modules against the text layer and the real question sets. Store tests skip
when the store is not mounted and assert on counts and booleans only.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import unicodedata
from pathlib import Path

import pytest

import test_gen_confirm_ho as T
from test_gen_confirm_ho import (BAD_Q, G1_PASS, OK, ORDER, QID, SID, CL, FZ, GC, K, PW, R, RU, S, CliChanged,  # noqa: F401
                                 HoError, Reply, accept_all, audit, ctx, drafted, env, gold, inject_spend, item, labels,
                                 log_line, needs_store, pilot, question, rec_of, revised, stand_in_cues, state,
                                 through_main)

REVISE = {"decision": "revise", "note": "name the book once only"}
DROP = {"decision": "drop", "note": ""}
NO_FIRES = lambda q: False  # noqa: E731


def to_kay(env, **over) -> None:
    through_main(env)
    K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    K.apply(env.paths, accept_all(env, **over))


def freeze(env, **kw):
    return FZ.freeze(env.paths, **{"fires": NO_FIRES, "f1_check": OK, **kw})


def no_change(qid: str, q: str | None = None, value: int | None = None, reason: str = "the numeral is fine") -> Reply:
    return Reply({"status": "no_change", "reason": reason, "item": item(qid, value, q)})


def remanifest(env, files: dict) -> None:
    """A synthetic F1 manifest and the order.json drawn from it."""
    man = GC.write_json(env.paths.f1_manifest, {"files": files})
    doc = GC.read_json(env.paths.order)
    GC.write_json(env.paths.order, {**doc, "f1_manifest_sha256": GC.sha256_file(man)})


# ---------------------------------------------------------------- HO-1: infrastructure runs are not breaches
def test_a_run_that_never_started_or_fell_back_is_rerun_and_a_breach_in_one_still_counts(env):
    f = env.fake
    f.on("Q01", "draft", Reply(mode="nostart"))
    f.on("Q02", "draft", Reply(drafted("Q02"), mode="fallback_init"))
    f.on("Q04", "audit", Reply(mode="nostart"))
    f.on("Q05", "draft", Reply(drafted("Q05"), mode="infra+breach"))
    pilot(env)
    st = state(env)
    for qid in ("Q01", "Q02", "Q04"):
        r = rec_of(env, qid)
        assert r["status"] == S.PASSED and S.attempts_used(r) == 1 and len(r["attempts"]) == 1, qid
        runs = [st["runs"][k] for k in r["attempts"][0]["runs"]]
        assert [x["infra"] for x in runs].count(True) == 1 and not any(x["breach"] for x in runs), qid
    r = rec_of(env, "Q05")
    assert S.attempts_used(r) == 2 and "盲化違規 ['t_tool']" in r["attempts"][0]["end"]["why"]
    assert labels(env, r["attempts"][0]) == ["draft"]                                # a breach is never rerun


def test_freeze_accepts_an_infra_run_that_never_started_but_not_a_tool_call_in_it(env):
    env.fake.on("Q01", "draft", Reply(mode="nostart"))
    to_kay(env)
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    att = S.current(rec_of(env, "Q01"))
    run = state(env)["runs"][att["runs"][0]]
    assert run["infra"] and run["error"] and len(att["runs"]) == 3
    t = env.out / run["root"] / "transcripts" / f"{run['run_id']}.jsonl"
    call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "x", "name": "Bash",
                                                          "input": {"command": "cat notes"}}]}}
    t.write_text(json.dumps(call) + "\n", encoding="utf-8")
    with pytest.raises(HoError, match="t_tool"):
        freeze(env)
    assert RU.infra_own({"rule": "t_init", "detail": RU.NO_INIT}, run)
    assert not RU.infra_own({"rule": "t_init", "detail": RU.NO_INIT}, {**run, "error": None})
    assert not RU.infra_own({"rule": "t_tool", "detail": "x"}, run)
    t.write_text("", encoding="utf-8")
    assert freeze(env)["counts"]["n"] == 16


# ---------------------------------------------------------------- HO-2: the audit-vs-mech conflict
def test_an_audit_vs_mech_conflict_needs_the_audit_driven_break_and_keep_reaudits_the_revision(env):
    f = env.fake
    f.on("Q06", "audit", Reply(audit("Q06", severity="major")))                     # mech fix breaks another rule
    f.on("Q06", "fix-audit", Reply(revised("Q06", q=question("Q06") + BAD_Q)))
    f.on("Q06", "fix-mech", Reply(revised("Q06", q=question("Q06").replace("創世記", "聖經"))))
    f.on("Q07", "draft", Reply(drafted("Q07", q=question("Q07") + BAD_Q)))           # mech round spent first
    f.on("Q07", "audit", Reply(audit("Q07", severity="major")))
    f.on("Q07", "fix-audit", Reply(revised("Q07", q=question("Q07") + BAD_Q)))
    pilot(env)
    a = rec_of(env, "Q06")
    assert a["status"] == S.PASSED and S.attempts_used(a) == 2 and a["dispute"] is None
    assert labels(env, a["attempts"][0]) == ["draft", "audit", "fix-audit", "fix-mech"]
    b = rec_of(env, "Q07")
    assert b["status"] == S.DISPUTE and S.attempts_used(b) == 1
    assert labels(env, b["attempts"][0]) == ["draft", "fix-mech", "audit", "fix-audit"]
    d = b["dispute"]
    assert (d["kind"], d["rules"]) == ("audit_mech_conflict", ["v_number"])
    assert d["candidate"]["question"] == question("Q07") + BAD_Q and d["audited"]["question"] == question("Q07")
    R.kp(env.paths, g1_fn=G1_PASS)
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    K.draw(env.paths, verses=lambda k: [(k, "某段經文")])
    page = (env.paths.kay_dir / K.PAGE).read_text(encoding="utf-8")
    assert K.KEEP_MEANS["audit_mech_conflict:audit"] in page
    K.apply(env.paths, accept_all(env, disputes={SID["Q07"]: {"decision": "keep"}}))
    assert rec_of(env, "Q07")["status"] == S.PENDING_AUDIT
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    att = S.current(rec_of(env, "Q07"))
    assert att["step"] == S.STEP_PASSED and {m["rule"] for m in att["kept_mech"]} == {"v_number"}
    assert state(env)["runs"][att["runs"][-1]]["root"] == "ho/kay"
    freeze(env)
    frozen = {q["sid"]: q["question"] for q in GC.read_json(env.paths.frozen)["questions"]}
    assert frozen[SID["Q07"]] == question("Q07") + BAD_Q


def test_no_change_after_a_row_3_audit_fix_is_the_row_3_dispute(env):
    g = gold("Q05")
    env.fake.on("Q05", "draft", Reply(drafted("Q05", g + 3)))
    env.fake.on("Q05", "audit", Reply(audit("Q05", g + 3, severity="major")))
    env.fake.on("Q05", "fix-audit", no_change("Q05", value=g + 3, reason="my count holds"))
    pilot(env)
    d = rec_of(env, "Q05")["dispute"]
    assert (d["kind"], d["source"]) == ("program_differs", "audit") and d["gold_trace"]["agrees"]


# ---------------------------------------------------------------- HO-3: a logged re-pin after a CLI change
def test_a_logged_repin_lets_the_runner_go_on_after_a_cli_change(env):
    pin0 = GC.sha256_file(env.paths.cli_pin)
    remanifest(env, {"x/frozen.py": "1" * 64, R.CLI_KEY: pin0})
    check = lambda p: R.f1_problems(p, current={"x/frozen.py": "1" * 64}, prereg=env.prereg)  # noqa: E731
    assert check(env.paths) == []
    assert any("frozen.py" in p for p in R.f1_problems(env.paths, current={"x/frozen.py": "2" * 64}, prereg=env.prereg))
    env.fake.on("Q01", "draft", Reply(mode="cli_changed"))
    with pytest.raises(CliChanged):
        R.pilot(env.paths, ctx(env), f1_check=check)
    assert S.open_stop(state(env))["kind"] == "cli_changed"
    n = len(env.fake.calls)
    with pytest.raises(HoError, match="repin"):
        R.pilot(env.paths, ctx(env), f1_check=check)
    exe = env.out / "cli" / "9.9.10" / "claude"
    exe.parent.mkdir(parents=True)
    exe.write_text("a synthetic CLI copy", encoding="utf-8")
    new = CL.CliPin("9.9.10", GC.sha256_file(exe), str(exe), True, dict(CL.MODELS))
    with pytest.raises(HoError, match="verdict"):
        CL.write_pin(new, env.paths.cli_pin)
        R.repin(env.paths, log_line(env, "re-probe without a verdict record"), prereg=env.prereg)
    verdict = GC.write_json(env.out / "probe" / "verdict_2.json", {"action": "pin", "claude_version_expected": "9.9.10",
                                                                   "cli_sha256": new.cli_sha256})
    CL.write_pin(new, env.paths.cli_pin, verdict=verdict.name, verdict_sha256=GC.sha256_file(verdict))
    assert any("cli_pin.json" in p for p in check(env.paths))
    with pytest.raises(HoError, match="not a whole line"):
        R.repin(env.paths, "re-probe: a line that is not in the log", prereg=env.prereg)
    with pytest.raises(HoError, match="before this step"):
        R.repin(env.paths, "K0 synthetic log line one", prereg=env.prereg)
    line = log_line(env, "re-probe after a CLI change: pinned 9.9.10")
    doc = R.repin(env.paths, line, prereg=env.prereg)
    assert (doc["from_sha256"], doc["to_sha256"]) == (pin0, GC.sha256_file(env.paths.cli_pin))
    assert check(env.paths) == [] and S.open_stop(state(env)) is None and len(env.fake.calls) == n
    with pytest.raises(HoError, match="nothing to re-pin"):
        R.repin(env.paths, log_line(env, "a second line for the same pin"), prereg=env.prereg)
    R.pilot(env.paths, ctx(env), f1_check=check)
    assert S.with_status(state(env), ORDER[:12], S.PASSED) == ORDER[:12]
    run = state(env)["runs"][S.current(rec_of(env, "Q01"))["runs"][0]]
    assert GC.read_json(env.out / run["root"] / "prompts" / f"{run['run_id']}.json")["pin"]["claude_version"] == "9.9.10"
    env.prereg.write_text(env.prereg.read_text(encoding="utf-8").replace(line, "a reworded line"), encoding="utf-8")
    assert any("anchor" in p for p in check(env.paths))


# ---------------------------------------------------------------- HO-4: F2 checks F1 and the trigger's own files
def test_freeze_checks_the_f1_manifest_before_anything(env):
    to_kay(env)
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    with pytest.raises(HoError, match="F1-frozen files changed"):
        freeze(env, f1_check=lambda p: ["mech_g.py is not the F1 manifest's"])
    assert not env.paths.frozen.exists()


@needs_store
def test_prod_trigger_pins_the_routing_files_and_lexicon_it_loads(monkeypatch):
    """§4.3 (D15): the files the trigger loads besides backend_pins() are g_common.trigger_pins(), at their kept
    sha256 (TRIGGER_PINS_SHA256) and in the F1 manifest: a change of any one, or a manifest without them, refuses."""
    import f1_g as F1
    pins = F1.prod_pins()
    assert GC.trigger_pins() == GC.TRIGGER_PINS_SHA256 and set(GC.TRIGGER_PINS_SHA256) <= set(pins)
    assert FZ.LEXICON is GC.ROUTING_LEXICON and FZ.TRIGGER_FILES is GC.PROD_TRIGGER_FILES
    assert set(FZ.TRIGGER_FILES) <= set(GC.BACKEND_PIN_FILES) and not hasattr(FZ, "TRIGGER_EXTRA_SHA256")
    assert callable(FZ.prod_trigger(pins))
    for key in GC.TRIGGER_PINS_SHA256:
        with pytest.raises(HoError, match="differ"):                     # the F1 manifest names another sha256
            FZ.prod_trigger({**pins, key: "0" * 64})
        with pytest.raises(HoError, match="differ"):                     # the file changed since its kept sha256
            FZ.prod_trigger(pins, trigger_pins=lambda k=key: {**GC.trigger_pins(), k: "0" * 64})
    with pytest.raises(HoError, match="differ"):                         # a manifest of backend_pins() only
        FZ.prod_trigger(GC.backend_pins())
    monkeypatch.setitem(GC.TRIGGER_PINS_SHA256, "packages/ragcommon/routing.py", "0" * 64)
    with pytest.raises(HoError, match="differ"):
        FZ.prod_trigger(pins)


@needs_store
def test_prod_trigger_hashes_again_the_lexicon_bytes_it_parses(tmp_path, monkeypatch):
    """§4.3 (review m04): the lexicon bytes the trigger parses are hashed again after the pin check; bytes that
    differ from TRIGGER_PINS_SHA256 there (a change between the check and the load) refuse."""
    import f1_g as F1
    other = tmp_path / GC.ROUTING_LEXICON.name
    other.write_bytes(GC.ROUTING_LEXICON.read_bytes() + b"\n")
    monkeypatch.setattr(FZ, "LEXICON", other)                          # the pin check still hashes the store file
    with pytest.raises(HoError, match="changed while loading"):
        FZ.prod_trigger(F1.prod_pins())


# ---------------------------------------------------------------- HO-5: logged infrastructure fixes
def test_an_exhausted_job_holds_every_runner_until_a_logged_infra_fix(env):
    env.fake.on("Q03", "audit", *[Reply(mode="infra")] * (1 + GC.MAX_INFRA_RETRIES))
    with pytest.raises(RU.InfraStop):
        pilot(env)
    stop = S.open_stop(state(env))
    assert stop["kind"] == "infra" and [j["qid"] for j in stop["jobs"]] == ["Q03"]
    assert R.status(env.paths)["open_stop"] == "infra"
    n = len(env.fake.calls)
    for fix, why in ((None, "log the fix in 執行紀錄"), ("infra fix: a line that is not in the log", "not a whole line"),
                     ("K0 synthetic log line one", "before this step")):
        with pytest.raises(HoError, match=why):
            pilot(env, infra_fix=fix)
    assert len(env.fake.calls) == n
    line = log_line(env, "infra fix: synthetic audit reruns of Q03")
    pilot(env, infra_fix=line)
    assert rec_of(env, "Q03")["status"] == S.PASSED and S.open_stop(state(env)) is None
    assert labels(env, rec_of(env, "Q03")["attempts"][0]) == ["draft"] + ["audit"] * (2 + GC.MAX_INFRA_RETRIES)
    with pytest.raises(HoError, match="no infrastructure stop"):
        pilot(env, infra_fix=log_line(env, "infra fix: nothing to resume from"))
    R.kp(env.paths, g1_fn=G1_PASS)
    env.fake.on("Q13", "draft", *[Reply(mode="infra")] * (1 + GC.MAX_INFRA_RETRIES))
    with pytest.raises(RU.InfraStop):
        R.main_phase(env.paths, ctx(env), f1_check=OK)
    with pytest.raises(HoError, match="used by an earlier"):
        R.main_phase(env.paths, ctx(env), f1_check=OK, infra_fix=line)
    R.main_phase(env.paths, ctx(env), f1_check=OK, infra_fix=log_line(env, "infra fix: synthetic draft reruns of Q13"))
    assert S.with_status(state(env), ORDER, S.PASSED) == ORDER


# ---------------------------------------------------------------- HO-6 and Kay's page: K-Kay, drops, revisions
def test_k_kay_reached_during_kay_work_launches_nothing_more(env):
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    s = state(env)["kay"]["sampled"]
    for x in s[2:5]:
        env.fake.on(QID[x], "audit", Reply(audit(QID[x], severity="major")))
    K.apply(env.paths, accept_all(env, questions={s[0]: DROP, s[1]: DROP, **{x: REVISE for x in s[2:5]}}))
    n = len(env.fake.calls)
    R.kay_work(env.paths, ctx(env, parallel=1), f1_check=OK)
    rec = GC.read_json(env.paths.kay)
    assert rec["rule"] == "K-Kay" and rec["n_dropped"] == 3 and len(env.fake.calls) - n == 2
    with pytest.raises(HoError, match="stopped the line"):
        R.kay_work(env.paths, ctx(env), f1_check=OK)


def test_kay_drops_close_their_slots_and_a_cap_stopped_revision_counts_for_k_kay(env):
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    with pytest.raises(HoError, match="Kay's page is drawn"):
        R.main_phase(env.paths, ctx(env), f1_check=OK)
    s = state(env)["kay"]["sampled"]
    K.apply(env.paths, accept_all(env, questions={s[0]: DROP, s[1]: DROP, s[2]: REVISE}))
    st = state(env)
    assert [S.slot(st, x)["status"] for x in s[:2]] == [S.KAY_DROPPED] * 2
    assert [S.slot(st, x)["close"]["cause"] for x in s[:2]] == ["kay", "kay"]
    inject_spend(env, 47.6)
    n = len(env.fake.calls)
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    r = S.slot(state(env), s[2])
    assert len(env.fake.calls) == n and r["status"] == S.CAP_STOPPED and K._revision(r)["status"] == "cap_stopped"
    rec = GC.read_json(env.paths.kay)
    assert (rec["n_dropped"], rec["rule"], rec["revisions_failed"]) == (3, "K-Kay", [s[2]])


def test_a_kay_revision_that_fails_mech_or_turns_into_row_3_is_a_kay_drop(env):
    through_main(env)
    K.draw(env.paths, verses=lambda k: [])
    s = state(env)["kay"]["sampled"]
    q0, q1 = QID[s[0]], QID[s[1]]
    env.fake.on(q0, "fix-kay", Reply(revised(q0, q=question(q0) + BAD_Q)))
    env.fake.on(q1, "fix-kay", Reply(revised(q1, gold(q1) + 3)))
    env.fake.on(q1, "audit", Reply(audit(q1, gold(q1) + 3)))
    K.apply(env.paths, accept_all(env, questions={s[0]: REVISE, s[1]: REVISE}))
    n = len(env.fake.calls)
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    new = env.fake.calls[n:]
    assert [c["label"] for c in new if c["job"]["qid"] == q0] == ["fix-kay"]
    assert [c["label"] for c in new if c["job"]["qid"] == q1] == ["fix-kay", "audit"]
    st = state(env)
    for x in s[:2]:
        assert S.slot(st, x)["status"] == S.KAY_DROPPED and K._revision(S.slot(st, x))["status"] == "failed"
    rec = GC.read_json(env.paths.kay)
    assert rec["revisions_failed"] == sorted(s[:2]) and rec["n_dropped"] == 2 and not rec["stop"] and rec["final"]
    freeze(env)
    assert sorted(GC.read_json(env.paths.frozen)["attrition"]["kay"]) == sorted(s[:2])


def test_after_kays_keep_an_ended_attempt_fails_a_row_3_result_is_another_quantity_and_kept_errors_stay_kept(env):
    f = env.fake
    f.on("Q01", "draft", Reply(drafted("Q01", q=question("Q01") + BAD_Q)))
    f.on("Q01", "fix-mech", no_change("Q01", question("Q01") + BAD_Q))
    f.on("Q01", "audit", Reply(audit("Q01", severity="major")))
    f.on("Q01", "fix-audit", Reply({"status": "dropped", "reason": "cannot be saved", "item": None}))
    f.on("Q02", "draft", Reply(drafted("Q02", gold("Q02") + 3, question("Q02") + BAD_Q)))
    f.on("Q02", "fix-mech", no_change("Q02", question("Q02") + BAD_Q, gold("Q02") + 3))
    f.on("Q02", "audit", Reply(audit("Q02", gold("Q02") + 3)))
    f.on("Q04", "draft", Reply(drafted("Q04", q=question("Q04") + BAD_Q)))           # the kept numeral survives a fix
    f.on("Q04", "fix-mech", no_change("Q04", question("Q04") + BAD_Q))
    f.on("Q04", "audit", Reply(audit("Q04", severity="major")))
    f.on("Q04", "fix-audit", Reply(revised("Q04", q=question("Q04", "裏") + BAD_Q)))
    pilot(env)
    assert [rec_of(env, q)["dispute"]["kind"] for q in ("Q01", "Q02", "Q04")] == ["no_change"] * 3
    to_kay(env, disputes={SID[q]: {"decision": "keep"} for q in ("Q01", "Q02", "Q04")})
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    a, b, c = rec_of(env, "Q01"), rec_of(env, "Q02"), rec_of(env, "Q04")
    assert (a["status"], a["close"]["why"], S.attempts_used(a)) == (S.FAILED, "post_kay", 1)
    assert b["status"] == S.OTHER_QUANTITY and S.current(b)["late_dispute"]["kind"] == "program_differs"
    assert c["status"] == S.PASSED and labels(env, S.current(c))[-3:] == ["audit", "fix-audit", "audit"]
    out = freeze(env)
    att = GC.read_json(env.paths.frozen)["attrition"]
    assert (att["failed"], att["other_quantity"]) == ([SID["Q01"]], [SID["Q02"]])
    assert out["counts"]["failed_by_why"] == {"post_kay": 1}


# ---------------------------------------------------------------- the hard cap and the wave order
def test_an_attempt_that_ends_after_the_hard_cap_closes_cap_stopped(env):
    pilot(env)
    R.kp(env.paths, g1_fn=G1_PASS)
    inject_spend(env, 46.0)
    env.fake.cost.update(draft=1.0, audit=0.5)
    q = QID[ORDER[12]]
    env.fake.on(q, "audit", Reply(audit(q, severity="major")), Reply(audit(q, severity="major")))
    R.main_phase(env.paths, ctx(env), f1_check=OK)
    r = S.slot(state(env), ORDER[12])
    assert (r["status"], S.attempts_used(r)) == (S.CAP_STOPPED, 1) and state(env)["drafting_stopped"]
    assert labels(env, r["attempts"][0]) == ["draft", "audit", "fix-audit", "audit"]


def test_a_waiting_job_runs_before_a_new_draft(env):
    R.pilot(env.paths, ctx(env, parallel=1), f1_check=OK)
    order = [(c["job"]["qid"], c["label"]) for c in env.fake.calls]
    assert order[:4] == [("Q01", "draft"), ("Q01", "audit"), ("Q02", "draft"), ("Q02", "audit")]


# ---------------------------------------------------------------- K-P's inputs and the G1 contract
def test_kp_counts_opened_and_passed_pilot_slots_and_spends_only_the_pilot_root(env):
    env.fake.on("Q03", "draft", Reply(drafted("Q03", gold("Q03") + 3)))
    env.fake.on("Q03", "audit", Reply(audit("Q03", gold("Q03") + 3)))
    pilot(env)
    st, q12 = state(env), SID["Q12"]
    st["slots"][q12]["attempts"] = []
    S.save_state(env.paths, S.close(st, q12, S.CAP_STOPPED, "a pilot slot never opened (test)"))
    inject_spend(env, 10.0)
    doc = R.kp(env.paths, g1_fn=G1_PASS)
    assert (doc["opened"], doc["passed"]) == (11, 10)
    assert doc["pilot_spent_usd"] == pytest.approx(2.4) and doc["spent_usd"] == pytest.approx(10.0)
    assert doc["per_slot_usd"] == pytest.approx(2.4 / 11, abs=1e-6)
    assert doc["n_kp"] == PW.kp_n(10, 11, doc["n_target"]) and doc["n_target"] == 16


def test_g1_contract_needs_pass_the_gt_nail_the_threshold_and_the_f1a_pins():
    good = {"schema": S.G1_SCHEMA, "R_card": 45, "R_wrong": 1, "n_v": 50, "g1": 0.9, "pass": True,
            "gt_zero_trigger": True, "f1a_pins_sha256": "a" * 64}
    assert S.g1_problems(good, "a" * 64) == [] and S.g1_problems(good, None)
    for bad, why in (({"gt_zero_trigger": False}, "G1 did not pass"), ({"pass": False}, "G1 did not pass"),
                     ({"g1": 0.69}, "below 0.70"), ({"f1a_pins_sha256": "b" * 64}, "other F1a pins"),
                     ({"R_card": True}, "not a count"), ({"n_v": 0}, "n_v is 0"), ({"schema": "x"}, "is not")):
        assert any(why in p for p in S.g1_problems({**good, **bad}, "a" * 64)), why


# ---------------------------------------------------------------- F2 steps 1 and 2
def test_freeze_step_1_and_2_refuse_what_changed_after_the_commit(env):
    env.fake.on("Q01", "draft", Reply(drafted("Q01", q=question("Q01") + BAD_Q)))
    env.fake.on("Q01", "fix-mech", no_change("Q01", question("Q01") + BAD_Q))
    pilot(env)
    to_kay(env, disputes={SID["Q01"]: {"decision": "keep"}})
    R.kay_work(env.paths, ctx(env), f1_check=OK)
    good, q1, q2 = state(env), SID["Q01"], SID["Q02"]
    s0 = good["kay"]["sampled"][0]

    def refused(edit, why: str) -> None:
        st = copy.deepcopy(good)
        edit(st)
        S.save_state(env.paths, st)
        with pytest.raises(HoError, match=why):
            freeze(env)
        assert not env.paths.frozen.exists()

    refused(lambda st: S.current(st["slots"][q2])["item"].update(question=question("Q02") + BAD_Q), "Q02: mech v_number")
    refused(lambda st: S.current(st["slots"][q1])["item"].update(
        question=(question("Q01") + BAD_Q).replace("創世記", "聖經")), "Q01: mech v_source")
    refused(lambda st: st["kay"]["decisions"]["questions"][s0].update(decision="drop"), "Kay's drop but the slot is")
    S.save_state(env.paths, good)
    assert freeze(env)["counts"]["n"] == 16


# ---------------------------------------------------------------- the launcher's keyword arguments
def test_run_job_calls_the_real_run_reserved_with_launch_keywords(env, monkeypatch):
    monkeypatch.setattr(CL, "run_reserved", T.REAL_RUN_RESERVED)
    seen = []

    def launch(*a, **kw):
        bound = inspect.signature(T.REAL_LAUNCH).bind(*a, **kw)
        seen.append(bound.arguments)
        b = bound.arguments
        return T.write_run(Path(b["root"]), b["run_id"], b["system_prompt"], b["user_prompt"], b["schema"],
                           b["budget_usd"], b["model"], b["pin"], b["user_scope"],
                           {"cwd": b.get("cwd", CL.AGENT_CWD), "effort": b["effort"], "tools_mode": b["tools_mode"],
                            "tool_values": b["tool_values"], "extra_record": b["extra_record"]}, Reply(drafted("Q01")))
    monkeypatch.setattr(CL, "launch", launch)
    c = ctx(env)
    job = RU.job_for(S.new_state(c.plan), c, "S00", "pilot", True)
    out = RU.run_job(c, job)
    assert not out.stopped and out.tries[0].result.error is None and seen[0]["user_scope"] == "prompt"
    assert (env.paths.root("pilot") / "reserve" / f"{out.tries[0].run_id}.json").is_file()


# ---------------------------------------------------------------- the store: CPU gold trace and the window scan
@needs_store
def test_cpu_gold_trace_agrees_with_the_gold_on_every_pool_slot():
    pool = GC.read_json(GC.POOL)["pool"]
    n_ok = n_text = 0
    for row in pool:
        first = RU.cpu_gold_trace(row, {"steps": []}, {"value": None})
        cited = {"steps": [{"verse": k} for k in first["reader_verses"]], "answer": {"value": row["gold"]}}
        t = RU.cpu_gold_trace(row, cited, {"value": row["gold"]})
        n_ok += bool(t["agrees"] and not t["cited_not_read"] and not t["read_not_cited"] and not t["unresolved_cited"]
                     and t["writer_value"] == t["auditor_value"] == t["gold"])
        n_text += all(RU.verse_text(k) for k in first["reader_verses"])
    assert (len(pool), n_ok, n_text) == (58, 58, 58)


SCANNED = ("state_g.py", "runs_g.py", "run_ho_g.py", "kay_g.py", "freeze_g.py")


def _windows(s: str) -> set[str]:
    return {s[i:i + 8] for i in range(len(s) - 7)}


@needs_store
def test_ho_files_share_no_8_character_window_with_scripture_or_real_questions():
    texts = [json.loads(x)["text"] for x in T.TEXT.read_text(encoding="utf-8").splitlines() if x.strip()]
    for f in ("ground_truth.json", "ground_truth.v2.json"):
        texts += [q["question"] for q in GC.read_json(GC.REPO / f)["questions"]]
    for p in (GC.STORE / "reports/kg_cards_20261018/A_confirm/questions_frozen.json", GC.STAGE0_OUT / "items.json"):
        doc = GC.read_json(p)
        texts += [q["question"] for q in doc.get("questions") or doc.get("items") or ()]
    real = set().union(*(_windows(t) | _windows(unicodedata.normalize("NFKC", t)) for t in texts))
    mine = set()
    for p in [T.H / n for n in SCANNED] + [Path(T.__file__), Path(__file__)]:
        src = p.read_text(encoding="utf-8")
        strings = [n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        mine |= _windows(src) | _windows(unicodedata.normalize("NFKC", src)) | set().union(*map(_windows, strings))
    n_texts, n_shared = len(texts), len({w for w in mine & real if any("㐀" <= ch <= "鿿" for ch in w)})
    assert n_texts > 31000, f"only {n_texts} reference texts"
    assert n_shared == 0, f"{n_shared} shared 8-character windows"
