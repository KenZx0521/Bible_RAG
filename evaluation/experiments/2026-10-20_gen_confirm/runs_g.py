"""Agent jobs of the blind question writing and their commits into the HO state (prereg §3.1–§3.7, §8.1-8, §8.2).

Every job is a new `claude -p` session launched through claude_g.run_reserved (kind "ho", tools mode "bt", the pin's
opus id, effort xhigh) under HO_ROOT/pilot, HO_ROOT/main or HO_ROOT/kay (a disputed attempt Kay kept, and Kay's
revisions). Prompts come from prompts_g with the slot's own pool row and draft only (no other slot's question or
answer, §3.1): a draft (render_writer, user scope "prompt", cap JOB_CAP_USD.draft), a fix (render_fix / render_kay_revise,
scope "agent", cap .fix), a value-blind audit (render_audit: the question and the English definition, scope "agent",
cap .audit). The tool values go into the launch record (tool_values) for transcript_g.

A job retries while its run is an infrastructure failure (claude_g.RunResult.infra_failure: no result, timeout, model
fallback, a CLI that never started, …; and an audit output mech_g.check_audit refuses), up to MAX_INFRA_RETRIES
reruns; never an attempt (§2.3). After each run transcript_g.check_run's BLINDING_RULES errors (transcript_g.blinding)
end the job: a blinding error in any run drops the draft and the attempt counts. On a run that failed for
infrastructure its own failure is not a breach (``infra_own``: no init event — the CLI never started a session —, and
on a model fallback the init event's other model); every other rule (cwd, tools, MCP, paths, words) still is. An
agent limit (claude_g.agent_limit: the budget cap, max turns, structured-output retries) is the agent's outcome:
never rerun, the attempt ends. Before a launch: BudgetRefused (the single ledger, §3.9), CliChanged (§3.1
infrastructure stop: the runner records a CLI stop and stops; re-probe, then run_ho_g.py repin), CliUnavailable (the
job is planned again later, not an attempt) and other HoError refusals leave the step as it was. A job that used
its reruns records an infra stop (state_g.infra_stop) and the runner stops (InfraStop): no HO job starts again
before a logged fix (run_ho_g --infra-fix), so a job never gets more than 1 + MAX_INFRA_RETRIES runs per fix.

Commits (pure: state in, new state out), the §3.1 order:
* draft → mech_g.check_draft (no gold): clean → audit (the item canonical_item'd); errors → the attempt's mech fix
  round (mech_g.fix_issues) or, once it is spent, the attempt ends;
* fix → revised: mech again; no_change with a reason: dispute (not deleted, §3.4; after an audit fix whose values were
  §3.6 row 3, the row-3 dispute); no_change without a reason, dropped, abandoned: the attempt ends. §3.4's
  audit-vs-mech conflict: the mech rules an audit-source revision broke (``audit_broke``) are the rules the audit's
  finding conflicts with. When such a revision fails mech the attempt's mech round goes first (if unused); with
  the round spent the item goes to the dispute only when every error left is one of those rules (the break the
  audit drove persisted), else the attempt ends as for any mech failure (a new error is the writer's own). Errors
  Kay overruled on this attempt (``kept_mech``, a kept mech dispute) are not errors any more;
* audit → mech_g.check_audit, then mech_g.after_audit with the pool gold (§3.6): pass | fix (the audit round,
  neutral hints) | dispute (row 3: the CPU comparison of the cited verses with stage-0's independent reader,
  ``cpu_gold_trace``; a reader that disagrees with the gold is K-gold) | end_attempt.
A Kay revision (source kay, §3.7) is one fix: mech must pass and the re-audit must pass outright (no further
round); any failure (mech, no_change, dropped, a re-audit that does not pass, a blinding error, an agent limit)
closes the slot as kay_dropped and counts as a Kay drop for K-Kay. After Kay's page a new dispute closes the slot
(failed, or other_quantity for row 3): there is no second page. ``drive`` takes a stop predicate (Kay's work: K-Kay
or K-gold reached) checked before every wave, so nothing more launches once a stop rule holds.

``drive`` runs waves of at most PARALLEL jobs (threads): jobs waiting on a live draft first, then new drafts, each
in writing order; a wave admits a job only while ledger spent + the wave's caps ≤ USD_CAP − START_MARGIN_USD, so the
reservations inside never collide; a job whose cap alone does not fit is cap-refused (pilot: BudgetRefused, exit 3;
main: drafting stops (no draft fits any more) and the refused slot is cap_stopped; Kay work: cap_stopped). Commits run
in the wave's order on the main thread and the state is saved after each. Nothing here runs gencard (§5.5).
"""
from __future__ import annotations

