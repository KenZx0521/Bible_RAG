#!/usr/bin/env python3
"""
Bible RAG Evaluation CLI

Usage:
    uv run python run_eval.py                 # Full pipeline
    uv run python run_eval.py --collect-only  # Only collect RAG responses + inline eval
    uv run python run_eval.py --eval-only     # Only run batch evaluation (needs responses)
    uv run python run_eval.py --visualize-only # Only generate dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

console = Console()


def _setup_logging() -> None:
    """Configure logging so RAG API and Claude API calls are visible."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    # Suppress noisy third-party loggers
    for name in ("httpx", "httpcore", "urllib3", "asyncio", "transformers",
                 "sentence_transformers", "filelock", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bible RAG Evaluation System")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--collect-only", action="store_true", help="Only collect RAG responses + inline eval")
    group.add_argument("--eval-only", action="store_true", help="Only run batch evaluation metrics")
    group.add_argument("--visualize-only", action="store_true", help="Only generate dashboard")
    args = parser.parse_args()

    _setup_logging()

    console.print(Panel.fit(
        "[bold blue]Bible RAG Evaluation System[/bold blue]\n"
        "[dim]RAGAS + Custom Metrics[/dim]",
        border_style="blue",
    ))

    from src.evaluator import (
        run_collection,
        run_evaluation,
        load_results,
        load_samples_from_checkpoint,
    )
    from src.visualizer import generate_dashboard

    if args.collect_only:
        console.print("[bold]Mode: Collect Only[/bold]")
        samples, inline_metrics = asyncio.run(run_collection())
        console.print("[green]Collection complete. Run with --eval-only to run batch metrics.[/green]")

    elif args.eval_only:
        console.print("[bold]Mode: Evaluate Only (batch)[/bold]")
        samples = load_samples_from_checkpoint()
        console.print(f"Loaded {len(samples)} samples from raw_responses.json.")
        report = run_evaluation(samples)
        generate_dashboard(report)

    elif args.visualize_only:
        console.print("[bold]Mode: Visualize Only[/bold]")
        report = load_results()
        generate_dashboard(report)

    else:
        # Full pipeline
        console.print("[bold]Mode: Full Evaluation Pipeline[/bold]\n")

        # Step 1: Collect + inline Claude eval
        console.rule("[bold cyan]Step 1: Collect RAG Responses + Claude Point Coverage")
        samples, inline_metrics = asyncio.run(run_collection())

        # Step 2: Batch evaluate (pass inline metrics so point coverage isn't re-run)
        console.rule("[bold cyan]Step 2: Run Batch Evaluation Metrics")
        report = run_evaluation(samples, inline_metrics=inline_metrics)

        # Step 3: Visualize
        console.rule("[bold cyan]Step 3: Generate Dashboard")
        generate_dashboard(report)

        console.print("\n[bold green]Evaluation complete![/bold green]")
        console.print("Open [cyan]results/dashboard.html[/cyan] to view the dashboard.")


if __name__ == "__main__":
    main()
