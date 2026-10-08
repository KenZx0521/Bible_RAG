#!/usr/bin/env python3
"""Export the curated event registry → backend/data/event_registry.json.

The registry is the graph's auxiliary lane for event questions (2026-10 graph
audit, docs/records/2026-10-03_graph_benchmark_validity_audit.md §3.3): the
only graph signal with measured value was the hand-curated event→anchor map
(S2's gain over no_graph is 93% reproducible from curated injections alone),
so it is frozen into a static file the backend reads without Neo4j. At query
time an exact trigger appends ONE anchor after the untouched dense top-k
instead of competing for a top-k slot.

Which events are curated (single source of truth = the scripts that made them):
  * scripts/backfill_head_events.py — ALIAS_INJECTIONS (11 existing events given
    question-phrasing aliases) + NEW_EVENTS (18 hand-built events), 046040a.
  * config/curated/manual_graph_patches.jsonl — Event nodes whose anchors are
    hand-typed MENTIONS edges: 受難週, 大使命 (nodes made by hand, provenance
    manual_patch) and 山上寶訓 plus the two 保羅敘述歸主(的)經過 events
    (extracted nodes given hand-typed anchors for EVENT_011/EVENT_019,
    provenance manual_edges). The 2026-10 simulation (a4) seeded only
    CURATED 31 + 山上寶訓; the two 保羅 events share the trigger 保羅歸主 with
    curated 掃羅的轉變, so they only matter when its act:9:0 is already in
    the top-k (they then append act:9:1).

Known limitation: an event keeps one anchor list for all its triggers, so a
trigger naming one part of a merged event gets the event's first anchor
(所羅門獻殿 → 1ki:6:0, the building of the temple). Per-trigger anchors would
be tuned on benchmark questions; validate them on held-out questions first.

Names, aliases and anchors are read from live Neo4j (MENTIONS, chunk → parent
pericope) and anchors are sorted canonically (output/books.jsonl book order,
chapter, pericope index). Triggers are the backend EVENT_KEYWORDS that exactly
equal the event's canonical name or one of its aliases — the same exact-match
rule as `keyword_exact` in graph_retriever.retrieve_by_events. Aliases are NOT
triggers by themselves: many were written for specific benchmark questions,
and widening the trigger set needs held-out validation first.

The core, registry_from_rows(), is a pure function of the anchor rows (the
shape _ANCHOR_QUERY returns), so a registry can also be built offline from a
JSONL projection of the graph (validate_kg --snapshot, rebuild simulations);
build_registry() only adds the live Neo4j fetch.

Usage (from the project root):
    scripts/.venv/bin/python scripts/export_event_registry.py           # write
    scripts/.venv/bin/python scripts/export_event_registry.py --check   # drift check
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from backfill_head_events import (  # noqa: E402  (also loads .env)
    ALIAS_INJECTIONS,
    NEW_EVENTS,
    get_neo4j,
)

OUT_PATH = _PROJECT_ROOT / "backend" / "data" / "event_registry.json"
MANUAL_PATCHES = _PROJECT_ROOT / "config" / "curated" / "manual_graph_patches.jsonl"
# The backend's EVENT_KEYWORDS, frozen when R1 moved routing to the contract (D-12(a)).
ROUTING_LEXICON = _PROJECT_ROOT / "config" / "registries" / "routing_lexicon.legacy.json"
BOOKS = _PROJECT_ROOT / "output" / "books.jsonl"

_ANCHOR_QUERY = """
UNWIND $ids AS eid
MATCH (e:Event {entity_id: eid})
OPTIONAL MATCH (e)-[:MENTIONS]-(p0)
WHERE p0:Pericope OR p0:Chunk
OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
WITH e, collect(DISTINCT CASE WHEN p0:Chunk THEN coalesce(parent.id, p0.id) ELSE p0.id END) AS anchors
RETURN e.entity_id AS id, e.canonical_name AS name, e.aliases AS aliases, anchors
"""


def curated_event_ids() -> dict[str, str]:
    """entity_id → provenance tag, from the scripts that created the curation."""
    ids: dict[str, str] = {eid: "alias_injection" for eid in ALIAS_INJECTIONS}
    for ev in NEW_EVENTS:
        # The literal id the backfill wrote (ID-7), never one re-derived from
        # the name: a pypinyin upgrade or a renamed event must not move it.
        ids[ev["entity_id"]] = "head_event_backfill"
    for line in MANUAL_PATCHES.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("kind") == "node" and "Event" in row.get("labels", []):
            tag = "manual_patch" if row.get("origin") == "manual" else "manual_edges"
            ids.setdefault(row["entity_id"], tag)
    return ids


def event_keywords() -> set[str]:
    """The backend's EVENT_KEYWORDS: the events of the frozen legacy routing lexicon."""
    terms = {e["term"] for e in json.loads(ROUTING_LEXICON.read_text(encoding="utf-8"))["events"]}
    if not terms:
        raise RuntimeError(f"no event keywords in {ROUTING_LEXICON}")
    return terms


