#!/usr/bin/env python3
"""Backfill entity aliases from the curated dictionary into Neo4j (P0 repair).

Only 35 / 9,122 entities carry aliases in the live graph, so alias-based
fallbacks in backend Cypher (``any(a IN e.aliases WHERE ...)``) never fire.
This script writes the PERSON/PLACE/GROUP dictionaries from
``entity_extraction/entity_dict.py`` onto matching graph nodes as native
LIST properties (never json.dumps — the backend queries need real lists).

Matching (per type, conservative):
  Tier 1: node.canonical_name == dictionary canonical key.
  Tier 2: node.canonical_name equals a dictionary alias that maps to exactly
          one canonical within that type (ambiguous aliases like Person
          「西門」/「猶大」 are skipped and reported).

Existing aliases are merged, never overwritten; the node's own
canonical_name is excluded from its alias list.

Usage:
    uv run python backfill_aliases.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_DICTS = {
    "Person": PERSON_DICT,
    "Place": PLACE_DICT,
    "Group": GROUP_DICT,
}

_UPDATE_CYPHER = """
UNWIND $rows AS row
MATCH (e:%(label)s:Entity) WHERE e.canonical_name = row.match_name
WITH e, coalesce(e.aliases, []) + row.aliases AS combined
SET e.aliases = apoc.coll.toSet([x IN combined WHERE x <> e.canonical_name])
RETURN count(e) AS updated
"""


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def build_rows(label: str, dictionary: dict, existing_names: set[str]) -> tuple[list[dict], dict]:
    """Build (match_name → aliases) rows for one entity type."""
    # alias → canonicals reverse map to detect ambiguity within this type
    alias_owners: dict[str, set[str]] = defaultdict(set)
    for canonical, aliases in dictionary.items():
        for alias in set(aliases) | {canonical}:
            alias_owners[alias].add(canonical)

    rows: list[dict] = []
    report = {"tier1": 0, "tier2": 0, "ambiguous_skipped": [], "not_in_graph": []}
    for canonical, aliases in dictionary.items():
        name_pool = sorted(set(aliases) | {canonical})

        if canonical in existing_names:
            payload = [a for a in name_pool if a != canonical]
            if payload:
                rows.append({"match_name": canonical, "aliases": payload})
                report["tier1"] += 1
            continue

        # Tier 2: node named after an unambiguous alias of this entry
        matched = False
        for alias in sorted(set(aliases)):
            if alias == canonical or alias not in existing_names:
                continue
            if len(alias_owners[alias]) > 1:
                report["ambiguous_skipped"].append(f"{alias} → {sorted(alias_owners[alias])}")
                continue
            payload = [a for a in name_pool if a != alias]
            if payload:
                rows.append({"match_name": alias, "aliases": payload})
                report["tier2"] += 1
                matched = True
        if not matched:
            report["not_in_graph"].append(canonical)
    return rows, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    driver = get_driver()
    try:
        with driver.session() as session:
            record = session.run(
                "MATCH (e:Entity) WHERE size(coalesce(e.aliases, [])) > 0 "
                "RETURN count(e) AS with_aliases"
            ).single()
            before_alias_nodes = record["with_aliases"]
        print(f"Before: {before_alias_nodes:,} entities carry aliases")

        total_updated = 0
        for label, dictionary in _DICTS.items():
            with driver.session() as session:
                names = {
                    r["name"] for r in session.run(
                        f"MATCH (e:{label}:Entity) RETURN e.canonical_name AS name"
                    )
                }
            rows, report = build_rows(label, dictionary, names)
            print(f"\n[{label}] dict entries: {len(dictionary)} | "
                  f"tier1 exact: {report['tier1']} | tier2 via-alias: {report['tier2']} | "
                  f"not in graph: {len(report['not_in_graph'])}")
            if report["ambiguous_skipped"]:
                uniq = sorted(set(report["ambiguous_skipped"]))
                print(f"  Ambiguous aliases skipped ({len(uniq)}):")
                for line in uniq:
                    print(f"    {line}")
            if report["not_in_graph"]:
                print(f"  Dict entries without graph node: {report['not_in_graph']}")

            if args.dry_run or not rows:
                continue
            with driver.session() as session:
                record = session.run(_UPDATE_CYPHER % {"label": label}, rows=rows).single()
                updated = record["updated"] if record else 0
            total_updated += updated
            print(f"  → {updated} {label} nodes updated")

        if not args.dry_run:
            with driver.session() as session:
                record = session.run(
                    "MATCH (e:Entity) WHERE size(coalesce(e.aliases, [])) > 0 "
                    "RETURN count(e) AS with_aliases"
                ).single()
            print(f"\nAfter: {record['with_aliases']:,} entities carry aliases "
                  f"(was {before_alias_nodes:,}); {total_updated} nodes written this run")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
