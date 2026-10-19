"""The writers' and labeller's prompts (prompts_q.md), slot rendering and output schemas (qset.md §3).

A prompt file is split on `<!-- section:NAME -->` lines (HO format): system and task_gen for writers,
label_system and task_label for the labeller. Intents are defined in one English line each, so the
only Chinese a writer reads is the instructions, the persona and king names: Chinese definitions
would have to dodge the cue words with synonyms the trigger does not take (recall too low) or use
them (recall too high). Every rendered writer prompt and schema passes banned_q.check_prompt_text
before a launch (QError otherwise); a labeller prompt's own text does too, the questions in it are
only checked for memory markers.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import banned_q
from q_common import INTENT, KNAME, PROMPTS_MD, QError, sha256_file
from spec_q import Chains

_SECTION = re.compile(r"^<!-- section:([a-z_]+) -->[ \t]*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
SECTIONS = ("system", "task_gen", "label_system", "task_label")
LABEL_INTENTS = (*INTENT.values(), "other")
LABEL_KINGDOMS = ("以色列", "猶大", "不明")

DEFINITIONS = {
    "offset": "The king who is |k| places later (k > 0) or earlier (k < 0) than the given king in the same "
              "kingdom's line of kings. The answer is a king.",
    "handovers": "How many times the crown passed from one king to the next, going from the earlier king to the "
                 "later king of the same kingdom. The answer is a number.",
    "usurper_n": "Counting forward in time from the given king in the same kingdom, the n-th man who took the "
                 "crown by conspiracy or by killing the king. The answer is a king.",
    "on_throne_at_birth": "The king of Judah who was ruling in the year the given king of Judah was born. "
                          "The answer is a king.",
    "attribute": "One recorded fact about this king himself (see aspect).",
    "event": "Something that happened to this king or that he did (see aspect).",
    "sync": "In which year of the other king's reign this king began to reign. The answer is a year number.",
    "contemporary": "Which kings of the other kingdom ruled during this king's reign.",
    "kin": "A family-line question about this king (see aspect).",
}
LABEL_OTHER = "None of the above (for example the very next or previous king, or not about a king)."
ASPECTS = {
    "reign_length": "how long he reigned",
    "accession_age": "how old he was when he became king",
    "mother": "who his mother was",
    "father": "who his father was",
    "death": "how his reign ended or how he died",
    "came_to_throne": "how he came to the throne",
    "remembered_for": "what he is remembered for, good or evil",
    "prophet": "which prophet spoke to him or was active in his time",
    "generations_from_david": "how many generations there are from David down to this king",
    "grandfather": "who this king's grandfather was",
}
PERSONA_TEXT = {
    "sunday_school": "主日學老師，正在備課，想把一個細節問清楚。",
    "casual": "一般信徒，用口語隨口問，句子短。",
    "seminary": "神學生，用詞正式，問得精確。",
    "search_box": "在搜尋框打字的人，常常只打關鍵詞，不一定寫成完整的句子。",
    "reading": "正在讀列王紀或歷代志的人，讀到一半順口想問。",
}
_STR = {"type": "string"}
_NSTR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NINT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


@dataclass(frozen=True)
class PromptFile:
    path: Path
    sha256: str
    sections: Mapping[str, str]


def load_prompts(path: Path = PROMPTS_MD) -> PromptFile:
    """Sections of the prompt file; the file itself must pass the banned check."""
    text = Path(path).read_text(encoding="utf-8")
    hits = banned_q.check_prompt_text(text, str(path))
    if hits:
        raise QError(f"{Path(path).name}: banned {sorted({h.term for h in hits})}")
    parts = _SECTION.split(text)
    if parts[0].strip():
        raise QError(f"{Path(path).name}: text before the first section marker")
    sections = {name: body.strip() + "\n" for name, body in zip(parts[1::2], parts[2::2])}
    if set(sections) != set(SECTIONS) or len(sections) != len(parts[1::2]):
        raise QError(f"{Path(path).name}: needs exactly the sections {SECTIONS}")
    return PromptFile(Path(path), sha256_file(path), MappingProxyType(sections))


def render(pf: PromptFile, section: str, values: Mapping[str, Any]) -> str:
    body = pf.sections[section]
    names = set(_PLACEHOLDER.findall(body))
    if names != set(values):
        raise QError(f"{pf.path.name}:{section} placeholders {sorted(names)} != values {sorted(values)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)


def gen_schema(labels: Sequence[str]) -> dict[str, Any]:
    item = {"type": "object", "properties": {"slot": {"type": "string", "enum": list(labels)}, "question": _STR},
            "required": ["slot", "question"]}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item, "minItems": len(labels),
                                                       "maxItems": len(labels)}}, "required": ["items"]}


def label_schema(ids: Sequence[str]) -> dict[str, Any]:
    item = {"type": "object",
            "properties": {"id": {"type": "string", "enum": list(ids)},
                           "intent": {"type": "string", "enum": list(LABEL_INTENTS)}, "king": _NSTR,
                           "kingdom": {"type": "string", "enum": list(LABEL_KINGDOMS)}, "k": _NINT, "n": _NINT,
                           "second_king": _NSTR},
            "required": ["id", "intent", "king", "kingdom", "k", "n", "second_king"]}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item, "minItems": len(ids),
                                                       "maxItems": len(ids)}}, "required": ["items"]}


def _king_lines(ch: Chains, x: str, head: str) -> list[str]:
    lines = [f"{head}: {ch.name(x)}（{KNAME[ch.kingdom(x)]}）",
             f"names that may be used{'' if head == 'king' else ' for the ' + head}: {'、'.join(ch.safe_names(x))}"]
    same = ch.homonyms(x)
    if len(same) > 1:
        kds = {ch.kingdom(y) for y in same}
        if len(kds) == 1:
            nth = ("first", "second", "third")[same.index(x)]
            father = ch.field(x, "father")
            lines.append(f"note: {KNAME[ch.kingdom(x)]} had {len(same)} kings named {ch.name(x)}; this is the {nth} "
                         f"of them{', son of ' + father if father else ''}. The question must make clear which one.")
        else:
            lines.append(f"note: both {KNAME['I']} and {KNAME['J']} had a king named {ch.name(x)}; the question must "
                         f"make clear which one is meant.")
    return lines


def slot_block(ch: Chains, slot: Mapping[str, Any]) -> str:
    """One slot as the writer reads it: label, intent, English definition, kings and conditions (no answer)."""
    intent = slot["intent"]
    lines = [f"[{slot['slot']}]", f"intent: {intent}", f"definition: {DEFINITIONS[intent]}"]
    if slot["qtype"] == "S1b":
        lines += _king_lines(ch, slot["start"], "earlier king") + _king_lines(ch, slot["other"], "later king")
    else:
        lines += _king_lines(ch, slot["start"], "king")
    if slot["qtype"] == "S1a":
        k = slot["k"]
        lines.append(f"k: {k:+d} ({abs(k)} places {'later' if k > 0 else 'earlier'} in that kingdom's line of kings)")
    elif slot["qtype"] == "S1c":
        lines.append(f"n: {slot['n']}")
    elif slot["qtype"] == "N3":
        lines += _king_lines(ch, slot["other"], "other king")
    if slot.get("aspect"):
        lines.append(f"aspect: {ASPECTS[slot['aspect']]}")
    return "\n".join(lines)


def _checked(where: str, text: str) -> str:
    hits = banned_q.check_prompt_text(text, where)
    if hits:
        raise QError(f"{where}: banned {sorted({h.term for h in hits})}")
    return text


def gen_prompt(pf: PromptFile, ch: Chains, job: Mapping[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """(system, user, schema) of a writer job; each part passed the banned check."""
    slots = "\n\n".join(slot_block(ch, s) for s in job["slots"])
    user = render(pf, "task_gen", {"persona": PERSONA_TEXT[job["persona"]], "n": len(job["slots"]), "slots": slots})
    schema = gen_schema([s["slot"] for s in job["slots"]])
    _checked("schema", json.dumps(schema, ensure_ascii=False))
    return _checked("system", pf.sections["system"]), _checked("user", user), schema


def definitions_text() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in DEFINITIONS.items()) + f"\n- other: {LABEL_OTHER}"


def label_prompt(pf: PromptFile, questions: Sequence[tuple[str, str]]) -> tuple[str, str, dict[str, Any]]:
    """(system, user, schema) of a labeller job over (id, question) pairs. The template and schema pass the
    full banned check; the writers' questions (cue words allowed) only the memory-marker check."""
    system = _checked("label_system", render(pf, "label_system", {"definitions": definitions_text()}))
    _checked("task_label", render(pf, "task_label", {"n": len(questions), "questions": ""}))
    body = "\n".join(f"{i}：{q}" for i, q in questions)
    leaks = banned_q.memory_hits(body, "questions")
    if leaks:
        raise QError(f"label questions: memory markers {sorted({h.term for h in leaks})}")
    schema = label_schema([i for i, _ in questions])
    _checked("label_schema", json.dumps(schema, ensure_ascii=False))
    return system, render(pf, "task_label", {"n": len(questions), "questions": body}), schema
