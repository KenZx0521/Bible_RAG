"""Executor of the question set (qset.md §7–§10): probe, pin, gen, refill, label, mech, budget, status, show.

Layout under the store root R (reports/regnal_qset_20261019/):
  spec.json, cli_pin.json
  probe/ p1/ p2/       transcripts/<run>.jsonl, prompts/<run>.json (+ clibin/, bin/ of the launch)
  ledger/              reserve/<sub>/<run>.json (written before every launch), ledger.json (snapshot)
  <set>/drafts/        one file per writer job (<job_id>.json; the refill job <job_id>-r.json)
  <set>/labels/        one file per labeller batch
  <set>/items.json     every slot with its question, validity, flags and label (mech_q rules)

Ledger: a run counts its result event's total_cost_usd; a run without one counts the cap it was
reserved with, so a crashed run is never cheaper than its cap. Before every launch the budget lock is
taken and spent + this job's cap ≤ USD_CAP checked (probes also ≤ PROBE_TOTAL_USD, at most
PROBE_MAX_RUNS). Infrastructure failures (no result, timeout, CLI error, model fallback) are rerun
up to MAX_RETRIES; an agent limit (budget cap, structured-output retries) counts and is not rerun; a
blinding error voids the job's output (its slots go to the refill round).
P2 is locked: no command prints a p2 question, king or label; status and score give counts only.

    run_q.py probe --model opus|sonnet [--tools-mode none|bash_guard]
    run_q.py pin --verdict FILE [FILE …]
    run_q.py gen [--set p1|p2]        run_q.py refill [--set …]      run_q.py label [--set …]
    run_q.py mech [--set …]           run_q.py budget                 run_q.py status
    run_q.py show --job p1-jNN        (p1 only: the rendered writer prompt)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import claude_q as CL
import mech_q as M
import prompt_q as P
import spec_q as S
import transcript_q as TR
from q_common import (CLAUDE_VERSION, EFFORT, JOB_CAP_USD, LABEL_BATCH, LABELLER, MAX_RETRIES, MODEL_IDS, PARALLEL,
                      PROBE_MAX_RUNS, PROBE_TOTAL_USD, ROOT, SEED, SETS, USD_CAP, BudgetRefused, QError, counts,
                      now, read_json, write_json)

LEDGER_SUBS = ("probe", *SETS)
BUDGET_LOCK = threading.Lock()
MAX_FIRST_PROMPT_TOKENS = 6000


# ---------------------------------------------------------------- ledger

def _run_cost(root: Path, sub: str, run_id: str) -> tuple[float, str]:
    t = Path(root) / sub / "transcripts" / f"{run_id}.jsonl"
    if t.is_file():
        for line in reversed(t.read_text(encoding="utf-8").splitlines()):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "result" and isinstance(e.get("total_cost_usd"), (int, float)):
                return float(e["total_cost_usd"]), "result"
    r = Path(root) / "ledger" / "reserve" / sub / f"{run_id}.json"
    if r.is_file():
        return float(read_json(r)["budget_usd"]), "cap_assumed"
    return max(JOB_CAP_USD.values()), "cap_assumed"


def ledger(root: Path) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for sub in LEDGER_SUBS:
        ids = {p.stem for p in (Path(root) / sub / "transcripts").glob("*.jsonl")}
        ids |= {p.stem for p in (Path(root) / "ledger" / "reserve" / sub).glob("*.json")}
        for run in sorted(ids):
            cost, src = _run_cost(root, sub, run)
            runs[f"{sub}/{run}"] = {"cost_usd": round(cost, 6), "source": src}
    by_sub = {s: round(sum(v["cost_usd"] for k, v in runs.items() if k.startswith(s + "/")), 6) for s in LEDGER_SUBS}
    return {"runs": runs, "by_sub": by_sub, "total_usd": round(sum(by_sub.values()), 6), "cap_usd": USD_CAP,
            "utc": now()}


def write_ledger(root: Path) -> dict[str, Any]:
    doc = ledger(root)
    write_json(Path(root) / "ledger" / "ledger.json", doc, root)
    return doc


def check_cap(root: Path, job_cap: float, probe: bool = False) -> float:
    led = ledger(root)
    if led["total_usd"] + job_cap > USD_CAP + 1e-9:
        raise BudgetRefused(f"已花 {led['total_usd']:.3f} + 本 job 上限 {job_cap:g} > 硬上限 {USD_CAP:g} USD，不啟動")
    if probe:
        n = sum(1 for k in led["runs"] if k.startswith("probe/"))
        if n >= PROBE_MAX_RUNS:
            raise BudgetRefused(f"probe 已跑 {n} 次（上限 {PROBE_MAX_RUNS}），不啟動")
        if led["by_sub"]["probe"] + job_cap > PROBE_TOTAL_USD + 1e-9:
            raise BudgetRefused(f"probe 已花 {led['by_sub']['probe']:.3f} + 上限 {job_cap:g} > {PROBE_TOTAL_USD:g} USD")
    return led["total_usd"]


def reserve(root: Path, sub: str, run_id: str, cap: float) -> Path:
    return write_json(Path(root) / "ledger" / "reserve" / sub / f"{run_id}.json",
                      {"run_id": run_id, "sub": sub, "budget_usd": cap, "at": now()}, root)


def _run_id(root: Path, sub: str, base: str) -> str:
    n = 1
    while (Path(root) / sub / "transcripts" / f"{base}_{n}.jsonl").exists() or \
            (Path(root) / "ledger" / "reserve" / sub / f"{base}_{n}.json").exists():
        n += 1
    return f"{base}_{n}"


# ---------------------------------------------------------------- one job

@dataclass(frozen=True)
class Job:
    kind: str                   # gen | label | probe
    sub: str                    # probe | p1 | p2
    base: str                   # run id stem (job id or batch id)
    system: str
    user: str
    schema: Mapping[str, Any]
    cap: float
    model: str
    effort: str


def run_job(root: Path, job: Job, pin: CL.CliPin, cwd: Path = CL.AGENT_CWD,
            launcher=None) -> dict[str, Any]:
    """Launch with reruns on infrastructure failures (none for a probe: each probe run counts against
    PROBE_MAX_RUNS); returns the job record (runs, output, violations)."""
    launcher = launcher or CL.launch
    attempts = []
    for _ in range(1 + (0 if job.kind == "probe" else MAX_RETRIES)):
        with BUDGET_LOCK:
            try:
                check_cap(root, job.cap, probe=job.kind == "probe")
            except BudgetRefused as err:
                return {"runs": attempts, "refused": str(err), "output": None, "ok": False}
            run_id = _run_id(root, job.sub, job.base)
            reserve(root, job.sub, run_id, job.cap)
        try:
            res = launcher(Path(root) / job.sub, run_id, job.system, job.user, job.schema, job.cap, job.model,
                           job.effort, pin, cwd, extra_record={"kind": job.kind})
        except (QError, OSError) as err:            # refused before starting: nothing ran, release the cap
            if not (Path(root) / job.sub / "transcripts" / f"{run_id}.jsonl").exists():
                (Path(root) / "ledger" / "reserve" / job.sub / f"{run_id}.json").unlink(missing_ok=True)
            return {"runs": attempts, "failed": str(err), "output": None, "ok": False}
        lim = CL.agent_limit(res.result, job.cap) if res.error else None
        res = replace(res, limit=lim)
        vs = TR.check_run(Path(root) / job.sub, run_id, job.model, pin.tools_mode, job.kind)
        attempts.append({"run_id": run_id, "error": res.error, "limit": lim, "seconds": res.seconds,
                         "usage": dict(res.usage), "violations": M.as_dicts(vs)})
        if res.error is None or lim:
            blind = TR.blinding(vs)
            ok = res.error is None and not blind
            return {"runs": attempts, "output": dict(res.output) if ok and res.output else None, "ok": ok,
                    "blinding": M.as_dicts(blind)}
    return {"runs": attempts, "output": None, "ok": False}


# ---------------------------------------------------------------- context

@dataclass(frozen=True)
class Ctx:
    root: Path
    spec: Mapping[str, Any]
    ch: S.Chains
    pf: P.PromptFile
    pin: CL.CliPin | None


def context(root: Path, need_pin: bool = True) -> Ctx:
    spec = S.load_spec(root)
    ref = S.load_ref()
    if ref.sha256 != spec["ref"]["sha256"]:
        raise QError(f"the reference layer changed ({ref.sha256[:12]} vs spec {spec['ref']['sha256'][:12]}): "
                     "rebuild the spec")
    rebuilt = S.build_spec(ref, spec["seed"])
    if S.spec_sha(rebuilt) != S.spec_sha(spec):
        raise QError("spec.json is not what spec_q builds from the reference and its seed")
    return Ctx(Path(root), spec, S.Chains(ref.rows), P.load_prompts(), CL.load_pin(root) if need_pin else None)


def _sets(arg: str | None) -> tuple[str, ...]:
    return SETS if arg in (None, "all") else (arg,)


def draft_path(root: Path, side: str, job_id: str) -> Path:
    return Path(root) / side / "drafts" / f"{job_id}.json"


def gen_job(ctx: Ctx, job: Mapping[str, Any]) -> Job:
    system, user, schema = P.gen_prompt(ctx.pf, ctx.ch, job)
    return Job("gen", job["set"], job["job_id"], system, user, schema, JOB_CAP_USD["gen"],
               ctx.pin.model(job["writer"]), EFFORT["gen"])


def _write_draft(ctx: Ctx, job: Mapping[str, Any], rec: Mapping[str, Any], refill_of: str | None = None) -> None:
    write_json(draft_path(ctx.root, job["set"], job["job_id"]),
               {"job_id": job["job_id"], "set": job["set"], "writer": job["writer"], "persona": job["persona"],
                "slots": [s["slot"] for s in job["slots"]], "refill_of": refill_of, "utc": now(), **rec}, ctx.root)


def run_many(ctx: Ctx, jobs: Sequence[tuple[Mapping[str, Any], Job]], refill: bool = False) -> dict[str, int]:
    """Writer jobs, at most PARALLEL at once, in the given order; drafts written as they finish."""
    def one(pair) -> bool:
        job, j = pair
        rec = run_job(ctx.root, j, ctx.pin)
        _write_draft(ctx, job, rec, job["job_id"][:-2] if refill else None)
        return bool(rec["ok"])
    done: list[bool] = []
    if jobs:
        with ThreadPoolExecutor(max_workers=min(PARALLEL, len(jobs))) as pool:
            done = list(pool.map(one, jobs))
    write_ledger(ctx.root)
    return {"ok": sum(done), "failed": len(done) - sum(done)}


# ---------------------------------------------------------------- items (mech_q rules)

def _slot_items(ctx: Ctx, finder: M.NameFinder, job: Mapping[str, Any], draft: Mapping[str, Any] | None
                ) -> dict[str, dict[str, Any]]:
    out = {}
    got, bad = M.slot_violations(job, (draft or {}).get("output")) if draft and draft.get("ok") else ({}, [])
    for s in job["slots"]:
        it = {k: s.get(k) for k in ("item_id", "set", "kind", "qtype", "intent", "kingdom", "start", "other", "k",
                                    "n", "aspect", "gold", "cell", "slot")}
        it.update(job=job["job_id"], persona=job["persona"], writer=job["writer"], question=got.get(s["slot"]),
                  flags=[], refilled=False)
        if draft is None:
            it.update(valid=False, violations=[{"rule": "v_missing", "detail": "no draft", "level": "error"}])
        elif not draft.get("ok"):
            it.update(valid=False, violations=[{"rule": "v_run", "detail": "the job produced no usable output",
                                                "level": "error"}])
        elif it["question"] is None:
            it.update(valid=False, violations=M.as_dicts(v for v in bad if v.detail.startswith(s["slot"])) or
                      [{"rule": "v_slot", "detail": "no question", "level": "error"}])
        else:
            vs, flags = M.item_checks(ctx.ch, finder, s, it["question"])
            it.update(valid=not vs, violations=M.as_dicts(vs), flags=flags)
        out[s["slot"]] = it
    return out


def assemble(ctx: Ctx, side: str) -> list[dict[str, Any]]:
    """Every slot of the side in spec order, refills applied, duplicates marked, labels attached."""
    finder = M.NameFinder(ctx.ch)
    labels = _labels(ctx.root, side)
    items = []
    for job in (j for j in ctx.spec["jobs"] if j["set"] == side):
        first = _slot_items(ctx, finder, job, _read(draft_path(ctx.root, side, job["job_id"])))
        rjob = refill_job(job, first)
        rdraft = _read(draft_path(ctx.root, side, rjob["job_id"])) if rjob else None
        second = _slot_items(ctx, finder, rjob, rdraft) if rdraft else {}
        for lab, it in first.items():
            if not it["valid"] and lab in second:
                it = dict(second[lab], job=job["job_id"], refilled=True, first_violations=it["violations"])
            items.append(it)
    items = M.dedupe(items)
    out = []
    for it in items:
        lab = labels.get(it["item_id"]) if it["valid"] else None
        ok, why = M.label_consistent(ctx.ch, finder, it, lab) if lab else (None, [])
        out.append(dict(it, label=lab, label_consistent=ok, label_reasons=why))
    return out


def refill_job(job: Mapping[str, Any], first: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """The one refill job of a writer job: its invalid slots (duplicates excluded), same persona and writer."""
    redo = [s for s in job["slots"] if not first[s["slot"]]["valid"]]
    return dict(job, job_id=f"{job['job_id']}-r", slots=redo) if redo else None


def _read(path: Path) -> dict[str, Any] | None:
    return read_json(path) if Path(path).is_file() else None


def _labels(root: Path, side: str) -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted((Path(root) / side / "labels").glob("*.json")):
        doc = read_json(p)
        for it in ((doc.get("output") or {}).get("items") or []) if doc.get("ok") else []:
            iid = doc["map"].get(it.get("id"))
            if iid:
                out[iid] = {k: it.get(k) for k in ("intent", "king", "kingdom", "k", "n", "second_king")}
    return out


def write_items(ctx: Ctx, side: str) -> dict[str, Any]:
    items = assemble(ctx, side)
    doc = {"set": side, "spec_sha256": S.spec_sha(ctx.spec), "utc": now(), "items": items}
    write_json(Path(ctx.root) / side / "items.json", doc, ctx.root)
    return item_counts(items)


def item_counts(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [i for i in items if i["valid"]]
    return {"slots": len(items), "valid": len(valid), "invalid": len(items) - len(valid),
            "refilled": sum(1 for i in items if i.get("refilled")),
            "labelled": sum(1 for i in valid if i.get("label")),
            "label_inconsistent": sum(1 for i in valid if i.get("label_consistent") is False),
            "flags": {f: sum(1 for i in valid if f in i["flags"]) for f in ("f_start_unnamed", "f_between")},
            "violations": counts(v["rule"] for i in items for v in i["violations"])}


# ---------------------------------------------------------------- commands

def cmd_gen(ctx: Ctx, sides: Sequence[str]) -> dict[str, Any]:
    by_id = S.jobs_by_id(ctx.spec)
    todo = [by_id[j] for j in ctx.spec["order"] if by_id[j]["set"] in sides
            and not draft_path(ctx.root, by_id[j]["set"], j).is_file()]
    return {"started": len(todo), **run_many(ctx, [(j, gen_job(ctx, j)) for j in todo])}


def cmd_refill(ctx: Ctx, sides: Sequence[str]) -> dict[str, Any]:
    finder, todo = M.NameFinder(ctx.ch), []
    by_id = S.jobs_by_id(ctx.spec)
    for jid in ctx.spec["order"]:
        job = by_id[jid]
        if job["set"] not in sides:
            continue
        draft = _read(draft_path(ctx.root, job["set"], jid))
        if draft is None:
            raise QError(f"{jid}: no draft yet (run gen first)")
        rjob = refill_job(job, _slot_items(ctx, finder, job, draft))
        if rjob and not draft_path(ctx.root, job["set"], rjob["job_id"]).is_file():
            todo.append((rjob, gen_job(ctx, rjob)))
    return {"started": len(todo), **run_many(ctx, todo, refill=True)}


def label_batches(items: Sequence[Mapping[str, Any]], side: str, seed: int = SEED) -> list[list[Mapping[str, Any]]]:
    pool = sorted((i for i in items if i["valid"] and not i.get("label")), key=lambda i: i["item_id"])
    random.Random(f"{seed}:label:{side}").shuffle(pool)
    return [pool[i:i + LABEL_BATCH] for i in range(0, len(pool), LABEL_BATCH)]


def cmd_label(ctx: Ctx, sides: Sequence[str]) -> dict[str, Any]:
    tally = {"started": 0, "ok": 0, "failed": 0}
    for side in sides:
        items = assemble(ctx, side)
        done = len(list((ctx.root / side / "labels").glob("*.json")))
        for n, batch in enumerate(label_batches(items, side), done + 1):
            ids = {f"x{i:02d}": it["item_id"] for i, it in enumerate(batch, 1)}
            system, user, schema = P.label_prompt(ctx.pf, [(x, it["question"]) for x, it in zip(ids, batch)])
            job = Job("label", side, f"label_{side}_b{n:02d}", system, user, schema, JOB_CAP_USD["label"],
                      ctx.pin.model(LABELLER), EFFORT["label"])
            rec = run_job(ctx.root, job, ctx.pin)
            write_json(ctx.root / side / "labels" / f"b{n:02d}.json", {"batch": n, "map": ids, "utc": now(), **rec},
                       ctx.root)
            tally["started"] += 1
            tally["ok" if rec["ok"] else "failed"] += 1
        write_items(ctx, side)
    write_ledger(ctx.root)
    return tally


def cmd_status(ctx: Ctx) -> dict[str, Any]:
    out: dict[str, Any] = {"ledger_usd": ledger(ctx.root)["total_usd"], "cap_usd": USD_CAP}
    for side in SETS:
        jobs = [j for j in ctx.spec["jobs"] if j["set"] == side]
        drafts = [_read(draft_path(ctx.root, side, j["job_id"])) for j in jobs]
        out[side] = {"jobs": len(jobs), "drafted": sum(1 for d in drafts if d),
                     "ok": sum(1 for d in drafts if d and d.get("ok")),
                     "items": item_counts(assemble(ctx, side)) if any(drafts) else None}
    return out


# ---------------------------------------------------------------- probe and pin

def probe_checks(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, job: Mapping[str, Any],
                 model_key: str, tools_mode: str, memory_empty: bool) -> dict[str, Any]:
    init, res = CL.init_event(events) or {}, CL.result_event(events) or {}
    used = sorted((res.get("modelUsage") or {}))
    resolved = MODEL_IDS.get(model_key) or (used[0] if len(used) == 1 else None)
    fallback = CL.model_fallback(events, res or None, resolved or "?")
    out = res.get("structured_output") if isinstance(res.get("structured_output"), dict) else None
    got, bad = M.slot_violations(job, out)
    vs = TR.check_events(events, prompts, MODEL_IDS.get(model_key), tools_mode, "probe")
    memory = [v.detail for v in vs if v.rule == "t_memory"]
    tokens = TR.first_prompt_tokens(events)
    tools = list(init.get("tools") or [])
    return {
        "c1_init": "pass" if not TR.init_violations(events, MODEL_IDS.get(model_key), tools_mode) else "fail",
        "c2_structured_output": "pass" if "StructuredOutput" in tools and out is not None and not bad
                                and len(got) == len(job["slots"]) else "fail",
        "c3_model": "pass" if resolved and fallback is None and init.get("model") in (resolved, model_key) else "fail",
        "c4_no_memory": "pass" if memory_empty and not memory and tokens is not None
                        and tokens <= MAX_FIRST_PROMPT_TOKENS else "fail",
        "c5_result": "pass" if CL.failure(0, res or None) is None else "fail",
        "detail": {"init_tools": tools, "init_model": init.get("model"), "model_usage": used, "resolved": resolved,
                   "fallback": fallback, "first_prompt_tokens": tokens, "memory_hits": memory[:3],
                   "violations": [v.as_dict() for v in vs if v.level == "error"][:5],
                   "slot_problems": [b.detail for b in bad],
                   "usage": CL.usage_of(res or None), "cli": init.get("claude_code_version")}}


def cmd_probe(root: Path, model_key: str, tools_mode: str, cwd: Path = CL.AGENT_CWD, launcher=None) -> dict[str, Any]:
    spec = S.load_spec(root)
    ch, pf = S.Chains(S.load_ref().rows), P.load_prompts()
    job = S.probe_job(spec, model_key)
    system, user, schema = P.gen_prompt(pf, ch, job)
    model = MODEL_IDS.get(model_key, model_key)
    pin = CL.CliPin(CLAUDE_VERSION, True, tools_mode, {model_key: model})
    launcher = launcher or (lambda *a, **k: CL.launch(*a, **k, check_model=model_key in MODEL_IDS))
    rec = run_job(root, Job("probe", "probe", f"probe_{model_key}", system, user, schema, JOB_CAP_USD["probe"],
                            model, EFFORT["probe"]), pin, cwd, launcher)
    if not rec["runs"]:
        return {"action": "stop", "error": rec.get("refused") or rec.get("failed")}
    run_id = rec["runs"][-1]["run_id"]
    events = CL.read_events(Path(root) / "probe" / "transcripts" / f"{run_id}.jsonl")
    prompts = read_json(Path(root) / "probe" / "prompts" / f"{run_id}.json")
    checks = probe_checks(events, prompts, job, model_key, tools_mode, not any(CL.memory_dir(cwd).glob("*")))
    keys = ("c1_init", "c2_structured_output", "c3_model", "c4_no_memory", "c5_result")
    ok = all(checks[k] == "pass" for k in keys)
    doc = {"model_key": model_key, "model_arg": model, "tools_mode": tools_mode, "claude_version": CLAUDE_VERSION,
           "thinking_display": True, "effort": EFFORT["probe"], "from_job": job["from_job"], "slots": len(job["slots"]),
           "run_ids": [r["run_id"] for r in rec["runs"]], "checks": checks, "pass": ok,
           "action": "pin" if ok else "stop", "cost_usd": checks["detail"]["usage"]["total_cost_usd"], "utc": now()}
    n = 1 + len(list((Path(root) / "probe").glob("verdict_*.json")))
    path = write_json(Path(root) / "probe" / f"verdict_{n}.json", doc, root)
    write_ledger(root)
    return {k: doc[k] for k in ("action", "pass", "model_key", "tools_mode", "cost_usd")} | \
        {"checks": {k: checks[k] for k in keys}, "resolved": checks["detail"]["resolved"],
         "init_tools": checks["detail"]["init_tools"], "verdict": str(path)}


def cmd_pin(root: Path, verdicts: Sequence[Path]) -> dict[str, Any]:
    docs = [read_json(v) for v in verdicts]
    if not docs or not all(d.get("pass") for d in docs):
        raise QError("every verdict must pass (action pin)")
    modes = {d["tools_mode"] for d in docs}
    if len(modes) != 1:
        raise QError(f"verdicts disagree on tools_mode {sorted(modes)}")
    models = {d["model_key"]: d["checks"]["detail"]["resolved"] for d in docs}
    if LABELLER not in models:
        raise QError(f"no passing verdict for the labeller model {LABELLER!r}")
    pin = CL.CliPin(CLAUDE_VERSION, True, modes.pop(), models)
    costs = [d["cost_usd"] for d in docs if isinstance(d.get("cost_usd"), (int, float))]
    path = CL.write_pin(root, pin, verdicts=[Path(v).name for v in verdicts],
                        probe_job_cost_usd=costs, probe_slots=[d["slots"] for d in docs])
    return {"pin": str(path), **pin.as_dict(), "probe_job_cost_usd": costs}


def cmd_show(ctx: Ctx, job_id: str) -> str:
    job = S.jobs_by_id(ctx.spec).get(job_id)
    if job is None or job["set"] != "p1":
        raise QError("show prints p1 jobs only (p2 is locked)")
    system, user, _ = P.gen_prompt(ctx.pf, ctx.ch, job)
    return f"--- system ---\n{system}\n--- user ---\n{user}"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="問法集出題執行（≤10 USD）")
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--model", required=True)
    p.add_argument("--tools-mode", choices=CL.TOOLS_MODES, default="none")
    p = sub.add_parser("pin")
    p.add_argument("--verdict", type=Path, nargs="+", required=True)
    for name in ("gen", "refill", "label", "mech"):
        sub.add_parser(name).add_argument("--set", choices=(*SETS, "all"), default="all")
    sub.add_parser("budget")
    sub.add_parser("status")
    sub.add_parser("show").add_argument("--job", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "probe":
        out: Any = cmd_probe(a.root, a.model, a.tools_mode)
    elif a.cmd == "pin":
        out = cmd_pin(a.root, a.verdict)
    elif a.cmd == "budget":
        out = write_ledger(a.root)
        out = {k: out[k] for k in ("by_sub", "total_usd", "cap_usd")} | {"runs": len(out["runs"])}
    else:
        ctx = context(a.root, need_pin=a.cmd in ("gen", "refill", "label"))
        if a.cmd == "show":
            print(cmd_show(ctx, a.job))
            return 0
        if a.cmd == "status":
            out = cmd_status(ctx)
        elif a.cmd == "mech":
            out = {s: write_items(ctx, s) for s in _sets(a.set)}
        else:
            out = {"gen": cmd_gen, "refill": cmd_refill, "label": cmd_label}[a.cmd](ctx, _sets(a.set))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BudgetRefused as err:
        print(json.dumps({"action": "stop", "error": f"budget: {err}"}, ensure_ascii=False))
        sys.exit(3)
    except (QError, OSError, ValueError) as err:
        print(json.dumps({"action": "stop", "error": f"{type(err).__name__}: {err}"}, ensure_ascii=False))
        sys.exit(2)
