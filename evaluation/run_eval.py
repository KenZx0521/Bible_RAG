#!/usr/bin/env python3
"""
Bible RAG Evaluation CLI

Usage:
    uv run python run_eval.py                 # Full pipeline (uses backend RAG_USE_GRAPH)
    uv run python run_eval.py --collect-only  # Only collect RAG responses + inline eval
    uv run python run_eval.py --eval-only     # Only run batch evaluation (needs responses)
    uv run python run_eval.py --eval-only --rebuild-contexts  # legacy checkpoint: rebuild
                                              # generator-format judge contexts from PostgreSQL
    uv run python run_eval.py --visualize-only # Only generate dashboard

    Graph-retrieval A/B (backend does NOT need restart between runs):
        uv run python run_eval.py --graph       # results_graph/
        uv run python run_eval.py --no-graph    # results_no_graph/
        uv run python run_eval.py --semantic    # results_semantic/ (pure semantic baseline)

    Since 2026-10 --graph runs only the backend's RAG_GRAPH_STRATEGIES (default:
    graph_event). Round 3's results_graph/ was every strategy; reproduce it with
        uv run python run_eval.py --graph --graph-strategies all
    A pre-2026-10 archive in the output dir is never overwritten: move it first.

    Ground truth: --gt v1|v2 (default EVAL_GT_VERSION). The backend's /health
    names the build (none = legacy-20261004), recorded in run_meta.json beside
    the checkpoint; a new build is scored only against GT v2, its sources mapped
    through contracts/{build_id}/verse_index.json (--contracts-dir to override).
    evaluation_results.json meta records data_build_id, gt_version, gt_sha and
    encoder_fingerprint.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

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


def _parse_args() -> argparse.Namespace:
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
    parser.add_argument(
        "--graph-strategies",
        nargs="*",
        default=None,
        help="Graph strategies the backend may run (e.g. graph_event, or 'all'; "
             "no values = none). Omit = backend RAG_GRAPH_STRATEGIES default.",
    )
    parser.add_argument(
        "--rebuild-contexts",
        action="store_true",
        help="With --eval-only: rebuild generator-format context blocks (header + text) "
             "from PostgreSQL for legacy checkpoints whose sources carry no context.",
    )
    parser.add_argument("--gt", choices=("v1", "v2"), default=None,
                        help="ground truth version (default: EVAL_GT_VERSION setting)")
    parser.add_argument("--contracts-dir", type=Path, default=None,
                        help="the build's contracts directory (default: "
                             "$RAG_STORE/contracts/<build_id>)")
    args = parser.parse_args()
    if args.semantic and args.graph is not None:
        parser.error("--semantic cannot be combined with --graph / --no-graph")
    if args.rebuild_contexts and not args.eval_only:
        parser.error("--rebuild-contexts requires --eval-only")
    return args


def _print_banner(args: argparse.Namespace, results_dir: Path) -> None:
    if args.semantic:
        mode_label = "semantic-only"
    else:
        mode_label = {True: "graph", False: "no-graph", None: "default (backend env)"}[args.graph]
    strategies = args.graph_strategies if args.graph_strategies is not None else "backend default"
    console.print(Panel.fit(
        "[bold blue]Bible RAG Evaluation System[/bold blue]\n"
        f"[dim]RAGAS + Custom Metrics | Graph mode: {mode_label} | "
        f"graph strategies: {strategies}[/dim]\n"
        f"[dim]Output dir: {results_dir}[/dim]",
        border_style="blue",
    ))


def _run_context(args: argparse.Namespace, live: bool):
    """GT + build: from the backend's /health when collecting, else the checkpoint's run_meta."""
    from src.config import settings
    from src.data_loader import load_gt
    from src.provenance import fetch_health, from_health, make_context, read_run_meta

    provenance = (from_health(fetch_health(settings.backend_url)) if live
                  else read_run_meta(settings.results_dir))
    ctx = make_context(load_gt(args.gt), provenance, args.contracts_dir)
    console.print(f"[dim]Run meta: {ctx.meta()}[/dim]")
    return ctx


def _collect(args: argparse.Namespace, ctx):
    from src.evaluator import run_collection

    return asyncio.run(run_collection(ctx, use_graph=args.graph, semantic_only=args.semantic,
                                      graph_strategies=args.graph_strategies))


def _evaluate(samples, ctx, inline_metrics=None) -> None:
    from src.evaluator import export_csv, run_evaluation
    from src.visualizer import generate_dashboard

    report = run_evaluation(samples, ctx, inline_metrics=inline_metrics)
    csv_path = export_csv(report)
    console.print(f"[bold green]CSV exported to {csv_path}[/bold green]")
    generate_dashboard(report)


def main() -> None:
    args = _parse_args()
    _setup_logging()

    # Configure evaluation output dir based on graph mode. Must happen before any
    # function below reads settings.results_dir.
    from src.config import settings
    settings.set_graph_mode(args.graph)
    settings.set_semantic_mode(args.semantic)
    _print_banner(args, settings.results_dir)

    if args.collect_only:
        console.print("[bold]Mode: Collect Only[/bold]")
        _collect(args, _run_context(args, live=True))
        console.print("[green]Collection complete. Run with --eval-only to run batch metrics.[/green]")
    elif args.eval_only:
        from src.evaluator import load_samples_from_checkpoint

        console.print("[bold]Mode: Evaluate Only (batch)[/bold]")
        ctx = _run_context(args, live=False)
        samples = load_samples_from_checkpoint(rebuild_contexts=args.rebuild_contexts, gt=ctx.gt)
        console.print(f"Loaded {len(samples)} samples from raw_responses.json.")
        _evaluate(samples, ctx)
    elif args.visualize_only:
        from src.evaluator import load_results
        from src.visualizer import generate_dashboard

        console.print("[bold]Mode: Visualize Only[/bold]")
        generate_dashboard(load_results())
    else:
        console.print("[bold]Mode: Full Evaluation Pipeline[/bold]\n")
        ctx = _run_context(args, live=True)
        console.rule("[bold cyan]Step 1: Collect RAG Responses + Claude Point Coverage")
        samples, inline_metrics = _collect(args, ctx)
        console.rule("[bold cyan]Step 2: Run Batch Evaluation Metrics")
        _evaluate(samples, ctx, inline_metrics=inline_metrics)
        console.print("\n[bold green]Evaluation complete![/bold green]")
        console.print(f"Open [cyan]{settings.results_dir / 'dashboard.html'}[/cyan] to view the dashboard.")


if __name__ == "__main__":
    main()
