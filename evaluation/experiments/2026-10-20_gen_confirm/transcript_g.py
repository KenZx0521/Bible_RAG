"""Transcript rules of every agent run of the GEN confirmation set (prereg §3.1, §3.3, §3.5, §5.4).

Copied from experiment A's ho_a/transcript_a.py (HO's _ho_transcript.py with A's lists) and the regnal qset's
transcript_q.py; neither is imported. A run is its stream-json transcript plus its prompts record
(prompts/<run_id>.json, written by claude_g before the launch: system, user, schema, model, tools_mode,
user_scope, tool_values, pin). Visible text is what the agent read or wrote as far as the transcript holds it: the
system and user prompts, the schema, its text, thinking summaries, tool inputs and results, the final result.

Word lists are banned_g's, with its scope rule (prereg §3.3, as the qset): the full prompt check (PROMPT_TERMS
with the cue words, BANNED_TERMS, MEMORY_MARKERS) on everything fixed or tool-filled — the system prompt, the
schema, every recorded tool value, and the user prompt when its record says scope "prompt" (all of it
tool-rendered: a new-draft prompt, a qset writer prompt); a user prompt of scope "agent" embeds agent-written
fields (a question to audit, a draft to fix, audit findings, Kay's note), so like every agent-written text it
gets MEMORY_MARKERS as an error and BANNED_TERMS as a warning (A's t_banned_agent). Only an explicit "agent" gets
the weaker check: a record with no scope or an unknown one gets the full check (fail closed).

* t_init          init event; cwd AGENT_CWD (outside the repo); model = the job's; claude_code_version = the
                  pin's (when the event names one); tools ⊆ {Bash, StructuredOutput} (mode bt) or ⊆
                  {StructuredOutput} (mode none); no MCP server; permission mode dontAsk
* t_tool          mode bt: every call StructuredOutput or one plain `bt ...` (HO's bt_guard.check_command, the
                  original loaded by path after its sha check); mode none: StructuredOutput only. A refused call
                  is only a warning (t_tool_denied: it ran nothing)
* t_path          no absolute path (or ~/...) in visible text but the prompts, no relative path (./ ../ a/b) in a
                  Bash command line or a tool result
* t_memory        no MEMORY_MARKERS anywhere visible, prompts and the agent's own output included
* t_banned        a full-check hit on the fixed or tool-filled parts listed above
* t_banned_agent  (warn) BANNED_TERMS in agent-written text or in a user prompt of scope "agent"
* t_result        the run ended with a successful result event

BLINDING_RULES are the error rules a draft cannot survive (the HO runner drops the draft, the qset runner voids the
job's output). Cue words in an agent's output are never checked: writers phrase freely.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import banned_g as B
import g_common as GC
import hog_common as H
from claude_g import AGENT_CWD, TOOLS_MODES, init_event, read_events, result_event
from hog_common import Violation, under

TOOLS_OK = {"bt": frozenset({"Bash", "StructuredOutput"}), "none": frozenset({"StructuredOutput"})}
BLINDING_RULES = frozenset({"t_init", "t_tool", "t_path", "t_memory", "t_banned"})
ANSWER_TOOL = "StructuredOutput"
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
    """(where, text) of everything the agent read or wrote; prompt parts are labelled prompt:<part>."""
    p = prompts or {}
    for key in ("system", "user"):
        if isinstance(p.get(key), str):
            yield f"prompt:{key}", p[key]
    if isinstance(p.get("schema"), Mapping):
        yield "prompt:schema", json.dumps(p["schema"], ensure_ascii=False)
    for name, value in sorted(H.as_mapping(p.get("tool_values")).items()):
        yield f"prompt:tool:{name}", str(value)
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
                    cwd: Path = AGENT_CWD, version: str | None = None) -> list[Violation]:
    """``model`` None (the probe of an alias) skips the model comparison; ``version`` None the CLI version's."""
    init = init_event(events)
    if init is None:
        return [Violation("t_init", "no init event")]
    bad = []
    got = Path(str(init.get("cwd")))
    if got != Path(cwd) or under(got, GC.REPO):
        bad.append(f"cwd {got} (expected {cwd}, outside the repo)")
    if model is not None and init.get("model") != model:
        bad.append(f"model {init.get('model')!r} (expected {model})")
    if version is not None and init.get("claude_code_version") not in (None, version):
        bad.append(f"claude_code_version {init.get('claude_code_version')!r} (pinned {version})")
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


def is_denied(result: Mapping[str, Any] | None) -> bool:
    res = result or {}
    return bool(res.get("is_error")) and "denied" in _content_text(res.get("content")).lower()


def tool_reason(name: Any, inp: Mapping[str, Any], tools_mode: str) -> str | None:
    """None when the call is allowed in this mode, else why not."""
    if name == ANSWER_TOOL:
        return None
    if name == "Bash" and tools_mode == "bt":
        return H.bt_guard().check_command(inp.get("command"))
    return f"tool {name!r} (mode {tools_mode})"


