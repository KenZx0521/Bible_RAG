"""State of the blind question writing (HO) of the GEN confirmation set (prereg §2.3, §3.1, §3.6, §3.7, §8.1-7..9).

Slot plan. Store order.json (order_g, drawn once after F1) is read only when its ``f1_manifest_sha256`` is the sha256 of
the F1 manifest now and pool.json hashes as POOL_SHA256 (prereg §2.3); the order must be a permutation of the pool.
Position p (1-based) is question id ``Q{p:02d}``; pilot = order[:PILOT] (§8.1-7), main = order[PILOT:n_target] with
n_target from kp.json (K-P). Layer ids, sids and golds stay in the store: no prompt ever gets them (prompts_g).

Per slot: a list of attempts (≤ MAX_ATTEMPTS counted; an attempt ended by an infrastructure failure is not
counted, §2.3) and at most one close. An attempt walks the §3.1 steps

    draft → mech_fix (source mech) → audit → audit_fix (source audit) → … → passed | ended | dispute

with one fix round per source per attempt (FIX_SOURCES, MAX_FIX_ROUNDS; a round is counted when it is requested)
and kay_fix for Kay's 「修改」 on a passed attempt (§3.7: no attempt used). Slot status is derived from the last
attempt and the close: unopened (no attempt), open (the last attempt ended, attempts left: the next job is a new
draft), drafting, pending_audit, needs_fix (by source), passed, dispute (a closed slot waiting for Kay's page), and the
closes failed (MAX_ATTEMPTS counted attempts ended, or a disputed attempt Kay kept ended without passing),
cap_stopped (the hard cap stopped drafting before the slot passed, §8.1-8), kay_dropped and other_quantity (§3.6
row 3 without K-gold). The closes map onto arms_g.ATTRITION (CLOSE_CAUSE); a failed close also records why
(FAILED_WHY: attempts | post_kay | kept_dispute | late_dispute), since arms_g has one cause for all of them. A
dispute closes the slot to new attempts: Kay's page is drawn once after every slot is done, so nothing is drafted
after it; Kay's 「留」 resumes only the disputed attempt (``post_kay``: its later jobs run under HO_ROOT/kay, and any
new dispute there closes the slot).

Infrastructure stops (prereg §2.3, §3.1, §8.1: only logged infrastructure fixes): a job that used its
MAX_INFRA_RETRIES reruns, or a CliChanged, records a stop (``infra_stop``: the jobs, and the sha256 of the 執行紀錄
lines at that moment) and the runner stops. While a stop is open no HO job starts: an infra stop is cleared by
``--infra-fix LINE`` (a new line of the log), a CLI stop by ``run_ho_g.py repin`` (a re-probe, logged). So no job
gets more than 1 + MAX_INFRA_RETRIES runs per logged fix.

Every job in flight is recorded on its slot (``inflight``) and saved before the launch, so a crash leaves a trace:
``recover`` turns a stale one into an 「interrupted」 job event and the step is planned again (its runs stay in the
ledger at their cost or cap). State is one JSON file, HO_ROOT/state.json, written atomically (g_common.write_json)
by the process that holds HO_ROOT/state.lock (``locked``: a second runner is refused). Functions are pure where they
can be: a state in, a new state out (deep copies). Nothing here launches an agent or calls gencard.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import g_common as GC
from hog_common import HoError, now, read_json, write_json

SCHEMA = "gen_confirm.ho_state.v1"
G1_SCHEMA = "gen_confirm.g1.v1"
ROOTS = GC.HO_SUB_ROOTS                              # run sub-roots of HO_ROOT (the single ledger counts them all)
UNOPENED, OPEN, DRAFTING, PENDING_AUDIT, NEEDS_FIX = "unopened", "open", "drafting", "pending_audit", "needs_fix"
PASSED, FAILED, DISPUTE = "passed", "failed", "dispute"
CAP_STOPPED, KAY_DROPPED, OTHER_QUANTITY = "cap_stopped", "kay_dropped", "other_quantity"
STATUSES = (UNOPENED, OPEN, DRAFTING, PENDING_AUDIT, NEEDS_FIX, PASSED, DISPUTE, FAILED, CAP_STOPPED, KAY_DROPPED,
            OTHER_QUANTITY)
NEEDS_DRAFT = frozenset({UNOPENED, OPEN})
LIVE = frozenset({DRAFTING, PENDING_AUDIT, NEEDS_FIX})
DONE = frozenset({PASSED, DISPUTE, FAILED, CAP_STOPPED, KAY_DROPPED, OTHER_QUANTITY})
CLOSE_CAUSE = {FAILED: "failed", CAP_STOPPED: "cap_stopped", KAY_DROPPED: "kay", OTHER_QUANTITY: "other_quantity"}
DRAFT, MECH_FIX, AUDIT, AUDIT_FIX, KAY_FIX = "draft", "mech_fix", "audit", "audit_fix", "kay_fix"
STEP_PASSED, ENDED, STEP_DISPUTE = "passed", "ended", "dispute"
FIX_STEP = {"mech": MECH_FIX, "audit": AUDIT_FIX, "kay": KAY_FIX}
STEP_STATUS = {DRAFT: DRAFTING, AUDIT: PENDING_AUDIT, MECH_FIX: NEEDS_FIX, AUDIT_FIX: NEEDS_FIX, KAY_FIX: NEEDS_FIX,
               STEP_PASSED: PASSED, STEP_DISPUTE: DISPUTE}
FAILED_WHY = ("attempts", "post_kay", "kept_dispute", "late_dispute")
STOP_KINDS = ("infra", "cli_changed")


@dataclass(frozen=True)
class Paths:
    """Every store file the HO track reads or writes, laid out as under g_common.OUT_ROOT (tests use a tmp root)."""
    out_root: Path = GC.OUT_ROOT
    pool_sha256: str = GC.POOL_SHA256

    def _at(self, p: Path) -> Path:
        return Path(self.out_root) / p.relative_to(GC.OUT_ROOT)

    @property
    def pool(self) -> Path:
        return self._at(GC.POOL)

    @property
    def order(self) -> Path:
        return self._at(GC.ORDER)

    @property
    def f1_manifest(self) -> Path:
        return self._at(GC.F1_MANIFEST)

    @property
    def f1a(self) -> Path:
        return self._at(GC.F1A_LOG)

    @property
    def names(self) -> Path:
        return self._at(GC.GEN_NAMES)

    @property
    def cli_pin(self) -> Path:
        return self._at(GC.CLI_PIN)

    @property
    def g1(self) -> Path:
        return self._at(GC.G1_RESULT)

    @property
    def frozen(self) -> Path:
        return self._at(GC.QUESTIONS_FROZEN)

    @property
    def ho_root(self) -> Path:
        return self._at(GC.HO_ROOT)

    def root(self, name: str) -> Path:
        if name not in ROOTS:
            raise HoError(f"run root {name!r} is not one of {ROOTS}")
        return self.ho_root / name

    @property
    def state(self) -> Path:
        return self.ho_root / GC.HO_STATE

    @property
    def kp(self) -> Path:
        return self.ho_root / GC.KP_FILE

    @property
    def kay(self) -> Path:
        return self.ho_root / GC.KAY_FILE

    @property
    def kay_dir(self) -> Path:
        return self.root("kay")

    @property
    def repins(self) -> Path:
        return self.ho_root / GC.REPINS_FILE


# ---------------------------------------------------------------- the slot plan (order.json)
@dataclass(frozen=True)
class SlotPlan:
    sid: str
    position: int                                   # 1-based place in the writing order
    qid: str                                        # Q01 … by position
    phase: str                                      # pilot | main
    row: Mapping[str, Any]                          # the pool.json slot


@dataclass(frozen=True)
class Plan:
    order: tuple[str, ...]
    slots: Mapping[str, SlotPlan]
    pool: tuple[Mapping[str, Any], ...]
    order_sha256: str
    pool_sha256: str
    f1_manifest_sha256: str

    @property
    def pilot(self) -> tuple[str, ...]:
        return self.order[:GC.PILOT]

    def main(self, n_target: int) -> tuple[str, ...]:
        return self.order[GC.PILOT:n_target]

    def planned(self, n_target: int | None) -> tuple[str, ...]:
        """The slots that may be written: the pilot before K-P, order[:n_target] after it."""
        return self.pilot if n_target is None else self.order[:n_target]


def qid_of(position: int) -> str:
    return f"Q{position:02d}"


def load_plan(paths: Paths = Paths()) -> Plan:
    """order.json and pool.json, refused unless order.json was drawn from the F1 manifest now and pool.json is pinned."""
    for p in (paths.f1_manifest, paths.order, paths.pool):
        if not p.is_file():
            raise HoError(f"{p.name} missing (prereg §2.3: F1, then order.json)")
    man_sha, pool_sha, order_sha = (GC.sha256_file(p) for p in (paths.f1_manifest, paths.pool, paths.order))
    doc = read_json(paths.order)
    if doc.get("f1_manifest_sha256") != man_sha:
        raise HoError("order.json was not drawn from the F1 manifest now (its f1_manifest_sha256 differs)")
    if pool_sha != paths.pool_sha256 or doc.get("pool_sha256") != paths.pool_sha256:
        raise HoError(f"pool.json (or order.json's pool_sha256) is not the pinned {paths.pool_sha256[:12]}")
    if doc.get("pilot") != GC.PILOT:
        raise HoError(f"order.json pilot {doc.get('pilot')!r} is not {GC.PILOT}")
    pool = tuple(read_json(paths.pool)["pool"])
    order = tuple(doc.get("order") or ())
    by = {s["sid"]: s for s in pool}
    if len(order) != len(set(order)) or set(order) != set(by) or len(order) < GC.PILOT:
        raise HoError("order.json is not a permutation of the pool's sids")
    slots = {sid: SlotPlan(sid, i, qid_of(i), "pilot" if i <= GC.PILOT else "main", by[sid])
             for i, sid in enumerate(order, 1)}
    return Plan(order, slots, pool, order_sha, pool_sha, man_sha)


# ---------------------------------------------------------------- the state file
def _slot_record(sp: SlotPlan) -> dict[str, Any]:
    return {"sid": sp.sid, "qid": sp.qid, "position": sp.position, "phase": sp.phase, "status": UNOPENED,
            "attempts": [], "close": None, "dispute": None, "inflight": None, "events": []}


def new_state(plan: Plan) -> dict[str, Any]:
    return {"schema": SCHEMA, "created": now(), "plan": {"order_sha256": plan.order_sha256,
                                                         "pool_sha256": plan.pool_sha256,
                                                         "f1_manifest_sha256": plan.f1_manifest_sha256},
            "slots": {sid: _slot_record(sp) for sid, sp in plan.slots.items()}, "runs": {},
            "drafting_stopped": False, "cap_stop": None, "k_gold_cpu": [], "kay": None, "infra_stops": [], "log": []}


def load_state(paths: Paths, plan: Plan) -> dict[str, Any]:
    """state.json (a new state when absent), refused when it belongs to another order, pool or manifest."""
    if not paths.state.is_file():
        return new_state(plan)
    state = read_json(paths.state)
    if state.get("schema") != SCHEMA:
        raise HoError(f"state.json schema {state.get('schema')!r} is not {SCHEMA}")
    want = new_state(plan)["plan"]
    if state.get("plan") != want or set(state["slots"]) != set(plan.slots):
        raise HoError("state.json belongs to another order.json, pool.json or F1 manifest")
    return state


def save_state(paths: Paths, state: Mapping[str, Any]) -> Path:
    return write_json(paths.state, state)


@contextlib.contextmanager
def locked(paths: Paths) -> Iterator[None]:
    """The HO runner's lock (HO_ROOT/state.lock, flock): one runner at a time; a second one is refused at once."""
    path = GC.writable(paths.ho_root / GC.HO_LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o664)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HoError("another HO runner holds state.lock") from None
        yield
    finally:
        os.close(fd)


