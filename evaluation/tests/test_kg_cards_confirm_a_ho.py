"""Experiment A confirmation set, blind question-writing tools (ho_a/: bt_a, bt_guard, banned_a, prompts_a,
claude_a, transcript_a, state_a ledger, probe_cli checks; confirm_A.md §9 test 5).

No agent is launched and Ollama is never called: the claude command line is checked as a value,
transcripts are synthetic, probe_cli's checks run on synthetic events. Tests that read the text
layer or segments.json skip when the store is not mounted.
"""

import hashlib
import importlib
import io
import json
import sys
from pathlib import Path

import pytest

import kgca_helpers as K

H = K.H
bt = importlib.import_module("bt_a")
guard = importlib.import_module("bt_guard")
banned = importlib.import_module("banned_a")
P = importlib.import_module("prompts_a")
CL = importlib.import_module("claude_a")
TR = importlib.import_module("transcript_a")
S = importlib.import_module("state_a")
PR = importlib.import_module("probe_cli")
needs_store = pytest.mark.skipif(not K.STORE_OK, reason=f"store not mounted ({K.C.SEGMENTS})")


# ---------------------------------------------------------------- bt_a and the guard (test 5)

@pytest.mark.parametrize("argv", [["old", "亞撒"], ["old", "--gold", "1ki.15.8"], ["pid", "1ki.15.8"]])
def test_bt_refuses_old_and_pid(argv):
    buf = io.StringIO()
    assert bt.main(argv, out=buf) == 2
    assert "不認得的子命令" in buf.getvalue() and "old" not in bt.USAGE and "pid" not in bt.USAGE


def test_bt_never_prints_back_a_path_like_argument(monkeypatch):
    monkeypatch.setattr(bt, "resolve", lambda key: ([], "missing"))
    out = bt.cmd_v(["../home/x/.claude/projects/y/memory/a.md", "1ki.99.1", "~kay", "/etc/passwd"])
    assert out == ["第1個參數 <<查無此節>>", "1ki.99.1 <<查無此節>>", "第3個參數 <<查無此節>>", "第4個參數 <<查無此節>>"]
    buf = io.StringIO()
    assert bt.main(["/home/x"], out=buf) == 2 and "/home" not in buf.getvalue()


def test_bt_internal_errors_are_neutral(monkeypatch):
    def boom(_argv):
        raise RuntimeError("/mnt/ollama-data/secret")
    monkeypatch.setattr(bt, "run", boom)
    buf = io.StringIO()
    assert bt.main(["v", "x"], out=buf) == 2 and "/mnt" not in buf.getvalue() and "RuntimeError" in buf.getvalue()


@needs_store
def test_bt_text_commands_read_the_pinned_layer():
    assert bt.cmd_v(["gen.24.30"])[0].startswith("gen.24.29-30 ")
    assert len(bt.cmd_v(["1ki.15.1-1ki.15.3"])) == 3
    assert bt.cmd_v(["gen.1.1a"]) == ["gen.1.1a <<半節鍵不支援，請用整節>>"]
    assert bt.cmd_grep("亞比央", "1ki")[-1].startswith("[")
    assert bt.cmd_books()[0].split()[0] == "gen" and len(bt.cmd_books()) == 66
    with pytest.raises(bt.BtUsage):
        bt.cmd_grep("x", "../etc")


@needs_store
def test_bt_refuses_a_changed_text_layer(monkeypatch):
    bt.checked.cache_clear()
    monkeypatch.setitem(bt.TEXT_SHA256, "books.jsonl", "0" * 64)
    buf = io.StringIO()
    try:
        assert bt.main(["books"], out=buf) == 2 and "核對失敗" in buf.getvalue()
    finally:
        bt.checked.cache_clear()


@needs_store
def test_no_banned_or_memory_word_occurs_in_what_bt_can_print():
    blob = "\n".join(r["text"] for r in K.C.verse_units().values()) + "\n".join(bt.cmd_books())
    assert banned.find_terms(blob, banned.BANNED_TERMS + banned.MEMORY_MARKERS) == []


