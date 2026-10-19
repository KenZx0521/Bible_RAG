"""Headless `claude -p` launches of the writers and the labeller (qset.md §3, §8).

Taken from experiment A's ho_a/claude_a.py (copied in small parts, the original untouched). Same
blinding: cwd AGENT_CWD (/srv, empty, outside the repo), --system-prompt replaces the default prompt,
--setting-sources local, --strict-mcp-config, --disable-slash-commands, --no-session-persistence, the
parent's CLAUDE* variables removed, the cwd's auto-memory directory must be empty. Differences:

* tools: writers need none. tools_mode "none" passes `--tools ""` (StructuredOutput from --json-schema
  is all that is left, if the probe confirms it); "bash_guard" is the fallback, `--tools Bash` behind
  the bt-guard hook with no bt wrapper on PATH (a bt call can only fail). The bt-guard hook is
  passed through --settings in both modes, as insurance; bt_guard.py is a verbatim copy of HO's
  (sha pinned in q_common).
* model: per job (writer opus or the second writer), the full id from cli_pin.json (the probe
  records what an alias resolved to); the model check and the fallback check use that id.
* CLI version: the pinned executable ~/.local/share/claude/versions/<version> (sha checked) is
  linked as <root>/clibin/claude, first on PATH for the version check and the launch, so a CLI
  self-update in between changes nothing. DISABLE_AUTOUPDATER=1 in the child.
* model_fallback(): a `model_refusal_fallback` event, or modelUsage naming another model, means the
  run was not answered by the job's model: an infrastructure failure (rerun, output unused).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from q_common import (BT_GUARD_HO_SHA256, CLI_SHA256, CLI_VERSIONS_DIR, HERE, PIN_FILE, REPO, QError, now,
                      read_json, sha256_file, under, write_json)

AGENT_CWD = Path("/srv")
CLAUDE_BIN = "claude"
THINKING_DISPLAY = "summarized"
TOOLS_MODES = ("none", "bash_guard")
DISALLOWED_TOOLS = ("Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task",
                    "Agent", "NotebookEdit", "NotebookRead", "TodoWrite", "Skill", "ToolSearch", "KillShell",
                    "BashOutput")
GUARD_WRAPPER = "bt-guard"
DEFAULT_TIMEOUT_S = 1800
LIMIT_SUBTYPES = frozenset({"error_max_budget_usd", "error_max_turns", "error_max_structured_output_retries"})
COST_EPS = 1e-9
_SETUP_LOCK = threading.Lock()      # parallel launches share <root>/clibin and <root>/bin


@dataclass(frozen=True)
class CliPin:
    """What the runs are pinned to: CLI version, thinking display, tools mode, model ids by writer key."""
    claude_version: str
    thinking_display: bool
    tools_mode: str
    models: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "models": dict(self.models)}

    def model(self, key: str) -> str:
        if key not in self.models:
            raise QError(f"no pinned model id for {key!r} (cli_pin.json models {sorted(self.models)})")
        return self.models[key]


@dataclass(frozen=True)
class RunResult:
    run_id: str
    transcript: Path
    returncode: int
    seconds: float
    result: Mapping[str, Any] | None
    error: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    limit: str | None = None

    @property
    def output(self) -> Mapping[str, Any] | None:
        return None if self.result is None else self.result.get("structured_output")


def load_pin(root: Path) -> CliPin:
    path = Path(root) / PIN_FILE
    if not path.is_file():
        raise QError(f"{PIN_FILE} missing in {root}: run the probe and `run_q.py pin` first")
    d = read_json(path)
    if d.get("tools_mode") not in TOOLS_MODES or not isinstance(d.get("models"), dict):
        raise QError(f"{PIN_FILE}: needs tools_mode in {TOOLS_MODES} and a models map")
    return CliPin(d["claude_version"], bool(d["thinking_display"]), d["tools_mode"], dict(d["models"]))


def write_pin(root: Path, pin: CliPin, **record: Any) -> Path:
    return write_json(Path(root) / PIN_FILE, {**pin.as_dict(), "written_utc": now(), **record}, root)


def check_guard_copy() -> None:
    got = sha256_file(HERE / "bt_guard.py")
    if got != BT_GUARD_HO_SHA256:
        raise QError(f"bt_guard.py sha256 {got[:12]} is not the HO copy {BT_GUARD_HO_SHA256[:12]}")


def pin_cli(root: Path, version: str) -> Path:
    """<root>/clibin/claude → the pinned CLI executable (sha checked); returns the directory."""
    exe = CLI_VERSIONS_DIR / version
    want = CLI_SHA256.get(version)
    if want is None or not exe.is_file() or sha256_file(exe) != want:
        raise QError(f"CLI {version}: {exe} missing or not the pinned sha {str(want)[:12]}")
    bindir = Path(root) / "clibin"
    with _SETUP_LOCK:
        bindir.mkdir(parents=True, exist_ok=True)
        link = bindir / CLAUDE_BIN
        if link.is_symlink() and Path(os.readlink(link)) != exe:
            link.unlink()
        if not link.is_symlink():
            link.symlink_to(exe)
    return bindir


def write_guard(root: Path) -> str:
    """<root>/bin/bt-guard (the hook wrapper); no bt wrapper is ever written."""
    check_guard_copy()
    bindir = Path(root) / "bin"
    text = f"#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\nexec {sys.executable} -B {HERE / 'bt_guard.py'}\n"
    path = bindir / GUARD_WRAPPER
    with _SETUP_LOCK:
        bindir.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
        path.chmod(0o755)
    return text


def child_env(root: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parent env without CLAUDE* variables; <root>/clibin then <root>/bin first on PATH."""
    base = os.environ if base is None else base
    env = {k: v for k, v in base.items() if not k.upper().startswith("CLAUDE")}
    env["PATH"] = f"{Path(root) / 'clibin'}:{Path(root) / 'bin'}:{base.get('PATH', '/usr/bin:/bin')}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