# ---------------------------------------------------------------- queries
def slot(state: Mapping[str, Any], sid: str) -> dict[str, Any]:
    try:
        return state["slots"][sid]
    except KeyError:
        raise HoError(f"no slot {sid!r}") from None


def current(rec: Mapping[str, Any]) -> dict[str, Any] | None:
    return rec["attempts"][-1] if rec["attempts"] else None


def derive(rec: Mapping[str, Any]) -> str:
    if rec.get("close"):
        return rec["close"]["status"]
    att = current(rec)
    if att is None:
        return UNOPENED
    return OPEN if att["step"] == ENDED else STEP_STATUS[att["step"]]


def attempts_used(rec: Mapping[str, Any]) -> int:
    return sum(bool(a["counted"]) for a in rec["attempts"])


def statuses(state: Mapping[str, Any], sids: Sequence[str]) -> dict[str, str]:
    return {sid: slot(state, sid)["status"] for sid in sids}


def with_status(state: Mapping[str, Any], sids: Sequence[str], wanted) -> list[str]:
    want = frozenset([wanted] if isinstance(wanted, str) else wanted)
    return [sid for sid in sids if slot(state, sid)["status"] in want]


def done(state: Mapping[str, Any], sids: Sequence[str]) -> bool:
    """Every slot passed, closed or in dispute, and no job in flight."""
    return all(slot(state, s)["status"] in DONE and not slot(state, s)["inflight"] for s in sids)


