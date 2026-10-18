"""Question-writing state (confirm_A.md §2.4, §3, §8): slot plan, records in commit order, ledger, pilot draw.

One JSON file per run root (<root>/state.json). Functions are pure where they can be: they take a
state dict and return a new one. Slot plan (§2.4, F1-frozen in segments.json): every segment's
`slots` list, numbered from 1 (key "I1_1"); slot type S1a_rev is an S1a question whose direction
(or |k|) differs from the segment's passed slot-1 question. A slot has up to MAX_ATTEMPTS drafting
attempts (an attempt that ended in an infrastructure failure does not count); it is done when a
question passed, or when it has no live draft and no attempt left (or was cancelled by the §8.2
re-estimate, or drafting stopped at the hard cap, stop_for_cap). Rounds plan one slot per segment, in segment order; in the main phase a segment's
slots go in slot order. The pilot phase only plans the 12 pilot slots of segments.json `pilot`
(§3, re-derived with segments.pilot_plan and checked).

Ledger (§8.2): every run of <root> and <root>/probe counts its result event's total_cost_usd; a run
with no result counts the cap it was started with (<root>/reserve/<run_id>.json, written before
the launch), so an unfinished or crashed run is never cheaper than its cap.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hoa_common import PASSED_FILE, C, BudgetRefused, HoError, now, read_json, write_json

import segments as SG  # noqa: E402

SCHEMA = "a_confirm_ho_state.v1"
STATE_FILE = "state.json"
ABANDONED, PENDING, PASSED, NEEDS_FIX, DROPPED = "abandoned", "pending_audit", "passed", "needs_fix", "dropped"
STATUSES = (ABANDONED, PENDING, PASSED, NEEDS_FIX, DROPPED)
UNRESOLVED = frozenset({PENDING, NEEDS_FIX})
LIVE = frozenset({PENDING, PASSED, NEEDS_FIX})
FIX_SOURCES = ("mech", "audit", "kay")
LEDGER_DIRS = ("", "probe")


@dataclass(frozen=True)
class Slot:
    segment: str
    number: int                 # 1-based position in the segment's slot list
    slot_type: str              # S1a | S1a_rev | S1b | S1c | S4
    pilot: bool                 # one of the 12 pilot slots (§3)

    @property
    def key(self) -> str:
        return f"{self.segment}_{self.number}"

    @property
    def qtype(self) -> str:
        return "S1a" if self.slot_type == "S1a_rev" else self.slot_type


@dataclass(frozen=True)
class Planned:
    seq: int
    round: int
    qid: str
    slot: Slot
    attempt: int
    phase: str                  # pilot | main


# ------------------------------------------------------------------ plan (segments.json, F1)

def load_segments(path: Path = C.SEGMENTS) -> dict[str, Any]:
    doc = read_json(path)
    again = SG.pilot_plan(doc["segments"])
    if again != doc["pilot"]:
        raise HoError("segments.json pilot differs from segments.pilot_plan (§3 draw)")
    return doc


def slot_plan(doc: Mapping[str, Any]) -> tuple[Slot, ...]:
    pilot = {(p["segment"], p["slot"]) for p in doc["pilot"]}
    return tuple(Slot(s["id"], i, t, (s["id"], i) in pilot) for s in doc["segments"]
                 for i, t in enumerate(s["slots"], 1))


def segment_rows(doc: Mapping[str, Any]) -> dict[str, dict]:
    return {s["id"]: s for s in doc["segments"]}


# ------------------------------------------------------------------ state file

def new_state() -> dict[str, Any]:
    return {"schema": SCHEMA, "created_utc": now(), "records": [], "runs": {}, "kay": None, "reestimate": None,
            "cancelled": [], "slot_limit": {}, "drafting_stopped": False, "meta_log": []}


def load_state(root: Path) -> dict[str, Any]:
    path = Path(root) / STATE_FILE
    if not path.is_file():
        return new_state()
    state = read_json(path)
    if state.get("schema") != SCHEMA:
        raise HoError(f"{path.name}: schema {state.get('schema')!r} is not {SCHEMA}")
    seqs = [r["seq"] for r in state["records"]]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        raise HoError(f"{path.name}: records are not in strict commit order")
    return state


def save_state(root: Path, state: Mapping[str, Any]) -> Path:
    return write_json(Path(root) / STATE_FILE, state)


# ------------------------------------------------------------------ queries

def records(state: Mapping[str, Any], statuses: Iterable[str] | None = None, slot: str | None = None,
            segment: str | None = None) -> list[dict[str, Any]]:
    wanted = None if statuses is None else frozenset(statuses)
    return [r for r in state["records"] if (wanted is None or r["status"] in wanted)
            and (slot is None or r["slot"] == slot) and (segment is None or r["segment"] == segment)]


def record(state: Mapping[str, Any], qid: str) -> dict[str, Any]:
    for r in state["records"]:
        if r["id"] == qid:
            return r
    raise HoError(f"no record {qid!r}")


def attempts_used(state: Mapping[str, Any], key: str) -> int:
    return sum(not r.get("infra_failure") for r in records(state, slot=key))


def slot_limit(state: Mapping[str, Any], key: str) -> int:
    return int(state["slot_limit"].get(key, C.MAX_ATTEMPTS))


def passed_record(state: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    return next(iter(records(state, (PASSED,), slot=key)), None)


def slot_done(state: Mapping[str, Any], slot: Slot) -> bool:
    if passed_record(state, slot.key):
        return True
    if records(state, UNRESOLVED, slot=slot.key):
        return False
    return slot.key in state["cancelled"] or attempts_used(state, slot.key) >= slot_limit(state, slot.key)


def phase_slots(slots: Sequence[Slot], phase: str) -> list[Slot]:
    if phase not in ("pilot", "main"):
        raise HoError(f"unknown phase {phase!r}")
    return [s for s in slots if s.pilot] if phase == "pilot" else list(slots)


def is_complete(state: Mapping[str, Any], slots: Sequence[Slot], phase: str) -> bool:
    """Every slot of the phase done and no draft waiting (the main phase also ends when drafting stopped)."""
    if records(state, UNRESOLVED):
        return False
    if phase == "main" and state.get("drafting_stopped"):
        return True
    return all(slot_done(state, s) for s in phase_slots(slots, phase))


def pilot_finished(state: Mapping[str, Any], slots: Sequence[Slot]) -> bool:
    """The pilot phase ended: recorded by the re-estimate (which needs it), or complete right now."""
    return bool(state.get("reestimate")) or is_complete(state, slots, "pilot")


def segment_passed(state: Mapping[str, Any], segment: str, exclude: str | None = None) -> list[dict[str, Any]]:
    """Items of this segment's passed questions (本段已出題), in commit order."""
    return [r["item"] for r in records(state, (PASSED,), segment=segment) if r["id"] != exclude]