def test_bt_guard_is_the_verbatim_ho_copy():
    assert hashlib.sha256((K.HO_A / "bt_guard.py").read_bytes()).hexdigest() == H.BT_GUARD_HO_SHA256
    H.check_guard_copy()


@pytest.mark.parametrize("cmd", ["bt v 1ki.15.8", "bt grep '亞比央|亞撒' 1ki,2ch", "bt books", "bt grep '以拉$'"])
def test_guard_lets_one_plain_bt_call_through(cmd):
    assert guard.check_command(cmd) is None


@pytest.mark.parametrize("cmd", ["ls", "pwd", "env", "cat /etc/hostname", "bt x; ls", "bt v x && cat y",
                                 "bt v x | head", "bt v $(whoami)", "bt v `id`", "bt v x > f", "bt v x\nls", "btx v",
                                 "bt v ~", "bt v 1ki.15.?", "bt grep 亞.* 1ki", ""])
def test_guard_refuses_everything_else(cmd):
    assert guard.check_command(cmd) is not None


def test_guard_hook_io(monkeypatch, capsys):
    def run(event):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        return guard.main()
    assert run({"tool_name": "Bash", "tool_input": {"command": "bt v 1ki.15.8"}}) == 0
    assert run({"tool_name": "StructuredOutput", "tool_input": {}}) == 0
    assert run({"tool_name": "Bash", "tool_input": {"command": "ls"}}) == guard.DENY_EXIT
    assert run({"tool_name": "Read", "tool_input": {"file_path": "/etc/x"}}) == guard.DENY_EXIT
    err = capsys.readouterr().err
    assert "denied" in err and "/home" not in err


# ---------------------------------------------------------------- banned words and prompts (test 5)

def test_prompts_and_schemas_pass_banned_a(capsys):
    assert banned.main([str(H.GEN_PROMPT), str(H.AUDIT_PROMPT)]) == 0
    assert "0 hit(s)" in capsys.readouterr().out
    P.check_schemas()
    PR.check_prompts()


def test_banned_a_extends_the_ho_lists():
    assert set(banned.HO.PROMPT_TERMS) <= set(banned.PROMPT_TERMS)
    assert set(banned.HO.MEMORY_MARKERS) <= set(banned.MEMORY_MARKERS)
    for word in ("引擎", "推導", "卡片", "模板", "種子", "pilot", "參照層", "G-auto", "T-canon", "kg_cards"):
        assert banned.check_prompt_text(f"請看{word}"), word
    assert banned.check_prompt_text("依登基年齡推算") == []
    assert banned.check_prompt_text("paragraph backstage") == []           # ASCII terms match whole words only
    assert banned.check_prompt_text("the stage list") != []


def test_prompt_loader_refuses_banned_words_and_stray_text(tmp_path):
    bad = tmp_path / "x.md"
    bad.write_text("<!-- section:system -->\n本題用引擎推算\n", encoding="utf-8")
    with pytest.raises(H.HoError):
        P.load_prompt(bad)
    bad.write_text("前言\n<!-- section:system -->\n題目\n", encoding="utf-8")
    with pytest.raises(H.HoError):
        P.load_prompt(bad)


def test_prompt_sections_render_with_exact_placeholders():
    gen, audit = P.default_prompts()
    assert set(gen.sections) == {"system", "task_new", "task_fix"} and set(audit.sections) == {"system", "task_audit"}
    vals = {"qid": "QI1s1a1", "segment_code": "I1", "segment_line": "以色列；本段範圍 王上1:1–王上1:2",
            "qtype_line": P.qtype_line("S1a"), "segment_done": P.NO_DONE}
    text = P.render(gen, "task_new", vals)
    assert "QI1s1a1" in text and "{{" not in text
    with pytest.raises(H.HoError):
        P.render(gen, "task_new", {**vals, "extra": "x"})
    with pytest.raises(H.HoError):
        P.render(gen, "task_new", {k: v for k, v in vals.items() if k != "qid"})
    assert "{{" not in P.render(audit, "task_audit", {**vals, "item_json": "{}"})


