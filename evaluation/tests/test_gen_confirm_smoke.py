"""GEN confirmation set: the smoke, its redo and its truncation void (smoke_g, void_g, run_g; prereg §4.4, §4.5, §9).

Ollama and every LLM are never called: the chats and /api answers are test_gen_confirm_run's fakes, and every run
root, log and harness record is a tmp one (its ``root`` and ``logged`` fixtures; the void record sits beside the
tmp run root; every later store path points into tmp, its autouse ``later_store_files_in_tmp``), so nothing is
written to the store or the repository. Covered: the smoke jobs; a truncation keeps
the formal run from starting; a void or a truncated smoke is set aside by --redo under one whole log line, unused
and newer than the log at K0 and at every redo, a truncated one only when it ran with §4.3's options (D5); a
truncation with no infrastructure cause is 作廢 by --void-truncated, once, under the same anchor rule; after any
void (this one or F2's parity void, the same record, D6) smoke, run, score and dry-run refuse and analyze writes
only the void sentence; an unreadable record voids too.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

from test_gen_confirm_run import (NEW_LINE, OLD_LINE, QUIET, A, Api, Chat, F1, GC, R,  # noqa: E402,F401
                                  built, fake_jobs, later_store_files_in_tmp, logged, root, src_of)
import smoke_g as SM  # noqa: E402
import void_g as V  # noqa: E402

TRUNC = "作廢（截斷），不構成任何方向的證據"
NO_ARGS = SimpleNamespace(out=None, jobs_unrecoverable=False, infra_fix=None, canary_fixed=None, redo=None,
                          void_truncated=None)


def add_line(logged, line: str) -> str:
    with logged.pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {line}\n")
    return line


def truncated_smoke(js: list[dict]) -> dict:
    return R.execute(R.store("smoke"), SM.smoke_jobs(js), "smoke", chat=Chat(done_reason="length"), get=Api(), **QUIET)


def test_smoke_takes_the_two_longest_rep_1_prompts_per_arm(built):
    _doc, b = built
    sj = SM.smoke_jobs(b["jobs"])
    assert {j["rep"] for j in sj} == {1} and len(sj) == 2 * len({j["arm"] for j in b["jobs"]})
    for arm in A.ARMS:
        mine = [j for j in b["jobs"] if j["arm"] == arm and j["rep"] == 1]
        if mine:
            longest = sorted(len(j["user"]) for j in mine)[-2:]
            assert sorted(len(j["user"]) for j in sj if j["arm"] == arm) == longest
    assert [j["job_id"] for j in sj] == [j["job_id"] for j in b["jobs"] if j in sj]
    assert SM.smoke_jobs is not None and not hasattr(R, "smoke_jobs")           # moved out of run_g (D5)


def test_a_truncated_smoke_keeps_the_formal_run_from_starting(root, logged):
    """§4.4 (RUN-2 R4): any truncation in the smoke is an infrastructure problem; no formal run."""
    js = fake_jobs(4)
    sj = SM.smoke_jobs(js)
    assert SM.smoke_problems(js) == ["no smoke yet (§4.4)"]
    meta = truncated_smoke(js)
    st = SM.smoke_status(R.store("smoke"), sj, meta)
    assert st["truncated"] == sorted(j["job_id"] for j in sj) and st["infra_problem"] and not st["pass"]
    (p,) = SM.smoke_problems(js)
    assert p.startswith("the smoke truncated 2 calls: an infrastructure problem, no formal run (§4.4)")
    assert "smoke --redo ANCHOR" in p and "smoke --void-truncated ANCHOR" in p


def test_a_truncated_smoke_is_redone_only_under_a_new_anchor_and_section_4_3s_options(root, logged, monkeypatch):
    """§4.4, §4.3 (D5): a truncated smoke is set aside like a void one, under a new unused anchor, when it ran with
    the options the redo uses (they never change); the record says kind truncated."""
    js = fake_jobs(4)
    truncated_smoke(js)
    meta_p = R.store("smoke") / R.RUN_META
    for bad in (OLD_LINE, NEW_LINE[:-3], "不在紀錄裡的一行錨點文字"):
        with pytest.raises(SystemExit, match="anchor"):
            SM.smoke_redo(bad, **QUIET)
    meta = GC.read_json(meta_p)
    assert meta["options"] == R.OPTIONS == GC.OLLAMA_OPTIONS == {"temperature": 0.1, "num_predict": 10000,
                                                                   "num_ctx": 131072}
    GC.write_json(meta_p, {**meta, "options": {**meta["options"], "num_ctx": 8192}})
    with pytest.raises(SystemExit, match="recorded Ollama options"):
        SM.smoke_redo(NEW_LINE, **QUIET)
    GC.write_json(meta_p, meta)
    with monkeypatch.context() as m:
        m.setattr(R, "OPTIONS", {**R.OPTIONS, "temperature": 0.2})
        with pytest.raises(SystemExit, match="not §4.3's"):
            SM.smoke_redo(NEW_LINE, **QUIET)
    assert meta_p.is_file()                                                       # nothing was set aside
    unused = add_line(logged, "2026-10-22 第二行：此時已在紀錄裡")
    rec = SM.smoke_redo(NEW_LINE, **QUIET)
    assert (rec["kind"], rec["moved_to"], rec["truncated"], rec["options"]) == (
        "truncated", f"{R.SMOKE_SET_ASIDE}/1", 2, GC.OLLAMA_OPTIONS)
    assert not R.store("smoke").exists() and (R.store(f"{R.SMOKE_SET_ASIDE}/1") / R.RUN_META).is_file()
    assert GC.read_json(R.store(R.SMOKE_HISTORY))["redo"] == [rec]
    truncated_smoke(js)                                                           # truncated again
    with pytest.raises(SystemExit, match="used by an earlier record"):
        SM.smoke_redo(NEW_LINE, **QUIET)
    with pytest.raises(SystemExit, match="before this step"):                    # in the log at the last redo
        SM.smoke_redo(unused, **QUIET)
    later = add_line(logged, "2026-10-23 第三行：上次重做之後才加")
    assert SM.smoke_redo(later, **QUIET)["moved_to"] == f"{R.SMOKE_SET_ASIDE}/2"
    R.execute(R.store("smoke"), SM.smoke_jobs(js), "smoke", chat=Chat(), get=Api(), **QUIET)
    assert SM.smoke_problems(js) == []
    with pytest.raises(SystemExit, match="only a void smoke"):
        SM.smoke_redo(add_line(logged, "2026-10-24 第四行：沒有東西可以重做"), **QUIET)


def test_a_void_smoke_is_set_aside_by_redo_under_a_new_anchor(root, logged):
    """§4.4, §4.5 (RUN-6, RUN-2 X2): a void smoke is never passed; smoke --redo A after a logged fix."""
    js = fake_jobs(4)
    sj = SM.smoke_jobs(js)
    api = Api()

    def flip(system, user, options=None):
        api.version = "0.33.0"
        return Chat()(system, user, options)
    meta = R.execute(R.store("smoke"), sj, "smoke", chat=flip, get=api, **QUIET)
    st = SM.smoke_status(R.store("smoke"), sj, meta)
    assert meta["state"] == "void" and st["state"] == "void" and not st["truncated"] and not st["missing"]
    assert not st["pass"]
    assert SM.smoke_problems(js)[0].startswith("the smoke is void") and "smoke --redo" in SM.smoke_problems(js)[0]
    for bad in (OLD_LINE, NEW_LINE[:-3], "不在紀錄裡的一行錨點文字"):
        with pytest.raises(SystemExit, match="anchor"):
            SM.smoke_redo(bad, **QUIET)
    assert (R.store("smoke") / R.RUN_META).is_file()
    SM.smoke_redo(NEW_LINE, **QUIET)
    moved = R.store(f"{R.SMOKE_SET_ASIDE}/1")
    assert not R.store("smoke").exists() and GC.read_json(moved / R.RUN_META)["state"] == "void"
    (h,) = GC.read_json(R.store(R.SMOKE_HISTORY))["redo"]
    assert h["anchor"] == NEW_LINE and h["moved_to"] == f"{R.SMOKE_SET_ASIDE}/1" and h["void"] and h["kind"] == "void"
    assert h["run_meta_sha256"] == GC.sha256_file(moved / R.RUN_META) and h["truncated"] == 0
    assert SM.smoke_problems(js) == ["no smoke yet (§4.4)"]
    api.version = GC.OLLAMA_VERSION
    R.execute(R.store("smoke"), sj, "smoke", chat=flip, get=api, **QUIET)              # void again
    with pytest.raises(SystemExit, match="used by an earlier record"):
        SM.smoke_redo(NEW_LINE, **QUIET)
    again = add_line(logged, "2026-10-23 再修正：鎖定伺服器的版本")
    assert SM.smoke_redo(again, **QUIET)["moved_to"] == f"{R.SMOKE_SET_ASIDE}/2"
    assert [x["anchor"] for x in GC.read_json(R.store(R.SMOKE_HISTORY))["redo"]] == [NEW_LINE, again]
    R.execute(R.store("smoke"), sj, "smoke", chat=Chat(), get=Api(), **QUIET)
    assert SM.smoke_problems(js) == []
    with pytest.raises(SystemExit, match="only a void smoke"):
        SM.smoke_redo(NEW_LINE, **QUIET)
    assert SM.smoke_problems([dict(j, user=j["user"] + "多一字") for j in js]) == ["the smoke ran other jobs"]


def test_a_smoke_with_missing_calls_resumes_and_is_not_redone(root, logged):
    js = fake_jobs(4)
    sj = SM.smoke_jobs(js)
    R.execute(R.store("smoke"), sj, "smoke", chat=Chat(fail_users={sj[0]["user"]}), get=Api(), **QUIET)
    assert SM.smoke_problems(js) == ["smoke not passed (missing 1, state ok): resume smoke"]
    with pytest.raises(SystemExit, match="only a void smoke"):
        SM.smoke_redo(NEW_LINE, **QUIET)


def stub_gates(monkeypatch) -> None:
    """Every §4.5 gate but the void record passes (the void must refuse on its own)."""
    for mod, name in ((F1, "git_problems"), (F1, "harness_problems"), (R, "stage0_problems"), (R, "pin_problems"),
                      (R, "f2_problems")):
        monkeypatch.setattr(mod, name, lambda *a, **k: [])
    monkeypatch.setattr(R.X.c_common, "frozen_mismatches", lambda: [])
    monkeypatch.setattr(R, "metric_version", lambda: GC.METRIC_VERSION)


def test_a_truncation_without_a_cause_is_void_once_and_every_command_refuses_after(root, logged, monkeypatch):
    """§4.4, §9 (D5): smoke --void-truncated A writes the one void record (「作廢（截斷）…」) once, under a new unused
    anchor; then smoke, run, score and dry-run refuse and analyze writes only the void sentence."""
    js, void = fake_jobs(4), R.void_file()
    assert void == root.parent / "void.json" and V.problems(void) == []
    with pytest.raises(SystemExit, match="there is no smoke"):
        SM.void_truncated(NEW_LINE, jobs=js, **QUIET)
    R.execute(R.store("smoke"), SM.smoke_jobs(js), "smoke", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="did not truncate"):
        SM.void_truncated(NEW_LINE, jobs=js, **QUIET)
    R.cli_out(R.store("smoke")).rename(root / "set_aside_by_hand")
    truncated_smoke(js)
    SM.smoke_redo(NEW_LINE, **QUIET)                                               # a logged fix, then again
    truncated_smoke(js)
    with pytest.raises(SystemExit, match="other jobs"):
        SM.void_truncated(add_line(logged, "2026-10-23 換了別的工作清單"), jobs=fake_jobs(5)[1:], **QUIET)
    for bad, why in ((OLD_LINE, "before this step"), (NEW_LINE, "used by an earlier record"),
                     ("不在紀錄裡的一行錨點文字", "not a whole line")):
        with pytest.raises(SystemExit, match=why):
            SM.void_truncated(bad, jobs=js, **QUIET)
    assert not void.exists()
    line = add_line(logged, "2026-10-24 查無原因：截斷記作廢")
    rec = SM.void_truncated(line, jobs=js, **QUIET)
    assert (rec["why"], rec["label"], rec["anchor"], rec["sentence"]) == ("truncation", "截斷", line, TRUNC)
    assert rec["detail"]["truncated"] == 2 and V.read(void) == rec
    assert V.problems(void) == [f"the line is void (截斷; void.json): {TRUNC}"]
    with pytest.raises(SystemExit, match="recorded once"):
        SM.void_truncated(add_line(logged, "2026-10-25 第二次作廢的嘗試"), jobs=js, **QUIET)
    for args in (SimpleNamespace(**{**vars(NO_ARGS), "void_truncated": line}),
                 SimpleNamespace(**{**vars(NO_ARGS), "redo": line}), NO_ARGS):
        with pytest.raises(SystemExit, match="smoke refused.*the line is void"):
            SM.smoke(args, get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="formal run refused.*the line is void"):
        R.run(NO_ARGS, get=Api(), chat=Chat(), **QUIET)
    with pytest.raises(SystemExit, match="score refused.*the line is void"):
        R.score(NO_ARGS)
    with pytest.raises(SystemExit, match="dry-run refused.*the line is void"):
        R.dry_run(**QUIET)
    stub_gates(monkeypatch)
    assert R.gate_problems(prereg=logged.pre)[0] == V.problems(void)[0]
    rep = R.analyze(NO_ARGS)
    assert rep["verdict"]["result"] == "作廢" and rep["verdict"]["sentence"] == TRUNC and rep["void_only"]
    md = (R.store("formal") / GC.RUN_REPORT_MD).read_text(encoding="utf-8")
    assert GC.read_json(R.store("formal") / GC.RUN_REPORT) == rep and md.count("\n- ") == 1 and TRUNC in md
    assert R.analyze(SimpleNamespace(**{**vars(NO_ARGS), "out": R.store("dry_run")}))["verdict"]["sentence"] == TRUNC


def test_void_truncated_refuses_a_cause_to_fix_or_an_unfinished_smoke(root, logged):
    """§4.4, §4.3 (review m07): a truncated smoke that ran with other options than §4.3's or is void (digest or
    Ollama version) has an infrastructure cause (fixed, then smoke --redo), one with a call unanswered or no agreeing
    after-check is resumed: neither is voided. A finished clean truncated smoke is."""
    js, void = fake_jobs(4), R.void_file()
    sj, line = SM.smoke_jobs(js), add_line(logged, "2026-10-24 查無原因：截斷記作廢")
    R.execute(R.store("smoke"), sj, "smoke", chat=Chat(fail_users={sj[0]["user"]}, done_reason="length"), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match=r"not finished \(state ok, missing 1\)"):
        SM.void_truncated(line, jobs=js, **QUIET)
    truncated_smoke(js)                                                            # resumed: every call answered
    meta_p = R.store("smoke") / R.RUN_META
    meta = GC.read_json(meta_p)
    flip = {**meta["checks"][-1], "version": "0.33.0"}
    cases = {"recorded Ollama options": {**meta, "options": {**meta["options"], "num_ctx": 8192}},
             "the smoke is void": {**meta, "checks": meta["checks"] + [flip]},
             r"not finished \(state unfinished": {**meta, "checks": meta["checks"][:-1]}}
    for why, bad in cases.items():
        GC.write_json(meta_p, bad)
        with pytest.raises(SystemExit, match=f"--void-truncated refused.*{why}"):
            SM.void_truncated(line, jobs=js, **QUIET)
        assert not void.exists()
    GC.write_json(meta_p, meta)
    assert SM.void_truncated(line, jobs=js, **QUIET)["detail"]["truncated"] == len(sj) and V.problems(void)


def test_void_truncated_through_the_command_reads_the_store_builds_smoke_jobs(built, root, logged, monkeypatch):
    """§4.4 (review m06): ``smoke --void-truncated A`` takes the smoke jobs of the store build (load_inputs), so a
    smoke of another job list is refused and the store build's truncated smoke is voided."""
    doc, _b = built
    monkeypatch.setattr(R, "f2_problems", lambda *a, **k: [])
    R.build(src=src_of(doc), **QUIET)
    js = R.load_inputs()[GC.RUN_JOBS]
    args = SimpleNamespace(**{**vars(NO_ARGS), "void_truncated": add_line(logged, "2026-10-24 查無原因：截斷記作廢")})
    truncated_smoke(fake_jobs(4))
    with pytest.raises(SystemExit, match="other jobs than the store build's"):
        SM.smoke(args, get=Api(), **QUIET)
    R.cli_out(R.store("smoke")).rename(root / "set_aside_by_hand")
    truncated_smoke(js)
    rec = SM.smoke(args, get=Api(), **QUIET)
    assert rec["why"] == "truncation" and rec["detail"]["n_jobs"] == len(SM.smoke_jobs(js)) > 0
    assert rec["detail"]["jobs_sha256"] == A.prompts_sha256(SM.smoke_jobs(js)) and V.problems(R.void_file())


