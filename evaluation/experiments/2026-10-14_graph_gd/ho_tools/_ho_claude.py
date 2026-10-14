"""Headless `claude -p` launches of the §7 drafting / audit agents (盲化).

What an agent gets (all checked by the 2026-10-14 probes in store ho/probe/, discarded):

* cwd AGENT_CWD (/srv: empty, root-owned, outside the repo). The SDK prints the cwd into
  the agent's environment block even with --system-prompt, so a store path such as
  .../graph_gd_20261014/ho/work would show the agent 'graph' and 'rag'; /srv shows nothing.
* --system-prompt = the frozen prompt's system section; the user prompt = its task section.
* tools: only Bash (--tools Bash), only `bt ...` (--allowedTools "Bash(bt *)"), the other
  built-ins in --disallowedTools, --permission-mode dontAsk. Claude Code still auto-allows
  read-only commands (ls, cat, `bt x; ls`), so a PreToolUse hook (`bt-guard` → bt_guard.py,
  via --settings) denies every Bash command that is not one plain `bt ...` call.
* `bt` and `bt-guard` are wrappers in <root>/bin put first on PATH, so neither the agent's
  commands nor a hook's deny message carry a repo path; bt's stderr goes to /dev/null.
* no user settings, CLAUDE.md, rules, memory, MCP, skills or sessions on disk:
  --setting-sources local, --strict-mcp-config, --disable-slash-commands,
  --no-session-persistence (not --safe-mode: it also drops the --settings hook).
* Claude Code still reports an auto-memory directory for the cwd (~/.claude/projects/-srv/
  memory/); launch() refuses to start while that directory holds anything.
* the parent's CLAUDE* environment variables are removed (nested launch was not blocked
  with CLAUDECODE set, but the child should not inherit effort, session or messaging ids).
* --thinking-display summarized (a CLI option not listed in --help; 2.1.299): without it
  every thinking block of a headless stream-json run is empty (signature only; pilot
  2026-10-14: 120 blocks, 0 characters). The setting showThinkingSummaries in --settings
  does not change that (probe 2026-10-14, store ho/probe/README.txt).
* `claude --version` must be CLAUDE_VERSION (附錄 A pin; --thinking-display is undocumented,
  so a new CLI version is re-probed with the store ho/probe method before the pin moves).

The stream-json transcript (--output-format stream-json --verbose) is written to
<root>/transcripts/<run_id>.jsonl and the rendered prompts to <root>/prompts/<run_id>.json.
It holds the prompts, the agent's text, API-side thinking summaries (not the raw thinking),
tool calls and results and the structured output; it does not hold the context Claude Code
injects itself (environment block, the account's e-mail), so no mechanical check sees that.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import EVAL_PYTHON, HO_DIR, REPO_ROOT, HoToolError, under

__all__ = ["MODEL", "EFFORT", "THINKING_DISPLAY", "AGENT_CWD", "ALLOWED_TOOLS", "DISALLOWED_TOOLS", "BT_WRAPPER",
           "GUARD_WRAPPER", "STATE_ENV", "RunResult", "write_wrappers", "child_env", "build_argv",
           "check_cwd", "launch", "read_events", "result_event", "usage_of", "guard_settings",
           "claude_version", "check_claude_version", "CLAUDE_VERSION", "memory_dir", "check_memory_dir"]

MODEL = "claude-opus-5-5"
EFFORT = "xhigh"                    # the effort the user's settings give this model (NEW82 drafting)
THINKING_DISPLAY = "summarized"     # thinking summaries in the transcript (else they are empty)
AGENT_CWD = Path("/srv")
CLAUDE_BIN = "claude"
CLAUDE_VERSION = "2.1.299"          # pinned in 附錄 A
ALLOWED_TOOLS = ("Bash(bt *)",)
DISALLOWED_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "WebFetch",
                    "WebSearch", "Task", "Agent", "NotebookEdit", "NotebookRead", "TodoWrite",
                    "Skill", "ToolSearch", "KillShell", "BashOutput")
BT_WRAPPER, GUARD_WRAPPER = "bt", "bt-guard"
STATE_ENV = "HOBT_STATE"
DEFAULT_TIMEOUT_S = 3600


@dataclass(frozen=True)
class RunResult:
    run_id: str
    transcript: Path
    returncode: int
    seconds: float
    result: Mapping[str, Any] | None           # the stream's final 'result' event
    error: str | None = None                   # infrastructure failure, None when usable
    usage: Mapping[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> Mapping[str, Any] | None:
        return None if self.result is None else self.result.get("structured_output")


def _wrapper(target: Path, args: str = '"$@"', stderr: str = "") -> str:
    return (f"#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\n"
            f"exec {EVAL_PYTHON} -B {target} {args}{stderr}\n")


def write_wrappers(root: Path) -> dict[str, str]:
    """<root>/bin/bt and bin/bt-guard; returns {name: content} for the run meta."""
    bindir = Path(root) / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    content = {BT_WRAPPER: _wrapper(HO_DIR / "bt.py", stderr=" 2>/dev/null"),
               GUARD_WRAPPER: _wrapper(HO_DIR / "bt_guard.py", args="")}
    for name, text in content.items():
        path = bindir / name
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
        path.chmod(0o755)
    return content


def child_env(root: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The parent's environment without CLAUDE* variables, <root>/bin first on PATH and
    HOBT_STATE pointing bt at the root's state file."""
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE")}
    env["PATH"] = f"{Path(root) / 'bin'}:{base.get('PATH', '/usr/bin:/bin')}"
    env[STATE_ENV] = str(Path(root) / "state.json")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def claude_version() -> str:
    """`claude --version` (recorded in the executor meta)."""
    try:
        return subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"unknown ({type(err).__name__})"


