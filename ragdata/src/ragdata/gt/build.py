"""Derive GT v2 from v1, a text layer and the curated decisions (design §11.3).

Per question: structured refs and gold/omitted slots from the strict parser,
then the answer fields go through ``STAGES`` in order; each stage's edits are
logged as changes (see ``changes``), so the log replays v1 into v2. Question,
question_id, question_type, book_name and reference are copied unchanged;
legacy questions get ``family: legacy_head`` (logged too). The result is a pure
function of its inputs: the same inputs give the same bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from ragcommon.refs import RefParseError
from ragcommon.versification import Versification
from ragdata.gt import rules
from ragdata.gt.changes import POINTS, Change, Edit, apply_edits, get_field, set_field
from ragdata.gt.corpus import ServiceText
from ragdata.gt.curated import Curated, QuoteFix
from ragdata.gt.forms import CUNP, ORTHO
from ragdata.gt.goldrefs import GoldError, GoldRefs, derive_gold
from ragdata.gt.mechanical import mechanical_edits
from ragdata.gt.textnorm import clause_spans, norm

GT_VERSION = "v2"
LEGACY_FAMILY = "legacy_head"
FIXED_FIELDS = ("question_id", "question", "question_type", "book_name", "reference")
DERIVED_FIELDS = ("refs", "gold_slots", "omitted_slots")
STAGES = ("errata_word", "mechanical_clause", "cunp_gloss", CUNP, ORTHO, "interpunct",
          "quote_original")
FAMILY_RULE = "legacy_family"
RULES = (*STAGES, FAMILY_RULE)


class BuildError(ValueError):
    """The inputs do not yield a GT v2."""


@dataclass(frozen=True)
class Provenance:
    """What the v2 header records about how it was made."""

    v1: Mapping[str, str]                    # {"path", "sha256"}
    generator: Mapping[str, Any]             # {"command", "git_sha", "files": {path: blob sha}}
    curated: Mapping[str, str]               # {"path", "sha256"}
    changes_path: str


@dataclass(frozen=True)
class BuildResult:
    doc: dict[str, Any]
    changes: tuple[Change, ...]
    changes_bytes: bytes = field(repr=False, default=b"")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_doc(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def encode_changes(changes: Sequence[Change]) -> bytes:
    lines = [json.dumps(c.to_json(), ensure_ascii=False, sort_keys=True) for c in changes]
    return "".join(line + "\n" for line in lines).encode("utf-8")


def answer_fields(question: Mapping[str, Any]) -> list[str]:
    return ["reference_answer"] + [f"{POINTS}[{i}]" for i in range(len(question[POINTS]))]


class _FixBook:
    """Curated quote fixes by (qid, field); each must be used exactly once."""

    def __init__(self, corpus: ServiceText, fixes: Sequence[QuoteFix]):
        self._fixes: dict[tuple[str, str], list[QuoteFix]] = {}
        for fix in fixes:
            bad = [c.text for c in clause_spans(fix.after)
                   if not corpus.contains(norm(c.text), accept_pdf=False)]
            if bad or fix.evidence_slot not in corpus.slot_status:
                raise BuildError(f"quote fix {fix.qid} {fix.field}: not service text {bad} "
                                 f"or unknown slot {fix.evidence_slot}")
            self._fixes.setdefault((fix.qid, fix.field), []).append(fix)
        self.used: set[QuoteFix] = set()

    def edits(self, qid: str, field_name: str, value: str) -> list[Edit]:
        out = []
        for fix in self._fixes.get((qid, field_name), []):
            if value.count(fix.before) != 1:
                raise BuildError(f"quote fix {qid} {field_name}: {fix.before!r} occurs "
                                 f"{value.count(fix.before)} times")
            start = value.index(fix.before)
            out.append(Edit(start, start + len(fix.before), fix.after, fix.evidence_slot))
            self.used.add(fix)
        return out

    def unused(self) -> list[QuoteFix]:
        return [f for fixes in self._fixes.values() for f in fixes if f not in self.used]


def _stage_edits(stage: str, corpus: ServiceText, gold: Sequence[str], local: str,
                 fixes: _FixBook, qid: str) -> Callable[[str, str], list[Edit]]:
    table: dict[str, Callable[[str, str], list[Edit]]] = {
        "errata_word": lambda f, v: rules.errata_edits(v, corpus, gold),
        "mechanical_clause": lambda f, v: mechanical_edits(v, corpus, gold, local),
        "cunp_gloss": lambda f, v: rules.gloss_edits(v),
        CUNP: lambda f, v: rules.form_edits(v, corpus, CUNP, gold),
        ORTHO: lambda f, v: rules.form_edits(v, corpus, ORTHO, gold),
        "interpunct": lambda f, v: rules.interpunct_edits(v, corpus, gold),
        "quote_original": lambda f, v: fixes.edits(qid, f, v),
    }
    return table[stage]


def _align(question: dict[str, Any], gold: GoldRefs, corpus: ServiceText,
           fixes: _FixBook) -> list[Change]:
    qid = question["question_id"]
    changes: list[Change] = []
    local = corpus.local(gold.gold_slots)
    for stage in STAGES:
        edits_of = _stage_edits(stage, corpus, gold.gold_slots, local, fixes, qid)
        for name in answer_fields(question):
            value = get_field(question, name)
            new, logged = apply_edits(qid, name, value, edits_of(name, value), rule=stage)
            set_field(question, name, new)
            changes += logged
    return changes


def _gold_all(questions: Sequence[Mapping[str, Any]], corpus: ServiceText,
              vers: Versification) -> dict[str, GoldRefs]:
    out, failed = {}, []
    for q in questions:
        try:
            out[q["question_id"]] = derive_gold(q["reference"], corpus, vers)
        except (RefParseError, GoldError) as exc:
            failed.append(f"{q['question_id']}: {exc}")
    if failed:
        raise BuildError(f"{len(failed)} references fail the strict parser:\n" + "\n".join(failed))
    return out


def _question(v1q: Mapping[str, Any], gold: GoldRefs, corpus: ServiceText,
              fixes: _FixBook) -> tuple[dict[str, Any], list[Change]]:
    question = copy.deepcopy(dict(v1q))
    changes = _align(question, gold, corpus, fixes)
    if "family" not in question:
        question["family"] = LEGACY_FAMILY
        changes.append(Change(question["question_id"], "family", None, None, LEGACY_FAMILY,
                              FAMILY_RULE, None))
    question.update(refs=[dict(r) for r in gold.refs], gold_slots=list(gold.gold_slots),
                    omitted_slots=list(gold.omitted_slots))
    return question, changes


def _metadata(v1_meta: Mapping[str, Any], corpus: ServiceText, curated: Curated,
              prov: Provenance, changes: Sequence[Change], changes_bytes: bytes) -> dict:
    meta = copy.deepcopy(dict(v1_meta))
    meta.update({
        "gt_version": GT_VERSION,
        "slot_universe": corpus.version,
        "v2_note": ("答案欄位（reference_answer、expected_answer_points）對齊 slot_universe 的 "
                    "verse_units.text；題目、question_type、book_name、reference 與 v1 相同。"
                    "refs 由 ragcommon.refs strict 解析 reference 導出；gold_slots 是有經文的節位，"
                    "omitted_slots 是只見於異文註腳的缺號槽，不算 gold。逐筆修改見 changes。"),
        "v1": dict(prov.v1),
        "generator": dict(prov.generator),
        "curated": dict(prov.curated),
        "changes": {"path": prov.changes_path, "sha256": sha256(changes_bytes),
                    "count": len(changes),
                    "by_rule": dict(sorted(Counter(c.rule for c in changes).items()))},
        "quote_exempt": [vars(e) for e in curated.quote_exempt],
        "kay_review": [vars(k) for k in curated.kay_review],
    })
    return meta


def build_v2(v1_doc: Mapping[str, Any], corpus: ServiceText, vers: Versification,
             curated: Curated, prov: Provenance) -> BuildResult:
    questions = v1_doc["questions"]
    golds = _gold_all(questions, corpus, vers)
    fixes = _FixBook(corpus, curated.quote_fixes)
    out, changes = [], []
    for v1q in questions:
        question, logged = _question(v1q, golds[v1q["question_id"]], corpus, fixes)
        out.append(question)
        changes += logged
    if fixes.unused():
        raise BuildError(f"quote fixes never applied: {fixes.unused()}")
    changes_bytes = encode_changes(changes)
    meta = _metadata(v1_doc["metadata"], corpus, curated, prov, changes, changes_bytes)
    return BuildResult({"metadata": meta, "questions": out}, tuple(changes), changes_bytes)
