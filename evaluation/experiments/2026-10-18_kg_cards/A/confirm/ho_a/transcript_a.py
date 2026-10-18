"""Transcript rules of the question-writing runs (confirm_A.md §2.5, §2.9): HO _ho_transcript.py with banned_a.

A run is its stream-json transcript plus the rendered prompts (prompts/<run_id>.json). "Visible" text
is what the agent read or wrote as far as the transcript holds it: system and user prompts, its
text, API-side thinking summaries, tool inputs and results, the final result. Rules (HO, unchanged
except the word lists and that no absolute path at all is allowed outside the prompts, because
bt_a prints none):

* t_init         init event exists; cwd AGENT_CWD (outside the repo); model MODEL; tools ⊆ {Bash,
                 StructuredOutput}; no MCP server; permission mode dontAsk
* t_tool         every tool call is StructuredOutput or one plain `bt ...` (bt_guard rule); a refused
                 attempt is only a warning (t_tool_denied: it ran nothing)
* t_path         no absolute path (or ~/...) in visible text but the prompts, and no relative path
                 (./ ../ a/b) in a Bash command line or a tool result
* t_memory       no banned_a.MEMORY_MARKERS in visible text
* t_banned       no banned_a.BANNED_TERMS in the system prompt
* t_banned_agent (warn) BANNED_TERMS in agent-written text and the user prompt's values
* t_result       the run ended with a successful result event

BLINDING_RULES are the error rules a draft cannot survive: a run with one of them drops its draft at
commit (runs_a), so freeze never meets them on a passed question.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from hoa_common import REPO_ROOT, Violation, under  # first: sets sys.path

import banned_a  # noqa: E402
import bt_guard  # noqa: E402
from claude_a import AGENT_CWD, MODEL, read_events  # noqa: E402

TOOLS_OK = frozenset({"Bash", "StructuredOutput"})
BLINDING_RULES = frozenset({"t_init", "t_tool", "t_path", "t_memory", "t_banned"})
_STOP = "\\s'\"`<>|;,，。"
_ABS_PATH = re.compile(r"(?<![\w.~-])(?:~[A-Za-z0-9_-]*(?=/)|/(?:home|mnt|tmp|srv|etc|usr|root|var|opt|"
                       r"proc|run|dev|sys|bin|lib|media|snap)(?![\w.-]))(?:/[^" + _STOP + r"]*)?")
_REL_PATH = re.compile(r"(?<![\w./~-])(?:\.{1,2}/|[A-Za-z0-9_.*?-]*[A-Za-z_.*?][A-Za-z0-9_.*?-]*/)"
                       r"[^" + _STOP + r"]*")


def run_paths(root: Path, run_id: str) -> tuple[Path, Path]:
    return Path(root) / "transcripts" / f"{run_id}.jsonl", Path(root) / "prompts" / f"{run_id}.json"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def _blocks(e: Mapping[str, Any]) -> list:
    content = (e.get("message") or {}).get("content")
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def visible_texts(events: Sequence[Mapping[str, Any]],
                  prompts: Mapping[str, Any] | None = None) -> Iterator[tuple[str, str]]:
    """(where, text) of everything the agent read or wrote."""
    for key in ("system", "user"):
        if prompts and isinstance(prompts.get(key), str):
            yield f"prompt:{key}", prompts[key]
    for n, e in enumerate(events):
        kind = e.get("type")
        if kind in ("assistant", "user"):
            for c in _blocks(e):
                t = c.get("type") if isinstance(c, dict) else None
                where = f"event {n} {kind}:{t}"
                if t == "text":
                    yield where, c.get("text") or ""
                elif t == "thinking":
                    yield where, c.get("thinking") or ""
                elif t == "tool_use":
                    yield where, json.dumps(c.get("input"), ensure_ascii=False)
                elif t == "tool_result":
                    yield where, _content_text(c.get("content"))
        elif kind == "result":
            yield f"event {n} result", e.get("result") or ""
            if e.get("structured_output") is not None:
                yield f"event {n} result:structured_output", json.dumps(e["structured_output"], ensure_ascii=False)


def init_violations(events: Sequence[Mapping[str, Any]], cwd: Path = AGENT_CWD, model: str = MODEL) -> list[Violation]:
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if init is None:
        return [Violation("t_init", "no init event")]
    bad = []
    got_cwd = Path(str(init.get("cwd")))
    if got_cwd != Path(cwd) or under(got_cwd, REPO_ROOT):
        bad.append(f"cwd {got_cwd} (expected {cwd}, outside the repo)")
    if init.get("model") != model:
        bad.append(f"model {init.get('model')!r}")
    if not set(init.get("tools") or ()) <= TOOLS_OK:
        bad.append(f"tools {sorted(set(init.get('tools') or ()) - TOOLS_OK)}")
    if init.get("mcp_servers"):
        bad.append(f"mcp servers {init.get('mcp_servers')}")
    if init.get("permissionMode") != "dontAsk":
        bad.append(f"permission mode {init.get('permissionMode')!r}")
    return [Violation("t_init", b) for b in bad]


def tool_results(events: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {c.get("tool_use_id"): c for e in events if e.get("type") == "user"
            for c in _blocks(e) if isinstance(c, dict) and c.get("type") == "tool_result"}


def tool_calls(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [c for e in events if e.get("type") == "assistant" for c in _blocks(e)
            if isinstance(c, dict) and c.get("type") == "tool_use"]


def is_denied(result: Mapping[str, Any] | None) -> bool:
    res = result or {}
    return bool(res.get("is_error")) and "denied" in _content_text(res.get("content")).lower()


def _tool_violations(events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    results, out = tool_results(events), []
    for c in tool_calls(events):
        name, inp = c.get("name"), c.get("input") or {}
        reason = (None if name == "StructuredOutput" else
                  bt_guard.check_command(inp.get("command")) if name == "Bash" else f"tool {name!r}")
        if reason is None:
            continue
        detail = f"{name} {json.dumps(inp, ensure_ascii=False)[:160]}: {reason}"
        out.append(Violation("t_tool_denied", detail, "warn") if is_denied(results.get(c.get("id")))
                   else Violation("t_tool", detail))
    return out


def _tool_io(events: Sequence[Mapping[str, Any]]) -> Iterator[tuple[str, str]]:
    """(where, text) of every Bash command line and every tool result."""
    for n, e in enumerate(events):
        if e.get("type") not in ("assistant", "user"):
            continue
        for c in _blocks(e):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") == "Bash":
                yield f"event {n} command", str((c.get("input") or {}).get("command", ""))
            elif c.get("type") == "tool_result":
                yield f"event {n} tool_result", _content_text(c.get("content"))


def _path_violations(texts: Sequence[tuple[str, str]], events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    found = [(where, m.group(0)) for where, text in texts if not where.startswith("prompt:")
             for m in _ABS_PATH.finditer(text)]
    found += [(where, m.group(0)) for where, text in _tool_io(events) for m in _REL_PATH.finditer(text)]
    return [Violation("t_path", f"{where}: {path[:120]}") for where, path in found]


def word_violations(where: str, text: str) -> list[Violation]:
    """t_memory everywhere; banned terms are t_banned in the system prompt, else a warning."""
    out = [Violation("t_memory", f"{where}: {h.term!r} in …{h.excerpt}…")
           for h in banned_a.find_terms(text, banned_a.MEMORY_MARKERS)]
    rule, level = ("t_banned", "error") if where == "prompt:system" else ("t_banned_agent", "warn")
    out += [Violation(rule, f"{where}: {h.term!r} in …{h.excerpt}…", level)
            for h in banned_a.find_terms(text, banned_a.BANNED_TERMS)]
    return out


def check_events(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None = None,
                 cwd: Path = AGENT_CWD, model: str = MODEL) -> list[Violation]:
    """Every transcript rule on one run's events (and its rendered prompts)."""
    texts = list(visible_texts(events, prompts))
    out = init_violations(events, cwd, model) + _tool_violations(events) + _path_violations(texts, events)
    for where, text in texts:
        out += word_violations(where, text)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None or result.get("subtype") != "success" or result.get("is_error"):
        out.append(Violation("t_result", "no successful result event"))
    return out


def check_run(root: Path, run_id: str, cwd: Path = AGENT_CWD) -> list[Violation]:
    transcript, prompts = run_paths(root, run_id)
    if not transcript.is_file():
        return [Violation("t_result", f"transcript {transcript.name} is missing")]
    doc = json.loads(prompts.read_text(encoding="utf-8")) if prompts.is_file() else None
    out = check_events(read_events(transcript), doc, cwd)
    if doc is None:
        out.append(Violation("t_init", f"prompts/{run_id}.json is missing"))
    return out


def blinding_errors(root: Path, run_ids: Sequence[str]) -> list[Violation]:
    """Error-level BLINDING_RULES violations of these runs (t_result is the executor's business)."""
    out = []
    for run in run_ids:
        out += [Violation(v.rule, f"{run}: {v.detail}") for v in check_run(root, run)
                if v.level == "error" and v.rule in BLINDING_RULES]
    return out


def thinking_chars(events: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """(thinking blocks, characters of their summaries) of one run (probe_cli check 3)."""
    blocks = [c for e in events if e.get("type") == "assistant" for c in _blocks(e)
              if isinstance(c, dict) and c.get("type") == "thinking"]
    return len(blocks), sum(len(c.get("thinking") or "") for c in blocks)
