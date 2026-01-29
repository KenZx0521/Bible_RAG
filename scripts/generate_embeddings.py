#!/usr/bin/env python3
"""
Embeddings Generation Script for Bible RAG System.

Generates BGE-M3 embeddings for chunks from embedding_queue.jsonl.

Usage:
    # Generate embeddings for all items
    python scripts/generate_embeddings.py

    # With custom options
    python scripts/generate_embeddings.py --batch-size 64 --device cuda

    # Test with limited items
    python scripts/generate_embeddings.py --limit 10 --output output/test_embeddings.jsonl
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Iterator, Optional

from tqdm import tqdm

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.embeddings.embedder import BGEEmbedder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_items(input_path: Path, limit: Optional[int] = None) -> List[Dict]:
    """Load items from JSONL file."""
    items = []
    with open(input_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            items.append(json.loads(line))
    return items


def save_embedding(f, item_id: str, item_type: str, embedding: List[float]):
    """Save a single embedding to JSONL file."""
    record = {
        "id": item_id,
        "type": item_type,
        "embedding": embedding,
    }
    f.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate_embeddings(
    input_path: Path,
    output_path: Path,
    batch_size: int = 32,
    device: Optional[str] = None,
    limit: Optional[int] = None,
):
    """
    Generate embeddings for all items in input file.
    
    Args:
        input_path: Path to embedding_queue.jsonl.
        output_path: Path to output embeddings.jsonl.
        batch_size: Batch size for encoding.
        device: Device to use ('cuda' or 'cpu').
        limit: Optional limit on number of items to process.
    """
    # Load items
    logger.info(f"Loading items from {input_path}...")
    items = load_items(input_path, limit)
    total_items = len(items)
    logger.info(f"Loaded {total_items} items")
    
    if total_items == 0:
        logger.warning("No items to process")
        return
    
    # Initialize embedder
    logger.info("Initializing BGE-M3 embedder...")
    embedder = BGEEmbedder(device=device)
    
    # Process in batches
    logger.info(f"Generating embeddings with batch_size={batch_size}...")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    processed = 0
    with open(output_path, "w", encoding="utf-8") as f:
        # Process in batches
        for batch_start in tqdm(range(0, total_items, batch_size), desc="Batches"):
            batch_end = min(batch_start + batch_size, total_items)
            batch_items = items[batch_start:batch_end]
            
            # Extract texts
            texts = [item["text"] for item in batch_items]
            
            # Generate embeddings
            embeddings = embedder.encode_batch(texts, batch_size=batch_size, show_progress=False)
            
            # Save embeddings
            for item, embedding in zip(batch_items, embeddings):
                save_embedding(f, item["id"], item["type"], embedding)
                processed += 1
    
    logger.info(f"Generated {processed} embeddings")
    logger.info(f"Output saved to {output_path}")
    
    # Validate output
    validate_output(output_path, processed)


def validate_output(output_path: Path, expected_count: int):
    """Validate the output file."""
    actual_count = 0
    sample_dims = None
    
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            actual_count += 1
            if sample_dims is None:
                sample_dims = len(record["embedding"])
    
    if actual_count != expected_count:
        logger.warning(f"Count mismatch: expected {expected_count}, got {actual_count}")
    else:
        logger.info(f"✓ Output validation passed: {actual_count} embeddings, {sample_dims} dimensions each")


def main():
    parser = argparse.ArgumentParser(
        description="Generate BGE-M3 embeddings for Bible RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/embedding_queue.jsonl"),
        help="Input JSONL file (default: output/embedding_queue.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/embeddings.jsonl"),
        help="Output JSONL file (default: output/embeddings.jsonl)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for encoding (default: 32)",
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["cuda", "cpu"],
        default=None,
        help="Device to use (default: auto-detect)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to process (for testing)",
    )
    
    args = parser.parse_args()
    
    # Validate input file exists
    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)
    
    # Generate embeddings
    generate_embeddings(
        input_path=args.input,
        output_path=args.output,
        batch_size=args.batch_size,
        device=args.device,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