def canonical_key(book_order: Mapping[str, int]):
    def key(pericope_id: str) -> tuple[int, int, int]:
        book, chapter, index = pericope_id.split(":")
        return book_order[book], int(chapter), int(index)
    return key


def load_book_order(path: Path = BOOKS) -> dict[str, int]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["id"]: row["order"] for row in rows}


def fetch_anchor_rows(driver, ids: Iterable[str]) -> list[dict]:
    """One _ANCHOR_QUERY row per :Event node among ``ids`` (read-only)."""
    with driver.session() as session:
        return [dict(r) for r in session.run(_ANCHOR_QUERY, ids=sorted(ids))]


def registry_from_rows(rows: Iterable[Mapping], curated: Mapping[str, str],
                       keywords: Collection[str], book_order: Mapping[str, int],
                       *, generated_at: str | None = None) -> dict:
    """Build the registry from anchor rows; no I/O, inputs are not modified.

    ``rows`` has the _ANCHOR_QUERY shape — {id, name, aliases, anchors}, one
    per :Event node, anchors already rolled up from chunks to their parent
    pericope. Rows outside ``curated`` are ignored, so an offline caller may
    pass every event. A curated id without a row, or with two rows, raises.
    """
    by_id: dict[str, Mapping] = {}
    duplicated: set[str] = set()
    for row in rows:
        if row["id"] not in curated:
            continue
        if row["id"] in by_id:
            # Two nodes share the id (no :Entity constraint); picking either
            # would make the registry depend on the graph's return order.
            duplicated.add(row["id"])
        by_id[row["id"]] = row
    if duplicated:
        raise RuntimeError(f"curated events on more than one node: {sorted(duplicated)}")
    missing = sorted(set(curated) - set(by_id))
    if missing:
        raise RuntimeError(f"curated events missing from the graph: {missing}")

    order = canonical_key(book_order)
    events, dropped = [], []
    for eid in sorted(curated):
        row = by_id[eid]
        names = {row["name"], *(row["aliases"] or [])}
        triggers = sorted(kw for kw in keywords if kw in names)
        anchors = sorted(row["anchors"], key=order)
        if not triggers:
            dropped.append({"id": eid, "name": row["name"], "reason": "no EVENT_KEYWORDS exact match"})
            continue
        if not anchors:
            dropped.append({"id": eid, "name": row["name"], "reason": "no anchors"})
            continue
        events.append({
            "id": eid,
            "name": row["name"],
            "provenance": curated[eid],
            "triggers": triggers,
            "anchors": anchors,
        })

    return {
        "version": 1,
        "generated_at": generated_at,
        "generator": "scripts/export_event_registry.py",
        "trigger_rule": "backend EVENT_KEYWORDS exactly equal to the event's canonical name or an alias",
        "anchor_order": "canonical: book order, chapter, pericope index",
        "events": events,
        "dropped": dropped,
    }


def build_registry(driver=None) -> dict:
    """The registry the live graph yields; opens (and closes) a driver if none is given."""
    curated = curated_event_ids()
    keywords = event_keywords()
    book_order = load_book_order()

    owned = driver is None
    driver = get_neo4j() if owned else driver
    try:
        rows = fetch_anchor_rows(driver, curated)
    finally:
        if owned:
            driver.close()

    return registry_from_rows(rows, curated, keywords, book_order,
                              generated_at=datetime.now().isoformat(timespec="seconds"))


def render_registry(registry: dict) -> str:
    """The exact text written to OUT_PATH."""
    return json.dumps(registry, ensure_ascii=False, indent=2) + "\n"


def _comparable(registry: dict) -> dict:
    return {k: v for k, v in registry.items() if k != "generated_at"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the live graph no longer matches the committed registry")
    args = parser.parse_args()

    registry = build_registry()
    if args.check:
        current = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        if _comparable(current) != _comparable(registry):
            print(f"DRIFT: {OUT_PATH} differs from the live graph; re-run without --check")
            return 1
        print(f"OK: {OUT_PATH} matches the live graph")
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render_registry(registry), encoding="utf-8")
    print(f"wrote {len(registry['events'])} events → {OUT_PATH}")
    for d in registry["dropped"]:
        print(f"  dropped {d['id']} ({d['name']}): {d['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
