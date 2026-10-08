"""Curated event registry — the auxiliary lane for event questions.

The 2026-10 graph audit found the hand-curated event→anchor map to be the only
graph signal with measured value, while letting graph candidates compete for
top-k slots displaced as many gold passages as it added. So the registry never
enters the candidate pool: router.retrieve_and_rerank APPENDS its anchors after
the finished dense top-k, which stays identical to the lane being off.

The registry is the build's contract file ``event_registry.json``
(``ragdata.event_registry.v2``, the R1 mechanical conversion): an event fires on
one of its frozen legacy triggers, its anchors are passage ids, and it is
reported by its legacy id (R1 keeps the old event ids). The startup check that
every anchor passage exists lives in serving.startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ragcommon import ids

SCHEMA = "ragdata.event_registry.v2"
_MASK = "□"


class RegistryError(ValueError):
    """The registry contract file is malformed."""


@dataclass(frozen=True)
class RegistryEvent:
    id: str                    # legacy id, what R1 reports
    event_id: str              # ev id of the build
    name: str
    triggers: tuple[str, ...]
    anchors: tuple[str, ...]   # passage ids, registry order


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise RegistryError(message)


def _anchor(raw: Any, where: str) -> str:
    _require(isinstance(raw, Mapping), f"{where}: anchor is not an object")
    passage = raw.get("passage_id")
    _require(ids.is_valid(passage, "passage"), f"{where}: {passage!r} is not a passage id")
    return passage


def _event(raw: Any, i: int) -> RegistryEvent:
    where = f"events[{i}]"
    _require(isinstance(raw, Mapping), f"{where}: not an object")
    triggers = tuple(t.get("text") for t in raw.get("legacy_triggers") or [])
    _require(bool(triggers) and all(isinstance(t, str) and t for t in triggers),
             f"{where}: needs legacy triggers")
    anchors = tuple(_anchor(a, where) for a in raw.get("anchors") or [])
    _require(bool(anchors), f"{where}: needs anchors")
    _require(bool(raw.get("legacy_id")) and bool(raw.get("name")), f"{where}: needs ids and name")
    return RegistryEvent(raw["legacy_id"], raw.get("event_id", ""), raw["name"], triggers, anchors)


def parse_registry(doc: Any) -> tuple[RegistryEvent, ...]:
    """Validate the contract document; raise RegistryError on any defect."""
    _require(isinstance(doc, Mapping) and doc.get("schema") == SCHEMA,
             f"registry schema must be {SCHEMA}")
    _require(isinstance(doc.get("events"), list), "registry events must be a list")
    events = tuple(_event(raw, i) for i, raw in enumerate(doc["events"]))
    seen = [e.id for e in events]
    _require(len(set(seen)) == len(seen), "duplicate registry event")
    return events


def anchor_passages(events: Iterable[RegistryEvent]) -> tuple[str, ...]:
    """Every anchor passage, first appearance order."""
    return tuple(dict.fromkeys(a for e in events for a in e.anchors))


def mask_book_names(text: str, book_names: Sequence[str]) -> str:
    """Blank out book names so a trigger never fires on part of one (longest first)."""
    for name in sorted((n for n in book_names if len(n) >= 2), key=len, reverse=True):
        text = text.replace(name, _MASK * len(name))
    return text


def match_events(query: str, events: Sequence[RegistryEvent],
                 book_names: Sequence[str]) -> list[RegistryEvent]:
    """Events with a trigger literally in the question; fewest anchors first, then file order."""
    masked = mask_book_names(query, book_names)
    hits = [(len(e.anchors), i, e) for i, e in enumerate(events)
            if any(t in masked for t in e.triggers)]
    return [e for _, _, e in sorted(hits, key=lambda h: (h[0], h[1]))]


def select_aux_anchors(events: Sequence[RegistryEvent], core_passages: Iterable[str],
                       slots: int) -> list[tuple[str, str]]:
    """(event id, anchor) picks: each event's first anchor the core lacks, up to ``slots``."""
    covered = set(core_passages)
    picks: list[tuple[str, str]] = []
    for event in events:
        if len(picks) >= slots:
            break
        anchor = next((a for a in event.anchors if a not in covered), None)
        if anchor is not None:
            picks.append((event.id, anchor))
            covered.add(anchor)
    return picks
