"""Phase R1 — Co-mention pair miner.

For each pericope with >=2 mentioned entities, generate type-allowed candidate
pairs and attach grounding text (the pericope content, optionally pre-trimmed
to a verse window). Output is RelationCandidate per pair.
"""

from __future__ import annotations

import logging
from itertools import combinations
from typing import Iterator

from .config import REPipelineConfig
from .models import RelationCandidate
from .schema_loader import RelationSchema

logger = logging.getLogger(__name__)


_PERICOPE_ENTITIES_CYPHER = """
MATCH (p:Pericope)-[:MENTIONS]-(e:Entity)
WHERE p.id IN $pericope_ids
RETURN p.id AS pericope_id,
       collect(DISTINCT {
         entity_id: e.entity_id,
         canonical_name: e.canonical_name,
         type: [l IN labels(e) WHERE l <> 'Entity'][0]
       }) AS entities
"""

_ALL_PERICOPE_IDS_CYPHER = """
MATCH (p:Pericope)
WHERE EXISTS { MATCH (p)-[:MENTIONS]-(:Entity) }
RETURN p.id AS pericope_id, p.title AS title, p.book_name AS book_name
ORDER BY p.id
"""


def list_pericopes_with_entities(driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(_ALL_PERICOPE_IDS_CYPHER)
        return [dict(record) for record in result]


def fetch_pericope_entities(driver, pericope_ids: list[str]) -> dict[str, list[dict]]:
    if not pericope_ids:
        return {}
    with driver.session() as session:
        result = session.run(_PERICOPE_ENTITIES_CYPHER, pericope_ids=pericope_ids)
        return {row["pericope_id"]: list(row["entities"]) for row in result}


def fetch_pericope_text(pg_conn, pericope_ids: list[str]) -> dict[str, str]:
    """Fetch text keyed by pericope_id from the `pericopes` table."""
    if not pericope_ids:
        return {}
    cur = pg_conn.cursor()
    try:
        cur.execute(
            "SELECT id, content FROM pericopes WHERE id = ANY(%s)",
            (pericope_ids,),
        )
        return {row[0]: (row[1] or "") for row in cur.fetchall()}
    finally:
        cur.close()


def _trim_grounding(text: str, name_a: str, name_b: str, window: int) -> str:
    """Smallest substring covering both names plus +/- window 'verse' lines."""
    if not text or window <= 0:
        return text[:1500]
    if name_a not in text or name_b not in text:
        return text[:1500]

    parts = text.split("\n")
    a_idx = next((i for i, p in enumerate(parts) if name_a in p), None)
    b_idx = next((i for i, p in enumerate(parts) if name_b in p), None)
    if a_idx is None or b_idx is None:
        return text[:1500]

    lo = max(0, min(a_idx, b_idx) - window)
    hi = min(len(parts), max(a_idx, b_idx) + window + 1)
    return "\n".join(parts[lo:hi])[:1500]


def mine_pairs(
    driver,
    pg_conn,
    schema: RelationSchema,
    config: REPipelineConfig,
    pericope_ids: list[str] | None = None,
) -> Iterator[RelationCandidate]:
    if pericope_ids is None:
        pericope_records = list_pericopes_with_entities(driver)
        pericope_ids = [r["pericope_id"] for r in pericope_records]

    if not pericope_ids:
        logger.info("pair_miner: no pericopes with mentions found")
        return

    BATCH = 200
    total_pairs = 0
    skipped_typing = 0

    for start in range(0, len(pericope_ids), BATCH):
        batch_ids = pericope_ids[start:start + BATCH]
        ents_by_pericope = fetch_pericope_entities(driver, batch_ids)
        text_by_pericope = fetch_pericope_text(pg_conn, batch_ids)

        for pid in batch_ids:
            entities = ents_by_pericope.get(pid, [])
            if len(entities) < 2:
                continue
            ents_sorted = sorted(entities, key=lambda x: x["entity_id"])

            text = text_by_pericope.get(pid, "")
            pericope_pair_count = 0
            for a, b in combinations(ents_sorted, 2):
                if config.skip_self_loops and a["entity_id"] == b["entity_id"]:
                    continue
                allowed = bool(schema.candidates_for(a["type"], b["type"])) or bool(
                    schema.candidates_for(b["type"], a["type"])
                )
                if not allowed:
                    skipped_typing += 1
                    continue

                grounding = _trim_grounding(
                    text,
                    a["canonical_name"] or "",
                    b["canonical_name"] or "",
                    config.grounding_window,
                )

                yield RelationCandidate(
                    head_id=a["entity_id"],
                    tail_id=b["entity_id"],
                    head_type=a["type"],
                    tail_type=b["type"],
                    head_canonical=a["canonical_name"] or "",
                    tail_canonical=b["canonical_name"] or "",
                    source_pericope_id=pid,
                    grounding_text=grounding,
                )

                pericope_pair_count += 1
                total_pairs += 1
                if pericope_pair_count >= config.max_pairs_per_pericope:
                    break

    logger.info(
        "pair_miner emitted %d candidate pairs (skipped %d type-mismatched)",
        total_pairs, skipped_typing,
    )