import functools
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import claude_g as CL
import f1_g as F1
import g_common as GC
import ledger_g as L
import mech_g as M
import prompts_g as P
import state_g as S
import transcript_g as TR
from hog_common import BudgetRefused, CliChanged, CliUnavailable, HoError

KIND = "ho"
TOOLS_MODE = "bt"
SCOPE = {"draft": "prompt", "fix": "agent", "audit": "agent"}
UNAVAILABLE_WAVES = GC.UNAVAILABLE_WAVES             # waves in a row in which every job met CliUnavailable
EPS = L.EPS
STEP_JOB = {S.DRAFTING: "draft", S.PENDING_AUDIT: "audit", S.NEEDS_FIX: "fix"}
_KEY = re.compile(r"^gen\.(\d+)\.(\d+)(?:-(?:gen\.(\d+)\.)?(\d+))?$")


NO_INIT = "no init event"                           # transcript_g.init_violations when the CLI never started


class KGold(HoError):
    """prereg §3.6: the CPU trace shows the program gold is wrong (the independent reader disagrees): the line stops."""


class InfraStop(HoError):
    """prereg §2.3: a job used its MAX_INFRA_RETRIES reruns; the stop is recorded and the runner stops."""


@dataclass(frozen=True)
class Ctx:
    paths: S.Paths
    plan: S.Plan
    names: P.Names
    pin: CL.CliPin
    prompts: tuple[P.PromptFile, P.PromptFile]
    cwd: Path = CL.AGENT_CWD
    home: Path | None = None
    timeout_s: int = CL.DEFAULT_TIMEOUT_S
    parallel: int = GC.PARALLEL
    gold_trace: Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], dict] | None = None
    prereg: Path = F1.PREREG                         # its 執行紀錄 holds the anchors of logged fixes

    @property
    def model(self) -> str:
        return self.pin.model("opus")

    def row(self, sid: str) -> Mapping[str, Any]:
        return self.plan.slots[sid].row

    def qid(self, sid: str) -> str:
        return self.plan.slots[sid].qid

    def spec(self, sid: str) -> P.SlotSpec:
        return P.slot_spec(self.row(sid), self.names, self.qid(sid))

    def trace(self, sid: str, item: Mapping[str, Any], audit: Mapping[str, Any]) -> dict:
        return (self.gold_trace or cpu_gold_trace)(self.row(sid), item, audit)


@dataclass(frozen=True)
class Job:
    sid: str
    qid: str
    kind: str                       # draft | fix | audit
    source: str | None              # fix: mech | audit | kay
    attempt: int
    root: str                       # pilot | main | kay
    rendered: P.Rendered
    new_attempt: bool = False

    @property
    def label(self) -> str:
        return f"fix-{self.source}" if self.kind == "fix" else self.kind

    @property
    def budget(self) -> float:
        return GC.JOB_CAP_USD[self.kind]

    @property
    def user_scope(self) -> str:
        return SCOPE[self.kind]

    def record(self) -> dict[str, Any]:
        return {"sid": self.sid, "qid": self.qid, "kind": self.kind, "source": self.source, "attempt": self.attempt,
                "root": self.root, "prompt_file": self.rendered.prompt_file,
                "prompt_sha256": self.rendered.prompt_sha256, "section": self.rendered.section}


@dataclass(frozen=True)
class Try:
    run_id: str
    result: CL.RunResult
    breach: tuple[Mapping[str, str], ...] = ()
    invalid: tuple[str, ...] = ()

    @property
    def infra(self) -> bool:
        return not self.breach and self.result.limit is None and (self.result.infra_failure or bool(self.invalid))


