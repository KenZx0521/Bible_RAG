"""GEN confirmation set: the shared agent-launch infrastructure (prereg §3.1, §3.3, §3.9, §8.1-2, §8.2).

hog_common, claude_g, bt_g, ledger_g, transcript_g and probe_g. Nothing here launches claude or calls Ollama: every
launch runs a fake ``claude`` (a small python script written into a tmp versions/ dir, printing canned stream-json
chosen through the GTEST_FAKE variable), every root is a tmp dir. Synthetic names and texts are made up (the
8-character window scan at the end checks this file and the new modules against the text layer); bt_g's store
test reads the real text layer at run time, skips when the store is not mounted, and asserts on booleans and
hashes only, so a failure never prints scripture.
"""

import ast
import hashlib
import io
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

H_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H_DIR) not in sys.path:
    sys.path.insert(0, str(H_DIR))

import banned_g as B  # noqa: E402
import bt_g as BT  # noqa: E402
import claude_g as CL  # noqa: E402
import g_common as GC  # noqa: E402
import hog_common as H  # noqa: E402
import ledger_g as LG  # noqa: E402
import probe_g as PR  # noqa: E402
import transcript_g as TR  # noqa: E402

TEXT_DIR = GC.STORE / "layers/text/text@247eafe44b02"
needs_text = pytest.mark.skipif(not (TEXT_DIR / "verse_units.jsonl").is_file(), reason="text layer not mounted")
HO_A = GC.REPO / "evaluation/experiments/2026-10-18_kg_cards/A/confirm/ho_a"
STAND_IN_CUES = ("出生", "去世", "幾歲", "嗎")
OPUS, SONNET = CL.MODELS["opus"], CL.MODELS["sonnet"]
FAKE_VERSION = "9.9.9"
NEW_FILES = ("hog_common.py", "claude_g.py", "bt_g.py", "ledger_g.py", "transcript_g.py", "probe_g.py")

FAKE_CLAUDE = r'''#!{python}
import json, os, sys, time
VERSION = "{version}"
args = sys.argv[1:]
if args[:1] == ["--version"]:
    fail = os.environ.get("GTEST_VERSION_FAIL")             # a counter file: fail (exit 1, no output) while > 0
    left = int(open(fail).read() or 0) if fail else 0
    if left > 0:
        open(fail, "w").write(str(left - 1))
        time.sleep(float(os.environ.get("GTEST_VERSION_SLEEP") or 0))
        sys.exit(1)
    print(VERSION + " (Claude Code)")
    sys.exit(0)
def arg(name, default=None):
    return args[args.index(name) + 1] if name in args else default
cfg = json.loads(os.environ.get("GTEST_FAKE") or "{{}}")
if os.environ.get("GTEST_LOG"):
    keep = {{k: v for k, v in os.environ.items() if k in ("PATH", "PWD", "OLDPWD", "DISABLE_AUTOUPDATER", "AI_AGENT")
            or k.upper().startswith("CLAUDE")}}
    with open(os.environ["GTEST_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({{"argv": args, "cwd": os.getcwd(), "env": keep}}) + "\n")
model, tools, mode = arg("--model"), arg("--tools"), cfg.get("mode", "ok")
schema = json.loads(arg("--json-schema") or "{{}}")
def emit(e):
    print(json.dumps(e, ensure_ascii=False), flush=True)
def fill(s):
    t = s.get("type")
    if t == "object":
        return {{k: fill(v) for k, v in (s.get("properties") or {{}}).items()}}
    return 1 if t == "integer" else ["x"] if t == "array" else "x"
usage = {{"input_tokens": 8, "cache_creation_input_tokens": cfg.get("tokens", 1500), "cache_read_input_tokens": 0,
         "output_tokens": 40}}
emit({{"type": "system", "subtype": "init", "cwd": os.getcwd(), "model": cfg.get("init_model", model),
      "claude_code_version": VERSION, "tools": ["Bash", "StructuredOutput"] if tools == "Bash" else ["StructuredOutput"],
      "mcp_servers": [], "permissionMode": arg("--permission-mode")}})
if mode == "crash":
    sys.exit(1)
if mode == "torn":                                           # killed while writing a line, inside a CJK character
    sys.stdout.flush()
    sys.stdout.buffer.write(json.dumps({{"type": "assistant", "text": "甲乙丙"}}, ensure_ascii=False).encode()[:-6])
    sys.stdout.buffer.flush()
    sys.exit(1)
if mode == "fallback":
    emit({{"type": "system", "subtype": "model_refusal_fallback", "original_model": model,
          "fallback_model": "claude-other-0", "trigger": "refusal"}})
blocks = [{{"type": "thinking", "thinking": "Plan the steps first."}}] if cfg.get("thinking", True) else []
if mode == "probe" and tools == "Bash":
    emit({{"type": "assistant", "message": {{"usage": usage, "content": blocks + [
        {{"type": "tool_use", "id": "t1", "name": "Bash", "input": {{"command": "ls"}}}}]}}}})
    emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                                   "content": "denied: only `bt` may run"}}]}}}})
    emit({{"type": "assistant", "message": {{"usage": usage, "content": [
        {{"type": "tool_use", "id": "t2", "name": "Bash", "input": {{"command": "bt books"}}}}]}}}})
    emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t2", "content": "[3 筆]"}}]}}}})
    blocks = []
out = cfg.get("output") or fill(schema)
emit({{"type": "assistant", "message": {{"usage": usage, "content": blocks + [
    {{"type": "tool_use", "id": "t9", "name": "StructuredOutput", "input": out}}]}}}})
cost = cfg.get("cost", 0.03)
used = {{model: {{"costUSD": cost}}}}
if mode == "other_model":
    used["claude-other-0"] = {{"costUSD": 0.001}}
if mode == "budget":
    emit({{"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": float(arg("--max-budget-usd")),
          "modelUsage": used}})
    sys.exit(1)
final = {{"type": "result", "subtype": "success", "is_error": False, "result": "done", "structured_output": out,
         "total_cost_usd": cost, "usage": usage, "modelUsage": used}}
if mode == "no_output":
    del final["structured_output"]
emit(final)
'''


