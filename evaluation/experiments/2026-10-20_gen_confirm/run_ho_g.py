"""Blind question-writing executor of the GEN confirmation set (prereg §3, §8.1-7..9, §8.2): pilot, K-P, main writing.

    run_ho_g.py pilot [--infra-fix LINE]   # order positions 1–12 until every pilot slot is done (passed, failed or
                                           # in dispute)
    run_ho_g.py kp                         # once, after the pilot: HO_ROOT/kp.json (n_target, n_KP, the K-P gate)
    run_ho_g.py main [--infra-fix LINE]    # positions 13..n_target; refused unless kp.json says go
    run_ho_g.py stop-drafting              # §8.1-8 hard cap by hand (main does it by itself when no draft fits)
    run_ho_g.py kay [--infra-fix LINE]     # after kay_g.py apply: Kay's revisions and the disputes he kept
    run_ho_g.py repin --anchor LINE        # after a CliChanged stop: the re-probe's new cli_pin.json, logged
    run_ho_g.py status                     # counts only, never question text

Order: CLI probe and pin → P1 → F1a → P2 → G1 (qset/g1.json) → F1 → order.json → pilot → kp → main → kay_g.py draw /
apply → kay → freeze_g.py (F2 steps 1–4) → f2_g.py. Every agent command refuses unless the F1 manifest, order.json
(drawn from it, state_g.load_plan) and cli_pin.json exist and every file the F1 manifest names is unchanged now
(f1_g.manifest_problems over f1_g.frozen_paths() and f1_g.prod_pins(), g_common.backend_pins() with trigger_pins():
the prompt files, banned terms, g_common, mech_g, gencard, gen_names, the CLI pin); the pilot also needs
qset/g1.json with pass true (the cross-track contract, state_g.g1_problems) and no kp.json yet. One runner at a
time (state_g.locked).

Logged infrastructure fixes (prereg §2.3, §3.1, §8.1: thresholds fixed in F0, only logged infrastructure fixes after):
* A job that used its MAX_INFRA_RETRIES reruns stops the runner with an infra stop; every agent command then refuses
  until it is given ``--infra-fix LINE``: one whole line of prereg.md's 執行紀錄 that was not there at the stop and
  that no earlier fix or re-pin used (f1_g.anchor_problems). So no job gets more than 1 + MAX_INFRA_RETRIES runs per
  logged fix.
* CliChanged stops the runner with a CLI stop (§3.1: re-probe, log it, change nothing else). After probe_g.py run and
  pin, ``repin --anchor LINE`` records the new pin in HO_ROOT/repins.json: {from_sha256, to_sha256, the pin's
  version, CLI sha and thinking flag, the verdict and its sha256, the anchor}. The new cli_pin.json must come from a
  probe verdict in the store (action pin or drop_thinking_display, the same CLI sha and version), its CLI copy must
  hash as pinned, its models and probed pairs those of claude_g. The F1 manifest is never rewritten (order.json is
  drawn from it): ``f1_problems`` accepts a cli_pin.json other than the manifest's only at the end of an unbroken
  chain of logged re-pins whose anchors are still lines of the log.

K-P (§8.1-7), once, after every pilot slot is done:
  per_slot  = spent_by_root(HO_ROOT/pilot) / pilot slots opened (at least one draft launched)
  projected(n) = ledger total now (every root: probes, qset, HO) + (n − PILOT) × per_slot
  n_target  = 58 when projected(58) ≤ KP_BUDGET_USD (47), else the longest prefix n ≥ PILOT with projected(n) ≤ 47;
              never below PILOT (the order's length, not 58, in a test pool)
  n_KP      = power_g.kp_n(passed, opened, n_target): round-half-up(min(passed / opened, 0.914) × n_target) in exact
              fractions; passed = pilot slots whose question passed mech, the audit and the three-way comparison
  stop      when power_g.g1(pool, R_card, R_wrong, n_v, n = n_KP)'s pow_H1_and_H2 < 0.70 (qset/g1.json's P2 counts),
            or K-gold holds (the §3.6 CPU trace found the program gold wrong); the sentence is analyze_g.stop_sentence
            (〈條目〉 K-P or K-gold, state 未凍結: the pilot questions exist, nothing is frozen).
Exit 0 done (a rule stop included: its sentence is printed and recorded), 2 error or infrastructure stop (CliChanged:
re-probe, §3.1), 3 budget cap in the pilot (the job was not started; state saved).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import analyze_g as AG
import claude_g as CL
import f1_g as F1
import g_common as GC
import hog_common as H
import k0_g as K0
import kay_g as K
import ledger_g as L
import power_g as PW
import prompts_g as P
import runs_g as RU
import state_g as S
from hog_common import BudgetRefused, HoError, now, read_json, write_json

KP_SCHEMA = "gen_confirm.kp.v1"
REPINS_SCHEMA = "gen_confirm.repins.v1"
K_GOLD_FILE = GC.K_GOLD_FILE
HO_FILES = H.TOOL_FILES                              # the tool files and this runner's modules (hog_common)
CLI_KEY = F1.rel(F1.CLI_PIN, GC.STORE)               # the F1 manifest's key of store cli_pin.json
PIN_VERDICTS = ("pin", "drop_thinking_display")     # probe_g.pin_from writes a pin only from these
G1Fn = Callable[[int, int, int, int], Mapping[str, Any]]


# ---------------------------------------------------------------- the F1 manifest and logged re-pins (§3.1)
def repins(paths: S.Paths) -> list[dict[str, Any]]:
    return list(read_json(paths.repins).get("repins") or ()) if paths.repins.is_file() else []


def pin_problems(manifest_sha: str | None, chain: Sequence[Mapping[str, Any]], now_sha: str | None,
                 prereg: Path = F1.PREREG) -> list[str]:
    """cli_pin.json now against the manifest's pin and the logged re-pins after it (sha prefixes only)."""
    if manifest_sha is None:
        return ["the F1 manifest names no cli_pin.json"]
    want, lines, out = manifest_sha, set(F1.log_lines(prereg)), []
    for r in chain:
        if r.get("from_sha256") != want:
            return out + ["repins.json is not one chain from the F1 manifest's cli_pin.json"]
        if r.get("anchor") not in lines:
            out.append(f"re-pin {str(r.get('to_sha256'))[:12]}: its anchor is no longer a line of 執行紀錄")
        want = r.get("to_sha256")
    return out + ([] if now_sha == want else
                  ["cli_pin.json is neither the F1 manifest's nor the last logged re-pin (§3.1: re-probe, repin)"])


