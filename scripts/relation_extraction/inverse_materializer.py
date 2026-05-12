"""Phase R5 — Inverse materialiser.

For every ExtractedRelation whose schema entry declares an `inverse`, emit a
companion ExtractedRelation in the reverse direction. Keeps Cypher queries
simple at the cost of doubling edge count for paired relations.
"""

from __future__ import annotations

import logging

from .models import ExtractedRelation, ExtractionPhase
from .schema_loader import RelationSchema

logger = logging.getLogger(__name__)


def materialize_inverses(
    triples: list[ExtractedRelation],
    schema: RelationSchema,
) -> list[ExtractedRelation]:
    if not triples:
        return []

    existing_keys = {(t.head_id, t.tail_id, t.relation) for t in triples}
    new_triples: list[ExtractedRelation] = []
    skipped_no_inverse = 0
    skipped_dup = 0

    for source in triples:
        entry = schema.get(source.relation)
        if entry is None or not entry.inverse:
            skipped_no_inverse += 1
            continue
        inverse_name = entry.inverse
        inverse_entry = schema.get(inverse_name)
        if inverse_entry is None:
            logger.warning(
                "Schema declares unknown inverse %s for %s — skipping",
                inverse_name, source.relation,
            )
            continue

        key = (source.tail_id, source.head_id, inverse_name)
        if key in existing_keys:
            skipped_dup += 1
            continue

        new_triples.append(ExtractedRelation(
            head_id=source.tail_id,
            tail_id=source.head_id,
            relation=inverse_name,
            confidence=round(source.confidence * 0.9, 4),
            evidence_span=source.evidence_span,
            source_pericope_id=source.source_pericope_id,
            extraction_phase=ExtractionPhase.INVERSE_DERIVED,
            head_canonical=source.tail_canonical,
            tail_canonical=source.head_canonical,
            notes=f"derived_from={source.relation}",
        ))
        existing_keys.add(key)

    logger.info(
        "Inverse materialiser: +%d derived (skipped %d no-inverse, %d duplicate)",
        len(new_triples), skipped_no_inverse, skipped_dup,
    )
    return new_triples
