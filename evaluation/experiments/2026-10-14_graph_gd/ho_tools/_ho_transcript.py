"""§7 transcript rules of the mechanical audit (private part of mech_check.py).

A run is its stream-json transcript plus the rendered prompts (prompts/<run_id>.json).
"Visible" text is what the agent read or wrote as far as the transcript holds it: the
rendered system and user prompts, its text, the API-side thinking summaries
(--thinking-display summarized; not the raw thinking), tool inputs, tool results and the
final result. Claude Code's own injected context (environment block, account) is not in
the transcript, so no rule can see it. Rules:

* t_init        the init event exists, cwd is AGENT_CWD (outside the repo), the model is
                MODEL, tools ⊆ {Bash, StructuredOutput}, no MCP server, permission mode dontAsk
* t_tool        every tool call is StructuredOutput or one plain `bt ...` (bt_guard rule);
                a refused attempt is only a warning (t_tool_denied: it ran nothing)
* t_path        no absolute path (or ~/...) other than the store layers/ in any visible
                text but the prompts, and no relative path (./ ../ a/b) in a Bash command
                line or a tool result (bt prints none: verse text, passage titles and the
                question banks hold no '/')
* t_memory      no banned.MEMORY_MARKERS in visible text (project memory, CLAUDE.md, paths)
* t_banned      no banned.BANNED_TERMS in the system prompt (checked at load too)
* t_banned_agent (warn) BANNED_TERMS in agent-written text: the agent's own words, tool
                inputs and results, and the user prompt's values (another agent's question
                JSON or audit issues). §7 bans the words in the prompts, not in what agents
                write ("用 grep 檢索平行經文"), so these are listed for a human, not blocking.
* t_result      the run ended with a successful result event

BLINDING_RULES are the error rules a draft cannot survive: a run with one of them drops
its question at commit time (_ho_runs), so freeze never meets them on a selected one.
conflict_passages() reads, for 附錄 B, the passages `bt old --gold` reported as 衝突.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from _ho_common import REPO_ROOT, Violation, gd, under  # first: sets sys.path

import banned  # noqa: E402
import bt_guard  # noqa: E402
from _ho_claude import AGENT_CWD, MODEL, read_events  # noqa: E402

__all__ = ["TOOLS_OK", "BLINDING_RULES", "visible_texts", "check_events", "check_run", "run_paths",
           "blinding_errors", "conflict_passages", "run_conflicts"]

TOOLS_OK = frozenset({"Bash", "StructuredOutput"})
BLINDING_RULES = frozenset({"t_init", "t_tool", "t_path", "t_memory", "t_banned"})
_STOP = "\\s'\"`<>|;,，。"
_ABS_PATH = re.compile(r"(?<![\w.~-])(?:~[A-Za-z0-9_-]*(?=/)|/(?:home|mnt|tmp|srv|etc|usr|root|var|opt|"
                       r"proc|run|dev|sys|bin|lib|media|snap)(?![\w.-]))(?:/[^" + _STOP + r"]*)?")
_REL_PATH = re.compile(r"(?<![\w./~-])(?:\.{1,2}/|[A-Za-z0-9_.*?-]*[A-Za-z_.*?][A-Za-z0-9_.*?-]*/)"
                       r"[^" + _STOP + r"]*")            # ./x, ../x, a/b (not 1/2)
_CONFLICT = re.compile(r"→ (ps:\S+) 衝突：")


def run_paths(root: Path, run_id: str) -> tuple[Path, Path]:
    return Path(root) / "transcripts" / f"{run_id}.jsonl", Path(root) / "prompts" / f"{run_id}.json"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def visible_texts(events: Sequence[Mapping[str, Any]],
                  prompts: Mapping[str, Any] | None = None) -> Iterator[tuple[str, str]]:
    """(where, text) of everything the agent read or wrote."""
    for key in ("system", "user"):
        if prompts and isinstance(prompts.get(key), str):
            yield f"prompt:{key}", prompts[key]
    for n, e in enumerate(events):
        kind = e.get("type")
        if kind in ("assistant", "user"):
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else [{"type": "text", "text": content}]:
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
                yield f"event {n} result:structured_output", json.dumps(
                    e["structured_output"], ensure_ascii=False)


def _init_violations(events: Sequence[Mapping[str, Any]], cwd: Path, model: str) -> list[Violation]:
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


def _tool_violations(events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    results = {c.get("tool_use_id"): c for e in events if e.get("type") == "user"
               for c in ((e.get("message") or {}).get("content") or [])
               if isinstance(c, dict) and c.get("type") == "tool_result"}
    out = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name, inp = c.get("name"), c.get("input") or {}
            reason = (None if name == "StructuredOutput" else
                      bt_guard.check_command(inp.get("command")) if name == "Bash" else
                      f"tool {name!r}")
            if reason is None:
                continue
            res = results.get(c.get("id")) or {}
            denied = res.get("is_error") and "denied" in _content_text(res.get("content")).lower()
            detail = f"{name} {json.dumps(inp, ensure_ascii=False)[:160]}: {reason}"
            out.append(Violation("t_tool_denied", detail, "warn") if denied
                       else Violation("t_tool", detail))
    return out


def _tool_io(events: Sequence[Mapping[str, Any]]) -> Iterator[tuple[str, str]]:
    """(where, text) of every Bash command line and every tool result (not the agent's
    free-text tool descriptions)."""
    for n, e in enumerate(events):
        if e.get("type") not in ("assistant", "user"):
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name") == "Bash":
                yield f"event {n} command", str((c.get("input") or {}).get("command", ""))
            elif c.get("type") == "tool_result":
                yield f"event {n} tool_result", _content_text(c.get("content"))


def _path_violations(texts: Sequence[tuple[str, str]],
                     events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    layers = str(gd.LAYERS_ROOT)
    found = [(where, m.group(0)) for where, text in texts if not where.startswith("prompt:")
             for m in _ABS_PATH.finditer(text) if not m.group(0).startswith(layers)]
    found += [(where, m.group(0)) for where, text in _tool_io(events) for m in _REL_PATH.finditer(text)]
    return [Violation("t_path", f"{where}: {path[:120]}") for where, path in found]


def _word_violations(where: str, text: str) -> list[Violation]:
    """t_memory everywhere; banned terms are t_banned in the system prompt, else a warning."""
    out = [Violation("t_memory", f"{where}: {h.term!r} in …{h.excerpt}…")
           for h in banned.find_terms(text, banned.MEMORY_MARKERS)]
    rule, level = ("t_banned", "error") if where == "prompt:system" else ("t_banned_agent", "warn")
    out += [Violation(rule, f"{where}: {h.term!r} in …{h.excerpt}…", level)
            for h in banned.find_terms(text, banned.BANNED_TERMS)]
    return out


def check_events(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None = None,
                 cwd: Path = AGENT_CWD, model: str = MODEL) -> list[Violation]:
    """Every §7 transcript rule on one run's events (and its rendered prompts)."""
    texts = list(visible_texts(events, prompts))
    out = _init_violations(events, cwd, model) + _tool_violations(events) + _path_violations(texts, events)
    for where, text in texts:
        out += _word_violations(where, text)
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
    """Error-level BLINDING_RULES violations of these runs (not t_result: whether a run
    finished is the executor's business, a failed one was rerun)."""
    out = []
    for run in run_ids:
        out += [Violation(v.rule, f"{run}: {v.detail}") for v in check_run(root, run)
                if v.level == "error" and v.rule in BLINDING_RULES]
    return out


def conflict_passages(events: Sequence[Mapping[str, Any]]) -> set[str]:
    """Passages a `bt old --gold` call of this run reported as 衝突 (already used as gold)."""
    calls = {c.get("id") for e in events if e.get("type") == "assistant"
             for c in (e.get("message") or {}).get("content") or []
             if isinstance(c, dict) and c.get("type") == "tool_use"
             and " --gold" in str((c.get("input") or {}).get("command", ""))}
    out: set[str] = set()
    for e in events:
        for c in (e.get("message") or {}).get("content") or [] if e.get("type") == "user" else []:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                out |= set(_CONFLICT.findall(_content_text(c.get("content"))))
    return out


def run_conflicts(root: Path, run_id: str) -> set[str]:
    """conflict_passages of one run's transcript (none when it is missing)."""
    transcript, _ = run_paths(root, run_id)
    return conflict_passages(read_events(transcript)) if transcript.is_file() else set()