# ---------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def stand_in_cues():
    with B.override_cue_literals(STAND_IN_CUES):
        yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp out root, a tmp versions/ with the fake CLI, an empty agent cwd and home, the fake's log."""
    versions, out_root, cwd, home = (tmp_path / d for d in ("versions", "out", "srv", "home"))
    for d in (versions, out_root, cwd, home):
        d.mkdir()
    exe = versions / FAKE_VERSION
    exe.write_text(FAKE_CLAUDE.format(python=sys.executable, version=FAKE_VERSION), encoding="utf-8")
    exe.chmod(0o755)
    log = tmp_path / "fake.log"
    monkeypatch.setenv("GTEST_LOG", str(log))
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "parent")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("GTEST_FAKE", raising=False)
    monkeypatch.setenv("AI_AGENT", "parent_agent")
    path, sha = CL.copy_cli(FAKE_VERSION, versions, out_root / "cli", H.sha256_file(exe))
    pin = CL.CliPin(FAKE_VERSION, sha, str(path), True, dict(CL.MODELS))

    class Env:
        pass
    e = Env()
    e.versions, e.out_root, e.cwd, e.home, e.log, e.pin, e.monkeypatch = versions, out_root, cwd, home, log, pin, monkeypatch
    e.sha = sha
    e.ledger = LG.Ledger(out_root)
    e.fake = lambda **cfg: monkeypatch.setenv("GTEST_FAKE", json.dumps(cfg))
    e.logs = lambda: [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
    return e


SCHEMA = {"type": "object", "properties": {"value": {"type": "integer"}, "note": {"type": "string"}},
          "required": ["value", "note"]}


def launch(e, root, run_id="r1", cap=1.0, model=OPUS, tools_mode="bt", kind="ho", user_scope="prompt", **kw):
    return CL.run_reserved(kind, root, run_id, "Answer with StructuredOutput once.", "Give one number.", SCHEMA, cap,
                           model, e.pin, user_scope=user_scope, out_root=e.out_root, tools_mode=tools_mode, cwd=e.cwd,
                           home=e.home, timeout_s=60, **kw)


def direct(e, root, run_id="r1", cap=1.0, model=OPUS, **kw):
    """CL.launch itself (no reservation taken here), on the env's out root."""
    kw = {"user_scope": "prompt", "cwd": e.cwd, "home": e.home, "out_root": e.out_root, "timeout_s": 60, **kw}
    return CL.launch(root, run_id, "S", "U", SCHEMA, cap, model, e.pin, **kw)


# ---------------------------------------------------------------- hog_common
def test_errors_violation_and_meta():
    assert issubclass(H.BudgetRefused, H.HoError)
    assert H.Violation("t_x", "d").as_dict() == {"rule": "t_x", "detail": "d", "level": "error"}
    sha = H.tool_sha()
    assert set(NEW_FILES) <= set(sha) and sha["evaluation/experiments/2026-10-14_graph_gd/ho_tools/bt_guard.py"] == \
        H.BT_GUARD_SHA256
    m = H.meta("x.py", extra=1)
    assert m["script"] == "x.py" and m["extra"] == 1 and "tools_sha256" in m


def test_guard_is_hos_original_by_sha_and_loaded_by_path(tmp_path):
    assert H.check_guard() == H.BT_GUARD_SHA256
    copy = tmp_path / "bt_guard.py"
    copy.write_text(H.BT_GUARD.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(H.HoError, match="sha256"):
        H.check_guard(copy)
    with pytest.raises(H.HoError, match="missing"):
        H.check_guard(tmp_path / "none.py")
    g = H.bt_guard()
    assert Path(g.__file__).resolve() == H.BT_GUARD.resolve()
    assert g.check_command("bt v gen.5.3") is None and g.check_command("ls") is not None


def test_write_wrappers_refuses_a_changed_guard(tmp_path, monkeypatch):
    copy = tmp_path / "bt_guard.py"
    copy.write_text(H.BT_GUARD.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    monkeypatch.setattr(H, "BT_GUARD", copy)
    with pytest.raises(H.HoError, match="sha256"):
        CL.write_wrappers(tmp_path / "root", "bt")
    assert not (tmp_path / "root" / "hookbin").exists()


# ---------------------------------------------------------------- argv and environment
def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_argv_of_mode_bt():
    argv = CL.build_argv("SYS", "USER", SCHEMA, 2.0, OPUS, "xhigh", True, "bt")
    assert argv[:3] == ["claude", "-p", "USER"] and _flag(argv, "--system-prompt") == "SYS"
    assert _flag(argv, "--model") == OPUS and _flag(argv, "--effort") == "xhigh"
    assert _flag(argv, "--thinking-display") == "summarized" and _flag(argv, "--tools") == "Bash"
    assert _flag(argv, "--allowedTools") == "Bash(bt *)" and _flag(argv, "--permission-mode") == "dontAsk"
    assert _flag(argv, "--setting-sources") == "local" and _flag(argv, "--max-budget-usd") == "2"
    hook = json.loads(_flag(argv, "--settings"))["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "*" and hook["hooks"][0]["command"] == "bt-guard"
    for f in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--verbose"):
        assert f in argv
    assert json.loads(_flag(argv, "--json-schema")) == SCHEMA and _flag(argv, "--output-format") == "stream-json"
    dis = argv[argv.index("--disallowedTools") + 1:argv.index("--permission-mode")]
    assert {"Read", "Write", "Edit", "WebFetch", "WebSearch", "Task", "Agent", "Grep", "Glob"} <= set(dis)


def test_argv_of_mode_none_and_without_thinking():
    argv = CL.build_argv("SYS", "USER", SCHEMA, 0.2, SONNET, "xhigh", False, "none")
    assert _flag(argv, "--tools") == "" and "--allowedTools" not in argv and "--thinking-display" not in argv
    assert _flag(argv, "--model") == SONNET and "--settings" in argv and _flag(argv, "--max-budget-usd") == "0.2"
    with pytest.raises(H.HoError):
        CL.build_argv("S", "U", SCHEMA, 1, OPUS, "xhigh", True, "bash")


def test_child_env_strips_claude_variables_and_puts_the_pinned_bins_first(tmp_path):
    base = {"CLAUDE_CODE_ENTRYPOINT": "x", "CLAUDECODE": "1", "claude_x": "y", "HOME": "/h", "PATH": "/usr/bin:/bin",
            "PWD": "/somewhere/repo", "OLDPWD": "/elsewhere", "ANTHROPIC_X": "k", "AI_AGENT": "claude-code_9_agent"}
    env = CL.child_env(tmp_path, "bt", Path("/srv"), base)
    assert not any(k.upper().startswith("CLAUDE") for k in env) and "OLDPWD" not in env and "AI_AGENT" not in env
    assert env["PATH"].split(":") == [str(tmp_path / "clibin"), str(tmp_path / "hookbin"), str(tmp_path / "bin"),
                                      "/usr/bin", "/bin"]
    assert env["DISABLE_AUTOUPDATER"] == "1" and env["PWD"] == "/srv" and env["HOME"] == "/h" and env["ANTHROPIC_X"] == "k"
    none = CL.child_env(tmp_path, "none", Path("/srv"), base)
    assert str(tmp_path / "bin") not in none["PATH"].split(":")


def test_agent_cwd_must_be_an_empty_dir_outside_and_not_above_the_repo(tmp_path):
    with pytest.raises(H.HoError, match="not a directory"):
        CL.check_cwd(tmp_path / "missing")
    with pytest.raises(H.HoError, match="outside"):
        CL.check_cwd(GC.REPO / "evaluation")
    with pytest.raises(H.HoError, match="outside"):
        CL.check_cwd(GC.REPO.parent)
    (tmp_path / "f").write_text("x")
    with pytest.raises(H.HoError, match="not empty"):
        CL.check_cwd(tmp_path)
    (tmp_path / "e").mkdir()
    assert CL.check_cwd(tmp_path / "e") == tmp_path / "e"


def test_auto_memory_of_the_cwd_must_be_empty(tmp_path):
    mem = CL.memory_dir(Path("/srv"), tmp_path)
    assert mem == tmp_path / ".claude/projects/-srv/memory"
    CL.check_memory_dir(Path("/srv"), tmp_path)
    mem.mkdir(parents=True)
    CL.check_memory_dir(Path("/srv"), tmp_path)
    (mem / "note.md").write_text("x")
    with pytest.raises(H.HoError, match="auto-memory"):
        CL.check_memory_dir(Path("/srv"), tmp_path)


# ---------------------------------------------------------------- CLI copy and pin
def test_copy_cli_copies_the_executable_with_its_sha_and_keeps_an_equal_copy(env):
    src = env.versions / FAKE_VERSION
    path, sha = CL.copy_cli(FAKE_VERSION, env.versions, env.out_root / "cli", env.sha)
    assert path == env.out_root / "cli" / FAKE_VERSION / "claude" and sha == H.sha256_file(src) == H.sha256_file(path)
    assert (path.parent / "claude.sha256").read_text().split()[0] == sha and os.access(path, os.X_OK)
    src.write_text(src.read_text() + "# newer build\n")
    with pytest.raises(H.HoError, match="not the expected"):
        CL.copy_cli(FAKE_VERSION, env.versions, env.out_root / "cli", env.sha)
    with pytest.raises(H.HoError, match="another sha256"):
        CL.copy_cli(FAKE_VERSION, env.versions, env.out_root / "cli", H.sha256_file(src))
    for bad in ("../x", "latest", "9.9.9; ls"):
        with pytest.raises(H.HoError, match="plain version"):
            CL.copy_cli(bad, env.versions, env.out_root / "cli")
    with pytest.raises(H.HoError, match="no executable"):
        CL.copy_cli("9.9.8", env.versions, env.out_root / "cli")


def test_copy_cli_refuses_a_known_version_with_another_sha(env):
    (env.versions / "2.1.302").write_text("#!/bin/sh\n")
    with pytest.raises(H.HoError, match="not the expected"):
        CL.copy_cli("2.1.302", env.versions, env.out_root / "cli")
    sha = H.sha256_file(env.versions / "2.1.302")
    with pytest.raises(H.HoError, match="known sha256"):
        CL.copy_cli("2.1.302", env.versions, env.out_root / "cli", sha)


def test_copy_cli_needs_an_expected_sha_for_a_version_without_a_known_one(env):
    """INF-8: no trust on first use; the basis of the sha and the source's size and mtime are recorded."""
    with pytest.raises(H.HoError, match="--cli-sha256"):
        CL.copy_cli(FAKE_VERSION, env.versions, env.out_root / "cli2")
    assert not (env.out_root / "cli2").exists()
    path, _ = CL.copy_cli(FAKE_VERSION, env.versions, env.out_root / "cli2", env.sha.upper())
    meta = json.loads((path.parent / "claude.json").read_text())
    src = env.versions / FAKE_VERSION
    assert meta["sha256"] == env.sha and meta["sha_basis"] == "operator" and meta["version"] == FAKE_VERSION
    assert meta["source_size"] == src.stat().st_size and meta["source"] == str(src) and meta["source_mtime_utc"]
    assert CL.sha_basis("2.1.302") == "known" and CL.sha_basis(FAKE_VERSION) == "operator"


def test_copy_cli_never_writes_into_the_repo(env):
    with pytest.raises(H.HoError, match="repository"):
        CL.copy_cli(FAKE_VERSION, env.versions, GC.REPO / "tmp_cli", env.sha)
    assert not (GC.REPO / "tmp_cli").exists()


def test_pin_cli_links_the_checked_copy_and_the_version_is_checked(env):
    root = env.out_root / "ho"
    bindir = CL.pin_cli(root, env.pin)
    link = bindir / "claude"
    assert link.is_symlink() and Path(os.readlink(link)) == Path(env.pin.cli_path)
    assert CL.claude_version(root) == f"{FAKE_VERSION} (Claude Code)"
    assert CL.check_claude_version(root, FAKE_VERSION).startswith(FAKE_VERSION)
    with pytest.raises(H.HoError, match="pinned"):
        CL.check_claude_version(root, "9.9.8")
    Path(env.pin.cli_path).write_text(Path(env.pin.cli_path).read_text() + "# self-update\n")
    with pytest.raises(H.HoError, match="pinned copy"):
        CL.pin_cli(root, env.pin)


def test_pin_file_round_trip_and_refusals(env, tmp_path):
    p = CL.write_pin(env.pin, tmp_path / "cli_pin.json", verdict="v.json")
    got = CL.load_pin(p)
    assert got == env.pin and got.model("sonnet") == SONNET and got.tools_modes == ("bt", "none")
    assert got.combos == CL.PROBED_COMBOS == (("bt", "opus"), ("none", "opus"), ("none", "sonnet"))
    with pytest.raises(H.HoError, match="no pinned model"):
        got.model("haiku")
    with pytest.raises(H.HoError, match="missing"):
        CL.load_pin(tmp_path / "none.json")
    doc = json.loads(p.read_text())
    for change in ({"cli_sha256": "ab"}, {"thinking_display": "yes"}, {"combos": [["bash_guard", "opus"]]},
                   {"combos": [["bt", "haiku"]]}, {"combos": [["bt"]]}, {"combos": []}, {"models": []}):
        with pytest.raises(H.HoError, match="cli pin needs"):
            CL.CliPin.from_dict({**doc, **change})
    assert CL.PIN_PATH == GC.OUT_ROOT / "cli_pin.json"


# ---------------------------------------------------------------- launch end to end (fake claude)
def test_launch_end_to_end_in_mode_bt(env):
    env.fake(mode="ok", cost=0.04)
    root = env.out_root / "ho"
    res = launch(env, root, user_scope="prompt", tool_values={"qid": "Q01"}, extra_record={"kind": "draft"})
    assert res.error is None and res.limit is None and not res.infra_failure and res.output == {"value": 1, "note": "x"}
    rec = json.loads((root / "prompts/r1.json").read_text())
    assert rec["system"] == "Answer with StructuredOutput once." and rec["user"] == "Give one number."
    assert rec["schema"] == SCHEMA and rec["budget_usd"] == 1.0 and rec["model"] == OPUS and rec["effort"] == "xhigh"
    assert rec["tools_mode"] == "bt" and rec["user_scope"] == "prompt" and rec["tool_values"] == {"qid": "Q01"}
    assert rec["kind"] == "draft" and rec["pin"]["cli_sha256"] == env.pin.cli_sha256 and rec["cwd"] == str(env.cwd)
    assert "<prompt>" in rec["argv"] and "Give one number." not in rec["argv"]
    assert set(rec) == CL.RECORD_KEYS | {"kind"}
    assert rec["env_keys"] == sorted(rec["env_keys"]) and "PATH" in rec["env_keys"] and "AI_AGENT" not in rec["env_keys"]
    (log,) = [x for x in env.logs() if x["argv"][:1] == ["-p"]]
    assert log["cwd"] == str(env.cwd) and not any(k.upper().startswith("CLAUDE") for k in log["env"])
    assert log["env"]["DISABLE_AUTOUPDATER"] == "1" and log["env"]["PWD"] == str(env.cwd) and "OLDPWD" not in log["env"]
    assert "AI_AGENT" not in log["env"]
    assert log["env"]["PATH"].split(":")[:3] == [str(root / d) for d in ("clibin", "hookbin", "bin")]
    bt = (root / "bin/bt").read_text()
    assert str(H.HERE / "bt_g.py") in bt and "2>/dev/null" in bt and sys.executable in bt
    assert str(H.BT_GUARD) in (root / "hookbin/bt-guard").read_text()
    assert [v for v in TR.check_run(root, "r1") if v.level == "error"] == []
    assert env.ledger.snapshot()["runs"]["ho/r1"] == {"kind": "ho", "cost_usd": 0.04, "source": "result"}


def test_launch_in_mode_none_has_no_bt_on_path(env):
    env.fake(mode="ok")
    root = env.out_root / "qset" / "p1"
    res = launch(env, root, cap=0.2, model=SONNET, tools_mode="none", kind="qset")
    assert res.error is None and res.tools_mode == "none" and res.model == SONNET
    assert not (root / "bin").exists() and (root / "hookbin/bt-guard").is_file()
    (log,) = [x for x in env.logs() if x["argv"][:1] == ["-p"]]
    assert str(root / "bin") not in log["env"]["PATH"].split(":") and _flag(log["argv"], "--tools") == ""
    assert [v for v in TR.check_run(root, "r1") if v.level == "error"] == []


def test_launch_refuses_before_starting(env):
    root = env.out_root / "ho"
    with pytest.raises(H.HoError, match="reservation"):
        direct(env, root)
    env.ledger.reserve("ho", root, "r1", 0.5)
    with pytest.raises(H.HoError, match="reservation"):
        direct(env, root)
    with pytest.raises(H.HoError, match="not a pinned id"):
        direct(env, root, cap=0.5, model="claude-other-0")
    only_bt = CL.CliPin(**{**env.pin.as_dict(), "combos": (("bt", "opus"),)})
    with pytest.raises(H.HoError, match="not probed"):
        CL.launch(root, "r1", "S", "U", SCHEMA, 0.5, OPUS, only_bt, user_scope="prompt", tools_mode="none",
                  cwd=env.cwd, home=env.home, out_root=env.out_root)
    other = CL.CliPin(**{**env.pin.as_dict(), "claude_version": "9.9.8"})
    with pytest.raises(CL.CliChanged, match="pinned 9.9.8"):
        CL.launch(root, "r1", "S", "U", SCHEMA, 0.5, OPUS, other, user_scope="prompt", cwd=env.cwd, home=env.home,
                  out_root=env.out_root)
    with pytest.raises(H.HoError, match="user scope"):
        direct(env, root, cap=0.5, user_scope="all")
    with pytest.raises(H.HoError, match="overwrite"):
        direct(env, root, cap=0.5, extra_record={"budget_usd": 0.01})
    with pytest.raises(H.HoError, match="overwrite"):
        direct(env, root, cap=0.5, extra_record={"env_keys": []})
    assert not (root / "prompts").exists() and not (root / "transcripts").exists() and env.logs() == []


# ---------------------------------------------------------------- review fixes (INF-1 ... INF-12)
WRAPPER_DIRS = ("hookbin", "bin", "clibin")


def test_inf1_a_refused_launch_writes_nothing_into_its_root(env, monkeypatch):
    ho = env.out_root / "ho"
    with pytest.raises(H.HoError, match="reservation"):
        direct(env, ho / "q")
    assert not (ho / "q").exists()
    elsewhere = env.out_root.parent / "elsewhere"
    with pytest.raises(H.HoError, match="not under a ledger base"):
        direct(env, elsewhere)
    assert not elsewhere.exists()
    frozen = ho / "frozen"                                   # a frozen folder g_common.writable refuses
    frozen.mkdir(parents=True)
    monkeypatch.setattr(GC, "READ_ONLY", (*GC.READ_ONLY, frozen))
    with pytest.raises(H.HoError, match="store is written only"):
        direct(env, frozen)
    assert list(frozen.iterdir()) == []
    with pytest.raises(H.HoError, match="store is written only"):
        CL.write_wrappers(frozen, "bt")
    with pytest.raises(H.HoError, match="store is written only"):
        CL.pin_cli(frozen, env.pin)
    assert list(frozen.iterdir()) == [] and env.logs() == []


def test_inf1_wrapper_writes_go_through_writable(env, monkeypatch):
    root, seen = env.out_root / "ho", []
    real = GC.writable
    monkeypatch.setattr(GC, "writable", lambda p: (seen.append(Path(p).name), real(p))[1])
    CL.write_wrappers(root, "bt")
    CL.pin_cli(root, env.pin)
    assert {"bt-guard", "bt", "clibin"} <= set(seen)


def _torn(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"type": "assistant", "text": "甲乙丙"}, ensure_ascii=False).encode()
    path.write_bytes(json.dumps({"type": "system", "subtype": "init"}).encode() + b"\n" + line[:-6])


def test_inf2_a_transcript_torn_inside_a_character_blocks_nothing(env):
    ho = env.out_root / "ho"
    env.ledger.reserve("ho", ho, "draft_1", 1.0)
    _torn(ho / "transcripts" / "draft_1.jsonl")
    assert [e.get("subtype") for e in CL.read_events(ho / "transcripts" / "draft_1.jsonl")] == ["init"]
    assert LG.result_cost(ho / "transcripts" / "draft_1.jsonl") is None
    env.ledger.reserve("ho", ho, "audit_2", 1.0)
    assert env.ledger.snapshot()["runs"]["ho/draft_1"] == {"kind": "ho", "cost_usd": 1.0, "source": "reserve"}
    assert env.ledger.spent() == 2.0
    assert "t_result" in _errors(TR.check_run(ho, "draft_1", OPUS, "bt"))


def test_inf2_a_launch_whose_cli_dies_mid_character_returns_an_infra_failure(env):
    env.fake(mode="torn")
    res = launch(env, env.out_root / "ho", cap=1.0)
    assert res.error.startswith("no result event") and res.infra_failure
    assert env.ledger.snapshot()["runs"]["ho/r1"]["cost_usd"] == 1.0


def test_inf3_user_scope_is_required_and_a_missing_scope_fails_closed():
    import inspect
    for fn in (CL.launch, CL.run_reserved):
        assert inspect.signature(fn).parameters["user_scope"].default is inspect.Parameter.empty, fn.__name__
    prompts = {"system": "s", "user": "a template naming 算術", "schema": {}}
    events = [_events()[0], _events()[-1]]
    assert ("t_banned", "error") in {(v.rule, v.level) for v in TR.check_events(events, prompts, OPUS, "bt")}
    bogus = {**prompts, "user_scope": "bogus"}
    assert ("t_banned", "error") in {(v.rule, v.level) for v in TR.check_events(events, bogus, OPUS, "bt")}
    assert TR.full_check("prompt:user", "bogus") is True and TR.full_check("prompt:user", "agent") is False


def test_inf4_any_failure_before_the_start_releases_the_reservation(env, monkeypatch):
    def disk_full(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(CL, "write_wrappers", disk_full)
    with pytest.raises(OSError, match="disk full"):
        launch(env, env.out_root / "probe" / "1", run_id="bt_1", cap=0.12, kind="probe")
    snap = env.ledger.snapshot()
    assert snap["runs"] == {} and snap["probe_invocations"] == []
    with pytest.raises(TypeError):
        CL.run_reserved("ho", env.out_root / "ho", "r2", "S", "U", SCHEMA, 1.0, OPUS, env.pin, out_root=env.out_root)
    assert env.ledger.snapshot()["runs"] == {}


def test_inf4_a_started_run_keeps_its_reservation_when_the_launcher_dies(env, monkeypatch):
    def interrupted(*a, **k):
        raise KeyboardInterrupt
    env.fake(mode="ok")
    monkeypatch.setattr(CL, "outcome", interrupted)
    with pytest.raises(KeyboardInterrupt):
        launch(env, env.out_root / "ho", cap=1.5)
    assert env.ledger.snapshot()["runs"]["ho/r1"]["source"] == "result"


def test_inf5_concurrent_snapshots_never_collide(tmp_path):
    led, errors = LG.Ledger(tmp_path), []
    led.reserve("ho", tmp_path / "ho", "draft_1", 1.0)

    def work() -> None:
        for _ in range(150):
            try:
                led.write_snapshot()
            except Exception as err:  # noqa: BLE001
                errors.append(type(err).__name__)
    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and json.loads((tmp_path / "ledger.json").read_text())["total_usd"] == 1.0


def _hold_flock(path: str, held, release) -> None:
    import fcntl
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o664)
    fcntl.flock(fd, fcntl.LOCK_EX)
    held.set()
    release.wait(30)
    os.close(fd)


def test_inf6_reserve_waits_for_another_process_holding_the_ledger_flock(tmp_path):
    ctx = multiprocessing.get_context("fork")
    held, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_flock, args=(str(tmp_path / LG.LOCK_NAME), held, release))
    child.start()
    try:
        assert held.wait(30)
        done = threading.Event()
        worker = threading.Thread(target=lambda: (LG.Ledger(tmp_path).reserve("ho", tmp_path / "ho", "r1", 1.0),
                                                  done.set()))
        worker.start()
        assert not done.wait(1.0) and not (tmp_path / "ho/reserve/r1.json").exists()
    finally:
        release.set()
        child.join(30)
    worker.join(30)
    assert done.is_set() and (tmp_path / "ho/reserve/r1.json").is_file()


def test_inf7_only_probed_mode_model_pairs_and_the_probed_effort_launch(env):
    root = env.out_root / "ho"
    env.ledger.reserve("ho", root, "r1", 1.0)
    with pytest.raises(H.HoError, match=r"\(bt, sonnet\) was not probed"):
        direct(env, root, model=SONNET, tools_mode="bt")
    with pytest.raises(H.HoError, match="effort 'low'"):
        direct(env, root, effort="low")
    assert env.logs() == [] and not (root / "prompts").exists()
    env.fake(mode="ok")
    env.ledger.reserve("qset", env.out_root / "qset" / "p1", "w1", 0.2)
    assert direct(env, env.out_root / "qset" / "p1", "w1", 0.2, SONNET, tools_mode="none").error is None


def test_inf9_a_transient_version_failure_is_retried_and_told_apart_from_a_change(env, tmp_path, monkeypatch):
    root = env.out_root / "ho"
    CL.pin_cli(root, env.pin)
    counter = tmp_path / "fail_count"
    monkeypatch.setenv("GTEST_VERSION_FAIL", str(counter))
    counter.write_text("1")
    assert CL.check_claude_version(root, FAKE_VERSION).startswith(FAKE_VERSION)
    counter.write_text(str(CL.VERSION_TRIES))
    with pytest.raises(CL.CliUnavailable, match="no answer"):
        CL.check_claude_version(root, FAKE_VERSION)
    counter.write_text("5")
    monkeypatch.setenv("GTEST_VERSION_SLEEP", "3")
    monkeypatch.setattr(CL, "VERSION_TIMEOUT_S", 0.5)
    with pytest.raises(CL.CliUnavailable, match="TimeoutExpired"):
        CL.claude_version(root)
    monkeypatch.delenv("GTEST_VERSION_FAIL")
    with pytest.raises(CL.CliChanged, match="pinned 9.9.8"):
        CL.check_claude_version(root, "9.9.8")
    assert issubclass(CL.CliUnavailable, H.HoError) and issubclass(CL.CliChanged, H.HoError)
    assert not issubclass(CL.CliUnavailable, CL.CliChanged)


def test_inf9_a_tampered_copy_is_a_cli_change(env):
    Path(env.pin.cli_path).write_text(Path(env.pin.cli_path).read_text() + "# self-update\n")
    with pytest.raises(CL.CliChanged, match="pinned copy"):
        CL.check_cli(env.pin)


def test_inf10_run_error_as_claude_a_and_the_registered_fallback_rule():
    fb = [{"type": "system", "subtype": "model_refusal_fallback", "original_model": OPUS, "fallback_model": "m"}]
    capped = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 1.0}
    ok = {"type": "result", "subtype": "success", "is_error": False, "structured_output": {}, "modelUsage": {OPUS: {}}}
    assert CL.run_error(0, ok, [], OPUS) is None
    assert CL.run_error(0, ok, fb, OPUS).startswith("model fallback")
    assert CL.run_error(1, capped, fb, OPUS) == "result 'error_max_budget_usd' is_error=True"
    # claude_a + runs_a: run_error, then agent_limit -> an agent limit; here (§2.3: 模型改派 is an infra rerun) none
    assert CL.agent_limit(capped, 1.0) == "error_max_budget_usd"
    err, lim, fall = CL.outcome(1, capped, fb, OPUS, 1.0)
    assert err == CL.run_error(1, capped, fb, OPUS) and lim is None and fall.startswith("model fallback")


def test_inf11_launch_refuses_a_non_empty_auto_memory(env):
    mem = CL.memory_dir(env.cwd, env.home)
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("x")
    with pytest.raises(H.HoError, match="auto-memory"):
        launch(env, env.out_root / "ho")
    assert env.logs() == [] and env.ledger.snapshot()["runs"] == {}


def test_inf11_claude_must_resolve_inside_clibin(env, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    (other / "claude").write_text(f"#!/bin/sh\necho {FAKE_VERSION} '(Claude Code)'\n")
    (other / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{other}:/usr/bin:/bin")
    with pytest.raises(H.HoError, match="resolves to"):
        CL.claude_version(env.out_root / "ho")
    root = env.out_root / "ho"
    (root / "clibin").mkdir(parents=True)
    (root / "clibin" / "claude").write_text("#!/bin/sh\n")
    with pytest.raises(H.HoError, match="not a link"):
        CL.pin_cli(root, env.pin)


def test_inf11_a_success_without_structured_output_is_an_infra_failure(env):
    env.fake(mode="no_output")
    res = launch(env, env.out_root / "ho")
    assert res.error == "no structured output" and res.infra_failure and res.output is None


def test_inf11_the_ledger_counts_the_last_result_and_a_prompts_only_run(tmp_path):
    led, ho = LG.Ledger(tmp_path), tmp_path / "ho"
    (ho / "transcripts").mkdir(parents=True)
    (ho / "transcripts/r1.jsonl").write_text("\n".join(json.dumps({"type": "result", "total_cost_usd": c})
                                                       for c in (0.1, 0.7)) + "\n")
    (ho / "prompts").mkdir()
    (ho / "prompts/r2.json").write_text(json.dumps({"budget_usd": 1.5}))
    runs = led.snapshot()["runs"]
    assert runs["ho/r1"]["cost_usd"] == 0.7 and runs["ho/r2"] == {"kind": "ho", "cost_usd": 1.5, "source": "prompts"}


def test_inf11_only_a_refused_error_result_counts_as_denied():
    assert TR.is_denied({"is_error": True, "content": "Permission denied by hook"})
    assert not TR.is_denied({"is_error": True, "content": "command failed"})
    assert not TR.is_denied({"is_error": False, "content": "denied appears in the text"})
    failed = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x1", "is_error": True,
                                                  "content": "exit 1"}]}}]
    assert "t_tool" in _errors(TR.check_events(_events(extra=failed), _prompts(), OPUS, "bt"))