@dataclass(frozen=True)
class Outcome:
    tries: tuple[Try, ...] = ()
    refused: str | None = None
    cli_changed: str | None = None
    unavailable: str | None = None
    failed: str | None = None

    @property
    def stopped(self) -> str | None:
        """Why the job stopped before a run could settle it (the step stays as it was)."""
        return self.refused or self.cli_changed or self.unavailable or self.failed

    @property
    def breach(self) -> list[Mapping[str, str]]:
        return [v for t in self.tries for v in t.breach]

    @property
    def limit(self) -> str | None:
        return self.tries[-1].result.limit if self.tries else None

    @property
    def infra_exhausted(self) -> bool:
        return bool(self.tries) and not self.stopped and self.tries[-1].infra

    @property
    def output(self) -> Mapping[str, Any]:
        out = self.tries[-1].result.output if self.tries else None
        return out if isinstance(out, Mapping) else {}


def infra_own(v: Mapping[str, Any], run: Mapping[str, Any]) -> bool:
    """On a run that failed for infrastructure (an error that is not an agent limit), whether the violation is that
    failure itself rather than a blinding breach (§2.3): no result event, no init event, and on a model fallback
    the init event naming the other model. ``run`` has the run record's error, limit and fallback."""
    if run.get("error") is None or run.get("limit") is not None:
        return False
    rule, detail = v.get("rule"), str(v.get("detail") or "")
    return rule == "t_result" or rule == "t_init" and (detail == NO_INIT or bool(run.get("fallback"))
                                                        and detail.startswith("model "))


def err_key(v: Mapping[str, Any]) -> tuple:
    """A mech error as Kay overruled it: rule, detail and quote (a reworded hit is a new error)."""
    return v.get("rule"), v.get("detail"), v.get("quote", "")


# ---------------------------------------------------------------- the text layer and the §3.6 row-3 CPU trace
@functools.lru_cache(maxsize=1)
def verse_units() -> tuple[dict[str, Any], ...]:
    """Genesis units of stage-0's text layer (unit_key, chapter, v_start, v_end, text), in order."""
    X = GC.stage0().x_common
    rows = [r for r in X.jsonl(X.TEXT / "verse_units.jsonl") if r["book_id"] == "gen"]
    return tuple(sorted(rows, key=lambda r: r["ord"]))


def units_of(key: str, units: Sequence[Mapping[str, Any]] | None = None) -> list[Mapping[str, Any]]:
    """The text-layer units a cited key covers (gen.5.3, gen.5.3-5, gen.5.3-gen.6.2, a merged unit key); [] if none."""
    units = verse_units() if units is None else units
    k = str(key or "").strip().lower()
    exact = [u for u in units if u["unit_key"] == k]
    m = _KEY.match(k)
    if exact or not m:
        return exact
    c1, v1 = int(m[1]), int(m[2])
    c2, v2 = (int(m[3]) if m[3] else c1), (int(m[4]) if m[4] else v1)
    return [u for u in units if (c1, v1) <= (u["chapter"], u["v_end"]) and (u["chapter"], u["v_start"]) <= (c2, v2)]


def verse_text(key: str) -> list[tuple[str, str]]:
    """(unit key, text) of a cited key, for Kay's page (store only)."""
    return [(u["unit_key"], u["text"]) for u in units_of(key)]


def cpu_gold_trace(row: Mapping[str, Any], item: Mapping[str, Any], audit: Mapping[str, Any]) -> dict:
    """§3.6 row 3: the writer's cited verses against stage-0's independent reader (items_x.verify_gold, which reads
    the numbers again from verse_units.jsonl) on this slot. ``agrees`` false is K-gold. Keys and numbers only."""
    S0 = GC.stage0()
    I = S0.items_x
    c = dict(qtype=row["qtype"], chapter=row["chapter"], pool=row["stratum"], path=list(row["persons"]),
             gold=row["gold"])
    it = I.gen_item(S0.gen_layer.load(), c)
    value, _ = I._verify_gen(it)
    problems = I.verify_gold(it)
    read = list(dict.fromkeys(it["keys"][0]["basis"]))
    cited = [str(s.get("verse", "")).strip() for s in item.get("steps") or () if isinstance(s, Mapping)]
    cited_units = list(dict.fromkeys(u["unit_key"] for k in cited for u in units_of(k)))
    texts = {u["unit_key"]: u["text"] for u in verse_units()}
    return {"gold": row["gold"], "reader_value": value, "reader_problems": problems, "agrees": not problems,
            "reader_verses": read, "cited_verses": cited, "cited_units": cited_units,
            "cited_not_read": [u for u in cited_units if u not in read],
            "read_not_cited": [u for u in read if u not in cited_units],
            "unresolved_cited": [k for k in cited if not units_of(k)],
            "numbers": {u: I.numbers_in_text(texts[u]) for u in dict.fromkeys(read + cited_units) if u in texts},
            "writer_value": writer_value(item), "auditor_value": audit.get("value")}


