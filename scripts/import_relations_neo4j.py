#!/usr/bin/env python3
"""Import grounded relation triples into Neo4j.

Reads JSONL output of `scripts.relation_extraction.extract_relations` and
materialises Entity-Entity edges via APOC's `apoc.merge.relationship`
(dynamic relation type, idempotent). Each edge's properties are replaced
wholesale by its file row (the row minus head_id/relation/tail_id, nulls
dropped), whether the edge is new or not, and every row is written in one
write transaction, so a failure leaves no partial layer.

Nothing is skipped silently: one read first lists the endpoints the file
references that the graph lacks, and any missing id stops the run (exit 1)
before a write. Inside the transaction each statement must write exactly as
many edges as it was sent rows, or the whole import rolls back (exit 1).

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


# The referenced ids no :Entity carries. An id on two nodes is not missing
# here; the written check catches it (MATCH then yields two node pairs).
_MISSING_ENDPOINTS_CYPHER = """
UNWIND $ids AS id
OPTIONAL MATCH (e:Entity {entity_id: id})
WITH id, count(e) AS found
WHERE found = 0
RETURN id
"""


class WrittenMismatch(RuntimeError):
    """A statement wrote a different number of edges than it was sent rows.

    Raised inside the transaction function, so the driver rolls back (it only
    retries its own transient errors)."""


def _edge_rows(records: list[dict]) -> list[dict]:
    """One query row per edge: its key, and the rest of the file row as props."""
    return [{
        **{key: rec.get(key) for key in EDGE_KEY},
        "props": {k: v for k, v in rec.items() if k not in EDGE_KEY and v is not None},
    } for rec in records]


def _endpoint_ids(rows: list[dict]) -> list[str]:
    return sorted({row[key] for row in rows for key in ("head_id", "tail_id")
                   if row[key] is not None})


def _missing_endpoints(tx, ids: list[str]) -> list[str]:
    """Read transaction function: the ids no :Entity carries."""
    return sorted(record["id"] for record in tx.run(_MISSING_ENDPOINTS_CYPHER, ids=ids))


def _report_missing(missing: list[str], rows: list[dict], path: Path) -> None:
    absent = set(missing)
    hit = sum(1 for row in rows if row["head_id"] in absent or row["tail_id"] in absent)
    logger.error("%d endpoint(s) used by %d row(s) of %s are not in the graph; "
                 "nothing written: %s", len(missing), hit, path, ", ".join(missing))


def _write_all(tx, rows: list[dict], batch_size: int) -> int:
    """Transaction function: every batch in the same transaction, each checked."""
    written = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        record = tx.run(_MERGE_RELATION_CYPHER, rows=batch).single()
        n = int(record["written"]) if record else 0
        if n != len(batch):
            raise WrittenMismatch(f"rows {start}-{start + len(batch) - 1}: "
                                  f"wrote {n} edge(s) for {len(batch)} row(s)")
        written += n
    return written


def _import_rows(driver, rows: list[dict], batch_size: int, path: Path) -> int:
    """Endpoint pre-check, then one write transaction. Returns the exit code."""
    with driver.session() as session:
        missing = session.execute_read(_missing_endpoints, _endpoint_ids(rows))
        if missing:
            _report_missing(missing, rows, path)
            return 1
        try:
            written = session.execute_write(_write_all, rows, batch_size)
        except WrittenMismatch as exc:
            logger.error("Rolled back, nothing written: %s", exc)
            return 1
    _summary_stats(driver)
    logger.info("Done. Total relations merged: %d (= rows)", written)
    return 0


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
        return _import_rows(driver, rows, args.batch_size, in_path)
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