def test_inf11_t_result_needs_subtype_success():
    ev = _events()
    ev[-1] = {**ev[-1], "subtype": "error_during_execution"}
    assert "t_result" in {v.rule for v in TR.check_events(ev, _prompts(), OPUS, "bt")}


@pytest.mark.parametrize("where", ["structured_output", "tool_result"])
def test_inf11_markers_in_structured_output_and_tool_results_are_caught(where):
    ev = _events()
    if where == "structured_output":
        ev[-1] = {**ev[-1], "structured_output": {"value": 1, "note": "from gen_layer"}}
    else:
        ev[2]["message"]["content"][0]["content"] = "see gen_layer"
    assert "t_memory" in _errors(TR.check_events(ev, _prompts(), OPUS, "bt"))


def test_inf11_check_run_compares_the_pinned_cli_version(tmp_path):
    root = tmp_path / "root"
    (root / "transcripts").mkdir(parents=True)
    (root / "prompts").mkdir()
    (root / "transcripts/r1.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in _events()),
                                               encoding="utf-8")
    (root / "prompts/r1.json").write_text(json.dumps(_prompts(pin={"claude_version": "9.9.8"}), ensure_ascii=False),
                                          encoding="utf-8")
    assert any(v.rule == "t_init" and "claude_code_version" in v.detail for v in TR.check_run(root, "r1"))


