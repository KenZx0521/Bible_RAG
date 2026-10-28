"""What evaluation_results.json records so the file audits itself (2026-10-28 P0).

* ``invalid_counts`` / ``invalid_ids``: per metric, the questions whose score is void
  (judge failure, infrastructure failure, ...), after the same invalidation the
  averages use. Why each one is void sits in its sample: rationale.errors (RAGAS),
  rationale.coverage_error (coverage), strategy_errors (infrastructure).
* ``unscored_ids``: per metric, the questions with no score at all, neither valid nor
  void (RAGAS skips a question without an answer or contexts; a failed RAGAS run
  scores none, rationale.errors.ragas says why). Every metric the run was expected to
  score is listed, so a metric's denominator is n_samples - unscored - invalid.
* ``eval_run``: when this evaluation ran, with which code (git) and argv.
* ``run_meta``: the checkpoint's run_meta.json v2 sections as they are on disk (null
  for a checkpoint without run_meta.json; each section null when it predates v2).
* ``judge_served_models``: {model: replies} the judge APIs named (llm/served_models.py);
  absent when no reply named one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .llm.served_models import served_models
from .metrics.coverage_eval import CoverageOutcome
from .models import EvalReport, Rationale
from .provenance import read_run_record
from .run_record import eval_code_state, now_iso


def invalid_summary(reports: Sequence[EvalReport], expected: Sequence[str] = ()) -> dict[str, dict]:
    """invalid_counts / invalid_ids / unscored_ids per metric, over every metric a report
    has plus every ``expected`` one (listed even when no report has it)."""
    scored = [(r.question_id, {m.name: m.valid for m in r.metrics}) for r in reports]
    names = sorted({name for _, valid in scored for name in valid} | set(expected))
    invalid = {n: [qid for qid, valid in scored if valid.get(n) is False] for n in names}
    return {"invalid_counts": {n: len(invalid[n]) for n in names},
            "invalid_ids": invalid,
            "unscored_ids": {n: [qid for qid, valid in scored if n not in valid] for n in names}}


def eval_run_info(started_at: str, argv: Sequence[str] | None = None) -> dict[str, Any]:
    """started_at / finished_at (now), argv, and the evaluation code's git state."""
    code = eval_code_state()
    info: dict[str, Any] = {
        "started_at": started_at, "finished_at": now_iso(),
        "argv": list(sys.argv if argv is None else argv),
        "git_head": code.get("git_head"), "git_dirty": code.get("git_dirty"),
        "dirty_paths": code.get("dirty_paths"),
    }
    if "error" in code:
        info["git_error"] = code["error"]
    return info


def with_coverage_audit(rationales: Mapping[str, Rationale],
                        outcomes: Mapping[str, CoverageOutcome]) -> dict[str, Rationale]:
    """Each question's rationale plus its coverage audit fields (a bare Rationale when RAGAS gave none)."""
    merged = dict(rationales)
    for qid, outcome in outcomes.items():
        base = merged.get(qid) or Rationale()
        merged[qid] = base.model_copy(update=outcome.rationale_fields())
    return merged


def audit_meta(report_samples: Sequence[EvalReport], started_at: str,
               results_dir: Path, expected: Sequence[str] = ()) -> dict[str, Any]:
    """The meta fields above, for a report whose checkpoint sits in ``results_dir``
    (``expected``: the metrics the run was to score, see invalid_summary)."""
    meta = {**invalid_summary(report_samples, expected),
            "eval_run": eval_run_info(started_at),
            "run_meta": read_run_record(results_dir)}
    served = served_models.snapshot()
    if served:
        meta["judge_served_models"] = served
    return meta
