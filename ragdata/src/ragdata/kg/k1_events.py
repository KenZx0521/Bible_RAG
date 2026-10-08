"""K1, R2: compile ``config/registries/events.yaml`` (schema ``ragdata.events.v2``) against
the struct layer (design §2.21, §5.3; DOC 2 D6).

The registry declares each event's anchors as pericopes, in canon order and once each.
The compiler expands every pericope into all of its passages (struct order), so a
continuation passage comes with its pericope, and gives each anchor its passage's keys
and slots and its evidence: the pericope's ``heading_id``, or the quote the registry
declares (a pericope without a heading needs one). pdf_terms and external_aliases get
their provenance stamped (external aliases take the registry's defaults for a missing
source or note); a retired event becomes ``merged_from`` on the event it merged into.

Only what cannot be compiled is refused here; the content rules (names equal their
heading, a pdf_term lies inside an anchor, one owner per trigger) are G-EVENT's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import yaml

from ragcommon import books, ids
from ragdata.gates.base import Snapshot
from ragdata.kg.k1_contracts import V2_SCHEMA, events_report, v2_doc
from ragdata.kg.registries import registry_version
from ragdata.stages.errors import StageError

SCHEMA = "ragdata.events.v2"
VARIANT = "R2"
__all__ = ["SCHEMA", "V2_SCHEMA", "EventRegistryError", "EventsResult", "canon_order",
           "compile_events", "load_events_yaml"]
DOC_KEYS = frozenset({"schema", "variant", "decided_by", "external_alias_defaults", "retired",
                      "events"})
EVENT_KEYS = frozenset({"event_id", "legacy_ids", "name", "anchors", "pdf_terms",
                        "external_aliases"})
RETIRED_KEYS = frozenset({"event_id", "legacy_ids", "merged_into"})


class EventRegistryError(StageError):
    """The event registry cannot be compiled against the struct layer."""


@dataclass(frozen=True)
class EventsResult:
    rows: Mapping[str, list[dict[str, Any]]]
    v2: dict[str, Any]
    report: dict[str, Any]


def canon_order(raw: str) -> tuple[int, int, int, bool]:
    """Canon order of a key-based id (book, chapter, verse, second half)."""
    p = ids.parse(raw)
    return books.get_book(p.book_id).ord, p.chapter, p.verse, p.half


def load_events_yaml(path: Path | str) -> tuple[dict[str, Any], str]:
    """The registry document and its version (``events@`` the file's sha256[:12])."""
    try:
        data = Path(path).read_bytes()
        doc = yaml.safe_load(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise EventRegistryError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict):
        raise EventRegistryError(f"{path}: expected a mapping")
    return doc, registry_version("events", data)


def _keys(obj: Any, required: frozenset[str], where: str,
          optional: frozenset[str] = frozenset()) -> None:
    if not isinstance(obj, dict) or not required <= set(obj) <= required | optional:
        raise EventRegistryError(f"{where}: keys must be {sorted(required)}"
                                 + (f" and optionally {sorted(optional)}" if optional else ""))


def _lists(obj: Mapping[str, Any], names: Sequence[str], where: str) -> None:
    for name in names:
        if not isinstance(obj[name], list):
            raise EventRegistryError(f"{where}: {name} must be a list")


def _check_event(event: Any, where: str) -> None:
    _keys(event, EVENT_KEYS, where, frozenset({"name_heading_id"}))
    _lists(event, ("anchors", "pdf_terms", "external_aliases"), where)
    for term in event["pdf_terms"]:
        _keys(term, frozenset({"text", "at"}), f"{where}.pdf_terms")
    for alias in event["external_aliases"]:
        _keys(alias, frozenset({"text"}), f"{where}.external_aliases",
              frozenset({"source", "note"}))


def _check_doc(doc: Mapping[str, Any]) -> None:
    _keys(doc, DOC_KEYS, "events.yaml")
    if doc["schema"] != SCHEMA or doc["variant"] != VARIANT:
        raise EventRegistryError(f"events.yaml must be schema {SCHEMA}, variant {VARIANT}")
    _keys(doc["external_alias_defaults"], frozenset({"source", "note"}),
          "external_alias_defaults")
    _lists(doc, ("retired", "events"), "events.yaml")
    for i, retired in enumerate(doc["retired"]):
        _keys(retired, RETIRED_KEYS, f"retired[{i}]")
    for i, event in enumerate(doc["events"]):
        _check_event(event, f"events[{i}]")


# ------------------------------------------------------------------ anchors


def _declared(item: Any, where: str) -> tuple[str, dict[str, Any] | None]:
    """(pericope id, quote evidence or None) of one anchor declaration."""
    if isinstance(item, str):
        return item, None
    _keys(item, frozenset({"pericope", "quote"}), where)
    _keys(item["quote"], frozenset({"unit_key", "text"}), f"{where}.quote")
    return item["pericope"], {"heading_id": None, "quote": dict(item["quote"])}


def _evidence(pericope: Any, quote: dict[str, Any] | None, where: str) -> dict[str, Any]:
    if quote is not None:
        return quote
    if pericope.heading_id is None:
        raise EventRegistryError(f"{where}: {pericope.pericope_id} has no heading; declare a "
                                 "quote as its evidence")
    return {"heading_id": pericope.heading_id, "quote": None}


def _anchor(pericope: Any, ps: Any, evidence: dict[str, Any], decided_by: str) -> dict[str, Any]:
    return {"pericope_id": pericope.pericope_id, "passage_id": ps.passage_id,
            "start_key": ps.start_key, "end_key": ps.end_key, "start_slot": ps.start_slot,
            "end_slot": ps.end_slot, "evidence": evidence, "provenance_class": "curated_human",
            "decided_by": decided_by}


def _anchors(event: Mapping[str, Any], snapshot: Snapshot, decided_by: str
             ) -> list[dict[str, Any]]:
    pericopes, passages = snapshot.index("pericopes"), snapshot.index("passages")
    out: list[dict[str, Any]] = []
    previous = None
    for i, item in enumerate(event["anchors"]):
        where = f"{event['event_id']} anchors[{i}]"
        pericope_id, quote = _declared(item, where)
        pericope = pericopes.get(pericope_id)
        if pericope is None:
            raise EventRegistryError(f"{where}: {pericope_id} is not a struct-layer pericope")
        if previous is not None and canon_order(pericope_id) <= canon_order(previous):
            raise EventRegistryError(f"{where}: {pericope_id} after {previous}; declare pericopes "
                                     "in canon order, once each")
        previous = pericope_id
        evidence = _evidence(pericope, quote, where)
        out += [_anchor(pericope, passages[ps], evidence, decided_by)
                for ps in pericope.passage_ids]
    return out


# ------------------------------------------------------------------ events


def _triggers(event: Mapping[str, Any], doc: Mapping[str, Any]) -> dict[str, list]:
    defaults, by = doc["external_alias_defaults"], doc["decided_by"]
    return {
        "pdf_terms": [{"text": t["text"], "at": t["at"], "decided_by": by,
                       "provenance_class": "curated_human"} for t in event["pdf_terms"]],
        "external_aliases": [{"text": a["text"], "source": a.get("source", defaults["source"]),
                              "note": a.get("note", defaults["note"]),
                              "provenance_class": "external_event_alias"}
                             for a in event["external_aliases"]],
    }


def _merged(doc: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Retired events, by the event they merged into."""
    known = {e["event_id"] for e in doc["events"]}
    out: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(doc["retired"], key=lambda r: str(r["event_id"])):
        if r["merged_into"] not in known:
            raise EventRegistryError(f"retired {r['event_id']}: merged_into {r['merged_into']} "
                                     "names no event of the registry")
        out.setdefault(r["merged_into"], []).append(
            {"event_id": r["event_id"], "legacy_ids": list(r["legacy_ids"])})
    return out


def _event_row(event: Mapping[str, Any], doc: Mapping[str, Any], snapshot: Snapshot,
               merged: Sequence[dict[str, Any]]) -> dict[str, Any]:
    heading = event.get("name_heading_id")
    return {"event_id": event["event_id"], "legacy_ids": list(event["legacy_ids"]),
            "name": event["name"], "name_source": "curated" if heading is None else "pdf_heading",
            "name_heading_id": heading,
            "anchors": _anchors(event, snapshot, doc["decided_by"]), **_triggers(event, doc),
            "merged_from": list(merged), "decided_by": doc["decided_by"],
            "provenance_class": "curated_human"}


def compile_events(doc: Mapping[str, Any], snapshot: Snapshot, struct_version: str,
                   registry_version: str) -> EventsResult:
    """The events records, contract and report of the registry ``doc`` over ``snapshot``
    (text and struct records); ``registry_version`` names the yaml's bytes."""
    _check_doc(doc)
    merged = _merged(doc)
    events = [_event_row(e, doc, snapshot, merged.get(e["event_id"], ())) for e in doc["events"]]
    return EventsResult(MappingProxyType({"events": events}), v2_doc(events, struct_version),
                        events_report(events, struct_version, registry_version))
