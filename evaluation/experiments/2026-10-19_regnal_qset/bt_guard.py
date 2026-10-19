"""PreToolUse hook of the HO agents (prereg §7 盲化): only `bt ...` may run, nothing else.

`--allowedTools "Bash(bt *)"` alone does not confine the agent: Claude Code auto-allows
read-only commands (ls, cat, pwd, `bt x; ls`, ...) even in dontAsk mode (probe 2026-10-14,
ho/probe/transcripts/probe_b.jsonl). run_gen.py / run_audit.py therefore also pass this hook
through `--settings`; it reads the hook JSON on stdin and

* lets StructuredOutput through (the agent's final answer),
* lets Bash through only for one simple command `bt <args>`: no unquoted ; & | < > ( ) or
  newline, no $ or backtick outside single quotes, no unquoted glob or tilde character
  (* ? [ ] { } ~: the shell would expand them to file names, and bt prints unknown keys
  back, so `bt v ../*` would work as ls), first word exactly `bt`,
* denies everything else with exit code 2 and a one-line reason (fed back to the agent).

Pure stdlib: it runs once per tool call.
"""
from __future__ import annotations

import json
import shlex
import sys
from typing import Any, Mapping

BT_COMMAND = "bt"
ANSWER_TOOL = "StructuredOutput"
DENY_EXIT = 2
_CONTROL = set(";&|<>()\n\r")
_EXPANSION = set("$`")
_GLOB = set("*?[]{}~")                 # file-name expansion outside quotes


def _unsafe_char(command: str) -> str | None:
    """First character that would make `command` more than one plain simple command."""
    single = double = escaped = False
    for ch in command:
        if escaped:
            escaped = False
            continue
        if single:
            single = ch != "'"
            continue
        if ch == "\\":
            escaped = True
        elif ch == "'" and not double:
            single = True
        elif ch == '"':
            double = not double
        elif ch in _EXPANSION:
            return ch
        elif ch in _CONTROL and not double:
            return ch
        elif ch in _GLOB and not double:
            return ch
    return "unterminated quote" if single or double or escaped else None


def check_command(command: Any) -> str | None:
    """None when `command` is one `bt ...` call, else the reason it is refused."""
    if not isinstance(command, str) or not command.strip():
        return "empty command"
    bad = _unsafe_char(command)
    if bad in _GLOB:
        return f"put regular expressions and other arguments with {bad!r} in single quotes"
    if bad is not None:
        return f"only one plain `{BT_COMMAND} ...` call is allowed (found {bad!r})"
    try:
        words = shlex.split(command)
    except ValueError as err:
        return f"cannot parse the command: {err}"
    if not words or words[0] != BT_COMMAND:
        return f"only `{BT_COMMAND}` may run"
    return None


def decide(event: Mapping[str, Any]) -> str | None:
    """None to let the tool call through, else the deny reason."""
    tool = event.get("tool_name")
    if tool == ANSWER_TOOL:
        return None
    if tool != "Bash":
        return f"tool {tool!r} is not available; use `{BT_COMMAND} ...`"
    return check_command((event.get("tool_input") or {}).get("command"))


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        event = {}
    reason = decide(event if isinstance(event, dict) else {})
    if reason is None:
        return 0
    print(f"denied: {reason}", file=sys.stderr)
    return DENY_EXIT


if __name__ == "__main__":
    sys.exit(main())
