"""Blind question-writing executor of the confirmation set (confirm_A.md §2.4, §3, §7, §8).

Agents are headless `claude -p` runs (claude_a: cwd /srv, only `bt`, CLI pinned by <root>/cli_pin.json)
with the F1-frozen gen_a.md / audit_a.md. Each round plans one slot per segment (segment order),
drafts them at most 4 at a time, commits in slot order (mechanical check + transcript blinding
check), then audits, fixes (≤1 per source) and re-audits until no draft waits.

    run_ho_a.py pilot   [--root R] [--rounds N]   # the 12 pilot slots (§3) until all are done
    run_ho_a.py budget  [--root R] [--reestimate] # ledger; after the pilot, §8.2 re-estimate (once)
    run_ho_a.py loop    [--root R] [--rounds N]   # the other slots; needs the pilot, K1 pass, re-estimate
    run_ho_a.py audit   [--root R]                # audit every pending draft once
    run_ho_a.py fix     [--root R]                # fix every needs_fix draft once
    run_ho_a.py stop-drafting [--root R]          # §8.2 hard cap reached: stop drafting (loop does it too)
    run_ho_a.py status  [--root R]

Order (§0): CLI probe and pin → F1 → pilot → k1.py (main program, CPU) → budget --reestimate → loop →
kay_a.py draw / apply → loop (Kay revisions and re-drafts) → freeze_a.py. Every save rewrites
<root>/questions_passed.json (k1.py and support.py read it). Exit 0 done, 2 error, 3 budget cap
(the job was not started; state saved).

Hard cap in the main phase (§8.2): when the cap refuses a job and not even one more draft fits
(state_a.cap_reached), `loop` stops drafting (state_a.stop_for_cap, also `stop-drafting`): no new
draft is planned, waiting drafts are audited / fixed while their job still fits, and a job the cap
refuses drops its draft (CAP_NOTE). The passed questions then go to the Kay page, K-U2 and F2.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import (ROOT, C, BudgetRefused, HoError, check_guard_copy, meta, out_dir,  # first: sys.path
                        read_json)

import claude_a as CL  # noqa: E402
import prompts_a as P  # noqa: E402
import runs_a as RU  # noqa: E402
import state_a as S  # noqa: E402

DEFAULT_ROUNDS = {"pilot": C.MAX_ATTEMPTS + 1, "main": 3 * C.MAX_ATTEMPTS + 2}
CAP_NOTE = "硬上限 140 USD：job 不啟動，停止出題後此稿刪除（§8.2）"


def make_ctx(root: Path, pin: CL.CliPin | None = None, cwd: Path = CL.AGENT_CWD,
             segments_path: Path = C.SEGMENTS) -> RU.Ctx:
    seg_doc = S.load_segments(segments_path)
    gen, audit = P.default_prompts()
    return RU.Ctx(seg_doc, S.slot_plan(seg_doc), gen, audit, pin or CL.load_pin(root), cwd,
                  rows=S.segment_rows(seg_doc))


def save(root: Path, state: Mapping[str, Any]) -> None:
    S.save_state(root, state)
    S.write_passed(root, state)


def _commit_all(root: Path, state: dict, jobs: Sequence[RU.Job], results: Mapping[str, RU.Outcome],
                commit) -> tuple[dict, list[str], list[str]]:
    """Commit every job that ran (slot order); returns (state, failures, budget refusals). After the
    hard-cap stop, a refused audit or fix drops its draft instead of being reported."""
    failed, refused = [], []
    for job in jobs:
        res = results[job.qid]
        if res.refused and state.get("cap_stop") and job.kind != "gen":
            if res.attempts:
                state = RU.record_runs(state, job.qid, job.kind, res.attempts)
            state = S.update_record(state, job.qid, S.DROPPED, CAP_NOTE, fix_request=None)
            save(root, state)
            continue
        if res.refused:
            refused.append(res.refused)
        if res.failed:
            failed.append(res.failed)
        if not res.attempts:
            continue
        try:
            state = commit(state, job, res.attempts)
        except HoError as err:
            state, failed = RU.record_runs(state, job.qid, job.kind, res.attempts), failed + [str(err)]
        save(root, state)
    return state, failed, refused


def _raise(failed: Sequence[str], refused: Sequence[str]) -> None:
    if refused:
        raise BudgetRefused(refused[0])
    if failed:
        raise HoError("; ".join(failed))


def draft_round(root: Path, ctx: RU.Ctx, phase: str) -> dict[str, Any]:
    state = S.load_state(root)
    planned = S.plan_round(state, ctx.slots, phase)
    if not planned:
        return state
    CL.write_wrappers(root)
    jobs = RU.gen_jobs(state, planned, ctx)
    results = RU.run_parallel(root, jobs, ctx)
    by_qid = {p.qid: p for p in planned}
    state, failed, refused = _commit_all(
        root, state, jobs, results, lambda st, job, att: RU.commit_draft(root, st, by_qid[job.qid], att, ctx))
    infra = [p.qid for p in planned if any(r["id"] == p.qid and r.get("infra_failure") for r in state["records"])]
    _raise(failed + ([f"基礎設施失敗 after {RU.MAX_RETRIES} reruns: {infra}"] if infra else []), refused)
    return state


def audit_pending(root: Path, ctx: RU.Ctx) -> dict[str, Any]:
    state = S.load_state(root)
    CL.write_wrappers(root)
    jobs = RU.audit_jobs(state, ctx)
    results = RU.run_parallel(root, jobs, ctx)
    state, failed, refused = _commit_all(root, state, jobs, results,
                                         lambda st, job, att: RU.commit_audit(root, st, job.qid, att))
    _raise(failed, refused)
    return state


def fix_needed(root: Path, ctx: RU.Ctx) -> dict[str, Any]:
    state = S.load_state(root)
    CL.write_wrappers(root)
    jobs = RU.fix_jobs(state, ctx)
    results = RU.run_parallel(root, jobs, ctx)
    state, failed, refused = _commit_all(root, state, jobs, results,
                                         lambda st, job, att: RU.commit_fix(root, st, job.qid, att, ctx))
    _raise(failed, refused)
    return state


def resolve_pending(root: Path, ctx: RU.Ctx) -> dict[str, Any]:
    """audit → fix → re-audit until no draft waits (bounded: each source fixes at most once)."""
    state = S.load_state(root)
    for _ in range(2 * (len(S.FIX_SOURCES) + 1)):
        if S.records(state, (S.PENDING,)):
            state = audit_pending(root, ctx)
        if S.records(state, (S.NEEDS_FIX,)):
            state = fix_needed(root, ctx)
        if not S.records(state, S.UNRESOLVED):
            return state
    raise HoError(f"drafts still unresolved: {[r['id'] for r in S.records(state, S.UNRESOLVED)]}")


def run_phase(root: Path, ctx: RU.Ctx, phase: str, rounds: int | None = None) -> dict[str, Any]:
    state = resolve_pending(root, ctx)
    for _ in range(DEFAULT_ROUNDS[phase] if rounds is None else rounds):
        if S.is_complete(state, ctx.slots, phase):
            break
        draft_round(root, ctx, phase)
        state = resolve_pending(root, ctx)
    return state


def k1_gate(root: Path, state: Mapping[str, Any]) -> dict[str, Any]:
    """The main phase needs k1.json (k1.py on the passed pilot questions) with stop false."""
    path = out_dir(root) / C.K1_JSON.name
    if not path.is_file():
        raise HoError(f"{path.name} missing: run k1.py on the passed pilot questions first (§3)")
    doc = read_json(path)
    est = state.get("reestimate") or {}
    n_pilot = est.get("pilot_passed", sum(r["pilot"] for r in S.records(state, (S.PASSED,))))
    if doc.get("stop") is not False:
        raise HoError(f"K1 stopped: {doc.get('wording')}")
    if doc.get("n_pass") != n_pilot:
        raise HoError(f"k1.json covers {doc.get('n_pass')} pilot questions, the state has {n_pilot} passed")
    return doc


def kay_gate(root: Path, state: Mapping[str, Any]) -> None:
    kay = state.get("kay")
    if kay and not kay.get("resolved"):
        raise HoError("the Kay page is drawn but not applied: kay_a.py apply first (§7)")
    if kay and (kay.get("layer") or {}).get("stop"):
        raise HoError(f"K0-1b stopped: {kay['layer'].get('wording')}")


def pilot(root: Path, ctx: RU.Ctx, rounds: int | None = None) -> dict[str, Any]:
    return run_phase(root, ctx, "pilot", rounds)


def main_gates(root: Path, state: Mapping[str, Any], slots: Sequence[S.Slot]) -> None:
    if not S.pilot_finished(state, slots):
        raise HoError("the pilot is not complete (§3)")
    k1_gate(root, state)
    if not state.get("reestimate"):
        raise HoError("run `budget --reestimate` after the pilot first (§8.2)")


def stop_drafting(root: Path, slots: Sequence[S.Slot]) -> dict[str, Any]:
    """§8.2 hard-cap stop (main phase only, and only when not even one more draft fits)."""
    state = S.load_state(root)
    main_gates(root, state, slots)
    if not S.cap_reached(root):
        spent = S.ledger(root)["total_usd"]
        raise HoError(f"已花 {spent:.2f} + 出題上限 {C.JOB_CAP_USD['gen']:g} ≤ {C.USD_CAP:g} USD：未達硬上限，不停止出題")
    state = S.stop_for_cap(state, S.ledger(root)["total_usd"])
    save(root, state)
    return state


def loop(root: Path, ctx: RU.Ctx, rounds: int | None = None) -> dict[str, Any]:
    state = S.load_state(root)
    main_gates(root, state, ctx.slots)
    kay_gate(root, state)
    try:
        return run_phase(root, ctx, "main", rounds)
    except BudgetRefused:
        if not S.cap_reached(root):
            raise
    stop_drafting(root, ctx.slots)
    return run_phase(root, ctx, "main", rounds)


def budget(root: Path, apply: bool = False, segments_path: Path = C.SEGMENTS) -> dict[str, Any]:
    state = S.load_state(root)
    slots = S.slot_plan(S.load_segments(segments_path))
    doc = {"ledger_total_usd": S.ledger(root)["total_usd"], "cap_usd": C.USD_CAP,
           "job_cap_usd": C.JOB_CAP_USD, "applied": state.get("reestimate")}
    if S.is_complete(state, slots, "pilot") and not state.get("reestimate"):
        est = S.reestimate(state, root, slots)
        doc["reestimate"] = est
        if apply:
            state = S.apply_reestimate(state, est)
            save(root, state)
            doc["applied"] = est
    elif apply and not state.get("reestimate"):
        raise HoError("the pilot is not complete (§8.2: the re-estimate follows the pilot)")
    return doc


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pilot", "loop", "audit", "fix", "status", "budget", "stop-drafting"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=ROOT)
        if name in ("pilot", "loop"):
            p.add_argument("--rounds", type=int)
        if name == "budget":
            p.add_argument("--reestimate", action="store_true", help="套用 §8.2 pilot 後重估（只一次）")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    root = a.root
    if a.cmd == "budget":
        print(f"run_ho_a.py budget: {budget(root, a.reestimate)}")
        return 0
    if a.cmd == "stop-drafting":
        state = stop_drafting(root, S.slot_plan(S.load_segments()))
        print(f"run_ho_a.py stop-drafting: {state['cap_stop']}; 接著跑 loop 處理等待中的稿")
        return 0
    if a.cmd == "status":
        state = S.load_state(root)
        slots = S.slot_plan(S.load_segments())
        print(f"run_ho_a.py status: {S.summary(state, slots)} ledger {S.ledger(root)['total_usd']} USD")
        return 0
    check_guard_copy()
    ctx = make_ctx(root)
    state = S.load_state(root)
    save(root, {**state, "meta_log": [*state.get("meta_log", []), meta(f"run_ho_a.py {a.cmd}", pin=ctx.pin.as_dict(),
                                                                         gen_sha256=ctx.gen.sha256,
                                                                         audit_sha256=ctx.audit.sha256)]})
    run = {"pilot": lambda: pilot(root, ctx, a.rounds), "loop": lambda: loop(root, ctx, a.rounds),
           "audit": lambda: audit_pending(root, ctx), "fix": lambda: fix_needed(root, ctx)}[a.cmd]
    state = run()
    print(f"run_ho_a.py {a.cmd}: {S.summary(state, ctx.slots)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BudgetRefused as err:
        print(f"run_ho_a.py: 預算上限：{err}", file=sys.stderr)
        sys.exit(3)
    except (HoError, OSError, ValueError) as err:
        print(f"run_ho_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
