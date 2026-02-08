#!/usr/bin/env python3
"""
Sparse Vector Generation Script for Bible RAG Hybrid Search.

Generates BM25-based sparse vectors using CKIP tokenization for Chinese text.
Outputs: sparse_vectors.jsonl and bm25_vocabulary.json

Usage:
    # Generate sparse vectors for all items
    python scripts/generate_sparse_vectors.py

    # With custom options
    python scripts/generate_sparse_vectors.py --batch-size 64 --use-gpu

    # Test with limited items
    python scripts/generate_sparse_vectors.py --limit 100
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sparse_encoding import CKIPTokenizer, BM25SparseEncoder

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


def save_sparse_vector(
    f,
    item_id: str,
    item_type: str,
    indices: List[int],
    values: List[float],
):
    """Save a single sparse vector to JSONL file."""
    record = {
        "id": item_id,
        "type": item_type,
        "sparse_vector": {
            "indices": indices,
            "values": values,
        }
    }
    f.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate_sparse_vectors(
    input_path: Path,
    output_path: Path,
    vocab_path: Path,
    batch_size: int = 32,
    use_gpu: bool = False,
    limit: Optional[int] = None,
):
    """
    Generate BM25 sparse vectors for all items in input file.

    Args:
        input_path: Path to embedding_queue.jsonl.
        output_path: Path to output sparse_vectors.jsonl.
        vocab_path: Path to save BM25 vocabulary.
        batch_size: Batch size for processing.
        use_gpu: Whether to use GPU for CKIP.
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

    # Initialize tokenizer
    logger.info(f"Initializing CKIP tokenizer (GPU: {use_gpu})...")
    tokenizer = CKIPTokenizer(use_gpu=use_gpu)

    # Initialize BM25 encoder
    logger.info("Initializing BM25 encoder...")
    encoder = BM25SparseEncoder(tokenizer=tokenizer)

    # Extract all texts for fitting
    texts = [item["text"] for item in items]

    # Fit the encoder on all documents
    logger.info("Fitting BM25 encoder on corpus...")
    encoder.fit(texts, show_progress=True)

    # Save vocabulary
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoder.save(vocab_path)
    logger.info(f"Vocabulary saved to {vocab_path}")

    # Generate sparse vectors
    logger.info(f"Generating sparse vectors with batch_size={batch_size}...")

    processed = 0
    total_nonzero = 0

    with open(output_path, "w", encoding="utf-8") as f:
        # Process in batches
        for batch_start in tqdm(range(0, total_items, batch_size), desc="Generating"):
            batch_end = min(batch_start + batch_size, total_items)
            batch_items = items[batch_start:batch_end]

            # Extract texts
            batch_texts = [item["text"] for item in batch_items]

            # Encode batch
            sparse_vectors = encoder.encode_batch(batch_texts, show_progress=False)

            # Save sparse vectors
            for item, (indices, values) in zip(batch_items, sparse_vectors):
                save_sparse_vector(f, item["id"], item["type"], indices, values)
                processed += 1
                total_nonzero += len(indices)

    avg_nonzero = total_nonzero / processed if processed > 0 else 0
    logger.info(f"Generated {processed} sparse vectors")
    logger.info(f"Average non-zero elements per vector: {avg_nonzero:.2f}")
    logger.info(f"Vocabulary size: {encoder.get_vocabulary_size()}")
    logger.info(f"Output saved to {output_path}")

    # Validate output
    validate_output(output_path, processed)

    # Print top IDF terms
    logger.info("\nTop 20 terms by IDF score:")
    for term, idf in encoder.get_top_idf_terms(20):
        logger.info(f"  {term}: {idf:.4f}")


def validate_output(output_path: Path, expected_count: int):
    """Validate the output file."""
    actual_count = 0
    empty_count = 0

    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            actual_count += 1
            if not record["sparse_vector"]["indices"]:
                empty_count += 1

    if actual_count != expected_count:
        logger.warning(f"Count mismatch: expected {expected_count}, got {actual_count}")
    else:
        logger.info(f"✓ Output validation passed: {actual_count} sparse vectors")

    if empty_count > 0:
        logger.warning(f"  {empty_count} vectors are empty (no non-zero elements)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate BM25 sparse vectors for Bible RAG hybrid search",
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
        default=Path("output/sparse_vectors.jsonl"),
        help="Output JSONL file (default: output/sparse_vectors.jsonl)",
    )
    parser.add_argument(
        "--vocab",
        type=Path,
        default=Path("output/bm25_vocabulary.json"),
        help="BM25 vocabulary output file (default: output/bm25_vocabulary.json)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for processing (default: 32)",
    )
    parser.add_argument(
        "--use-gpu",
        action="store_true",
        default=False,
        help="Use GPU for CKIP tokenization",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to process (for testing)",
    )

    args = parser.parse_args()

    # Check CKIP_USE_GPU from environment
    if os.environ.get("CKIP_USE_GPU", "").lower() == "true":
        args.use_gpu = True

    # Validate input file exists
    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Generate sparse vectors
    generate_sparse_vectors(
        input_path=args.input,
        output_path=args.output,
        vocab_path=args.vocab,
        batch_size=args.batch_size,
        use_gpu=args.use_gpu,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
