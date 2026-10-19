"""Transcript rules of the writer and labeller runs (qset.md §3), from A's transcript_a.py.

Visible text is what the agent read or wrote as far as the transcript holds it: the rendered prompts,
its text, thinking summaries, tool inputs and results, the final result. Rules:

* t_init    init event; cwd AGENT_CWD; model = the job's model; tools ⊆ {StructuredOutput} (tools_mode
            none) or ⊆ {Bash, StructuredOutput} (bash_guard); no MCP server; permission mode dontAsk
* t_tool    every tool call is StructuredOutput (a refused call is only t_tool_denied, a warning)
* t_memory  no banned_q.MEMORY_MARKERS anywhere visible, the agent's own output included
* t_banned  the banned check (CUES, cue literals, prompt terms) on the system prompt, and on the user
            prompt of a writer run; a labeller's user prompt holds the writers' questions, cue words
            allowed, so only its memory markers count
* t_result  a successful result event

Cue words in an agent's output are not checked at all: writers may phrase freely (qset.md §3).
BLINDING_RULES void the run's output.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import banned_q
from claude_q import AGENT_CWD, init_event, read_events
from q_common import REPO, Violation, under

BLINDING_RULES = frozenset({"t_init", "t_tool", "t_memory", "t_banned"})
TOOLS_OK = {"none": frozenset({"StructuredOutput"}), "bash_guard": frozenset({"Bash", "StructuredOutput"})}


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


def init_violations(events: Sequence[Mapping[str, Any]], model: str | None, tools_mode: str,
                    cwd: Path = AGENT_CWD) -> list[Violation]:
    """``model`` None (a probe of an alias) skips the model comparison."""
    init = init_event(events)
    if init is None:
        return [Violation("t_init", "no init event")]
    bad = []
    got = Path(str(init.get("cwd")))
    if got != Path(cwd) or under(got, REPO):
        bad.append(f"cwd {got} (expected {cwd})")
    if model is not None and init.get("model") != model:
        bad.append(f"model {init.get('model')!r} (expected {model})")
    extra = set(init.get("tools") or ()) - TOOLS_OK[tools_mode]
    if extra:
        bad.append(f"tools {sorted(extra)}")
    if init.get("mcp_servers"):
        bad.append(f"mcp servers {init.get('mcp_servers')}")
    if init.get("permissionMode") != "dontAsk":
        bad.append(f"permission mode {init.get('permissionMode')!r}")
    return [Violation("t_init", b) for b in bad]


def tool_calls(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [c for e in events if e.get("type") == "assistant" for c in _blocks(e)
            if isinstance(c, dict) and c.get("type") == "tool_use"]


def tool_results(events: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {c.get("tool_use_id"): c for e in events if e.get("type") == "user"
            for c in _blocks(e) if isinstance(c, dict) and c.get("type") == "tool_result"}


def _denied(result: Mapping[str, Any] | None) -> bool:
    res = result or {}
    return bool(res.get("is_error")) and "denied" in _content_text(res.get("content")).lower()


def tool_violations(events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    results, out = tool_results(events), []
    for c in tool_calls(events):
        if c.get("name") == "StructuredOutput":
            continue
        detail = f"{c.get('name')} {json.dumps(c.get('input'), ensure_ascii=False)[:160]}"
        out.append(Violation("t_tool_denied", detail, "warn") if _denied(results.get(c.get("id")))
                   else Violation("t_tool", detail))
    return out


def word_violations(where: str, text: str, banned_where: Sequence[str]) -> list[Violation]:
    out = [Violation("t_memory", f"{where}: {h.term!r} in …{h.excerpt}…") for h in banned_q.memory_hits(text, where)]
    if where in banned_where:
        out += [Violation("t_banned", f"{where}: {h.term!r} in …{h.excerpt}…")
                for h in banned_q.check_prompt_text(text, where) if h.term not in banned_q.MEMORY_MARKERS]
    return out


def check_events(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, model: str | None,
                 tools_mode: str, kind: str = "gen", cwd: Path = AGENT_CWD) -> list[Violation]:
    """Every rule on one run. ``kind`` gen | probe: both prompts get the banned check; label: system only."""
    banned_where = ("prompt:system",) if kind == "label" else ("prompt:system", "prompt:user")
    out = init_violations(events, model, tools_mode, cwd) + tool_violations(events)
    for where, text in visible_texts(events, prompts):
        out += word_violations(where, text, banned_where)
    res = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if res is None or res.get("subtype") != "success" or res.get("is_error"):
        out.append(Violation("t_result", "no successful result event"))
    return out


def check_run(root: Path, run_id: str, model: str | None, tools_mode: str, kind: str = "gen") -> list[Violation]:
    transcript, prompts = Path(root) / "transcripts" / f"{run_id}.jsonl", Path(root) / "prompts" / f"{run_id}.json"
    if not transcript.is_file():
        return [Violation("t_result", f"transcript {transcript.name} is missing")]
    doc = json.loads(prompts.read_text(encoding="utf-8")) if prompts.is_file() else None
    out = check_events(read_events(transcript), doc, model, tools_mode, kind)
    if doc is None:
        out.append(Violation("t_init", f"prompts/{run_id}.json is missing"))
    return out


def blinding(violations: Sequence[Violation]) -> list[Violation]:
    return [v for v in violations if v.level == "error" and v.rule in BLINDING_RULES]


def first_prompt_tokens(events: Sequence[Mapping[str, Any]]) -> int | None:
    """input + cache tokens of the first assistant message (a loaded context file would push it far up)."""
    for e in events:
        u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" else None
        if isinstance(u, dict):
            return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                     "cache_read_input_tokens"))
    return None
