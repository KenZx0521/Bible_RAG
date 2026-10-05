#!/usr/bin/env python3
"""Import Step 6.05's relation triples into Neo4j (Step 6.1).

Reads output/relations_clean.jsonl, which
`scripts.relation_extraction.relation_postprocess` (Step 6.05) writes from
Step 6's relations.jsonl, and materialises Entity-Entity edges via APOC's
`apoc.merge.relationship` (dynamic relation type, idempotent). Each edge's
properties are replaced wholesale by its file row (the row minus
head_id/relation/tail_id, nulls dropped), whether the edge is new or not, and
every row is written in one write transaction, so a failure leaves no partial
layer.

Only a 6.05 output is imported, and only as its report (the .report.json
beside it, or --report) describes it. Before connecting, the file must hash
to the report's output.sha256 and hold its output.rows rows, every row must
carry the report's pp_version and a head_id, relation, tail_id and source, and
no (head_id, relation, tail_id) key may appear twice; otherwise the run exits
2 and nothing is imported. So a file edited, truncated or stacked after 6.05
never reaches the graph. An undirected pair written both ways is two keys and
passes: the --rules none P1 control keeps such pairs.

Nor is the file stacked on an old layer. The semantic layer is every
Entity-Entity edge but MENTIONS and CROSS_REFERENCES; Step 5 rebuilds the graph
without one, and only 6.1 (and the legacy 10.3) add to it. So a graph that
already holds one is not fresh from Step 5, and the run stops (exit 1) before a
write: "Step 5 empties the graph". --replace, refused outside a staging shell
(kg_target.require_staging) before connecting, instead deletes the whole layer
-- 10.3's edges too -- as the first statement of the transaction that writes
the file, so the layer becomes exactly the file and a failure rolls the delete
back with the writes. The standard chain never passes --replace.

Nothing is skipped silently: one read first lists the endpoints the file
references that the graph lacks, and any missing id stops the run (exit 1)
before a write. Inside the transaction each statement must write exactly as
many edges as it was sent rows, or the whole import rolls back (exit 1).

Usage:
    python scripts/import_relations_neo4j.py [path/to/relations_clean.jsonl] [--report PATH]
        [--replace]

Exit codes: 0 imported (or the file is empty); 1 a semantic layer already in
the graph (without --replace), a missing endpoint or a written mismatch,
nothing written; 2 no input file, or the input contract refused it, before
connecting. --replace outside a staging shell exits before connecting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

import kg_target

load_dotenv()

logger = logging.getLogger("import_relations_neo4j")

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "output" / "relations_clean.jsonl"

# The edge key; every other field of a row is an edge property.
EDGE_KEY = ("head_id", "relation", "tail_id")
# What every row carries as a non-empty string: its key and 6.05's source stamp.
REQUIRED_FIELDS = (*EDGE_KEY, "source")
# How many offending rows or keys a refusal names.
_SHOWN = 10


# --- input contract: 6.05's output, exactly as its report describes it --------

class InputRefused(ValueError):
    """The file is not the 6.05 output its report describes (exit 2, before connecting)."""


def sibling_report(path: Path) -> Path:
    """The report 6.05 writes beside its output: relations_clean.report.json."""
    return path.with_suffix(".report.json")


def _load_report(path: Path) -> tuple[str, str, int]:
    """(pp_version, output.sha256, output.rows) of a 6.05 report."""
    if not path.exists():
        raise InputRefused(f"no 6.05 report at {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        return report["pp_version"], report["output"]["sha256"], report["output"]["rows"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InputRefused(f"{path} is not a 6.05 report: {exc!r}") from exc


def _parse_rows(data: bytes, path: Path) -> list[dict]:
    """One object per non-blank line. Split on '\\n' only, as 6.05 writes them:
    str.splitlines would also split a value that holds U+2028."""
    try:
        rows = [json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip()]
    except ValueError as exc:
        raise InputRefused(f"{path} is not JSON lines: {exc}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise InputRefused(f"{path} has a line that is not a JSON object")
    return rows


def _listed(items: list[str]) -> str:
    return ", ".join(items[:_SHOWN]) + (" ..." if len(items) > _SHOWN else "")


def _check_rows(rows: list[dict], pp_version: str) -> None:
    """Every row has the required fields and the report's pp_version; each key is one row."""
    lacking = [f"row {n}: no {field}" for n, row in enumerate(rows, 1) for field in REQUIRED_FIELDS
               if not (isinstance(row.get(field), str) and row[field])]
    if lacking:
        raise InputRefused(f"{len(lacking)} required field(s) missing: {_listed(lacking)}")
    other = Counter(str(row.get("pp_version")) for row in rows if row.get("pp_version") != pp_version)
    if other:
        raise InputRefused(f"{sum(other.values())} row(s) carry a pp_version other than the "
                           f"report's {pp_version}: {dict(sorted(other.items()))}")
    keys = Counter(tuple(row[key] for key in EDGE_KEY) for row in rows)
    dup = sorted(" ".join(key) for key, n in keys.items() if n > 1)
    if dup:
        raise InputRefused(f"{len(dup)} key(s) have two or more rows (one edge per key): {_listed(dup)}")