def tool_violations(events: Sequence[Mapping[str, Any]], tools_mode: str) -> list[Violation]:
    results, out = tool_results(events), []
    for c in tool_calls(events):
        inp = H.as_mapping(c.get("input"))
        reason = tool_reason(c.get("name"), inp, tools_mode)
        if reason is None:
            continue
        detail = f"{c.get('name')} {json.dumps(inp, ensure_ascii=False)[:160]}: {reason}"
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
                yield f"event {n} command", str(H.as_mapping(c.get("input")).get("command", ""))
            elif c.get("type") == "tool_result":
                yield f"event {n} tool_result", _content_text(c.get("content"))


def path_violations(texts: Sequence[tuple[str, str]], events: Sequence[Mapping[str, Any]]) -> list[Violation]:
    found = [(where, m.group(0)) for where, text in texts if not where.startswith("prompt:")
             for m in _ABS_PATH.finditer(text)]
    found += [(where, m.group(0)) for where, text in _tool_io(events) for m in _REL_PATH.finditer(text)]
    return [Violation("t_path", f"{where}: {path[:120]}") for where, path in found]


def full_check(where: str, user_scope: Any) -> bool:
    """Whether `where` gets the full prompt check (fixed or tool-filled) rather than the agent-text check; a user
    prompt gets the agent-text check only when its scope is exactly "agent"."""
    return where in ("prompt:system", "prompt:schema") or where.startswith("prompt:tool:") or \
        (where == "prompt:user" and user_scope != "agent")


def word_violations(where: str, text: str, full: bool) -> list[Violation]:
    """Full check: a memory marker is t_memory, any other term t_banned. Agent text: t_memory, t_banned_agent (warn)."""
    if full:
        return [Violation("t_memory" if h.term in B.MEMORY_MARKERS else "t_banned",
                          f"{where}: {h.term!r} in …{h.excerpt}…") for h in B.prompt_hits(text, where)]
    out = [Violation("t_memory", f"{where}: {h.term!r} in …{h.excerpt}…") for h in B.agent_hits(text, where)]
    out += [Violation("t_banned_agent", f"{where}: {h.term!r} in …{h.excerpt}…", "warn")
            for h in B.find_terms(text, B.BANNED_TERMS, where)]
    return out


def check_events(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, model: str | None,
                 tools_mode: str, cwd: Path = AGENT_CWD, version: str | None = None) -> list[Violation]:
    """Every transcript rule on one run's events and its prompts record."""
    if tools_mode not in TOOLS_MODES:
        raise H.HoError(f"tools mode {tools_mode!r} is not one of {TOOLS_MODES}")
    scope = H.as_mapping(prompts).get("user_scope")
    texts = list(visible_texts(events, prompts))
    out = init_violations(events, model, tools_mode, cwd, version) + tool_violations(events, tools_mode)
    out += path_violations(texts, events)
    for where, text in texts:
        out += word_violations(where, text, full_check(where, scope))
    res = result_event(events)
    if res is None or res.get("subtype") != "success" or res.get("is_error"):
        out.append(Violation("t_result", "no successful result event"))
    return out


def check_run(root: Path, run_id: str, model: str | None = None, tools_mode: str | None = None,
              cwd: Path | None = None) -> list[Violation]:
    """check_events on a saved run; model, tools mode, cwd and the pinned version default to its prompts record."""
    transcript, prompts = run_paths(root, run_id)
    if not transcript.is_file():
        return [Violation("t_result", f"transcript {transcript.name} is missing")]
    doc = json.loads(prompts.read_text(encoding="utf-8")) if prompts.is_file() else None
    rec = H.as_mapping(doc)
    model = model if model is not None else rec.get("model")
    tools_mode = tools_mode or rec.get("tools_mode")
    if tools_mode not in TOOLS_MODES or not isinstance(model, str):
        return [Violation("t_init", f"{run_id}: no model / tools mode (prompts record missing or incomplete)")]
    cwd = Path(cwd) if cwd is not None else Path(rec.get("cwd") or AGENT_CWD)
    version = H.as_mapping(rec.get("pin")).get("claude_version")
    return check_events(read_events(transcript), doc, model, tools_mode, cwd, version)


def blinding(violations: Sequence[Violation]) -> list[Violation]:
    """The error-level BLINDING_RULES violations (they void the run's output)."""
    return [v for v in violations if v.level == "error" and v.rule in BLINDING_RULES]


def blinding_errors(root: Path, run_ids: Sequence[str]) -> list[Violation]:
    """BLINDING_RULES errors of these saved runs (t_result is the executor's business)."""
    return [Violation(v.rule, f"{run}: {v.detail}") for run in run_ids for v in blinding(check_run(root, run))]


def thinking_chars(events: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """(thinking blocks, characters of their summaries) of one run (probe check c3)."""
    blocks = [c for e in events if e.get("type") == "assistant" for c in _blocks(e)
              if isinstance(c, dict) and c.get("type") == "thinking"]
    return len(blocks), sum(len(c.get("thinking") or "") for c in blocks)


def first_prompt_tokens(events: Sequence[Mapping[str, Any]]) -> int | None:
    """input + cache tokens of the first assistant message (a loaded context file would push it far up)."""
    for e in events:
        u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" else None
        if isinstance(u, dict):
            return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                     "cache_read_input_tokens"))
    return None
