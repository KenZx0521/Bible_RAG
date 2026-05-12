"""Load biblical_priors.yaml and resolve entity ids against Neo4j.

Each prior is realised as an ExtractedRelation with extraction_phase=DOMAIN_PRIOR.
Priors override LLM output for the same (head, relation, tail) triple — they
encode biblical scholarship consensus that should not be re-derived.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import ExtractedRelation, ExtractionPhase
from .schema_loader import RelationSchema

logger = logging.getLogger(__name__)


@dataclass
class PriorRecord:
    head_canonical: str
    relation: str
    tail_canonical: str
    source: str = ""
    notes: str = ""


def load_priors(path: Path) -> list[PriorRecord]:
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML required for priors loading") from e

    if not path.exists():
        logger.warning("Priors file not found: %s — skipping", path)
        return []

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw = data.get("priors", []) or []
    out: list[PriorRecord] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        head = (entry.get("head_canonical") or "").strip()
        rel = (entry.get("relation") or "").strip()
        tail = (entry.get("tail_canonical") or "").strip()
        if not (head and rel and tail):
            continue
        out.append(PriorRecord(
            head_canonical=head,
            relation=rel,
            tail_canonical=tail,
            source=str(entry.get("source") or ""),
            notes=str(entry.get("notes") or ""),
        ))
    logger.info("Loaded %d biblical priors from %s", len(out), path)
    return out


def _query_canonical_to_ids(driver, names: Iterable[str]) -> dict[str, list[dict]]:
    """Map canonical_name -> list of {entity_id, type}. Multiple matches kept
    so caller can disambiguate by type (relation domain/range)."""
    name_set = sorted(set(n for n in names if n))
    if not name_set:
        return {}

    cypher = (
        "UNWIND $names AS nm "
        "MATCH (e) WHERE (e:Person OR e:Place OR e:Group OR e:Event OR e:Object OR e:Theme) "
        "  AND e.canonical_name = nm "
        "RETURN nm AS name, e.entity_id AS entity_id, "
        "       [l IN labels(e) WHERE l <> 'Entity'][0] AS type"
    )
    result: dict[str, list[dict]] = defaultdict(list)
    with driver.session() as session:
        records = session.run(cypher, names=name_set)
        for record in records:
            result[record["name"]].append({
                "entity_id": record["entity_id"],
                "type": record["type"],
            })
    return dict(result)


def resolve_priors(
    driver,
    priors: list[PriorRecord],
    schema: RelationSchema,
) -> list[ExtractedRelation]:
    """Resolve canonical names to entity ids, filtering with schema typing."""
    if not priors:
        return []

    canonicals = {p.head_canonical for p in priors} | {p.tail_canonical for p in priors}
    lookup = _query_canonical_to_ids(driver, canonicals)

    extracted: list[ExtractedRelation] = []
    skipped_missing = 0
    skipped_typing = 0
    skipped_unknown_rel = 0

    for prior in priors:
        entry = schema.get(prior.relation)
        if entry is None:
            logger.warning("Prior references unknown relation %s — skipping", prior.relation)
            skipped_unknown_rel += 1
            continue

        head_options = lookup.get(prior.head_canonical, [])
        tail_options = lookup.get(prior.tail_canonical, [])
        if not head_options or not tail_options:
            logger.debug(
                "Prior unresolved: %s -[%s]-> %s",
                prior.head_canonical, prior.relation, prior.tail_canonical,
            )
            skipped_missing += 1
            continue

        chosen = None
        for h in head_options:
            for t in tail_options:
                if entry.accepts_pair(h["type"], t["type"]):
                    chosen = (h, t)
                    break
            if chosen:
                break
        if not chosen:
            logger.warning(
                "Prior typing mismatch for %s -[%s]-> %s (head_types=%s tail_types=%s)",
                prior.head_canonical, prior.relation, prior.tail_canonical,
                [h["type"] for h in head_options], [t["type"] for t in tail_options],
            )
            skipped_typing += 1
            continue

        head, tail = chosen
        if head["entity_id"] == tail["entity_id"]:
            continue

        extracted.append(ExtractedRelation(
            head_id=head["entity_id"],
            tail_id=tail["entity_id"],
            relation=prior.relation,
            confidence=entry.confidence_for(ExtractionPhase.DOMAIN_PRIOR),
            evidence_span=prior.source,
            source_pericope_id="",
            extraction_phase=ExtractionPhase.DOMAIN_PRIOR,
            head_canonical=prior.head_canonical,
            tail_canonical=prior.tail_canonical,
            notes=prior.notes,
        ))

    logger.info(
        "Priors resolved: %d ok / %d unresolved / %d typing-mismatch / %d unknown-rel",
        len(extracted), skipped_missing, skipped_typing, skipped_unknown_rel,
    )
    return extracted