def test_inf11_bt_guard_refuses_a_changed_file(tmp_path, monkeypatch):
    copy = tmp_path / "bt_guard.py"
    copy.write_text(H.BT_GUARD.read_text(encoding="utf-8") + "\n# patched\n", encoding="utf-8")
    monkeypatch.setattr(H, "BT_GUARD", copy)
    monkeypatch.delitem(sys.modules, H._GUARD_MODULE, raising=False)
    with pytest.raises(H.HoError, match="sha256"):
        H.bt_guard()
    assert H._GUARD_MODULE not in sys.modules


def test_run_reserved_releases_the_reservation_when_refused_before_start(env):
    (env.cwd / "left_over").write_text("x")
    root = env.out_root / "ho"
    with pytest.raises(H.HoError, match="not empty"):
        launch(env, root)
    assert not (root / "reserve/r1.json").exists() and env.ledger.spent() == 0
    (env.cwd / "left_over").unlink()
    env.fake(mode="ok")
    assert launch(env, root).error is None
    with pytest.raises(H.HoError, match="already exists"):
        launch(env, root)


@pytest.mark.parametrize("mode, why", [("fallback", "model fallback"), ("other_model", "modelUsage names other")])
def test_model_fallback_is_an_infrastructure_failure(env, mode, why):
    env.fake(mode=mode)
    res = launch(env, env.out_root / "ho")
    assert res.error.startswith(why) and res.fallback == res.error and res.limit is None and res.infra_failure


def test_agent_limit_is_the_agents_outcome(env):
    env.fake(mode="budget")
    res = launch(env, env.out_root / "ho", cap=1.5)
    assert res.limit == "error_max_budget_usd" and not res.infra_failure and res.fallback is None
    assert env.ledger.snapshot()["runs"]["ho/r1"]["cost_usd"] == 1.5


def test_a_crash_is_an_infrastructure_failure_and_counts_its_cap(env):
    env.fake(mode="crash")
    res = launch(env, env.out_root / "ho", cap=2.0)
    assert res.error.startswith("no result event") and res.infra_failure
    assert env.ledger.snapshot()["runs"]["ho/r1"] == {"kind": "ho", "cost_usd": 2.0, "source": "reserve"}


def test_outcome_rules_are_pure():
    fb = [{"type": "system", "subtype": "model_refusal_fallback", "original_model": OPUS, "fallback_model": "m"}]
    capped = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 1.0}
    assert CL.outcome(1, capped, [], OPUS, 1.0) == ("result 'error_max_budget_usd' is_error=True",
                                                    "error_max_budget_usd", None)
    err, lim, fall = CL.outcome(1, capped, fb, OPUS, 1.0)
    assert lim is None and fall.startswith("model fallback")
    ok = {"type": "result", "subtype": "success", "is_error": False, "structured_output": {}, "total_cost_usd": 1.0,
          "modelUsage": {OPUS: {}}}
    assert CL.outcome(0, ok, [], OPUS, 1.0) == (None, None, None)
    assert CL.outcome(-1, None, [], OPUS, 1.0, "timeout after 5s") == ("timeout after 5s", None, None)
    assert CL.agent_limit({"subtype": "error_during_execution", "total_cost_usd": 0.99999999999}, 1.0)


# ---------------------------------------------------------------- ledger
def _result_transcript(root: Path, run_id: str, cost: float) -> None:
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    (root / "transcripts" / f"{run_id}.jsonl").write_text(
        json.dumps({"type": "system", "subtype": "init"}) + "\n{torn\n" +
        json.dumps({"type": "result", "subtype": "success", "total_cost_usd": cost}) + "\n", encoding="utf-8")