# ---------------------------------------------------------------- planning
def writer_value(item: Mapping[str, Any] | None) -> int | None:
    ans = (item or {}).get("answer")
    v = ans.get("value") if isinstance(ans, Mapping) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def issues_json(issues: Sequence[P.Issue]) -> list[list[list[str]]]:
    return [[list(p) for p in i.parts] for i in issues]


def issues_of(data: Sequence[Sequence[Sequence[str]]]) -> tuple[P.Issue, ...]:
    return tuple(P.Issue.of(*(tuple(p) for p in parts)) for parts in data)


def decision_json(d: M.Decision) -> dict[str, Any]:
    return {"action": d.action, "case": d.case, "issues": issues_json(d.issues), "reaudit": d.reaudit,
            "uses_audit_round": d.uses_audit_round, "gold_trace": d.gold_trace, "severity": d.severity,
            "closes_slot": d.closes_slot}


def render(ctx: Ctx, sid: str, kind: str, att: Mapping[str, Any] | None) -> P.Rendered:
    row, qid = ctx.row(sid), ctx.qid(sid)
    if kind == "draft":
        return P.render_writer(row, ctx.names, qid, prompts=ctx.prompts)
    if kind == "audit":
        return P.render_audit(att["item"]["question"], row, qid, ctx.names, prompts=ctx.prompts)
    req = att["fix_request"]
    if req["source"] == "kay":
        return P.render_kay_revise(row, ctx.names, qid, att["item"], att["kay_revision"]["note"], prompts=ctx.prompts)
    return P.render_fix(req["source"], row, ctx.names, qid, att["item"], issues_of(req["issues"]), prompts=ctx.prompts)


def job_for(state: Mapping[str, Any], ctx: Ctx, sid: str, root: str, drafting: bool) -> Job | None:
    """The slot's next job, or None (done, waiting for Kay, or a new draft not allowed)."""
    rec = S.slot(state, sid)
    st, att = rec["status"], S.current(rec)
    if rec["inflight"]:
        return None
    if st in S.NEEDS_DRAFT:
        if not drafting or S.attempts_used(rec) >= GC.MAX_ATTEMPTS:
            return None
        return Job(sid, ctx.qid(sid), "draft", None, len(rec["attempts"]) + 1, root, render(ctx, sid, "draft", None),
                   new_attempt=True)
    kind = STEP_JOB.get(st)
    if kind is None or (kind == "draft" and not drafting):
        return None
    source = att["fix_request"]["source"] if kind == "fix" else None
    return Job(sid, ctx.qid(sid), kind, source, att["n"], att["root"], render(ctx, sid, kind, att))


def plan_jobs(state: Mapping[str, Any], ctx: Ctx, sids: Sequence[str], root: str, drafting: bool) -> list[Job]:
    """Jobs on live drafts first, then new drafts, each in writing order."""
    jobs = [j for j in (job_for(state, ctx, sid, root, drafting) for sid in sids) if j is not None]
    pos = {sid: ctx.plan.slots[sid].position for sid in sids}
    return sorted(jobs, key=lambda j: (j.kind == "draft", pos[j.sid]))


def admit(jobs: Sequence[Job], spent: float, parallel: int,
          limit: float = L.SPEND_LIMIT_USD) -> tuple[list[Job], list[Job]]:
    """(wave, cap-refused): a job joins while spent + the wave's caps ≤ limit; refused when its cap alone does not fit."""
    wave, refused, total = [], [], spent
    for j in jobs:
        if spent + j.budget > limit + EPS:
            refused.append(j)
        elif len(wave) < parallel and total + j.budget <= limit + EPS:
            wave.append(j)
            total += j.budget
    return wave, refused


# ---------------------------------------------------------------- launching
def next_run_id(root: Path, job: Job) -> str:
    base, k = f"{job.qid}_a{job.attempt}_{job.label}", 1
    while L.has_run(root, f"{base}_{k}"):
        k += 1
    return f"{base}_{k}"