def test_prompts_carry_the_section_2_rules():
    gen, audit = (H.GEN_PROMPT.read_text(encoding="utf-8"), H.AUDIT_PROMPT.read_text(encoding="utf-8"))
    for text in (gen, audit):
        for phrase in ("bt v", "bt grep", "bt books", "歷代志上 3 章", "馬太福音 1 章", "S1a", "S1b", "S1c", "S4",
                       "亞哈謝", "約雅斤", "本段範圍"):
            assert phrase in text, phrase
        assert "bt old" not in text and "bt pid" not in text
    assert "[SHORTCUT]" in gen and "繼位句" in gen and "critical" in audit and "major" in audit


def test_qtype_line_names_the_reverse_rule():
    assert P.qtype_line("S1a_rev") == P.qtype_line("S1a")
    assert "相反" in P.qtype_line("S1a_rev", {"k": 2})
    with pytest.raises(H.HoError):
        P.qtype_line("S2")


# ---------------------------------------------------------------- claude_a

def test_argv_pins_model_tools_and_the_thinking_flag():
    argv = CL.build_argv("SYS", "USER", P.AUDIT_SCHEMA, 1.5, True)
    after = lambda flag: argv[argv.index(flag) + 1]  # noqa: E731
    assert argv[:3] == ["claude", "-p", "USER"] and after("--system-prompt") == "SYS"
    assert after("--model") == "claude-opus-5-5" and after("--tools") == "Bash" and after("--allowedTools") == "Bash(bt *)"
    assert after("--thinking-display") == "summarized" and after("--max-budget-usd") == "1.5"
    assert after("--permission-mode") == "dontAsk" and after("--setting-sources") == "local"
    assert "--safe-mode" not in argv and json.loads(after("--json-schema")) == P.AUDIT_SCHEMA
    assert "--thinking-display" not in CL.build_argv("SYS", "USER", P.AUDIT_SCHEMA, 1.5, False)


def test_launch_needs_the_pin_file_and_the_pinned_version(tmp_path):
    with pytest.raises(H.HoError):
        CL.load_pin(tmp_path)
    (tmp_path / H.PIN_FILE).write_text('{"claude_version": "2.1.302"}')
    with pytest.raises(H.HoError):
        CL.load_pin(tmp_path)
    K.write_pin(tmp_path)
    assert CL.load_pin(tmp_path) == CL.CliPin("2.1.302", True)
    with pytest.raises(H.HoError):
        CL.check_claude_version("2.1.302", "2.1.299 (Claude Code)")
    assert CL.check_claude_version("2.1.302", "2.1.302 (Claude Code)")


def test_child_env_wrappers_and_cwd(tmp_path):
    env = CL.child_env(tmp_path, {"CLAUDECODE": "1", "CLAUDE_EFFORT": "max", "PATH": "/usr/bin", "HOME": "/h"})
    assert not [k for k in env if k.upper().startswith("CLAUDE")] and env["PATH"] == f"{tmp_path / 'bin'}:/usr/bin"
    content = CL.write_wrappers(tmp_path)
    assert f"{K.HO_A / 'bt_a.py'} \"$@\" 2>/dev/null" in content["bt"] and "bt_guard.py" in content["bt-guard"]
    sub = tmp_path / "cwd"
    sub.mkdir()
    assert CL.check_cwd(sub) == sub
    for bad in (H.REPO_ROOT, K.HO_A, tmp_path / "missing"):
        with pytest.raises(H.HoError):
            CL.check_cwd(bad)


# ---------------------------------------------------------------- transcript rules

def _run(tmp_path, run_id, events, system="系統提示"):
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / f"{run_id}.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False)
                                                                         for e in events))
    (tmp_path / "prompts" / f"{run_id}.json").write_text(json.dumps({"system": system, "user": "任務"}))
    return {v.rule for v in TR.blinding_errors(tmp_path, [run_id])}


