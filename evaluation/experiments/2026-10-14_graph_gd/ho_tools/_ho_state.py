"""HO drafting state (prereg §7): draft records in commit order, the generation order with
its quotas, and the selection 「每類取前 30 個通過稽核的題」.

One JSON file per run root (`<root>/state.json`). Records are kept in commit order (`seq`,
fixed when a slot is planned, so the order never depends on which agent finished first).
Functions here are pure: they take a state dict and return a new one.

Generation order (§7): rounds; each round plans, for slot j = 0..per_round-1 and each open
category in CATEGORY_ORDER (KIN, DIS, TO, MH), one slot (四類輪替). Multi-hop slots rotate
over MH_SUBTYPES (SUC, BRP, BRL, OQ), skipping a sub-type whose selected count reached its
quota 8/7/8/7 (多跳類內再依子型輪替). A category is open while its selection is below 30
and it has fewer than 60 drafts (某類草稿達 60 題仍不足 30 時，以實際數凍結).
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from _ho_common import (CATEGORY_ORDER, MAX_DRAFTS, MH_QUOTA, MH_SUBTYPES, PER_CATEGORY, PREFIX,
                        HoToolError, is_pilot_root)

__all__ = ["SCHEMA", "STATE_FILE", "ABANDONED", "BLOCKED", "PENDING", "PASSED", "NEEDS_FIX",
           "DROPPED", "LIVE", "UNRESOLVED", "MAX_FIX_ROUNDS", "OVERLAP_RULES", "Slot", "new_state",
           "load_state", "save_state", "records", "record", "drafts", "selection", "selected_ids",
           "open_categories", "plan_round", "add_record", "update_record", "live_items",
           "is_complete", "blocked_by_overlap", "transcript_breaches", "summary", "now"]

SCHEMA = "ho_state.v1"
STATE_FILE = "state.json"
ABANDONED = "abandoned"     # the agent produced no question: not a draft
BLOCKED = "blocked"         # mechanical check failed: a draft, never audited
PENDING = "pending_audit"   # mechanical check passed, waiting for the (re-)audit
PASSED = "passed"           # audit ok / minor (通過稽核)
NEEDS_FIX = "needs_fix"     # audit major / critical, or Kay asked for a revision
DROPPED = "dropped"         # fix failed, or deleted (由後續題遞補)
STATUSES = (ABANDONED, BLOCKED, PENDING, PASSED, NEEDS_FIX, DROPPED)
LIVE = frozenset({PENDING, PASSED, NEEDS_FIX})      # hold their gold and core against later drafts
UNRESOLVED = frozenset({PENDING, NEEDS_FIX})
MAX_FIX_ROUNDS = 1          # §7: major/critical 須修好並複驗，否則刪題 (one fix, one re-audit)
OVERLAP_RULES = frozenset({"overlap_ho", "overlap_new82", "overlap_old31"})


@dataclass(frozen=True)
class Slot:
    seq: int
    round: int
    qid: str
    cat: str            # KIN | DIS | TO | MH
    subtype: str        # KIN | DIS | TO for the first three, SUC | BRP | BRL | OQ for MH


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_state(pilot: bool) -> dict[str, Any]:
    return {"schema": SCHEMA, "pilot": pilot, "created_utc": now(), "records": [], "runs": {},
            "kay": None}


def load_state(root: Path) -> dict[str, Any]:
    """The root's state.json (a new one when absent); its pilot flag must match the root."""
    path = Path(root) / STATE_FILE
    pilot = is_pilot_root(root)
    if not path.is_file():
        return new_state(pilot)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != SCHEMA:
        raise HoToolError(f"{path}: schema {state.get('schema')!r} is not {SCHEMA}")
    if state.get("pilot") is not pilot:
        raise HoToolError(f"{path}: pilot flag {state.get('pilot')} does not match the root")
    seqs = [r["seq"] for r in state["records"]]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        raise HoToolError(f"{path}: records are not in strict commit order")
    return state


def save_state(root: Path, state: Mapping[str, Any]) -> Path:
    """Atomic write (temp file + rename) of the root's state.json."""
    path = Path(root) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------ queries