def output_problems(job: Job, out: Any) -> tuple[str, ...]:
    """An audit output check_audit refuses is an infrastructure failure (rerun); a writer's output is its outcome."""
    return tuple(v.detail for v in M.check_audit(out, job.qid)) if job.kind == "audit" else ()


def run_job(ctx: Ctx, job: Job) -> Outcome:
    r, root, tries = job.rendered, ctx.paths.root(job.root), []
    for _ in range(1 + GC.MAX_INFRA_RETRIES):
        run_id = next_run_id(root, job)
        try:
            res = CL.run_reserved(KIND, root, run_id, r.system, r.user, r.schema, job.budget, ctx.model, ctx.pin,
                                  user_scope=job.user_scope, out_root=ctx.paths.out_root, tools_mode=TOOLS_MODE,
                                  effort=CL.EFFORT, cwd=ctx.cwd, timeout_s=ctx.timeout_s, tool_values=dict(r.values),
                                  home=ctx.home, extra_record={"job": job.record()})
        except BudgetRefused as err:
            return Outcome(tuple(tries), refused=str(err))
        except CliChanged as err:
            return Outcome(tuple(tries), cli_changed=str(err))
        except CliUnavailable as err:
            return Outcome(tuple(tries), unavailable=str(err))
        except HoError as err:
            return Outcome(tuple(tries), failed=f"{job.qid}: {err}")
        own = {"error": res.error, "limit": res.limit, "fallback": res.fallback}
        found = [v.as_dict() for v in TR.blinding(TR.check_run(root, run_id))]
        breach = tuple(d for d in found if not infra_own(d, own))
        invalid = () if res.error is not None else output_problems(job, res.output)
        tries.append(Try(run_id, res, breach, invalid))
        if not tries[-1].infra:
            break
    return Outcome(tuple(tries))


def run_wave(ctx: Ctx, wave: Sequence[Job]) -> list[Outcome]:
    if not wave:
        return []
    with ThreadPoolExecutor(max_workers=min(ctx.parallel, len(wave))) as pool:
        return [f.result() for f in [pool.submit(run_job, ctx, j) for j in wave]]


# ---------------------------------------------------------------- commits
def run_info(ctx: Ctx, job: Job, t: Try) -> dict[str, Any]:
    rel = ctx.paths.root(job.root).resolve().relative_to(Path(ctx.paths.out_root).resolve()).as_posix()
    res = t.result
    return {"key": f"{rel}/{t.run_id}", "root": rel, "run_id": t.run_id, "sid": job.sid, "qid": job.qid,
            "attempt": job.attempt, "kind": job.kind, "source": job.source, "error": res.error, "limit": res.limit,
            "fallback": res.fallback, "infra": t.infra, "breach": list(t.breach), "invalid": list(t.invalid),
            "seconds": res.seconds, "returncode": res.returncode, "usage": dict(res.usage), "model": res.model}


def _fail(state: Mapping[str, Any], sid: str, why: str) -> dict[str, Any]:
    """The attempt's failure: a Kay revision becomes a Kay drop (§3.7), anything else ends the attempt."""
    att = S.current(S.slot(state, sid))
    if att.get("kay_revision") and att["kay_revision"]["status"] == "pending":
        new = S.update_attempt(state, sid, S.ENDED, why, kay_revision={**att["kay_revision"], "status": "failed",
                                                                       "why": why})
        return S.close(new, sid, S.KAY_DROPPED, f"Kay 修改後未通過，當 Kay 刪除（§3.7）：{why}")
    return S.end_attempt(state, sid, why)


def dispute(state: Mapping[str, Any], sid: str, d: Mapping[str, Any]) -> dict[str, Any]:
    att = S.current(S.slot(state, sid))
    if att.get("kay_revision") and att["kay_revision"]["status"] == "pending":
        return _fail(state, sid, f"Kay 修改後成為爭議（{d['kind']}）")
    if att["post_kay"]:
        new = S.update_attempt(state, sid, S.ENDED, f"Kay 頁之後的爭議（{d['kind']}）", late_dispute=dict(d))
        if d["kind"] == "program_differs":
            return S.close(new, sid, S.OTHER_QUANTITY, "Kay 頁之後的 §3.6 第三種情況：問了別的量，刪題")
        return S.close(new, sid, S.FAILED, f"Kay 頁之後的爭議（{d['kind']}）：不再送 Kay，這次嘗試結束",
                       "late_dispute")
    return S.to_dispute(state, sid, d)


