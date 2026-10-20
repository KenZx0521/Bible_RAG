"""The P1/P2 writers' prompt (prompts_qg.md), slot rendering and output schema (prereg §5.4; qset.md §3).

qset's shape: one system prompt and one task prompt per job (a reader persona and a few slots with opaque labels q1..,
shuffled, so a writer cannot tell a positive from a near miss); the writer only phrases (no tools, no answer). All of
it is English but names, the marker and the book names, so no cue word has to be dodged (qset.md §3: English
definitions; personas are qset's five, in English here). A positive slot is the HO writer's slot (prereg §3.2, §5.4:
the same name and marker constraints): ``prompts_g.slot_spec`` gives its definition (prompts_g.DEFINITIONS, exactly),
scope and naming line (NO_OTHER_PERSON, or WITH_MARKER with the computed marker on a marker-required slot). A near
miss gets its family's English definition (NEAR, one per spec_qg source) in the same four lines; d = 1, d >= 5, the
cross-chapter, Cain-line, Terah's-son and post-Genesis-12 slots use the positives' own definition and differ only in
scope, as a near miss should.

Every rendered part passes banned_g's full prompt check before a launch (scope "prompt": the prompt file, the system
prompt, the user prompt, the schema and every tool value: persona, n, each slot block), and holds none of gencard's
CUE_LITERALS (checked explicitly against the package's own tuple, whatever banned_g's stand-in); a hit raises
banned_g.BlindingError, so nothing launches. Output schema: {items: [{slot, question}]} with exactly the job's labels.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import banned_g as B
import g_common as GC
import prompts_g as P

PROMPT_FILE = GC.QSET_PROMPT
SECTIONS = ("system", "task_gen")
PERSONA_TEXT = MappingProxyType({
    "sunday_school": "A Sunday-school teacher preparing a lesson, who wants one detail made clear.",
    "casual": "An ordinary churchgoer asking offhand, in spoken style and short sentences.",
    "seminary": "A seminary student who uses formal wording and asks precisely.",
    "search_box": "Someone typing into a search box, often only key words, not always a complete sentence.",
    "reading": "Someone reading through the Bible who stops partway through a chapter to ask."})
ANCESTOR = "{scope}, where X is an ancestor of Y"
ONE_PERSON = "name exactly {x} and no other person."
# spec_qg source -> (quantity, scope, naming); people is "X = {x}; Y = {y}" or "X = {x}"
NEAR = MappingProxyType({
    "n2": ("{x}'s age, in years, in the year {y} died, according to Genesis.", ANCESTOR, P.NO_OTHER_PERSON),
    "lifespan": ("How many years {x} lived in all, according to Genesis.", "{scope}", ONE_PERSON),
    "d1_f1": (P.DEFINITIONS["age_at_birth"], "{scope}, where X is the father of Y", P.NO_OTHER_PERSON),
    "d1_f5": (P.DEFINITIONS["age_at_death"], "{scope}, where X is the father of Y", P.NO_OTHER_PERSON),
    "flood": ("{x}'s age, in years, in the year of the flood, according to Genesis.", "Genesis", ONE_PERSON),
    "f3": ("How many years after the flood {x} was born, according to Genesis.", "{scope}", ONE_PERSON),
    "f1_far": (P.DEFINITIONS["age_at_birth"], ANCESTOR, P.NO_OTHER_PERSON),
    "cross": (P.DEFINITIONS["age_at_birth"], "Genesis 5 and Genesis 11, where X is an ancestor of Y",
              P.NO_OTHER_PERSON),
    "cain": (P.DEFINITIONS["age_at_birth"], "Genesis 4, the family of Cain, where X is the father of Y",
             P.NO_OTHER_PERSON),
    "terah": (P.DEFINITIONS["age_at_birth"], "{scope}, where Y is a son of X", P.NO_OTHER_PERSON),
    "luke": ("{x}'s age, in years, in the year {y} was born, according to {book_en}.", "{book_en} ({book})",
             "name exactly {x} and {y} and no other person; name the book {book}."),
    "chron": ("{x}'s age, in years, in the year {y} was born, according to {book_en}.", "{book_en} ({book})",
              "name exactly {x} and {y} and no other person; name the book {book}."),
    "after12": (P.DEFINITIONS["age_at_birth"], "Genesis, after chapter 12, where Y is a son of X", P.NO_OTHER_PERSON),
    "gens": ("How many generations there are from {x} down to {y}, according to Genesis.", ANCESTOR,
             P.NO_OTHER_PERSON),
    "longest": ("Which of {x} and {y} lived longer, according to Genesis; the answer is one of the two.", "{scope}",
                P.NO_OTHER_PERSON),
    "yes_no": ("Whether {x} was still alive in the year {y} was born, according to Genesis; the question asks for a "
               "yes or a no.", ANCESTOR, P.NO_OTHER_PERSON),
    "word0": ("{x}'s age, in years, at some moment of his life, according to Genesis, asked in a sentence that also "
              "uses the everyday word {word}.", "{scope}",
              "name exactly {x} and no other person; also use the everyday word {word} once."),
})
NEAR = MappingProxyType({**NEAR, "word1": NEAR["word0"]})
_STR = {"type": "string"}


@dataclass(frozen=True)
class QRendered:
    """What one writer job sends: --system-prompt, the user prompt, --json-schema and the tool values."""
    job_id: str
    system: str
    user: str
    schema: Mapping[str, Any]
    prompt_sha256: str
    values: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def load(path: Path = PROMPT_FILE) -> P.PromptFile:
    """The prompt file's sections; the whole file passes the full prompt check (prompts_g.load_prompt)."""
    return P.load_prompt(path, SECTIONS)


