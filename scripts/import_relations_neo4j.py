#!/usr/bin/env python3
"""Import grounded relation triples into Neo4j.

Reads JSONL output of `scripts.relation_extraction.extract_relations` and
materialises Entity-Entity edges via APOC's `apoc.merge.relationship`
(dynamic relation type, idempotent).

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


_MERGE_RELATION_CYPHER = """
UNWIND $rows AS row
MATCH (head:Entity {entity_id: row.head_id})
MATCH (tail:Entity {entity_id: row.tail_id})
CALL apoc.merge.relationship(
    head,
    $relation,
    {},
    {
      confidence: row.confidence,
      evidence_span: row.evidence_span,
      source_pericope_id: row.source_pericope_id,
      extraction_phase: row.extraction_phase,
      head_canonical: row.head_canonical,
      tail_canonical: row.tail_canonical,
      notes: row.notes
    },
    tail
) YIELD rel
RETURN count(rel) AS written
"""


def _import_batch(driver, relation: str, batch: list[dict]) -> int:
    rows = [{
        "head_id": r["head_id"],
        "tail_id": r["tail_id"],
        "confidence": float(r.get("confidence", 0.5)),
        "evidence_span": (r.get("evidence_span") or "")[:512],
        "source_pericope_id": r.get("source_pericope_id", "") or "",
        "extraction_phase": int(r.get("extraction_phase", 1)),
        "head_canonical": r.get("head_canonical", "") or "",
        "tail_canonical": r.get("tail_canonical", "") or "",
        "notes": r.get("notes", "") or "",
    } for r in batch]
    with driver.session() as session:
        result = session.run(_MERGE_RELATION_CYPHER, rows=rows, relation=relation)
        record = result.single()
        return int(record["written"]) if record else 0


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
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

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

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_password"),
        ),
    )
    total_written = 0
    try:
        for relation, items in by_relation.items():
            batch_count = 0
            for start in range(0, len(items), args.batch_size):
                chunk = items[start:start + args.batch_size]
                batch_count += _import_batch(driver, relation, chunk)
            logger.info("  %s: %d edges merged", relation, batch_count)
            total_written += batch_count
        _summary_stats(driver)
    finally:
        driver.close()

    logger.info("Done. Total relations merged: %d", total_written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
