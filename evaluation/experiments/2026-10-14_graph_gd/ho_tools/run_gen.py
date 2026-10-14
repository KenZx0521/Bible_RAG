"""§7 HO 出題 executor: drafting rounds, fixes, and the full draft → audit → fix → re-audit loop.

Agents are headless `claude -p` runs (_ho_claude: cwd outside the repo, only `bt`, model
claude-opus-5-5, stream-json transcripts in <root>/transcripts/) with the frozen
gen_prompt.md. Order (§7): each round plans one slot per open category in the order KIN,
DIS, TO, MH (per_round times, interleaved), multi-hop slots rotating SUC, BRP, BRL, OQ;
slots run in parallel but are committed in that order, so a later draft that clashes with
an earlier one is the one blocked. Every category takes its first 30 passed drafts (MH
within 8/7/8/7); one that reaches 60 drafts first is frozen at its actual count.

    run_gen.py draft --root R [--per-round 1] [--categories KIN DIS TO MH]
    run_gen.py fix   --root R                    # every needs_fix draft (audit or Kay request)
    run_gen.py loop  --root R --rounds N [--per-round 1]

A pilot root (store ho/pilot/) gets ids H_KIN_P01, ...; its results are discarded. A formal
root needs 附錄 A and a V1 that did not stop (_ho_common.assert_formal_allowed). Exit 0
done, 2 error (one line; 基礎設施失敗 after MAX_RETRIES reruns also stops with 2).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import (CATEGORY_ORDER, HO_DIR, HoToolError, assert_formal_allowed,  # first: sys.path
                        gd, ho_meta)

import _ho_claude as C  # noqa: E402
import _ho_prompts as P  # noqa: E402
import _ho_runs as RU  # noqa: E402
import _ho_state as S  # noqa: E402
import mech_check as M  # noqa: E402
import run_audit  # noqa: E402

__all__ = ["GEN_BUDGET_USD", "draft_jobs", "draft_round", "fix_jobs", "fix_needed", "loop", "main",
           "SCRIPT_FILES"]

GEN_BUDGET_USD = 30.0
SCRIPT_FILES = (HO_DIR / "run_gen.py", HO_DIR / "run_audit.py", *RU.AGENT_FILES)


def draft_jobs(state: Mapping[str, Any], slots: Sequence[S.Slot], prompt: P.PromptFile,
               budget: float) -> list[RU.Job]:
    cores = RU.used_cores(state)
    return [RU.Job(s.qid, "gen", s.qid, prompt, "task_new",
                   {"qid": s.qid, "category_line": P.category_line(s.cat, s.subtype),
                    "category_code": s.subtype, "used_cores": cores}, P.GEN_SCHEMA, budget)
            for s in slots]


def draft_round(root: Path, per_round: int = 1, categories: Sequence[str] | None = None,
                budget: float = GEN_BUDGET_USD, cwd: Path = C.AGENT_CWD) -> dict[str, Any]:
    """Plan, draft in parallel, commit in order (annotate + mechanical check); saved state."""
    state = S.load_state(root)
    slots = S.plan_round(state, per_round, categories)
    if not slots:
        return state
    C.write_wrappers(root)
    jobs = draft_jobs(state, slots, P.load_prompt(P.GEN_PROMPT), budget)
    results = RU.run_parallel(root, jobs, cwd=cwd)
    ctx = M.store_context()
    for slot in slots:
        state = RU.commit_draft(state, slot, results[slot.qid], ctx)
        S.save_state(root, state)
    infra = [s.qid for s in slots if S.record(state, s.qid).get("infra_failure")]
    if infra:
        raise HoToolError(f"基礎設施失敗 after {RU.MAX_RETRIES} reruns: {infra}")
    return state


def fix_jobs(state: Mapping[str, Any], prompt: P.PromptFile, budget: float) -> list[RU.Job]:
    jobs = []
    for r in S.records(state, statuses=(S.NEEDS_FIX,)):
        req = r.get("fix_request") or {}
        issues = "\n".join(f"- {x}" for x in req.get("issues") or ()) or "- （無具體意見）"
        if req.get("suggested_fix"):
            issues += f"\n建議改法：{req['suggested_fix']}"
        jobs.append(RU.Job(r["id"], "fix", r["id"], prompt, "task_fix",
                           {"qid": r["id"], "category_line": P.category_line(r["cat"], r["subtype"]),
                            "used_cores": RU.used_cores(state, exclude=r["id"]), "issues": issues,
                            "item_json": P.item_json(r["item"])}, P.GEN_SCHEMA, budget))
    return jobs


def fix_needed(root: Path, budget: float = GEN_BUDGET_USD, cwd: Path = C.AGENT_CWD) -> dict[str, Any]:
    """One fix for every needs_fix draft, committed in commit order; saved state."""
    state = S.load_state(root)
    C.write_wrappers(root)
    jobs = fix_jobs(state, P.load_prompt(P.GEN_PROMPT), budget)
    results = RU.run_parallel(root, jobs, cwd=cwd)
    ctx, failed = M.store_context(), []
    for job in jobs:
        try:
            state = RU.commit_fix(state, job.qid, results[job.key], ctx)
        except HoToolError as err:
            state, failed = RU.record_runs(state, job.qid, "fix", results[job.key]), failed + [str(err)]
        S.save_state(root, state)
    if failed:
        raise HoToolError("; ".join(failed))
    return state


def resolve_pending(root: Path, gen_budget: float, audit_budget: float, cwd: Path) -> dict[str, Any]:
    """audit → fix → re-audit until no draft waits (at most MAX_FIX_ROUNDS + 1 audits)."""
    state = S.load_state(root)
    for _ in range(S.MAX_FIX_ROUNDS + 2):
        if S.records(state, statuses=(S.PENDING,)):
            state = run_audit.audit_pending(root, audit_budget, cwd=cwd)
        if S.records(state, statuses=(S.NEEDS_FIX,)):
            state = fix_needed(root, gen_budget, cwd)
        if not S.records(state, statuses=S.UNRESOLVED):
            return state
    raise HoToolError(f"drafts still unresolved: {[r['id'] for r in S.records(state, statuses=S.UNRESOLVED)]}")


def loop(root: Path, rounds: int, per_round: int = 1, gen_budget: float = GEN_BUDGET_USD,
         audit_budget: float = run_audit.AUDIT_BUDGET_USD, cwd: Path = C.AGENT_CWD) -> dict[str, Any]:
    """Up to `rounds` rounds of draft → audit → fix → re-audit; stops early when complete."""
    state = resolve_pending(root, gen_budget, audit_budget, cwd)
    for _ in range(rounds):
        if S.is_complete(state):
            break
        draft_round(root, per_round, budget=gen_budget, cwd=cwd)
        state = resolve_pending(root, gen_budget, audit_budget, cwd)
    return state


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draft", "fix", "loop"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--budget", type=float, default=GEN_BUDGET_USD, help="max USD per drafting run")
        if name != "fix":
            p.add_argument("--per-round", type=int, default=1)
        if name == "draft":
            p.add_argument("--categories", nargs="+", choices=CATEGORY_ORDER)
        if name == "loop":
            p.add_argument("--rounds", type=int, required=True)
            p.add_argument("--audit-budget", type=float, default=run_audit.AUDIT_BUDGET_USD)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    assert_formal_allowed(a.root)                    # before anything is written to the root
    RU.log_meta(a.root, ho_meta(f"run_gen.py {a.cmd}", SCRIPT_FILES, **RU.run_settings(a.root)))
    if a.cmd == "draft":
        state = draft_round(a.root, a.per_round, a.categories, a.budget)
    elif a.cmd == "fix":
        state = fix_needed(a.root, a.budget)
    else:
        state = loop(a.root, a.rounds, a.per_round, a.budget, a.audit_budget)
    print(f"run_gen.py {a.cmd}: {S.summary(state)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"run_gen.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
