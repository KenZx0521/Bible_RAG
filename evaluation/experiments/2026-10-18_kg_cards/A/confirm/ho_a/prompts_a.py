"""The question-writing prompts (gen_a.md, audit_a.md), their rendering and output schemas (confirm_A.md §2.6–2.8).

A prompt file is split on `<!-- section:NAME -->` lines (HO format). Section `system` is passed as
--system-prompt; a task section (task_new, task_fix, task_audit) is rendered with `{{name}}`
placeholders as the user prompt, and rendering needs every placeholder of the section and no
other value. The prompt file and the output schemas must pass banned_a when loaded. Rendered values
are tool text (qid, segment line, slot line) or text agents wrote (questions, audit issues);
transcript_a checks those as visible text. QUESTION_SCHEMA is §2.8.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from hoa_common import AUDIT_PROMPT, GEN_PROMPT, HoError, sha256_file

import banned_a  # noqa: E402

_SECTION = re.compile(r"^<!-- section:([a-z_]+) -->[ \t]*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
QTYPES = ("S1a", "S1b", "S1c", "S4")
SLOT_TYPES = ("S1a", "S1a_rev", "S1b", "S1c", "S4")
KINGDOMS = ("以色列", "猶大")
ROLES = ("seed", "step", "answer")
SEVERITIES = ("ok", "minor", "major", "critical")
GEN_STATUSES = ("drafted", "abandoned", "revised", "dropped", "no_change")
ITEM_KEYS = ("id", "segment", "qtype", "kingdom", "question", "seeds", "k", "n", "answer", "chain", "convention",
             "shortcut_search", "conflict_search", "notes", "change_log")
NO_DONE = "（無）"
_STR = {"type": "string"}
_NSTR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NINT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_SEED = {"type": "object", "properties": {"name": _STR, "father": _NSTR}, "required": ["name", "father"]}
_ANSWER = {"type": "object",
           "properties": {"kind": {"type": "string", "enum": ["name", "count"]}, "text": _STR,
                          "accept": {"type": "array", "items": _STR}, "value": _NINT, "unit": _NSTR},
           "required": ["kind", "text", "accept", "value", "unit"]}
_ROW = {"type": "object",
        "properties": {"king": _STR, "father": _NSTR, "role": {"type": "string", "enum": list(ROLES)},
                       "fact": _STR, "basis": {"type": "array", "items": _STR}},
        "required": ["king", "father", "role", "fact", "basis"]}
QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"id": _STR, "segment": _STR, "qtype": {"type": "string", "enum": list(QTYPES)},
                   "kingdom": {"type": "string", "enum": list(KINGDOMS)}, "question": _STR,
                   "seeds": {"type": "array", "items": _SEED, "minItems": 1, "maxItems": 2},
                   "k": _NINT, "n": _NINT, "answer": _ANSWER,
                   "chain": {"type": "array", "items": _ROW, "minItems": 2},
                   "convention": _STR, "shortcut_search": _STR, "conflict_search": _STR, "notes": _STR,
                   "change_log": _STR},
    "required": list(ITEM_KEYS)}
GEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": list(GEN_STATUSES)}, "reason": _STR,
                   "item": {"anyOf": [QUESTION_SCHEMA, {"type": "null"}]}},
    "required": ["status", "reason", "item"]}
AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"id": _STR, "severity": {"type": "string", "enum": list(SEVERITIES)},
                   "issues": {"type": "array", "items": _STR}, "suggested_fix": _STR, "checked": _STR},
    "required": ["id", "severity", "issues", "suggested_fix", "checked"]}
QTYPE_TEXT = {"S1a": "S1a 第 k 位王", "S1b": "S1b 交接次數", "S1c": "S1c 第 n 個篡位者", "S4": "S4 出生時在位的王"}


@dataclass(frozen=True)
class PromptFile:
    path: Path
    sha256: str
    sections: Mapping[str, str]


def check_schemas() -> None:
    """The schemas reach the agent through --json-schema: they must pass banned_a too."""
    for name, schema in (("GEN_SCHEMA", GEN_SCHEMA), ("AUDIT_SCHEMA", AUDIT_SCHEMA)):
        hits = banned_a.check_prompt_text(json.dumps(schema, ensure_ascii=False), name)
        if hits:
            raise HoError(f"{name}: banned words {sorted({h.term for h in hits})}")


def load_prompt(path: Path) -> PromptFile:
    """Sections of a prompt file; the file must pass banned_a.check_prompt_text."""
    text = Path(path).read_text(encoding="utf-8")
    hits = banned_a.check_prompt_text(text, str(path))
    if hits:
        raise HoError(f"{Path(path).name}: banned words {sorted({h.term for h in hits})}")
    parts = _SECTION.split(text)
    if parts[0].strip():
        raise HoError(f"{Path(path).name}: text before the first section marker")
    sections = {name: body.strip() + "\n" for name, body in zip(parts[1::2], parts[2::2])}
    if "system" not in sections or len(sections) != len(parts[1::2]):
        raise HoError(f"{Path(path).name}: needs one 'system' section and unique section names")
    check_schemas()
    return PromptFile(Path(path), sha256_file(path), MappingProxyType(sections))


def render(pf: PromptFile, section: str, values: Mapping[str, str]) -> str:
    """The section with every {{name}} replaced; refuses missing or extra values."""
    if section not in pf.sections:
        raise HoError(f"{pf.path.name} has no section {section!r}")
    body = pf.sections[section]
    names = set(_PLACEHOLDER.findall(body))
    if names != set(values):
        raise HoError(f"{pf.path.name}:{section} placeholders {sorted(names)} != values {sorted(values)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)


def segment_line(seg: Mapping[str, Any]) -> str:
    """'以色列；本段範圍 王上15:27–王上16:15' ({{segment_line}}, §2.6-10)."""
    return f"{seg['kingdom_name']}；本段範圍 {seg['range_label']}"


def qtype_line(slot_type: str, reverse_of: Mapping[str, Any] | None = None) -> str:
    """The slot's question type in the writer's words; S1a_rev names the direction rule (§2.4)."""
    if slot_type not in SLOT_TYPES:
        raise HoError(f"unknown slot type {slot_type!r}")
    if slot_type != "S1a_rev":
        return QTYPE_TEXT[slot_type]
    if reverse_of is None:
        return QTYPE_TEXT["S1a"]
    return f"{QTYPE_TEXT['S1a']}（方向要與本段已出的 S1a 題（k＝{reverse_of.get('k')}）相反，或 k 的大小不同）"


def segment_done(items: Sequence[Mapping[str, Any]]) -> str:
    """「本段已出題」: this segment's own passed questions with their answers only (§2.5)."""
    rows = [f"- {it.get('qtype')}（k＝{it.get('k')}，n＝{it.get('n')}）：{it.get('question')}"
            f"（答案：{(it.get('answer') or {}).get('text')}）" for it in items]
    return "\n".join(rows) if rows else NO_DONE


def item_json(item: Mapping[str, Any]) -> str:
    """The question as the agents see it: the §2.8 keys only, in ITEM_KEYS order (never hidden flags)."""
    return json.dumps({k: item.get(k) for k in ITEM_KEYS}, ensure_ascii=False, indent=1)


def issues_text(request: Mapping[str, Any]) -> str:
    issues = "\n".join(f"- {x}" for x in request.get("issues") or ()) or "- （無具體意見）"
    if request.get("suggested_fix"):
        issues += f"\n建議改法：{request['suggested_fix']}"
    return issues


def default_prompts() -> tuple[PromptFile, PromptFile]:
    return load_prompt(GEN_PROMPT), load_prompt(AUDIT_PROMPT)
