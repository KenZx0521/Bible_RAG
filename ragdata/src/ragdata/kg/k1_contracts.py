"""The events layer's contract file and report (design §2.21, §7.5; R2 contract spec §2).

``event_registry_v2.json`` (copied to ``contracts/<build>/event_registry.json``) is the
records projected: per event its ids, name, passage-level anchors and triggers; a
retired event is listed once at the top level with the event it merged into. The
records' ``merged_from`` and the event-level ``decided_by`` and ``provenance_class`` are
left out.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

V2_SCHEMA = "ragdata.event_registry.v2"
VARIANT = "R2"
EVENT_KEYS = ("event_id", "legacy_ids", "name", "name_source", "name_heading_id", "anchors",
              "pdf_terms", "external_aliases")


def retired(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [{**m, "merged_into": e["event_id"]} for e in events for m in e["merged_from"]]
    return sorted(rows, key=lambda r: r["event_id"])


def v2_doc(events: Sequence[Mapping[str, Any]], struct_version: str) -> dict[str, Any]:
    return {"schema": V2_SCHEMA, "variant": VARIANT, "struct": struct_version,
            "events": [{k: e[k] for k in EVENT_KEYS} for e in events],
            "retired": retired(events)}


def _expanded(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pericopes whose expansion took in more than one passage (continuations)."""
    out = []
    for e in events:
        by_pericope: dict[str, list[str]] = {}
        for a in e["anchors"]:
            by_pericope.setdefault(a["pericope_id"], []).append(a["passage_id"])
        out += [{"event_id": e["event_id"], "pericope_id": pc, "passage_ids": ps}
                for pc, ps in by_pericope.items() if len(ps) > 1]
    return out


def events_report(events: Sequence[Mapping[str, Any]], struct_version: str,
                  registry_version: str) -> dict[str, Any]:
    anchors = [a for e in events for a in e["anchors"]]
    declared = sum(len({a["pericope_id"] for a in e["anchors"]}) for e in events)
    return {
        "schema": "ragdata.events_report.v2", "struct": struct_version,
        "registry": registry_version,
        "counts": {"events": len(events), "anchors": len(anchors),
                   "passages": len({a["passage_id"] for a in anchors}),
                   "pericope_declarations": declared,
                   "pericopes": len({a["pericope_id"] for a in anchors}),
                   "pdf_terms": sum(len(e["pdf_terms"]) for e in events),
                   "external_aliases": sum(len(e["external_aliases"]) for e in events),
                   "retired": sum(len(e["merged_from"]) for e in events)},
        "expanded": _expanded(events),
    }