def f1_problems(paths: S.Paths, *, current: Mapping[str, str | None] | None = None,
                prereg: Path = F1.PREREG) -> list[str]:
    """Every file the F1 manifest names unchanged now, the CLI pin up to logged re-pins (keys only in the messages).
    ``current`` (tests) stands for the frozen and backend files now; the pin is always paths.cli_pin."""
    if not paths.f1_manifest.is_file():
        return ["no F1 manifest"]
    files = dict(read_json(paths.f1_manifest)["files"])
    now_files = dict(current) if current is not None else {**F1.sha_map(F1.frozen_paths()), **F1.prod_pins()}
    now_files.pop(CLI_KEY, None)
    pin = GC.sha256_file(paths.cli_pin) if paths.cli_pin.is_file() else None
    out = F1.manifest_problems({k: v for k, v in files.items() if k != CLI_KEY}, now_files)
    return out + pin_problems(files.get(CLI_KEY), repins(paths), pin, prereg)


def _verdict_problems(paths: S.Paths, doc: Mapping[str, Any], pin: CL.CliPin) -> list[str]:
    name, sha = doc.get("verdict"), doc.get("verdict_sha256")
    path = L.Ledger(paths.out_root).base("probe") / str(name or "")
    if not (name and sha and path.is_file() and GC.sha256_file(path) == sha):
        return ["cli_pin.json names no probe verdict in the store with its sha256 (probe_g.py pin writes both)"]
    v = read_json(path)
    out = [] if v.get("action") in PIN_VERDICTS else [f"the verdict's action {v.get('action')!r} pins nothing"]
    return out + ([] if (v.get("cli_sha256"), v.get("claude_version_expected")) == (pin.cli_sha256, pin.claude_version)
                  else ["the verdict probed another CLI copy or version"])


