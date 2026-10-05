#!/usr/bin/env python3
"""Import grounded relation triples into Neo4j.

Reads JSONL output of `scripts.relation_extraction.extract_relations` and
materialises Entity-Entity edges via APOC's `apoc.merge.relationship`
(dynamic relation type, idempotent). Each edge's properties are replaced
wholesale by its file row (the row minus head_id/relation/tail_id, nulls
dropped), whether the edge is new or not, and every row is written in one
write transaction, so a failure leaves no partial layer.

Usage:
    python scripts/import_relations_neo4j.py [path/to/relations.jsonl]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from neo4j import GraphDatabase

import kg_target

load_dotenv()

logger = logging.getLogger("import_relations_neo4j")


def _read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _bucket_by_relation(records: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for rec in records:
        rel = rec.get("relation")
        if not rel:
            continue
        out.setdefault(rel, []).append(rec)
    return out


# The edge key; every other field of a row is an edge property.
EDGE_KEY = ("head_id", "relation", "tail_id")

# No onCreate/onMatch maps: SET rel = props replaces every property, so an
# edge an earlier import left behind cannot keep stale values (REL-10).
_MERGE_RELATION_CYPHER = """
UNWIND $rows AS row
MATCH (h:Entity {entity_id: row.head_id})
MATCH (t:Entity {entity_id: row.tail_id})
CALL apoc.merge.relationship(h, row.relation, {}, {}, t, {}) YIELD rel
SET rel = row.props
RETURN count(rel) AS written
"""


def _edge_rows(records: list[dict]) -> list[dict]:
    """One query row per edge: its key, and the rest of the file row as props."""
    return [{
        **{key: rec.get(key) for key in EDGE_KEY},
        "props": {k: v for k, v in rec.items() if k not in EDGE_KEY and v is not None},
    } for rec in records]


def _write_all(tx, rows: list[dict], batch_size: int) -> int:
    """Transaction function: every batch in the same transaction."""
    written = 0
    for start in range(0, len(rows), batch_size):
        record = tx.run(_MERGE_RELATION_CYPHER, rows=rows[start:start + batch_size]).single()
        written += int(record["written"]) if record else 0
    return written


def _summary_stats(driver) -> None:
    with driver.session() as session:
        result = session.run(
            """
            MATCH ()-[r]->()
            WHERE NOT type(r) IN ['CONTAINS','NEXT','NEXT_BOOK','MENTIONS','CROSS_REFERENCES']
            RETURN type(r) AS rel, count(*) AS n
            ORDER BY n DESC
            LIMIT 25
            """
        )
        rows = [dict(record) for record in result]
    if not rows:
        logger.info("No Entity-Entity relations present yet.")
        return
    logger.info("Top relation counts after import:")
    for row in rows:
        logger.info("  %s: %d", row["rel"], row["n"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "output" / "relations.jsonl"),
        help="Path to relations.jsonl",
    )
    parser.add_argument("--batch-size", type=int, default=500,
                        help="rows per statement; every statement is in one transaction")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    kg_target.assert_target("neo4j")

    in_path = Path(args.path)
    if not in_path.exists():
        logger.error("relations file not found: %s", in_path)
        return 2

    logger.info("Reading triples from %s", in_path)
    records = list(_read_jsonl(in_path))
    if not records:
        logger.warning("Empty relations file — nothing to import")
        return 0

    by_relation = _bucket_by_relation(records)
    logger.info("Loaded %d triples spanning %d relation types", len(records), len(by_relation))
    rows = _edge_rows([rec for rec in records if rec.get("relation")])

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_password"),
        ),
    )
    try:
        with driver.session() as session:
            total_written = session.execute_write(_write_all, rows, args.batch_size)
        _summary_stats(driver)
    finally:
        driver.close()

    logger.info("Done. Total relations merged: %d", total_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
