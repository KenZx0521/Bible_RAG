#!/usr/bin/env python3
"""
Entity Extraction Script for Bible RAG System.

Default: Grounded pipeline (bible_md → Pericope Mining → POS → Rules → LLM Classifier)
Legacy:  --legacy-llm uses old open-ended LLM extraction

Staged (rebuilds): freeze the grounded Event/Object/Theme half once (Phase 4
LLM verdicts have no cache), then re-run only NER and merge the two halves.

Usage:
    # Grounded pipeline (new default)
    python scripts/extract_entities.py --bible-md-dir bible_md --output-dir output
    python scripts/extract_entities.py --bible-md-dir bible_md --sample 50

    # Staged Step 1 (rebuilds)
    python scripts/extract_entities.py --stage freeze-grounded   # once, from a full build
    python scripts/extract_entities.py --stage ner               # CKIP only, ~30 min
    python scripts/extract_entities.py --stage merge             # -> entities.jsonl
    # ner writes ner_manifest.json; merge refuses a sampled or unrecorded NER
    # half, or one extracted from another queue than -i (default
    # output/embedding_queue.jsonl), and freeze refuses an empty/partial
    # grounded half without --force.
    # A re-freeze that moves the grounded half >5% also needs
    # --accept-grounded-drift (see entity_extraction/stages.py).

    # Legacy NER only: entities.jsonl WITHOUT Event/Object/Theme
    python scripts/extract_entities.py --ner-only --force

    # Legacy LLM pipeline
    python scripts/extract_entities.py --legacy-llm
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_extraction.models import (
    Entity, EntityMention, EntityCandidate, EntityType, ExtractionMethod,
)
from entity_extraction.ner_extractor import NERExtractor
from entity_extraction.llm_extractor import LLMExtractor, extract_entities_batch
from entity_extraction.entity_normalizer import normalize_and_merge
from entity_extraction.config import (
    LLMConfig, CKIPConfig, ExtractionConfig,
    EntityExtractLLMConfig, GroundedConfig,
)
from entity_extraction.stages import (
    ENTITIES_FILE, GROUNDED_DRIFT_TOLERANCE, GROUNDED_TYPES, MENTIONS_FILE,
    NER_ENTITIES_FILE, NER_MANIFEST_FILE, NER_MENTIONS_FILE, StageError,
    entity_sort_key, file_sha256, freeze_grounded, merge_stage, write_ner_manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_embedding_queue(input_path: Path) -> List[Dict]:
    """Load items from embedding_queue.jsonl."""
    items = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    logger.info(f"Loaded {len(items)} items from {input_path}")
    return items


def save_entities(entities: Dict[str, Entity], output_path: Path):
    """Save entities to JSONL file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for entity in sorted(entities.values(),
                             key=lambda e: entity_sort_key(e.type.value, e.mention_count)):
            f.write(entity.to_json() + "\n")
    logger.info(f"Saved {len(entities)} entities to {output_path}")


