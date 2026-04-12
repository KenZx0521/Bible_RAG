"""
Main evaluation orchestrator.

Coordinates:
  1. RAG response collection + inline Claude evaluation (per-question)
  2. Batch metric computations (retrieval, reference, RAGAS, semantic)
  3. Aggregation by question_type and overall
  4. Saving results to JSON
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import settings
from .models import EvalSample, MetricResult, EvalReport, AggregatedReport, Rationale
from .data_loader import load_ground_truth
from .collector import collect_responses

from .metrics.retrieval import compute_retrieval_metrics
from .metrics.reference_based import compute_reference_metrics
from .metrics.ragas_eval import compute_ragas_metrics
from .metrics.semantic_similarity import compute_semantic_similarity

console = Console()

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def _merge_metrics(
    question_ids: list[str],
    *metric_dicts: dict[str, list[MetricResult]],
) -> dict[str, list[MetricResult]]:
    """Merge multiple metric dicts into one per question_id."""
    merged: dict[str, list[MetricResult]] = defaultdict(list)
    for qid in question_ids:
        for md in metric_dicts:
            if qid in md:
                merged[qid].extend(md[qid])
    return dict(merged)


def _aggregate(
    samples: list[EvalSample],
    all_metrics: dict[str, list[MetricResult]],
    rationales: dict[str, Rationale] | None = None,
) -> AggregatedReport:
    """Build aggregated report: overall averages and by question_type."""
    # Per-sample reports
    reports: list[EvalReport] = []
    for sample in samples:
        report = EvalReport(
            question_id=sample.question_id,
            question_type=sample.question_type,
            metrics=all_metrics.get(sample.question_id, []),
            route_used=sample.route_used,
            strategies_used=sample.strategies_used,
        )
        if rationales and sample.question_id in rationales:
            report.rationale = rationales[sample.question_id]
        reports.append(report)

    # Collect all metric names
    all_names: set[str] = set()
    for ms in all_metrics.values():
        for m in ms:
            all_names.add(m.name)

    # Overall averages
    overall: dict[str, float] = {}
    for name in sorted(all_names):
        vals = [
            m.value
            for ms in all_metrics.values()
            for m in ms
            if m.name == name
        ]
        overall[name] = round(sum(vals) / len(vals), 4) if vals else 0.0

    # By question_type
    type_groups: dict[str, list[str]] = defaultdict(list)
    for sample in samples:
        type_groups[sample.question_type].append(sample.question_id)

    by_type: dict[str, dict[str, float]] = {}
    for qtype, qids in type_groups.items():
        type_avgs: dict[str, float] = {}
        for name in sorted(all_names):
            vals = [
                m.value
                for qid in qids
                for m in all_metrics.get(qid, [])
                if m.name == name
            ]
            type_avgs[name] = round(sum(vals) / len(vals), 4) if vals else 0.0
        by_type[qtype] = type_avgs

    return AggregatedReport(overall=overall, by_type=by_type, samples=reports)


def _save_results(report: AggregatedReport) -> Path:
    """Save evaluation results to JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "evaluation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    return out_path


def _print_summary(report: AggregatedReport) -> None:
    """Print a summary table to the console."""
    table = Table(title="Evaluation Summary (Overall Averages)")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    for name, value in sorted(report.overall.items()):
        table.add_row(name, f"{value:.4f}")

    console.print(table)

    # By type summary
    if report.by_type:
        type_table = Table(title="Averages by Question Type")
        type_table.add_column("Metric", style="cyan")
        for qtype in sorted(report.by_type.keys()):
            type_table.add_column(qtype, justify="right")

        all_names = set()
        for avgs in report.by_type.values():
            all_names.update(avgs.keys())

        for name in sorted(all_names):
            row = [name]
            for qtype in sorted(report.by_type.keys()):
                val = report.by_type[qtype].get(name, 0.0)
                row.append(f"{val:.4f}")
            type_table.add_row(*row)

        console.print(type_table)


async def run_collection() -> tuple[list[EvalSample], dict[str, list[MetricResult]]]:
    """
    Step 1: Collect RAG responses + inline Claude evaluation.

    Returns: (samples, inline_point_coverage_metrics)
    """
    questions = load_ground_truth()
    console.print(f"[bold]Loaded {len(questions)} ground truth questions.[/bold]")
    return await collect_responses(questions)


