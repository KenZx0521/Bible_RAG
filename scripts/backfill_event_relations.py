#!/usr/bin/env python3
"""Salvage Event-related unclassified relation pairs (P0 repair).

77,953 mined pairs never got a relation type from the LLM classifier
(gemma3:4b) and sit in relations_unclassified.jsonl. The Event-related
subset is directly usable to fill the near-empty event layer:

    Event–Person  →  (Person)-[:PARTICIPATED_IN]->(Event)
    Event–Place   →  (Event)-[:OCCURRED_IN]->(Place)

These are pericope-cooccurrence signals, not verified assertions, so edges
are written with confidence=0.35, extraction_phase=5 and
notes='cooccurrence-backfill'. MERGE ... ON CREATE never touches existing
classifier-produced edges. Event–Event pairs (277) are skipped: temporal
direction (PRECEDED_BY/CAUSED) cannot be inferred from cooccurrence.

Usage:
    uv run python backfill_event_relations.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BATCH_SIZE = 2000
CONFIDENCE = 0.35
PHASE = 5  # cooccurrence backfill (R2 rule=2, R4 llm=4 in existing data)

_MERGE_PARTICIPATED = """
UNWIND $rows AS row
MATCH (p:Person:Entity {entity_id: row.person_id})
MATCH (ev:Event:Entity {entity_id: row.event_id})
MERGE (p)-[r:PARTICIPATED_IN]->(ev)
ON CREATE SET r.confidence = $confidence,
              r.extraction_phase = $phase,
              r.notes = 'cooccurrence-backfill',
              r.evidence_count = row.evidence_count,
              r.source_pericope_id = row.source_pericope_id,
              r.head_canonical = row.head_canonical,
              r.tail_canonical = row.tail_canonical,
              r.backfilled = true
RETURN count(r) AS matched, sum(CASE WHEN r.backfilled THEN 1 ELSE 0 END) AS created
"""

_MERGE_OCCURRED = """
UNWIND $rows AS row
MATCH (ev:Event:Entity {entity_id: row.event_id})
MATCH (pl:Place:Entity {entity_id: row.place_id})
MERGE (ev)-[r:OCCURRED_IN]->(pl)
ON CREATE SET r.confidence = $confidence,
              r.extraction_phase = $phase,
              r.notes = 'cooccurrence-backfill',
              r.evidence_count = row.evidence_count,
              r.source_pericope_id = row.source_pericope_id,
              r.head_canonical = row.head_canonical,
              r.tail_canonical = row.tail_canonical,
              r.backfilled = true
RETURN count(r) AS matched, sum(CASE WHEN r.backfilled THEN 1 ELSE 0 END) AS created
"""

_EVENT_COVERAGE = """
MATCH (ev:Event) WITH count(ev) AS total
MATCH (ev2:Event) WHERE EXISTS { (:Person)-[:PARTICIPATED_IN]->(ev2) }
WITH total, count(ev2) AS with_participant
MATCH (ev3:Event) WHERE EXISTS { (ev3)-[:OCCURRED_IN]->(:Place) }
RETURN total, with_participant, count(ev3) AS with_place
"""


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def load_pairs(path: Path) -> tuple[list[dict], list[dict], int]:
    """Aggregate Event-Person / Event-Place pairs; count cooccurrence evidence."""
    ep: dict[tuple[str, str], dict] = defaultdict(lambda: {"evidence_count": 0})
    epl: dict[tuple[str, str], dict] = defaultdict(lambda: {"evidence_count": 0})
    ee_skipped = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            ht, tt = rec.get("head_type"), rec.get("tail_type")
            if ht == "Event" and tt == "Person":
                slot = ep[(rec["head_id"], rec["tail_id"])]
            elif ht == "Event" and tt == "Place":
                slot = epl[(rec["head_id"], rec["tail_id"])]
            elif ht == "Event" and tt == "Event":
                ee_skipped += 1
                continue
            else:
                continue
            slot["evidence_count"] += 1
            if "source_pericope_id" not in slot:
                slot["source_pericope_id"] = rec.get("source_pericope_id", "")
                slot["head_canonical"] = rec.get("head_canonical", "")
                slot["tail_canonical"] = rec.get("tail_canonical", "")

    participated = [
        {"event_id": eid, "person_id": pid, **v} for (eid, pid), v in ep.items()
    ]
    occurred = [
        {"event_id": eid, "place_id": plid, **v} for (eid, plid), v in epl.items()
    ]
    return participated, occurred, ee_skipped


def run_batches(driver, cypher: str, rows: list[dict], label: str) -> dict:
    stats = {"matched": 0, "created": 0, "skipped_missing": 0}
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        with driver.session() as session:
            record = session.run(cypher, rows=batch, confidence=CONFIDENCE, phase=PHASE).single()
            matched = int(record["matched"]) if record else 0
            created = int(record["created"]) if record else 0
        stats["matched"] += matched
        stats["created"] += created
        stats["skipped_missing"] += len(batch) - matched
    print(f"  {label}: {stats['created']:,} new edges "
          f"({stats['matched']:,} pairs matched, "
          f"{stats['skipped_missing']:,} skipped: node missing)")
    return stats


def coverage(driver) -> dict:
    with driver.session() as session:
        record = session.run(_EVENT_COVERAGE).single()
        return dict(record) if record else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str,
                        default=str(ROOT / "output" / "relations_unclassified.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"✗ Not found: {path}")
        return 2

    participated, occurred, ee_skipped = load_pairs(path)
    print(f"Event–Person pairs: {sum(1 for _ in participated):,} unique "
          f"→ PARTICIPATED_IN candidates")
    print(f"Event–Place pairs:  {len(occurred):,} unique → OCCURRED_IN candidates")
    print(f"Event–Event pairs skipped (no temporal direction inferable): {ee_skipped:,}")

    driver = get_driver()
    try:
        before = coverage(driver)
        print(f"\nBefore: {before['with_participant']:,}/{before['total']:,} events "
              f"with participant, {before['with_place']:,}/{before['total']:,} with place")

        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        print("\nImporting...")
        run_batches(driver, _MERGE_PARTICIPATED, participated, "PARTICIPATED_IN")
        run_batches(driver, _MERGE_OCCURRED, occurred, "OCCURRED_IN")

        after = coverage(driver)
        print(f"\nAfter:  {after['with_participant']:,}/{after['total']:,} events "
              f"with participant ({before['with_participant']:,} before), "
              f"{after['with_place']:,}/{after['total']:,} with place "
              f"({before['with_place']:,} before)")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
