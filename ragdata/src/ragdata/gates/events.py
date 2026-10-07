"""G-EVENT, R1 rules: the frozen event registry (design §8, §2.21, §5.3).

- events are numbered ``ev0001…`` without gaps; each has at least one anchor (its PDF
  evidence) and keeps every legacy trigger;
- every anchor resolves to a valid slot range that is exactly its passage, and is
  ``legacy_tuned``; R1 has no ``pdf_terms`` and no ``external_aliases``;
- the change list holds exactly the anchors that are not ``same``;
- both contract files follow the records;
- frozen: event for event, the records reproduce the legacy registry — names, sources,
  triggers in order, and every legacy anchor mapped through ``legacy_ids`` to the
  record's passage, in order. Without the legacy registry this check fails closed.

R2 adds the checks on ``pdf_terms`` (Kay-approved PDF substrings with an anchor verse),
``external_aliases`` (source and note) and fragment headings; they do not apply to R1.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.contract import record_to_dict
from ragdata.gates.base import GateResult, Snapshot, violations_result
from ragdata.kg.k1_contracts import v1_events, v2_doc
from ragdata.kg.k1_events import EventRegistryError, convert_anchor, legacy_map

NAME = "G-EVENT"


def _order(slot: str) -> tuple[int, int]:
    p = ids.parse(slot)
    return p.chapter, p.verse


def _anchor_checks(event: Any, slots: Mapping[str, Any], passages: Mapping[str, Any]) -> list[str]:
    out = []
    for a in event.anchors:
        where = f"{event.event_id} {a.passage_id}"
        if a.start_slot not in slots or a.end_slot not in slots \
                or _order(a.start_slot) > _order(a.end_slot):
            out.append(f"{where}: {a.start_slot}–{a.end_slot} is not a valid slot range")
        ps = passages.get(a.passage_id)
        if ps is None or (ps.start_key, ps.end_key) != (a.start_key, a.end_key):
            out.append(f"{where}: anchor keys are not its passage's")
        if a.provenance_class != "legacy_tuned":
            out.append(f"{where}: R1 anchors are legacy_tuned, not {a.provenance_class}")
    return out


def _event_checks(snapshot: Snapshot) -> list[str]:
    events, out = snapshot.of("events"), []
    slots, passages = snapshot.index("verse_slots"), snapshot.index("passages")
    for n, event in enumerate(events, start=1):
        if event.event_id != ids.event_id(n):
            out.append(f"events[{n - 1}]: {event.event_id} breaks the ev0001… numbering")
        if not event.legacy_triggers:
            out.append(f"{event.event_id}: R1 keeps the legacy triggers; none left")
        if event.pdf_terms or event.external_aliases:
            out.append(f"{event.event_id}: R1 has no pdf_terms or external_aliases")
        out += _anchor_checks(event, slots, passages)
    expected = {(e.event_id, a.legacy_anchor, a.passage_id, a.change)
                for e in events for a in e.anchors if a.change != "same"}
    listed = {(c.event_id, c.legacy_anchor, c.passage_id, c.change)
              for c in snapshot.of("anchor_changes")}
    out += [f"anchor_changes: {c} is not listed" for c in sorted(expected - listed)]
    out += [f"anchor_changes: {c} is not a changed anchor" for c in sorted(listed - expected)]
    return out


def _contract_checks(events: Sequence[dict[str, Any]], v1: Mapping[str, Any],
                     v2: Mapping[str, Any], struct_version: str) -> list[str]:
    out = []
    if v2 != v2_doc(events, struct_version):
        out.append("event_registry_v2.json does not follow the event records")
    if v1.get("version") != 1 or v1.get("events") != v1_events(events):
        out.append("event_registry_v1.json does not follow the event records")
    return out


def _frozen_event(raw: Mapping[str, Any], event: Mapping[str, Any], lmap: Any) -> list[str]:
    where = f"{event['event_id']} ({raw.get('id')})"
    same = (raw.get("id"), raw.get("name"), raw.get("provenance"), raw.get("triggers")) == (
        event["legacy_id"], event["name"], event["legacy_provenance"],
        [t["text"] for t in event["legacy_triggers"]])
    out = [] if same else [f"{where}: id, name, provenance or triggers differ from the legacy"]
    try:
        mapped = [(a, convert_anchor(a, lmap)["passage_id"]) for a in raw.get("anchors", [])]
    except EventRegistryError as exc:
        return [*out, f"{where}: {exc}"]
    if mapped != [(a["legacy_anchor"], a["passage_id"]) for a in event["anchors"]]:
        out.append(f"{where}: anchors are not the legacy anchors mapped through legacy_ids")
    return out


def _frozen_checks(snapshot: Snapshot, events: Sequence[dict[str, Any]],
                   legacy: bytes | None) -> list[str]:
    if legacy is None:
        return ["frozen check needs the legacy registry (backend/data/event_registry.json)"]
    try:
        raw_events = json.loads(legacy.decode("utf-8"))["events"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        return ["the legacy registry is unreadable"]
    if len(raw_events) != len(events):
        return [f"{len(events)} events, the legacy registry has {len(raw_events)}"]
    lmap = legacy_map(snapshot)
    return [v for raw, event in zip(raw_events, events) for v in _frozen_event(raw, event, lmap)]


def check_event(snapshot: Snapshot, v1: Mapping[str, Any], v2: Mapping[str, Any],
                legacy: bytes | None, struct_version: str) -> GateResult:
    """``snapshot`` holds text, struct and events records; ``v1``/``v2`` the layer's contract
    files; ``legacy`` the bytes of the legacy registry the layer was frozen from."""
    events = [record_to_dict(e) for e in snapshot.of("events")]
    violations = [] if events else ["the layer holds no events"]
    violations += _event_checks(snapshot)
    violations += _contract_checks(events, v1, v2, struct_version)
    violations += _frozen_checks(snapshot, events, legacy)
    return violations_result(NAME, violations)
