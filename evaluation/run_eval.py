#!/usr/bin/env python3
"""
Bible RAG Evaluation CLI

Usage:
    uv run python run_eval.py                 # Full pipeline (uses backend RAG_USE_GRAPH)
    uv run python run_eval.py --collect-only  # Only collect RAG responses + inline eval
    uv run python run_eval.py --eval-only     # Only run batch evaluation (needs responses)
    uv run python run_eval.py --visualize-only # Only generate dashboard

    Graph-retrieval A/B (backend does NOT need restart between runs):
        uv run python run_eval.py --graph       # results_graph/
        uv run python run_eval.py --no-graph    # results_no_graph/
        uv run python run_eval.py --semantic    # results_semantic/ (pure semantic baseline)
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
    parser.add_argument(
        "--graph",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable (--graph) or disable (--no-graph) graph retrieval for this run. "
             "Default: use backend RAG_USE_GRAPH env. Also routes output to "
             "results_graph/ or results_no_graph/ (vs plain results/).",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Semantic-only mode: bypass R1-R6 routing + SQL + graph + cross-ref; "
             "run pure semantic retrieval + rerank. Outputs to results_semantic/.",
    )
    args = parser.parse_args()

    if args.semantic and args.graph is not None:
        parser.error("--semantic cannot be combined with --graph / --no-graph")

    _setup_logging()

    # Configure evaluation output dir based on graph mode. Must happen before any
    # function below reads settings.results_dir.
    from src.config import settings
    settings.set_graph_mode(args.graph)
    settings.set_semantic_mode(args.semantic)

    if args.semantic:
        mode_label = "semantic-only"
    else:
        mode_label = {True: "graph", False: "no-graph", None: "default (backend env)"}[args.graph]
    console.print(Panel.fit(
        "[bold blue]Bible RAG Evaluation System[/bold blue]\n"
        f"[dim]RAGAS + Custom Metrics | Graph mode: {mode_label}[/dim]\n"
        f"[dim]Output dir: {settings.results_dir}[/dim]",
        border_style="blue",
    ))

    from src.evaluator import (
        run_collection,
        run_evaluation,
        load_results,
        load_samples_from_checkpoint,
        export_csv,
    )
    from src.visualizer import generate_dashboard

    if args.collect_only:
        console.print("[bold]Mode: Collect Only[/bold]")
        samples, inline_metrics = asyncio.run(
            run_collection(use_graph=args.graph, semantic_only=args.semantic)
        )
        console.print("[green]Collection complete. Run with --eval-only to run batch metrics.[/green]")

    elif args.eval_only:
        console.print("[bold]Mode: Evaluate Only (batch)[/bold]")
        samples = load_samples_from_checkpoint()
        console.print(f"Loaded {len(samples)} samples from raw_responses.json.")
        report = run_evaluation(samples)
        csv_path = export_csv(report)
        console.print(f"[bold green]CSV exported to {csv_path}[/bold green]")
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
        samples, inline_metrics = asyncio.run(
            run_collection(use_graph=args.graph, semantic_only=args.semantic)
        )

        # Step 2: Batch evaluate (pass inline metrics so point coverage isn't re-run)
        console.rule("[bold cyan]Step 2: Run Batch Evaluation Metrics")
        report = run_evaluation(samples, inline_metrics=inline_metrics)

        # Step 3: Export CSV
        csv_path = export_csv(report)
        console.print(f"[bold green]CSV exported to {csv_path}[/bold green]")

        # Step 4: Visualize
        console.rule("[bold cyan]Step 4: Generate Dashboard")
        generate_dashboard(report)

        console.print("\n[bold green]Evaluation complete![/bold green]")
        console.print(f"Open [cyan]{settings.results_dir / 'dashboard.html'}[/cyan] to view the dashboard.")


if __name__ == "__main__":
    main()
