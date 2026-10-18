"""Agent jobs and their commits into the question-writing state (private part of run_ho_a.py).

run_agent() launches one job with up to MAX_RETRIES reruns, only on infrastructure failures (no
result event, timeout, CLI start failure, API error). A run that ended on an agent limit
(claude_a.agent_limit: the --max-budget-usd cap, max turns, structured-output retries) is the
agent's outcome: never rerun, and it counts (draft → abandoned, one slot attempt; audit or fix →
dropped, the slot may be drafted again). Before every launch it takes the budget lock, checks the
§8.2 hard cap (spent + this job's cap ≤ 140 USD, state_a.check_cap) and writes the run's
reservation, so parallel jobs never overrun the cap together; a refused job is not started.

Commits (pure: state in, new state out), in slot order:
* draft  → abandoned (no question), needs_fix (mechanical error, source mech, once) or pending_audit;
* audit  → passed (ok / minor), needs_fix (major / critical, source audit, once) or dropped;
* fix    → revised / no_change go through the mechanical check again (an error there takes the one
           mech fix if still unused, else drops), then pending_audit (re-audit); dropped by the fixer.
Each source (mech, audit, kay) allows MAX_FIX_ROUNDS fix. A blinding error (transcript_a
BLINDING_RULES) in any run of a job drops the draft at once; its slot can be drafted again.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import C, BudgetRefused, HoError, Violation  # first: sets sys.path

import claude_a as CL  # noqa: E402
import mech_a as M  # noqa: E402
import prompts_a as P  # noqa: E402
import state_a as S  # noqa: E402
import transcript_a as TR  # noqa: E402

MAX_RETRIES = 2
BUDGET_LOCK = threading.Lock()


@dataclass(frozen=True)
class Ctx:
    """Everything a run of the executor shares: plan, prompts, CLI pin, agent cwd."""
    seg_doc: Mapping[str, Any]
    slots: tuple
    gen: P.PromptFile
    audit: P.PromptFile
    pin: CL.CliPin
    cwd: Path = CL.AGENT_CWD
    timeout_s: int = CL.DEFAULT_TIMEOUT_S
    rows: Mapping[str, Any] = field(default_factory=dict)

    def seg(self, sid: str) -> Mapping[str, Any]:
        return (self.rows or S.segment_rows(self.seg_doc))[sid]

    def slot(self, key: str) -> S.Slot:
        return next(s for s in self.slots if s.key == key)


@dataclass(frozen=True)
class Job:
    kind: str                   # gen | fix | audit
    qid: str
    prompt: P.PromptFile
    section: str
    values: Mapping[str, str]
    schema: Mapping[str, Any]
    budget: float


@dataclass(frozen=True)
class Outcome:
    attempts: tuple
    refused: str | None = None  # BudgetRefused message when a launch was not started
    failed: str | None = None   # HoError before a launch (cwd, memory directory, CLI version)


def _run_id(root: Path, kind: str, qid: str) -> str:
    n = 1
    while (Path(root) / "transcripts" / f"{kind}_{qid}_{n}.jsonl").exists() or \
            (Path(root) / "reserve" / f"{kind}_{qid}_{n}.json").exists():
        n += 1
    return f"{kind}_{qid}_{n}"


def run_agent(root: Path, job: Job, ctx: Ctx) -> Outcome:
    system, user = job.prompt.sections["system"], P.render(job.prompt, job.section, job.values)
    attempts = []
    for _ in range(1 + MAX_RETRIES):
        with BUDGET_LOCK:
            try:
                S.check_cap(root, job.budget)
            except BudgetRefused as err:
                return Outcome(tuple(attempts), str(err))
            run_id = _run_id(root, job.kind, job.qid)
            S.reserve(root, run_id, job.budget)
        try:
            res = CL.launch(root, run_id, system, user, job.schema, job.budget, ctx.pin, ctx.cwd, ctx.timeout_s,
                            {"kind": job.kind, "qid": job.qid, "prompt_file": job.prompt.path.name,
                             "prompt_sha256": job.prompt.sha256, "section": job.section})
        except BudgetRefused:
            raise
        except HoError as err:                      # refused before starting: nothing ran, release the cap
            if not (Path(root) / "transcripts" / f"{run_id}.jsonl").exists():
                (Path(root) / "reserve" / f"{run_id}.json").unlink(missing_ok=True)
            return Outcome(tuple(attempts), failed=f"{job.qid}: {err}")
        out = res.output or {}
        if res.error is None and job.kind == "audit" and out.get("id") != job.qid:
            res = CL.RunResult(res.run_id, res.transcript, res.returncode, res.seconds, res.result,
                               f"audit answered for id {out.get('id')!r}", res.usage)
        if res.error is not None:
            lim = CL.agent_limit(res.result, job.budget)
            res = replace(res, limit=lim) if lim else res
        attempts.append(res)
        if res.error is None or res.limit:
            break
    return Outcome(tuple(attempts))


def run_parallel(root: Path, jobs: Sequence[Job], ctx: Ctx) -> dict[str, Outcome]:
    """run_agent for every job, at most PARALLEL at once; keyed by qid."""
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=min(C.PARALLEL, len(jobs))) as pool:
        futures = {j.qid: pool.submit(run_agent, root, j, ctx) for j in jobs}
        return {k: f.result() for k, f in futures.items()}


# ------------------------------------------------------------------ job builders

def _values(state: Mapping[str, Any], ctx: Ctx, qid: str, slot: S.Slot) -> dict[str, str]:
    seg = ctx.seg(slot.segment)
    return {"qid": qid, "segment_code": slot.segment, "segment_line": P.segment_line(seg),
            "qtype_line": P.qtype_line(slot.slot_type, S.reverse_reference(state, slot)),
            "segment_done": P.segment_done(S.segment_passed(state, slot.segment, exclude=qid))}


def gen_jobs(state: Mapping[str, Any], planned: Sequence[S.Planned], ctx: Ctx) -> list[Job]:
    return [Job("gen", p.qid, ctx.gen, "task_new", _values(state, ctx, p.qid, p.slot), P.GEN_SCHEMA,
                C.JOB_CAP_USD["gen"]) for p in planned]


def fix_jobs(state: Mapping[str, Any], ctx: Ctx) -> list[Job]:
    out = []
    for r in S.records(state, (S.NEEDS_FIX,)):
        vals = {**_values(state, ctx, r["id"], ctx.slot(r["slot"])), "issues": P.issues_text(r["fix_request"] or {}),
                "item_json": P.item_json(r["item"])}
        out.append(Job("fix", r["id"], ctx.gen, "task_fix", vals, P.GEN_SCHEMA, C.JOB_CAP_USD["fix"]))
    return out


def audit_jobs(state: Mapping[str, Any], ctx: Ctx) -> list[Job]:
    return [Job("audit", r["id"], ctx.audit, "task_audit",
                {**_values(state, ctx, r["id"], ctx.slot(r["slot"])), "item_json": P.item_json(r["item"])},
                P.AUDIT_SCHEMA, C.JOB_CAP_USD["audit"]) for r in S.records(state, (S.PENDING,))]


# ------------------------------------------------------------------ commits

def record_runs(state: Mapping[str, Any], qid: str, kind: str, attempts: Sequence[CL.RunResult]) -> dict[str, Any]:
    new = dict(state)
    new["runs"] = {**state["runs"], **{r.run_id: {
        "kind": kind, "qid": qid, "error": r.error, "limit": r.limit, "seconds": r.seconds, "returncode": r.returncode,
        "usage": dict(r.usage), "transcript": r.transcript.name} for r in attempts}}
    for r in attempts:
        new = S.update_record(new, qid, append={"runs": r.run_id})
    return new


def blinding(root: Path, attempts: Sequence[CL.RunResult]) -> list[Violation]:
    return TR.blinding_errors(root, [r.run_id for r in attempts]) if attempts else []


def _dicts(found: Sequence[Violation]) -> list[dict[str, str]]:
    return [v.as_dict() for v in found]


def _breach_note(what: str, breach: Sequence[Violation]) -> str:
    return f"{what} transcript 違規（盲化）：{sorted({v.rule for v in breach})}，刪題，同 slot 可重出"


def _limit_note(what: str, limit: str) -> str:
    return f"{what} job 觸及代理上限（{limit}），不重跑、計一次嘗試"


def _mech(state: Mapping[str, Any], ctx: Ctx, rec_like: Mapping[str, Any], item: Mapping[str, Any]):
    slot = ctx.slot(rec_like["slot"])
    others = [r["item"] for r in S.records(state, S.LIVE, segment=slot.segment)
              if r["id"] != rec_like["id"] and r.get("item")]
    return M.check_item(item, rec_like["id"], ctx.seg(slot.segment), slot.slot_type, ctx.seg_doc["segments"],
                        others, S.reverse_reference(state, slot))


def _after_mech(state: Mapping[str, Any], qid: str, found: Sequence[Violation], ok_note: str,
                **fields: Any) -> dict[str, Any]:
    """pending_audit when clean; else the one mech fix (needs_fix) or dropped."""
    errs = M.errors_of(found)
    if not errs:
        return S.update_record(state, qid, S.PENDING, ok_note, fix_request=None, **fields)
    if S.fixes_from(S.record(state, qid), "mech") < C.MAX_FIX_ROUNDS:
        req = {"source": "mech", "issues": M.fix_issues(found), "suggested_fix": ""}
        return S.update_record(state, qid, S.NEEDS_FIX, "機械檢查未過，退回修題", fix_request=req, **fields)
    return S.update_record(state, qid, S.DROPPED, "機械檢查修題後仍未過，刪題", fix_request=None, **fields)


def commit_draft(root: Path, state: Mapping[str, Any], p: S.Planned, attempts: Sequence[CL.RunResult],
                 ctx: Ctx) -> dict[str, Any]:
    last = attempts[-1]
    out = last.output or {}
    breach = blinding(root, attempts)
    if last.error is not None and not last.limit:
        new = S.add_record(state, p, S.ABANDONED, None, f"基礎設施失敗：{last.error}", infra_failure=True,
                           transcript=_dicts(breach))
    elif breach:
        new = S.add_record(state, p, S.DROPPED, out.get("item"), _breach_note("出題", breach),
                           transcript=_dicts(breach))
    elif last.limit:
        new = S.add_record(state, p, S.ABANDONED, None, _limit_note("出題", last.limit), agent_limit=last.limit)
    elif out.get("status") != "drafted" or not isinstance(out.get("item"), dict):
        new = S.add_record(state, p, S.ABANDONED, None, f"{out.get('status')}: {out.get('reason', '')}")
    else:
        item = {k: out["item"].get(k) for k in P.ITEM_KEYS}
        new = S.add_record(state, p, S.PENDING, item, "已出題")
        found, hidden = _mech(new, ctx, S.record(new, p.qid), item)
        new = _after_mech(new, p.qid, found, "機械檢查通過", mech=_dicts(found), hidden=hidden)
    return record_runs(new, p.qid, "gen", attempts)


def commit_audit(root: Path, state: Mapping[str, Any], qid: str, attempts: Sequence[CL.RunResult]) -> dict[str, Any]:
    new = record_runs(state, qid, "audit", attempts)
    last = attempts[-1]
    breach = blinding(root, attempts)
    audit = {"run": last.run_id, **dict(last.output or {"error": last.error})}
    if breach:
        rec = S.record(new, qid)
        return S.update_record(new, qid, S.DROPPED, _breach_note("稽核", breach), append={"audits": audit},
                               transcript=[*rec["transcript"], *_dicts(breach)])
    if last.limit:
        return S.update_record(new, qid, S.DROPPED, f"{_limit_note('稽核', last.limit)}，刪題，同 slot 可重出",
                               append={"audits": audit}, fix_request=None, agent_limit=last.limit)
    if last.error is not None:
        raise HoError(f"{qid}: audit failed after {len(attempts)} attempts: {last.error}")
    sev = audit["severity"]
    if sev in ("ok", "minor"):
        return S.update_record(new, qid, S.PASSED, f"稽核 {sev}", append={"audits": audit})
    if S.fixes_from(S.record(new, qid), "audit") < C.MAX_FIX_ROUNDS:
        req = {"source": "audit", "issues": audit["issues"], "suggested_fix": audit["suggested_fix"]}
        return S.update_record(new, qid, S.NEEDS_FIX, f"稽核 {sev}", append={"audits": audit}, fix_request=req)
    return S.update_record(new, qid, S.DROPPED, f"稽核 {sev}，修正後複驗仍未通過", append={"audits": audit})


def commit_fix(root: Path, state: Mapping[str, Any], qid: str, attempts: Sequence[CL.RunResult],
               ctx: Ctx) -> dict[str, Any]:
    new = record_runs(state, qid, "fix", attempts)
    last, rec = attempts[-1], S.record(new, qid)
    out = dict(last.output or {})
    fix = {"run": last.run_id, "source": (rec["fix_request"] or {}).get("source"), "status": out.get("status"),
           "reason": out.get("reason", last.error or "")}
    breach = blinding(root, attempts)
    if breach:
        return S.update_record(new, qid, S.DROPPED, _breach_note("修題", breach), append={"fixes": fix},
                               fix_request=None, transcript=[*rec["transcript"], *_dicts(breach)])
    if last.limit:
        return S.update_record(new, qid, S.DROPPED, f"{_limit_note('修題', last.limit)}，刪題，同 slot 可重出",
                               append={"fixes": fix}, fix_request=None, agent_limit=last.limit)
    if last.error is not None:
        raise HoError(f"{qid}: fix failed after {len(attempts)} attempts: {last.error}")
    new = S.update_record(new, qid, append={"fixes": fix})
    if out.get("status") in ("revised", "no_change") and isinstance(out.get("item"), dict):
        item = {k: out["item"].get(k) for k in P.ITEM_KEYS} if out["status"] == "revised" else rec["item"]
        found, hidden = _mech(new, ctx, rec, item)
        note = "已修正，待複驗" if out["status"] == "revised" else "修題者認為意見不成立，待複驗"
        return _after_mech(new, qid, found, note, item=item, mech=_dicts(found), hidden=hidden)
    return S.update_record(new, qid, S.DROPPED, f"修題者放棄：{fix['reason']}", fix_request=None)
