"""K1, R1 version: the event registry converted mechanically from the legacy one (§2.21, §5.3).

``convert_registry`` turns ``backend/data/event_registry.json`` (33 events, 178 anchors
on legacy pericope ids) into ``config/registries/events.yaml``: every anchor becomes
the passage the struct layer's ``legacy_ids`` maps it to, with that passage's keys and
slot range, and is classified by its integer verse range (§2.14):

- ``same``: the passage spans the legacy verses;
- ``narrowed``: same range, but a ghost verse the legacy text had is an omitted slot now;
- ``widened``: the passage also takes in the half verse a mid-verse heading split off.

Anything else (a legacy anchor that is unknown, split, or would shrink) is refused:
R1 freezes the content, so the conversion must be one-to-one. Triggers are copied
verbatim into ``legacy_triggers`` (``external_legacy``, retired by R2); anchors are
``legacy_tuned``; there are no ``pdf_terms`` yet.

``compile_events`` re-derives every anchor from ``legacy_ids`` and refuses a registry
that drifted from the conversion, then writes the records and two contract files:
``event_registry_v2.json`` (design §2.21) and ``event_registry_v1.json``, the shape the
current backend reads with passage ids in place of pericope ids.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import yaml

from ragcommon import ids
from ragdata.gates.base import Snapshot
from ragdata.kg.k1_contracts import V2_SCHEMA, events_report, v1_doc, v2_doc
from ragdata.stages.errors import StageError

SCHEMA = "ragdata.events.v1"
__all__ = ["V2_SCHEMA", "EventRegistryError", "EventsResult", "compile_events", "convert_registry",
           "dump_events_yaml", "load_events_yaml"]
LEGACY_SOURCE = "backend/data/event_registry.json"
TRIGGER_NOTE = "R1 凍結的 legacy 觸發詞，依同一份 GT 調出（D3 報告須註明）"
HEADER = ("# R1 事件註冊表：由 `python -m ragdata convert events` 從 backend/data/event_registry.json\n"
          "# 經 struct 層 legacy_ids 機械轉換；內容凍結（錨點 legacy_tuned、觸發詞 external_legacy，"
          "R2 退場）。不要手改。\n")
ANCHOR_KEYS = ("legacy", "passage_id", "start_key", "end_key", "start_slot", "end_slot", "change")
EVENT_KEYS = {"event_id", "legacy_id", "name", "legacy_provenance", "legacy_triggers", "anchors"}
SOURCE_COPIED = ("generated_at", "trigger_rule", "anchor_order", "dropped")


class EventRegistryError(StageError):
    """The event registry does not convert one to one, or drifted from its conversion."""


@dataclass(frozen=True)
class LegacyMap:
    pericopes: Mapping[str, Any]            # legacy pericope id -> LegacyId row
    retired: tuple[str, ...]                # slots of legacy verses the PDF omits
    passages: Mapping[str, Any]


def legacy_map(snapshot: Snapshot) -> LegacyMap:
    rows = snapshot.of("legacy_ids")
    return LegacyMap(
        MappingProxyType({r.legacy_id: r for r in rows if r.kind == "pericope"}),
        tuple(r.start_slot for r in rows if r.relation == "retired"),
        snapshot.index("passages"))


def _verses(start: str, end: str) -> tuple[str, int, int]:
    s, e = ids.parse(start), ids.parse(end)
    return ids.chapter_key(s.book_id, s.chapter), s.verse, e.verse


def _change(old: tuple[str, int, int], new: tuple[str, int, int], ps: Any,
            retired: Sequence[str]) -> tuple[str, list[str], list[str]]:
    """(change, removed slots, added keys) of a legacy range against its passage."""
    chapter, lo, hi = old
    if new == old:
        removed = [s for s in retired if _verses(s, s)[0] == chapter and lo <= _verses(s, s)[1] <= hi]
        return ("narrowed" if removed else "same"), removed, []
    if new[0] == chapter and new[1] <= lo and hi <= new[2]:
        book = ids.parse(ps.start_slot).book_id
        chapter_no = ids.parse(ps.start_slot).chapter
        added = [ids.verse_key(book, chapter_no, v, half=(v == new[1] and ps.start_partial))
                 for v in range(new[1], new[2] + 1) if not lo <= v <= hi]
        return "widened", [], added
    raise EventRegistryError(f"{ps.passage_id} is neither the legacy range {old} nor a "
                             "widening of it")


def convert_anchor(legacy: str, lmap: LegacyMap) -> dict[str, Any]:
    row = lmap.pericopes.get(legacy)
    if row is None:
        raise EventRegistryError(f"legacy anchor {legacy} is not in legacy_ids")
    if row.relation not in ("exact", "contained") or len(row.new_ids) != 1:
        raise EventRegistryError(f"legacy anchor {legacy} does not map to one passage "
                                 f"({row.relation}: {list(row.new_ids)})")
    ps = lmap.passages[row.new_ids[0]]
    change, removed, added = _change(_verses(row.start_slot, row.end_slot),
                                     _verses(ps.start_slot, ps.end_slot), ps, lmap.retired)
    return {"legacy": legacy, "passage_id": ps.passage_id, "start_key": ps.start_key,
            "end_key": ps.end_key, "start_slot": ps.start_slot, "end_slot": ps.end_slot,
            "change": change, "removed": removed, "added": added,
            "legacy_range": [row.start_slot, row.end_slot]}


def _yaml_anchor(converted: Mapping[str, Any]) -> dict[str, Any]:
    return {key: converted[key] for key in ANCHOR_KEYS}


def _legacy_doc(data: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventRegistryError(f"legacy registry is not JSON: {exc}") from None
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("events"), list):
        raise EventRegistryError("legacy registry must be version 1 with a list of events")
    return doc


def convert_registry(data: bytes, snapshot: Snapshot, struct_version: str,
                     source: str = LEGACY_SOURCE) -> dict[str, Any]:
    """The events.yaml document for the legacy registry ``data`` (its file bytes)."""
    legacy, lmap = _legacy_doc(data), legacy_map(snapshot)
    events = [{"event_id": ids.event_id(n), "legacy_id": raw["id"], "name": raw["name"],
               "legacy_provenance": raw["provenance"], "legacy_triggers": list(raw["triggers"]),
               "anchors": [_yaml_anchor(convert_anchor(a, lmap)) for a in raw["anchors"]]}
              for n, raw in enumerate(legacy["events"], start=1)]
    return {"schema": SCHEMA, "variant": "R1",
            "source": {"file": source, "sha256": hashlib.sha256(data).hexdigest(),
                       "struct": struct_version,
                       **{k: legacy[k] for k in SOURCE_COPIED if k in legacy}},
            "defaults": {"anchor_provenance": "legacy_tuned",
                         "trigger": {"provenance_class": "external_legacy", "source": source,
                                     "note": TRIGGER_NOTE, "retire_by": "R2"}},
            "events": events}


def dump_events_yaml(doc: Mapping[str, Any]) -> str:
    return HEADER + yaml.safe_dump(dict(doc), allow_unicode=True, sort_keys=False, width=100)


def load_events_yaml(path: Path | str) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise EventRegistryError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict):
        raise EventRegistryError(f"{path}: expected a mapping")
    return doc


# ------------------------------------------------------------------ compile


@dataclass(frozen=True)
class EventsResult:
    rows: Mapping[str, list[dict[str, Any]]]
    v1: dict[str, Any]
    v2: dict[str, Any]
    report: dict[str, Any]


def _check_doc(doc: Mapping[str, Any]) -> None:
    if doc.get("schema") != SCHEMA or doc.get("variant") != "R1":
        raise EventRegistryError(f"events.yaml must be schema {SCHEMA}, variant R1")
    for n, event in enumerate(doc.get("events") or [], start=1):
        if not isinstance(event, dict) or set(event) != EVENT_KEYS:
            raise EventRegistryError(f"events[{n - 1}]: keys must be {sorted(EVENT_KEYS)}")
        if event["event_id"] != ids.event_id(n):
            raise EventRegistryError(f"events[{n - 1}]: event_id must be {ids.event_id(n)}")
        if not event["legacy_triggers"] or not event["anchors"]:
            raise EventRegistryError(f"{event['event_id']}: R1 keeps every legacy trigger and "
                                     "anchor; none may be empty")


def _anchors(event: Mapping[str, Any], lmap: LegacyMap) -> list[dict[str, Any]]:
    found = []
    for anchor in event["anchors"]:
        converted = convert_anchor(anchor.get("legacy"), lmap)
        if _yaml_anchor(converted) != anchor:
            raise EventRegistryError(f"{event['event_id']}: anchor {anchor} drifted; the "
                                     f"conversion gives {_yaml_anchor(converted)}")
        found.append(converted)
    return found


def _event_row(event: Mapping[str, Any], anchors: Sequence[Mapping[str, Any]],
               trigger: Mapping[str, Any], provenance: str) -> dict[str, Any]:
    return {"event_id": event["event_id"], "legacy_id": event["legacy_id"], "name": event["name"],
            "legacy_provenance": event["legacy_provenance"],
            "anchors": [{**{k: a[k] for k in ANCHOR_KEYS[1:]}, "legacy_anchor": a["legacy"],
                         "provenance_class": provenance} for a in anchors],
            "legacy_triggers": [{"text": t, **trigger} for t in event["legacy_triggers"]],
            "pdf_terms": [], "external_aliases": [], "provenance_class": provenance}


def _change_row(event_id: str, a: Mapping[str, Any], source: str) -> dict[str, Any]:
    removed, added = a["removed"], a["added"]
    return {"change_key": f"{event_id}|{a['legacy']}", "event_id": event_id,
            "legacy_anchor": a["legacy"], "passage_id": a["passage_id"], "change": a["change"],
            "legacy_start_slot": a["legacy_range"][0], "legacy_end_slot": a["legacy_range"][1],
            "start_key": a["start_key"], "end_key": a["end_key"], "removed_slots": removed,
            "added_keys": added, "provenance_class": "external_legacy", "source": source,
            "note": ("去掉幽靈節 " + "、".join(removed)) if removed else ("補回 " + "、".join(added)),
            "retire_by": "R2"}


def compile_events(doc: Mapping[str, Any], snapshot: Snapshot,
                   struct_version: str) -> EventsResult:
    _check_doc(doc)
    lmap, defaults = legacy_map(snapshot), doc["defaults"]
    change_source = f"{doc['source']['file']} → {struct_version} legacy_ids"
    events, changes, converted = [], [], []
    for event in doc["events"]:
        anchors = _anchors(event, lmap)
        converted.append(anchors)
        events.append(_event_row(event, anchors, defaults["trigger"], defaults["anchor_provenance"]))
        changes += [_change_row(event["event_id"], a, change_source)
                    for a in anchors if a["change"] != "same"]
    half = [{"event_id": e["event_id"], "legacy_anchor": a["legacy"], "passage_id": a["passage_id"]}
            for e, group in zip(doc["events"], converted) for a in group
            if a["change"] == "same" and (lmap.passages[a["passage_id"]].start_partial
                                         or lmap.passages[a["passage_id"]].end_partial)]
    report = {**events_report(events, converted, doc["source"], struct_version),
              "same_with_half_verse": half}
    return EventsResult(MappingProxyType({"events": events, "anchor_changes": changes}),
                        v1_doc(events, doc["source"]), v2_doc(events, struct_version), report)
