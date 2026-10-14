"""GD experiment §7 HO executors and freeze (ho_tools/_ho_claude.py, _ho_runs.py, freeze.py).

No agent is launched: the claude command line, environment and cwd are checked as values,
launches are monkeypatched, and agent outputs are synthetic. Store tests build questions
from verses outside the NEW82 ∪ OLD31 gold and synthetic transcripts (a blinding breach in
any run drops its question at commit); freeze writes only under tmp_path and must refuse
pilot data. The formal-root guard is never patched: only its V1 half is tested alone.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
for _p in (str(_DIR / "ho_tools"), str(_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = importlib.import_module("_ho_common")
gd = H.gd
C = importlib.import_module("_ho_claude")
RU = importlib.import_module("_ho_runs")
S = importlib.import_module("_ho_state")
P = importlib.import_module("_ho_prompts")
M = importlib.import_module("mech_check")
F = importlib.import_module("freeze")
kay = importlib.import_module("sample_kay")

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# ---------------------------------------------------------------- the claude command line

def test_argv_pins_model_tools_permissions_and_transcript_format():
    argv = C.build_argv("SYSTEM", "USER", P.AUDIT_SCHEMA, 5)
    def after(flag, n=1):
        i = argv.index(flag)
        return argv[i + 1:i + 1 + n]
    assert argv[:3] == ["claude", "-p", "USER"] and after("--system-prompt") == ["SYSTEM"]
    assert after("--model") == ["claude-opus-5-5"] and after("--tools") == ["Bash"]
    assert after("--thinking-display") == ["summarized"]          # else thinking is empty
    assert after("--allowedTools") == ["Bash(bt *)"]
    assert {"Read", "Edit", "Write", "Glob", "Grep", "WebFetch", "WebSearch", "Task"} <= set(
        after("--disallowedTools", len(C.DISALLOWED_TOOLS)))
    assert after("--permission-mode") == ["dontAsk"] and after("--setting-sources") == ["local"]
    assert after("--output-format") == ["stream-json"] and "--verbose" in argv
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert "--safe-mode" not in argv                  # it would drop the guard hook
    hook = json.loads(after("--settings")[0])["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "*" and hook["hooks"][0]["command"] == "bt-guard"
    assert json.loads(after("--json-schema")[0]) == P.AUDIT_SCHEMA


def test_child_env_drops_claude_variables_and_points_bt_at_the_state(tmp_path):
    env = C.child_env(tmp_path, {"CLAUDECODE": "1", "CLAUDE_EFFORT": "max", "claude_x": "y",
                                 "PATH": "/usr/bin", "HOME": "/h"})
    assert not [k for k in env if k.upper().startswith("CLAUDE")]
    assert env["PATH"] == f"{tmp_path / 'bin'}:/usr/bin" and env["HOME"] == "/h"
    assert env[C.STATE_ENV] == str(tmp_path / "state.json")


def test_agent_cwd_must_be_an_empty_directory_outside_the_repo(tmp_path):
    assert C.check_cwd(tmp_path) == tmp_path
    for bad in (H.REPO_ROOT, H.EXP_DIR, Path("/"), tmp_path / "missing"):
        with pytest.raises(H.HoToolError):
            C.check_cwd(bad)
    (tmp_path / "x").write_text("x")
    with pytest.raises(H.HoToolError):
        C.check_cwd(tmp_path)


def test_wrappers_run_the_ho_tools_copies_and_hide_bt_stderr(tmp_path):
    content = C.write_wrappers(tmp_path)
    bt, guard = (tmp_path / "bin" / n for n in (C.BT_WRAPPER, C.GUARD_WRAPPER))
    assert f"{H.HO_DIR / 'bt.py'} \"$@\" 2>/dev/null" in bt.read_text()
    assert str(H.HO_DIR / "bt_guard.py") in guard.read_text()
    assert bt.stat().st_mode & 0o111 and content[C.BT_WRAPPER] == bt.read_text()


def test_transcript_parsing_and_usage(tmp_path):
    path = tmp_path / "t.jsonl"
    lines = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
             {"type": "result", "subtype": "success", "num_turns": 3, "total_cost_usd": 0.5,
              "usage": {"input_tokens": 7, "output_tokens": 11, "output_tokens_details": {"thinking_tokens": 2}}}]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n{torn")
    ev = C.read_events(path)
    u = C.usage_of(C.result_event(ev), ev)
    assert len(ev) == 2 and u["tool_calls"] == 1 and u["output_tokens"] == 11 and u["thinking_tokens"] == 2
    assert C._failure(0, None) and C._failure(0, {"subtype": "error_max_turns"})
    assert C._failure(0, {"subtype": "success"}) == "no structured output"

# ---------------------------------------------------------------- retries (基礎設施失敗 only)

def _fake_launch(outcomes, calls):
    def launch(root, run_id, system, user, schema, budget, cwd, timeout_s, extra):
        calls.append(run_id)
        (Path(root) / "transcripts").mkdir(parents=True, exist_ok=True)
        (Path(root) / "transcripts" / f"{run_id}.jsonl").write_text("")
        err, out = outcomes[len(calls) - 1]
        return C.RunResult(run_id, Path(root) / f"{run_id}.jsonl", 0, 1.0,
                           None if err else {"structured_output": out}, err)
    return launch


def _job(kind="audit", qid="H_KIN_001"):
    gen, audit = P.default_prompts()
    values = {"qid": qid, "category_line": "親屬", "used_cores": RU.NO_CORES, "item_json": "{}"}
    return RU.Job(qid, kind, qid, audit, "task_audit", values, P.AUDIT_SCHEMA, 1.0)


def test_run_agent_reruns_infrastructure_failures_at_most_twice(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(C, "launch", _fake_launch([("boom", None), (None, {"id": "H_KIN_001"})], calls))
    got = RU.run_agent(tmp_path, _job(), cwd=tmp_path)
    assert calls == ["audit_H_KIN_001_1", "audit_H_KIN_001_2"] and got[-1].error is None
    calls.clear()
    monkeypatch.setattr(C, "launch", _fake_launch([("x", None)] * 5, calls))
    assert len(RU.run_agent(tmp_path, _job(qid="H_KIN_002"), cwd=tmp_path)) == 1 + RU.MAX_RETRIES


def test_an_audit_answering_for_another_id_is_rerun(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(C, "launch", _fake_launch([(None, {"id": "H_KIN_999"}),
                                                   (None, {"id": "H_KIN_001"})], calls))
    got = RU.run_agent(tmp_path, _job(), cwd=tmp_path)
    assert len(got) == 2 and got[0].error.startswith("audit answered for id") and got[1].error is None

# ---------------------------------------------------------------- commits (store)

def free_verses(n):
    used = set(M.store_context().owners)
    vi, out = gd.load_verse_index(), {}
    for key in gd.load_verse_units().order:
        pid = vi.passage_of[key]
        if "-" not in key and not vi.split_of[key] and pid not in used and pid not in out:
            out[pid] = key
            if len(out) == n:
                return list(out.values())
    raise AssertionError("not enough free passages")


def raw_item(qid, category, keys, core):
    return {"id": qid, "category": category, "subtype": "x", "question": "問？", "answer": "答",
            "key_points": ["a", "b"], "hop_slots": [[k] for k in keys], "hop_roles": ["r"] * len(keys),
            "bridge": "", "why_multihop": "", "shortcut_search": "", "needs_identity_resolution": False,
            "notes": "", "change_log": "", "core": core}


def result(run_id, output, error=None):
    return C.RunResult(run_id, Path(f"{run_id}.jsonl"), 0, 2.0, {"structured_output": output}, error,
                       {"output_tokens": 5})


@needs_store
def test_commit_draft_lands_pending_blocked_or_abandoned():
    v = free_verses(6)
    ctx = M.store_context()
    st = S.new_state(False)
    slots = S.plan_round(st, per_round=1)
    kin, dis, to, mh = slots
    st = RU.commit_draft(st, kin, [result("g1", {"status": "drafted", "reason": "",
                                                  "item": raw_item(kin.qid, "KIN", v[:2], "甲")})], ctx)
    new82_key = gd.load_new82().questions[0].hops[0][0]
    st = RU.commit_draft(st, dis, [result("g2", {"status": "drafted", "reason": "",
                                                  "item": raw_item(dis.qid, "DIS", [new82_key, v[2]], "乙")})], ctx)
    st = RU.commit_draft(st, to, [result("g3", {"status": "abandoned", "reason": "找不到", "item": None})], ctx)
    st = RU.commit_draft(st, mh, [result("g4", {}, "no result"), result("g5", {}, "no result")], ctx)
    status = {r["id"]: r["status"] for r in st["records"]}
    assert status == {kin.qid: S.PENDING, dis.qid: S.BLOCKED, to.qid: S.ABANDONED, mh.qid: S.ABANDONED}
    assert S.record(st, kin.qid)["item"]["n_hops"] == 2 and S.record(st, kin.qid)["runs"] == ["g1"]
    assert S.blocked_by_overlap(st)["DIS"] == 1 and S.record(st, mh.qid)["infra_failure"] is True
    assert st["runs"]["g5"]["error"] == "no result"


@needs_store
def test_commit_draft_refuses_an_item_for_another_slot():
    v = free_verses(2)
    slot = S.plan_round(S.new_state(False))[3]                     # H_MH_001, SUC
    st = RU.commit_draft(S.new_state(False), slot, [result("g", {"status": "drafted", "reason": "",
                         "item": raw_item(slot.qid, "OQ", v, "甲")})], M.store_context())
    assert {m["rule"] for m in S.record(st, slot.qid)["mech"]} == {"slot_mismatch"}


@needs_store
def test_audit_and_fix_follow_section_7():
    v = free_verses(4)
    ctx = M.store_context()
    slot = S.plan_round(S.new_state(False))[0]
    st = RU.commit_draft(S.new_state(False), slot, [result("g", {"status": "drafted", "reason": "",
                         "item": raw_item(slot.qid, "KIN", v[:2], "甲")})], ctx)
    major = {"id": slot.qid, "severity": "major", "issues": ["缺平行經文"], "suggested_fix": "補", "checked": ""}
    st = RU.commit_audit(st, slot.qid, [result("a1", major)])
    rec = S.record(st, slot.qid)
    assert rec["status"] == S.NEEDS_FIX and rec["fix_request"]["source"] == "audit"
    fixed = raw_item(slot.qid, "KIN", v[2:4], "甲")
    st = RU.commit_fix(st, slot.qid, [result("f1", {"status": "revised", "reason": "", "item": fixed})], ctx)
    rec = S.record(st, slot.qid)
    assert rec["status"] == S.PENDING and rec["item"]["hop_slots"] == [[v[2]], [v[3]]]
    st2 = RU.commit_audit(st, slot.qid, [result("a2", {**major, "severity": "critical"})])
    assert S.record(st2, slot.qid)["status"] == S.DROPPED            # one fix, then 刪題
    st3 = RU.commit_audit(st, slot.qid, [result("a3", {**major, "severity": "minor"})])
    assert S.record(st3, slot.qid)["status"] == S.PASSED
    with pytest.raises(H.HoToolError):
        RU.commit_audit(st, slot.qid, [result("a4", {}, "timeout")])


def test_used_cores_lists_every_core_of_live_drafts_with_its_count():
    st = S.new_state(False)
    for i, (core, status) in enumerate([("甲", S.PASSED), ("甲", S.PENDING), ("乙", S.PASSED),
                                        ("乙", S.DROPPED), ("丙", S.NEEDS_FIX), ("丙", S.PASSED)]):
        st = S.add_record(st, S.Slot(i + 1, 1, f"H_KIN_{i + 1:03d}", "KIN", "KIN"), status, {"core": core})
    assert RU.used_cores(st) == "丙（2 題，已滿）、乙（1 題）、甲（2 題，已滿）"
    assert RU.used_cores(st, exclude="H_KIN_001") == "丙（2 題，已滿）、乙（1 題）、甲（1 題）"
    assert RU.used_cores(S.new_state(False)) == RU.NO_CORES

# ---------------------------------------------------------------- freeze

@pytest.mark.parametrize("where", ["root", "out", "manifest"])
def test_freeze_refuses_pilot_paths(tmp_path, where):
    paths = {"root": tmp_path / "ho", "out": tmp_path / "ho.json", "manifest": tmp_path / "m.json"}
    paths[where] = (H.PILOT_ROOT if where == "root" else H.PILOT_ROOT / f"{where}.json")
    with pytest.raises(H.HoToolError, match="pilot"):
        F.freeze(paths["root"], paths["out"], paths["manifest"])
    with pytest.raises(H.HoToolError, match="pilot"):
        F.freeze(tmp_path / "x" / "pilot", tmp_path / "o.json", tmp_path / "mm.json")
    assert not (tmp_path / "ho.json").exists()


def test_freeze_refuses_a_pilot_state_and_an_incomplete_selection(tmp_path):
    st = S.new_state(False)
    with pytest.raises(H.HoToolError, match="pilot"):
        F.check_ready(tmp_path, {**st, "pilot": True})
    with pytest.raises(H.HoToolError, match="not complete"):
        F.check_ready(tmp_path, st)


def _transcript(root, run_id):
    ev = [{"type": "system", "subtype": "init", "cwd": str(C.AGENT_CWD), "tools": ["Bash", "StructuredOutput"],
           "mcp_servers": [], "model": C.MODEL, "permissionMode": "dontAsk"},
          {"type": "result", "subtype": "success", "is_error": False, "structured_output": {}}]
    for d in ("transcripts", "prompts"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "transcripts" / f"{run_id}.jsonl").write_text("\n".join(json.dumps(e) for e in ev))
    (root / "prompts" / f"{run_id}.json").write_text(json.dumps({"system": "出題", "user": "任務"}))


def _transcript_with(root, run_id, *content, result_content=None):
    """A clean transcript plus one assistant message (and a tool result) in the middle."""
    _transcript(root, run_id)
    path = root / "transcripts" / f"{run_id}.jsonl"
    ev = [json.loads(line) for line in path.read_text().splitlines()]
    extra = [{"type": "assistant", "message": {"content": list(content)}}]
    if result_content is not None:
        extra.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": result_content}]}})
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [ev[0], *extra, ev[1]]))
    return C.RunResult(run_id, path, 0, 1.0, None)


def run_at(root, run_id, output, *content, error=None):
    res = _transcript_with(root, run_id, *content)
    return C.RunResult(run_id, res.transcript, 0, 1.0, {"structured_output": output}, error)


@needs_store
def test_a_blinding_breach_drops_the_question_at_commit_and_frees_its_gold(tmp_path):
    v = free_verses(4)
    ctx = M.store_context()
    kin, dis = S.plan_round(S.new_state(False))[:2]
    leak = {"type": "thinking", "thinking": "Kay 的設定提到這題"}
    drafted = {"status": "drafted", "reason": "", "item": raw_item(kin.qid, "KIN", v[:2], "甲")}
    st = RU.commit_draft(S.new_state(False), kin, [run_at(tmp_path, "g1", drafted, leak)], ctx)
    rec = S.record(st, kin.qid)
    assert rec["status"] == S.DROPPED and [t["rule"] for t in rec["transcript"]] == ["t_memory"]
    assert S.live_items(st) == [] and S.transcript_breaches(st)["KIN"] == 1
    word = {"type": "text", "text": "用 grep 檢索平行經文"}                    # agent wording: a warning
    drafted2 = {"status": "drafted", "reason": "", "item": raw_item(dis.qid, "DIS", v[:2], "乙")}
    st = RU.commit_draft(st, dis, [run_at(tmp_path, "g2", drafted2, word)], ctx)
    assert S.record(st, dis.qid)["status"] == S.PENDING and S.record(st, dis.qid)["transcript"] == []


@needs_store
def test_a_breach_in_an_audit_or_fix_run_drops_the_question_even_after_failed_attempts(tmp_path):
    v = free_verses(2)
    ctx = M.store_context()
    slot = S.plan_round(S.new_state(False))[0]
    st = RU.commit_draft(S.new_state(False), slot, [run_at(tmp_path, "g", {"status": "drafted", "reason": "",
                         "item": raw_item(slot.qid, "KIN", v, "甲")})], ctx)
    assert S.record(st, slot.qid)["status"] == S.PENDING
    path_leak = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "bt v gen.1.1"}}
    res = _transcript_with(tmp_path, "a1", path_leak, result_content="../home/x <<查無此節>>")
    failed = C.RunResult("a1", res.transcript, 1, 1.0, None, "no result event (exit 1)")
    st_a = RU.commit_audit(st, slot.qid, [failed])                     # no raise: the breach decides
    assert S.record(st_a, slot.qid)["status"] == S.DROPPED
    assert {t["rule"] for t in S.record(st_a, slot.qid)["transcript"]} == {"t_path"}
    major = {"id": slot.qid, "severity": "major", "issues": ["x"], "suggested_fix": "y", "checked": ""}
    st = RU.commit_audit(st, slot.qid, [run_at(tmp_path, "a2", major)])
    fixed = {"status": "revised", "reason": "", "item": raw_item(slot.qid, "KIN", v, "甲")}
    st = RU.commit_fix(st, slot.qid, [run_at(tmp_path, "f1", fixed, {"type": "text", "text": "依 prereg"})], ctx)
    assert S.record(st, slot.qid)["status"] == S.DROPPED and S.record(st, slot.qid)["fix_request"] is None


def test_overlap_avoided_counts_what_the_drafting_agents_met(tmp_path):
    st = S.new_state(False)
    gold = "gen.2.1 → ps:gen.2.1 衝突：舊多跳題\ngen.3.1 → ps:gen.3.1 衝突：本批其他草稿"
    call = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "bt old --gold gen.2.1 gen.3.1"}}
    for i, (qid, status, note) in enumerate([("H_KIN_001", S.PASSED, "稽核 ok"),
                                             ("H_KIN_002", S.ABANDONED, "abandoned: 段落都已被其他題目使用")]):
        st = S.add_record(st, S.Slot(i + 1, 1, qid, "KIN", "KIN"), status, None, note)
        run = f"gen_{qid}_1"
        _transcript_with(tmp_path, run, call, result_content=gold)
        st = RU.record_runs(st, qid, "gen", [C.RunResult(run, tmp_path / "transcripts" / f"{run}.jsonl", 0, 1.0, None)])
    _transcript_with(tmp_path, "audit_H_KIN_001_1", call, result_content="gen.9.1 → ps:gen.9.1 衝突：舊多跳題")
    st = RU.record_runs(st, "H_KIN_001", "audit", [C.RunResult("audit_H_KIN_001_1", Path("x"), 0, 1.0, None)])
    got = F.overlap_avoided(tmp_path, st)
    assert got["KIN"] == {"conflict_passages_reported": 2, "runs_meeting_conflicts": 2, "gave_up_citing_overlap": 1}
    assert got["DIS"] == {"conflict_passages_reported": 0, "runs_meeting_conflicts": 0, "gave_up_citing_overlap": 0}


def complete_state(root, verses):
    """120 passed questions (30 per category; MH 8/7/8/7) with clean transcripts, Kay settled."""
    st, k = S.new_state(False), 0
    subs = [s for s, n in H.MH_QUOTA.items() for _ in range(n)]
    for i in range(30):
        for cat in H.CATEGORY_ORDER:
            sub = subs[i] if cat == "MH" else cat
            qid = f"{H.PREFIX[cat]}{i + 1:03d}"
            item = RU.annotate.annotate_item(raw_item(qid, sub, verses[k:k + 2], f"核心{k}"))
            if k == 0:
                item["change_log"] = "1) [SHORTCUT] 原題單段可答，改寫"
            st = S.add_record(st, S.Slot(k // 2 + 1, i + 1, qid, cat, sub), S.PASSED, item)
            for run in (f"gen_{qid}_1", f"audit_{qid}_1"):
                _transcript(root, run)
                st = RU.record_runs(st, qid, run.split("_")[0], [result(run, {})])
            k += 2
    ids = kay.sample_ids(S.selected_ids(st))
    return {**st, "kay": {"sample_ids": ids, "resolved": True,
                          "decisions": {q: {"decision": "accept"} for q in ids}}}


@needs_store
def test_store_freeze_writes_the_ho_file_and_the_appendix_b_list(tmp_path):
    root = tmp_path / "ho"
    S.save_state(root, complete_state(root, free_verses(240)))
    out, man = tmp_path / "heldout_ho.json", tmp_path / "freeze.json"
    doc = F.freeze(root, out, man)
    assert doc["n"] == 120 and doc["sha256"] == gd.file_sha256(out) and not out.with_suffix(".json.tmp").exists()
    qset = gd.load_ho(out, expected_sha256=doc["sha256"])
    assert doc["ids_sha256"] == qset.ids_sha256 and doc["file"] == str(out)
    assert doc["unit_table"]["n_units"] == 120 and len(doc["core_units"]) == 120
    assert doc["shortcut"] == ["H_KIN_001"] and doc["selected"]["SUC"] == 8
    assert sum(doc["density_distribution"]["bins"].values()) == 120
    assert set(doc["density_layers"]["low"]) | set(doc["density_layers"]["high"]) == set(qset.ids)
    assert "ho_tools/freeze.py" in doc["meta"]["sha256"] and "_eval_report.py" in doc["meta"]["sha256"]
    assert doc["overlap_avoided"]["KIN"]["conflict_passages_reported"] == 0
    assert doc["transcript_breaches"] == {c: 0 for c in H.CATEGORY_ORDER}
    assert json.loads(man.read_text())["sha256"] == doc["sha256"]
    with pytest.raises(H.HoToolError, match="exists"):
        F.freeze(root, out, tmp_path / "other.json")


@needs_store
def test_store_freeze_refuses_unsettled_kay_mech_errors_and_dirty_transcripts(tmp_path):
    root = tmp_path / "ho"
    base = complete_state(root, free_verses(240))
    out, man = tmp_path / "o.json", tmp_path / "m.json"
    S.save_state(root, {**base, "kay": {**base["kay"], "resolved": False}})
    with pytest.raises(H.HoToolError, match="Kay"):
        F.freeze(root, out, man)
    new82_key = gd.load_new82().questions[0].hops[0][0]
    bad = S.update_record(base, "H_TO_005", item={**S.record(base, "H_TO_005")["item"],
                                                 "hop_slots": [[new82_key], ["gen.1.1"]]})
    S.save_state(root, bad)
    with pytest.raises(H.HoToolError, match="mechanical"):
        F.freeze(root, out, man)
    S.save_state(root, base)
    (root / "transcripts" / "gen_H_DIS_003_1.jsonl").write_text(json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "用向量"}]}}))
    with pytest.raises(H.HoToolError, match="transcript"):
        F.freeze(root, out, man)
    assert not out.exists() and not man.exists()