def test_an_unreadable_void_record_still_voids(root, logged):
    """A record that cannot be read, or lacks its why, label or sentence (review m08), voids of unknown cause."""
    void, unreadable = R.void_file(), ["void.json exists but cannot be read: the line is treated as void"]
    void.write_text("{not json", encoding="utf-8")
    assert V.problems(void) == unreadable
    with pytest.raises(SystemExit, match="smoke refused"):
        SM.smoke(NO_ARGS, get=Api(), **QUIET)
    for doc in ({"why": "other"}, {"why": "parity"}, {"why": "truncation", "label": "截斷"},
                {"why": "parity", "label": "", "sentence": TRUNC}, {"why": "parity", "label": "x", "sentence": 1}):
        GC.write_json(void, doc)
        assert V.read(void)["unreadable"] and V.problems(void) == unreadable, sorted(doc)


def test_the_void_record_lives_beside_the_run_root_and_f2_json_in_the_store():
    """D6: one file for both voids (F2's parity void and the smoke's truncation void), OUT_ROOT/void.json."""
    import f2_g as F2
    assert R.void_file() == F2.void_path(F2.OUT) == GC.VOID_FILE == GC.OUT_ROOT / "void.json"
    assert V.WHYS == ("parity", "truncation") and V.sentence("truncation") == TRUNC
    assert V.sentence("parity") == "作廢（prompt 對等），不構成任何方向的證據"
