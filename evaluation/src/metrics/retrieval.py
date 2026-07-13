"""
Custom retrieval metrics for Bible RAG evaluation.

Computes 9 metrics at k (default k=5):

  Verse-level (primary readout, deterministic, added 2026-07-13):
  - verse_recall_at_k     true verse coverage of the gold reference span
  - anchor_coverage_at_k  fraction of chapter-level gold anchors hit

  Unit-level (kept for backward comparability with historical runs —
  ⚠️ chapter ranges count as 1 unit, so these are systematically inflated
  for multi-chapter questions; see relevance_judge.estimate_total_relevant):
  - Precision@k / Recall@k / F1@k / MRR / MAP@k / NDCG@k / Hit Rate
"""

from __future__ import annotations

import math

from ..models import EvalSample, MetricResult
from ..reference_parser import parse_reference
from ..relevance_judge import binary_relevance, graded_relevance, estimate_total_relevant
from ..verse_coverage import verse_level_metrics

_ALL_METRIC_NAMES = [
    "precision_at_k", "recall_at_k", "f1_at_k", "mrr", "map_at_k",
    "ndcg_at_k", "hit_rate", "verse_recall_at_k", "anchor_coverage_at_k",
]


def _compute_for_sample(sample: EvalSample, k: int = 5) -> list[MetricResult]:
    """Compute all retrieval metrics for one sample."""
    gt_refs = parse_reference(sample.ground_truth.reference)
    sources = sample.sources[:k]

    if not gt_refs or not sources:
        return [
            MetricResult(name=n, value=0.0, category="retrieval")
            for n in _ALL_METRIC_NAMES
        ]

    # Binary relevance list
    rels = [binary_relevance(s, gt_refs) for s in sources]
    # Graded relevance list
    grades = [graded_relevance(s, gt_refs) for s in sources]

    relevant_count = sum(rels)
    total_relevant = estimate_total_relevant(gt_refs)

    # Precision@k
    precision = relevant_count / k if k > 0 else 0.0

    # Recall@k
    recall = relevant_count / total_relevant if total_relevant > 0 else 0.0
    recall = min(recall, 1.0)

    # F1@k
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # MRR
    mrr = 0.0
    for i, r in enumerate(rels):
        if r:
            mrr = 1.0 / (i + 1)
            break

    # MAP@k
    cum_precision = 0.0
    hits = 0
    for i, r in enumerate(rels):
        if r:
            hits += 1
            cum_precision += hits / (i + 1)
    map_k = cum_precision / total_relevant if total_relevant > 0 else 0.0
    map_k = min(map_k, 1.0)

    # NDCG@k (graded)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(grades))
    # Ideal: sort grades descending, pad with max grade for total_relevant items
    ideal_grades = sorted(grades, reverse=True)
    # If total_relevant > len(grades), assume perfect grades for the remaining
    max_grade = 3
    ideal_full = [max_grade] * min(total_relevant, k)
    # Use whichever is longer for ideal
    if len(ideal_full) > len(ideal_grades):
        ideal_grades = ideal_full
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal_grades[:k]))
    ndcg = dcg / idcg if idcg > 0 else 0.0

    # Hit Rate
    hit_rate = 1.0 if any(rels) else 0.0

    # Verse-level metrics (deterministic, no inflation from chapter ranges)
    verse_recall, anchor_coverage = verse_level_metrics(gt_refs, sources)

    return [
        MetricResult(name="precision_at_k", value=round(precision, 4), category="retrieval"),
        MetricResult(name="recall_at_k", value=round(recall, 4), category="retrieval"),
        MetricResult(name="f1_at_k", value=round(f1, 4), category="retrieval"),
        MetricResult(name="mrr", value=round(mrr, 4), category="retrieval"),
        MetricResult(name="map_at_k", value=round(map_k, 4), category="retrieval"),
        MetricResult(name="ndcg_at_k", value=round(ndcg, 4), category="retrieval"),
        MetricResult(name="hit_rate", value=round(hit_rate, 4), category="retrieval"),
        MetricResult(name="verse_recall_at_k", value=verse_recall, category="retrieval"),
        MetricResult(name="anchor_coverage_at_k", value=anchor_coverage, category="retrieval"),
    ]


def compute_retrieval_metrics(samples: list[EvalSample], k: int = 5) -> dict[str, list[MetricResult]]:
    """
    Compute retrieval metrics for all samples.

    Returns: { question_id: [MetricResult, ...] }
    """
    results: dict[str, list[MetricResult]] = {}
    for sample in samples:
        results[sample.question_id] = _compute_for_sample(sample, k=k)
    return results