def read_checked(path: Path, report_path: Path) -> list[dict]:
    """The rows of a 6.05 output; InputRefused when the file is not what its report describes."""
    pp_version, sha256, n_rows = _load_report(report_path)
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        raise InputRefused(f"{path} hashes to {actual}, not the report's output.sha256 {sha256} "
                           f"(edited, truncated or stacked after 6.05?)")
    rows = _parse_rows(data, path)
    if len(rows) != n_rows:
        raise InputRefused(f"{path} has {len(rows)} row(s); the report says {n_rows}")
    _check_rows(rows, pp_version)
    return rows


# --- import -------------------------------------------------------------------

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


# The semantic layer 6.1 writes: every Entity-Entity edge but MENTIONS and
# CROSS_REFERENCES. Step 5's own edges join Book/Chapter/Pericope/Chunk nodes,
# and 10.4/10.5 add only MENTIONS, so after Step 5 the layer is empty.
_LAYER = """
MATCH (:Entity)-[r]->(:Entity)
WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']
"""
_COUNT_LAYER_CYPHER = _LAYER + "RETURN count(r) AS edges\n"
_DELETE_LAYER_CYPHER = _LAYER + "DELETE r\nRETURN count(r) AS edges\n"


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


def _layer_edges(tx, query: str = _COUNT_LAYER_CYPHER) -> int:
    """Transaction function: the semantic layer's edge count (or, given the
    delete, how many it deleted)."""
    record = tx.run(query).single()
    return int(record["edges"]) if record else 0


def _report_layer(edges: int) -> None:
    logger.error("The graph already holds %d semantic edge(s) (Entity-Entity, not MENTIONS or "
                 "CROSS_REFERENCES); nothing written. Step 5 empties the graph, and 6.1 runs "
                 "right after it, so this would stack the file on an old layer. To rebuild "
                 "the layer on staging, run with --replace from a shell that sourced "
                 "scripts/tools/staging.env.", edges)


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


def _replace_all(tx, rows: list[dict], batch_size: int) -> tuple[int, int]:
    """Transaction function for --replace: delete the layer, then write every
    row. (deleted, written); a WrittenMismatch rolls the delete back too."""
    deleted = _layer_edges(tx, _DELETE_LAYER_CYPHER)
    return deleted, _write_all(tx, rows, batch_size)


def _write(session, rows: list[dict], batch_size: int, replace: bool) -> int:
    """The one write transaction; with replace, its first statement deletes the layer."""
    if not replace:
        return session.execute_write(_write_all, rows, batch_size)
    deleted, written = session.execute_write(_replace_all, rows, batch_size)
    logger.warning("--replace: deleted the old layer's %d edge(s) in the same transaction",
                   deleted)
    return written


def _import_rows(driver, rows: list[dict], batch_size: int, path: Path,
                 replace: bool = False) -> int:
    """Empty-layer guard (unless replace) and endpoint pre-check, then one write
    transaction. Returns the exit code."""
    with driver.session() as session:
        edges = 0 if replace else session.execute_read(_layer_edges)
        if edges:
            _report_layer(edges)
            return 1
        missing = session.execute_read(_missing_endpoints, _endpoint_ids(rows))
        if missing:
            _report_missing(missing, rows, path)
            return 1
        try:
            written = _write(session, rows, batch_size, replace)
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_PATH,
        help="Step 6.05's output (default: output/relations_clean.jsonl)",
    )
    parser.add_argument("--report", type=Path, default=None,
                        help="6.05's report on that file (default: the .report.json beside it)")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="rows per statement; every statement is in one transaction")
    parser.add_argument("--replace", action="store_true",
                        help="staging only (needs a shell that sourced scripts/tools/staging.env): "
                             "delete the whole semantic layer, 10.3's edges too, in the "
                             "transaction that writes the file; the standard chain never passes it")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    kg_target.assert_target("neo4j")
    if args.replace:
        logger.warning("--replace: the semantic layer of %s will be deleted and rewritten",
                       kg_target.require_staging("neo4j")["neo4j"])

    in_path = args.path
    if not in_path.exists():
        logger.error("relations file not found: %s (Step 6.05 writes it: "
                     "python -m scripts.relation_extraction.relation_postprocess)", in_path)
        return 2
    report_path = args.report or sibling_report(in_path)
    logger.info("Reading triples from %s, checked against %s", in_path, report_path)
    try:
        records = read_checked(in_path, report_path)
    except InputRefused as exc:
        logger.error("Refused before connecting, nothing imported: %s", exc)
        return 2
    if not records:
        logger.warning("Empty relations file — nothing to import")
        return 0

    logger.info("Loaded %d triples spanning %d relation types",
                len(records), len({rec["relation"] for rec in records}))
    rows = _edge_rows(records)

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "neo4j_password"),
        ),
    )
    try:
        return _import_rows(driver, rows, args.batch_size, in_path, args.replace)
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