def claude_version(root: Path) -> str:
    try:
        return subprocess.run([CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, env=child_env(root)).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"unknown ({type(err).__name__})"


def check_claude_version(root: Path, expected: str) -> str:
    found = claude_version(root)
    if found.split()[:1] != [expected]:
        raise QError(f"claude --version is {found!r}; pinned {expected}")
    return found


def guard_settings() -> str:
    hook = {"type": "command", "command": GUARD_WRAPPER}
    return json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}})


def build_argv(system_prompt: str, user_prompt: str, schema: Mapping[str, Any], budget_usd: float, model: str,
               effort: str, thinking_display: bool, tools_mode: str) -> list[str]:
    if tools_mode not in TOOLS_MODES:
        raise QError(f"tools_mode {tools_mode!r}")
    thinking = ["--thinking-display", THINKING_DISPLAY] if thinking_display else []
    tools = ["--tools", ""] if tools_mode == "none" else ["--tools", "Bash", "--allowedTools", "Bash(bt *)"]
    return [CLAUDE_BIN, "-p", user_prompt, "--model", model, "--effort", effort, *thinking,
            "--system-prompt", system_prompt, *tools, "--disallowedTools", *DISALLOWED_TOOLS,
            "--permission-mode", "dontAsk", "--setting-sources", "local", "--settings", guard_settings(),
            "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--max-budget-usd", f"{budget_usd:g}"]


def check_cwd(cwd: Path) -> Path:
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise QError(f"agent cwd {cwd} is not a directory")
    if under(cwd, REPO) or under(REPO, cwd):
        raise QError(f"agent cwd {cwd} must be outside (and not above) the repo")
    if any(cwd.iterdir()):
        raise QError(f"agent cwd {cwd} is not empty")
    return cwd


def memory_dir(cwd: Path, home: Path | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd)))
    return (Path.home() if home is None else Path(home)) / ".claude" / "projects" / slug / "memory"