def repin(paths: S.Paths = S.Paths(), anchor: str = "", *, prereg: Path = F1.PREREG) -> dict[str, Any]:
    """Record the re-probe's cli_pin.json (logged at ``anchor``) and clear an open CLI stop."""
    with S.locked(paths):
        plan = S.load_plan(paths)
        files, chain = read_json(paths.f1_manifest)["files"], repins(paths)
        end = chain[-1]["to_sha256"] if chain else files.get(CLI_KEY)
        bad = pin_problems(files.get(CLI_KEY), chain, end, prereg)
        now_sha = GC.sha256_file(paths.cli_pin) if paths.cli_pin.is_file() else None
        if now_sha is None or now_sha == end:
            raise HoError("cli_pin.json is the pinned one: nothing to re-pin")
        doc = read_json(paths.cli_pin)
        pin = CL.CliPin.from_dict(doc)
        bad += _verdict_problems(paths, doc, pin)
        if dict(pin.models) != CL.MODELS or set(pin.combos) != set(CL.PROBED_COMBOS):
            bad.append("the new pin's models or probed pairs are not claude_g's")
        state = S.load_state(paths, plan)
        stop = S.open_stop(state)
        seen = stop["log_lines_sha256"] if stop else ()
        used = S.stop_anchors(state) + [r["anchor"] for r in chain]
        bad += F1.anchor_problems(anchor, prereg, used=used, seen=seen)
        if bad:
            raise HoError(f"re-pin refused: {bad}")
        CL.check_cli(pin)
        rec = {"from_sha256": end, "to_sha256": now_sha, "claude_version": pin.claude_version,
               "cli_sha256": pin.cli_sha256, "thinking_display": pin.thinking_display, "verdict": doc["verdict"],
               "verdict_sha256": doc["verdict_sha256"], "anchor": anchor.strip(), "t": now()}
        write_json(paths.repins, {"schema": REPINS_SCHEMA, "repins": [*chain, rec]})
        if stop and stop["kind"] == "cli_changed":
            S.save_state(paths, S.clear_stop(state, "repin", anchor))
        return rec


def resume(state: Mapping[str, Any], infra_fix: str | None, prereg: Path, used: Sequence[str] = ()) -> dict[str, Any]:
    """The state an agent command may run on: an open infra stop cleared by a logged fix (an anchor that no earlier
    fix or re-pin (``used``) took), never a CLI stop (repin clears that one)."""
    stop = S.open_stop(state)
    if stop is None:
        if infra_fix is not None:
            raise HoError("--infra-fix: there is no infrastructure stop to resume from")
        return dict(state)
    if stop["kind"] == "cli_changed":
        raise HoError("CLI stop (§3.1): re-probe (probe_g.py run, pin), log it, then run_ho_g.py repin --anchor LINE")
    if infra_fix is None:
        raise HoError(f"infrastructure stop (§2.3: {stop['note']}): log the fix in 執行紀錄, then rerun with "
                      "--infra-fix LINE")
    bad = F1.anchor_problems(infra_fix, prereg, used=[*S.stop_anchors(state), *used], seen=stop["log_lines_sha256"])
    if bad:
        raise HoError(f"--infra-fix refused: {bad}")
    return S.clear_stop(state, "infra_fix", infra_fix)


def make_ctx(paths: S.Paths, plan: S.Plan, **kw: Any) -> RU.Ctx:
    """The executor context: names (gen_names.json), the F1-frozen prompt files, the CLI pin; ``kw`` overrides."""
    base = {"names": P.load_names(paths.names), "pin": CL.load_pin(paths.cli_pin), "prompts": P.default_prompts()}
    return RU.Ctx(paths, plan, **{**base, **kw})


def agent_gates(paths: S.Paths, f1_check: Callable[[S.Paths], list[str]] = f1_problems) -> S.Plan:
    for p, why in ((paths.f1_manifest, "the F1 manifest"), (paths.order, "order.json"), (paths.cli_pin, "cli_pin.json")):
        if not p.is_file():
            raise HoError(f"{why} missing ({p.name}): F1, order.json and the CLI pin come first (prereg §8.1)")
    plan = S.load_plan(paths)
    bad = f1_check(paths)
    if bad:
        raise HoError(f"F1-frozen files changed: {bad[:5]}")
    if (paths.ho_root / K_GOLD_FILE).is_file():
        raise HoError(f"K-gold stopped the line ({K_GOLD_FILE})")
    return plan