def _dispute_doc(kind: str, source: str | None, reason: str, att: Mapping[str, Any], gold: int,
                 candidate: Mapping[str, Any] | None, audit: Mapping[str, Any] | None,
                 mech: Sequence[Mapping[str, Any]] = (), **extra: Any) -> dict[str, Any]:
    """The dispute record: ``candidate`` is the draft Kay keeps or drops (its mech errors in ``mech``)."""
    values = {"writer": writer_value(candidate), "auditor": (audit or {}).get("value"), "gold": gold}
    return {"kind": kind, "source": source, "reason": reason, "candidate": candidate, "item": att["item"],
            "audit": audit, "mech": list(mech), "gold_trace": att.get("gold_trace"), "values": values, **extra}


def after_mech(state: Mapping[str, Any], ctx: Ctx, sid: str, item: Mapping[str, Any],
               source: str | None = None) -> dict[str, Any]:
    """mech_g.check_draft on a new item (source None) or a revision (its fix source): audit, the mech fix round, an
    audit-vs-mech conflict dispute, or the end of the attempt."""
    spec = ctx.spec(sid)
    found = M.check_draft(item, spec, ctx.names)
    att = S.current(S.slot(state, sid))
    kept = {err_key(v) for v in att["kept_mech"]}
    mech = [v.as_dict() for v in found]
    rules = sorted({v.rule for v in M.errors_of(found) if err_key(v.as_dict()) not in kept})
    if not rules:
        return S.update_attempt(state, sid, S.AUDIT, "機械檢查通過", item=M.canonical_item(item, spec), mech=mech,
                                fix_request=None)
    if source == "kay":
        return _fail(S.update_attempt(state, sid, item=dict(item), mech=mech), sid, "Kay 修改後機械檢查未過")
    broke = rules if source == "audit" else (att["audit_broke"] or []) if source == "mech" else []
    new = S.update_attempt(state, sid, item=dict(item), mech=mech, audit_broke=broke or None)
    if att["fixes"]["mech"] < GC.MAX_FIX_ROUNDS:
        req = {"source": "mech", "issues": issues_json(M.fix_issues(found))}
        return S.update_attempt(new, sid, S.MECH_FIX, "機械檢查未過，退回修一次", fix_request=req,
                                fixes={**att["fixes"], "mech": att["fixes"]["mech"] + 1})
    if broke and set(rules) <= set(broke) and att.get("audited"):
        audit = att["audits"][-1] if att["audits"] else None
        errs = [m for m in mech if m.get("level", "error") == "error"]
        return dispute(new, sid, _dispute_doc("audit_mech_conflict", "audit",
                                              f"依稽核意見修改後，機械檢查不過（{', '.join(rules)}）",
                                              S.current(S.slot(new, sid)), ctx.row(sid)["gold"], dict(item), audit,
                                              errs, audited=att["audited"], rules=rules))
    return S.end_attempt(new, sid, f"機械檢查修題後仍未過（{', '.join(rules)}）")


def commit_draft(state: Mapping[str, Any], ctx: Ctx, job: Job, out: Outcome) -> dict[str, Any]:
    o = out.output
    if M.check_gen_output(o) or o.get("status") != "drafted":
        return S.end_attempt(state, job.sid, f"出題者未出題（{o.get('status')}）：{str(o.get('reason', ''))[:300]}")
    return after_mech(state, ctx, job.sid, {k: o["item"].get(k) for k in P.ITEM_KEYS})