def reverse_reference(state: Mapping[str, Any], slot: Slot) -> dict[str, Any] | None:
    """For an S1a_rev slot: the segment's passed slot-1 S1a item (None when slot 1 stayed empty)."""
    if slot.slot_type != "S1a_rev":
        return None
    rec = passed_record(state, f"{slot.segment}_1")
    return rec["item"] if rec else None


def fixes_from(rec: Mapping[str, Any], source: str) -> int:
    return sum(f.get("source") == source for f in rec.get("fixes") or ())


# ------------------------------------------------------------------ planning

def _qid(slot: Slot, n: int) -> str:
    return f"Q{slot.segment}s{slot.number}a{n}"


def plan_round(state: Mapping[str, Any], slots: Sequence[Slot], phase: str) -> list[Planned]:
    """One open slot per segment, in segment order; refuses while drafts wait for audit or fix."""
    waiting = [r["id"] for r in records(state, UNRESOLVED)]
    if waiting:
        raise HoError(f"audit or fix these drafts before the next round: {waiting}")
    if phase == "main" and state.get("drafting_stopped"):
        return []
    seq = state["records"][-1]["seq"] + 1 if state["records"] else 1
    rnd = max((r["round"] for r in state["records"]), default=0) + 1
    out, seen = [], set()
    for s in phase_slots(slots, phase):
        if s.segment in seen or slot_done(state, s):
            continue
        seen.add(s.segment)
        out.append(Planned(seq, rnd, _qid(s, len(records(state, slot=s.key)) + 1), s,
                           attempts_used(state, s.key) + 1, phase))
        seq += 1
    return out


