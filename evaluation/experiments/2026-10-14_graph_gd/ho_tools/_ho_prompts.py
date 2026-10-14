"""The frozen §7 prompts (gen_prompt.md, audit_prompt.md): sections, rendering, schemas.

A prompt file is split on `<!-- section:NAME -->` lines. Section `system` is passed as
`--system-prompt`; a task section (task_new, task_fix, task_audit) is rendered with
`{{name}}` placeholders and passed as the user prompt. Rendering needs every placeholder
of the section and no other value. The prompt file itself is checked with banned.py when it
is loaded (§7: the frozen prompts name none of the banned words); the rendered values are
not: they are tool text (qid, category line) or text other agents wrote (the question JSON,
audit issues, the cores in use). Banned words in that agent text are reported by the
transcript check as warnings (t_banned_agent), project-memory words as t_memory errors.
The output schemas (--json-schema, plain JSON dicts: treat them as read-only) live here
next to the prompts they belong to.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from _ho_common import (AUDIT_PROMPT, CATEGORY_NAME, GEN_PROMPT, MH_SUBTYPES, SUBTYPE_NAME,
                        HoToolError, gd)

import banned  # noqa: E402

__all__ = ["PromptFile", "load_prompt", "render", "category_line", "ITEM_SCHEMA", "GEN_SCHEMA",
           "AUDIT_SCHEMA", "GEN_STATUSES", "SEVERITIES", "ITEM_KEYS", "item_json",
           "default_prompts"]

_SECTION = re.compile(r"^<!-- section:([a-z_]+) -->[ \t]*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
SEVERITIES = ("ok", "minor", "major", "critical")
GEN_STATUSES = ("drafted", "abandoned", "revised", "dropped", "no_change")
ITEM_KEYS = ("id", "category", "subtype", "question", "answer", "key_points", "hop_slots",
             "hop_roles", "bridge", "why_multihop", "shortcut_search", "needs_identity_resolution",
             "notes", "change_log", "core")
_STR = {"type": "string"}
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{k: _STR for k in ITEM_KEYS},
        "category": {"type": "string", "enum": ["KIN", "DIS", "TO", *MH_SUBTYPES]},
        "key_points": {"type": "array", "items": _STR, "minItems": 2, "maxItems": 5},
        "hop_slots": {"type": "array", "minItems": 2, "maxItems": 5,
                      "items": {"type": "array", "minItems": 1, "items": _STR}},
        "hop_roles": {"type": "array", "items": _STR},
        "needs_identity_resolution": {"type": "boolean"}},
    "required": list(ITEM_KEYS)}
GEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": list(GEN_STATUSES)}, "reason": _STR,
                   "item": {"anyOf": [ITEM_SCHEMA, {"type": "null"}]}},
    "required": ["status", "reason", "item"]}
AUDIT_SCHEMA: dict[str, Any] = {   # E7/newq/audit_result.json results rows
    "type": "object",
    "properties": {"id": _STR, "severity": {"type": "string", "enum": list(SEVERITIES)},
                   "issues": {"type": "array", "items": _STR}, "suggested_fix": _STR,
                   "checked": _STR},
    "required": ["id", "severity", "issues", "suggested_fix", "checked"]}


@dataclass(frozen=True)
class PromptFile:
    path: Path
    sha256: str
    sections: Mapping[str, str]


def load_prompt(path: Path) -> PromptFile:
    """Sections of a prompt file; the file itself must pass banned.check_prompt_file."""
    text = Path(path).read_text(encoding="utf-8")
    hits = banned.check_prompt_text(text, str(path))
    if hits:
        raise HoToolError(f"{path}: banned words {sorted({h.term for h in hits})}")
    parts = _SECTION.split(text)
    if parts[0].strip():
        raise HoToolError(f"{path}: text before the first section marker")
    sections = {name: body.strip() + "\n" for name, body in zip(parts[1::2], parts[2::2])}
    if "system" not in sections or len(sections) != len(parts[1::2]):
        raise HoToolError(f"{path}: needs one 'system' section and unique section names")
    return PromptFile(Path(path), gd.file_sha256(path), MappingProxyType(sections))


def render(pf: PromptFile, section: str, values: Mapping[str, str]) -> str:
    """The section with every {{name}} replaced; refuses missing or extra values."""
    if section not in pf.sections:
        raise HoToolError(f"{pf.path.name} has no section {section!r}")
    body = pf.sections[section]
    names = set(_PLACEHOLDER.findall(body))
    if names != set(values):
        raise HoToolError(f"{pf.path.name}:{section} placeholders {sorted(names)} "
                          f"!= values {sorted(values)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)


def category_line(cat: str, subtype: str) -> str:
    """'親屬' / '多跳，子型 SUC（承繼與職分鏈）'."""
    if cat == "MH":
        return f"{CATEGORY_NAME[cat]}，子型 {subtype}（{SUBTYPE_NAME[subtype]}）"
    return CATEGORY_NAME[cat]


def item_json(item: Mapping[str, Any]) -> str:
    """The question as the agents see it: the content keys only, in ITEM_KEYS order."""
    return json.dumps({k: item.get(k) for k in ITEM_KEYS}, ensure_ascii=False, indent=1)


def default_prompts() -> tuple[PromptFile, PromptFile]:
    return load_prompt(GEN_PROMPT), load_prompt(AUDIT_PROMPT)
