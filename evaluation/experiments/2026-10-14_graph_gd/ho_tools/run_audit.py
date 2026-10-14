"""§7 獨立 Claude 稽核 of the HO drafts waiting for an audit (pending_audit).

Each draft gets a fresh headless agent (_ho_claude: cwd outside the repo, only `bt`, model
pinned) with the frozen audit_prompt.md; its answer is the E7/newq/audit_result.json row
(id, severity, issues, suggested_fix, checked). ok / minor → passed; major / critical →
needs_fix (once) or dropped after a failed fix (§7). Audits run in parallel and are
committed in commit order; the state is saved after each one.

    run_audit.py --root <store>/reports/graph_gd_20261014/ho [--budget USD] [--ids ID ...]

A formal (non-pilot) root needs 附錄 A and a V1 that did not stop
(_ho_common.assert_formal_allowed). Exit 0 done, 2 error (one line).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import HO_DIR, HoToolError, assert_formal_allowed, gd, ho_meta  # first: sys.path

import _ho_claude as C  # noqa: E402
import _ho_prompts as P  # noqa: E402
import _ho_runs as RU  # noqa: E402
import _ho_state as S  # noqa: E402

__all__ = ["AUDIT_BUDGET_USD", "audit_jobs", "audit_pending", "main", "SCRIPT_FILES"]

AUDIT_BUDGET_USD = 20.0
SCRIPT_FILES = (HO_DIR / "run_audit.py", *RU.AGENT_FILES)


def audit_jobs(state: Mapping[str, Any], prompt: P.PromptFile, budget: float,
               ids: Sequence[str] | None = None) -> list[RU.Job]:
    recs = [r for r in S.records(state, statuses=(S.PENDING,)) if ids is None or r["id"] in ids]
    return [RU.Job(r["id"], "audit", r["id"], prompt, "task_audit",
                   {"qid": r["id"], "category_line": P.category_line(r["cat"], r["subtype"]),
                    "used_cores": RU.used_cores(state, exclude=r["id"]),
                    "item_json": P.item_json(r["item"])}, P.AUDIT_SCHEMA, budget)
            for r in recs]


def audit_pending(root: Path, budget: float = AUDIT_BUDGET_USD, ids: Sequence[str] | None = None,
                  cwd: Path = C.AGENT_CWD) -> dict[str, Any]:
    """Audit every pending draft (or `ids`); returns the saved state."""
    state = S.load_state(root)
    C.write_wrappers(root)
    jobs = audit_jobs(state, P.load_prompt(P.AUDIT_PROMPT), budget, ids)
    results = RU.run_parallel(root, jobs, cwd=cwd)
    failed = []
    for job in jobs:                                     # commit order = record order
        try:
            state = RU.commit_audit(state, job.qid, results[job.key])
        except HoToolError as err:
            state, failed = RU.record_runs(state, job.qid, "audit", results[job.key]), failed + [str(err)]
        S.save_state(root, state)
    if failed:
        raise HoToolError("; ".join(failed))
    return state


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--budget", type=float, default=AUDIT_BUDGET_USD, help="max USD per agent run")
    ap.add_argument("--ids", nargs="+")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    assert_formal_allowed(a.root)                    # before anything is written to the root
    RU.log_meta(a.root, ho_meta("run_audit.py", SCRIPT_FILES, **RU.run_settings(a.root)))
    state = audit_pending(a.root, a.budget, a.ids)
    print(f"run_audit.py: {S.summary(state)['by_status']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"run_audit.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
