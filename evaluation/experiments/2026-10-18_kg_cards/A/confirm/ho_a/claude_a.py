"""Headless `claude -p` launches of the question writers and auditors (confirm_A.md §2.5, §8.3).

Fork of HO ho_tools/_ho_claude.py. Same blinding: cwd AGENT_CWD (/srv, empty, outside the repo),
--system-prompt replaces the default prompt, only Bash and only `bt ...` (--allowedTools, the other
built-ins disallowed, the bt-guard PreToolUse hook through --settings), --setting-sources local,
--strict-mcp-config, --disable-slash-commands, --no-session-persistence, the parent's CLAUDE*
variables removed, the auto-memory directory of the cwd must be empty, `bt` and `bt-guard` are
wrappers in <root>/bin (so no repo path reaches the agent).

Differences from HO:
* the CLI version and whether --thinking-display summarized is passed come from a CliPin. Real
  runs read it from <root>/cli_pin.json, which the main program writes (probe_cli.py pin) after
  the §8.3 probe; launch refuses to start without it, or when `claude --version` differs.
  probe_cli.py passes its CliPin explicitly.
* the bt wrapper runs ho_a/bt_a.py (v, grep, books) with this interpreter; no state file.
* the prompts record holds budget_usd (the --max-budget-usd cap), for the §8.2 ledger.
* agent_limit(): a result that ended on an agent limit (LIMIT_SUBTYPES, e.g. the --max-budget-usd cap,
  or total_cost_usd ≥ the cap) is the agent's outcome, not an infrastructure failure: runs_a does
  not rerun it and the job counts (confirm_A.md §2.4).
* model_fallback(): a run the CLI handed to another model (a `model_refusal_fallback` event, or
  modelUsage naming a model other than MODEL) was not answered by the registered writer model; it is
  an infrastructure failure (rerun, not counted; probe 2026-10-19, confirm_A.md §2.4).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import HO_A, PIN_FILE, REPO_ROOT, HoError, now, read_json, under

MODEL = "claude-opus-5-5"
EFFORT = "xhigh"
THINKING_DISPLAY = "summarized"
AGENT_CWD = Path("/srv")
CLAUDE_BIN = "claude"
ALLOWED_TOOLS = ("Bash(bt *)",)
DISALLOWED_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task",
                    "Agent", "NotebookEdit", "NotebookRead", "TodoWrite", "Skill", "ToolSearch", "KillShell",
                    "BashOutput")
BT_WRAPPER, GUARD_WRAPPER = "bt", "bt-guard"
DEFAULT_TIMEOUT_S = 3600
LIMIT_SUBTYPES = frozenset({"error_max_budget_usd", "error_max_turns", "error_max_structured_output_retries"})
COST_EPS = 1e-9


@dataclass(frozen=True)
class CliPin:
    """The CLI the runs are pinned to (§8.3): version string and whether --thinking-display is passed."""
    claude_version: str
    thinking_display: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    transcript: Path
    returncode: int
    seconds: float
    result: Mapping[str, Any] | None
    error: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    limit: str | None = None    # set by runs_a when the error is an agent limit (agent_limit)

    @property
    def output(self) -> Mapping[str, Any] | None:
        return None if self.result is None else self.result.get("structured_output")


def load_pin(root: Path) -> CliPin:
    """<root>/cli_pin.json written by the main program after the probe; refuse without it."""
    path = Path(root) / PIN_FILE
    if not path.is_file():
        raise HoError(f"{PIN_FILE} missing in the root: run probe_cli.py (§8.3) and write the pin first")
    doc = read_json(path)
    if not isinstance(doc.get("claude_version"), str) or not isinstance(doc.get("thinking_display"), bool):
        raise HoError(f"{PIN_FILE}: needs claude_version (str) and thinking_display (bool)")
    return CliPin(doc["claude_version"], doc["thinking_display"])


def write_pin(root: Path, pin: CliPin, **record: Any) -> Path:
    path = Path(root) / PIN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**pin.as_dict(), "written_utc": now(), **record}, ensure_ascii=False, indent=1)
                    + "\n", encoding="utf-8")
    return path


def _wrapper(target: Path, args: str = '"$@"', stderr: str = "") -> str:
    return f"#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\nexec {sys.executable} -B {target} {args}{stderr}\n"


def write_wrappers(root: Path) -> dict[str, str]:
    """<root>/bin/bt and bin/bt-guard; returns {name: content} for the run meta."""
    bindir = Path(root) / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    content = {BT_WRAPPER: _wrapper(HO_A / "bt_a.py", stderr=" 2>/dev/null"),
               GUARD_WRAPPER: _wrapper(HO_A / "bt_guard.py", args="")}
    for name, text in content.items():
        path = bindir / name
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
        path.chmod(0o755)
    return content


def child_env(root: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The parent's environment without CLAUDE* variables and with <root>/bin first on PATH."""
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE")}
    env["PATH"] = f"{Path(root) / 'bin'}:{base.get('PATH', '/usr/bin:/bin')}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def claude_version() -> str:
    try:
        return subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"unknown ({type(err).__name__})"


def check_claude_version(expected: str, found: str | None = None) -> str:
    found = claude_version() if found is None else found
    if found.split()[:1] != [expected]:
        raise HoError(f"claude --version is {found!r}; pinned {expected}")
    return found


def guard_settings() -> str:
    hook = {"type": "command", "command": GUARD_WRAPPER}
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}})