def run_evaluation(
    samples: list[EvalSample],
    inline_metrics: dict[str, list[MetricResult]] | None = None,
) -> AggregatedReport:
    """
    Step 2: Run batch metrics on collected samples.

    inline_metrics: pre-computed per-question metrics (e.g. point coverage from collection phase).
    """
    console.print("[bold]Starting batch evaluation pipeline...[/bold]")
    question_ids = [s.question_id for s in samples]

    # 1. Retrieval metrics (fast, no LLM)
    console.print("\n[bold cyan]1/4 Retrieval Metrics[/bold cyan]")
    retrieval = compute_retrieval_metrics(samples, k=settings.top_k)

    # 2. Reference-based metrics (BLEU, ROUGE, BERTScore)
    console.print("\n[bold cyan]2/4 Reference-Based Metrics[/bold cyan]")
    reference = compute_reference_metrics(samples)

    # 3. Semantic similarity
    console.print("\n[bold cyan]3/4 Semantic Similarity[/bold cyan]")
    semantic = compute_semantic_similarity(samples)

    # 4. RAGAS (LLM judge) - extracts rationales from traces
    console.print("\n[bold cyan]4/4 RAGAS Evaluation[/bold cyan]")
    ragas, rationales = compute_ragas_metrics(samples)

    # Use inline point coverage if provided, otherwise compute in batch
    if inline_metrics is None:
        from .metrics.llm_judge import compute_llm_judge_metrics
        console.print("\n[bold cyan]Extra: Answer Point Coverage[/bold cyan]")
        inline_metrics = compute_llm_judge_metrics(samples)

    # Merge all metrics
    all_metrics = _merge_metrics(
        question_ids, retrieval, reference, semantic, ragas, inline_metrics
    )

    # Log rationale statistics
    has_rationales = any(
        r.faithfulness or r.relevance or r.context or r.overall
        for r in rationales.values()
    ) if rationales else False

    if has_rationales:
        console.print("[green]Rationales extracted from RAGAS traces.[/green]")
    else:
        console.print("[yellow]No rationales found in RAGAS traces.[/yellow]")

    # Aggregate
    report = _aggregate(samples, all_metrics, rationales)
    _print_summary(report)

    # Save
    out_path = _save_results(report)
    console.print(f"\n[bold green]Results saved to {out_path}[/bold green]")

    return report


def load_results() -> AggregatedReport:
    """Load previously saved evaluation results."""
    path = RESULTS_DIR / "evaluation_results.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return AggregatedReport(**data)


def load_samples_from_checkpoint() -> list[EvalSample]:
    """Reconstruct EvalSample list from raw_responses.json + ground_truth.json."""
    from .models import SourceInfo

    raw_path = RESULTS_DIR / "raw_responses.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"No checkpoint found at {raw_path}")

    with open(raw_path, encoding="utf-8") as f:
        raw_data = json.load(f)

    gt_items = {q.question_id: q for q in load_ground_truth()}

    samples = []
    for item in raw_data:
        qid = item["question_id"]
        gt = gt_items.get(qid)
        if gt is None:
            continue
        samples.append(EvalSample(
            question_id=qid,
            question=gt.question,
            question_type=gt.question_type,
            rag_answer=item.get("rag_answer", ""),
            contexts=item.get("contexts", []),
            sources=[SourceInfo(**s) for s in item.get("sources", [])],
            ground_truth=gt,
            reference_answer=gt.reference_answer,
            route_used=item.get("route_used", ""),
            strategies_used=item.get("strategies_used", []),
        ))

    return samples


def export_csv(report: AggregatedReport) -> Path:
    """Export per-question evaluation results to CSV."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "evaluation_results.csv"

    # Collect all metric names across samples
    all_metric_names: list[str] = []
    seen: set[str] = set()
    for sample in report.samples:
        for m in sample.metrics:
            if m.name not in seen:
                all_metric_names.append(m.name)
                seen.add(m.name)

    fieldnames = [
        "question_id", "question_type", "route_used", "strategies_used",
    ] + all_metric_names

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sample in report.samples:
            metric_map = {m.name: m.value for m in sample.metrics}
            row = {
                "question_id": sample.question_id,
                "question_type": sample.question_type,
                "route_used": sample.route_used,
                "strategies_used": "|".join(sample.strategies_used),
            }
            for name in all_metric_names:
                row[name] = metric_map.get(name, "")
            writer.writerow(row)

    return out_path
