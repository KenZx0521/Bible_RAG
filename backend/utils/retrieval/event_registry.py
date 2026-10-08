"""Curated event registry — the auxiliary lane for event questions.

The 2026-10 graph audit found the hand-curated event→anchor map to be the only
graph signal with measured value, while letting graph candidates compete for
top-k slots displaced as many gold passages as it added. So the registry never
enters the candidate pool: router.retrieve_and_rerank APPENDS its anchors after
the finished dense top-k, which stays identical to the lane being off.

The registry is the build's contract file ``event_registry.json``
(``ragdata.event_registry.v2``, variant R2): an event fires on one of its triggers
(its pdf_terms, then its external aliases), its anchors are passage ids, and it is
reported by its ev id; ``legacy_ids`` (R1 ids, merged events included) are only
for logs and evaluation. An event without triggers is legal and never fires. An
R1 file (legacy triggers, external_legacy provenance) is refused. The startup
check that every anchor passage exists lives in serving.startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ragcommon import ids
from ragcommon.routing import legacy_mark

SCHEMA = "ragdata.event_registry.v2"
VARIANT = "R2"
_MASK = "□"


class RegistryError(ValueError):
    """The registry contract file is malformed."""


@dataclass(frozen=True)
class RegistryEvent:
    id: str                         # ev id, what R2 reports
    legacy_ids: tuple[str, ...]     # R1 ids, for logs and evaluation id mapping only
    name: str
    triggers: tuple[str, ...]       # pdf_terms then external aliases, de-duplicated
    anchors: tuple[str, ...]        # passage ids, registry order


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise RegistryError(message)


def _texts(rows: Any, where: str) -> list[str]:
    _require(isinstance(rows, list), f"{where}: not a list")
    texts = [row.get("text") if isinstance(row, Mapping) else None for row in rows]
    _require(all(isinstance(t, str) and t for t in texts), f"{where}: needs a text per item")
    return texts


def _anchor(raw: Any, where: str) -> str:
    _require(isinstance(raw, Mapping), f"{where}: anchor is not an object")
    passage = raw.get("passage_id")
    _require(ids.is_valid(passage, "passage"), f"{where}: {passage!r} is not a passage id")
    return passage


def _event(raw: Any, i: int) -> RegistryEvent:
    where = f"events[{i}]"
    _require(isinstance(raw, Mapping), f"{where}: not an object")
    _require(not raw.get("legacy_triggers"), f"{where}: carries legacy triggers (an R1 registry)")
    _require(ids.is_valid(raw.get("event_id"), "event"),
             f"{where}: {raw.get('event_id')!r} is not an event id")
    _require(isinstance(raw.get("name"), str) and bool(raw["name"]), f"{where}: needs a name")
    legacy_ids = raw.get("legacy_ids") or []
    _require(isinstance(legacy_ids, list) and all(isinstance(x, str) for x in legacy_ids),
             f"{where}: legacy_ids must be a list of ids")
    triggers = (_texts(raw.get("pdf_terms"), f"{where}.pdf_terms")
                + _texts(raw.get("external_aliases"), f"{where}.external_aliases"))
    anchors = tuple(_anchor(a, where) for a in raw.get("anchors") or [])
    _require(bool(anchors), f"{where}: needs anchors")
    return RegistryEvent(raw["event_id"], tuple(legacy_ids), raw["name"],
                         tuple(dict.fromkeys(triggers)), anchors)


def _check_retired(retired: Any, event_ids: set[str]) -> None:
    _require(isinstance(retired, list), "registry retired must be a list")
    for i, row in enumerate(retired):
        target = row.get("merged_into") if isinstance(row, Mapping) else None
        _require(target in event_ids, f"retired[{i}]: merged_into {target!r} names no event")


def parse_registry(doc: Any) -> tuple[RegistryEvent, ...]:
    """Validate the contract document; raise RegistryError on any defect."""
    _require(isinstance(doc, Mapping) and doc.get("schema") == SCHEMA,
             f"registry schema must be {SCHEMA}")
    _require(doc.get("variant") == VARIANT,
             f"registry variant must be {VARIANT}, got {doc.get('variant')!r}")
    mark = legacy_mark(doc)
    _require(mark is None, f"registry carries legacy provenance at {mark}")
    _require(isinstance(doc.get("events"), list), "registry events must be a list")
    events = tuple(_event(raw, i) for i, raw in enumerate(doc["events"]))
    seen = [e.id for e in events]
    _require(len(set(seen)) == len(seen), "duplicate registry event")
    _check_retired(doc.get("retired"), set(seen))
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
