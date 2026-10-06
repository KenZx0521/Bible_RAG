"""xref 實測探針: the measured side of 模擬等於實測 for cross references (W1 1B;
plan docs/records/2026-10-04_kg_batch1_plan.md §2.2).

Reads a seed file written by `scripts/tools/xref_probe.py seeds` on stdin and
writes {version, params, rows} on stdout, keyed like `xref_probe predict`:
'single:<pid>' and 'q:<qid>' come from retrieve_via_cross_references with the
router's settings (rag_cross_ref_max_hops / rag_cross_ref_expand_limit),
'legacy:<pid>' from retrieve_cross_references with the router's top_k. Each
row is [id, hop, curated, weight] as the returned candidate carries it, so the
retriever call sites (the XREF-3 weights) are measured, not re-implemented.
Logging goes to stderr. Compare with `xref_probe compare --pred P --measured M`.

Every Neo4j session is opened with READ_ACCESS, so session.run (the only form
neo4j_db uses; a test pins it) and begin_transaction are read-only on the
server. execute_write would still open a WRITE transaction, so neither the
probe nor neo4j_db calls it. Postgres is never queried: get_content_by_id is
stubbed for the run.
Both swaps replace module attributes, which is safe only in this process:
never import this module from the app.

Usage, host (pre-deploy), from backend/; NEO4J_* from .env for prod, or
`source scripts/tools/staging.env` first for staging:
    PYTHONPATH=. .venv/bin/python -m probes.xref_measure < seeds.json > measured.json
Deployed code (backend-staging likewise); .venv/bin/python, not uv run, so
nothing syncs:
    docker exec -i bible_rag_backend .venv/bin/python -m probes.xref_measure \\
        < seeds.json > measured.json
"""

import asyncio
import contextlib
import json
import logging
import sys
import time

import neo4j

from config import settings
from database import neo4j_db, postgres
from utils.retrieval import cross_ref_retriever

logger = logging.getLogger(__name__)

LEGACY_TOP_K = 10  # router: retrieve_cross_references(source_ids, top_k=10)


class _ReadOnlyDriver:
    """The real driver, but every session is READ_ACCESS whatever the caller asks."""

    def __init__(self, driver):
        self._driver = driver

    def session(self, **kwargs):
        return self._driver.session(**{**kwargs, "default_access_mode": neo4j.READ_ACCESS})

    async def close(self):
        await self._driver.close()


async def _stub_content(pericope_id: str) -> dict:
    return {"content": ""}  # truthy: the retriever keeps the candidate


@contextlib.contextmanager
def _postgres_stubbed():
    original = postgres.get_content_by_id
    postgres.get_content_by_id = _stub_content
    try:
        yield
    finally:
        postgres.get_content_by_id = original


def _rows(candidates: list[dict]) -> list[list]:
    return [[c["id"], c.get("hop_distance", 1), c["curated"], c["weight"]] for c in candidates]


async def _measure_rows(seeds: dict, max_hops: int, limit: int) -> dict:
    async def expand(ids):
        return _rows(await cross_ref_retriever.retrieve_via_cross_references(
            ids, max_hops=max_hops, limit=limit))

    rows = {}
    for pid in seeds["singles"]:
        rows[f"single:{pid}"] = await expand([pid])
        rows[f"legacy:{pid}"] = _rows(await cross_ref_retriever.retrieve_cross_references(
            [pid], top_k=LEGACY_TOP_K))
    for qid, ids in seeds["sets"].items():
        rows[f"q:{qid}"] = await expand(list(ids))
    return rows


async def measure(seeds: dict) -> dict:
    """{version, params, rows} for one seed file, through the real retrievers."""
    if seeds.get("version") != 1:
        raise ValueError(f"not a version-1 seed file: version {seeds.get('version')!r}")
    params = {"max_hops": settings.rag_cross_ref_max_hops, "limit": settings.rag_cross_ref_expand_limit}
    try:
        neo4j_db._driver = _ReadOnlyDriver(await neo4j_db.init_driver())
        with _postgres_stubbed():
            rows = await _measure_rows(seeds, params["max_hops"], params["limit"])
    finally:
        await neo4j_db.close_driver()
    return {"version": 1, "params": params, "rows": rows}


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.setLevel(logging.INFO)
    seeds = json.load(sys.stdin)
    started = time.monotonic()
    doc = asyncio.run(measure(seeds))
    json.dump(doc, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    logger.info("xref_measure: %d keys (%d singles, %d sets) from %s in %.1f s",
                len(doc["rows"]), len(seeds["singles"]), len(seeds["sets"]),
                settings.neo4j_uri, time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