def build_argv(system_prompt: str, user_prompt: str, schema: Mapping[str, Any], budget_usd: float,
               thinking_display: bool) -> list[str]:
    thinking = ["--thinking-display", THINKING_DISPLAY] if thinking_display else []
    return [CLAUDE_BIN, "-p", user_prompt, "--model", MODEL, "--effort", EFFORT, *thinking,
            "--system-prompt", system_prompt, "--tools", "Bash", "--allowedTools", *ALLOWED_TOOLS,
            "--disallowedTools", *DISALLOWED_TOOLS, "--permission-mode", "dontAsk", "--setting-sources", "local",
            "--settings", guard_settings(), "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "stream-json", "--verbose",
            "--json-schema", json.dumps(schema, ensure_ascii=False), "--max-budget-usd", f"{budget_usd:g}"]


def check_cwd(cwd: Path) -> Path:
    """The agent cwd must exist, be a directory outside (and not above) the repo, and be empty."""
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise HoError(f"agent cwd {cwd} is not a directory")
    if under(cwd, REPO_ROOT) or under(REPO_ROOT, cwd):
        raise HoError(f"agent cwd {cwd} must be outside (and not above) the repo")
    if any(cwd.iterdir()):
        raise HoError(f"agent cwd {cwd} is not empty")
    return cwd


def memory_dir(cwd: Path, home: Path | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd)))
    return (Path.home() if home is None else Path(home)) / ".claude" / "projects" / slug / "memory"


def check_memory_dir(cwd: Path, home: Path | None = None) -> Path:
    mem = memory_dir(cwd, home)
    if mem.is_dir() and any(mem.iterdir()):
        raise HoError(f"auto-memory {mem} is not empty; the agent would load it")
    return mem


def read_events(path: Path) -> list[dict[str, Any]]:
    """stream-json lines; a torn line is dropped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def result_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def usage_of(result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    calls = sum(1 for e in events if e.get("type") == "assistant"
                for c in (e.get("message") or {}).get("content") or [] if isinstance(c, dict)
                and c.get("type") == "tool_use")
    u = (result or {}).get("usage") or {}
    out = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                 "output_tokens")}
    out.update({"total_cost_usd": (result or {}).get("total_cost_usd"), "num_turns": (result or {}).get("num_turns"),
                "duration_ms": (result or {}).get("duration_ms"), "tool_calls": calls})
    return out


def failure(rc: int, result: Mapping[str, Any] | None) -> str | None:
    if result is None:
        return f"no result event (exit {rc})"
    if result.get("subtype") != "success" or result.get("is_error"):
        return f"result {result.get('subtype')!r} is_error={result.get('is_error')}"
    if not isinstance(result.get("structured_output"), dict):
        return "no structured output"
    return None


def model_fallback(events: Sequence[Mapping[str, Any]], result: Mapping[str, Any] | None) -> str | None:
    """Why the run was not answered by MODEL alone (the CLI's refusal fallback); None when it was."""
    ev = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "model_refusal_fallback"), None)
    if ev is not None:
        return f"model fallback {ev.get('original_model')} → {ev.get('fallback_model')} ({ev.get('trigger')})"
    other = sorted(set(((result or {}).get("modelUsage") or {})) - {MODEL})
    return f"modelUsage names other models {other}" if other else None


def run_error(rc: int, result: Mapping[str, Any] | None, events: Sequence[Mapping[str, Any]]) -> str | None:
    return failure(rc, result) or model_fallback(events, result)


def agent_limit(result: Mapping[str, Any] | None, budget_usd: float) -> str | None:
    """Why a failed run ended on an agent limit (counted, never rerun); None for an infrastructure failure
    (no result event, timeout, CLI start failure, API error)."""
    if result is None:
        return None
    if result.get("subtype") in LIMIT_SUBTYPES:
        return str(result["subtype"])
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost >= budget_usd - COST_EPS:
        return f"total_cost_usd {cost:g} ≥ 上限 {budget_usd:g}"
    return None


def launch(root: Path, run_id: str, system_prompt: str, user_prompt: str, schema: Mapping[str, Any],
           budget_usd: float, pin: CliPin, cwd: Path = AGENT_CWD, timeout_s: int = DEFAULT_TIMEOUT_S,
           extra_record: Mapping[str, Any] | None = None) -> RunResult:
    """Run one agent; transcript and prompts are saved before parsing. Never raises on an agent or
    CLI failure (RunResult.error says what went wrong); raises HoError before starting when the
    cwd, memory directory or CLI version is wrong."""
    root = Path(root)
    check_cwd(cwd)
    check_memory_dir(cwd)
    check_claude_version(pin.claude_version)
    tdir, pdir = root / "transcripts", root / "prompts"
    tdir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    transcript = tdir / f"{run_id}.jsonl"
    if transcript.exists():
        raise HoError(f"run id {run_id} already has a transcript")
    argv = build_argv(system_prompt, user_prompt, schema, budget_usd, pin.thinking_display)
    shown = [a if a not in (system_prompt, user_prompt) else "<prompt>" for a in argv]
    (pdir / f"{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "system": system_prompt, "user": user_prompt, "argv": shown, "cwd": str(cwd),
         "budget_usd": budget_usd, "pin": pin.as_dict(), **(extra_record or {})}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    start, rc, err = time.monotonic(), -1, None
    with open(transcript, "w", encoding="utf-8") as out, \
            open(tdir / f"{run_id}.stderr.log", "w", encoding="utf-8") as errf:
        try:
            rc = subprocess.run(argv, cwd=cwd, env=child_env(root), stdin=subprocess.DEVNULL, stdout=out,
                                stderr=errf, text=True, timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            err = f"timeout after {timeout_s}s"
        except OSError as exc:
            err = f"cannot start {CLAUDE_BIN}: {exc}"
    seconds = round(time.monotonic() - start, 1)
    events = read_events(transcript)
    result = result_event(events)
    return RunResult(run_id, transcript, rc, seconds, result, err or run_error(rc, result, events),
                     usage_of(result, events))