def commit_fix(state: Mapping[str, Any], ctx: Ctx, job: Job, out: Outcome) -> dict[str, Any]:
    o, sid, src = out.output, job.sid, job.source
    att = S.current(S.slot(state, sid))
    st, reason = o.get("status"), str(o.get("reason") or "").strip()
    state = S.update_attempt(state, sid, append={"fix_log": {"run": out.tries[-1].run_id, "source": src, "status": st,
                                                             "reason": reason}})
    if st == "revised" and isinstance(o.get("item"), Mapping):
        return after_mech(state, ctx, sid, {k: o["item"].get(k) for k in P.ITEM_KEYS}, src)
    if src == "kay":
        return _fail(state, sid, f"Kay 修改未完成（{st}）：{reason[:300]}")
    if st == "no_change" and reason:
        gold, audit = ctx.row(sid)["gold"], (att["audits"][-1] if att["audits"] else None)
        last = att["decisions"][-1] if att["decisions"] else {}
        kind = "program_differs" if src == "audit" and last.get("case") == "program_differs" else "no_change"
        return dispute(state, sid, _dispute_doc(kind, src, reason, att, gold, att["item"],
                                                audit if src == "audit" else None, att["mech"] if src == "mech" else ()))
    why = "修題者回 no_change 但未附理由" if st == "no_change" else f"修題者放棄（{st}）：{reason[:300]}"
    return S.end_attempt(state, sid, why)


def commit_audit(state: Mapping[str, Any], ctx: Ctx, job: Job, out: Outcome) -> dict[str, Any]:
    o, sid = out.output, job.sid
    att = S.current(S.slot(state, sid))
    findings = list(o["findings"])
    audit = {"run": out.tries[-1].run_id, **{k: o[k] for k in P.AUDIT_KEYS}, "findings": findings,
             "severity": M.severity_of(findings)}
    kay_rev = bool(att.get("kay_revision") and att["kay_revision"]["status"] == "pending")
    spent = kay_rev or att["fixes"]["audit"] >= GC.MAX_FIX_ROUNDS
    d = M.after_audit(audit, writer_value(att["item"]), ctx.row(sid)["gold"], spent)
    state = S.update_attempt(state, sid, audited=att["item"], audit_broke=None,
                             append={"audits": audit, "decisions": decision_json(d)})
    if d.gold_trace:
        trace = ctx.trace(sid, att["item"], audit)
        state = S.update_attempt(state, sid, gold_trace=trace)
        if not trace["agrees"] and sid not in state["k_gold_cpu"]:
            state = {**state, "k_gold_cpu": [*state["k_gold_cpu"], sid]}
    if d.action == "pass":
        fields = {"kay_revision": {**att["kay_revision"], "status": "passed"}} if kay_rev else {}
        return S.update_attempt(state, sid, S.STEP_PASSED, f"稽核 {d.severity}，三方值一致", **fields)
    if d.action == "fix":
        req = {"source": "audit", "issues": issues_json(d.issues)}
        return S.update_attempt(state, sid, S.AUDIT_FIX, f"稽核 {d.severity}／{d.case}：修一次", fix_request=req,
                                fixes={**att["fixes"], "audit": att["fixes"]["audit"] + 1})
    if d.action == "dispute":
        cur = S.current(S.slot(state, sid))
        return dispute(state, sid, _dispute_doc("program_differs", None, "出題者與稽核者的值一致，與程式 gold 不同（§3.6）",
                                                cur, ctx.row(sid)["gold"], att["item"], audit))
    return _fail(state, sid, f"稽核 {d.severity}／{d.case}：這次嘗試的稽核輪已用完")


def commit(state: Mapping[str, Any], ctx: Ctx, job: Job, out: Outcome) -> dict[str, Any]:
    """One job's outcome into the state (pure)."""
    rec = {**job.record(), "runs": [t.run_id for t in out.tries], "stopped": out.stopped,
           "breach": bool(out.breach), "limit": out.limit, "infra_exhausted": out.infra_exhausted}
    if not out.tries:
        return S.end_job(state, job.sid, rec)
    if job.new_attempt:
        state = S.open_attempt(state, job.sid, job.root)
    state = S.end_job(S.record_runs(state, job.sid, [run_info(ctx, job, t) for t in out.tries]), job.sid, rec)
    if out.stopped:
        return state
    if out.breach:
        rules = sorted({v["rule"] for v in out.breach})
        return _fail(state, job.sid, f"{job.label} transcript 盲化違規 {rules}：刪稿，這次嘗試計入（§3.1）")
    if out.limit:
        return _fail(state, job.sid, f"{job.label} 觸及代理上限（{out.limit}）：不重跑，這次嘗試計入")
    if out.infra_exhausted:
        if job.kind == "draft":
            return S.end_attempt(state, job.sid, f"出題 job 基礎設施失敗 {len(out.tries)} 次：不算嘗試", counted=False)
        return state
    return {"draft": commit_draft, "fix": commit_fix, "audit": commit_audit}[job.kind](state, ctx, job, out)