def check_claude_version(found: str | None = None) -> str:
    """Refuse a CLI whose `claude --version` is not the pinned CLAUDE_VERSION."""
    found = claude_version() if found is None else found
    if found.split()[:1] != [CLAUDE_VERSION]:
        raise HoToolError(f"claude --version is {found!r}; pinned {CLAUDE_VERSION}")
    return found


def guard_settings() -> str:
    hook = {"type": "command", "command": GUARD_WRAPPER}
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}})


def build_argv(system_prompt: str, user_prompt: str, schema: Mapping[str, Any],
               budget_usd: float) -> list[str]:
    return [CLAUDE_BIN, "-p", user_prompt, "--model", MODEL, "--effort", EFFORT,
            "--thinking-display", THINKING_DISPLAY, "--system-prompt", system_prompt, "--tools", "Bash",
            "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS,
            "--permission-mode", "dontAsk", "--setting-sources", "local",
            "--settings", guard_settings(), "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "stream-json", "--verbose",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--max-budget-usd", f"{budget_usd:g}"]


def check_cwd(cwd: Path) -> Path:
    """The agent cwd must exist, be a directory outside the repo, and be empty."""
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise HoToolError(f"agent cwd {cwd} is not a directory")
    if under(cwd, REPO_ROOT) or under(REPO_ROOT, cwd):
        raise HoToolError(f"agent cwd {cwd} must be outside (and not above) the repo")
    if any(cwd.iterdir()):
        raise HoToolError(f"agent cwd {cwd} is not empty")
    return cwd


def memory_dir(cwd: Path, home: Path | None = None) -> Path:
    """Claude Code's auto-memory directory for a cwd (~/.claude/projects/<slug>/memory)."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd)))
    return (Path.home() if home is None else Path(home)) / ".claude" / "projects" / slug / "memory"


def check_memory_dir(cwd: Path, home: Path | None = None) -> Path:
    """Refuse a cwd whose auto-memory directory holds files (they would reach the agent)."""
    mem = memory_dir(cwd, home)
    if mem.is_dir() and any(mem.iterdir()):
        raise HoToolError(f"auto-memory {mem} is not empty; the agent would load it")
    return mem


def read_events(path: Path) -> list[dict[str, Any]]:
    """stream-json lines; a torn last line is dropped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def result_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for e in reversed(events):
        if e.get("type") == "result":
            return e
    return None


def usage_of(result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Tokens, cost, turns and tool calls of one run (from the result event, when present)."""
    calls = sum(1 for e in events if e.get("type") == "assistant"
                for c in e["message"].get("content", []) if c.get("type") == "tool_use")
    u = (result or {}).get("usage") or {}
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    out = {k: u.get(k) for k in keys}
    out.update({"thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                "total_cost_usd": (result or {}).get("total_cost_usd"),
                "num_turns": (result or {}).get("num_turns"),
                "duration_ms": (result or {}).get("duration_ms"), "tool_calls": calls})
    return out


def _failure(rc: int, result: Mapping[str, Any] | None) -> str | None:
    if result is None:
        return f"no result event (exit {rc})"
    if result.get("subtype") != "success" or result.get("is_error"):
        return f"result {result.get('subtype')!r} is_error={result.get('is_error')}"
    if not isinstance(result.get("structured_output"), dict):
        return "no structured output"
    return None


def launch(root: Path, run_id: str, system_prompt: str, user_prompt: str,
           schema: Mapping[str, Any], budget_usd: float, cwd: Path = AGENT_CWD,
           timeout_s: int = DEFAULT_TIMEOUT_S, extra_record: Mapping[str, Any] | None = None) -> RunResult:
    """Run one agent; transcript and prompts are saved before parsing. Never raises on an
    agent or CLI failure: RunResult.error says what went wrong (基礎設施失敗)."""
    root = Path(root)
    check_cwd(cwd)
    check_memory_dir(cwd)
    check_claude_version()
    tdir, pdir = root / "transcripts", root / "prompts"
    tdir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    transcript = tdir / f"{run_id}.jsonl"
    if transcript.exists():
        raise HoToolError(f"run id {run_id} already has a transcript")
    argv = build_argv(system_prompt, user_prompt, schema, budget_usd)
    shown = [a if a not in (system_prompt, user_prompt) else "<prompt>" for a in argv]
    (pdir / f"{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "system": system_prompt, "user": user_prompt, "argv": shown,
         "cwd": str(cwd), **(extra_record or {})}, ensure_ascii=False, indent=1), encoding="utf-8")
    start, rc, err = time.monotonic(), -1, None
    with open(transcript, "w", encoding="utf-8") as out, \
            open(tdir / f"{run_id}.stderr.log", "w", encoding="utf-8") as errf:
        try:
            rc = subprocess.run(argv, cwd=cwd, env=child_env(root), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=errf, text=True, timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            err = f"timeout after {timeout_s}s"
        except OSError as exc:
            err = f"cannot start {CLAUDE_BIN}: {exc}"
    seconds = round(time.monotonic() - start, 1)
    events = read_events(transcript)
    result = result_event(events)
    return RunResult(run_id, transcript, rc, seconds, result, err or _failure(rc, result),
                     usage_of(result, events))