def records(state: Mapping[str, Any], cat: str | None = None,
            statuses: Iterable[str] | None = None) -> list[dict[str, Any]]:
    wanted = None if statuses is None else frozenset(statuses)
    return [r for r in state["records"] if (cat is None or r["cat"] == cat)
            and (wanted is None or r["status"] in wanted)]


def record(state: Mapping[str, Any], qid: str) -> dict[str, Any]:
    for r in state["records"]:
        if r["id"] == qid:
            return r
    raise HoToolError(f"no record {qid!r} in the state")


def drafts(state: Mapping[str, Any], cat: str) -> int:
    """Drafts of a category: records with a question (abandoned attempts are not drafts)."""
    return sum(r["status"] != ABANDONED for r in records(state, cat))


def selection(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """每類取前 30 個通過稽核的題, in commit order; MH also within its 8/7/8/7 quotas."""
    taken: dict[str, int] = {}
    out = []
    for r in records(state, statuses=(PASSED,)):
        key = r["subtype"] if r["cat"] == "MH" else None
        if taken.get(r["cat"], 0) >= PER_CATEGORY or (key and taken.get(key, 0) >= MH_QUOTA[key]):
            continue
        taken[r["cat"]] = taken.get(r["cat"], 0) + 1
        if key:
            taken[key] = taken.get(key, 0) + 1
        out.append(r)
    return out


def selected_ids(state: Mapping[str, Any]) -> list[str]:
    return [r["id"] for r in selection(state)]


def _selected_counts(state: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in selection(state):
        counts[r["cat"]] = counts.get(r["cat"], 0) + 1
        if r["cat"] == "MH":
            counts[r["subtype"]] = counts.get(r["subtype"], 0) + 1
    return counts


def open_categories(state: Mapping[str, Any]) -> list[str]:
    counts = _selected_counts(state)
    return [c for c in CATEGORY_ORDER
            if counts.get(c, 0) < PER_CATEGORY and drafts(state, c) < MAX_DRAFTS]


def is_complete(state: Mapping[str, Any]) -> bool:
    return not open_categories(state) and not records(state, statuses=UNRESOLVED)


def live_items(state: Mapping[str, Any], exclude: str | None = None) -> list[tuple[str, dict]]:
    """(id, item) of drafts that hold gold and core (LIVE), minus `exclude`."""
    return [(r["id"], r["item"]) for r in records(state, statuses=LIVE)
            if r["id"] != exclude and r.get("item")]


def blocked_by_overlap(state: Mapping[str, Any]) -> dict[str, int]:
    """Per category: blocked drafts whose last mechanical check hit a §7 不重疊 rule (附錄 B).
    Only what the mechanical check stopped: the drafting agents check every key with
    `bt old --gold` first and move away from used passages, so this is nearly always 0;
    freeze.overlap_avoided() counts what they met in their transcripts."""
    out = {c: 0 for c in CATEGORY_ORDER}
    for r in records(state, statuses=(BLOCKED,)):
        if {v["rule"] for v in r.get("mech") or ()} & OVERLAP_RULES:
            out[r["cat"]] += 1
    return out


def transcript_breaches(state: Mapping[str, Any]) -> dict[str, int]:
    """Per category: records with a blinding error in one of their runs (dropped at commit)."""
    out = {c: 0 for c in CATEGORY_ORDER}
    for r in state["records"]:
        if any(v.get("level") == "error" for v in r.get("transcript") or ()):
            out[r["cat"]] += 1
    return out


def summary(state: Mapping[str, Any]) -> dict[str, Any]:
    counts = _selected_counts(state)
    by_status = {c: {s: len(records(state, c, (s,))) for s in STATUSES} for c in CATEGORY_ORDER}
    return {"selected": {k: counts.get(k, 0) for k in (*CATEGORY_ORDER, *MH_SUBTYPES)},
            "drafts": {c: drafts(state, c) for c in CATEGORY_ORDER}, "by_status": by_status,
            "blocked_by_overlap": blocked_by_overlap(state),
            "transcript_breaches": transcript_breaches(state), "open": open_categories(state),
            "complete": is_complete(state)}


# ------------------------------------------------------------------ planning (§7 order)

def _qid(cat: str, n: int, pilot: bool) -> str:
    return f"{PREFIX[cat]}P{n:02d}" if pilot else f"{PREFIX[cat]}{n:03d}"


def _next_subtype(last: str | None, counts: Mapping[str, int]) -> str | None:
    """Next MH sub-type after `last` in rotation, skipping full quotas; None when all full."""
    start = 0 if last is None else MH_SUBTYPES.index(last) + 1
    for i in range(len(MH_SUBTYPES)):
        sub = MH_SUBTYPES[(start + i) % len(MH_SUBTYPES)]
        if counts.get(sub, 0) < MH_QUOTA[sub]:
            return sub
    return None


def plan_round(state: Mapping[str, Any], per_round: int = 1,
               categories: Iterable[str] | None = None) -> list[Slot]:
    """The next round's slots in commit order. Refuses while drafts await audit or fix.
    `categories` limits the round to some categories (pilot / tests); order is unchanged."""
    if per_round < 1:
        raise HoToolError("per_round must be at least 1")
    pending = [r["id"] for r in records(state, statuses=UNRESOLVED)]
    if pending:
        raise HoToolError(f"audit or fix these drafts before the next round: {pending}")
    only = None if categories is None else frozenset(categories)
    cats = [c for c in open_categories(state) if only is None or c in only]
    counts = _selected_counts(state)
    used = {c: len(records(state, c)) for c in CATEGORY_ORDER}
    room = {c: MAX_DRAFTS - drafts(state, c) for c in CATEGORY_ORDER}
    mh = records(state, "MH")
    last_sub = mh[-1]["subtype"] if mh else None
    seq = state["records"][-1]["seq"] + 1 if state["records"] else 1
    rnd = max((r["round"] for r in state["records"]), default=0) + 1
    slots = []
    for _ in range(per_round):
        for cat in cats:
            if room[cat] <= 0:
                continue
            sub = cat
            if cat == "MH":
                sub = _next_subtype(last_sub, counts)
                if sub is None:
                    continue
                last_sub = sub
            used[cat] += 1
            room[cat] -= 1
            slots.append(Slot(seq, rnd, _qid(cat, used[cat], state["pilot"]), cat, sub))
            seq += 1
    return slots


# ------------------------------------------------------------------ updates (new state)

def add_record(state: Mapping[str, Any], slot: Slot, status: str, item: dict | None,
               note: str = "", **fields: Any) -> dict[str, Any]:
    """New state with the slot's record appended (commit order)."""
    if status not in STATUSES:
        raise HoToolError(f"unknown status {status!r}")
    if state["records"] and slot.seq <= state["records"][-1]["seq"]:
        raise HoToolError(f"slot {slot.qid} (seq {slot.seq}) is out of commit order")
    rec = {"seq": slot.seq, "round": slot.round, "id": slot.qid, "cat": slot.cat,
           "subtype": slot.subtype, "status": status, "item": item, "mech": [], "audits": [],
           "fixes": [], "runs": [], "events": [{"at": now(), "status": status, "note": note}]}
    rec.update(fields)
    new = copy.deepcopy(dict(state))
    new["records"].append(rec)
    return new


def update_record(state: Mapping[str, Any], qid: str, status: str | None = None, note: str = "",
                  append: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    """New state with one record changed: optional status (logged as an event), fields
    replaced, and list fields extended by `append` ({"audits": {...}, "runs": "id"})."""
    if status is not None and status not in STATUSES:
        raise HoToolError(f"unknown status {status!r}")
    new = copy.deepcopy(dict(state))
    rec = record(new, qid)
    rec.update(copy.deepcopy(fields))
    for key, value in (append or {}).items():
        rec[key].append(copy.deepcopy(value))
    if status is not None:
        rec["status"] = status
        rec["events"].append({"at": now(), "status": status, "note": note})
    return new
