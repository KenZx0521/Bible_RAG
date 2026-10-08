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

GT v1 judges a source relevant when its verses overlap the reference
(relevance_judge) and expands the reference over the legacy chapter table
(verse_coverage). GT v2 scores on its slot universe with the ruler of the
build under test (slot_coverage): a source is relevant when it holds a gold
slot, and gold is the item's gold_slots. NDCG's grades stay reference-based.
"""

from __future__ import annotations

import math

from ..gt_v2 import GroundTruthItemV2
from ..models import EvalSample, MetricResult, SourceInfo
from ..reference_parser import parse_reference
from ..relevance_judge import binary_relevance, graded_relevance, estimate_total_relevant
from ..slot_coverage import SlotRuler
from ..verse_coverage import verse_level_metrics

_ALL_METRIC_NAMES = [
    "precision_at_k", "recall_at_k", "f1_at_k", "mrr", "map_at_k",
    "ndcg_at_k", "hit_rate", "verse_recall_at_k", "anchor_coverage_at_k",
]
_MAX_GRADE = 3


def _require_matching_ruler(sample: EvalSample, ruler: SlotRuler | None) -> None:
    if isinstance(sample.ground_truth, GroundTruthItemV2) != (ruler is not None):
        raise ValueError(f"{sample.question_id}: GT v2 items are scored with a slot ruler, "
                         "GT v1 items without one")


def gold_flags(sample: EvalSample, sources: list[SourceInfo],
               ruler: SlotRuler | None = None) -> list[bool]:
    """Per source: does it hold gold? (v1: reference overlap; v2: a gold slot on the ruler)."""
    _require_matching_ruler(sample, ruler)
    if ruler is None:
        gt_refs = parse_reference(sample.ground_truth.reference)
        return [bool(gt_refs) and binary_relevance(s, gt_refs) for s in sources]
    gold = frozenset(sample.ground_truth.gold_slots)
    return [bool(ruler.map_source(s) & gold) for s in sources]


def _verse_metrics(sample: EvalSample, sources: list[SourceInfo],
                   ruler: SlotRuler | None) -> tuple[float, float]:
    """(verse_recall, anchor_coverage): v1 on the chapter table, v2 on the slot ruler."""
    _require_matching_ruler(sample, ruler)
    if ruler is None:
        return verse_level_metrics(parse_reference(sample.ground_truth.reference), sources)
    return ruler.verse_metrics(sample.ground_truth, sources)


def _ndcg(grades: list[int], total_relevant: int, k: int) -> float:
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(grades))
    # Ideal: grades sorted descending, or max grades for total_relevant items when longer
    ideal = sorted(grades, reverse=True)
    ideal_full = [_MAX_GRADE] * min(total_relevant, k)
    if len(ideal_full) > len(ideal):
        ideal = ideal_full
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
    return dcg / idcg if idcg > 0 else 0.0


def _unit_metrics(rels: list[bool], grades: list[int], total_relevant: int,
                  k: int) -> dict[str, float]:
    relevant_count = sum(rels)
    precision = relevant_count / k if k > 0 else 0.0
    recall = min(relevant_count / total_relevant, 1.0) if total_relevant > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    mrr = next((1.0 / (i + 1) for i, r in enumerate(rels) if r), 0.0)
    hits, cum_precision = 0, 0.0
    for i, r in enumerate(rels):
        if r:
            hits += 1
            cum_precision += hits / (i + 1)
    map_k = min(cum_precision / total_relevant, 1.0) if total_relevant > 0 else 0.0
    return {
        "precision_at_k": precision, "recall_at_k": recall, "f1_at_k": f1, "mrr": mrr,
        "map_at_k": map_k, "ndcg_at_k": _ndcg(grades, total_relevant, k),
        "hit_rate": 1.0 if any(rels) else 0.0,
    }


def _compute_for_sample(sample: EvalSample, k: int = 5,
                        ruler: SlotRuler | None = None) -> list[MetricResult]:
    """Compute all retrieval metrics for one sample."""
    gt_refs = parse_reference(sample.ground_truth.reference)
    sources = sample.sources[:k]
    if not gt_refs or not sources:
        return [MetricResult(name=n, value=0.0, category="retrieval") for n in _ALL_METRIC_NAMES]

    values = _unit_metrics(gold_flags(sample, sources, ruler),
                           [graded_relevance(s, gt_refs) for s in sources],
                           estimate_total_relevant(gt_refs), k)
    verse_recall, anchor_coverage = _verse_metrics(sample, sources, ruler)
    return [
        *(MetricResult(name=name, value=round(value, 4), category="retrieval")
          for name, value in values.items()),
        MetricResult(name="verse_recall_at_k", value=verse_recall, category="retrieval"),
        MetricResult(name="anchor_coverage_at_k", value=anchor_coverage, category="retrieval"),
    ]


def compute_retrieval_metrics(samples: list[EvalSample], k: int = 5,
                              ruler: SlotRuler | None = None) -> dict[str, list[MetricResult]]:
    """
    Compute retrieval metrics for all samples (``ruler``: the build's slot
    ruler, required for GT v2 items).

    Returns: { question_id: [MetricResult, ...] }
    """
    return {s.question_id: _compute_for_sample(s, k=k, ruler=ruler) for s in samples}
