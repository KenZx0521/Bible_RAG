#!/usr/bin/env python3
"""Salvage Event-related unclassified relation pairs (P0 repair; legacy only).

77,953 mined pairs never got a relation type from the LLM classifier
(gemma3:4b) and sit in relations_unclassified.jsonl. The Event-related
subset was used to fill the near-empty event layer:

    Event–Person  →  (Person)-[:PARTICIPATED_IN]->(Event)
    Event–Place   →  (Event)-[:OCCURRED_IN]->(Place)

These are pericope-cooccurrence signals, not verified assertions (strict
precision about 0.2, REL-06), and they reach the graph after Step 6.05, so
its provenance gate never sees them. Step 10.3 is therefore out of the
default chain (D2, K7): without --legacy-cooccurrence the script exits 2
before it checks KG_TARGET or connects. The flag exists only for the K8 P1
control and for reproducing the paper's numbers.

With the flag, edges are written with source='cooccurrence',
extraction_phase=7 (ExtractionPhase.COOCCURRENCE; it was 5, shared with R5's
inverse edges, REL-09), confidence=0.35, notes='cooccurrence-backfill' and
backfilled=true. MERGE ... ON CREATE never touches existing
classifier-produced edges. Event–Event rows (277; 257 distinct pairs) are
skipped: temporal direction (PRECEDED_BY/CAUSED) cannot be inferred from
cooccurrence.

Usage:
    uv run python backfill_event_relations.py --legacy-cooccurrence [--dry-run]
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

import kg_target
from relation_extraction.models import PHASE_OF_SOURCE

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BATCH_SIZE = 2000
CONFIDENCE = 0.35
SOURCE = "cooccurrence"
PHASE = PHASE_OF_SOURCE[SOURCE]  # 7; was 5, the phase R5's inverse edges also carry

RETIRED = (
    "Step 10.3 is retired from the default build chain (D2, K7): it promotes "
    "same-pericope co-occurrence to typed PARTICIPATED_IN/OCCURRED_IN edges "
    "(strict precision about 0.2), read from the 2026-05 relations_unclassified.jsonl "
    "snapshot after Step 6.05, so the 6.05 provenance gate never sees them.\n"
    "Nothing was written. Pass --legacy-cooccurrence only to build the P1 control "
    "(K8) or to reproduce the paper's numbers; its edges carry "
    f"source='{SOURCE}' and extraction_phase={PHASE}."
)

_MERGE_PARTICIPATED = """
UNWIND $rows AS row
MATCH (p:Person:Entity {entity_id: row.person_id})
MATCH (ev:Event:Entity {entity_id: row.event_id})
MERGE (p)-[r:PARTICIPATED_IN]->(ev)
ON CREATE SET r.confidence = $confidence,
              r.extraction_phase = $phase,
              r.source = $source,
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
              r.source = $source,
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
    """Aggregate Event-Person / Event-Place pairs; count cooccurrence evidence.

    The third value counts the Event–Event rows skipped (rows, not pairs)."""
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
            record = session.run(cypher, rows=batch, confidence=CONFIDENCE,
                                 phase=PHASE, source=SOURCE).single()
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str,
                        default=str(ROOT / "output" / "relations_unclassified.jsonl"))
    parser.add_argument("--legacy-cooccurrence", action="store_true",
                        help="run the retired Step 10.3 (P1 control / paper reproduction only)")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def backfill(driver, participated: list[dict], occurred: list[dict], dry_run: bool) -> int:
    before = coverage(driver)
    print(f"\nBefore: {before['with_participant']:,}/{before['total']:,} events "
          f"with participant, {before['with_place']:,}/{before['total']:,} with place")

    if dry_run:
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
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.legacy_cooccurrence:
        print(RETIRED, file=sys.stderr)
        return 2
    kg_target.assert_target("neo4j")

    path = Path(args.input)
    if not path.exists():
        print(f"✗ Not found: {path}")
        return 2

    participated, occurred, ee_skipped = load_pairs(path)
    print(f"Event–Person pairs: {len(participated):,} unique "
          f"→ PARTICIPATED_IN candidates")
    print(f"Event–Place pairs:  {len(occurred):,} unique → OCCURRED_IN candidates")
    print(f"Event–Event rows skipped (no temporal direction inferable): {ee_skipped:,}")

    driver = get_driver()
    try:
        return backfill(driver, participated, occurred, args.dry_run)
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
