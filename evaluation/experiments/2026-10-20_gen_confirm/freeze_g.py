"""F2 steps 1–4 of the GEN confirmation set (prereg §8.1-10.1..4, §1.2, §4.3): store questions_frozen.json, once.

    freeze_g.py      # after kay_g.py apply and run_ho_g.py kay; then log the printed sha256, then f2_g.py

Refused (nothing written) unless: every file the F1 manifest names is unchanged (run_ho_g.f1_problems: the rules
step 1 reruns are the frozen ones; the CLI pin up to logged re-pins); K-P let the line go on; Kay's decisions are
applied and settled (kay.json final: no revision pending, no kept dispute still running) with no K-Kay or K-gold
stop (and no CPU K-gold); every written slot (order[:n_target]) is done and no job is in flight;
questions_frozen.json does not exist.
1. Every passed question again: mech_g.check_draft on its item (its only errors may be the mech errors Kay
   overruled when he kept a mech dispute, exactly those) and transcript_g.check_run on every run of its passed
   attempt (the draft, fixes, audits, Kay's revision and re-audit): any error refuses, as freeze_a, except on a run
   that failed for infrastructure (it was rerun) that failure itself (runs_g.infra_own: no result event, no init
   event, a fallback's other model in the init event).
2. Kay's decisions: already applied to the state by kay_g.apply (accept keeps, revise went through runs_g, drop and
   the dispute drops closed their slots); here each decision is checked against the slot's end state.
3. The prod dynasty trigger (§4.3): backend/utils/regnal/trigger.py run on each question's text alone, with the r4
   regnal layer's names and blockers as prod builds them (backend/serving/context.make_active: layer.with_lexicon(
   layer.parse_layer(bytes), the contract's routing lexicon)); the loader is test_gen_confirm_gencard's nail
   (``prod_trigger``), with every file loaded by path only after its sha256 equals g_common.backend_pins() and the
   F1 manifest's value (trigger.py, layer.py, ragcommon/regnal.py, the r4 layer). The trigger also runs on files
   backend_pins() does not name: ragcommon's __init__, routing, books, ids, its data/books.json and the contract's
   routing_lexicon.json (the blockers): g_common.trigger_pins() now must equal both the F1 manifest's items (F1
   pins them beside backend_pins(), f1_g.prod_pins) and their kept sha256 (g_common.TRIGGER_PINS_SHA256), and each
   of those modules must resolve to this checkout's packages/ (a new import would change a pinned file). A
   question it fires on is deleted (attrition dynasty_trigger).
4. questions_frozen.json in arms_g's contract (arms_g.frozen_problems must return []): {"schema", "n_target",
   "questions": [{"sid", "question", "qtype"}] in pool sid order, "attrition": the six §1.2 causes}; then
   HO_ROOT/freeze.json (sha256, counts by cause and by stratum, homonym end and marker flag, failed closes by why;
   sids, no text).
Printed: the sha256 and the counts, never question text. a_meas and everything after step 4 are f2_g's: gencard
never runs here (arms_g is imported for its contract only).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

import arms_g as A
import g_common as GC
import kay_g as K
import mech_g as M
import prompts_g as P
import run_ho_g as R
import runs_g as RU
import state_g as S
import transcript_g as TR
from hog_common import HoError, now, read_json, sha256_bytes, write_json

TRIGGER_FILES = GC.PROD_TRIGGER_FILES                # trigger.py, layer.py, ragcommon/regnal.py (in backend_pins())
LEXICON = GC.ROUTING_LEXICON
LEXICON_KEY = str(LEXICON.relative_to(GC.STORE))
RAGCOMMON_USED = ("ragcommon", "ragcommon.regnal", "ragcommon.routing", "ragcommon.books", "ragcommon.ids")
FREEZE_FILE = GC.FREEZE_FILE
FLAGS = ("stratum", "homonym", "marker_required")
Fires = Callable[[str], bool]


# ---------------------------------------------------------------- the prod dynasty trigger (§4.3)
def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def prod_trigger(manifest_files: Mapping[str, str], pins: Callable[[], Mapping[str, str]] = GC.backend_pins,
                 trigger_pins: Callable[[], Mapping[str, str]] = GC.trigger_pins) -> Fires:
    """question -> whether prod's dynasty trigger fires on it, with the r4 layer's names and blockers (every file
    sha-checked against backend_pins() and trigger_pins() now, their kept sha256 and the F1 manifest before anything
    is loaded)."""
    now_pins, now_trig = dict(pins()), dict(trigger_pins())
    r4 = str(GC.R4_LAYER.relative_to(GC.STORE))
    keys = (*TRIGGER_FILES, r4)
    bad = [k for k in keys if now_pins.get(k) is None or now_pins[k] != manifest_files.get(k)]
    bad += [] if now_pins.get(r4) == GC.R4_LAYER_SHA256 else [f"{r4} is not R4_LAYER_SHA256"]
    bad += [k for k, v in GC.TRIGGER_PINS_SHA256.items() if now_trig.get(k) != v or manifest_files.get(k) != v]
    if bad:
        raise HoError(f"prod trigger files differ from backend_pins() / trigger_pins() / the F1 manifest: {bad}")
    pkg = GC.REPO / "packages"
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    from ragcommon import regnal, routing  # noqa: E402,F401  (this checkout's packages/, sha-checked above)
    home = (pkg / "ragcommon").resolve()
    where = {n: Path(getattr(sys.modules.get(n), "__file__", None) or "/").resolve().parent for n in RAGCOMMON_USED}
    if any(d != home for d in where.values()):
        raise HoError(f"ragcommon resolved outside this checkout's packages/: {sorted(where.items())}")
    layer = _load("gen_confirm_prod_regnal_layer", GC.REPO / TRIGGER_FILES[1])
    trig = _load("gen_confirm_prod_regnal_trigger", GC.REPO / TRIGGER_FILES[0])
    data, lexicon = GC.R4_LAYER.read_bytes(), LEXICON.read_bytes()
    if sha256_bytes(data) != GC.R4_LAYER_SHA256 or sha256_bytes(lexicon) != GC.TRIGGER_PINS_SHA256[LEXICON_KEY]:
        raise HoError("the r4 layer or its routing lexicon changed while loading")
    lay = layer.with_lexicon(layer.parse_layer(data), routing.parse_lexicon(json.loads(lexicon)))
    return lambda q: bool(trig.trigger(q, lay.names, lay.blockers).fired)


# ---------------------------------------------------------------- step 1 and step 2
def passed_attempt(rec: Mapping[str, Any]) -> Mapping[str, Any]:
    att = S.current(rec)
    if att is None or att["step"] != S.STEP_PASSED:
        raise HoError(f"{rec['sid']} is not passed")
    return att


def recheck(state: Mapping[str, Any], plan: S.Plan, names: P.Names, paths: S.Paths, sids: Sequence[str]) -> list[str]:
    """Step 1: mech_g and transcript_g again on every passed question (ids and rule names only)."""
    out = []
    for sid in sids:
        rec = S.slot(state, sid)
        att = passed_attempt(rec)
        spec = P.slot_spec(plan.slots[sid].row, names, plan.slots[sid].qid)
        allowed = {RU.err_key(v) for v in att.get("kept_mech") or ()}
        errs = [v for v in M.errors_of(M.check_draft(att["item"], spec, names)) if RU.err_key(v.as_dict()) not in allowed]
        out += [f"{rec['qid']}: mech {v.rule}" for v in errs]
        for key in att["runs"]:
            run = state["runs"][key]
            for v in TR.check_run(Path(paths.out_root) / run["root"], run["run_id"]):
                if v.level == "error" and not RU.infra_own(v.as_dict(), run):
                    out.append(f"{rec['qid']}: {run['run_id']} {v.rule}")
    return out


END_OF = {"accept": {S.PASSED}, "revise": {S.PASSED, S.KAY_DROPPED, S.CAP_STOPPED}, "drop": {S.KAY_DROPPED},
          "keep": {S.PASSED, S.FAILED, S.OTHER_QUANTITY, S.CAP_STOPPED}, "drop_d": {S.KAY_DROPPED, S.OTHER_QUANTITY}}


def kay_problems(state: Mapping[str, Any]) -> list[str]:
    """Step 2: each of Kay's decisions against its slot's end state."""
    dec, out = K.require_applied(state)["decisions"], []
    for part, suffix in (("questions", ""), ("disputes", "_d")):
        for sid, d in dec[part].items():
            want = END_OF[d["decision"] + (suffix if d["decision"] == "drop" else "")]
            if S.slot(state, sid)["status"] not in want:
                out.append(f"{sid}: Kay's {d['decision']} but the slot is {S.slot(state, sid)['status']}")
    return out


# ---------------------------------------------------------------- step 3 and step 4
def frozen_doc(state: Mapping[str, Any], plan: S.Plan, n_target: int, fires: Fires) -> tuple[dict[str, Any], list[str]]:
    """questions_frozen.json and the sids the dynasty trigger deleted."""
    by_cause: dict[str, list[str]] = {c: [] for c in A.ATTRITION}
    by_cause["unopened"] = list(plan.order[n_target:])
    questions, fired = [], []
    for sid in plan.order[:n_target]:
        rec = S.slot(state, sid)
        if rec["status"] == S.PASSED:
            q = passed_attempt(rec)["item"]["question"]
            if fires(q):
                fired.append(sid)
                by_cause["dynasty_trigger"].append(sid)
            else:
                questions.append({"sid": sid, "question": q, "qtype": plan.slots[sid].row["qtype"]})
        elif rec["status"] in S.CLOSE_CAUSE:
            by_cause[S.CLOSE_CAUSE[rec["status"]]].append(sid)
        else:
            raise HoError(f"{sid} is {rec['status']}: not frozen, not attrited")
    index = {s["sid"]: i for i, s in enumerate(plan.pool)}
    questions.sort(key=lambda q: index[q["sid"]])
    att = {c: sorted(v, key=index.get) for c, v in by_cause.items()}
    return {"schema": A.FROZEN_SCHEMA, "n_target": n_target, "questions": questions, "attrition": att}, fired


def counts(doc: Mapping[str, Any], plan: S.Plan) -> dict[str, Any]:
    """Frozen and attrited slots by cause, and by stratum, homonym end and marker flag (§1.2); no text."""
    row = {s["sid"]: s for s in plan.pool}
    where = {q["sid"]: "frozen" for q in doc["questions"]} | {s: c for c, v in doc["attrition"].items() for s in v}
    causes = ("frozen", *A.ATTRITION)
    out = {"n": len(doc["questions"]), "by_cause": {c: sum(v == c for v in where.values()) for c in causes}}
    for flag in FLAGS:
        vals = sorted({str(row[s][flag]) for s in row})
        out[f"by_{flag}"] = {v: {c: sum(where[s] == c for s in row if str(row[s][flag]) == v) for c in causes}
                             for v in vals}
    return out


def failed_by_why(state: Mapping[str, Any], doc: Mapping[str, Any]) -> dict[str, int]:
    """The failed closes by why (state_g.FAILED_WHY): arms_g has one cause for them all."""
    whys = [S.slot(state, sid)["close"]["why"] for sid in doc["attrition"]["failed"]]
    return {w: whys.count(w) for w in S.FAILED_WHY if w in whys}


def ready(paths: S.Paths, state: Mapping[str, Any], plan: S.Plan) -> int:
    """The refusals before step 1; n_target."""
    if paths.frozen.exists():
        raise HoError(f"{paths.frozen.name} exists: a frozen file is never rewritten")
    n_target = S.kp_go(paths)["n_target"]
    rec = K.record(state, plan)
    if rec["stop"]:
        raise HoError(f"Kay's page stopped the line: {rec['sentence']}")
    if not rec["final"]:
        raise HoError(f"Kay's work is not settled (revisions pending {rec['revisions_pending']}): run_ho_g.py kay")
    if state.get("k_gold_cpu"):
        raise HoError("K-gold (CPU trace) stopped the line")
    sids = plan.planned(n_target)
    if not S.done(state, sids) or S.with_status(state, sids, S.DISPUTE):
        raise HoError(f"slots not settled: {S.summary(state, sids)['by_status']}")
    return n_target


def freeze(paths: S.Paths = S.Paths(), *, names: P.Names | None = None, fires: Fires | None = None,
           f1_check: Callable[[S.Paths], list[str]] = R.f1_problems) -> dict[str, Any]:
    """F2 steps 1–4; questions_frozen.json written once."""
    with S.locked(paths):
        plan = S.load_plan(paths)
        f1_bad = f1_check(paths)
        if f1_bad:
            raise HoError(f"F1-frozen files changed: {f1_bad[:5]}")
        state = S.load_state(paths, plan)
        n_target = ready(paths, state, plan)
        names = names or P.load_names(paths.names)
        passed = S.with_status(state, plan.planned(n_target), S.PASSED)
        bad = recheck(state, plan, names, paths, passed) + kay_problems(state)
        if bad:
            raise HoError(f"F2 refused ({len(bad)}): {bad[:8]}{' …' if len(bad) > 8 else ''}")
        fires = fires or prod_trigger(read_json(paths.f1_manifest)["files"])
        doc, fired = frozen_doc(state, plan, n_target, fires)
        problems = A.frozen_problems(doc, list(plan.pool), list(plan.order))
        if problems:
            raise HoError(f"questions_frozen.json would break its contract: {problems}")
        write_json(paths.frozen, doc)
        sha = GC.sha256_file(paths.frozen)
        out = {"schema": "gen_confirm.freeze.v1", "t": now(), "questions_frozen_sha256": sha, "n_target": n_target,
               "dynasty_trigger": fired, "attrition": doc["attrition"],
               "counts": {**counts(doc, plan), "failed_by_why": failed_by_why(state, doc)},
               "kay": {k: K.record(state, plan)[k] for k in ("n_sampled", "n_dropped", "n_disputes")}}
        write_json(paths.ho_root / FREEZE_FILE, out)
        return out


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description="F2 第 1–4 步：questions_frozen.json（只寫一次）").parse_args(argv)
    out = freeze()
    print(f"freeze_g.py: questions_frozen.json sha256 {out['questions_frozen_sha256']}; n {out['counts']['n']}; "
          f"by cause {out['counts']['by_cause']}; by stratum {out['counts']['by_stratum']}; "
          f"homonym {out['counts']['by_homonym']}; marker {out['counts']['by_marker_required']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HoError, OSError, ValueError) as err:
        print(f"freeze_g.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
