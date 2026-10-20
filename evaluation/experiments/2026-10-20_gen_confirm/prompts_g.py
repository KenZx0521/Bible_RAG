"""Writer, fixer and auditor prompts of the GEN confirmation set (prereg §3.2, §3.5, §3.6): slots, rendering, schemas.

Inputs. A slot is a pool.json row (prereg §2.1); the names are store gen_names.json (schema
gen_confirm.gen_names.v1, built by names_g.py). ``slot_spec`` turns the two into what an agent may see: the
neutral qtype (F1 -> age_at_birth, F5 -> age_at_death), X and Y in layer spelling, the chapter, the path X..Y
(for mech_g only) and, on the 6 marker-required slots, the marker computed from the chain order: Y's chain son
「C的父親Y」 when Y has one in its chapter, else X's chain father 「F的兒子X」 (both are off the path by
construction; every marker-required pool slot gets the Y form). The audit's definition then adds which namesake
is meant (``SlotSpec.identity``, the marker in English). Layer ids, sids and golds never reach a prompt.

Prompt files (HO format, split on ``<!-- section:NAME -->``): gen_g.md (system, task_new, task_fix) for writers
and fixers, audit_g.md (system, task_audit) for the value-blind auditor. Everything is English except names,
the marker, 創世記, 和合本修訂版 and the units 歲 / 年, so no cue word has to be dodged.

Rendering applies banned_g's scope rule part by part (prereg §3.3): the prompt files, the schemas and every
tool value (ids, qtype, definition, names, scope, naming line, mech details, value hints) pass the full prompt
check; agent text (the question, the draft JSON, audit findings, mech quotes, Kay's note) passes the memory-marker
check; any hit raises banned_g.BlindingError before a launch. An audit prompt is built from the question string
alone (never the writer's value, steps, notes or other slots); no render takes another slot's question or answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import banned_g as B
import g_common as GC

GEN_PROMPT = GC.GEN_PROMPT
AUDIT_PROMPT = GC.AUDIT_PROMPT
GEN_SECTIONS = ("system", "task_new", "task_fix")
AUDIT_SECTIONS = ("system", "task_audit")
NAMES_SCHEMA = "gen_confirm.gen_names.v1"
NAMES_KEYS = ("schema", "chain", "cain_line", "abram_family", "extra_persons", "other_books", "lexicon_blockers")
QTYPE = {"F1": "age_at_birth", "F5": "age_at_death"}
QTYPES = tuple(QTYPE.values())
DEFINITIONS = {"age_at_birth": "{x}'s age, in years, in the year {y} was born, according to Genesis.",
               "age_at_death": "{y}'s age, in years, in the year {x} died, according to Genesis."}
# the auditor's definition on a marker slot says which namesake is meant (the marker read as English)
IDENTITY = {"Y": " Here {y} means the father of {c}.", "X": " Here {x} means the son of {f}."}
NO_OTHER_PERSON = "name exactly {x} and {y} and no other person."
WITH_MARKER = ("name {x} and {y}; write the identifying phrase {marker} exactly as given, once, because {who} has a "
               "namesake; name no other person.")
UNITS = ("歲", "年")
SEVERITIES = ("critical", "major", "minor")
GEN_STATUSES = ("drafted", "abandoned", "revised", "dropped", "no_change")
ITEM_KEYS = ("id", "slot", "qtype", "X", "Y", "marker", "question", "answer", "steps", "convention", "notes")
STEP_KEYS = ("person", "fact", "verse")
AUDIT_KEYS = ("id", "value", "reading", "findings", "checked")
FINDING_KEYS = ("severity", "issue", "suggested_fix")
SOURCES = GC.FIX_SOURCES                             # mech, audit (value fixes count as audit), kay
# prereg §3.6: the neutral gold_mismatch hint (its Chinese text) and the ambiguity hint of row 2
GOLD_MISMATCH_HINT = "answer.value：與依所引經節的獨立重算不一致。"
AMBIGUITY_HINT = ("An independent reader working from the question alone did not arrive at the same number: the "
                  "question may allow more than one reading of a person or of the quantity. Make it allow exactly one.")
QID = re.compile(r"^Q[0-9]{2,}[0-9a-z]*$")
_SECTION = re.compile(r"^<!-- section:([a-z_]+) -->[ \t]*$", re.M)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
_STR = {"type": "string"}
_NSTR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NINT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"id": _STR, "slot": _STR, "qtype": {"type": "string", "enum": list(QTYPES)}, "X": _STR, "Y": _STR,
                   "marker": _NSTR, "question": _STR,
                   "answer": {"type": "object", "properties": {"value": {"type": "integer"},
                                                               "unit": {"type": "string", "enum": list(UNITS)}},
                              "required": ["value", "unit"]},
                   "steps": {"type": "array", "minItems": 2,
                             "items": {"type": "object", "properties": {k: _STR for k in STEP_KEYS},
                                       "required": list(STEP_KEYS)}},
                   "convention": _STR, "notes": _STR},
    "required": list(ITEM_KEYS)}
GEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": list(GEN_STATUSES)}, "reason": _STR,
                   "item": {"anyOf": [ITEM_SCHEMA, {"type": "null"}]}},
    "required": ["status", "reason", "item"]}
AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"id": _STR, "value": _NINT, "reading": _STR,
                   "findings": {"type": "array",
                                "items": {"type": "object",
                                          "properties": {"severity": {"type": "string", "enum": list(SEVERITIES)},
                                                         "issue": _STR, "suggested_fix": _STR},
                                          "required": list(FINDING_KEYS)}},
                   "checked": _STR},
    "required": list(AUDIT_KEYS)}


class PromptError(ValueError):
    """A slot, names document, prompt file or render input was refused."""


# ---------------------------------------------------------------- names (store gen_names.json)
@dataclass(frozen=True)
class Person:
    id: str
    name: str
    chapter: int


def _names(doc: Mapping[str, Any], key: str) -> tuple[str, ...]:
    v = doc.get(key)
    if not (isinstance(v, list) and all(isinstance(s, str) and s for s in v)):
        raise PromptError(f"gen_names {key} must be a list of non-empty strings")
    return tuple(v)


@dataclass(frozen=True)
class Names:
    """The chain (in chain order, chapter 5 then 11) and the name lists of gen_names.json."""
    chain: tuple[Person, ...]
    cain_line: tuple[str, ...]
    abram_family: tuple[str, ...]
    extra_persons: tuple[str, ...]
    other_books: tuple[str, ...]
    lexicon_blockers: tuple[str, ...]

    @classmethod
    def from_doc(cls, doc: Mapping[str, Any]) -> "Names":
        missing = [k for k in NAMES_KEYS if k not in doc]
        if missing:
            raise PromptError(f"gen_names misses {missing}")
        if doc["schema"] != NAMES_SCHEMA:
            raise PromptError(f"gen_names schema {doc['schema']!r} is not {NAMES_SCHEMA}")
        rows = doc["chain"]
        if not (isinstance(rows, list) and rows and all(
                isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("name"), str) and r["name"]
                and isinstance(r.get("chapter"), int) for r in rows)):
            raise PromptError("gen_names chain must be a non-empty list of {id, name, chapter}")
        chain = tuple(Person(r["id"], r["name"], r["chapter"]) for r in rows)
        if len({p.id for p in chain}) != len(chain) or len({p.name for p in chain}) != len(chain):
            raise PromptError("gen_names chain ids and names must be unique")
        return cls(chain=chain, **{k: _names(doc, k) for k in NAMES_KEYS[2:]})

    def person(self, pid: str) -> Person:
        for p in self.chain:
            if p.id == pid:
                return p
        raise PromptError(f"{pid!r} is not a chain person")

    def id_of(self, name: str) -> str | None:
        return next((p.id for p in self.chain if p.name == name), None)

    def line(self, chapter: int) -> tuple[Person, ...]:
        return tuple(p for p in self.chain if p.chapter == chapter)

    def _step(self, pid: str, k: int) -> Person | None:
        p = self.person(pid)
        line = self.line(p.chapter)
        i = line.index(p) + k
        return line[i] if 0 <= i < len(line) else None

    def father(self, pid: str) -> Person | None:
        """The chain father of `pid` in its chapter (None for the chapter's first person)."""
        return self._step(pid, -1)

    def son(self, pid: str) -> Person | None:
        """The chain son of `pid` in its chapter (None for the chapter's last person)."""
        return self._step(pid, 1)

    def path(self, x: str, y: str) -> tuple[Person, ...]:
        px, py = self.person(x), self.person(y)
        if px.chapter != py.chapter:
            raise PromptError(f"{x} and {y} are not in one chapter")
        line = self.line(px.chapter)
        i, j = line.index(px), line.index(py)
        if i >= j:
            raise PromptError(f"{x} is not an ancestor of {y}")
        return line[i:j + 1]

    @property
    def known(self) -> tuple[str, ...]:
        """Every person name mech_g may meet: the chain plus the extra persons (lexicon blockers are not names)."""
        return tuple(dict.fromkeys([p.name for p in self.chain] + list(self.extra_persons)))


def load_names(path: Path = GC.GEN_NAMES) -> Names:
    return Names.from_doc(GC.read_json(path))


# ---------------------------------------------------------------- slots
def chain_marker(names: Names, x: str, y: str) -> tuple[str, str, str]:
    """(marker, marker person, end): Y's chain son as 「C的父親Y」, else X's chain father as 「F的兒子X」."""
    son = names.son(y)
    if son is not None:
        return f"{son.name}的父親{names.person(y).name}", son.name, "Y"
    father = names.father(x)
    if father is not None:
        return f"{father.name}的兒子{names.person(x).name}", father.name, "X"
    raise PromptError(f"no off-path marker for {x}>{y}: Y has no chain son and X no chain father")


@dataclass(frozen=True)
class SlotSpec:
    """One slot as the writer, fixer and auditor may see it, plus the path mech_g needs."""
    sid: str
    qid: str
    slot_id: str
    qtype: str
    chapter: int
    x_id: str
    y_id: str
    x: str
    y: str
    path: tuple[str, ...]
    marker: str | None = None
    marker_person: str | None = None
    marker_end: str | None = None

    @property
    def definition(self) -> str:
        return DEFINITIONS[self.qtype].format(x=self.x, y=self.y)

    @property
    def identity(self) -> str:
        """On a marker slot, the marked person in English ("Here Y means the father of C."); else empty."""
        if self.marker is None:
            return ""
        return IDENTITY[self.marker_end].format(x=self.x, y=self.y, c=self.marker_person, f=self.marker_person)

    @property
    def scope(self) -> str:
        return f"Genesis {self.chapter}"

    @property
    def naming(self) -> str:
        if self.marker is None:
            return NO_OTHER_PERSON.format(x=self.x, y=self.y)
        who = self.y if self.marker_end == "Y" else self.x
        return WITH_MARKER.format(x=self.x, y=self.y, marker=self.marker, who=who)


def _check_id(value: str, what: str) -> str:
    if not (isinstance(value, str) and QID.fullmatch(value)):
        raise PromptError(f"{what} id {value!r} must look like Q01")
    return value


def slot_spec(slot: Mapping[str, Any], names: Names, qid: str, slot_id: str | None = None) -> SlotSpec:
    """The spec of a pool row; refuses a row that is not a same-chapter ancestor pair of the chain at d >= 2."""
    _check_id(qid, "question")
    _check_id(slot_id or qid, "slot")
    if slot.get("qtype") not in QTYPE:
        raise PromptError(f"qtype {slot.get('qtype')!r} is not F1 or F5")
    px, py = names.person(slot["x"]), names.person(slot["y"])
    if px.chapter != slot["chapter"] or py.chapter != slot["chapter"]:
        raise PromptError(f"{slot['x']}>{slot['y']} is not in chapter {slot['chapter']}")
    path = names.path(px.id, py.id)
    if len(path) < 3:
        raise PromptError(f"{px.id}>{py.id} is less than two generations")
    if "persons" in slot and list(slot["persons"]) != [p.id for p in path]:
        raise PromptError(f"persons of {slot.get('sid')} differ from the chain path")
    marker = chain_marker(names, px.id, py.id) if slot.get("marker_required") else (None, None, None)
    return SlotSpec(str(slot.get("sid", "")), qid, slot_id or qid, QTYPE[slot["qtype"]], slot["chapter"], px.id, py.id,
                    px.name, py.name, tuple(p.name for p in path), *marker)


# ---------------------------------------------------------------- prompt files and schemas
@dataclass(frozen=True)
class PromptFile:
    path: Path
    sha256: str
    sections: Mapping[str, str]


def load_prompt(path: Path, sections: Sequence[str]) -> PromptFile:
    """Sections of a prompt file; the whole file must pass the full prompt check."""
    text = Path(path).read_text(encoding="utf-8")
    B.require(text, Path(path).name)
    parts = _SECTION.split(text)
    if parts[0].strip():
        raise PromptError(f"{Path(path).name}: text before the first section marker")
    found = {name: body.strip() + "\n" for name, body in zip(parts[1::2], parts[2::2])}
    if set(found) != set(sections) or len(found) != len(parts[1::2]):
        raise PromptError(f"{Path(path).name}: needs exactly the sections {tuple(sections)}")
    return PromptFile(Path(path), GC.sha256_file(path), MappingProxyType(found))


def default_prompts() -> tuple[PromptFile, PromptFile]:
    return load_prompt(GEN_PROMPT, GEN_SECTIONS), load_prompt(AUDIT_PROMPT, AUDIT_SECTIONS)


def check_schemas() -> None:
    """The schemas reach the agent through --json-schema: they get the full check too."""
    for name, schema in (("GEN_SCHEMA", GEN_SCHEMA), ("AUDIT_SCHEMA", AUDIT_SCHEMA)):
        B.require(json.dumps(schema, ensure_ascii=False), name)


def item_json(item: Mapping[str, Any]) -> str:
    """The question as an agent sees it: ITEM_KEYS only, in order (never hidden flags or mech results)."""
    return json.dumps({k: item.get(k) for k in ITEM_KEYS}, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- issues (fix requests)
@dataclass(frozen=True)
class Issue:
    """One fix-request line; each part is ('tool', text) or ('agent', text) and is checked by its scope."""
    parts: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, *parts: tuple[str, str]) -> "Issue":
        for scope, text in parts:
            if scope not in ("tool", "agent") or not isinstance(text, str):
                raise PromptError(f"bad issue part {(scope, text)!r}")
        return cls(tuple(parts))

    @classmethod
    def tool(cls, text: str) -> "Issue":
        return cls.of(("tool", text))

    @classmethod
    def agent(cls, text: str) -> "Issue":
        return cls.of(("agent", text))

    @property
    def text(self) -> str:
        return "".join(t for _, t in self.parts)


def issues_text(issues: Sequence[Issue], where: str) -> str:
    for k, issue in enumerate(issues):
        for scope, text in issue.parts:
            B.require(text, f"{where} issue {k + 1}", "prompt" if scope == "tool" else "agent")
    return "\n".join(f"- {i.text}" for i in issues)


# ---------------------------------------------------------------- rendering
@dataclass(frozen=True)
class Rendered:
    """What one job sends: --system-prompt, the user prompt and --json-schema."""
    kind: str                                       # draft | fix | audit (g_common.JOB_CAP_USD keys)
    qid: str
    system: str
    user: str
    schema: Mapping[str, Any]
    prompt_file: str
    prompt_sha256: str
    section: str
    source: str | None = None                       # fix only: mech | audit | kay (never shown to the agent)
    values: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def render(pf: PromptFile, section: str, tool: Mapping[str, str], agent: Mapping[str, str]) -> str:
    """The section with every {{name}} replaced: tool values get the full check, agent values the memory check."""
    if section not in pf.sections or section == "system":
        raise PromptError(f"{pf.path.name} has no task section {section!r}")
    body = B.require(pf.sections[section], f"{pf.path.name}:{section}")
    names = set(_PLACEHOLDER.findall(body))
    if set(tool) & set(agent) or names != set(tool) | set(agent):
        raise PromptError(f"{pf.path.name}:{section} placeholders {sorted(names)} != values "
                          f"{sorted(set(tool) | set(agent))}")
    for k, v in tool.items():
        B.require(str(v), f"{pf.path.name}:{section}:{k}")
    for k, v in agent.items():
        B.require(str(v), f"{pf.path.name}:{section}:{k}", "agent")
    values = {**tool, **agent}
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), body)