def _save(paths: S.Paths) -> Callable[[Mapping[str, Any]], Any]:
    return lambda st: S.save_state(paths, st)


def _meta(ctx: RU.Ctx, cmd: str) -> dict[str, Any]:
    return {"cmd": cmd, "pin": ctx.pin.as_dict(), "prompts_sha256": {p.path.name: p.sha256 for p in ctx.prompts},
            "tools_sha256": H.tool_sha(HO_FILES), "model": ctx.model}


def _k_gold(paths: S.Paths, state: Mapping[str, Any]) -> dict[str, Any]:
    sids = sorted(state.get("k_gold_cpu") or ())
    doc = {"rule": "K-gold", "sids": sids, "t": now(),
           "sentence": AG.stop_sentence("K-gold", f"CPU 追查：程式 gold 與獨立讀取不一致（{len(sids)} 個題位）", "未凍結")}
    write_json(paths.ho_root / K_GOLD_FILE, doc)
    return doc


def _drive(paths: S.Paths, ctx: RU.Ctx, sids: Sequence[str], mode: str, infra_fix: str | None = None,
           stop: Callable[[Mapping[str, Any]], bool] | None = None) -> dict[str, Any]:
    state = resume(S.recover(S.load_state(paths, ctx.plan)), infra_fix, ctx.prereg,
                   [r["anchor"] for r in repins(paths)])
    state = S.log(state, {**_meta(ctx, f"run_ho_g.py {mode}"), "infra_fix": infra_fix})
    S.save_state(paths, state)
    try:
        return RU.drive(ctx, state, sids, mode, _save(paths), stop)
    except RU.KGold:
        _k_gold(paths, S.load_state(paths, ctx.plan))
        raise


def pilot(paths: S.Paths = S.Paths(), ctx: RU.Ctx | None = None, *,
          f1_check: Callable[[S.Paths], list[str]] = f1_problems, infra_fix: str | None = None) -> dict[str, Any]:
    """The 12 pilot slots (order positions 1–12) until each is done."""
    with S.locked(paths):
        plan = agent_gates(paths, f1_check)
        S.read_g1(paths)
        if paths.kp.is_file():
            raise HoError("kp.json exists: the pilot is over (K-P was judged)")
        return _drive(paths, ctx or make_ctx(paths, plan), plan.pilot, "pilot", infra_fix)


# ---------------------------------------------------------------- K-P (§8.1-7)
def default_g1(r_card: int, r_wrong: int, n_v: int, n: int) -> Mapping[str, Any]:
    return PW.g1(PW.load_pool(), r_card, r_wrong, n_v, n=n)


def kp_decision(spent: float, pilot_spent: float, opened: int, passed: int, g1_doc: Mapping[str, Any], *,
                k_gold: bool, n_pool: int, g1_fn: G1Fn = default_g1) -> dict[str, Any]:
    """K-P's arithmetic and verdict (pure but for g1_fn)."""
    if opened <= 0:
        raise HoError("no pilot slot was opened: K-P has no pilot spend per slot")
    per = pilot_spent / opened

    def projected(n: int) -> float:
        return spent + (n - GC.PILOT) * per

    fits = [n for n in range(GC.PILOT, n_pool + 1) if projected(n) <= GC.KP_BUDGET_USD + RU.EPS]
    n_target = max(fits, default=GC.PILOT)
    n_kp = PW.kp_n(passed, opened, n_target)
    rc, rw, nv = (int(g1_doc[k]) for k in ("R_card", "R_wrong", "n_v"))
    g1 = dict(g1_fn(rc, rw, nv, n_kp)) if n_kp > 0 else {"n": 0, "pow_H1_and_H2": 0.0, "pass": False}
    pw = float(g1["pow_H1_and_H2"])
    k_p = not (g1["pass"] and pw >= PW.TARGET)
    rule = "K-gold" if k_gold else "K-P" if k_p else None
    value = ("CPU 追查：程式 gold 錯" if k_gold else
             f"檢定力 {pw:.4f}＜{PW.TARGET:.2f}（n_KP＝{n_kp}；pilot 通過 {passed}/{opened}；n_target＝{n_target}）")
    return {"schema": KP_SCHEMA, "t": now(), "spent_usd": round(spent, 6), "pilot_spent_usd": round(pilot_spent, 6),
            "opened": opened, "passed": passed, "per_slot_usd": round(per, 6), "budget_usd": GC.KP_BUDGET_USD,
            "n_pool": n_pool, "projected_full_usd": round(projected(n_pool), 6),
            "projected_n_target_usd": round(projected(n_target), 6), "n_target": n_target, "n_kp": n_kp,
            "g1_inputs": {"R_card": rc, "R_wrong": rw, "n_v": nv}, "g1": g1, "k_p_fails": k_p, "k_gold": k_gold,
            "stop": rule is not None, "go": rule is None, "rule": rule,
            "sentence": AG.stop_sentence(rule, value, "未凍結") if rule else None}


