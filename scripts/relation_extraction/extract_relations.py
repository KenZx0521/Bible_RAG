"""Orchestrator for the grounded relation extraction pipeline.

Run as:

    python -m scripts.relation_extraction.extract_relations \\
        [--limit-pericopes N] [--no-llm] [--resume]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Iterable, Iterator

from neo4j import GraphDatabase

try:
    import psycopg2
except ImportError as e:
    raise SystemExit("psycopg2 is required for relation extraction (postgres pericope text)") from e

from .config import Neo4jConfig, RELLMConfig, REPipelineConfig
from .grounded_re_classifier import GroundedREClassifier
from .inverse_materializer import materialize_inverses
from .models import ExtractedRelation, ExtractionPhase, RelationCandidate
from .pair_miner import list_pericopes_with_entities, mine_pairs
from .priors_loader import load_priors, resolve_priors
from .rule_classifier import classify_by_rules
from .schema_loader import RelationSchema

logger = logging.getLogger("relation_extraction")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-pericopes", type=int, default=None,
                        help="Process only the first N pericopes (debug aid).")
    parser.add_argument("--pericope-id", type=str, default=None,
                        help="Process only this single pericope id.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip Phase R4 LLM classification (rules + priors only).")
    parser.add_argument("--no-priors", action="store_true",
                        help="Skip Phase R3 priors loading.")
    parser.add_argument("--no-inverse", action="store_true",
                        help="Skip Phase R5 inverse materialization.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip pairs already present in checkpoint file.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _build_pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "bible_rag"),
        user=os.getenv("POSTGRES_USER", "bible"),
        password=os.getenv("POSTGRES_PASSWORD", "bible_password"),
    )


def _read_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("pair_key")
            if key:
                seen.add(key)
    logger.info("Checkpoint: %d pair_keys already processed", len(seen))
    return seen


def _checkpoint_writer(path: Path, resume: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a" if resume else "w", encoding="utf-8")


def _persist_results(triples: Iterable[ExtractedRelation], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for t in triples:
            f.write(t.to_jsonl() + "\n")
            count += 1
    return count


def _dedup_triples(triples: list[ExtractedRelation]) -> list[ExtractedRelation]:
    by_key: dict[tuple, ExtractedRelation] = {}
    for t in triples:
        key = (t.head_id, t.tail_id, t.relation)
        existing = by_key.get(key)
        if existing is None or t.confidence > existing.confidence:
            by_key[key] = t
    return list(by_key.values())


def _select_pericopes(driver, args) -> list[str]:
    if args.pericope_id:
        return [args.pericope_id]
    records = list_pericopes_with_entities(driver)
    ids = [r["pericope_id"] for r in records]
    if args.limit_pericopes:
        ids = ids[:args.limit_pericopes]
    return ids


def _stream_with_checkpoint(
    candidates: Iterable[RelationCandidate],
    seen: set[str],
    checkpoint_fp,
) -> Iterator[RelationCandidate]:
    for cand in candidates:
        if cand.pair_key in seen:
            continue
        yield cand
        seen.add(cand.pair_key)
        checkpoint_fp.write(json.dumps({"pair_key": cand.pair_key}, ensure_ascii=False) + "\n")
        checkpoint_fp.flush()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    pipeline_cfg = REPipelineConfig.from_env()
    llm_cfg = RELLMConfig.from_env()
    neo4j_cfg = Neo4jConfig.from_env()

    logger.info("Loading schema from %s", pipeline_cfg.schema_path)
    schema = RelationSchema.load(pipeline_cfg.schema_path)
    logger.info("Schema has %d relations", len(schema))

    seen = _read_checkpoint(pipeline_cfg.checkpoint_path) if args.resume else set()

    driver = GraphDatabase.driver(neo4j_cfg.uri, auth=(neo4j_cfg.user, neo4j_cfg.password))
    pg_conn = _build_pg_connection()

    all_triples: list[ExtractedRelation] = []
    unclassified_pairs: list[RelationCandidate] = []

    try:
        prior_keys: set[tuple[str, str, str]] = set()
        if not args.no_priors:
            logger.info("Phase R3: loading priors from %s", pipeline_cfg.priors_path)
            priors = load_priors(pipeline_cfg.priors_path)
            prior_triples = resolve_priors(driver, priors, schema)
            all_triples.extend(prior_triples)
            prior_keys = {(t.head_id, t.tail_id, t.relation) for t in prior_triples}

        pericope_ids = _select_pericopes(driver, args)
        if not pericope_ids:
            logger.warning("No pericopes selected — pipeline exiting")
            return 1
        logger.info("Phase R1: mining pairs across %d pericopes", len(pericope_ids))

        pair_iter = mine_pairs(driver, pg_conn, schema, pipeline_cfg, pericope_ids=pericope_ids)

        with _checkpoint_writer(pipeline_cfg.checkpoint_path, args.resume) as ckpt_fp:
            tracked = _stream_with_checkpoint(pair_iter, seen, ckpt_fp)

            llm_pending: list[RelationCandidate] = []
            rule_hits = 0
            for cand in tracked:
                rule_match = classify_by_rules(cand, schema)
                if rule_match and rule_match.confidence >= pipeline_cfg.rule_confidence_floor:
                    key = (rule_match.head_id, rule_match.tail_id, rule_match.relation)
                    if key not in prior_keys:
                        all_triples.append(rule_match)
                        rule_hits += 1
                    continue
                llm_pending.append(cand)

            logger.info("Phase R2: %d rule-hit triples", rule_hits)

            if llm_pending and not args.no_llm:
                logger.info("Phase R4: %d candidates queued for LLM (model=%s)",
                            len(llm_pending), llm_cfg.model)
                with GroundedREClassifier(llm_cfg) as llm:
                    llm_triples = llm.classify_batch(llm_pending, schema)
                llm_triples = [
                    t for t in llm_triples
                    if (t.head_id, t.tail_id, t.relation) not in prior_keys
                ]
                logger.info("Phase R4: kept %d triples after prior dedup", len(llm_triples))
                all_triples.extend(llm_triples)

                classified_pair_keys = {
                    f"{min(t.head_id, t.tail_id)}|{max(t.head_id, t.tail_id)}|{t.source_pericope_id}"
                    for t in llm_triples
                }
                seen_pairs: set[str] = set()
                for cand in llm_pending:
                    if cand.pair_key in seen_pairs:
                        continue
                    seen_pairs.add(cand.pair_key)
                    if cand.pair_key not in classified_pair_keys:
                        unclassified_pairs.append(cand)
            elif llm_pending:
                logger.info("Phase R4 skipped (--no-llm); %d pairs left unclassified",
                            len(llm_pending))
                unclassified_pairs.extend(llm_pending)

        if not args.no_inverse:
            inverses = materialize_inverses(all_triples, schema)
            all_triples.extend(inverses)

        all_triples = _dedup_triples(all_triples)
        out_count = _persist_results(all_triples, pipeline_cfg.output_path)
        logger.info("Wrote %d triples to %s", out_count, pipeline_cfg.output_path)

        if unclassified_pairs:
            with pipeline_cfg.unclassified_path.open("w", encoding="utf-8") as f:
                for cand in unclassified_pairs:
                    f.write(json.dumps({
                        "head_id": cand.head_id,
                        "tail_id": cand.tail_id,
                        "head_type": cand.head_type,
                        "tail_type": cand.tail_type,
                        "head_canonical": cand.head_canonical,
                        "tail_canonical": cand.tail_canonical,
                        "source_pericope_id": cand.source_pericope_id,
                    }, ensure_ascii=False) + "\n")
            logger.info("Wrote %d unclassified pairs to %s",
                        len(unclassified_pairs), pipeline_cfg.unclassified_path)

        by_phase: dict[int, int] = {}
        for t in all_triples:
            by_phase[int(t.extraction_phase)] = by_phase.get(int(t.extraction_phase), 0) + 1
        for phase, count in sorted(by_phase.items()):
            logger.info("  phase %d (%s): %d", phase, ExtractionPhase(phase).name, count)

    finally:
        pg_conn.close()
        driver.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
