"""GD experiment §7 HO generation order, quotas and selection (ho_tools/_ho_state.py).

Pure state functions on synthetic records: 四類輪替 (KIN, DIS, TO, MH), 多跳子型輪替 with
the 8/7/8/7 quotas, 每類取前 30 個通過稽核的題, the 60-draft cap, pilot ids, and that
updates return new states.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
for _p in (str(_DIR / "ho_tools"), str(_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = importlib.import_module("_ho_common")
S = importlib.import_module("_ho_state")


def fill(state, cat, status, n, sub=None):
    """n records of one category and status appended in commit order."""
    for _ in range(n):
        seq = state["records"][-1]["seq"] + 1 if state["records"] else 1
        k = len(S.records(state, cat)) + 1
        slot = S.Slot(seq, 1, f"{H.PREFIX[cat]}{k:03d}", cat, sub or cat)
        state = S.add_record(state, slot, status, None if status == S.ABANDONED else {"id": slot.qid})
    return state


def order(slots):
    return [(s.qid, s.subtype) for s in slots]

# ---------------------------------------------------------------- 四類輪替與子型

def test_a_round_takes_one_slot_per_category_in_order():
    slots = S.plan_round(S.new_state(False))
    assert order(slots) == [("H_KIN_001", "KIN"), ("H_DIS_001", "DIS"), ("H_TO_001", "TO"),
                            ("H_MH_001", "SUC")]
    assert [s.seq for s in slots] == [1, 2, 3, 4] and {s.round for s in slots} == {1}


def test_per_round_interleaves_the_categories_and_rotates_mh_sub_types():
    slots = S.plan_round(S.new_state(False), per_round=3)
    assert [s.qid[:-4] for s in slots] == ["H_KIN", "H_DIS", "H_TO", "H_MH"] * 3
    assert [s.subtype for s in slots if s.cat == "MH"] == ["SUC", "BRP", "BRL"]


def test_mh_rotation_continues_from_the_last_mh_draft_across_rounds():
    st = fill(S.new_state(False), "MH", S.PASSED, 1, "SUC")
    st = fill(st, "MH", S.BLOCKED, 1, "BRP")
    assert [s.subtype for s in S.plan_round(st) if s.cat == "MH"] == ["BRL"]
    st = fill(st, "MH", S.DROPPED, 1, "OQ")
    assert [s.subtype for s in S.plan_round(st, 2) if s.cat == "MH"] == ["SUC", "BRP"]


def test_a_sub_type_whose_quota_is_selected_is_skipped():
    st = S.new_state(False)
    for sub, n in (("SUC", 8), ("BRP", 7)):
        st = fill(st, "MH", S.PASSED, n, sub)
    st = fill(st, "MH", S.PASSED, 1, "OQ")
    assert [s.subtype for s in S.plan_round(st, 3) if s.cat == "MH"] == ["BRL", "OQ", "BRL"]


def test_quotas_add_up_to_thirty():
    assert sum(H.MH_QUOTA.values()) == H.PER_CATEGORY == 30
    assert H.MH_QUOTA == {"SUC": 8, "BRP": 7, "BRL": 8, "OQ": 7}
    assert H.CATEGORY_ORDER == ("KIN", "DIS", "TO", "MH")

# ---------------------------------------------------------------- 前 30、60 題上限

def test_selection_takes_the_first_30_passed_in_commit_order():
    st = fill(S.new_state(False), "KIN", S.PASSED, 20)
    st = fill(st, "KIN", S.DROPPED, 3)
    st = fill(st, "KIN", S.PASSED, 12)
    sel = S.selected_ids(st)
    assert len(sel) == 30 and sel[-1] == "H_KIN_033" and "H_KIN_034" not in sel
    assert "KIN" not in S.open_categories(st)


def test_selection_keeps_mh_within_its_sub_type_quotas():
    st = fill(S.new_state(False), "MH", S.PASSED, 9, "SUC")
    st = fill(st, "MH", S.PASSED, 2, "BRP")
    sel = S.selection(st)
    assert [r["subtype"] for r in sel].count("SUC") == 8 and len(sel) == 10
    assert S.selected_ids(st)[:8] == [f"H_MH_{i:03d}" for i in range(1, 9)]


def test_a_category_closes_at_60_drafts_and_abandoned_attempts_are_not_drafts():
    st = fill(S.new_state(False), "TO", S.ABANDONED, 5)
    st = fill(st, "TO", S.BLOCKED, 40)
    st = fill(st, "TO", S.PASSED, 10)
    assert S.drafts(st, "TO") == 50 and "TO" in S.open_categories(st)
    assert sum(s.cat == "TO" for s in S.plan_round(st, per_round=20)) == 10
    st = fill(st, "TO", S.DROPPED, 10)
    assert "TO" not in S.open_categories(st)


def test_complete_when_every_category_is_full_or_capped():
    st = S.new_state(False)
    for cat in ("KIN", "DIS", "TO"):
        st = fill(st, cat, S.PASSED, 30)
    assert not S.is_complete(st)
    st = fill(st, "MH", S.BLOCKED, 55)
    st = fill(st, "MH", S.PASSED, 5, "OQ")
    assert S.is_complete(st) and S.plan_round(st) == []
    assert S.summary(st)["selected"]["MH"] == 5


def test_plan_refuses_while_drafts_wait_for_audit_or_fix():
    st = fill(S.new_state(False), "DIS", S.PENDING, 1)
    with pytest.raises(H.HoToolError):
        S.plan_round(st)
    with pytest.raises(H.HoToolError):
        S.plan_round(S.new_state(False), per_round=0)


def test_plan_can_be_limited_to_some_categories_without_reordering():
    slots = S.plan_round(S.new_state(True), categories=("MH", "KIN"))
    assert order(slots) == [("H_KIN_P01", "KIN"), ("H_MH_P01", "SUC")]

# ---------------------------------------------------------------- records

def test_updates_return_new_states_and_keep_commit_order():
    st0 = S.new_state(False)
    slot = S.plan_round(st0)[0]
    st1 = S.add_record(st0, slot, S.PENDING, {"id": slot.qid})
    st2 = S.update_record(st1, slot.qid, S.PASSED, "ok", append={"audits": {"severity": "ok"}})
    assert st0["records"] == [] and S.record(st1, slot.qid)["status"] == S.PENDING
    assert S.record(st2, slot.qid)["audits"] == [{"severity": "ok"}]
    assert [e["status"] for e in S.record(st2, slot.qid)["events"]] == [S.PENDING, S.PASSED]
    with pytest.raises(H.HoToolError):
        S.add_record(st2, slot, S.PENDING, None)
    with pytest.raises(H.HoToolError):
        S.update_record(st2, slot.qid, "weird")


def test_blocked_by_overlap_counts_drafts_blocked_by_a_section_7_overlap_rule():
    st = fill(S.new_state(False), "KIN", S.BLOCKED, 3)
    st = S.update_record(st, "H_KIN_001", mech=[{"rule": "overlap_new82", "detail": "", "level": "error"}])
    st = S.update_record(st, "H_KIN_002", mech=[{"rule": "key_form", "detail": "", "level": "error"}])
    st = S.update_record(st, "H_KIN_003", mech=[{"rule": "overlap_ho", "detail": "", "level": "error"},
                                                 {"rule": "core_limit", "detail": "", "level": "error"}])
    assert S.blocked_by_overlap(st) == {"KIN": 2, "DIS": 0, "TO": 0, "MH": 0}


def test_live_items_are_the_drafts_that_hold_gold():
    st = S.new_state(False)
    for status in (S.PENDING, S.PASSED, S.NEEDS_FIX, S.BLOCKED, S.DROPPED, S.ABANDONED):
        st = fill(st, "KIN", status, 1)
    assert [q for q, _ in S.live_items(st)] == ["H_KIN_001", "H_KIN_002", "H_KIN_003"]
    assert [q for q, _ in S.live_items(st, exclude="H_KIN_002")] == ["H_KIN_001", "H_KIN_003"]


def test_state_files_round_trip_and_pilot_flags_must_match(tmp_path):
    formal, pilot = tmp_path / "ho", tmp_path / "ho" / "pilot"
    st = fill(S.new_state(False), "KIN", S.PASSED, 2)
    S.save_state(formal, st)
    assert S.load_state(formal) == json.loads(json.dumps(st))
    assert S.load_state(pilot)["pilot"] is True and S.load_state(formal)["pilot"] is False
    S.save_state(pilot, st)                                     # a formal state under a pilot path
    with pytest.raises(H.HoToolError):
        S.load_state(pilot)
    assert H.is_pilot_root(H.PILOT_ROOT) and H.is_pilot_root(H.PILOT_ROOT / "x")
    assert not H.is_pilot_root(H.HO_ROOT)