def check_memory_dir(cwd: Path, home: Path | None = None) -> Path:
    mem = memory_dir(cwd, home)
    if mem.is_dir() and any(mem.iterdir()):
        raise QError(f"auto-memory {mem} is not empty; the agent would load it")
    return mem


def read_events(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def result_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((e for e in reversed(events) if e.get("type") == "result"), None)


def init_event(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)


def usage_of(result: Mapping[str, Any] | None) -> dict[str, Any]:
    u = (result or {}).get("usage") or {}
    out = {k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                                 "output_tokens")}
    out.update({"thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
                "total_cost_usd": (result or {}).get("total_cost_usd"), "num_turns": (result or {}).get("num_turns"),
                "duration_ms": (result or {}).get("duration_ms"),
                "models": sorted(((result or {}).get("modelUsage") or {}))})
    return out


def failure(rc: int, result: Mapping[str, Any] | None) -> str | None:
    if result is None:
        return f"no result event (exit {rc})"
    if result.get("subtype") != "success" or result.get("is_error"):
        return f"result {result.get('subtype')!r} is_error={result.get('is_error')}"
    if not isinstance(result.get("structured_output"), dict):
        return "no structured output"
    return None


def model_fallback(events: Sequence[Mapping[str, Any]], result: Mapping[str, Any] | None, model: str) -> str | None:
    """Why the run was not answered by ``model`` alone; None when it was."""
    ev = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "model_refusal_fallback"), None)
    if ev is not None:
        return f"model fallback {ev.get('original_model')} → {ev.get('fallback_model')} ({ev.get('trigger')})"
    other = sorted(set(((result or {}).get("modelUsage") or {})) - {model})
    return f"modelUsage names other models {other}" if other else None


def agent_limit(result: Mapping[str, Any] | None, budget_usd: float) -> str | None:
    """A failed run that ended on an agent limit (counted, never rerun); None for an infrastructure failure."""
    if result is None:
        return None
    if result.get("subtype") in LIMIT_SUBTYPES:
        return str(result["subtype"])
    cost = result.get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost >= budget_usd - COST_EPS:
        return f"total_cost_usd {cost:g} ≥ cap {budget_usd:g}"
    return None


def launch(root: Path, run_id: str, system_prompt: str, user_prompt: str, schema: Mapping[str, Any],
           budget_usd: float, model: str, effort: str, pin: CliPin, cwd: Path = AGENT_CWD,
           timeout_s: int = DEFAULT_TIMEOUT_S, extra_record: Mapping[str, Any] | None = None,
           check_model: bool = True) -> RunResult:
    """Run one agent under <root> (transcripts/, prompts/); the prompts record is saved before the launch.
    Never raises on an agent or CLI failure (RunResult.error); raises QError before starting when the cwd,
    the memory directory, the guard copy or the CLI version is wrong. ``check_model`` False (a probe of
    an alias) skips the fallback check against ``model``: the probe records modelUsage instead."""
    root = Path(root)
    check_cwd(cwd)
    check_memory_dir(cwd)
    write_guard(root)
    pin_cli(root, pin.claude_version)
    check_claude_version(root, pin.claude_version)
    tdir, pdir = root / "transcripts", root / "prompts"
    tdir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    transcript = tdir / f"{run_id}.jsonl"
    if transcript.exists():
        raise QError(f"run id {run_id} already has a transcript")
    argv = build_argv(system_prompt, user_prompt, schema, budget_usd, model, effort, pin.thinking_display,
                      pin.tools_mode)
    shown = [a if a not in (system_prompt, user_prompt) else "<prompt>" for a in argv]
    write_json(pdir / f"{run_id}.json",
               {"run_id": run_id, "system": system_prompt, "user": user_prompt, "argv": shown, "cwd": str(cwd),
                "budget_usd": budget_usd, "model": model, "effort": effort, "pin": pin.as_dict(),
                "utc": now(), **(extra_record or {})}, root)
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
    error = err or failure(rc, result) or (model_fallback(events, result, model) if check_model else None)
    return RunResult(run_id, transcript, rc, seconds, result, error, usage_of(result))