# ---------------------------------------------------------------- the wave loop
def on_cap(state: Mapping[str, Any], ctx: Ctx, refused: Sequence[Job], sids: Sequence[str], mode: str,
           spent: float) -> dict[str, Any]:
    """Jobs whose cap alone does not fit (§3.9, §8.1-8)."""
    if mode == "pilot":
        raise BudgetRefused(f"已花 {spent:.3f} + job 上限 > {L.SPEND_LIMIT_USD:g} USD：pilot 的 job 不啟動")
    if mode == "main":
        state = S.stop_drafting(state, sids, spent, f"{refused[0].qid} {refused[0].label} 放不下")
    for j in refused:
        rec = S.slot(state, j.sid)
        if rec["status"] in S.DONE:
            continue
        att = S.current(rec)
        if att and att.get("kay_revision") and att["kay_revision"]["status"] == "pending":
            state = S.update_attempt(state, j.sid, kay_revision={**att["kay_revision"], "status": "cap_stopped"})
        state = S.close(state, j.sid, S.CAP_STOPPED, f"硬上限：{j.label} job 放不下（§8.1-8）")
    return state


def _stop(state: Mapping[str, Any], ctx: Ctx, kind: str, jobs: Sequence[tuple[Job, Outcome]],
          note: str) -> dict[str, Any]:
    recs = [{**j.record(), "runs": [t.run_id for t in o.tries]} for j, o in jobs]
    return S.infra_stop(state, kind, recs, note, F1.lines_sha256(F1.log_lines(ctx.prereg)))


def drive(ctx: Ctx, state: Mapping[str, Any], sids: Sequence[str], mode: str,
          save: Callable[[Mapping[str, Any]], Any],
          stop: Callable[[Mapping[str, Any]], bool] | None = None) -> dict[str, Any]:
    """Waves until no job is left for `sids` (mode pilot | main | kay; kay drafts nothing) or ``stop(state)``."""
    ledger, state, unavailable = L.Ledger(ctx.paths.out_root), dict(state), 0
    while True:
        if state.get("k_gold_cpu"):
            raise KGold(f"K-gold: CPU 追查顯示程式 gold 錯（{sorted(state['k_gold_cpu'])}）")
        if S.open_stop(state):
            raise InfraStop(f"基礎設施停（{S.open_stop(state)['kind']}）未經記錄的修正清除")
        if stop is not None and stop(state):
            return state
        drafting = mode != "kay" and not state.get("drafting_stopped")
        jobs = plan_jobs(state, ctx, sids, mode, drafting)
        if not jobs:
            return state
        spent = ledger.spent()
        wave, refused = admit(jobs, spent, ctx.parallel)
        if refused:
            state = on_cap(state, ctx, refused, sids, mode, spent)
            save(state)
            continue
        for j in wave:
            state = S.begin_job(state, j.sid, j.record())
        save(state)
        outcomes = run_wave(ctx, wave)
        for j, o in zip(wave, outcomes):
            state = commit(state, ctx, j, o)
            save(state)
        exhausted = [(j, o) for j, o in zip(wave, outcomes) if o.infra_exhausted]
        changed = [(j, o) for j, o in zip(wave, outcomes) if o.cli_changed]
        why = [f"{j.qid} {j.label}: 基礎設施失敗 {len(o.tries)} 次" for j, o in exhausted]
        if changed or exhausted:
            note = changed[0][1].cli_changed if changed else "; ".join(why)
            state = _stop(state, ctx, "cli_changed" if changed else "infra", changed + exhausted, note)
            save(state)
        if changed:
            raise CliChanged(f"基礎設施停（§3.1，重做 probe，再 run_ho_g.py repin）：{changed[0][1].cli_changed}")
        bad = [o.failed for o in outcomes if o.failed]
        if exhausted:
            raise InfraStop("; ".join(why + bad) + "（§2.3：記錄修正後以 --infra-fix 續跑）")
        if bad:
            raise HoError("; ".join(bad))
        unavailable = unavailable + 1 if all(o.unavailable for o in outcomes) else 0
        if unavailable >= UNAVAILABLE_WAVES:
            raise CliUnavailable(f"`claude --version` 連續 {unavailable} 輪沒有回應：稍後再跑")
