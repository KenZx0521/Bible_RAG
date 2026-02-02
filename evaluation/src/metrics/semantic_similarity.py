"""
Semantic similarity between RAG answer and reference answer using sentence-transformers.
"""

from __future__ import annotations

import numpy as np
from rich.console import Console

from ..models import EvalSample, MetricResult

console = Console()


def compute_semantic_similarity(samples: list[EvalSample]) -> dict[str, list[MetricResult]]:
    """
    Compute cosine similarity between RAG answer and reference answer.

    Uses a multilingual sentence-transformer model.

    Returns: { question_id: [MetricResult, ...] }
    """
    from sentence_transformers import SentenceTransformer

    console.print("[dim]Loading sentence-transformers model...[/dim]")
    model = SentenceTransformer("BAAI/bge-m3")

    results: dict[str, list[MetricResult]] = {}

    hyps = []
    refs = []
    valid_ids = []

    for sample in samples:
        if not sample.rag_answer or not sample.reference_answer:
            results[sample.question_id] = [
                MetricResult(name="semantic_similarity", value=0.0, category="semantic")
            ]
            continue
        hyps.append(sample.rag_answer)
        refs.append(sample.reference_answer)
        valid_ids.append(sample.question_id)

    if hyps:
        console.print(f"[dim]Encoding {len(hyps)} pairs...[/dim]")
        hyp_embeds = model.encode(hyps, normalize_embeddings=True, show_progress_bar=False)
        ref_embeds = model.encode(refs, normalize_embeddings=True, show_progress_bar=False)

        # Cosine similarity (already normalized)
        similarities = np.sum(hyp_embeds * ref_embeds, axis=1)

        for qid, sim in zip(valid_ids, similarities):
            results[qid] = [
                MetricResult(
                    name="semantic_similarity",
                    value=round(float(sim), 4),
                    category="semantic",
                )
            ]

    console.print(f"[green]Semantic similarity computed for {len(results)} samples.[/green]")
    return results
