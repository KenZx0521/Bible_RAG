#!/usr/bin/env python3
"""
One-off: compute answer_coverage for every results_graph sample and merge it
into the existing report, then regenerate JSON/CSV/dashboard.

Reuses the cached retrieval / semantic / RAGAS metrics from the existing
evaluation_results.json, so the slow RAGAS judge is NOT re-run — only the new
coverage metric is computed.
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console()
logging.basicConfig(
    level=logging.INFO, format="%(message)s", datefmt="[%X]",
    handlers=[RichHandler(console=console, show_path=False)],
)
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    from src.config import settings
    settings.set_graph_mode(True)

    from src.evaluator import (
        load_samples_from_checkpoint, load_results,
        _aggregate, _save_results, export_csv,
    )
    from src.metrics.coverage_eval import compute_coverage_metrics
    from src.visualizer import generate_dashboard

    samples = load_samples_from_checkpoint()
    old = load_results()
    old_by_id = {s.question_id: s for s in old.samples}

    coverage = compute_coverage_metrics(samples)

    # Merge: existing per-sample metrics (drop any stale answer_coverage) + new.
    all_metrics: dict = {}
    rationales: dict = {}
    for s in samples:
        qid = s.question_id
        prev = old_by_id.get(qid)
        existing = (
            [m for m in prev.metrics if m.name != "answer_coverage"] if prev else []
        )
        all_metrics[qid] = existing + coverage.get(qid, [])
        if prev and prev.rationale:
            rationales[qid] = prev.rationale

    report = _aggregate(samples, all_metrics, rationales)
    _save_results(report)
    export_csv(report)
    generate_dashboard(report)

    console.print(
        f"\n[bold green]answer_coverage overall = "
        f"{report.overall.get('answer_coverage')}[/bold green]"
    )
    console.print(
        f"ragas_answer_correctness overall = "
        f"{report.overall.get('ragas_answer_correctness')}"
    )


if __name__ == "__main__":
    main()
