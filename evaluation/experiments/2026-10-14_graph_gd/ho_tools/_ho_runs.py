"""Agent runs and their commits into the HO state (private part of run_gen.py / run_audit.py).

run_agent() launches one agent with up to MAX_RETRIES reruns, only on 基礎設施失敗 (§10:
CLI error, no result, no structured output). The commit functions turn an agent's output
into a new state: a draft is annotated and mechanically checked against the live drafts
committed before it (mech_check.check_item) and lands as pending_audit or blocked; an audit
moves a draft to passed / needs_fix / dropped (§7: major、critical 須修好並複驗，否則刪題);
a fix lands back in pending_audit (re-audit), blocked or dropped. Besides mech_check's rules,
a commit refuses an item whose id or category is not its slot's (rule slot_mismatch).

Every commit also runs the §7 transcript rules on the job's runs (_ho_transcript): a
blinding error (t_init, t_tool, t_path, t_memory, t_banned) drops the question at once
(由後續題遞補), so no selected question can stop freeze later; the violations stay on the
record ("transcript"). Banned words the agents wrote themselves are warnings there.
used_cores() is what the agents see of the §7 core rule: every core in use with its count.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import HO_DIR, HoToolError, Violation, gd  # first: sets sys.path

import _ho_claude as C  # noqa: E402
import _ho_prompts as P  # noqa: E402
import _ho_state as S  # noqa: E402
import _ho_transcript as TR  # noqa: E402
import annotate  # noqa: E402
import mech_check as M  # noqa: E402

__all__ = ["MAX_RETRIES", "AGENT_FILES", "Job", "run_agent", "run_parallel", "used_cores",
           "record_runs", "blinding", "commit_draft", "commit_fix", "commit_audit", "audit_fixes",
           "NO_CORES", "log_meta", "run_settings"]

MAX_RETRIES = 2
NO_CORES = "（無）"
AGENT_FILES = tuple(HO_DIR / n for n in (
    "bt.py", "bt_guard.py", "_ho_text.py", "_ho_common.py", "_ho_state.py", "_ho_claude.py",
    "_ho_prompts.py", "_ho_runs.py", "_ho_transcript.py", "banned.py", "annotate.py",
    "mech_check.py", "gen_prompt.md", "audit_prompt.md"))


class Job:
    """One agent task: run id prefix, prompt section and values, schema, budget."""

    def __init__(self, key: str, kind: str, qid: str, prompt: P.PromptFile, section: str,
                 values: Mapping[str, str], schema: Mapping[str, Any], budget: float) -> None:
        self.key, self.kind, self.qid, self.prompt, self.section = key, kind, qid, prompt, section
        self.values, self.schema, self.budget = dict(values), schema, budget


def _run_id(root: Path, kind: str, qid: str) -> str:
    n = 1
    while (Path(root) / "transcripts" / f"{kind}_{qid}_{n}.jsonl").exists():
        n += 1
    return f"{kind}_{qid}_{n}"


def _bad_output(job: Job, res: C.RunResult) -> str | None:
    out = res.output or {}
    if job.kind == "audit" and out.get("id") != job.qid:
        return f"audit answered for id {out.get('id')!r}"
    return None


def run_agent(root: Path, job: Job, cwd: Path = C.AGENT_CWD,
              timeout_s: int = C.DEFAULT_TIMEOUT_S) -> list[C.RunResult]:
    """All attempts of one job; the last one is usable unless its .error is set."""
    system = job.prompt.sections["system"]
    user = P.render(job.prompt, job.section, job.values)
    attempts = []
    for _ in range(1 + MAX_RETRIES):
        run_id = _run_id(root, job.kind, job.qid)
        res = C.launch(root, run_id, system, user, job.schema, job.budget, cwd, timeout_s,
                       {"kind": job.kind, "qid": job.qid, "prompt_file": job.prompt.path.name,
                        "prompt_sha256": job.prompt.sha256, "section": job.section})
        bad = res.error or _bad_output(job, res)
        if bad and not res.error:
            res = C.RunResult(res.run_id, res.transcript, res.returncode, res.seconds, res.result,
                              bad, res.usage)
        attempts.append(res)
        if res.error is None:
            break
    return attempts


def run_parallel(root: Path, jobs: Sequence[Job], **kw: Any) -> dict[str, list[C.RunResult]]:
    """run_agent for every job at once (threads wait on subprocesses); keyed by job.key."""
    if not jobs:
        return {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {j.key: pool.submit(run_agent, root, j, **kw) for j in jobs}
        return {k: f.result() for k, f in futures.items()}


def record_runs(state: Mapping[str, Any], qid: str, kind: str,
                attempts: Sequence[C.RunResult]) -> dict[str, Any]:
    """New state with the runs logged (state['runs']) and linked to the record."""
    new = dict(state)
    new["runs"] = {**state["runs"], **{r.run_id: {
        "kind": kind, "qid": qid, "error": r.error, "seconds": r.seconds, "returncode": r.returncode,
        "usage": dict(r.usage), "transcript": r.transcript.name} for r in attempts}}
    for r in attempts:
        new = S.update_record(new, qid, append={"runs": r.run_id})
    return new


def used_cores(state: Mapping[str, Any], exclude: str | None = None) -> str:
    """Every core live drafts (minus `exclude`) use, with its count, full ones marked:
    「約西亞（2 題，已滿）、參巴拉（1 題）」. The agents see all of them, so a variant
    spelling of a full core is visible to the drafter, the fixer and the auditor."""
    counts: dict[str, int] = {}
    for _, item in S.live_items(state, exclude):
        core = str(item.get("core") or "").strip()
        if core:
            counts[core] = counts.get(core, 0) + 1
    shown = [f"{c}（{n} 題{'，已滿' if n >= gd.HO_MAX_PER_CORE else ''}）" for c, n in sorted(counts.items())]
    return "、".join(shown) if shown else NO_CORES


def _expected_category(cat: str, subtype: str) -> str:
    return subtype if cat == "MH" else cat


def _checked_item(state: Mapping[str, Any], qid: str, cat: str, subtype: str, raw: Mapping[str, Any],
                  ctx: M.Context) -> tuple[dict[str, Any], list[Violation]]:
    """Annotated item and its violations against the live drafts committed before it."""
    item = annotate.annotate_item({k: raw.get(k) for k in P.ITEM_KEYS})
    earlier = [it for _, it in S.live_items(state, exclude=qid)]
    found = M.check_item(item, ctx, earlier)
    if item.get("id") != qid or item.get("category") != _expected_category(cat, subtype):
        found.append(Violation("slot_mismatch", f"{qid}: got id {item.get('id')!r}, "
                               f"category {item.get('category')!r}"))
    return item, found


def _errors(found: Sequence[Violation]) -> list[dict[str, str]]:
    return [v.as_dict() for v in found]


def blinding(attempts: Sequence[C.RunResult]) -> list[Violation]:
    """BLINDING_RULES errors of every attempt of one job (transcripts under their root)."""
    if not attempts:
        return []
    return TR.blinding_errors(attempts[0].transcript.parent.parent, [r.run_id for r in attempts])


def _breach_note(what: str, breach: Sequence[Violation]) -> str:
    return f"{what} transcript 違規（盲化）：{sorted({v.rule for v in breach})}，刪題，由後續題遞補"


def _drop_for_breach(state: Mapping[str, Any], qid: str, what: str, breach: Sequence[Violation],
                     append: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    """New state with the question dropped for a transcript breach of one of its runs."""
    rec = S.record(state, qid)
    return S.update_record(state, qid, S.DROPPED, _breach_note(what, breach), append=append,
                           transcript=[*rec.get("transcript", []), *_errors(breach)], **fields)


def commit_draft(state: Mapping[str, Any], slot: S.Slot, attempts: Sequence[C.RunResult],
                 ctx: M.Context) -> dict[str, Any]:
    """New state with the slot's record: abandoned, blocked, pending_audit, or dropped when
    a run broke the blinding (its question never reaches an auditor)."""
    last = attempts[-1]
    out = last.output or {}
    breach = blinding(attempts)
    if last.error is not None:
        new = S.add_record(state, slot, S.ABANDONED, None, f"基礎設施失敗：{last.error}", infra_failure=True,
                           transcript=_errors(breach))
    elif out.get("status") != "drafted" or not isinstance(out.get("item"), dict):
        new = S.add_record(state, slot, S.ABANDONED, None, f"{out.get('status')}: {out.get('reason', '')}",
                           transcript=_errors(breach))
    else:
        item, found = _checked_item(state, slot.qid, slot.cat, slot.subtype, out["item"], ctx)
        bad = any(v.level == "error" for v in found)
        status, note = (S.BLOCKED, "機械檢查未過") if bad else (S.PENDING, "機械檢查通過")
        if breach:
            status, note = S.DROPPED, _breach_note("出題", breach)
        new = S.add_record(state, slot, status, item, note, mech=_errors(found), transcript=_errors(breach))
    return record_runs(new, slot.qid, "gen", attempts)


def audit_fixes(rec: Mapping[str, Any]) -> int:
    return sum(f.get("source") == "audit" for f in rec.get("fixes") or ())


def commit_audit(state: Mapping[str, Any], qid: str, attempts: Sequence[C.RunResult]) -> dict[str, Any]:
    """New state after one audit: passed (ok/minor), needs_fix, or dropped after a failed fix
    or a transcript breach (checked first, also when every attempt failed)."""
    new = record_runs(state, qid, "audit", attempts)
    last = attempts[-1]
    breach = blinding(attempts)
    audit = {"run": last.run_id, **dict(last.output or {"error": last.error})}
    if breach:
        return _drop_for_breach(new, qid, "稽核", breach, {"audits": audit})
    if last.error is not None:
        raise HoToolError(f"{qid}: audit failed after {len(attempts)} attempts: {last.error}")
    sev = audit["severity"]
    rec = S.record(new, qid)
    if sev in ("ok", "minor"):
        return S.update_record(new, qid, S.PASSED, f"稽核 {sev}", append={"audits": audit})
    if audit_fixes(rec) < S.MAX_FIX_ROUNDS:
        request = {"source": "audit", "issues": audit["issues"], "suggested_fix": audit["suggested_fix"]}
        return S.update_record(new, qid, S.NEEDS_FIX, f"稽核 {sev}", append={"audits": audit},
                               fix_request=request)
    return S.update_record(new, qid, S.DROPPED, f"稽核 {sev}，修正後複驗仍未通過", append={"audits": audit})


def commit_fix(state: Mapping[str, Any], qid: str, attempts: Sequence[C.RunResult],
               ctx: M.Context) -> dict[str, Any]:
    """New state after one fix: pending_audit (revised / no_change), blocked, or dropped
    (given up, or a transcript breach: checked first, also when every attempt failed)."""
    new = record_runs(state, qid, "fix", attempts)
    last = attempts[-1]
    out, rec = dict(last.output or {}), S.record(new, qid)
    fix = {"run": last.run_id, "source": rec["fix_request"]["source"], "status": out.get("status"),
           "reason": out.get("reason", last.error or "")}
    breach = blinding(attempts)
    if breach:
        return _drop_for_breach(new, qid, "修題", breach, {"fixes": fix}, fix_request=None)
    if last.error is not None:
        raise HoToolError(f"{qid}: fix failed after {len(attempts)} attempts: {last.error}")
    if out.get("status") == "revised" and isinstance(out.get("item"), dict):
        item, found = _checked_item(new, qid, rec["cat"], rec["subtype"], out["item"], ctx)
        bad = any(v.level == "error" for v in found)
        return S.update_record(new, qid, S.BLOCKED if bad else S.PENDING,
                               "修正後機械檢查未過" if bad else "已修正，待複驗", append={"fixes": fix},
                               item=item, mech=_errors(found), fix_request=None)
    if out.get("status") == "no_change":
        return S.update_record(new, qid, S.PENDING, "修題者認為意見不成立，待複驗",
                               append={"fixes": fix}, fix_request=None)
    return S.update_record(new, qid, S.DROPPED, f"修題者放棄：{fix['reason']}",
                           append={"fixes": fix}, fix_request=None)


def log_meta(root: Path, meta: Mapping[str, Any]) -> None:
    """Append one executor run's §10 meta to the state's meta_log (saved at once)."""
    state = S.load_state(root)
    S.save_state(root, {**state, "meta_log": [*state.get("meta_log", []), dict(meta)]})


def run_settings(root: Path) -> dict[str, Any]:
    """What every agent of this executor run gets, for its §10 meta: model, effort, cwd, the
    tool restrictions and the exact `bt` / `bt-guard` wrapper texts (written here)."""
    return {"root": str(root), "model": C.MODEL, "effort": C.EFFORT, "thinking_display": C.THINKING_DISPLAY,
            "agent_cwd": str(C.AGENT_CWD),
            "allowed_tools": list(C.ALLOWED_TOOLS), "disallowed_tools": list(C.DISALLOWED_TOOLS),
            "guard_settings": C.guard_settings(), "wrappers": C.write_wrappers(root),
            "max_retries": MAX_RETRIES, "claude_version": C.claude_version()}