def save_mentions(mentions: List[EntityMention], output_path: Path):
    """Save mentions to JSONL file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for mention in mentions:
            f.write(mention.to_json() + "\n")
    logger.info(f"Saved {len(mentions)} mentions to {output_path}")


def run_ner_extraction(
    items: List[Dict],
    ckip_config: CKIPConfig,
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """Run NER extraction for Person, Place, Group entities."""
    logger.info("Starting NER extraction (Person, Place, Group)...")

    extractor = NERExtractor(use_gpu=ckip_config.use_gpu)

    try:
        from tqdm import tqdm
        items_iter = tqdm(items, desc="NER Extraction")
    except ImportError:
        items_iter = items

    all_entities: Dict[str, Entity] = {}
    all_mentions: List[EntityMention] = []

    for item in items_iter:
        try:
            entities, mentions = extractor.extract_from_text(
                text=item["text"],
                source_id=item["id"],
                source_type=item["type"],
            )

            for entity in entities:
                if entity.entity_id not in all_entities:
                    all_entities[entity.entity_id] = entity
                else:
                    all_entities[entity.entity_id].mention_count += entity.mention_count
                    for alias in entity.aliases:
                        if alias not in all_entities[entity.entity_id].aliases:
                            all_entities[entity.entity_id].aliases.append(alias)

            all_mentions.extend(mentions)

        except Exception as e:
            logger.error(f"NER extraction failed for {item.get('id')}: {e}")

    logger.info(f"NER extracted {len(all_entities)} unique entities, {len(all_mentions)} mentions")
    return all_entities, all_mentions


def run_llm_extraction(
    items: List[Dict],
    llm_config: LLMConfig,
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """Run legacy LLM extraction for Event, Object, Theme entities."""
    logger.info(f"Starting LLM extraction (Event, Object, Theme) using {llm_config.provider}...")

    extractor = LLMExtractor(config=llm_config)
    all_entities, all_mentions = extract_entities_batch(extractor, items, show_progress=True)

    logger.info(f"LLM extracted {len(all_entities)} unique entities, {len(all_mentions)} mentions")
    return all_entities, all_mentions


def _generate_entity_id(entity_type: EntityType, name: str) -> str:
    """Generate a unique entity ID from type + name."""
    try:
        from pypinyin import lazy_pinyin
        pinyin = "".join(lazy_pinyin(name))
    except ImportError:
        pinyin = name.replace(" ", "_").lower()
    return f"{entity_type.value.lower()}:{pinyin}"


def _candidates_to_entities(
    candidates: List[EntityCandidate],
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """Convert classified EntityCandidates into Entity + EntityMention objects."""
    entities: Dict[str, Entity] = {}
    mentions: List[EntityMention] = []
    mention_counter = 0

    for c in candidates:
        if c.proposed_type is None:
            continue
        if c.proposed_type not in GROUNDED_TYPES:
            continue

        entity_id = _generate_entity_id(c.proposed_type, c.name)

        # Determine extraction method from phase
        method_map = {
            1: ExtractionMethod.PERICOPE_TITLE,
            2: ExtractionMethod.POS_TAG,
            3: ExtractionMethod.RULE,
            4: ExtractionMethod.GROUNDED_LLM,
        }
        method = method_map.get(c.extraction_phase, ExtractionMethod.RULE)

        if entity_id not in entities:
            entities[entity_id] = Entity(
                entity_id=entity_id,
                type=c.proposed_type,
                canonical_name=c.name,
                description=c.evidence or c.grounding_text[:100] if c.grounding_text else "",
                extraction_method=method,
                mention_count=c.frequency,
            )
        else:
            entities[entity_id].mention_count += c.frequency

        # Create mentions from source_ids
        for src_id in c.source_ids:
            mention_counter += 1
            mentions.append(EntityMention(
                mention_id=f"m:{src_id}:{mention_counter:04d}",
                entity_id=entity_id,
                source_id=src_id,
                source_type="pericope",
                text_span=c.name,
                context=c.grounding_text[:100] if c.grounding_text else "",
            ))

    return entities, mentions


def run_grounded_extraction(
    bible_md_dir: Path,
    grounded_config: GroundedConfig,
    llm_config: EntityExtractLLMConfig,
    ckip_config: CKIPConfig,
    phase: str = "all",
    sample: int | None = None,
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """
    Run the grounded entity extraction pipeline (Phases 1-4).

    Args:
        bible_md_dir: Path to bible_md/ directory.
        grounded_config: Pipeline parameters (min_freq, rule_confidence).
        llm_config: LLM config for Phase 4.
        ckip_config: CKIP config for Phase 2.
        phase: Which phase to run ("1", "2", "3", "4", "all").
        sample: Limit pericopes to first N (for testing).
    """
    from entity_extraction.bible_md_parser import parse_all_bible_md
    from entity_extraction.pericope_miner import mine_pericope_titles
    from entity_extraction.rule_classifier import classify_candidates

    # Parse bible_md
    logger.info(f"Parsing bible_md from {bible_md_dir}...")
    pericopes = parse_all_bible_md(bible_md_dir)

    if sample:
        pericopes = pericopes[:sample]
        logger.info(f"Using sample of {len(pericopes)} pericopes")

    all_candidates: List[EntityCandidate] = []

    # Phase 1: Pericope Title Mining
    if phase in ("1", "all"):
        logger.info("=== Phase 1: Pericope Title Mining ===")
        phase1_candidates = mine_pericope_titles(pericopes)
        all_candidates.extend(phase1_candidates)
        if phase == "1":
            return _candidates_to_entities(all_candidates)

    # Phase 2: CKIP POS Tagging
    if phase in ("2", "all"):
        logger.info("=== Phase 2: CKIP POS Tagging ===")
        from entity_extraction.pos_extractor import CkipPosExtractor
        pos_extractor = CkipPosExtractor(use_gpu=ckip_config.use_gpu)
        phase2_candidates = pos_extractor.extract_candidates(
            pericopes, min_freq=grounded_config.min_freq,
        )
        all_candidates.extend(phase2_candidates)
        if phase == "2":
            return _candidates_to_entities(all_candidates)

    # Deduplicate candidates by name before Phase 3
    deduped: Dict[str, EntityCandidate] = {}
    for c in all_candidates:
        if c.name in deduped:
            existing = deduped[c.name]
            existing.frequency += c.frequency
            existing.source_ids.extend(c.source_ids)
            # Keep higher confidence
            if c.confidence > existing.confidence:
                existing.proposed_type = c.proposed_type
                existing.confidence = c.confidence
                existing.grounding_text = c.grounding_text
        else:
            deduped[c.name] = c
    all_candidates = list(deduped.values())
    logger.info(f"After dedup: {len(all_candidates)} unique candidates")

    # Phase 3: Rule-based Classification
    if phase in ("3", "all"):
        logger.info("=== Phase 3: Rule-based Classification ===")
        classified, unclassified = classify_candidates(
            all_candidates, rule_confidence=grounded_config.rule_confidence,
        )
        if phase == "3":
            return _candidates_to_entities(classified + unclassified)

    # Phase 4: LLM-as-Classifier
    if phase in ("4", "all"):
        logger.info("=== Phase 4: LLM-as-Classifier (Grounded) ===")
        if unclassified:
            from entity_extraction.grounded_classifier import GroundedClassifier
            classifier = GroundedClassifier(config=llm_config)
            llm_classified = classifier.classify_batch(unclassified)
            final_candidates = classified + llm_classified
        else:
            final_candidates = classified
    else:
        final_candidates = all_candidates

    return _candidates_to_entities(final_candidates)


def extract_ner_half(input_path: Path, ckip_config: CKIPConfig, sample: int | None = None
                     ) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """NER normalised alone == the monolithic NER half (merges stay in-type)."""
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    items = load_embedding_queue(input_path)
    if sample:
        items = items[:sample]
    ner_entities, ner_mentions = run_ner_extraction(items, ckip_config)
    return normalize_and_merge(ner_entities, {}, ner_mentions, [])


def _run_snapshot_stage(args: argparse.Namespace) -> None:
    """Dispatch --stage freeze-grounded / merge (pure file work, no models)."""
    frozen_dir = args.output_dir / "frozen"
    try:
        if args.stage == "freeze-grounded":
            freeze_grounded(args.output_dir / ENTITIES_FILE, args.output_dir / MENTIONS_FILE,
                            frozen_dir, force=args.force, dry_run=args.dry_run,
                            accept_drift=args.accept_grounded_drift)
        else:
            merge_stage(args.output_dir, frozen_dir, args.input, force=args.force,
                        dry_run=args.dry_run)
    except StageError as e:
        logger.error(str(e))
        sys.exit(1)


def main(argv: List[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Extract entities from Bible text."
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("output/embedding_queue.jsonl"),
        help="Input JSONL file path (default: output/embedding_queue.jsonl); "
             "--stage merge checks that ner_*.jsonl were extracted from it"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path("output"),
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--sample", "-s",
        type=int,
        default=None,
        help="Process only first N items/pericopes (for testing)"
    )
    parser.add_argument(
        "--ner-only",
        action="store_true",
        help="Legacy: entities.jsonl from NER only, drops Event/Object/Theme (needs --force)"
    )
    parser.add_argument(
        "--stage",
        choices=["ner", "freeze-grounded", "merge"],
        default=None,
        help="Staged Step 1; frozen grounded half lives in <output-dir>/frozen"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow --ner-only; re-freezing or freezing an empty/partial grounded half; "
             "merging a sampled/unrecorded/stale NER half or over a grounded half that "
             "differs"
    )
    parser.add_argument(
        "--accept-grounded-drift",
        action="store_true",
        help=f"--stage freeze-grounded: allow the new grounded half to differ by more than "
             f"{GROUNDED_DRIFT_TOLERANCE * 100:g}%% in line count from the snapshot it replaces"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="--stage freeze-grounded / merge: verify and report, write nothing"
    )
    parser.add_argument(
        "--legacy-llm",
        action="store_true",
        help="Use legacy open-ended LLM pipeline instead of grounded"
    )
    parser.add_argument(
        "--bible-md-dir",
        type=Path,
        default=Path("bible_md"),
        help="bible_md directory path (default: bible_md)"
    )
    parser.add_argument(
        "--phase",
        choices=["1", "2", "3", "4", "all"],
        default="all",
        help="Run only a specific phase of grounded pipeline (debug)"
    )
    parser.add_argument(
        "--min-freq",
        type=int,
        default=None,
        help="Override Phase 2 minimum frequency threshold"
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Use GPU for CKIP models"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=None,
        help="Seconds between LLM API calls (overrides .env)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args(argv)

    if args.stage and (args.ner_only or args.legacy_llm):
        parser.error("--stage cannot be combined with --ner-only or --legacy-llm")
    if args.dry_run and args.stage not in ("freeze-grounded", "merge"):
        parser.error("--dry-run only applies to --stage freeze-grounded / merge")
    if args.accept_grounded_drift and args.stage != "freeze-grounded":
        parser.error("--accept-grounded-drift only applies to --stage freeze-grounded")
    # Refuse before any model loads: a forgotten --ner-only silently wiped the
    # whole Event/Object/Theme half, which has no other reproducible source.
    if args.ner_only and not args.force:
        logger.error("--ner-only overwrites entities.jsonl / entity_mentions.jsonl with NER "
                     "only, dropping every Event/Object/Theme entity. Use --stage ner (writes "
                     "ner_*.jsonl) then --stage merge, or pass --force to overwrite anyway.")
        sys.exit(1)
    if args.stage in ("freeze-grounded", "merge"):
        _run_snapshot_stage(args)
        return

    # Load configurations
    llm_config = LLMConfig.from_env()
    ckip_config = CKIPConfig.from_env()
    extraction_config = ExtractionConfig.from_env()
    entity_extract_llm_config = EntityExtractLLMConfig.from_env()
    grounded_config = GroundedConfig.from_env()

    # CLI overrides
    if args.verbose or extraction_config.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.gpu:
        ckip_config.use_gpu = True
    if args.rate_limit:
        llm_config.rate_limit_delay = args.rate_limit
        entity_extract_llm_config.rate_limit_delay = args.rate_limit
    if args.min_freq is not None:
        grounded_config.min_freq = args.min_freq

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Decide pipeline ──

    if args.stage == "ner":
        if args.sample:
            logger.warning(f"--sample {args.sample}: ner_*.jsonl will hold a partial NER "
                           f"half; --stage merge refuses it without --force")
        queue_sha256 = file_sha256(args.input)  # what NER reads, not what is there after
        entities, mentions = extract_ner_half(args.input, ckip_config, args.sample)
        # Drop the old manifest before replacing the files it vouches for, so
        # a crash between the writes leaves no manifest rather than a stale one.
        (args.output_dir / NER_MANIFEST_FILE).unlink(missing_ok=True)
        save_entities(entities, args.output_dir / NER_ENTITIES_FILE)
        save_mentions(mentions, args.output_dir / NER_MENTIONS_FILE)
        write_ner_manifest(args.output_dir, args.input, args.sample, queue_sha256)
        logger.info("NER stage complete; next: --stage merge")
        return

    if args.ner_only:
        # Legacy NER only (--force given): overwrites entities.jsonl below
        all_entities, all_mentions = extract_ner_half(args.input, ckip_config, args.sample)

    elif args.legacy_llm:
        # Legacy LLM pipeline (old behavior)
        if not args.input.exists():
            logger.error(f"Input file not found: {args.input}")
            sys.exit(1)
        items = load_embedding_queue(args.input)
        if args.sample:
            items = items[:args.sample]

        ner_entities: Dict[str, Entity] = {}
        ner_mentions: List[EntityMention] = []
        llm_entities: Dict[str, Entity] = {}
        llm_mentions: List[EntityMention] = []

        ner_entities, ner_mentions = run_ner_extraction(items, ckip_config)
        llm_entities, llm_mentions = run_llm_extraction(items, llm_config)

        all_entities, all_mentions = normalize_and_merge(
            ner_entities, llm_entities, ner_mentions, llm_mentions,
        )

    else:
        # New default: Grounded pipeline
        if not args.bible_md_dir.exists():
            logger.error(f"bible_md directory not found: {args.bible_md_dir}")
            sys.exit(1)

        grounded_entities, grounded_mentions = run_grounded_extraction(
            bible_md_dir=args.bible_md_dir,
            grounded_config=grounded_config,
            llm_config=entity_extract_llm_config,
            ckip_config=ckip_config,
            phase=args.phase,
            sample=args.sample,
        )

        # Also run NER if embedding_queue exists
        ner_entities: Dict[str, Entity] = {}
        ner_mentions: List[EntityMention] = []
        if args.input.exists():
            items = load_embedding_queue(args.input)
            if args.sample:
                items = items[:args.sample]
            ner_entities, ner_mentions = run_ner_extraction(items, ckip_config)

        all_entities, all_mentions = normalize_and_merge(
            ner_entities, grounded_entities, ner_mentions, grounded_mentions,
        )

    # Print statistics
    type_counts: Dict[str, int] = {}
    for entity in all_entities.values():
        type_name = entity.type.value
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    logger.info("Entity type distribution:")
    for type_name, count in sorted(type_counts.items()):
        logger.info(f"  {type_name}: {count}")

    # Save results
    entities_path = args.output_dir / "entities.jsonl"
    mentions_path = args.output_dir / "entity_mentions.jsonl"

    save_entities(all_entities, entities_path)
    save_mentions(all_mentions, mentions_path)

    logger.info("Entity extraction complete!")
    logger.info(f"  Total entities: {len(all_entities)}")
    logger.info(f"  Total mentions: {len(all_mentions)}")


if __name__ == "__main__":
    main()
