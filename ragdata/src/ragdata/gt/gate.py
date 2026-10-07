"""G-GT (design §8): GT v2 against its slot universe, v1, its change log and its freeze.

Every check is hard and fails closed when its input is missing:

``G-GT.refs``     every ``reference`` parses in strict mode, and ``refs`` is that
                  parse in structured form ({book_id, ch, v_start, v_end, ch_end}).
``G-GT.gold``     the header's slot_universe is the given layer; gold_slots and
                  omitted_slots are the reference's expansion split by slot status
                  (gold non-empty, all present/merged; omitted all omitted_variant).
``G-GT.quote``    every clause inside 「」/『』 of an answer field is service text
                  (text_pdf accepted at errata), except the header's quote_exempt,
                  each of which must still match something.
``G-GT.spelling`` no answer field uses a form of ``forms.FORMS`` (question text is
                  exempt), and the service text uses none of them either.
``G-GT.v1``       same questions in the same order as v1, question_id, question,
                  question_type, book_name and reference unchanged; v1's sha256 is
                  the one in the header.
``G-GT.changes``  the change log is the header's (sha256, count), uses known rules,
                  turns v1 into v2 and v2 back into v1.
``G-GT.freeze``   the freeze record names this exact file and slot universe.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ragcommon import books
from ragcommon.refs import RefParseError, parse_refs
from ragcommon.versification import Versification
from ragdata.gates.base import GateResult, violations_result
from ragdata.gt.build import DERIVED_FIELDS, FIXED_FIELDS, RULES, answer_fields, sha256
from ragdata.gt.changes import Change, ChangeError, apply_changes, get_field, revert_changes
from ragdata.gt.corpus import GOLD_STATUSES, OMITTED_STATUS, ServiceText
from ragdata.gt.forms import FORMS, find_forms
from ragdata.gt.goldrefs import REF_KEYS, GoldError, derive_gold
from ragdata.gt.textnorm import QuoteError, norm, quote_clause_spans

REPORT_SCHEMA = "ragdata.gt_gate_report.v1"
FREEZE_SCHEMA = "ragdata.gt_v2_freeze.v1"
GT_PATH = "ground_truth.v2.json"


@dataclass(frozen=True)
class GtInputs:
    doc: Mapping[str, Any]
    corpus: ServiceText
    vers: Versification
    v1_doc: Mapping[str, Any] | None = None
    v1_sha256: str | None = None
    changes: Sequence[Change] | None = None
    changes_sha256: str | None = None
    freeze: Mapping[str, Any] | None = None
    v2_sha256: str | None = None


@dataclass(frozen=True)
class GtReport:
    slot_universe: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates if g.hard)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "slot_universe": self.slot_universe, "pass": self.passed,
                "gates": [g.to_json() for g in self.gates]}


def _missing(name: str, what: str) -> GateResult:
    return GateResult(name, hard=True, passed=False, observed="missing input", expected=what,
                      details=(f"{name} needs {what}",))


def _questions(inputs: GtInputs) -> list[Mapping[str, Any]]:
    return list(inputs.doc["questions"])


def _ref_shape(refs: Any) -> str | None:
    if not isinstance(refs, list) or not refs:
        return "refs is not a non-empty list"
    for ref in refs:
        if not isinstance(ref, dict) or tuple(sorted(ref)) != tuple(sorted(REF_KEYS)):
            return f"ref {ref!r} does not have exactly {REF_KEYS}"
        if not books.is_book_id(ref["book_id"]) or not all(
                isinstance(ref[k], int) and not isinstance(ref[k], bool) for k in ("ch", "ch_end")):
            return f"ref {ref!r}: bad book_id or chapter"
        verses = (ref["v_start"], ref["v_end"])
        if not (verses == (None, None) or all(isinstance(v, int) for v in verses)):
            return f"ref {ref!r}: v_start and v_end must both be null or both integers"
    return None


def check_refs(inputs: GtInputs) -> GateResult:
    bad, parsed = [], 0
    for q in _questions(inputs):
        qid = q["question_id"]
        shape = _ref_shape(q.get("refs"))
        try:
            refs = parse_refs(q["reference"], strict=True, versification=inputs.vers).to_dicts()
            parsed += 1
        except RefParseError as exc:
            bad.append(f"{qid}: strict parse fails: {exc}")
            continue
        if shape:
            bad.append(f"{qid}: {shape}")
        elif [{k: r[k] for k in REF_KEYS} for r in refs] != q["refs"]:
            bad.append(f"{qid}: refs {q['refs']} != strict parse {refs}")
    result = violations_result("G-GT.refs", bad)
    total = len(_questions(inputs))
    return GateResult(result.name, True, result.passed and parsed == total,
                      {**result.observed, "parsed": f"{parsed}/{total}"}, result.expected,
                      result.details)


def _gold_violations(q: Mapping[str, Any], corpus: ServiceText, vers: Versification) -> list[str]:
    qid = q["question_id"]
    try:
        expected = derive_gold(q["reference"], corpus, vers)
    except (RefParseError, GoldError) as exc:
        return [f"{qid}: {exc}"]
    gold, omitted = q.get("gold_slots"), q.get("omitted_slots")
    out = []
    if not gold or any(corpus.slot_status.get(s) not in GOLD_STATUSES for s in gold):
        out.append(f"{qid}: gold_slots empty or not all present/merged slots")
    if any(corpus.slot_status.get(s) != OMITTED_STATUS for s in omitted or []):
        out.append(f"{qid}: omitted_slots holds a slot that is not omitted_variant")
    if (gold, omitted) != (list(expected.gold_slots), list(expected.omitted_slots)):
        out.append(f"{qid}: gold/omitted {gold}/{omitted} != expansion "
                   f"{list(expected.gold_slots)}/{list(expected.omitted_slots)}")
    return out


def check_gold(inputs: GtInputs) -> GateResult:
    bad = []
    universe = inputs.doc["metadata"].get("slot_universe")
    if universe != inputs.corpus.version:
        bad.append(f"slot_universe {universe} is not the given layer {inputs.corpus.version}")
    for q in _questions(inputs):
        bad += _gold_violations(q, inputs.corpus, inputs.vers)
    return violations_result("G-GT.gold", bad)


def _answers(inputs: GtInputs):
    for q in _questions(inputs):
        for name in answer_fields(q):
            yield q["question_id"], name, get_field(q, name)


def check_quotes(inputs: GtInputs) -> GateResult:
    exempt = {(e["qid"], e["field"], e["quote"]) for e in inputs.doc["metadata"].get(
        "quote_exempt", [])}
    used, bad = set(), []
    for qid, name, value in _answers(inputs):
        try:
            spans = quote_clause_spans(value)
        except QuoteError as exc:
            bad.append(f"{qid} {name}: {exc}")
            continue
        for span in spans:
            clause = norm(span.text)
            if not clause or inputs.corpus.contains(clause):
                continue
            if (qid, name, span.text) in exempt:
                used.add((qid, name, span.text))
            else:
                bad.append(f"{qid} {name}: 「{span.text}」 is not service text")
    bad += [f"quote_exempt {e} matches nothing" for e in sorted(exempt - used)]
    return violations_result("G-GT.quote", bad)


def check_spelling(inputs: GtInputs) -> GateResult:
    bad = [f"{qid} {name}: {m.group()!r} (corpus writes {form.corpus_form!r})"
           for qid, name, value in _answers(inputs) for form, m in find_forms(value)]
    bad += [f"service text writes {m.group()!r}: forms entry {form.pattern!r} is wrong"
            for form, m in find_forms(inputs.corpus.raw, FORMS)]
    return violations_result("G-GT.spelling", bad)


def check_v1(inputs: GtInputs) -> GateResult:
    if inputs.v1_doc is None or inputs.v1_sha256 is None:
        return _missing("G-GT.v1", "ground_truth.json (v1) and its sha256")
    bad = []
    if inputs.doc["metadata"].get("v1", {}).get("sha256") != inputs.v1_sha256:
        bad.append(f"header v1 sha256 is not {inputs.v1_sha256}")
    v1q, v2q = inputs.v1_doc["questions"], _questions(inputs)
    if [q["question_id"] for q in v1q] != [q["question_id"] for q in v2q]:
        bad.append(f"question ids or order differ ({len(v1q)} in v1, {len(v2q)} in v2)")
    else:
        bad += [f"{a['question_id']}: {f} changed" for a, b in zip(v1q, v2q)
                for f in FIXED_FIELDS if a.get(f) != b.get(f)]
    return violations_result("G-GT.v1", bad)


def _without_derived(questions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{k: copy.deepcopy(v) for k, v in q.items() if k not in DERIVED_FIELDS}
            for q in questions]


def _replay(v1q, v2q, changes) -> list[str]:
    try:
        forward = apply_changes(v1q, changes)
        backward = revert_changes(v2q, changes)
    except ChangeError as exc:
        return [f"change log does not replay: {exc}"]
    out = []
    if forward != v2q:
        out += [f"{b['question_id']}: replaying v1 does not give v2"
                for a, b in zip(forward, v2q) if a != b] or ["replaying v1 does not give v2"]
    if backward != _without_derived(v1q):
        out.append("reverting v2 does not give v1")
    return out


def check_changes(inputs: GtInputs) -> GateResult:
    if inputs.v1_doc is None or inputs.changes is None or inputs.changes_sha256 is None:
        return _missing("G-GT.changes", "v1, the change log and its sha256")
    header = inputs.doc["metadata"].get("changes", {})
    bad = []
    if (header.get("sha256"), header.get("count")) != (inputs.changes_sha256, len(inputs.changes)):
        bad.append(f"header changes {header.get('sha256')}/{header.get('count')} != log "
                   f"{inputs.changes_sha256}/{len(inputs.changes)}")
    bad += [f"unknown rule {c.rule!r} ({c.qid})" for c in inputs.changes if c.rule not in RULES]
    bad += _replay(inputs.v1_doc["questions"], _without_derived(_questions(inputs)),
                   inputs.changes)
    return violations_result("G-GT.changes", bad)


def freeze_record(doc: Mapping[str, Any], v2_bytes: bytes) -> dict[str, Any]:
    meta = doc["metadata"]
    return {"schema": FREEZE_SCHEMA, "gt_path": GT_PATH, "sha256": sha256(v2_bytes),
            "slot_universe": meta["slot_universe"], "v1_sha256": meta["v1"]["sha256"],
            "changes_sha256": meta["changes"]["sha256"],
            "generator_git_sha": meta["generator"].get("git_sha"),
            "note": ("GT v2 凍結點：本檔所在的 commit。評估前比對 sha256；slot_universe 是答案對齊與"
                     "覆蓋計算的節位宇集。")}


def check_freeze(inputs: GtInputs) -> GateResult:
    if inputs.freeze is None or inputs.v2_sha256 is None:
        return _missing("G-GT.freeze", "config/gold/gt_v2_freeze.json and the v2 sha256")
    meta = inputs.doc["metadata"]
    expected = {"schema": FREEZE_SCHEMA, "sha256": inputs.v2_sha256,
                "slot_universe": meta.get("slot_universe"),
                "v1_sha256": meta.get("v1", {}).get("sha256"),
                "changes_sha256": meta.get("changes", {}).get("sha256")}
    bad = [f"freeze {k} is {inputs.freeze.get(k)!r}, expected {v!r}"
           for k, v in expected.items() if inputs.freeze.get(k) != v]
    return violations_result("G-GT.freeze", bad)


CHECKS: tuple[Callable[[GtInputs], GateResult], ...] = (
    check_refs, check_gold, check_quotes, check_spelling, check_v1, check_changes, check_freeze)


def check_gt(inputs: GtInputs) -> GtReport:
    return GtReport(inputs.corpus.version, tuple(check(inputs) for check in CHECKS))
