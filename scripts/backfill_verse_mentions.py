#!/usr/bin/env python3
"""Backfill verse-level entity mentions onto Pericope nodes (P0 data repair).

Verse-level mentions (source_id like ``gen:1:0:v:3``) were silently dropped at
import time because the graph has no Verse nodes. This script remaps each
verse mention to its parent pericope (strip ``:v:N``) and MERGEs the missing
(Pericope)-[:MENTIONS]->(Entity) edges directly into the live graph, without
re-running the full import.

New edges are tagged ``backfilled: true, source_granularity: 'verse'`` so they
can be audited or rolled back:
    MATCH (:Pericope)-[r:MENTIONS {backfilled: true}]->() DELETE r

Usage:
    uv run python backfill_verse_mentions.py [--dry-run] [--output-dir ../output]
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

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BATCH_SIZE = 2000

_MERGE_CYPHER = """
UNWIND $rows AS row
MATCH (e:Entity {entity_id: row.entity_id})
MATCH (p:Pericope {id: row.pericope_id})
MERGE (p)-[r:MENTIONS]->(e)
ON CREATE SET r.backfilled = true,
              r.source_granularity = 'verse',
              r.text_span = row.text_span,
              r.verse_mention_freq = row.freq
RETURN count(r) AS matched,
       sum(CASE WHEN r.backfilled = true THEN 1 ELSE 0 END) AS backfilled
"""

_STATS_CYPHER = """
MATCH (:Pericope)-[r:MENTIONS]->(:Entity) WITH count(r) AS pericope_mentions
MATCH (e:Entity) WHERE NOT EXISTS { (:Pericope)-[:MENTIONS]->(e) }
RETURN pericope_mentions, count(e) AS entities_without_pericope_anchor
"""


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def collect_verse_pairs(mentions_path: Path) -> list[dict]:
    """Aggregate verse mentions into unique (entity_id, pericope_id) rows."""
    pairs: dict[tuple[str, str], dict] = defaultdict(lambda: {"freq": 0, "text_span": ""})
    read = 0
    with mentions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("source_type") != "verse":
                continue
            source_id = rec.get("source_id") or ""
            entity_id = rec.get("entity_id")
            if not entity_id or ":v:" not in source_id:
                continue
            read += 1
            pericope_id = source_id.split(":v:")[0]
            slot = pairs[(entity_id, pericope_id)]
            slot["freq"] += 1
            if not slot["text_span"]:
                slot["text_span"] = rec.get("text_span", "")

    print(f"Read {read:,} verse-level mentions → {len(pairs):,} unique (entity, pericope) pairs")
    return [
        {"entity_id": eid, "pericope_id": pid, "freq": v["freq"], "text_span": v["text_span"]}
        for (eid, pid), v in pairs.items()
    ]


def graph_stats(driver) -> dict:
    with driver.session() as session:
        record = session.run(_STATS_CYPHER).single()
        return dict(record) if record else {}


def backfill(driver, rows: list[dict]) -> dict:
    stats = {"matched": 0, "backfilled": 0, "skipped_missing": 0}
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        with driver.session() as session:
            record = session.run(_MERGE_CYPHER, rows=batch).single()
            matched = int(record["matched"]) if record else 0
            backfilled = int(record["backfilled"]) if record else 0
        stats["matched"] += matched
        stats["backfilled"] += backfilled
        stats["skipped_missing"] += len(batch) - matched
        print(f"  {min(start + BATCH_SIZE, len(rows)):,}/{len(rows):,} pairs "
              f"(new edges so far: {stats['backfilled']:,})")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=str,
                        default=str(Path(__file__).resolve().parents[1] / "output"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Only report what would be backfilled")
    args = parser.parse_args()

    mentions_path = Path(args.output_dir) / "entity_mentions.jsonl"
    if not mentions_path.exists():
        print(f"✗ Not found: {mentions_path}")
        return 2

    rows = collect_verse_pairs(mentions_path)
    if not rows:
        print("Nothing to backfill")
        return 0

    driver = get_driver()
    try:
        before = graph_stats(driver)
        print(f"Before: {before['pericope_mentions']:,} pericope mentions, "
              f"{before['entities_without_pericope_anchor']:,} entities without pericope anchor")

        if args.dry_run:
            print(f"[dry-run] Would MERGE {len(rows):,} (entity, pericope) pairs")
            return 0

        stats = backfill(driver, rows)
        after = graph_stats(driver)

        print("\n" + "=" * 60)
        print("Backfill summary")
        print("=" * 60)
        print(f"  Pairs processed:        {len(rows):,}")
        print(f"  Pairs matched in graph: {stats['matched']:,}")
        print(f"  New edges created:      {stats['backfilled']:,}")
        print(f"  Pairs skipped (missing entity/pericope node): {stats['skipped_missing']:,}")
        print(f"  Pericope mentions: {before['pericope_mentions']:,} → {after['pericope_mentions']:,}")
        print(f"  Entities without pericope anchor: "
              f"{before['entities_without_pericope_anchor']:,} → "
              f"{after['entities_without_pericope_anchor']:,}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