def test_transcript_blinding_rules(tmp_path):
    ok = K.events_for({"status": "abandoned"}, 0.1)
    assert _run(tmp_path, "a", ok) == set()
    assert _run(tmp_path, "b", K.events_for({}, 0.1, K.tool_pair(2, "cat /etc/passwd", "root"))) >= {"t_tool", "t_path"}
    assert _run(tmp_path, "c", K.events_for({}, 0.1, K.tool_pair(2, "ls", "x", denied=True))) == set()
    assert _run(tmp_path, "d", K.events_for({}, 0.1, K.tool_pair(2, "bt v 1ki.1.1", "Kay 的筆記"))) == {"t_memory"}
    assert _run(tmp_path, "e", ok, system="這裏有引擎與G-auto") == {"t_banned"}
    assert _run(tmp_path, "f", [dict(K.init_event(), cwd=str(H.REPO_ROOT))] + ok[1:]) == {"t_init"}


# ---------------------------------------------------------------- ledger and hard cap (§8.2)

def test_ledger_counts_results_and_assumes_caps(tmp_path):
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "gen_x_1.jsonl").write_text(json.dumps(K.events_for({}, 1.25)[-1]) + "\n")
    S.reserve(tmp_path, "gen_x_1", 4.0)
    S.reserve(tmp_path, "gen_y_1", 4.0)                       # started, no transcript: counts its cap
    S.reserve(tmp_path, "probe_1", 0.33, sub="probe")
    led = S.ledger(tmp_path)
    assert led["runs"]["gen_x_1"] == {"cost_usd": 1.25, "source": "result"}
    assert led["runs"]["gen_y_1"]["source"] == "cap_assumed" and led["total_usd"] == pytest.approx(5.58)
    S.reserve(tmp_path, "big", 130.0)
    assert S.check_cap(tmp_path, 4.0) == pytest.approx(135.58)
    with pytest.raises(H.BudgetRefused):
        S.check_cap(tmp_path, 4.5)


# ---------------------------------------------------------------- probe_cli checks (§8.3; never launched)

OFF = {c: True for c in PR.OFFLINE_DENY}


def _probe_events(thinking="（摘要）", deny=True, memory=False, tokens=2786, fallback=False):
    extra = K.tool_pair(2, "ls", "x", denied=deny) + K.tool_pair(3, "bt books", "gen 創世記 50")
    if memory:
        extra += K.tool_pair(4, "bt v rut.1.16", "Bible_RAG 記憶")
    if fallback:
        extra += [{"type": "system", "subtype": "model_refusal_fallback", "trigger": "refusal",
                   "original_model": "claude-opus-5-5", "fallback_model": "claude-opus-4-8"}]
    ev = K.events_for({"answer": "4", "attempts": ["ok"] * 3}, 0.05, extra, thinking=thinking)
    ev[1] = {**ev[1], "message": {**ev[1]["message"], "usage": {"input_tokens": 2, "cache_read_input_tokens": tokens}}}
    return ev


def test_probe_checks_and_verdicts():
    prompts = {"system": PR.PROBE_SYSTEM, "user": PR.PROBE_USER}
    good = PR.run_checks(_probe_events(), prompts, True, True, OFF)
    assert all(good[k] == "pass" for k in ("c1_init", "c2_hook", "c3_thinking", "c4_no_memory", "c5_result"))
    v = PR.verdict([{"run_id": "p1", "checks": good}] * 3, "2.1.302", True, "2.1.302 (Claude Code)")
    assert v["action"] == "pin" and v["pin"] == {"claude_version": "2.1.302", "thinking_display": True}
    empty = PR.run_checks(_probe_events(thinking=""), prompts, True, True, OFF)
    assert empty["c3_thinking"] == "fail"
    assert PR.verdict([{"checks": good}, {"checks": empty}], "2.1.302", True, "x")["action"] == "drop_thinking_display"
    assert PR.run_checks(_probe_events(thinking=""), prompts, False, True, OFF)["c3_thinking"] == "skip"
    for bad in (PR.run_checks(_probe_events(deny=False), prompts, True, True, OFF),
                PR.run_checks(_probe_events(memory=True), prompts, True, True, OFF),
                PR.run_checks(_probe_events(tokens=48000), prompts, True, True, OFF),   # a context file loaded
                PR.run_checks(_probe_events(fallback=True), prompts, True, True, OFF),  # another model answered
                PR.run_checks(_probe_events(), prompts, True, True, {**OFF, "bt x; ls": False}),
                PR.run_checks(_probe_events(), prompts, True, True),                    # offline check not run
                PR.run_checks(_probe_events(), prompts, True, False, OFF)):
        assert PR.verdict([{"checks": bad}], "2.1.302", True, "x")["action"] == "stop"
    assert PR.verdict([], "2.1.302", True, "2.1.299")["action"] == "stop"