def test_a_run_counts_its_result_else_its_reserved_cap(tmp_path):
    led, ho = LG.Ledger(tmp_path), tmp_path / "ho"
    led.reserve("ho", ho, "draft_Q01_1", 2.0)
    assert led.snapshot()["runs"]["ho/draft_Q01_1"] == {"kind": "ho", "cost_usd": 2.0, "source": "reserve"}
    _result_transcript(ho, "draft_Q01_1", 0.31)
    assert led.snapshot()["runs"]["ho/draft_Q01_1"]["source"] == "result" and led.spent() == 0.31
    (ho / "transcripts/audit_Q01_1.jsonl").write_text(json.dumps({"type": "system"}) + "\n")
    (ho / "prompts").mkdir()
    (ho / "prompts/audit_Q01_1.json").write_text(json.dumps({"budget_usd": 1.0}))
    (ho / "transcripts/fix_Q01_1.jsonl").write_text("")
    snap = led.snapshot()
    assert snap["runs"]["ho/audit_Q01_1"] == {"kind": "ho", "cost_usd": 1.0, "source": "prompts"}
    assert snap["runs"]["ho/fix_Q01_1"] == {"kind": "ho", "cost_usd": 2.0, "source": "cap_assumed"}
    (ho / "prompts/notes.json").write_text(json.dumps({"other": 1}))
    assert "ho/notes" not in led.snapshot()["runs"] and snap["total_usd"] == round(0.31 + 1.0 + 2.0, 6)


def test_every_root_of_every_kind_counts_and_other_folders_do_not(tmp_path):
    led = LG.Ledger(tmp_path)
    led.reserve("ho", tmp_path / "ho" / "kay", "kay_Q03_1", 1.5)
    led.reserve("qset", tmp_path / "qset" / "p2", "p2-j01_1", 0.2)
    led.reserve("probe", tmp_path / "probe" / "1", "bt_1", 0.12)
    _result_transcript(tmp_path / "ho", "draft_Q01_1", 0.5)
    _result_transcript(tmp_path / "power", "x", 9.0)                 # not a ledger base
    _result_transcript(tmp_path / "ho" / "bin", "y", 9.0)            # wrapper dirs are skipped
    snap = led.snapshot()
    assert snap["by_root"] == {"ho": 0.5, "ho/kay": 1.5, "probe/1": 0.12, "qset/p2": 0.2}
    assert snap["by_kind"] == {"probe": 0.12, "qset": 0.2, "ho": 2.0} and snap["total_usd"] == 2.32
    assert snap["probe_invocations"] == ["probe/1"] and snap["limit_usd"] == 49.0
    assert led.spent_by_root() == snap["by_root"]
    assert led.spent_of([("ho/kay", "kay_Q03_1"), (tmp_path / "ho", "draft_Q01_1"), ("ho", "nothing")]) == 2.0
    led.write_snapshot()
    assert json.loads((tmp_path / "ledger.json").read_text())["total_usd"] == 2.32


def test_refusal_at_49_usd(tmp_path):
    led, ho = LG.Ledger(tmp_path), tmp_path / "ho"
    for i in range(24):
        led.reserve("ho", ho, f"draft_{i}", 2.0)
    assert led.spent() == 48.0
    with pytest.raises(H.BudgetRefused, match="49"):
        led.reserve("ho", ho, "draft_24", 2.0)
    with pytest.raises(H.BudgetRefused):
        led.check(1.5, "ho")
    assert led.check(1.0, "ho") == 48.0
    led.reserve("ho", ho, "audit_24", 1.0)
    with pytest.raises(H.BudgetRefused):
        led.reserve("qset", tmp_path / "qset" / "p1", "g1", 0.2)
    with pytest.raises(H.BudgetRefused):
        led.reserve("probe", tmp_path / "probe" / "1", "bt_1", 0.12)
    assert not (ho / "reserve/draft_24.json").exists() and led.spent() == 49.0


def test_probe_sub_caps_money_and_invocations(tmp_path):
    led = LG.Ledger(tmp_path)
    for i in range(4):
        led.reserve("probe", tmp_path / "probe" / "1", f"bt_{i}", 0.2)
    with pytest.raises(H.BudgetRefused, match="probe 已花"):
        led.reserve("probe", tmp_path / "probe" / "2", "bt_1", 0.21)
    led.reserve("probe", tmp_path / "probe" / "2", "bt_1", 0.1)
    with pytest.raises(H.BudgetRefused, match="probe 已跑 2 次"):
        led.reserve("probe", tmp_path / "probe" / "3", "bt_1", 0.05)
    with pytest.raises(H.BudgetRefused, match="probe 已跑 2 次"):
        led.check(0.05, "probe", tmp_path / "probe" / "3")
    led.reserve("probe", tmp_path / "probe" / "2", "none_opus", 0.05)       # an open invocation goes on
    with pytest.raises(H.HoError, match="not under a ledger base"):
        led.reserve("probe", tmp_path / "probe", "x", 0.01)
    with pytest.raises(H.HoError, match="not under a ledger base"):
        led.reserve("probe", tmp_path / "probe" / "2" / "deeper", "x", 0.01)
    with pytest.raises(H.HoError, match="belongs to kind ho"):
        led.reserve("probe", tmp_path / "ho", "x", 0.01)
    led.reserve("ho", tmp_path / "ho", "draft_1", 2.0)                     # HO is not held by the probe cap


def test_qset_sub_cap(tmp_path):
    led, p1 = LG.Ledger(tmp_path), tmp_path / "qset" / "p1"
    for i in range(15):
        led.reserve("qset", p1, f"p1-j{i:02d}_1", 0.2)
    with pytest.raises(H.BudgetRefused, match="qset 已花"):
        led.reserve("qset", tmp_path / "qset" / "p2", "p2-j00_1", 0.2)
    with pytest.raises(H.HoError, match="belongs to kind qset"):
        led.reserve("ho", p1, "x", 0.2)
    led.reserve("ho", tmp_path / "ho", "draft_1", 2.0)


@pytest.mark.parametrize("kind, cap", [("qset", 0.5), ("ho", 2.5), ("probe", 1.5), ("ho", 0), ("ho", -1),
                                       ("ho", True), ("ho", "1")])
def test_a_job_cap_must_fit_its_kind(tmp_path, kind, cap):
    root = {"qset": tmp_path / "qset" / "p1", "ho": tmp_path / "ho", "probe": tmp_path / "probe" / "1"}[kind]
    with pytest.raises(H.HoError, match="job cap"):
        LG.Ledger(tmp_path).reserve(kind, root, "r1", cap)
    assert not (root / "reserve").exists()


def test_run_ids_and_release(tmp_path):
    led, ho = LG.Ledger(tmp_path), tmp_path / "ho"
    for bad in ("../x", "a/b", "", ".hidden", "x" * 130):
        with pytest.raises(H.HoError, match="plain id"):
            led.reserve("ho", ho, bad, 1.0)
    with pytest.raises(H.HoError, match="kind"):
        led.reserve("haiku", ho, "r1", 1.0)
    led.reserve("ho", ho, "r1", 1.0)
    with pytest.raises(H.HoError, match="already exists"):
        led.reserve("ho", ho, "r1", 1.0)
    assert led.release(ho, "r1") and not led.release(ho, "r1") and led.spent() == 0
    led.reserve("ho", ho, "r2", 1.0)
    (ho / "transcripts").mkdir()
    (ho / "transcripts/r2.jsonl").write_text("")
    assert not led.release(ho, "r2") and led.spent() == 1.0


def _contend(out_root: str, sub: str, n: int, barrier, queue) -> None:
    led, got = LG.Ledger(out_root), 0
    barrier.wait()
    for i in range(n):
        try:
            led.reserve("ho", Path(out_root) / "ho" / sub, f"draft_{i}", 2.0)
            got += 1
        except LG.BudgetRefused:
            pass
    queue.put(got)


def test_two_processes_contending_never_overrun_the_cap(tmp_path):
    ctx = multiprocessing.get_context("fork")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_contend, args=(str(tmp_path), sub, 20, barrier, queue)) for sub in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    assert [p.exitcode for p in procs] == [0, 0]
    got = sorted(queue.get(timeout=5) for _ in procs)
    assert sum(got) == 24 and LG.Ledger(tmp_path).spent() == 48.0


