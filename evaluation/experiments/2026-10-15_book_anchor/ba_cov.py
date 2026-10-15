"""Coverage-only judge of the book_anchor ablation (prereg §5 量尺, §9 step 3.8).

    ba_cov.py --results-dir $OUT/ans/<arm>_r<k> --ids-file $OUT/checks/judge_ids_<arm>.json \\
        --gt v2 --out $OUT/judge/<arm>_r<k>.cov.json

Loads the checkpoint as quick_faithfulness_eval._load does (contexts as stored: the
generator blocks, no rebuild) and calls its _coverage (src/metrics/coverage_eval with the
evaluation/.env judge; generation and infrastructure failures are null), judging no
faithfulness. A logging handler on src.metrics.coverage_eval collects each question's
per-point verdicts ("[Coverage] QID => score {1: 'covered', …}") into the JSON, so they do
not live only in a log rich folds at 80 columns.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
EVAL_ROOT = _HERE.parents[1]
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

import quick_faithfulness_eval as qfe  # noqa: E402

COVERAGE_LOGGER = "src.metrics.coverage_eval"


class VerdictCollector(logging.Handler):
    """Per question: what the coverage judge logged (verdicts, empty answer, failure)."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.by_qid: dict[str, dict[str, Any]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.msg if isinstance(record.msg, str) else ""
        args = record.args if isinstance(record.args, tuple) else ()
        if not msg.startswith("[Coverage]") or not args:
            return
        qid = str(args[0])
        if len(args) == 3 and isinstance(args[2], dict):
            entry = {"status": "judged", "score": args[1],
                     "verdicts": {str(k): v for k, v in args[2].items()}}
        elif "empty/refused" in msg:
            entry = {"status": "empty_answer"}
        elif "judge call failed" in msg:
            entry = {"status": "judge_failed", "error": str(args[1])[:300]}
        elif "unparseable" in msg:
            entry = {"status": "unparseable", "raw": str(args[1])[:300]}
        elif "no expected_answer_points" in msg:
            entry = {"status": "no_points"}
        else:
            entry = {"status": "other", "message": record.getMessage()[:300]}
        self.by_qid[qid] = entry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--ids-file", type=Path, default=None)
    parser.add_argument("--gt", choices=("v1", "v2"), default="v2")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--contracts-dir", type=Path, default=None)
    return parser


def report(results_dir: Path, samples: list, coverage: dict[str, float | None],
           verdicts: dict[str, dict], run_meta: dict) -> dict[str, Any]:
    from src.config import settings
    from src.evaluator import _judge_model_name, context_format_summary
    from src.validity import answer_failure

    rows = [{"question_id": s.question_id, "question_type": s.question_type,
             "family": s.ground_truth.family or "legacy_head", "route_used": s.route_used,
             "invalid": answer_failure(s), "coverage": coverage.get(s.question_id),
             "n_points": len(s.ground_truth.expected_answer_points),
             "judge": verdicts.get(s.question_id)} for s in samples]
    scored = [r["coverage"] for r in rows if r["coverage"] is not None]
    return {
        "meta": {"timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "source_results_dir": results_dir.name, **run_meta,
                 "n_samples": len(samples), "n_coverage_scored": len(scored),
                 "coverage_only": True, "judge_provider": settings.eval_llm_provider,
                 "judge_model": _judge_model_name(),
                 "invalid_samples": {r["question_id"]: r["invalid"] for r in rows if r["invalid"]},
                 **context_format_summary(samples)},
        "overall": {"coverage": round(statistics.fmean(scored), 4) if scored else None},
        "samples": rows}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    qfe._setup_logging()
    results_dir = args.results_dir.resolve()
    load_args = argparse.Namespace(ids="", ids_file=args.ids_file, no_rebuild=True, limit=0,
                                   gt=args.gt, contracts_dir=args.contracts_dir)
    ctx = qfe._run_context(load_args, results_dir)
    samples = qfe._load(parser, load_args, results_dir, ctx.gt)
    collector = VerdictCollector()
    cov_logger = logging.getLogger(COVERAGE_LOGGER)
    cov_logger.addHandler(collector)
    cov_logger.setLevel(logging.INFO)
    try:
        coverage = qfe._coverage(samples)
    finally:
        cov_logger.removeHandler(collector)
    doc = report(results_dir, samples, coverage, collector.by_qid, ctx.meta())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")       # a killed judge leaves no --out
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, args.out)
    print(f"ba_cov: {len(samples)} samples, coverage {doc['overall']['coverage']} → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
