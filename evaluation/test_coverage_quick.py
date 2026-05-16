#!/usr/bin/env python3
"""
Quick manual smoke test for the new answer_coverage metric.

Runs compute_coverage_metrics on a curated subset of results_graph questions
and prints answer_coverage next to the existing ragas_answer_correctness so
the contrast is visible. Not a pytest test — just `python test_coverage_quick.py`.
"""

from __future__ import annotations

import json
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

# Curated mix: verbose-but-good answers, a genuinely incomplete one, a refusal.
SUBSET = [
    "VERSE_LOOKUP_001",     # short answer, expect high coverage
    "TOPIC_QUESTION_008",   # correctness 0.345, verbose-good
    "PERSON_QUESTION_006",  # correctness 0.482, verbose-good
    "EVENT_QUESTION_005",   # correctness 0.252, verbose-good
    "PERSON_QUESTION_019",  # correctness 0.190, genuinely incomplete
    "PERSON_QUESTION_005",  # correctness 0.089, refusal ("無法回答")
]


def main() -> None:
    from src.config import settings
    settings.set_graph_mode(True)  # load results_graph checkpoint

    from src.evaluator import load_samples_from_checkpoint
    from src.metrics.coverage_eval import compute_coverage_metrics

    all_samples = load_samples_from_checkpoint()
    samples = [s for s in all_samples if s.question_id in SUBSET]
    console.print(f"[bold]Testing {len(samples)} questions[/bold] "
                  f"(provider={settings.eval_llm_provider})\n")

    # Old answer_correctness for side-by-side comparison.
    res_path = settings.results_dir / "evaluation_results.json"
    old = json.load(open(res_path, encoding="utf-8"))
    old_ac = {
        s["question_id"]: next(
            (m["value"] for m in s["metrics"] if m["name"] == "ragas_answer_correctness"),
            None,
        )
        for s in old["samples"]
    }

    results = compute_coverage_metrics(samples)

    console.print(f"\n{'qid':24} {'#points':8} {'coverage':10} {'old answer_correctness':22}")
    console.print("-" * 66)
    for s in samples:
        mr = results[s.question_id][0]
        npts = len(s.ground_truth.expected_answer_points)
        cov = f"{mr.value:.3f}" + ("" if mr.valid else " (invalid)")
        console.print(f"{s.question_id:24} {npts:<8} {cov:10} {old_ac.get(s.question_id)}")


if __name__ == "__main__":
    main()
