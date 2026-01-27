#!/usr/bin/env python3
"""
Entity Extraction Script for Bible RAG System.

Extracts entities from embedding_queue.jsonl using hybrid NER + LLM approach:
- NER (CKIP) for Person, Place, Group
- LLM (Claude/Gemini/OpenAI) for Event, Object, Theme

Usage:
    python scripts/extract_entities.py --input output/embedding_queue.jsonl --output-dir output
    python scripts/extract_entities.py --input output/embedding_queue.jsonl --output-dir output --sample 10
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from entity_extraction.models import Entity, EntityMention
from entity_extraction.ner_extractor import NERExtractor
from entity_extraction.llm_extractor import LLMExtractor, extract_entities_batch
from entity_extraction.entity_normalizer import normalize_and_merge
from entity_extraction.config import LLMConfig, CKIPConfig, ExtractionConfig

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
        for entity in sorted(entities.values(), key=lambda e: (e.type.value, -e.mention_count)):
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
    """Run LLM extraction for Event, Object, Theme entities."""
    logger.info(f"Starting LLM extraction (Event, Object, Theme) using {llm_config.provider}...")
    
    extractor = LLMExtractor(config=llm_config)
    all_entities, all_mentions = extract_entities_batch(extractor, items, show_progress=True)
    
    logger.info(f"LLM extracted {len(all_entities)} unique entities, {len(all_mentions)} mentions")
    return all_entities, all_mentions


def main():
    parser = argparse.ArgumentParser(
        description="Extract entities from Bible text using hybrid NER + LLM approach."
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("output/embedding_queue.jsonl"),
        help="Input JSONL file path (default: output/embedding_queue.jsonl)"
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
        help="Process only first N items (for testing)"
    )
    parser.add_argument(
        "--ner-only",
        action="store_true",
        help="Run only NER extraction (no LLM calls)"
    )
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="Run only LLM extraction (skip NER)"
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
    
    args = parser.parse_args()
    
    # Load configuration from environment
    llm_config = LLMConfig.from_env()
    ckip_config = CKIPConfig.from_env()
    extraction_config = ExtractionConfig.from_env()
    
    # Override with command line arguments
    if args.verbose or extraction_config.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate input
    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    items = load_embedding_queue(args.input)
    
    # Apply sample limit
    if args.sample:
        items = items[:args.sample]
        logger.info(f"Processing sample of {len(items)} items")
    
    # Initialize results
    ner_entities: Dict[str, Entity] = {}
    ner_mentions: List[EntityMention] = []
    llm_entities: Dict[str, Entity] = {}
    llm_mentions: List[EntityMention] = []
    
    # Run NER extraction
    if not args.llm_only:
        # Override GPU setting if specified
        if args.gpu:
            ckip_config.use_gpu = True
        ner_entities, ner_mentions = run_ner_extraction(items, ckip_config)
    
    # Run LLM extraction
    if not args.ner_only:
        # Override rate limit if specified
        if args.rate_limit:
            llm_config.rate_limit_delay = args.rate_limit
        llm_entities, llm_mentions = run_llm_extraction(items, llm_config)
    
    # Merge and normalize
    logger.info("Normalizing and merging results...")
    all_entities, all_mentions = normalize_and_merge(
        ner_entities, llm_entities,
        ner_mentions, llm_mentions,
    )
    
    # Print statistics
    type_counts = {}
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