# ------------------------------------------------------------------ updates (new state)

def add_record(state: Mapping[str, Any], p: Planned, status: str, item: dict | None, note: str = "",
               **fields: Any) -> dict[str, Any]:
    if status not in STATUSES:
        raise HoError(f"unknown status {status!r}")
    if state["records"] and p.seq <= state["records"][-1]["seq"]:
        raise HoError(f"{p.qid} (seq {p.seq}) is out of commit order")
    rec = {"seq": p.seq, "round": p.round, "id": p.qid, "segment": p.slot.segment, "slot": p.slot.key,
           "slot_number": p.slot.number, "slot_type": p.slot.slot_type, "qtype": p.slot.qtype,
           "pilot": p.phase == "pilot", "attempt": p.attempt, "status": status, "item": item, "mech": [],
           "hidden": None, "audits": [], "fixes": [], "runs": [], "transcript": [], "fix_request": None,
           "events": [{"at": now(), "status": status, "note": note}]}
    rec.update(copy.deepcopy(fields))
    new = copy.deepcopy(dict(state))
    new["records"].append(rec)
    return new


def update_record(state: Mapping[str, Any], qid: str, status: str | None = None, note: str = "",
                  append: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    if status is not None and status not in STATUSES:
        raise HoError(f"unknown status {status!r}")
    new = copy.deepcopy(dict(state))
    rec = record(new, qid)
    rec.update(copy.deepcopy(fields))
    for key, value in (append or {}).items():
        rec[key].append(copy.deepcopy(value))
    if status is not None:
        rec["status"] = status
        rec["events"].append({"at": now(), "status": status, "note": note})
    return new


# ------------------------------------------------------------------ outputs

def passed_items(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """questions_passed.json rows: §2.8 item + pilot + slot (never hidden flags), in commit order."""
    return [{**r["item"], "id": r["id"], "pilot": bool(r["pilot"]), "slot": r["slot"]}
            for r in records(state, (PASSED,))]


def write_passed(root: Path, state: Mapping[str, Any]) -> Path:
    rows = passed_items(state)
    return write_json(Path(root) / PASSED_FILE, {"n": len(rows), "questions": rows})


def summary(state: Mapping[str, Any], slots: Sequence[Slot]) -> dict[str, Any]:
    done = [s for s in slots if slot_done(state, s)]
    return {"by_status": {st: len(records(state, (st,))) for st in STATUSES},
            "slots": len(slots), "slots_done": len(done),
            "slots_passed": sum(bool(passed_record(state, s.key)) for s in slots),
            "segments_with_passed": len({r["segment"] for r in records(state, (PASSED,))}),
            "pilot_complete": is_complete(state, slots, "pilot"), "main_complete": is_complete(state, slots, "main"),
            "cancelled": list(state["cancelled"]), "drafting_stopped": state.get("drafting_stopped", False),
            "cap_stop": bool(state.get("cap_stop")),
            "transcript_breaches": sum(any(v.get("level") == "error" for v in r.get("transcript") or ())
                                       for r in state["records"])}


# ------------------------------------------------------------------ ledger (§8.2)

def _run_cost(d: Path, run_id: str) -> tuple[float, str]:
    t = d / "transcripts" / f"{run_id}.jsonl"
    if t.is_file():
        for line in reversed(t.read_text(encoding="utf-8").splitlines()):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "result" and isinstance(e.get("total_cost_usd"), (int, float)):
                return float(e["total_cost_usd"]), "result"
    for p in (d / "reserve" / f"{run_id}.json", d / "prompts" / f"{run_id}.json"):
        if p.is_file() and isinstance(read_json(p).get("budget_usd"), (int, float)):
            return float(read_json(p)["budget_usd"]), "cap_assumed"
    return max(C.JOB_CAP_USD.values()), "cap_assumed"


def ledger(root: Path) -> dict[str, Any]:
    runs = {}
    for sub in LEDGER_DIRS:
        d = Path(root) / sub if sub else Path(root)
        ids = {p.stem for p in (d / "transcripts").glob("*.jsonl")} | {p.stem for p in (d / "reserve").glob("*.json")}
        for run in sorted(ids):
            cost, src = _run_cost(d, run)
            runs[f"{sub}/{run}" if sub else run] = {"cost_usd": round(cost, 6), "source": src}
    return {"runs": runs, "total_usd": round(sum(r["cost_usd"] for r in runs.values()), 6), "cap_usd": C.USD_CAP}


def check_cap(root: Path, job_cap: float) -> float:
    """§8.2 hard cap: refuse when spent + this job's cap > USD_CAP; returns the amount spent."""
    spent = ledger(root)["total_usd"]
    if spent + job_cap > C.USD_CAP + 1e-9:
        raise BudgetRefused(f"已花 {spent:.2f} + 本 job 上限 {job_cap:g} > 硬上限 {C.USD_CAP:g} USD，不啟動")
    return spent


def cap_reached(root: Path) -> bool:
    """§8.2 hard cap reached: not even one more draft (the largest job cap) may start."""
    return ledger(root)["total_usd"] + C.JOB_CAP_USD["gen"] > C.USD_CAP + 1e-9


def stop_for_cap(state: Mapping[str, Any], spent: float) -> dict[str, Any]:
    """§8.2 after the hard cap: drafting stops; waiting drafts are still audited / fixed while a job fits,
    a job the cap refuses drops its draft (run_ho_a); the passed questions go on to Kay, K-U2 and F2."""
    if state.get("cap_stop"):
        return copy.deepcopy(dict(state))
    new = copy.deepcopy(dict(state))
    new["drafting_stopped"] = True
    new["cap_stop"] = {"at": now(), "spent_usd": round(spent, 4), "cap_usd": C.USD_CAP,
                       "gen_cap_usd": C.JOB_CAP_USD["gen"], "unresolved": [r["id"] for r in records(state, UNRESOLVED)]}
    return new


def reserve(root: Path, run_id: str, job_cap: float, sub: str = "") -> Path:
    d = Path(root) / sub if sub else Path(root)
    return write_json(d / "reserve" / f"{run_id}.json", {"run_id": run_id, "budget_usd": job_cap, "at": now()})


def reestimate(state: Mapping[str, Any], root: Path, slots: Sequence[Slot]) -> dict[str, Any]:
    """§8.2 pilot re-estimate: spent + remaining slots × pilot cost per passed pilot question."""
    if not is_complete(state, slots, "pilot"):
        raise HoError("the pilot is not complete")
    led = ledger(root)["runs"]
    pilot_runs = [run for r in records(state) if r["pilot"] for run in r["runs"]]
    pilot_spent = sum(led.get(run, {}).get("cost_usd", 0.0) for run in pilot_runs)
    n_pilot = len([r for r in records(state, (PASSED,)) if r["pilot"]])
    avg = pilot_spent / max(n_pilot, 1)
    spent = ledger(root)["total_usd"]
    remaining = [s for s in slots if not slot_done(state, s)]
    est = spent + len(remaining) * avg
    doc = {"at": now(), "spent_usd": round(spent, 4), "pilot_spent_usd": round(pilot_spent, 4),
           "pilot_passed": n_pilot, "avg_per_question_usd": round(avg, 4), "remaining_slots": len(remaining),
           "estimate_usd": round(est, 4), "cap_usd": C.USD_CAP, "action": "none", "cancelled": []}
    if est > C.USD_CAP:
        cut = [s.key for s in remaining if s.number == 3]
        left = len(remaining) - len(cut)
        doc.update(action="cancel_slot3", cancelled=cut, estimate_after_cancel_usd=round(spent + left * avg, 4))
        if spent + left * avg > C.USD_CAP:
            doc["action"] = "stop_drafting"
    return doc


def apply_reestimate(state: Mapping[str, Any], doc: Mapping[str, Any]) -> dict[str, Any]:
    if state.get("reestimate"):
        raise HoError("the pilot re-estimate was already applied (§8.2: once, after the pilot)")
    new = copy.deepcopy(dict(state))
    new["reestimate"] = dict(doc)
    new["cancelled"] = sorted(set(new["cancelled"]) | set(doc.get("cancelled", [])))
    new["drafting_stopped"] = doc["action"] == "stop_drafting"
    return new
