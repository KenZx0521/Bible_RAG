"""G-EVENT, R2 rules: the curated event registry (design §8, §2.21, §5.3; DOC 1 §4).

1. ids: event ids ascend; together with the retired (``merged_from``) ids they are
   exactly ``ev0001…evN``, without overlap; a legacy id belongs to one event;
2. anchors: decided by kay; keys and slots are their passage's, ``pericope_id`` is the
   passage's pericope; the evidence is that pericope's heading (or section heading), or
   a quote from one of its units; anchors in canon order (so no fragment heading can
   stand in as evidence);
3. pericope completeness: an event that anchors one passage of a pericope anchors all;
4. name: a ``pdf_heading`` name is the text of its heading, and that heading is one of
   the anchors' evidence or section headings;
5. pdf_terms: decided by kay; ``at`` (a heading's anchor unit, or the unit) lies inside an
   anchor passage, and the text is a substring of ``text`` or ``text_pdf`` there;
6. external_aliases: a non-blank source and note;
7. triggers: no Latin letters, at least two characters, one owner event each;
8. the contract file is the records projected (``k1_contracts.v2_doc``).

No ``external_legacy`` or ``legacy_tuned`` can reach this gate: every ``provenance_class``
of an events row is fixed by its record contract (``contract.kg``), so G-SCHEMA refuses
them, and rule 8 holds the contract file to the records. An empty registry, and an event
without triggers, are legal.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.contract import record_to_dict
from ragdata.gates.base import GateResult, Snapshot, violations_result
from ragdata.kg.k1_contracts import v2_doc
from ragdata.kg.k1_events import canon_order

NAME = "G-EVENT"
DECIDER = "kay"
LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Refs:
    """The text and struct records the checks read."""

    passages: Mapping[str, Any]
    pericopes: Mapping[str, Any]
    headings: Mapping[str, Any]
    units: Mapping[str, Any]

    @classmethod
    def of(cls, snapshot: Snapshot) -> Refs:
        return cls(*(snapshot.index(n) for n in ("passages", "pericopes", "headings",
                                                  "verse_units")))

    def unit_keys(self, passage_ids: Sequence[str]) -> set[str]:
        return {u.unit_key for p in passage_ids if p in self.passages
                for u in self.passages[p].unit_refs}


def _quoted(text: str, record: Any) -> bool:
    return text in record.text or text in record.text_pdf


def _id_checks(events: Sequence[Any]) -> list[str]:
    own = [e.event_id for e in events]
    every = own + [m.event_id for e in events for m in e.merged_from]
    out = [] if own == sorted(own) else ["event ids do not ascend"]
    out += [f"{i} is listed {n} times (events and retired)" for i, n in Counter(every).items()
            if n > 1]
    expected = {ids.event_id(n) for n in range(1, len(every) + 1)}
    if set(every) != expected:
        out.append(f"event and retired ids are not ev0001…{ids.event_id(len(every))}: missing "
                   f"{sorted(expected - set(every))}, extra {sorted(set(every) - expected)}")
    legacy = Counter(i for e in events for i in e.legacy_ids)
    return out + [f"legacy id {i} belongs to {n} events" for i, n in legacy.items() if n > 1]


def _evidence_checks(a: Any, refs: Refs, where: str) -> list[str]:
    pericope = refs.pericopes.get(a.pericope_id)
    if pericope is None:
        return [f"{where}: no pericope {a.pericope_id}"]
    heading, quote = a.evidence.heading_id, a.evidence.quote
    if heading is not None:
        own = {pericope.heading_id, pericope.section_heading_id} - {None}
        return [] if heading in own else [f"{where}: evidence {heading} is not a heading of "
                                          f"{a.pericope_id}"]
    if quote.unit_key not in refs.unit_keys(pericope.passage_ids):
        return [f"{where}: quoted unit {quote.unit_key} is not in {a.pericope_id}"]
    unit = refs.units.get(quote.unit_key)
    return [] if unit is not None and _quoted(quote.text, unit) else [
        f"{where}: quote {quote.text!r} is not in {quote.unit_key}"]


def _anchor_checks(event: Any, refs: Refs) -> list[str]:
    out = []
    for a in event.anchors:
        where = f"{event.event_id} {a.passage_id}"
        if a.decided_by != DECIDER:
            out.append(f"{where}: decided_by {a.decided_by!r}, not {DECIDER}")
        ps = refs.passages.get(a.passage_id)
        if ps is None:
            out.append(f"{where}: no such passage")
            continue
        if (a.start_key, a.end_key, a.start_slot, a.end_slot) != (
                ps.start_key, ps.end_key, ps.start_slot, ps.end_slot):
            out.append(f"{where}: keys and slots are not its passage's")
        if a.pericope_id != ps.pericope_id:
            out.append(f"{where}: pericope_id {a.pericope_id} is not {ps.pericope_id}")
        out += _evidence_checks(a, refs, where)
    order = [canon_order(a.start_key) for a in event.anchors]
    return out + ([] if order == sorted(order) else [f"{event.event_id}: anchors are not in "
                                                     "canon order"])


def _completeness(event: Any, refs: Refs) -> list[str]:
    held: dict[str, set[str]] = defaultdict(set)
    for a in event.anchors:
        held[a.pericope_id].add(a.passage_id)
    out = []
    for pericope_id, passages in held.items():
        pericope = refs.pericopes.get(pericope_id)
        missing = [] if pericope is None else [p for p in pericope.passage_ids
                                               if p not in passages]
        if missing:
            out.append(f"{event.event_id}: anchors {pericope_id} but not its passages {missing}")
    return out


def _name_checks(event: Any, refs: Refs) -> list[str]:
    heading_id = event.name_heading_id
    if heading_id is None:
        return []
    heading, out = refs.headings.get(heading_id), []
    if heading is None or heading.text != event.name:
        out.append(f"{event.event_id}: name {event.name!r} is not the text of {heading_id}")
    own = {a.evidence.heading_id for a in event.anchors} | {
        refs.pericopes[a.pericope_id].section_heading_id for a in event.anchors
        if a.pericope_id in refs.pericopes}
    if heading_id not in own:
        out.append(f"{event.event_id}: {heading_id} is not a heading of its anchors")
    return out


def _term_checks(event: Any, refs: Refs) -> list[str]:
    inside = refs.unit_keys([a.passage_id for a in event.anchors])
    out = []
    for t in event.pdf_terms:
        where = f"{event.event_id} pdf_term {t.text!r}"
        if t.decided_by != DECIDER:
            out.append(f"{where}: decided_by {t.decided_by!r}, not {DECIDER}")
        heading = t.at.startswith("hd:")
        source = (refs.headings if heading else refs.units).get(t.at)
        if source is None:
            out.append(f"{where}: {t.at} is not in the text layer")
            continue
        if (source.anchor_unit_key if heading else t.at) not in inside:
            out.append(f"{where}: {t.at} lies outside the event's anchors")
        if not _quoted(t.text, source):
            out.append(f"{where}: not a substring of {t.at}")
    return out


def _alias_checks(event: Any) -> list[str]:
    return [f"{event.event_id} external alias {a.text!r}: blank source or note"
            for a in event.external_aliases if not a.source.strip() or not a.note.strip()]


def _trigger_checks(events: Sequence[Any]) -> list[str]:
    owners: dict[str, list[str]] = defaultdict(list)
    out = []
    for e in events:
        for text in e.triggers:
            owners[text].append(e.event_id)
            if LATIN.search(text) or len(text) < 2:
                out.append(f"{e.event_id}: trigger {text!r} has Latin letters or one character")
    return out + [f"trigger {t!r} belongs to {', '.join(evs)}" for t, evs in owners.items()
                  if len(evs) > 1]


def check_event(snapshot: Snapshot, v2: Mapping[str, Any], struct_version: str) -> GateResult:
    """``snapshot`` holds text, struct and events records; ``v2`` the layer's contract file;
    ``struct_version`` the struct layer the events layer was built on."""
    events, refs = snapshot.of("events"), Refs.of(snapshot)
    violations = _id_checks(events) + _trigger_checks(events)
    for event in events:
        violations += _anchor_checks(event, refs) + _completeness(event, refs)
        violations += _name_checks(event, refs) + _term_checks(event, refs)
        violations += _alias_checks(event)
    if v2 != v2_doc([record_to_dict(e) for e in events], struct_version):
        violations.append("event_registry_v2.json does not follow the event records")
    return violations_result(NAME, violations)