def test_threads_contending_never_overrun_the_cap(tmp_path):
    led, got, lock = LG.Ledger(tmp_path), [], threading.Lock()

    def work(t: int) -> None:
        for i in range(5):
            try:
                led.reserve("ho", tmp_path / "ho", f"draft_{t}_{i}", 2.0)
                with lock:
                    got.append(1)
            except LG.BudgetRefused:
                pass
    threads = [threading.Thread(target=work, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 24 and led.spent() == 48.0


def test_ledger_defaults_are_the_prereg_values():
    assert LG.SPEND_LIMIT_USD == 49.0 and LG.KIND_JOB_CAP == {"probe": 1.0, "qset": 0.2, "ho": 2.0}
    led = LG.Ledger()
    assert led.base("probe") == H.PROBE_ROOT and led.base("qset") == GC.QSET_ROOT and led.base("ho") == GC.HO_ROOT


# ---------------------------------------------------------------- transcript rules
def _events(tools_mode: str = "bt", model: str = OPUS, cwd: str = "/srv", extra: list | None = None) -> list:
    out = {"value": 1, "note": "柯梅的年歲依兩節相加"}
    calls = [
        {"type": "assistant", "message": {"usage": {"input_tokens": 9}, "content": [
            {"type": "thinking", "thinking": "Read both begetting lines first."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "bt v gen.5.3-gen.5.8"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "gen.5.3 柯梅記事一\ngen.5.6 柏羅丹記事二"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "bt grep '茵德' gen"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "[1 筆]"}]}},
    ] if tools_mode == "bt" else []
    return [{"type": "system", "subtype": "init", "cwd": cwd, "model": model, "claude_code_version": FAKE_VERSION,
             "tools": ["Bash", "StructuredOutput"] if tools_mode == "bt" else ["StructuredOutput"],
             "mcp_servers": [], "permissionMode": "dontAsk"},
            *calls, *(extra or []),
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Checked against both lines."},
                {"type": "tool_use", "id": "t9", "name": "StructuredOutput", "input": out}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "done", "structured_output": out}]


def _prompts(**over) -> dict:
    doc = {"system": "You write one question.", "user": "Write about 柯梅 and 茵德.", "schema": SCHEMA,
           "model": OPUS, "tools_mode": "bt", "user_scope": "prompt", "tool_values": {"x": "柯梅", "y": "茵德"},
           "cwd": "/srv", "pin": {"claude_version": FAKE_VERSION}}
    doc.update(over)
    return doc


def _errors(vs) -> set:
    return {v.rule for v in vs if v.level == "error"}


def test_k0_compliant_transcripts_pass_every_blinding_rule_in_both_modes():
    assert TR.BLINDING_RULES == {"t_init", "t_tool", "t_path", "t_memory", "t_banned"}
    assert TR.check_events(_events(), _prompts(), OPUS, "bt", Path("/srv"), FAKE_VERSION) == []
    none = TR.check_events(_events("none", SONNET), _prompts(model=SONNET, tools_mode="none"), SONNET, "none",
                           Path("/srv"), FAKE_VERSION)
    assert none == []


def test_k0_a_leaking_transcript_fails():
    ev = _events()
    ev[1]["message"]["content"][0]["thinking"] = "Compare with the T-rows arm from gen_layer."
    found = {(v.rule, v.level) for v in TR.check_events(ev, _prompts(), OPUS, "bt")}
    assert ("t_memory", "error") in found and ("t_banned_agent", "warn") in found
    assert TR.blinding(TR.check_events(ev, _prompts(), OPUS, "bt"))


def test_tool_rules_per_mode():
    ls = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x1", "name": "Bash", "input": {"command": "ls"}}]}}]
    denied = ls + [{"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "x1", "is_error": True, "content": "denied: only `bt` may run"}]}}]
    assert "t_tool" in _errors(TR.check_events(_events(extra=ls), _prompts(), OPUS, "bt"))
    vs = TR.check_events(_events(extra=denied), _prompts(), OPUS, "bt")
    assert _errors(vs) == set() and {v.rule for v in vs} == {"t_tool_denied"}
    for cmd in ("bt x; ls", "bt v ../*", "cat x"):
        bad = [{"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "x2", "name": "Bash", "input": {"command": cmd}}]}}]
        assert "t_tool" in _errors(TR.check_events(_events(extra=bad), _prompts(), OPUS, "bt"))
    read = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x3", "name": "Read", "input": {"file_path": "notes.txt"}}]}}]
    assert "t_tool" in _errors(TR.check_events(_events(extra=read), _prompts(), OPUS, "bt"))
    bt_in_none = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x4", "name": "Bash", "input": {"command": "bt books"}}]}}]
    none = _prompts(model=SONNET, tools_mode="none")
    assert "t_tool" in _errors(TR.check_events(_events("none", SONNET, extra=bt_in_none), none, SONNET, "none"))
    assert "t_init" in _errors(TR.check_events(_events("bt", SONNET), none, SONNET, "none"))


def test_path_rule():
    text = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "saved in /home/someone/x"}]}}]
    assert "t_path" in _errors(TR.check_events(_events(extra=text), _prompts(), OPUS, "bt"))
    rel = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x5", "name": "Bash", "input": {"command": "bt v gen.5.3 ../notes"}}]}}]
    assert "t_path" in _errors(TR.check_events(_events(extra=rel), _prompts(), OPUS, "bt"))
    assert "t_path" not in _errors(TR.check_events(_events(), _prompts(system="Run from /srv."), OPUS, "bt"))


def test_init_rules():
    for change, model, cwd in (({"model": SONNET}, OPUS, "/srv"), ({}, OPUS, "/elsewhere"),
                               ({"cwd": str(GC.REPO)}, OPUS, str(GC.REPO)), ({"claude_code_version": "9.9.8"}, OPUS, "/srv"),
                               ({"mcp_servers": [{"name": "m"}]}, OPUS, "/srv"), ({"permissionMode": "default"}, OPUS, "/srv"),
                               ({"tools": ["Bash", "Read", "StructuredOutput"]}, OPUS, "/srv")):
        ev = _events()
        ev[0].update(change)
        assert "t_init" in _errors(TR.check_events(ev, _prompts(), model, "bt", Path(cwd), FAKE_VERSION)), change
    assert _errors(TR.check_events(_events()[1:], _prompts(), OPUS, "bt")) == {"t_init"}
    no_version = _events()
    del no_version[0]["claude_code_version"]
    assert TR.check_events(no_version, _prompts(), OPUS, "bt", Path("/srv"), FAKE_VERSION) == []


def test_scope_rule_of_prompt_parts():
    ok = TR.check_events(_events(), _prompts(user="依創世記，柯梅幾歲時茵德出生？", user_scope="agent"), OPUS, "bt")
    assert ok == []
    assert "t_banned" in _errors(TR.check_events(_events(), _prompts(user="柯梅幾歲？"), OPUS, "bt"))
    assert "t_banned" in _errors(TR.check_events(_events(), _prompts(system="Ask how old (幾歲)."), OPUS, "bt"))
    assert "t_banned" in _errors(TR.check_events(_events(), _prompts(tool_values={"definition": "去世"}), OPUS, "bt"))
    schema = {**SCHEMA, "description": "the 算術 answer"}
    assert "t_banned" in _errors(TR.check_events(_events(), _prompts(schema=schema), OPUS, "bt"))
    vs = TR.check_events(_events(), _prompts(user="Fix this: B0 here", user_scope="agent"), OPUS, "bt")
    assert _errors(vs) == set() and {v.rule for v in vs} == {"t_banned_agent"}
    assert "t_memory" in _errors(TR.check_events(_events(), _prompts(user="see gen_layer", user_scope="agent"),
                                                 OPUS, "bt"))


def test_cue_words_in_agent_output_are_never_checked():
    ev = _events()
    ev[-2]["message"]["content"][0]["text"] = "柯梅幾歲時茵德出生？柯梅去世嗎"
    assert TR.check_events(ev, _prompts(), OPUS, "bt") == []


def test_check_run_reads_model_mode_cwd_and_version_from_the_prompts_record(tmp_path):
    root = tmp_path / "root"
    (root / "transcripts").mkdir(parents=True)
    (root / "prompts").mkdir()
    (root / "transcripts/r1.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in _events()),
                                               encoding="utf-8")
    assert TR.check_run(root, "r1") == [H.Violation("t_init", "r1: no model / tools mode (prompts record missing "
                                                              "or incomplete)")]
    (root / "prompts/r1.json").write_text(json.dumps(_prompts(), ensure_ascii=False), encoding="utf-8")
    assert TR.check_run(root, "r1") == [] and TR.blinding_errors(root, ["r1"]) == []
    (root / "prompts/r1.json").write_text(json.dumps(_prompts(model=SONNET), ensure_ascii=False), encoding="utf-8")
    assert "t_init" in _errors(TR.check_run(root, "r1"))
    assert TR.check_run(root, "r2")[0].rule == "t_result"


# ---------------------------------------------------------------- bt_g
SYN_UNITS = [("gen.5.3", "gen", 5, 3, 3, "柯梅記事一"), ("gen.5.4-5", "gen", 5, 4, 5, "柏羅丹記事二"),
             ("gen.5.6", "gen", 5, 6, 6, "茵德記事三"), ("rut.1.1", "rut", 1, 1, 1, "瓦勒記事四")]
SYN_BOOKS = [("gen", "甲書", 50, 1), ("rut", "乙書", 4, 8)]


@pytest.fixture
def syn_text(tmp_path, monkeypatch):
    units = "\n".join(json.dumps({"unit_key": k, "book_id": b, "chapter": c, "v_start": s, "v_end": e, "text": t,
                                  "ord": i}, ensure_ascii=False) for i, (k, b, c, s, e, t) in enumerate(SYN_UNITS))
    books = "\n".join(json.dumps({"book_id": b, "name": n, "chapter_count": c, "ord": o}, ensure_ascii=False)
                      for b, n, c, o in SYN_BOOKS)
    (tmp_path / "verse_units.jsonl").write_text(units + "\n", encoding="utf-8")
    (tmp_path / "books.jsonl").write_text(books + "\n", encoding="utf-8")
    monkeypatch.setattr(BT, "TEXT", tmp_path)
    monkeypatch.setattr(BT, "TEXT_SHA256", {n: H.sha256_file(tmp_path / n) for n in ("verse_units.jsonl", "books.jsonl")})
    monkeypatch.setattr(BT, "MAX_LINES", 3)
    BT.clear_caches()
    yield tmp_path
    BT.clear_caches()


def _bt(*argv) -> tuple[int, str]:
    out = io.StringIO()
    return BT.main(list(argv), out), out.getvalue()


def test_bt_g_reads_keys_merged_keys_and_ranges(syn_text):
    assert _bt("v", "gen.5.3") == (0, "gen.5.3 柯梅記事一\n")
    assert _bt("v", "gen.5.5") == (0, "gen.5.4-5 柏羅丹記事二\n")
    assert _bt("v", "gen.5.3-gen.5.6")[1].splitlines() == ["gen.5.3 柯梅記事一", "gen.5.4-5 柏羅丹記事二", "gen.5.6 茵德記事三"]
    assert _bt("v", "gen.5.3a") == (0, "gen.5.3a <<半節鍵不支援，請用整節>>\n")
    assert _bt("v", "gen.9.9") == (0, "gen.9.9 <<查無此節>>\n")
    assert _bt("v", "gen.5.3-rut.1.1") == (0, f"gen.5.3-rut.1.1 <<{BT._PROBLEM['long']}>>\n")
    assert _bt("v", "../x/y") == (0, "第1個參數 <<查無此節>>\n")


def test_bt_g_grep_books_and_usage(syn_text):
    assert _bt("grep", "記事", "rut") == (0, "rut.1.1 瓦勒記事四\n[1 筆]\n")
    assert _bt("grep", "記事[一二三]")[1].splitlines()[-1] == "[3 筆]"              # exactly MAX_LINES hits
    code, out = _bt("grep", "記事")
    assert code == 0 and out.splitlines()[-1] == "... 共 4 筆，只顯示前 3 筆；請縮小正規式或書卷"
    assert _bt("books") == (0, "gen 甲書 50\nrut 乙書 4\n")
    for argv, why in ((("grep", "記事", "xyz,/etc"), "不認得的書卷 第1個參數, xyz"), (("grep", "("), "正規式無法解析"),
                      ((), "缺少子命令"), (("rm",), "不認得的子命令 rm"), (("v",), "v 的參數不對"), (("books", "x"), "books 的參數不對")):
        code, out = _bt(*argv)
        assert code == 2 and why in out and "用法" in out and "/" not in out.replace("/etc", ""), argv


