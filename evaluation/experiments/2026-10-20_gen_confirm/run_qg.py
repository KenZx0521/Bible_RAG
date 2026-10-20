"""Executor and scorer of the blind P1/P2 question sets (prereg §5.4, §5.6 G1, §8.1-3..5; qset.md §3-§7).

Layout under the store qset root (OUT_ROOT/qset, the ledger's qset base; QSET_CAP_USD in all):
  <set>/spec.json          spec_qg's spec          <set>/drafts/<job>.json   one per writer job (refill: <job>-r)
  <set>/transcripts/ prompts/ reserve/ clibin/ hookbin/   claude_g's run files (ledger_g counts them)
  <set>/run.lock           held (fcntl.flock) by gen, refill and score: one command per set at a time
  <set>/items.json         the assembled items (mech_qg)   p1/scores.jsonl, p1/score_rows.json   every P1 score
  p2/gen_done.json, p2/refill_done.json, p2/score.json      P2's once-only records
  g1.json, p2_near_miss.json                                  P2's results (the HO runner and run_g read them)
Launches (``reserved_launch``: claude_g.run_reserved's reserve → claude_g.launch → release when nothing ran, with
P1's limit; kind "qset", root <set>, tools mode "none", the job's writer model from the pin, user scope "prompt":
the user prompt is template plus tool values; tool_values = the rendered values). P1 keeps P2_RESERVE_USD of the
qset cap free (a P1 launch is refused once qset spent + its cap > P1_LIMIT_USD; the check and the reservation are
one step under a process lock, the ledger counting runs in flight at their cap): P2 can always finish (48 jobs at
qset's largest measured 0.026 USD and one cap in flight fit in 1.5). Every prompt of a command is rendered (and
blind-checked, prompt_qg) before the first launch. A job's earlier runs (its transcripts) are read first: one that
finished (not an infrastructure failure) but has no draft (the runner died after the run) is the job's run, its
draft rebuilt from the transcript and never launched again (two such runs refuse: the job ran twice); otherwise
infrastructure failures (RunResult.infra_failure) are rerun, at most MAX_INFRA_RETRIES times over all invocations
(not an attempt); BudgetRefused, CliUnavailable or a refused launch leaves the job without a draft, so the next gen
/ refill runs it (CliUnavailable: retry later, no new probe); CliChanged stops the runner (§3.1 infrastructure stop:
re-probe). A blinding error (transcript_g.blinding on the output run) voids the job's output; mech_qg re-checks it
from the saved transcript, failing closed (``blind_of``: a missing transcript, or an ok draft naming no run, voids).
P2 (§5.4: after F1a, once, totals only): gen, refill and score refuse unless store f1a_pins.json exists, its
"files" equal the F1a group now (f1_g.f1a_problems) and its "p2_files" the P2 path now (f1a_g.p2_problems: the rest
of the P2 validity check, §5.6, and this scorer, spec and prompt); every P2 record carries the P2-path sha256.
gen_done / refill_done are written when every job (refill job) has a draft and then refuse a second run; score needs
refill_done and is done once score.json, written last, exists (g1.json and p2_near_miss.json first, each rewritten
only as itself: a rerun after a crash between them completes them, never changes one). Nothing of P2 is printed or
written but totals: no question, name, sid, abstention reason or breakdown (items.json keeps the items for an audit
after F2). P1 is scored any number of times (the rule may change until F1a); each score appends one line with the
F1a group's and the P2 path's sha256 to p1/scores.jsonl.

Scoring (§5.4), on gencard (``parse(gen_layer, gen_names)``) over the valid items: R_trig (Trigger.fired), R_seed
(the seeds are exactly the slot's gold pair), R_card (a card and the gold pair; Card.covers(gold) is asserted, K0-lines),
R_wrong (a card on another pair), n_v = the valid positives; P1 also abstention reasons and steps, per writer,
persona and stratum, near-miss triggers per family; GT v1 / v2 triggers (must be 0). A near miss still invalid after
its refill counts as fired in p2_near_miss.json (the conservative side of §9's release clause; the valid-fired and
invalid counts are printed and kept in score.json). P2 writes g1.json (contract gen_confirm.g1.v1: g1 =
power_g.g1(R_card, R_wrong, n_v, n = 53), pass = g1 ≥ 0.70 and no GT trigger; when not, a §9 stop sentence that
names what failed: §5.6's G1 sentence when only g1 < 0.70, 「GT 觸發 m 次」 when only the GT nail fails, both values
when both do) and p2_near_miss.json {"fired": k, "n": 20}, and prints every sha256 for the log.

    run_qg.py gen --set p1|p2      run_qg.py refill --set p1|p2      run_qg.py score --set p1|p2
    run_qg.py show --set p1        run_qg.py status
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import banned_g as B
import claude_g as CL
import f1_g as F1
import f1a_g as FA
import g_common as GC
import gencard
import hog_common as H
import k0_g as K0
import ledger_g as LG
import mech_qg as MQ
import prompt_qg as Q
import prompts_g as P
import spec_qg as S
import transcript_g as TR

KIND = "qset"
DRAFTS = GC.QSET_DRAFTS
GEN_DONE, REFILL_DONE, SCORE_DONE = GC.QSET_GEN_DONE, GC.QSET_REFILL_DONE, GC.QSET_SCORE_DONE
G1_FILE, NEAR_FILE, ITEMS_FILE = GC.G1_FILE, GC.P2_NEAR_FILE, GC.QSET_ITEMS
P1_SCORES, P1_ROWS, LOCK_FILE = GC.P1_SCORES, GC.P1_ROWS, GC.QSET_LOCK
G1_SCHEMA = "gen_confirm.g1.v1"
G1_N = GC.G1_N                                       # prereg §5.6: 58 slots × A's 32/35 (power_g.N_PLAN)
GT_FILES = GC.GT_FILES
P2_RESERVE_USD = GC.P2_RESERVE_USD                   # of QSET_CAP_USD, kept free for P2 (module docstring)
P1_LIMIT_USD = GC.P1_LIMIT_USD
Launcher = Callable[..., CL.RunResult]
_RESERVE_LOCK = threading.Lock()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class Ctx:
    set: str
    spec: Mapping[str, Any]
    names: P.Names
    L: Any                                           # gencard.Layer
    out_root: Path = GC.OUT_ROOT
    pin: CL.CliPin | None = None
    pf: P.PromptFile | None = None
    launch_kw: Mapping[str, Any] = field(default_factory=dict)       # cwd, home, timeout_s (tests)
    f1a: Path = GC.F1A_LOG
    f1a_group: Mapping[str, Path] | None = None                       # None: f1_g.f1a_paths()
    gt_files: Sequence[Path] = GT_FILES
    g1_fn: Callable[[int, int, int], float] | None = None             # None: power_g.g1 on the store pool
    p2_group: Mapping[str, Path] | None = None                        # None: f1a_g.p2_paths()

    @property
    def root(self) -> Path:
        return S.set_root(self.set, self.out_root)

    @property
    def qset_root(self) -> Path:
        return Path(self.out_root) / S.QSET_DIR


def context(set_name: str, out_root: Path = GC.OUT_ROOT, need_pin: bool = True, check_spec: bool = True) -> Ctx:
    """The store context: the stored spec (equal to a rebuild when ``check_spec``), gencard's layer, the names."""
    spec = S.load_spec(set_name, out_root)
    if check_spec and S.spec_sha(S.build_from_store(set_name, out_root)) != S.spec_sha(spec):
        raise H.HoError(f"{set_name}/spec.json is not what spec_qg builds from the store now")
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise H.HoError(f"{GC.GEN_LAYER}: sha256 is not {GC.GEN_LAYER_SHA256_PREFIX} (prereg §2)")
    names_doc = GC.read_json(GC.GEN_NAMES)
    return Ctx(set_name, spec, P.Names.from_doc(names_doc), gencard.parse(GC.read_json(GC.GEN_LAYER), names_doc),
               Path(out_root), CL.load_pin() if need_pin else None, Q.load())