def opened(rec: Mapping[str, Any]) -> bool:
    return bool(rec["attempts"])


def summary(state: Mapping[str, Any], sids: Sequence[str]) -> dict[str, Any]:
    """Counts only (never question text)."""
    st = statuses(state, sids)
    return {"slots": len(sids), "by_status": {s: sum(v == s for v in st.values()) for s in STATUSES},
            "opened": sum(opened(slot(state, s)) for s in sids),
            "attempts_counted": sum(attempts_used(slot(state, s)) for s in sids),
            "inflight": sum(bool(slot(state, s)["inflight"]) for s in sids), "runs": len(state["runs"]),
            "drafting_stopped": bool(state.get("drafting_stopped")), "k_gold_cpu": len(state.get("k_gold_cpu") or ()),
            "infra_stop_open": open_stop(state) is not None}


# ---------------------------------------------------------------- transitions (state in, new state out)
def _copy(state: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(state))


def _settle(rec: dict[str, Any]) -> None:
    rec["status"] = derive(rec)


def _event(rec: dict[str, Any], what: str, note: str = "") -> None:
    att = current(rec)
    (att["events"] if att is not None else rec["events"]).append({"t": now(), "what": what, "note": note})


def new_attempt(root: str) -> dict[str, Any]:
    return {"n": 0, "counted": True, "step": DRAFT, "root": root, "item": None, "audited": None,
            "fixes": {s: 0 for s in GC.FIX_SOURCES}, "fix_request": None, "audit_broke": None, "post_kay": False,
            "kay_revision": None, "mech": [], "kept_mech": [], "audits": [], "decisions": [], "fix_log": [],
            "gold_trace": None, "runs": [], "jobs": [], "end": None, "events": []}


