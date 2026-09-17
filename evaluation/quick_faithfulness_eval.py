#!/usr/bin/env python3
"""
Quick faithfulness re-judge: zh + strict faithfulness only, over an existing
raw_responses.json, with generator-format context blocks.

Use it to A/B judge prompts / context format without the full 4-metric RAGAS
run, or to re-judge a run of record after a judge fix.

Usage:
    uv run python quick_faithfulness_eval.py --results-dir results_graph \
        --out results_quick/faith_metric_validation.json [--limit N] [--ids A,B]

Contexts: backend-provided blocks when the checkpoint has them; otherwise
rebuilt from PostgreSQL (header + text). The per-statement verdicts of both
judges are written to the output for auditing.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()
EVAL_ROOT = Path(__file__).resolve().parent


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", datefmt="[%X]",
                        handlers=[RichHandler(console=console, show_path=False)])
    for name in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _mean(vals: list[float]) -> float | None:
    return round(statistics.mean(vals), 4) if vals else None


def positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text}")
    return value


def n_decomposed(statements: list[dict]) -> int:
    """Size of the judged decomposition (strict-only extras appended by the merge are not counted)."""
    zh = sum(1 for e in statements if e.get("verdict") is not None)
    return zh or len(statements)


def parse_ids(text: str) -> set[str] | None:
    """Comma-separated ids -> set (whitespace-tolerant); None when empty."""
    ids = {x.strip() for x in text.split(",") if x.strip()}
    return ids or None


def _load_stored_faithfulness(results_dir: Path) -> dict[str, float]:
    """Stored ragas_faithfulness per question (for a before/after delta), if present."""
    path = results_dir / "evaluation_results.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for s in data.get("samples", []):
        for m in s.get("metrics", []):
            if m.get("name") == "ragas_faithfulness" and m.get("valid", True):
                out[s["question_id"]] = m["value"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Faithfulness-only re-judge over a raw_responses checkpoint")
    parser.add_argument("--results-dir", default="results_graph", help="directory holding raw_responses.json")
    parser.add_argument("--out", required=True, help="output JSON path (relative to evaluation/)")
    parser.add_argument("--limit", type=positive_int, default=0, help="only the first N samples")
    parser.add_argument("--ids", default="", help="comma-separated question_ids to judge")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="do not rebuild legacy headerless contexts from PostgreSQL")
    args = parser.parse_args()
    _setup_logging()

    from src.config import settings
    from src.evaluator import _judge_model_name, context_format_summary, load_samples_from_checkpoint
    from src.metrics.ragas_eval import compute_faithfulness_only

    results_dir = (EVAL_ROOT / args.results_dir).resolve()
    only_ids = parse_ids(args.ids)
    samples = load_samples_from_checkpoint(
        rebuild_contexts=not args.no_rebuild,
        raw_path=results_dir / "raw_responses.json",
        only_ids=only_ids,
        limit=args.limit or None,
    )
    if only_ids and not args.limit:  # with --limit the loader already warned about ids it cut
        missing = only_ids - {s.question_id for s in samples}
        if missing:
            parser.error(f"unknown question ids: {sorted(missing)}")
    if not samples:
        console.print("[red]No samples to judge (check --results-dir / --ids / --limit).[/red]")
        sys.exit(1)
    console.print(f"[bold]Judging faithfulness for {len(samples)} samples from {results_dir.name}[/bold]")

    metrics, rationales = compute_faithfulness_only(samples)
    stored = _load_stored_faithfulness(results_dir)

    rows = []
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_family: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall: dict[str, list[float]] = defaultdict(list)
    n_scored = n_paired = 0
    for s in samples:
        vals = {m.name: m.value for m in metrics.get(s.question_id, []) if m.valid}
        family = s.ground_truth.family or "legacy_head"
        rationale = rationales.get(s.question_id)
        rows.append({
            "question_id": s.question_id,
            "question_type": s.question_type,
            "family": family,
            "route_used": s.route_used,
            "context_source": s.context_source,
            "stored_faithfulness": stored.get(s.question_id),
            "ragas_faithfulness": vals.get("ragas_faithfulness"),
            "ragas_faithfulness_strict": vals.get("ragas_faithfulness_strict"),
            "n_statements": n_decomposed(rationale.faithfulness_statements) if rationale else 0,
            "statements": rationale.faithfulness_statements if rationale else [],
        })
        if not vals:
            continue
        n_scored += 1
        for name, v in vals.items():
            overall[name].append(v)
            by_type[s.question_type][name].append(v)
            by_family[family][name].append(v)
        # Paired before/after: the stored score only counts for samples the new judge scored.
        if s.question_id in stored:
            n_paired += 1
            overall["stored_faithfulness"].append(stored[s.question_id])
            by_type[s.question_type]["stored_faithfulness"].append(stored[s.question_id])
            by_family[family]["stored_faithfulness"].append(stored[s.question_id])

    report = {
        "meta": {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_results_dir": results_dir.name,
            "n_samples": len(samples),
            "n_scored": n_scored,
            "n_paired_with_stored": n_paired,
            "judge_provider": settings.eval_llm_provider,
            "judge_model": _judge_model_name(),
            "strict_enabled": settings.eval_faithfulness_strict,
            **context_format_summary(samples),
        },
        "overall": {k: _mean(v) for k, v in overall.items()},
        "by_type": {t: {k: _mean(v) for k, v in d.items()} for t, d in by_type.items()},
        "by_family": {f: {k: _mean(v) for k, v in d.items()} for f, d in by_family.items()},
        "samples": rows,
    }
    out_path = (EVAL_ROOT / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    table = Table(title="Faithfulness re-judge (overall)")
    table.add_column("metric", style="cyan")
    table.add_column("mean", justify="right", style="green")
    for k, v in report["overall"].items():
        table.add_row(k, "-" if v is None else f"{v:.4f}")
    console.print(table)
    console.print(f"[bold green]Saved {out_path}[/bold green]")


if __name__ == "__main__":
    sys.path.insert(0, str(EVAL_ROOT))
    main()