def test_bt_g_refuses_a_changed_text_layer_neutrally(syn_text):
    with open(syn_text / "verse_units.jsonl", "a", encoding="utf-8") as f:
        f.write("\n")
    BT.clear_caches()
    code, out = _bt("v", "gen.5.3")
    assert code == 2 and out == "錯誤：資料檔核對失敗，請停止並回報\n"
    (syn_text / "books.jsonl").unlink()
    code, out = _bt("books")
    assert code == 2 and out == "錯誤：工具內部錯誤（FileNotFoundError），請停止並回報\n"


def test_bt_g_pins_equal_bt_a_and_it_imports_no_c_common():
    src = (HO_A / "bt_a.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    pins = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", None) == "TEXT_SHA256")
    assert pins == BT.TEXT_SHA256 and BT.TEXT == TEXT_DIR
    code = (f"import sys; sys.path.insert(0, {str(H_DIR)!r}); import bt_g;"
            "print('c_common' in sys.modules, 'g_common' in sys.modules, 'hog_common' in sys.modules)")
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["False", "False", "False"]


BT_CASES = (("books",), ("v", "gen.1.1"), ("v", "gen.5.3-gen.5.8"), ("v", "gen.24.30"), ("v", "gen.5.3a"),
            ("v", "gen.99.1"), ("v", "gen.1.1-gen.11.32"), ("grep", "瑪土撒拉", "gen"), ("grep", "^起初", "gen,exo"),
            ("grep", "(", "gen"), ("grep", "x", "zzz"), ("v", "../*"), ("x",))


@needs_text
def test_bt_g_on_the_real_store_matches_bt_a_through_the_wrapper(tmp_path):
    for name, sha in BT.TEXT_SHA256.items():
        assert H.sha256_file(TEXT_DIR / name) == sha, name
    CL.write_wrappers(tmp_path, "bt")
    bt = tmp_path / "bin" / "bt"
    differ, bad_exit, leaked = [], [], []
    for argv in BT_CASES:
        g = subprocess.run([str(bt), *argv], capture_output=True, text=True, timeout=120)
        a = subprocess.run([sys.executable, "-B", str(HO_A / "bt_a.py"), *argv], capture_output=True, text=True,
                           timeout=120)
        if hashlib.sha256(g.stdout.encode()).digest() != hashlib.sha256(a.stdout.encode()).digest():
            differ.append(argv)
        if g.returncode != a.returncode or g.stderr:
            bad_exit.append(argv)
        if any(m in g.stdout for m in ("/mnt", "/home", "Traceback", "bible_rag_store")):
            leaked.append(argv)
    assert differ == [] and bad_exit == [] and leaked == []
    n_books = subprocess.run([str(bt), "books"], capture_output=True, text=True, timeout=120).stdout.count("\n")
    assert n_books == 66


# ---------------------------------------------------------------- probe
def test_probe_prompts_pass_the_full_check_with_the_real_cue_words():
    try:
        with B.override_cue_literals(None):
            B.cue_literals()
            PR.check_prompts()
    except (ImportError, RuntimeError) as err:
        pytest.skip(f"gencard not importable: {err}")
    with B.override_cue_literals(("路得記",)):
        with pytest.raises(H.HoError, match="probe user prompt"):
            PR.check_prompts()


def test_probe_plan_and_caps_fit_two_invocations_in_the_probe_allowance():
    plan = PR.plan()
    assert [p[:3] for p in plan] == [("bt_1", "bt", "opus"), ("bt_2", "bt", "opus"), ("bt_3", "bt", "opus"),
                                     ("none_opus", "none", "opus"), ("none_sonnet", "none", "sonnet")]
    assert PR.INVOCATION_CAP_USD == round(sum(p[3] for p in plan), 6) == 0.46
    assert GC.PROBE_MAX_RUNS * PR.INVOCATION_CAP_USD <= GC.PROBE_CAP_USD - 0.05
    assert all(p[3] <= LG.KIND_JOB_CAP["probe"] for p in plan)


def _store_costs(pattern: str) -> dict[str, tuple[float, list]]:
    out = {}
    for f in sorted((GC.STORE / "reports").glob(pattern)):
        res = [json.loads(x) for x in f.read_bytes().decode("utf-8", "replace").splitlines() if '"type": "result"' in x
               or '"type":"result"' in x]
        if res:
            out[f.stem] = (res[-1]["total_cost_usd"], sorted(res[-1].get("modelUsage") or {}))
    return out


@pytest.mark.skipif(not (GC.STORE / "reports/kg_cards_20261018/A_confirm/ho/probe/transcripts").is_dir(),
                    reason="A's probe transcripts not mounted")
def test_probe_caps_cover_the_real_probe_costs_with_margin():
    a = _store_costs("kg_cards_20261018/A_confirm/ho/probe/transcripts/probe_*.jsonl")
    q = _store_costs("regnal_qset_20261019/probe/transcripts/probe_*.jsonl")
    assert len(a) == 6 and set(q) == {"probe_opus_1", "probe_sonnet_1"}
    clean = [c for c, used in a.values() if used == [OPUS]]
    assert len(clean) == 4 and max(clean) * 2 <= PR.RUN_CAP_USD["bt"] and max(c for c, _ in a.values()) < PR.RUN_CAP_USD["bt"]
    assert q["probe_opus_1"][0] * 2 <= PR.RUN_CAP_USD["none_opus"]
    assert q["probe_sonnet_1"][0] * 2 <= PR.RUN_CAP_USD["none_sonnet"]


def _probe(env, **kw):
    return PR.probe(FAKE_VERSION, out_root=env.out_root, versions_dir=env.versions, cwd=env.cwd, home=env.home,
                    timeout_s=60, cli_sha256=env.sha, **kw)


def test_probe_end_to_end_with_the_fake_cli_pins_both_modes(env, tmp_path):
    env.fake(mode="probe", cost=0.03)
    doc = _probe(env)
    assert doc["pass"] and doc["action"] == "pin" and doc["root"] == "probe/1" and doc["reps"] == 5
    assert doc["checks"]["bt"] == dict.fromkeys(PR.BT_KEYS, "pass")
    assert doc["checks"]["none"] == dict.fromkeys(PR.NONE_KEYS, "pass")
    assert doc["models"] == CL.MODELS and doc["cost_usd"] == 0.15
    assert all(r["checks"]["detail"]["offline_denied"] == dict.fromkeys(PR.OFFLINE_DENY, True)
               for r in doc["runs"] if r["mode"] == "bt")
    path = PR.write_verdict(doc, env.out_root)
    assert path == env.out_root / "probe" / "verdict_1.json"
    pin_path = PR.pin_from(path, pin_path=tmp_path / "cli_pin.json")
    pin = CL.load_pin(pin_path)
    assert pin == CL.CliPin(FAKE_VERSION, env.pin.cli_sha256, env.pin.cli_path, True, CL.MODELS)
    rec = json.loads(pin_path.read_text())
    assert rec["verdict_sha256"] == H.sha256_file(path) and rec["cli_sha_basis"] == "operator"
    assert rec["env_keys"] == doc["env_keys"] and "PATH" in doc["env_keys"] and "AI_AGENT" not in doc["env_keys"]
    assert doc["cli_sha_basis"] == "operator" and doc["cli_source"]["source_size"] > 0
    assert doc["combos"] == [list(c) for c in CL.PROBED_COMBOS]
    assert env.ledger.snapshot()["by_root"] == {"probe/1": 0.15}
    recs = [json.loads((env.out_root / "probe/1/prompts" / f"{r[0]}.json").read_text()) for r in PR.plan()]
    assert [r["tools_mode"] for r in recs] == ["bt", "bt", "bt", "none", "none"]
    assert {r["user_scope"] for r in recs} == {"prompt"} and [r["model"] for r in recs][-2:] == [OPUS, SONNET]
    assert {tuple(r["env_keys"]) for r in recs} == {tuple(doc["env_keys"])}


def test_inf11_pin_from_rechecks_the_copy_and_the_models(env, tmp_path):
    env.fake(mode="probe", cost=0.03)
    path = PR.write_verdict(_probe(env), env.out_root)
    doc = json.loads(path.read_text())
    bad = tmp_path / "bad_models.json"
    bad.write_text(json.dumps({**doc, "models": {**doc["models"], "opus": "claude-other-0"}}))
    with pytest.raises(H.HoError, match="verdict models"):
        PR.pin_from(bad, pin_path=tmp_path / "p0.json")
    few = tmp_path / "few_combos.json"
    few.write_text(json.dumps({**doc, "combos": [["bt", "opus"]]}))
    with pytest.raises(H.HoError, match="combos"):
        PR.pin_from(few, pin_path=tmp_path / "p1.json")
    Path(env.pin.cli_path).write_text(Path(env.pin.cli_path).read_text() + "# self-update\n")
    with pytest.raises(CL.CliChanged, match="pinned copy"):
        PR.pin_from(path, pin_path=tmp_path / "p2.json")
    assert not any((tmp_path / f"p{i}.json").exists() for i in range(3))


def test_inf11_verdict_refuses_inconsistent_models_and_a_rejection_needs_the_flag():
    bt_ok, none_ok = dict.fromkeys(PR.BT_KEYS, "pass"), dict.fromkeys(PR.NONE_KEYS, "pass")
    nones = [_run("none", none_ok, key="opus"), _run("none", none_ok, key="sonnet")]
    odd = _run("bt", bt_ok)
    odd["checks"]["detail"]["resolved"] = "claude-other-0"
    v = PR.verdict([_run("bt", bt_ok), odd, _run("bt", bt_ok)] + nones, "9", "a" * 64, "/x", True, "9")
    assert v["action"] == "stop" and not v["pass"] and v["pin"] is None
    rejected = [_run("bt", {**bt_ok, "c1_init": "fail", "c5_result": "fail"}, False)] * 3 + \
        [_run("none", {**none_ok, "c1_init": "fail", "c5_result": "fail"}, False, k) for k in ("opus", "sonnet")]
    assert PR.verdict(rejected, "9", "a" * 64, "/x", False, "9")["action"] == "stop"