def kp(paths: S.Paths = S.Paths(), *, g1_fn: G1Fn = default_g1) -> dict[str, Any]:
    """kp.json, once, after every pilot slot is done."""
    with S.locked(paths):
        plan = S.load_plan(paths)
        if paths.kp.is_file():
            raise HoError("kp.json exists: K-P is judged once")
        state = S.load_state(paths, plan)
        if not S.done(state, plan.pilot):
            raise HoError(f"the pilot is not done: {S.summary(state, plan.pilot)['by_status']}")
        g1_doc = S.read_g1(paths)
        led = L.Ledger(paths.out_root)
        snap = led.snapshot()
        pilot_rel = led.rel(paths.root("pilot"))
        recs = [S.slot(state, s) for s in plan.pilot]
        doc = kp_decision(snap["total_usd"], snap["by_root"].get(pilot_rel, 0.0), sum(map(S.opened, recs)),
                          sum(r["status"] == S.PASSED for r in recs), g1_doc, k_gold=bool(state.get("k_gold_cpu")),
                          n_pool=len(plan.order), g1_fn=g1_fn)
        doc["g1_inputs"]["g1_sha256"] = GC.sha256_file(paths.g1)
        doc["state_summary"] = S.summary(state, plan.pilot)
        write_json(paths.kp, doc)
        return doc


# ---------------------------------------------------------------- main writing, the hard cap, Kay's work
def main_phase(paths: S.Paths = S.Paths(), ctx: RU.Ctx | None = None, *,
               f1_check: Callable[[S.Paths], list[str]] = f1_problems, infra_fix: str | None = None) -> dict[str, Any]:
    """Positions PILOT+1..n_target until each is done (or cap-stopped)."""
    with S.locked(paths):
        plan = agent_gates(paths, f1_check)
        doc = S.kp_go(paths)
        if S.load_state(paths, plan).get("kay"):
            raise HoError("Kay's page is drawn: no more writing")
        return _drive(paths, ctx or make_ctx(paths, plan), plan.main(doc["n_target"]), "main", infra_fix)


def stop_drafting(paths: S.Paths = S.Paths()) -> dict[str, Any]:
    """§8.1-8 by hand: only when not even one more draft fits (ledger spent + the draft cap > USD_CAP − margin)."""
    with S.locked(paths):
        plan = S.load_plan(paths)
        doc = S.kp_go(paths)
        spent = L.Ledger(paths.out_root).spent()
        if spent + GC.JOB_CAP_USD["draft"] <= L.SPEND_LIMIT_USD + RU.EPS:
            raise HoError(f"已花 {spent:.3f} + 出題上限 {GC.JOB_CAP_USD['draft']:g} ≤ {L.SPEND_LIMIT_USD:g} USD："
                          "未達硬上限，不停筆")
        state = S.stop_drafting(S.load_state(paths, plan), plan.main(doc["n_target"]), spent, "stop-drafting 指令")
        S.save_state(paths, state)
        return state


