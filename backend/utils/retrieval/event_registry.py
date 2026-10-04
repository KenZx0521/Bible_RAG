"""
Curated event registry — the graph's auxiliary lane for event questions.

The 2026-10 graph audit found the hand-curated event→anchor map to be the only
graph signal with measured value (S2's gain over no_graph is 93% reproducible
from curated injections), while letting graph candidates compete for top-k
slots displaced as many gold passages as it added. So the registry never
enters the candidate pool: router.retrieve_and_rerank APPENDS its anchors after
the finished dense top-k, which stays identical to graph-off by construction.

The registry is a static file exported from Neo4j by
scripts/export_event_registry.py (backend/data/event_registry.json); no graph
database is touched at query time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from utils.verse_parser import BOOK_CONFIG

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "event_registry.json"
PERICOPE_ID = re.compile(r"[0-9a-z]+:\d+:\d+")

# Full book names, longest first so 約翰一書 is masked before 約翰.
_BOOK_NAMES = sorted((n for n in BOOK_CONFIG if len(n) >= 2), key=len, reverse=True)
_MASK = "□"


@dataclass(frozen=True)
class RegistryEvent:
    id: str
    name: str
    triggers: tuple[str, ...]
    anchors: tuple[str, ...]  # pericope ids, canonical order


@lru_cache(maxsize=4)
def load_registry(path: Path | None = None) -> tuple[RegistryEvent, ...]:
    """Load and validate the registry; raises ValueError on a malformed file."""
    data = json.loads(Path(path or REGISTRY_PATH).read_text(encoding="utf-8"))
    events: list[RegistryEvent] = []
    seen: set[str] = set()
    for raw in data.get("events", []):
        eid = raw["id"]
        if eid in seen:
            raise ValueError(f"duplicate registry event {eid}")
        seen.add(eid)
        triggers, anchors = tuple(raw["triggers"]), tuple(raw["anchors"])
        if not triggers or not anchors:
            raise ValueError(f"registry event {eid} needs triggers and anchors")
        bad = [a for a in anchors if not PERICOPE_ID.fullmatch(a)]
        if bad:
            raise ValueError(f"registry event {eid} has malformed anchors {bad}")
        events.append(RegistryEvent(id=eid, name=raw["name"], triggers=triggers, anchors=anchors))
    return tuple(events)


def mask_book_names(text: str) -> str:
    """Blank out book names so a trigger never fires on part of one."""
    for name in _BOOK_NAMES:
        text = text.replace(name, _MASK * len(name))
    return text


def match_events(
    query: str, events: tuple[RegistryEvent, ...] | None = None,
) -> list[RegistryEvent]:
    """Events with a trigger literally in the question (book names masked).

    Most specific first: fewest anchors, ties in registry order.
    """
    registry = load_registry() if events is None else events
    masked = mask_book_names(query)
    hits = [(len(e.anchors), i, e) for i, e in enumerate(registry)
            if any(t in masked for t in e.triggers)]
    return [e for _, _, e in sorted(hits, key=lambda h: (h[0], h[1]))]


def _covered(anchor: str, core_ids: list[str]) -> bool:
    """The anchor pericope, or a chunk/verse of it, is already in the core."""
    return any(cid == anchor or cid.startswith(anchor + ":") for cid in core_ids)


def select_aux_anchors(
    events: list[RegistryEvent], core_ids: list[str], slots: int,
) -> list[tuple[str, str]]:
    """(event_id, anchor) picks: each event's first anchor the core lacks, up to `slots`."""
    picks: list[tuple[str, str]] = []
    chosen: list[str] = []
    for event in events:
        if len(picks) >= slots:
            break
        for anchor in event.anchors:
            if not _covered(anchor, core_ids) and anchor not in chosen:
                picks.append((event.id, anchor))
                chosen.append(anchor)
                break
    return picks