def test_inf11_c2_hook_needs_every_offline_denial_and_none_mode_rejects_other_tools():
    ls = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x1", "is_error": True,
                                                  "content": "denied: only `bt` may run"}]}}]
    ev, prompts = _events(extra=ls), _prompts()
    offline = dict.fromkeys(PR.OFFLINE_DENY, True)
    assert PR.bt_checks(ev, prompts, True, True, offline, OPUS, Path("/srv"), FAKE_VERSION)["c2_hook"] == "pass"
    for cmd in PR.OFFLINE_DENY:
        got = PR.bt_checks(ev, prompts, True, True, {**offline, cmd: False}, OPUS, Path("/srv"), FAKE_VERSION)
        assert got["c2_hook"] == "fail", cmd
    bt_call = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "x4", "name": "Bash", "input": {"command": "bt books"}}]}}]
    none = PR.none_checks(_events("none", SONNET, extra=bt_call), _prompts(model=SONNET, tools_mode="none"), SONNET,
                          True, SCHEMA, Path("/srv"), FAKE_VERSION)
    assert none["c2_structured_output"] == "fail"


def test_probe_stops_on_a_fallback_and_never_pins(env, tmp_path):
    env.fake(mode="fallback")
    doc = _probe(env)
    assert not doc["pass"] and doc["action"] == "stop" and doc["pin"] is None
    assert doc["checks"]["bt"]["c1_init"] == "fail" and doc["checks"]["none"]["c3_model"] == "fail"
    with pytest.raises(H.HoError, match="no pin|models"):
        PR.pin_from(PR.write_verdict(doc, env.out_root), pin_path=tmp_path / "cli_pin.json")
    assert not (tmp_path / "cli_pin.json").exists()


def test_probe_invocations_are_limited_by_the_ledger(env):
    env.fake(mode="probe", cost=0.03)
    assert _probe(env)["root"] == "probe/1" and _probe(env)["root"] == "probe/2"
    with pytest.raises(H.BudgetRefused, match="probe 已跑 2 次"):
        _probe(env)
    assert not (env.out_root / "probe/3/reserve").exists() and env.ledger.snapshot()["by_kind"]["probe"] == 0.3


def test_probe_refuses_an_invocation_that_does_not_fit(env):
    env.ledger.reserve("probe", env.out_root / "probe" / "1", "bt_1", 0.6)
    with pytest.raises(H.BudgetRefused, match="probe 已花"):
        _probe(env)
    assert env.logs() == []


def test_probe_reports_a_version_mismatch_without_launching(env):
    (env.versions / "9.9.7").write_text((env.versions / FAKE_VERSION).read_text())
    (env.versions / "9.9.7").chmod(0o755)
    doc = _probe_version(env, "9.9.7")
    assert doc["action"] == "stop" and "pinned 9.9.7" in doc["error"] and doc["runs"] == []
    assert [x for x in env.logs() if x["argv"][:1] == ["-p"]] == []


def _probe_version(env, version):
    return PR.probe(version, out_root=env.out_root, versions_dir=env.versions, cwd=env.cwd, home=env.home, timeout_s=60,
                    cli_sha256=env.sha)


def _run(mode: str, checks: dict, has_init: bool = True, key: str = "opus") -> dict:
    return {"mode": mode, "model_key": key, "checks": {**checks, "detail": {"has_init": has_init,
                                                                             "resolved": CL.MODELS[key], "cost_usd": 0.01}}}


def test_verdict_actions():
    bt_ok, none_ok = dict.fromkeys(PR.BT_KEYS, "pass"), dict.fromkeys(PR.NONE_KEYS, "pass")
    nones = [_run("none", none_ok, key="opus"), _run("none", none_ok, key="sonnet")]
    v = PR.verdict([_run("bt", bt_ok)] * 3 + nones, "9", "a" * 64, "/x", True, "9 (Claude Code)")
    assert v["action"] == "pin" and v["pin"]["models"] == CL.MODELS
    no_think = {**bt_ok, "c3_thinking": "fail"}
    assert PR.verdict([_run("bt", no_think)] * 3 + nones, "9", "a" * 64, "/x", True, "9")["action"] == \
        "drop_thinking_display"
    rejected = [_run("bt", {**bt_ok, "c1_init": "fail", "c5_result": "fail"}, False)] * 3 + \
        [_run("none", {**none_ok, "c1_init": "fail", "c5_result": "fail"}, False, k) for k in ("opus", "sonnet")]
    assert PR.verdict(rejected, "9", "a" * 64, "/x", True, "9")["action"] == "rerun_no_thinking_display"
    assert PR.verdict([_run("bt", bt_ok)] * 3, "9", "a" * 64, "/x", True, "9")["action"] == "stop"
    assert PR.verdict([], "9", "a" * 64, "/x", True, "9")["action"] == "stop"


def test_pin_from_needs_a_recorded_rejection_or_an_explicit_drop(env, tmp_path):
    env.fake(mode="probe", cost=0.03, thinking=False)
    doc = _probe(env)
    assert doc["action"] == "drop_thinking_display"
    path = PR.write_verdict(doc, env.out_root)
    with pytest.raises(H.HoError, match="no pin"):
        PR.pin_from(path, pin_path=tmp_path / "p.json")
    pin = CL.load_pin(PR.pin_from(path, drop_thinking=True, pin_path=tmp_path / "p.json"))
    assert pin.thinking_display is False
    passing = PR.write_verdict({**_probe(env, thinking=False), "root": "probe/9"}, env.out_root)
    assert json.loads(passing.read_text())["action"] == "pin"
    with pytest.raises(H.HoError, match="after-rejected"):
        PR.pin_from(passing, pin_path=tmp_path / "q.json")


def test_bt_and_none_checks_catch_their_failures():
    prompts = _prompts(user_scope="prompt")
    ev = _events()
    offline = dict.fromkeys(PR.OFFLINE_DENY, True)
    c = PR.bt_checks(ev, prompts, True, True, offline, OPUS, Path("/srv"), FAKE_VERSION)
    assert c["c2_hook"] == "fail" and c["detail"]["denied"] == {"ls": False}          # no live ls refused
    assert {k: c[k] for k in ("c1_init", "c3_thinking", "c4_no_memory", "c5_result")} == \
        dict.fromkeys(("c1_init", "c3_thinking", "c4_no_memory", "c5_result"), "pass")
    assert PR.bt_checks(ev, prompts, True, False, offline)["c4_no_memory"] == "fail"
    big = _events()
    big[1]["message"]["usage"] = {"input_tokens": 3, "cache_creation_input_tokens": 9000}
    assert PR.bt_checks(big, prompts, True, True, offline)["c4_no_memory"] == "fail"
    none = PR.none_checks(_events("none", SONNET), _prompts(model=SONNET, tools_mode="none"), SONNET, True,
                          SCHEMA, Path("/srv"), FAKE_VERSION)
    assert none["c3_model"] == "fail" and none["c2_structured_output"] == "pass"             # no modelUsage


# ---------------------------------------------------------------- sys.modules and the text-layer scan
def test_no_module_of_a_ho_a_or_the_qset_is_loaded():
    code = (f"import sys, json; sys.path.insert(0, {str(H_DIR)!r});"
            "import hog_common, claude_g, bt_g, ledger_g, transcript_g, probe_g, banned_g;"
            "hog_common.bt_guard(); probe_g.plan();"
            "from pathlib import Path;"
            "cm = banned_g.override_cue_literals(('甲',)); cm.__enter__();"
            "transcript_g.check_events([], {}, 'm', 'bt'); probe_g.check_prompts();"
            "bad = sorted(m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None) and any("
            "d in m.__file__ for d in ('/ho_a/', '/A/confirm/', 'kg_cards_20261018', '2026-10-19_regnal_qset', "
            "'2026-10-20_arith_stage0')));"
            "gd = sorted(n for n, m in list(sys.modules.items()) if '2026-10-14_graph_gd' in (getattr(m, '__file__', '') or ''));"
            "print(json.dumps([bad, gd, 'c_common' in sys.modules, 'gencard' in sys.modules]))")
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(GC.REPO / "evaluation")).stdout
    assert json.loads(out) == [[], ["ho_banned_for_g", "ho_bt_guard_for_g"], False, False]


def test_no_module_of_a_ho_a_or_the_qset_is_loaded_with_the_real_cue_words():
    code = (f"import sys, json; sys.path.insert(0, {str(H_DIR)!r});"
            "import hog_common, claude_g, bt_g, ledger_g, transcript_g, probe_g, banned_g;\n"
            "try:\n    banned_g.cue_literals()\nexcept (ImportError, RuntimeError):\n    print('null'); sys.exit(0)\n"
            "hog_common.bt_guard(); transcript_g.check_events([], {'user': 'x'}, 'm', 'bt'); probe_g.check_prompts()\n"
            "bad = sorted(m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None) and any("
            "d in m.__file__ for d in ('/ho_a/', '/A/', 'kg_cards', '2026-10-19_regnal_qset', '2026-10-20_arith_stage0')))\n"
            "gd = sorted(n for n, m in list(sys.modules.items()) if '2026-10-14_graph_gd' in (getattr(m, '__file__', '') or ''))\n"
            "print(json.dumps([bad, gd, 'c_common' in sys.modules, 'gencard' in sys.modules]))")
    out = json.loads(subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
                                    cwd=str(GC.REPO / "evaluation")).stdout)
    if out is None:
        pytest.skip("gencard not importable")
    assert out == [[], ["ho_banned_for_g", "ho_bt_guard_for_g"], False, True]


@needs_text
def test_no_string_of_the_new_files_shares_an_8_character_window_with_the_text_layer():
    texts = [json.loads(x)["text"] for x in (TEXT_DIR / "verse_units.jsonl").read_text(encoding="utf-8").splitlines()
             if x.strip()]
    windows = {t[i:i + 8] for t in texts for i in range(len(t) - 7)}
    files = [H_DIR / f for f in NEW_FILES] + [Path(__file__)]
    strings = [n.value for p in files for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    shared = sum(1 for s in strings for i in range(len(s) - 7) if s[i:i + 8] in windows)
    assert len(strings) > 200 and shared == 0
