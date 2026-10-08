#!/usr/bin/env python3
"""
Quick faithfulness re-judge: zh + strict faithfulness only, over an existing
raw_responses.json, with generator-format context blocks.

Use it to A/B judge prompts / context format without the full 4-metric RAGAS
run, or to re-judge a run of record after a judge fix.

Usage:
    uv run python quick_faithfulness_eval.py --results-dir results_graph \
        --out results_quick/faith_metric_validation.json [--limit N] \
        [--ids A,B | --ids-file IDS] [--coverage] [--gt v1|v2] [--contracts-dir DIR]

--results-dir and --out resolve under evaluation/ when relative; absolute paths
are used as given. --ids-file is a JSON list or one id per line.

Samples whose answer cannot be judged get null scores and leave every mean:
infrastructure failures and the backend's generation-error answers
(src/validity.py answer_failure). Per-row "invalid" says why ("infra",
"generation", or null); meta "invalid_samples" lists them.

--coverage also judges answer coverage (metrics/coverage_eval.py: recall over
the --gt's expected_answer_points) on the same samples with the same judge
provider and model; invalid samples get none. It adds per-row
"coverage" (float or null), overall "coverage" and meta "coverage_enabled" /
"n_coverage_scored"; every other field is what the run without it writes.

The build comes from run_meta.json beside the checkpoint (none = legacy-20261004);
a new build's checkpoint is judged only with --gt v2. The output meta records
data_build_id, gt_version, gt_sha and encoder_fingerprint.

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Faithfulness-only re-judge over a raw_responses checkpoint")
    parser.add_argument("--results-dir", default="results_graph", help="directory holding raw_responses.json")
    parser.add_argument("--out", required=True,
                        help="output JSON path (relative to evaluation/, or absolute)")
    parser.add_argument("--limit", type=positive_int, default=0, help="only the first N samples")
    ids = parser.add_mutually_exclusive_group()
    ids.add_argument("--ids", default="", help="comma-separated question_ids to judge")
    ids.add_argument("--ids-file", type=Path, default=None,
                     help="question_ids to judge: a JSON list or one id per line")
    parser.add_argument("--coverage", action="store_true",
                        help="also judge answer coverage (expected_answer_points of --gt) with "
                             "the same judge; adds per-row and overall 'coverage'")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="do not rebuild legacy headerless contexts from PostgreSQL")
    parser.add_argument("--gt", choices=("v1", "v2"), default=None,
                        help="ground truth version (default: EVAL_GT_VERSION setting); a new "
                             "build's checkpoint is judged only with v2")
    parser.add_argument("--contracts-dir", type=Path, default=None,
                        help="the build's contracts directory (default: "
                             "$RAG_STORE/contracts/<build_id>)")
    return parser


def _run_context(args: argparse.Namespace, results_dir: Path):
    """The GT plus the build the checkpoint recorded beside it (run_meta.json)."""
    from src.data_loader import load_gt
    from src.provenance import make_context, read_run_meta

    return make_context(load_gt(args.gt), read_run_meta(results_dir), args.contracts_dir)


def _selected_ids(parser: argparse.ArgumentParser, args: argparse.Namespace) -> set[str] | None:
    """--ids or --ids-file; None = every sample in the checkpoint."""
    if args.ids_file is None:
        return parse_ids(args.ids)
    from src.id_selection import IdsFileError, read_ids_file

    try:
        return set(read_ids_file(args.ids_file))
    except IdsFileError as exc:
        parser.error(f"--ids-file {args.ids_file}: {exc}")


def _load(parser: argparse.ArgumentParser, args: argparse.Namespace, results_dir: Path, gt) -> list:
    from src.evaluator import load_samples_from_checkpoint

    only_ids = _selected_ids(parser, args)
    samples = load_samples_from_checkpoint(
        rebuild_contexts=not args.no_rebuild,
        raw_path=results_dir / "raw_responses.json",
        only_ids=only_ids,
        limit=args.limit or None,
        gt=gt,
    )
    if only_ids and not args.limit:  # with --limit the loader already warned about ids it cut
        missing = only_ids - {s.question_id for s in samples}
        if missing:
            parser.error(f"unknown question ids: {sorted(missing)}")
    if not samples:
        console.print("[red]No samples to judge (check --results-dir / --ids / --limit).[/red]")
        sys.exit(1)
    return samples


def _judge(samples: list) -> tuple[dict, dict]:
    from src.metrics.ragas_eval import compute_faithfulness_only

    return compute_faithfulness_only(samples)


def _coverage(samples: list) -> dict[str, float | None]:
    """Answer coverage per question, None where it is not valid (judge failure, no points,
    infrastructure or generation failure, as faithfulness)."""
    from src.metrics.coverage_eval import compute_coverage_metrics
    from src.validity import invalidate_answer_failures

    metrics = invalidate_answer_failures(samples, compute_coverage_metrics(samples))
    return {s.question_id: next((m.value for m in metrics.get(s.question_id, [])
                                 if m.name == "answer_coverage" and m.valid), None)
            for s in samples}


def _with_coverage(report: dict, coverage: dict[str, float | None]) -> dict:
    """The report plus per-row and overall "coverage"; every existing field unchanged."""
    scored = [v for v in coverage.values() if v is not None]
    return {
        **report,
        "meta": {**report["meta"], "coverage_enabled": True, "n_coverage_scored": len(scored)},
        "overall": {**report["overall"], "coverage": _mean(scored)},
        "samples": [{**row, "coverage": coverage.get(row["question_id"])}
                    for row in report["samples"]],
    }


def _tally(samples: list, metrics: dict, rationales: dict, stored: dict[str, float]) -> dict:
    """Per-sample rows plus overall / by-type / by-family means (stored scores paired)."""
    from src.validity import answer_failure

    rows = []
    groups: dict[str, dict[str, dict[str, list[float]]]] = {
        "overall": defaultdict(lambda: defaultdict(list)),
        "by_type": defaultdict(lambda: defaultdict(list)),
        "by_family": defaultdict(lambda: defaultdict(list)),
    }
    n_scored = n_paired = 0
    for s in samples:
        vals = {m.name: m.value for m in metrics.get(s.question_id, []) if m.valid}
        family = s.ground_truth.family or "legacy_head"
        rows.append(_row(s, family, vals, rationales.get(s.question_id), stored,
                         answer_failure(s)))
        if not vals:
            continue
        n_scored += 1
        # Paired before/after: the stored score only counts for samples the new judge scored.
        if s.question_id in stored:
            n_paired += 1
            vals = {**vals, "stored_faithfulness": stored[s.question_id]}
        for group, key in (("overall", ""), ("by_type", s.question_type), ("by_family", family)):
            for name, v in vals.items():
                groups[group][key][name].append(v)
    means = {g: {k: {n: _mean(v) for n, v in d.items()} for k, d in by.items()}
             for g, by in groups.items()}
    return {"rows": rows, "n_scored": n_scored, "n_paired": n_paired,
            "overall": means["overall"].get("", {}), "by_type": means["by_type"],
            "by_family": means["by_family"]}


def _row(s, family: str, vals: dict, rationale, stored: dict[str, float],
         invalid: str | None) -> dict:
    return {
        "question_id": s.question_id,
        "question_type": s.question_type,
        "family": family,
        "route_used": s.route_used,
        "context_source": s.context_source,
        "invalid": invalid,
        "stored_faithfulness": stored.get(s.question_id),
        "ragas_faithfulness": vals.get("ragas_faithfulness"),
        "ragas_faithfulness_strict": vals.get("ragas_faithfulness_strict"),
        "n_statements": n_decomposed(rationale.faithfulness_statements) if rationale else 0,
        "statements": rationale.faithfulness_statements if rationale else [],
    }


def _report(results_dir: Path, samples: list, tally: dict, run_meta: dict) -> dict:
    from src.config import settings
    from src.evaluator import _judge_model_name, context_format_summary

    return {
        "meta": {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_results_dir": results_dir.name,
            **run_meta,
            "n_samples": len(samples),
            "n_scored": tally["n_scored"],
            "invalid_samples": {r["question_id"]: r["invalid"]
                                for r in tally["rows"] if r["invalid"]},
            "n_paired_with_stored": tally["n_paired"],
            "judge_provider": settings.eval_llm_provider,
            "judge_model": _judge_model_name(),
            "strict_enabled": settings.eval_faithfulness_strict,
            **context_format_summary(samples),
        },
        "overall": tally["overall"],
        "by_type": tally["by_type"],
        "by_family": tally["by_family"],
        "samples": tally["rows"],
    }


def _save(report: dict, out: str) -> Path:
    out_path = (EVAL_ROOT / out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    table = Table(title="Faithfulness re-judge (overall)")
    table.add_column("metric", style="cyan")
    table.add_column("mean", justify="right", style="green")
    for k, v in report["overall"].items():
        table.add_row(k, "-" if v is None else f"{v:.4f}")
    console.print(table)
    return out_path


def main() -> None:
    from src.validity import invalidate_answer_failures

    parser = _parser()
    args = parser.parse_args()
    _setup_logging()

    results_dir = (EVAL_ROOT / args.results_dir).resolve()
    ctx = _run_context(args, results_dir)
    console.print(f"[dim]Run meta: {ctx.meta()}[/dim]")
    samples = _load(parser, args, results_dir, ctx.gt)
    console.print(f"[bold]Judging faithfulness for {len(samples)} samples from {results_dir.name}[/bold]")

    metrics, rationales = _judge(samples)
    # Infrastructure and generation failures: judged, but their scores are void
    # (prereg G-ANS counts them in n_invalid).
    metrics = invalidate_answer_failures(samples, metrics)
    tally = _tally(samples, metrics, rationales, _load_stored_faithfulness(results_dir))
    report = _report(results_dir, samples, tally, ctx.meta())
    if args.coverage:
        report = _with_coverage(report, _coverage(samples))
    out_path = _save(report, args.out)
    console.print(f"[bold green]Saved {out_path}[/bold green]")


if __name__ == "__main__":
    sys.path.insert(0, str(EVAL_ROOT))
    main()