def test_probe_rejected_thinking_flag_reruns_without_it(tmp_path):
    prompts = {"system": PR.PROBE_SYSTEM, "user": PR.PROBE_USER}
    rejected = [{"type": "result", "subtype": "error_during_execution", "is_error": True, "total_cost_usd": 0}]
    bad = PR.run_checks(rejected, prompts, True, True)
    assert bad["detail"]["has_init"] is False and bad["c1_init"] == bad["c5_result"] == "fail"
    v1 = PR.verdict([{"checks": bad}] * 3, "2.1.302", True, "2.1.302 (Claude Code)")
    assert v1["action"] == "rerun_no_thinking_display" and v1["pin"] is None
    assert PR.verdict([{"checks": PR.run_checks([], prompts, True, True)}], "2.1.302", True, "x")["action"] == \
        "rerun_no_thinking_display"                                            # no events at all, flag passed
    assert PR.verdict([{"checks": bad}], "2.1.302", False, "x")["action"] == "stop"   # without the flag: stop
    good = PR.run_checks(_probe_events(thinking=""), prompts, False, True, OFF)
    v2 = PR.verdict([{"checks": good}] * 3, "2.1.302", False, "2.1.302 (Claude Code)")
    assert v2["action"] == "pin" and v2["pin"] == {"claude_version": "2.1.302", "thinking_display": False}
    first, second = tmp_path / "probe" / "verdict_1.json", tmp_path / "probe" / "verdict_2.json"
    H.write_json(first, v1)
    H.write_json(second, v2)
    with pytest.raises(H.HoError, match="after-rejected"):
        PR.pin_from(tmp_path, second)                                          # thinking off needs the record
    with pytest.raises(H.HoError):
        PR.pin_from(tmp_path, second, after_rejected=second)
    PR.pin_from(tmp_path, second, after_rejected=first)
    assert CL.load_pin(tmp_path) == CL.CliPin("2.1.302", False)
    doc = H.read_json(tmp_path / H.PIN_FILE)
    assert doc["after_rejected"] == "verdict_1.json" and "不接受 --thinking-display" in doc["disclosure"]


def test_probe_checks_the_guard_copy_first(tmp_path, monkeypatch):
    monkeypatch.setattr(PR, "check_guard_copy", lambda: (_ for _ in ()).throw(H.HoError("bt_guard.py sha256 x")))
    monkeypatch.setattr(PR.CL, "launch", lambda *a, **k: pytest.fail("launched"))
    with pytest.raises(H.HoError, match="bt_guard"):
        PR.probe(tmp_path, "2.1.302", True)


def test_pin_from_verdict(tmp_path):
    path = tmp_path / "probe" / "verdict_1.json"
    H.write_json(path, {"action": "drop_thinking_display", "claude_version_expected": "2.1.302",
                        "thinking_display": True})
    with pytest.raises(H.HoError):
        PR.pin_from(tmp_path, path)
    PR.pin_from(tmp_path, path, drop_thinking=True)
    assert CL.load_pin(tmp_path) == CL.CliPin("2.1.302", False)
    H.write_json(path, {"action": "stop", "claude_version_expected": "2.1.302", "thinking_display": True})
    with pytest.raises(H.HoError):
        PR.pin_from(tmp_path, path, drop_thinking=True)


def test_check_memory_dir_refuses_a_non_empty_memory(tmp_path):
    home, cwd = tmp_path / "home", Path("/srv")
    mem = CL.memory_dir(cwd, home)
    assert mem == home / ".claude" / "projects" / "-srv" / "memory"
    assert CL.check_memory_dir(cwd, home) == mem                              # absent: fine
    mem.mkdir(parents=True)
    assert CL.check_memory_dir(cwd, home) == mem                              # empty: fine
    (mem / "MEMORY.md").write_text("x", encoding="utf-8")
    with pytest.raises(H.HoError, match="not empty"):
        CL.check_memory_dir(cwd, home)