def open_attempt(state: Mapping[str, Any], sid: str, root: str) -> dict[str, Any]:
    """A new attempt (step draft) when the slot needs a draft and has an attempt left."""
    new = _copy(state)
    rec = slot(new, sid)
    if rec["status"] not in NEEDS_DRAFT or attempts_used(rec) >= GC.MAX_ATTEMPTS:
        raise HoError(f"{sid}: no new attempt (status {rec['status']}, {attempts_used(rec)} counted)")
    att = new_attempt(root)
    att["n"] = len(rec["attempts"]) + 1
    rec["attempts"].append(att)
    _event(rec, "attempt", f"第 {att['n']} 次嘗試")
    _settle(rec)
    return new


def update_attempt(state: Mapping[str, Any], sid: str, step: str | None = None, note: str = "",
                   append: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    new = _copy(state)
    rec = slot(new, sid)
    att = current(rec)
    if att is None:
        raise HoError(f"{sid}: no attempt to update")
    att.update(copy.deepcopy(fields))
    for key, value in (append or {}).items():
        att[key].append(copy.deepcopy(value))
    if step is not None:
        att["step"] = step
        _event(rec, step, note)
    _settle(rec)
    return new


def close(state: Mapping[str, Any], sid: str, status: str, note: str, why: str | None = None) -> dict[str, Any]:
    """The slot's close; a failed one names why (FAILED_WHY), no other close takes a why."""
    if status not in CLOSE_CAUSE:
        raise HoError(f"{status!r} is not a close ({sorted(CLOSE_CAUSE)})")
    if (status == FAILED) != (why in FAILED_WHY):
        raise HoError(f"close {status} with why {why!r} (a failed close needs one of {FAILED_WHY})")
    new = _copy(state)
    rec = slot(new, sid)
    rec["close"] = {"status": status, "cause": CLOSE_CAUSE[status], "why": why, "note": note, "t": now()}
    rec["events"].append({"t": now(), "what": f"close:{status}", "note": note})
    _settle(rec)
    return new


def end_attempt(state: Mapping[str, Any], sid: str, why: str, counted: bool = True) -> dict[str, Any]:
    """The attempt ends; the slot closes as failed after MAX_ATTEMPTS counted ones or after Kay's page (post_kay),
    and as cap_stopped when drafting has stopped (it would need a new draft)."""
    new = update_attempt(state, sid, ENDED, why, counted=counted, end={"why": why, "counted": counted, "t": now()})
    rec = slot(new, sid)
    if current(rec)["post_kay"]:
        return close(new, sid, FAILED, f"Kay 頁之後這次嘗試結束：{why}", "post_kay")
    if attempts_used(rec) >= GC.MAX_ATTEMPTS:
        return close(new, sid, FAILED, f"{GC.MAX_ATTEMPTS} 次嘗試都沒通過", "attempts")
    if new.get("drafting_stopped"):
        return close(new, sid, CAP_STOPPED, "硬上限停筆後不再出新稿（§8.1-8）")
    return new


def to_dispute(state: Mapping[str, Any], sid: str, dispute: Mapping[str, Any]) -> dict[str, Any]:
    """The slot closes to new attempts and waits for Kay's page (prereg §3.4, §3.6 row 3)."""
    new = update_attempt(state, sid, STEP_DISPUTE, f"爭議：{dispute['kind']}")
    rec = slot(new, sid)
    rec["dispute"] = {**copy.deepcopy(dict(dispute)), "attempt": current(rec)["n"], "t": now(), "decision": None}
    return new


def begin_job(state: Mapping[str, Any], sid: str, job: Mapping[str, Any]) -> dict[str, Any]:
    new = _copy(state)
    rec = slot(new, sid)
    if rec["inflight"]:
        raise HoError(f"{sid}: a job is already in flight")
    rec["inflight"] = {**copy.deepcopy(dict(job)), "t": now()}
    return new


def end_job(state: Mapping[str, Any], sid: str, job: Mapping[str, Any]) -> dict[str, Any]:
    """Clear the slot's in-flight mark and log the job on its attempt (or the slot when no attempt opened)."""
    new = _copy(state)
    rec = slot(new, sid)
    rec["inflight"] = None
    att = current(rec)
    (att["jobs"] if att is not None and job.get("attempt") == att["n"] else rec["events"]).append(
        {**copy.deepcopy(dict(job)), "t": now()})
    return new


def recover(state: Mapping[str, Any]) -> dict[str, Any]:
    """A job left in flight by a crash: logged as interrupted, its step planned again."""
    new = _copy(state)
    for rec in new["slots"].values():
        if rec["inflight"]:
            rec["events"].append({"t": now(), "what": "interrupted", "note": f"未提交的 job：{rec['inflight']}"})
            rec["inflight"] = None
    return new


def record_runs(state: Mapping[str, Any], sid: str, runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run records (state["runs"][key]) and their keys on the slot's current attempt."""
    new = _copy(state)
    att = current(slot(new, sid))
    for r in runs:
        new["runs"][r["key"]] = copy.deepcopy(dict(r))
        att["runs"].append(r["key"])
    return new


def needs_draft(state: Mapping[str, Any], sid: str) -> bool:
    rec = slot(state, sid)
    return rec["status"] in NEEDS_DRAFT | {DRAFTING}


def stop_drafting(state: Mapping[str, Any], sids: Sequence[str], spent: float, note: str) -> dict[str, Any]:
    """§8.1-8 hard cap: no new draft; every slot of `sids` whose next job is a draft is cap_stopped (attrition)."""
    new = _copy(state)
    if not new.get("drafting_stopped"):
        new["drafting_stopped"] = True
        new["cap_stop"] = {"t": now(), "spent_usd": round(spent, 6), "limit_usd": GC.USD_CAP - GC.START_MARGIN_USD,
                           "draft_cap_usd": GC.JOB_CAP_USD["draft"], "note": note}
    for sid in sids:
        if needs_draft(new, sid) and not slot(new, sid)["inflight"]:
            new = close(new, sid, CAP_STOPPED, "硬上限：一份出題 job 都放不下，停筆（§8.1-8）")
    return new


def log(state: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    new = _copy(state)
    new["log"].append({"t": now(), **copy.deepcopy(dict(entry))})
    return new


def open_stop(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The infrastructure stop no logged fix has cleared yet (at most one: no job starts while it is open)."""
    return next((s for s in state.get("infra_stops") or () if not s.get("cleared")), None)


def infra_stop(state: Mapping[str, Any], kind: str, jobs: Sequence[Mapping[str, Any]], note: str,
               log_lines_sha256: Sequence[str]) -> dict[str, Any]:
    """Record a stop (kept as it is when one is open already)."""
    if kind not in STOP_KINDS:
        raise HoError(f"stop kind {kind!r} is not one of {STOP_KINDS}")
    new = _copy(state)
    if open_stop(new) is None:
        new.setdefault("infra_stops", []).append({"kind": kind, "t": now(), "jobs": copy.deepcopy(list(jobs)),
                                                  "note": note, "log_lines_sha256": sorted(log_lines_sha256),
                                                  "cleared": None})
    return new


def clear_stop(state: Mapping[str, Any], by: str, anchor: str) -> dict[str, Any]:
    new = _copy(state)
    stop = open_stop(new)
    if stop is None:
        raise HoError("no open infrastructure stop")
    stop["cleared"] = {"by": by, "anchor": anchor.strip(), "t": now()}
    return new


def stop_anchors(state: Mapping[str, Any]) -> list[str]:
    """The log lines that cleared earlier stops (an anchor stands for one fix only)."""
    return [s["cleared"]["anchor"] for s in state.get("infra_stops") or () if s.get("cleared")]


# ---------------------------------------------------------------- the store records the runner gates read
def g1_problems(doc: Any, f1a_sha256: str | None) -> list[str]:
    """qset/g1.json (the cross-track contract): schema, integer counts, pass true (g1 ≥ 0.70 and the GT zero-trigger
    nail), and the F1a pins it was judged under."""
    if not isinstance(doc, Mapping) or doc.get("schema") != G1_SCHEMA:
        return [f"g1.json is not {G1_SCHEMA}"]
    out = [f"g1.json {k} is not a count" for k in ("R_card", "R_wrong", "n_v")
           if not isinstance(doc.get(k), int) or isinstance(doc.get(k), bool) or doc[k] < 0]
    if not out and doc["n_v"] == 0:
        out.append("g1.json n_v is 0")
    if doc.get("pass") is not True or doc.get("gt_zero_trigger") is not True:
        out.append("G1 did not pass (g1.json pass is not true): no question is written (prereg §5.6)")
    if not isinstance(doc.get("g1"), (int, float)) or doc["g1"] < 0.70:
        out.append("g1.json g1 is below 0.70")
    if f1a_sha256 is None or doc.get("f1a_pins_sha256") != f1a_sha256:
        out.append("g1.json was judged under other F1a pins (f1a_pins_sha256)")
    return out


def read_g1(paths: Paths) -> dict[str, Any]:
    if not paths.g1.is_file():
        raise HoError("qset/g1.json missing: G1 (P2) comes before any question is written (prereg §8.1-5)")
    doc = read_json(paths.g1)
    bad = g1_problems(doc, GC.sha256_file(paths.f1a) if paths.f1a.is_file() else None)
    if bad:
        raise HoError("; ".join(bad))
    return doc


def read_kp(paths: Paths) -> dict[str, Any] | None:
    return read_json(paths.kp) if paths.kp.is_file() else None


def kp_go(paths: Paths) -> dict[str, Any]:
    """kp.json, when K-P let the line go on (main writing, Kay's page and F2 need it)."""
    doc = read_kp(paths)
    if doc is None:
        raise HoError("kp.json missing: run `run_ho_g.py kp` after the pilot (prereg §8.1-7)")
    if doc.get("go") is not True:
        raise HoError(f"K-P stopped the line: {doc.get('sentence')}")
    return doc