def _system(pf: PromptFile) -> str:
    return B.require(pf.sections["system"], f"{pf.path.name}:system")


def _slot_values(spec: SlotSpec) -> dict[str, str]:
    return {"qid": spec.qid, "slot_id": spec.slot_id, "qtype": spec.qtype, "definition": spec.definition,
            "x": spec.x, "y": spec.y, "scope": spec.scope, "naming": spec.naming}


def _prompts(prompts: tuple[PromptFile, PromptFile] | None) -> tuple[PromptFile, PromptFile]:
    check_schemas()
    return prompts or default_prompts()


def render_writer(slot: Mapping[str, Any], names: Names, qid: str, slot_id: str | None = None,
                  prompts: tuple[PromptFile, PromptFile] | None = None) -> Rendered:
    """A new draft for one slot (gen_g.md task_new)."""
    gen, _ = _prompts(prompts)
    spec = slot_spec(slot, names, qid, slot_id)
    tool = _slot_values(spec)
    user = render(gen, "task_new", tool, {})
    return Rendered("draft", qid, _system(gen), user, GEN_SCHEMA, gen.path.name, gen.sha256, "task_new", None,
                    MappingProxyType(tool))


def render_audit(question: str, slot: Mapping[str, Any], qid: str, names: Names,
                 prompts: tuple[PromptFile, PromptFile] | None = None) -> Rendered:
    """A value-blind audit (audit_g.md task_audit): the question string and the slot's English definition only
    (on a marker slot with the namesake meant, ``SlotSpec.identity``)."""
    if not (isinstance(question, str) and question.strip()):
        raise PromptError("an audit is rendered from the question string only")
    _, audit = _prompts(prompts)
    spec = slot_spec(slot, names, qid)
    tool = {"qid": qid, "definition": spec.definition + spec.identity}
    user = render(audit, "task_audit", tool, {"question": question})
    return Rendered("audit", qid, _system(audit), user, AUDIT_SCHEMA, audit.path.name, audit.sha256, "task_audit",
                    None, MappingProxyType(tool))