def cue_literals() -> tuple[str, ...]:
    return tuple(importlib.import_module("gencard").CUE_LITERALS)


def checked(text: str, where: str) -> str:
    """The full prompt check, and gencard's own cue words named explicitly."""
    B.require(text, where, "prompt")
    hits = [c for c in cue_literals() if c in text]
    if hits:
        raise B.BlindingError(f"{where}: cue words {sorted(set(hits))}")
    return text


def gen_schema(labels: Sequence[str]) -> dict[str, Any]:
    item = {"type": "object", "properties": {"slot": {"type": "string", "enum": list(labels)}, "question": _STR},
            "required": ["slot", "question"]}
    return {"type": "object", "properties": {"items": {"type": "array", "items": item, "minItems": len(labels),
                                                       "maxItems": len(labels)}}, "required": ["items"]}


def positive_spec(slot: Mapping[str, Any], names: P.Names) -> P.SlotSpec:
    """The HO writer's view of a positive slot (prompts_g.slot_spec; the qid is a placeholder the writer never sees)."""
    return P.slot_spec(slot, names, "Q01")


def _scope(slot: Mapping[str, Any]) -> str:
    return f"Genesis {slot['chapter']}" if slot.get("chapter") else "Genesis"


def slot_lines(slot: Mapping[str, Any], names: P.Names) -> tuple[str, str, str, str]:
    """(quantity, people, scope, naming) of one slot."""
    if slot["kind"] == "pos":
        s = positive_spec(slot, names)
        return s.definition, f"X = {s.x}; Y = {s.y}", ANCESTOR.format(scope=s.scope), s.naming
    quantity, scope, naming = NEAR[slot["source"]]
    v = {"x": slot["x"], "y": slot.get("y"), "scope": _scope(slot), "book": slot.get("book"),
         "book_en": slot.get("book_en"), "word": slot.get("word")}
    people = f"X = {slot['x']}" + (f"; Y = {slot['y']}" if slot.get("y") else "")
    return quantity.format(**v), people, scope.format(**v), naming.format(**v)


def slot_block(slot: Mapping[str, Any], names: P.Names) -> str:
    quantity, people, scope, naming = slot_lines(slot, names)
    return "\n".join((f"[{slot['slot']}]", f"quantity: {quantity}", f"people: {people}", f"scope: {scope}",
                      f"naming: {naming}"))


def render_job(job: Mapping[str, Any], names: P.Names, pf: P.PromptFile | None = None) -> QRendered:
    """(system, user, schema, tool values) of one writer job; every part passed ``checked``."""
    pf = pf or load()
    blocks = {s["slot"]: checked(slot_block(s, names), f"{job['job_id']}:{s['slot']}") for s in job["slots"]}
    tool = {"persona": PERSONA_TEXT[job["persona"]], "n": str(len(job["slots"])), "slots": "\n\n".join(blocks.values())}
    for k, v in tool.items():
        checked(v, f"{job['job_id']}:{k}")
    user = checked(P.render(pf, "task_gen", tool, {}), f"{job['job_id']}:user")
    system = checked(pf.sections["system"], f"{pf.path.name}:system")
    schema = gen_schema(list(blocks))
    checked(json.dumps(schema, ensure_ascii=False), f"{job['job_id']}:schema")
    return QRendered(job["job_id"], system, user, schema, pf.sha256, MappingProxyType(tool))