def kay_work(paths: S.Paths = S.Paths(), ctx: RU.Ctx | None = None, *,
             f1_check: Callable[[S.Paths], list[str]] = f1_problems, infra_fix: str | None = None) -> dict[str, Any]:
    """Kay's revisions and the disputed attempts he kept (HO_ROOT/kay), then kay.json's record; no wave starts once
    K-Kay or K-gold holds (§3.7)."""
    with S.locked(paths):
        plan = agent_gates(paths, f1_check)
        doc = S.kp_go(paths)
        state = S.load_state(paths, plan)
        K.require_applied(state)
        rec = K.record(state, plan)
        if rec["stop"]:
            raise HoError(f"Kay's page stopped the line: {rec['sentence']}")
        state = _drive(paths, ctx or make_ctx(paths, plan), plan.planned(doc["n_target"]), "kay", infra_fix,
                       stop=lambda st: K.record(st, plan)["stop"])
        K.write_record(paths, state, plan)
        return state


def status(paths: S.Paths = S.Paths()) -> dict[str, Any]:
    """Counts only: slots by status (pilot, main), the ledger by kind, K-P and Kay's page."""
    plan = S.load_plan(paths)
    state = S.load_state(paths, plan)
    doc = S.read_kp(paths)
    snap = L.Ledger(paths.out_root).snapshot()
    out = {"pilot": S.summary(state, plan.pilot), "ledger": {k: snap[k] for k in ("by_kind", "total_usd", "limit_usd")},
           "kp": None if doc is None else {k: doc.get(k) for k in ("n_target", "n_kp", "go", "rule")},
           "open_stop": (S.open_stop(state) or {}).get("kind"), "repins": len(repins(paths))}
    if doc is not None:
        out["main"] = S.summary(state, plan.main(doc["n_target"]))
    if state.get("kay") and state["kay"].get("applied"):
        rec = K.record(state, plan)
        out["kay"] = {k: rec[k] for k in ("final", "stop", "rule", "n_sampled", "n_dropped", "n_disputes")}
    elif state.get("kay"):
        out["kay"] = {"drawn": True, "applied": False}
    return out


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pilot", "kp", "main", "stop-drafting", "kay", "repin", "status"):
        sp = sub.add_parser(name)
        if name in ("pilot", "main", "kay"):
            sp.add_argument("--infra-fix", default=None, metavar="LINE", help="執行紀錄裡記錄這次基礎設施修正的一整行")
        if name == "repin":
            sp.add_argument("--anchor", required=True, metavar="LINE", help="執行紀錄裡記錄重做 probe 的一整行")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    if a.cmd == "status":
        print(f"run_ho_g.py status: {status()}")
        return 0
    if a.cmd == "kp":
        doc = kp()
        print(f"run_ho_g.py kp: n_target {doc['n_target']}, n_KP {doc['n_kp']}, "
              f"pow {doc['g1']['pow_H1_and_H2']}, go {doc['go']}" + (f"; {doc['sentence']}" if doc["stop"] else ""))
        return 0
    if a.cmd == "stop-drafting":
        state = stop_drafting()
        print(f"run_ho_g.py stop-drafting: {state['cap_stop']}; 接著跑 main 處理等待中的稿")
        return 0
    if a.cmd == "repin":
        rec = repin(anchor=a.anchor)
        print(f"run_ho_g.py repin: {rec['from_sha256'][:12]} -> {rec['to_sha256'][:12]} (CLI {rec['claude_version']})")
        return 0
    if bad := K0.k0_problems():
        raise HoError(f"K0 first (prereg §8.1-1: K0 before any USD): {bad[:3]}")
    run = {"pilot": pilot, "main": main_phase, "kay": kay_work}[a.cmd]
    try:
        run(infra_fix=a.infra_fix)
    except RU.KGold:
        doc = read_json(S.Paths().ho_root / K_GOLD_FILE)
        print(f"run_ho_g.py {a.cmd}: {doc['sentence']}")
        return 0
    if a.cmd == "kay" and (rec := read_json(S.Paths().kay)).get("stop"):
        print(f"run_ho_g.py kay: {rec['sentence']}")
        return 0
    print(f"run_ho_g.py {a.cmd}: {status()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BudgetRefused as err:
        print(f"run_ho_g.py: 預算上限：{err}", file=sys.stderr)
        sys.exit(3)
    except (HoError, OSError, ValueError) as err:
        print(f"run_ho_g.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