# ---------------------------------------------------------------- files
def draft_path(ctx: Ctx, job_id: str) -> Path:
    return ctx.root / DRAFTS / f"{job_id}.json"


def read_draft(ctx: Ctx, job_id: str) -> dict | None:
    p = draft_path(ctx, job_id)
    return GC.read_json(p) if p.is_file() else None


def blind_of(ctx: Ctx) -> Callable[[Mapping[str, Any]], list]:
    """The draft's output run re-checked (qset.md §3), failing closed: on an ok draft a t_result error (its
    transcript missing or no longer a success) voids it too, and so does an ok draft that names no run."""
    def check(d: Mapping[str, Any]) -> list:
        if not d.get("output_run"):
            return [H.Violation("t_result", "an ok draft names no output run")] if d.get("ok") else []
        vs = TR.check_run(ctx.root, d["output_run"])
        return TR.blinding(vs) + ([v for v in vs if v.rule == "t_result"] if d.get("ok") else [])
    return check


def items(ctx: Ctx) -> list[dict]:
    return MQ.assemble(ctx.spec, lambda j: read_draft(ctx, j), ctx.names, blind_of(ctx))


def append_jsonl(path: Path, row: Mapping[str, Any]) -> Path:
    p = GC.writable(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


def p2_shas(ctx: Ctx) -> dict[str, str | None]:
    return F1.sha_map(dict(FA.p2_paths() if ctx.p2_group is None else ctx.p2_group))


def f1a_problems(ctx: Ctx) -> list[str]:
    """prereg §3.8 F1a: the group and the P2 path now against store f1a_pins.json (paths only)."""
    if not Path(ctx.f1a).is_file():
        return [f"{Path(ctx.f1a).name} missing: run f1a_g.py first (prereg §3.8 F1a)"]
    group, doc = F1.f1a_paths() if ctx.f1a_group is None else ctx.f1a_group, GC.read_json(ctx.f1a)
    return F1.f1a_problems(F1.sha_map(dict(group)), doc) + FA.p2_problems(p2_shas(ctx), doc)


def require_p2(ctx: Ctx, step: str, needs: Sequence[str] = (), refuses: Sequence[str] = ()) -> None:
    """P2's gates: the F1a pins hold; the needed records exist; the once-only ones do not."""
    if ctx.set != "p2":
        return
    bad = f1a_problems(ctx)
    bad += [f"P2 {step} needs {n} (earlier step not complete)" for n in needs if not (ctx.root / n).is_file()]
    bad += [f"P2 {step} runs once: {n} exists" for n in refuses if (ctx.root / n).is_file()]
    if bad:
        raise H.HoError(f"P2 {step} refused: {bad}")


@contextlib.contextmanager
def run_lock(ctx: Ctx):
    """<set>/run.lock, exclusive and not waited for: a second gen / refill / score of the set is refused."""
    path = GC.writable(ctx.root / LOCK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o664)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise H.HoError(f"{ctx.set}: another run_qg command holds {ctx.set}/{LOCK_FILE}") from None
        yield
    finally:
        os.close(fd)


# ---------------------------------------------------------------- one job
def prior_runs(root: Path, job_id: str) -> list[str]:
    pat = re.compile(rf"{re.escape(job_id)}_(\d+)")
    return sorted((p.stem for p in (Path(root) / "transcripts").glob(f"{job_id}_*.jsonl") if pat.fullmatch(p.stem)),
                  key=lambda s: int(s.rsplit("_", 1)[1]))


def next_run_id(root: Path, job_id: str) -> str:
    n = 1
    while LG.has_run(root, f"{job_id}_{n}"):
        n += 1
    return f"{job_id}_{n}"


def _run_rec(res: CL.RunResult) -> dict[str, Any]:
    return {"run_id": res.run_id, "error": res.error, "limit": res.limit, "fallback": res.fallback,
            "infra": res.infra_failure, "seconds": res.seconds, "usage": dict(res.usage), "model": res.model}


def saved_result(root: Path, run_id: str) -> CL.RunResult | None:
    """The RunResult of a saved run, classified as claude_g.launch classifies it (None: no prompts record)."""
    transcript, prompts = TR.run_paths(root, run_id)
    rec = H.as_mapping(GC.read_json(prompts)) if prompts.is_file() else {}
    model, cap = rec.get("model"), rec.get("budget_usd")
    if not transcript.is_file() or not isinstance(model, str) or not isinstance(cap, (int, float)):
        return None
    events = CL.read_events(transcript)
    result = CL.result_event(events)
    error, limit, fallback = CL.outcome(-1, result, events, model, float(cap))
    return CL.RunResult(run_id, transcript, -1, 0.0, result, error, CL.usage_of(result, events), limit, fallback,
                        model, str(rec.get("tools_mode") or ""))


def reserved_launch(kind: str, root: Path, run_id: str, system: str, user: str, schema: Mapping[str, Any],
                    budget_usd: float, model: str, pin: CL.CliPin, *, user_scope: str, out_root: Path | str = GC.OUT_ROOT,
                    qset_limit_usd: float | None = None, **kw: Any) -> CL.RunResult:
    """claude_g.run_reserved with P1's limit: under one process lock, refuse when the qset spend + this cap would
    pass ``qset_limit_usd``, and reserve; then launch, releasing the reservation when nothing ran."""
    led = LG.Ledger(out_root)
    with _RESERVE_LOCK:
        if qset_limit_usd is not None:
            spent = led.snapshot()["by_kind"]["qset"]
            if spent + budget_usd > qset_limit_usd + LG.EPS:
                raise H.BudgetRefused(f"qset 已花 {spent:.3f} + 上限 {budget_usd:g} > P1 上限 {qset_limit_usd:g} USD"
                                      f"（保留 {P2_RESERVE_USD:g} 給 P2），不啟動")
        led.reserve(kind, root, run_id, budget_usd)
    try:
        return CL.launch(root, run_id, system, user, schema, budget_usd, model, pin, user_scope=user_scope,
                         out_root=out_root, **kw)
    except BaseException:
        led.release(root, run_id)
        raise


def run_job(ctx: Ctx, job: Mapping[str, Any], r: Q.QRendered, launcher: Launcher = reserved_launch,
            stop: threading.Event | None = None) -> dict[str, Any]:
    """The job's finished run without a draft if any (recovered, never relaunched), else runs with infrastructure
    reruns; {"stopped": why} when nothing ran this time (no draft is written)."""
    model, runs, res = ctx.pin.model(job["writer"]), [], None
    before = prior_runs(ctx.root, job["job_id"])
    done = [x for x in (saved_result(ctx.root, rid) for rid in before) if x is not None and not x.infra_failure]
    if len(done) > 1:
        raise H.HoError(f"{job['job_id']}: {len(done)} finished runs without a draft (a job runs once)")
    limit_kw = {"qset_limit_usd": P1_LIMIT_USD} if ctx.set == "p1" else {}
    res = done[0] if done else None
    for _ in range(0 if done else max(1 + GC.MAX_INFRA_RETRIES - len(before), 0)):
        if stop is not None and stop.is_set():
            return {"stopped": "the runner stopped (CLI changed)"}
        try:
            res = launcher(KIND, ctx.root, next_run_id(ctx.root, job["job_id"]), r.system, r.user, r.schema,
                           GC.QSET_JOB_CAP_USD["gen"], model, ctx.pin, user_scope="prompt", out_root=ctx.out_root,
                           tools_mode="none", tool_values=dict(r.values),
                           extra_record={"qset_job": job["job_id"], "qset_set": ctx.set}, **limit_kw, **ctx.launch_kw)
        except H.CliChanged:
            if stop is not None:
                stop.set()
            raise
        except H.HoError as err:                     # BudgetRefused, CliUnavailable, a refused launch: nothing ran
            return {"stopped": f"{type(err).__name__}: {err}"}
        runs.append(_run_rec(res))
        if not res.infra_failure:
            break
    final = res if res is not None and not res.infra_failure else None
    void = TR.blinding(TR.check_run(ctx.root, final.run_id)) if final else []
    ok = final is not None and final.error is None and isinstance(final.output, Mapping) and not void
    return {"runs": runs, "prior_runs": before, "recovered_from": done[0].run_id if done else None,
            "output_run": final.run_id if final else None, "ok": ok, "output": dict(final.output) if ok else None,
            "limit": final.limit if final else None, "blinding": [v.as_dict() for v in void]}


def write_draft(ctx: Ctx, job: Mapping[str, Any], rec: Mapping[str, Any], r: Q.QRendered) -> Path:
    return GC.write_json(draft_path(ctx, job["job_id"]), {
        "job_id": job["job_id"], "set": ctx.set, "writer": job["writer"], "persona": job["persona"],
        "slots": [s["slot"] for s in job["slots"]], "refill_of": job.get("refill_of"), "prompt_sha256": r.prompt_sha256,
        "t": now(), **rec})


def run_many(ctx: Ctx, jobs: Sequence[Mapping[str, Any]], launcher: Launcher = reserved_launch) -> dict[str, Any]:
    """Render every job first (a banned term stops all at 0 USD), then at most PARALLEL at once in order."""
    rendered = [(j, Q.render_job(j, ctx.names, ctx.pf)) for j in jobs]
    stop, changed = threading.Event(), []

    def one(pair) -> tuple[str, str, str | None]:
        job, r = pair
        if stop.is_set():
            return "stopped", job["job_id"], "the runner stopped (CLI changed)"
        rec = run_job(ctx, job, r, launcher, stop)
        if "stopped" in rec:
            return "stopped", job["job_id"], rec["stopped"]
        write_draft(ctx, job, rec, r)
        return ("ok" if rec["ok"] else "failed"), job["job_id"], None
    done = []
    if rendered:
        with ThreadPoolExecutor(max_workers=min(GC.PARALLEL, len(rendered))) as pool:
            for f in [pool.submit(one, p) for p in rendered]:
                try:
                    done.append(f.result())
                except H.CliChanged as err:
                    changed.append(err)
        LG.Ledger(ctx.out_root).write_snapshot()
    if changed:
        raise H.CliChanged(f"{changed[0]} — infrastructure stop (prereg §3.1): probe again")
    out = {k: sum(d[0] == k for d in done) for k in ("ok", "failed", "stopped")}
    return {**out, "stopped_why": dict(Counter(d[2].split(":")[0] for d in done if d[0] == "stopped"))}


# ---------------------------------------------------------------- gen and refill
def _p2_record(ctx: Ctx, **extra: Any) -> dict[str, Any]:
    return {"t": now(), **extra, "spec_sha256": S.spec_sha(ctx.spec), "f1a_pins_sha256": GC.sha256_file(ctx.f1a),
            "p2_files": p2_shas(ctx)}


def cmd_gen(ctx: Ctx, launcher: Launcher = reserved_launch) -> dict[str, Any]:
    with run_lock(ctx):
        require_p2(ctx, "gen", refuses=(GEN_DONE,))
        by_id = {j["job_id"]: j for j in ctx.spec["jobs"]}
        todo = [by_id[j] for j in ctx.spec["order"] if read_draft(ctx, j) is None]
        out = run_many(ctx, todo, launcher)
        left = sum(read_draft(ctx, j) is None for j in ctx.spec["order"])
        if ctx.set == "p2" and not left:
            GC.write_json(ctx.root / GEN_DONE, _p2_record(ctx, jobs=len(ctx.spec["order"])))
    return {"set": ctx.set, "started": len(todo), **out, "jobs_left": left}


def cmd_refill(ctx: Ctx, launcher: Launcher = reserved_launch) -> dict[str, Any]:
    """The one refill round (prereg §5.6): each job's invalid slots, same persona and writer, once."""
    with run_lock(ctx):
        require_p2(ctx, "refill", needs=(GEN_DONE,), refuses=(REFILL_DONE,))
        if missing := [j for j in ctx.spec["order"] if read_draft(ctx, j) is None]:
            raise H.HoError(f"{len(missing)} job(s) have no draft yet: gen first")
        jobs = MQ.refill_jobs(ctx.spec, lambda j: read_draft(ctx, j), ctx.names, blind_of(ctx))
        todo = [r for r in jobs if read_draft(ctx, r["job_id"]) is None]
        out = run_many(ctx, todo, launcher)
        left = sum(read_draft(ctx, r["job_id"]) is None for r in jobs)
        if ctx.set == "p2" and not left:
            GC.write_json(ctx.root / REFILL_DONE, _p2_record(ctx, refill_jobs=len(jobs)))
    return {"set": ctx.set, "refill_jobs": len(jobs), "started": len(todo), **out, "jobs_left": left}


# ---------------------------------------------------------------- scoring
def score_row(L: Any, it: Mapping[str, Any]) -> dict[str, Any]:
    """One item under gencard (no question text in the row)."""
    row = {k: it.get(k) for k in ("item_id", "kind", "stratum", "family", "source", "writer", "persona", "valid",
                                  "refilled")}
    if not it["valid"]:
        return {**row, "violations": sorted({v["rule"] for v in it["violations"]})}
    t = gencard.trigger(it["question"], L)
    row.update(fired=t.fired, step=t.step, reason=t.reason, shape=t.shape, seeds=list(t.seeds) if t.seeds else None)
    if it["kind"] != "pos":
        return row
    c = gencard.card(it["question"], L)
    if (c is None) == bool(t.fired):
        raise H.HoError("gencard's card and trigger disagree on an item (no fallback: a card iff it fires)")
    gold = t.fired and tuple(t.seeds) == (it["x"], it["y"])
    if c is not None and gold and not c.covers(it["gold"]):
        raise H.HoError("a card on the gold pair does not cover the gold: K0-lines is broken (K-gold, prereg §3.6)")
    return {**row, "seed_ok": bool(gold), "card": c is not None and bool(gold), "wrong": c is not None and not gold}


def _block(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {"n": len(rows), "R_trig": sum(bool(r["fired"]) for r in rows), "R_seed": sum(r["seed_ok"] for r in rows),
            "R_card": sum(r["card"] for r in rows), "R_wrong": sum(r["wrong"] for r in rows)}


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts and rates only (no id, no text): what P2 may print."""
    pos = [r for r in rows if r["kind"] == "pos" and r["valid"]]
    near = [r for r in rows if r["kind"] == "near"]
    b = _block(pos)
    n_v = b.pop("n")
    by = lambda key: {k: _block([r for r in pos if r[key] == k]) for k in sorted({r[key] for r in pos})}  # noqa: E731
    fam = {f: {"n": len(rs), "fired": sum(bool(r.get("fired")) for r in rs), "invalid": sum(not r["valid"] for r in rs)}
           for f, rs in ((f, [r for r in near if r["family"] == f]) for f, _ in S.NEAR_FAMILIES)}
    fired = sum(bool(r.get("fired")) for r in near if r["valid"])
    invalid = sum(not r["valid"] for r in near)
    return {"n_v": n_v, **b, "rates": {k: round(v / n_v, 4) if n_v else None for k, v in b.items()},
            "invalid_positives": sum(r["kind"] == "pos" and not r["valid"] for r in rows),
            "abstain": dict(sorted(Counter(r["reason"] for r in pos if not r["fired"]).items())),
            "abstain_step": dict(sorted(Counter(str(r["step"]) for r in pos if not r["fired"]).items())),
            "by_writer": by("writer"), "by_persona": by("persona"), "by_stratum": by("stratum"),
            "near": {"n": len(near), "valid": len(near) - invalid, "fired": fired, "invalid": invalid,
                     "fired_or_invalid": fired + invalid, "by_family": fam}}


def totals(agg: Mapping[str, Any]) -> dict[str, Any]:
    """What P2 records and prints (§5.4 只看總數): G1's counts, the invalid positives, the near-miss totals."""
    return {**{k: agg[k] for k in ("n_v", "R_trig", "R_seed", "R_card", "R_wrong", "invalid_positives")},
            "near": {k: agg["near"][k] for k in ("n", "valid", "fired", "invalid", "fired_or_invalid")}}


def tally_totals(tally: Mapping[str, Any]) -> dict[str, Any]:
    """mech_qg.tally without the per-rule counts."""
    return {k: {"slots": v["slots"], "valid": v["valid"], "refilled": v["refilled"], "invalid": v["slots"] - v["valid"]}
            for k, v in tally.items()}


def near_record(agg: Mapping[str, Any]) -> dict[str, int]:
    """store qset/p2_near_miss.json: a near miss still invalid after its refill counts as fired (module docstring)."""
    near = agg["near"]
    if near["n"] != S.N_NEAR:
        raise H.HoError(f"P2 has {near['n']} near misses, not {S.N_NEAR}")
    return {"fired": near["fired_or_invalid"], "n": near["n"]}


def write_same(path: Path, doc: Mapping[str, Any]) -> Path:
    """Write a once-only record, or keep it when it exists and equals ``doc`` but for "t" (a rerun after a crash);
    an existing record that differs refuses."""
    if Path(path).is_file():
        old = GC.read_json(path)
        if {k: v for k, v in old.items() if k != "t"} != {k: v for k, v in doc.items() if k != "t"}:
            raise H.HoError(f"{Path(path).name} exists and differs from this score: P2 is scored once")
        return Path(path)
    return GC.write_json(path, doc)


def gt_triggers(L: Any, files: Sequence[Path] = GT_FILES) -> dict[str, int]:
    """Questions of GT v1 / v2 the current gencard fires on (prereg §5.6: must be 0)."""
    return {Path(f).name: sum(bool(gencard.trigger(q["question"], L).fired) for q in GC.read_json(f)["questions"])
            for f in files}


def rule_shas(ctx: Ctx) -> dict[str, str | None]:
    return F1.sha_map(dict(F1.f1a_paths() if ctx.f1a_group is None else ctx.f1a_group))


def _items_and_rows(ctx: Ctx) -> tuple[list[dict], list[dict]]:
    its = items(ctx)
    return its, [score_row(ctx.L, it) for it in its]


def store_g1(r_card: int, r_wrong: int, n_v: int) -> float:
    import power_g as PG
    return float(PG.g1(PG.load_pool(), r_card, r_wrong, n_v, n=G1_N)["pow_H1_and_H2"])


def g1_sentence(r_card: int, r_wrong: int, n_v: int, low: bool, m: int) -> str | None:
    """G1's stop sentence: §5.6's when only g1 < 0.70, the GT trigger count when only the GT nail fails (m > 0), both
    when both fail; None when G1 passes."""
    import analyze_g as AG
    if low and not m:
        return AG.g1_stop_sentence(r_card, r_wrong, n_v)
    if m and not low:
        return AG.stop_sentence("G1", f"GT 觸發 {m} 次", "未出題")
    if m:
        return AG.stop_sentence("G1", f"R_card＝{r_card}/{n_v}，R_wrong＝{r_wrong}/{n_v}；GT 觸發 {m} 次", "未出題")
    return None


def g1_doc(r_card: int, r_wrong: int, n_v: int, m: int, f1a_sha: str, spec_sha: str,
           g1_fn: Callable[[int, int, int], float] | None = None) -> dict[str, Any]:
    """store qset/g1.json (contract gen_confirm.g1.v1); pass = g1 ≥ 0.70 (power_g.TARGET) and no GT trigger (m, the
    GT v1 / v2 questions gencard fires on, is 0)."""
    import power_g as PG
    if not isinstance(m, int) or isinstance(m, bool) or m < 0:
        raise ValueError(f"the GT trigger count must be a count, not {m!r}")
    value = float((g1_fn or store_g1)(r_card, r_wrong, n_v)) if n_v else 0.0
    passed = value >= PG.TARGET and m == 0
    return {"schema": G1_SCHEMA, "R_card": r_card, "R_wrong": r_wrong, "n_v": n_v, "g1": value, "pass": passed,
            "gt_zero_trigger": m == 0, "f1a_pins_sha256": f1a_sha, "p2_spec_sha256": spec_sha,
            "sentence": g1_sentence(r_card, r_wrong, n_v, value < PG.TARGET, m), "t": now()}


def cmd_score(ctx: Ctx) -> dict[str, Any]:
    with run_lock(ctx):
        require_p2(ctx, "score", needs=(REFILL_DONE,), refuses=(SCORE_DONE,))
        its, rows = _items_and_rows(ctx)
        agg, gt = aggregate(rows), gt_triggers(ctx.L, ctx.gt_files)
        shas = {"spec": S.spec_sha(ctx.spec), "rules": rule_shas(ctx), "p2_files": p2_shas(ctx)}
        GC.write_json(ctx.root / ITEMS_FILE, {"set": ctx.set, "spec_sha256": shas["spec"], "t": now(), "items": its})
        if ctx.set == "p1":
            append_jsonl(ctx.root / P1_SCORES, {"t": now(), "sha256": shas, "aggregate": agg, "gt": gt,
                                                "items": MQ.tally(its)})
            GC.write_json(ctx.root / P1_ROWS, {"t": now(), "sha256": shas, "rows": rows})
            return {"set": "p1", **agg, "gt": gt, "items": MQ.tally(its)}
        f1a_sha, near = GC.sha256_file(ctx.f1a), near_record(agg)
        g1 = g1_doc(agg["R_card"], agg["R_wrong"], agg["n_v"], sum(gt.values()), f1a_sha, shas["spec"], ctx.g1_fn)
        g1_path, near_path = write_same(ctx.qset_root / G1_FILE, g1), write_same(ctx.qset_root / NEAR_FILE, near)
        GC.write_json(ctx.root / SCORE_DONE, {"t": now(), "sha256": shas, "totals": totals(agg), "gt": gt,
                                              "items": tally_totals(MQ.tally(its)), "f1a_pins_sha256": f1a_sha})
    g1 = GC.read_json(g1_path)
    return {"set": "p2", "g1": {k: g1[k] for k in ("R_card", "R_wrong", "n_v", "g1", "pass", "gt_zero_trigger",
                                                    "sentence")},
            "near": near, "near_invalid": agg["near"]["invalid"], "near_valid_fired": agg["near"]["fired"], "gt": gt,
            "sha256": {G1_FILE: GC.sha256_file(g1_path), NEAR_FILE: GC.sha256_file(near_path),
                       SCORE_DONE: GC.sha256_file(ctx.root / SCORE_DONE), "p2/spec.json": shas["spec"],
                       "f1a_pins.json": f1a_sha, "p2_files": shas["p2_files"]}}


# ---------------------------------------------------------------- show and status
def cmd_show(ctx: Ctx) -> list[dict[str, Any]]:
    """P1 only: every item with its question and gencard's step, reason and seeds (rule tuning on dev slots)."""
    if ctx.set != "p1":
        raise H.HoError("show prints P1 only (P2 is totals only, prereg §5.4)")
    out = []
    for it in items(ctx):
        row = score_row(ctx.L, it)
        seeds = [ctx.L.name[x] for x in row.get("seeds") or []]
        gold = [ctx.L.name[x] for x in (it["x"], it["y"])] if it["kind"] == "pos" else None
        out.append({**{k: row.get(k) for k in ("item_id", "kind", "stratum", "family", "writer", "persona", "valid",
                                                "fired", "step", "reason", "shape", "violations")},
                    "question": it["question"], "seeds": seeds or None, "gold_pair": gold})
    return out


def cmd_status(out_root: Path = GC.OUT_ROOT, ctxs: Mapping[str, Ctx] | None = None) -> dict[str, Any]:
    """Counts only: jobs, drafts, refill jobs, items by validity (P1 by rule, P2 totals), the qset spend."""
    led = LG.Ledger(out_root).spent_by_root()
    out: dict[str, Any] = {"qset_spent_usd": round(sum(v for k, v in led.items() if k.startswith(str(S.QSET_DIR))), 6),
                           "qset_cap_usd": GC.QSET_CAP_USD}
    for s in S.SETS:
        try:
            ctx = (ctxs or {}).get(s) or context(s, out_root, need_pin=False, check_spec=False)
        except (H.HoError, S.SpecError, OSError) as err:
            out[s] = {"spec": None, "why": str(err)[:120]}
            continue
        read = lambda j, c=ctx: read_draft(c, j)  # noqa: E731
        drafted = [read(j) for j in ctx.spec["order"]]
        refills = MQ.refill_jobs(ctx.spec, read, ctx.names, blind_of(ctx)) if all(drafted) else []
        tally = MQ.tally(items(ctx)) if any(drafted) else None
        out[s] = {"jobs": len(drafted), "drafted": sum(d is not None for d in drafted),
                  "ok": sum(bool(d and d.get("ok")) for d in drafted), "refill_jobs": len(refills),
                  "refills_drafted": sum(read(r["job_id"]) is not None for r in refills),
                  "items": tally_totals(tally) if tally and s == "p2" else tally,
                  "records": sorted(n for n in (GEN_DONE, REFILL_DONE, SCORE_DONE) if (ctx.root / n).is_file()),
                  "spent_usd": round(led.get(f"{S.QSET_DIR}/{s}", 0.0), 6)}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P1/P2 blind question sets (prereg §5.4; ≤ QSET_CAP_USD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gen", "refill", "score"):
        sub.add_parser(name).add_argument("--set", required=True, choices=S.SETS)
    sub.add_parser("show").add_argument("--set", required=True, choices=("p1",))
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(cmd_status(), ensure_ascii=False))
        return 0
    if a.cmd in ("gen", "refill") and (bad := K0.k0_problems()):
        raise H.HoError(f"K0 first (prereg §8.1-1: K0 before any USD): {bad[:3]}")
    ctx = context(a.set, need_pin=a.cmd in ("gen", "refill"), check_spec=a.cmd in ("gen", "refill") or a.set == "p2")
    if a.cmd == "show":
        for row in cmd_show(ctx):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    out = {"gen": cmd_gen, "refill": cmd_refill, "score": cmd_score}[a.cmd](ctx)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except H.CliChanged as err:
        print(json.dumps({"action": "stop", "error": f"CliChanged: {err}"}, ensure_ascii=False))
        sys.exit(3)
    except (H.HoError, S.SpecError, B.BlindingError, P.PromptError, OSError, ValueError) as err:
        print(json.dumps({"action": "stop", "error": f"{type(err).__name__}: {err}"}, ensure_ascii=False))
        sys.exit(2)