def render_fix(source: str, slot: Mapping[str, Any], names: Names, qid: str, item: Mapping[str, Any],
               issues: Sequence[Issue], slot_id: str | None = None,
               prompts: tuple[PromptFile, PromptFile] | None = None) -> Rendered:
    """One fix round (gen_g.md task_fix) on this slot's own draft; the source is recorded, never shown."""
    if source not in SOURCES:
        raise PromptError(f"fix source {source!r} is not one of {SOURCES}")
    if not issues or not all(isinstance(i, Issue) for i in issues):
        raise PromptError("a fix needs at least one issue (prompts_g.Issue)")
    if not isinstance(item, Mapping):
        raise PromptError("a fix needs the slot's own draft item")
    gen, _ = _prompts(prompts)
    spec = slot_spec(slot, names, qid, slot_id)
    tool = _slot_values(spec)
    agent = {"issues": issues_text(issues, f"{qid} fix"), "item_json": item_json(item)}
    user = render(gen, "task_fix", tool, agent)
    return Rendered("fix", qid, _system(gen), user, GEN_SCHEMA, gen.path.name, gen.sha256, "task_fix", source,
                    MappingProxyType(tool))


def render_kay_revise(slot: Mapping[str, Any], names: Names, qid: str, item: Mapping[str, Any], note: str,
                      slot_id: str | None = None, prompts: tuple[PromptFile, PromptFile] | None = None) -> Rendered:
    """Kay's 「修改」 on the check page (prereg §3.7): a fix from source kay with Kay's note as agent text."""
    if not (isinstance(note, str) and note.strip()):
        raise PromptError("Kay's revise needs a note")
    return render_fix("kay", slot, names, qid, item, (Issue.agent(note),), slot_id, prompts)
