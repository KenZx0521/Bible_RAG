"""Experiment A confirmation set, question-writing executor end to end with a fake launcher
(ho_a/run_ho_a.py, runs_a.py, state_a.py, kay_a.py, freeze_a.py).

claude_a.launch is monkeypatched by kgca_helpers.FakeLauncher (canned structured outputs and
synthetic transcripts; nothing is launched, no USD, no Ollama). The fake writer drafts the segment
candidates with template wording. Covered: pilot → mechanical error → mech fix → audit major → audit
fix → re-audit → passed; a transcript breach drops its draft and the slot is drafted again; an
abandoned attempt; the K1 and re-estimate gates; the main loop over all 35 slots; the Kay page with
a revise and a drop; freeze with K-U2; the §8.2 hard cap refusing a job before it starts; the
re-estimate branches. Needs the store (segments.json, layers) and skips without it.
"""

import importlib
import json
import re

import pytest

import kgca_helpers as K

pytestmark = pytest.mark.skipif(not K.STORE_OK, reason=f"store not mounted ({K.C.SEGMENTS})")
H = K.H
QID = re.compile(r"^Q([IJ]\d+)s(\d+)a(\d+)$")
MECH_THEN_AUDIT, BREACH, ABANDON = "QI1s1a1", "QI3s1a1", "QI4s1a1"


@pytest.fixture(scope="module")
def mods():
    return {m: importlib.import_module(m) for m in ("claude_a", "state_a", "run_ho_a", "kay_a", "freeze_a", "support")}


class Agent:
    """Scripted writer / auditor / fixer: clean drafts of the segment candidates, plus three scripted cases."""

    def __init__(self, gen_cost=0.5):
        self.gen_cost, self.audits = gen_cost, {}

    def draft(self, root, qid):
        S = importlib.import_module("state_a")
        sid, slot_no, _ = QID.match(qid).groups()
        seg = K.seg_row(sid)
        slot_type = seg["slots"][int(slot_no) - 1]
        qtype = "S1a" if slot_type == "S1a_rev" else slot_type
        state = S.load_state(root)
        live = [r["item"] for r in S.records(state, S.LIVE, segment=sid) if r.get("item")]
        used = {(it["qtype"], tuple(s["name"] for s in it["seeds"]), it["answer"]["text"]) for it in live}
        first = S.passed_record(state, f"{sid}_1")
        rev_k = first["item"]["k"] if slot_type == "S1a_rev" and first else None
        for c in seg["candidates"]:
            if c["qtype"] != qtype:
                continue
            q = K.make_question(qid, seg, c)
            if (q["qtype"], tuple(s["name"] for s in q["seeds"]), q["answer"]["text"]) in used or \
                    (rev_k is not None and q["k"] == rev_k):
                continue
            return q
        raise AssertionError(f"no candidate left for {qid}")

    def __call__(self, kind, qid, user, root):
        if kind == "gen":
            if qid == ABANDON:
                return {"status": "abandoned", "reason": "核對不過", "item": None}, self.gen_cost, []
            q = self.draft(root, qid)
            if qid == MECH_THEN_AUDIT:
                q["question"] += "（王上15:25）"
            extra = K.tool_pair(9, "cat /etc/passwd", "root:x") if qid == BREACH else []
            return {"status": "drafted", "reason": "", "item": q}, self.gen_cost, extra
        if kind == "fix":
            item = json.loads(user.split("原題（JSON）：", 1)[1])
            item["question"] = item["question"].replace("（王上15:25）", "")
            item["change_log"] = "依意見修改"
            return {"status": "revised", "reason": "", "item": item}, 0.3, []
        n = self.audits[qid] = self.audits.get(qid, 0) + 1
        sev = "major" if qid == MECH_THEN_AUDIT and n == 1 else "ok"
        return {"id": qid, "severity": sev, "issues": ["算法要寫明"] if sev == "major" else [],
                "suggested_fix": "補寫算法" if sev == "major" else "不用改。", "checked": "重算"}, 0.1, []


def _setup(tmp_path, monkeypatch, mods, agent):
    root = tmp_path / "ho"
    root.mkdir()
    K.write_pin(root)
    fake = K.FakeLauncher(agent)
    monkeypatch.setattr(mods["claude_a"], "launch", fake)
    return root, fake, mods["run_ho_a"].make_ctx(root)


def test_end_to_end_pilot_loop_kay_freeze(tmp_path, monkeypatch, mods):
    S, R, KA, F = mods["state_a"], mods["run_ho_a"], mods["kay_a"], mods["freeze_a"]
    root, fake, ctx = _setup(tmp_path, monkeypatch, mods, Agent())

    state = R.pilot(root, ctx)
    assert S.is_complete(state, ctx.slots, "pilot")
    rec = S.record(state, MECH_THEN_AUDIT)
    assert rec["status"] == S.PASSED and [f["source"] for f in rec["fixes"]] == ["mech", "audit"]
    assert [a["severity"] for a in rec["audits"]] == ["major", "ok"] and "（王上" not in rec["item"]["question"]
    breach = S.record(state, BREACH)
    assert breach["status"] == S.DROPPED and {v["rule"] for v in breach["transcript"]} >= {"t_tool"}
    assert not [c for c in fake.calls if c[1] == BREACH and c[0] != "gen"]            # never audited
    assert S.record(state, "QI3s1a2")["status"] == S.PASSED
    assert S.record(state, ABANDON)["status"] == S.ABANDONED and S.record(state, "QI4s1a2")["status"] == S.PASSED
    passed = H.read_json(root / H.PASSED_FILE)["questions"]
    assert len(passed) == 12 and all(q["pilot"] for q in passed) and BREACH not in {q["id"] for q in passed}

    with pytest.raises(H.HoError, match="k1.json"):
        R.loop(root, ctx)
    H.write_json(tmp_path / "k1.json", {"stop": False, "n_pass": 12, "wording": "K1＝12/12"})
    with pytest.raises(H.HoError, match="reestimate"):
        R.loop(root, ctx)
    doc = R.budget(root, apply=True)
    assert doc["applied"]["action"] == "none" and doc["applied"]["pilot_passed"] == 12

    state = R.loop(root, ctx)
    summ = S.summary(state, ctx.slots)
    assert summ["slots_passed"] == 35 and summ["main_complete"] and summ["segments_with_passed"] == 14
    with pytest.raises(H.HoError, match="Kay"):
        F.freeze(root)

    doc = KA.draw(root)
    page = (root / "kay" / "kay_page.html").read_text(encoding="utf-8")
    assert len(doc["layer_nodes"]) == 20 and len(doc["question_ids"]) == 10
    for word in ("ref_disagree", "gen_passage", "answer_is_father", "hidden", "依上列資料推算"):
        assert word not in page
    assert KA.QUESTION_RULE in page and "不看層列對錯" in KA.QUESTION_RULE
    qids = doc["question_ids"]
    decisions = {"layer": {n: "ok" for n in doc["layer_nodes"]},
                 "questions": {q: {"decision": "accept", "note": ""} for q in qids}}
    decisions["layer"][doc["layer_nodes"][0]] = "wrong"                              # 1 wrong: recorded only
    decisions["questions"][qids[0]] = {"decision": "revise", "note": "措辭再清楚一點"}
    decisions["questions"][qids[1]] = {"decision": "drop", "note": "不自然"}
    leaky = json.loads(json.dumps(decisions))
    leaky["questions"][qids[0]]["note"] = "G-auto 算錯"
    with pytest.raises(H.HoError, match="reword"):
        KA.apply(root, leaky)                                                    # the note would reach the writer
    state = KA.apply(root, decisions)
    assert state["kay"]["layer"]["n_wrong"] == 1 and state["kay"]["layer"]["stop"] is False
    dropped_slot = S.record(state, qids[1])["slot"]
    assert S.record(state, qids[0])["status"] == S.NEEDS_FIX

    state = R.loop(root, ctx)
    assert S.record(state, qids[0])["status"] == S.PASSED and S.record(state, qids[0])["fixes"][-1]["source"] == "kay"
    assert S.passed_record(state, dropped_slot) is not None

    out = F.freeze(root)
    assert out["stop"] is False and out["n"] == 35
    frozen = H.read_json(tmp_path / F.FROZEN)
    man = H.read_json(tmp_path / F.MANIFEST)
    assert man["sha256"] == H.sha256_file(tmp_path / F.FROZEN) and man["n"] == 35
    assert "question" not in json.dumps(man["appendix_c"]) and H.read_json(tmp_path / F.KU2)["n_units"] == 14
    segs = K.seg_doc()["segments"]
    assert all(not mods["support"].support_record(q, segs)["errors"] for q in frozen["questions"])
    assert (root / "hidden_flags.json").is_file() and "hidden" not in json.dumps(frozen)
    with pytest.raises(H.HoError, match="never rewritten"):
        F.freeze(root)

    for p in (root / "prompts").glob("*.json"):                                    # what the agents saw
        seen = json.dumps(H.read_json(p), ensure_ascii=False)
        assert not re.search(r"(?<![A-Za-z])[IJ]\d\d(?!\d)", seen), p.name
        assert "ref_disagree" not in seen and "gen_passage" not in seen
    led = S.ledger(root)
    assert led["total_usd"] == pytest.approx(sum(r["cost_usd"] for r in led["runs"].values()))


def test_hard_cap_refuses_before_the_launch(tmp_path, monkeypatch, mods):
    S, R = mods["state_a"], mods["run_ho_a"]
    root, fake, ctx = _setup(tmp_path, monkeypatch, mods, Agent(gen_cost=4.0))
    S.reserve(root, "earlier_run", 133.0)                     # spent 133: one 4 USD job fits, the next does not
    with pytest.raises(H.BudgetRefused):
        R.pilot(root, ctx)
    state = S.load_state(root)
    assert len(fake.calls) == 1 and len(state["records"]) == 1
    assert S.ledger(root)["total_usd"] == pytest.approx(137.0)
    S.reserve(root, "other_run", 3.0)                         # spent 140: even the 1.5 USD audit cannot start
    with pytest.raises(H.BudgetRefused):
        R.pilot(root, ctx)
    assert len(fake.calls) == 1 and S.load_state(root)["records"][0]["status"] == S.NEEDS_FIX


def test_a_launch_refused_before_starting_fails_the_job_but_keeps_the_others(tmp_path, monkeypatch, mods):
    S, R, CL = mods["state_a"], mods["run_ho_a"], mods["claude_a"]
    root, fake, ctx = _setup(tmp_path, monkeypatch, mods, Agent())

    def picky(root_, run_id, *a, **kw):
        if "QI2" in run_id:
            raise H.HoError("claude --version is '2.1.299'; pinned 2.1.302")
        return fake(root_, run_id, *a, **kw)
    monkeypatch.setattr(CL, "launch", picky)
    with pytest.raises(H.HoError, match="pinned"):
        R.draft_round(root, ctx, "pilot")
    state = S.load_state(root)
    assert len(state["records"]) == 11 and "QI2s3a1" not in {r["id"] for r in state["records"]}
    assert not (root / "reserve" / "gen_QI2s3a1_1.json").exists()


def test_missing_pin_refuses_to_start(tmp_path, mods):
    with pytest.raises(H.HoError, match="cli_pin"):
        mods["run_ho_a"].make_ctx(tmp_path)


def _pilot_state(S, slots, root, cost):
    state = S.new_state()
    seq = 0
    for s in slots:
        if not s.pilot:
            continue
        seq += 1
        p = S.Planned(seq, 1, f"Q{s.segment}s{s.number}a1", s, 1, "pilot")
        state = S.add_record(state, p, S.PASSED, {"id": p.qid}, runs=[f"gen_{p.qid}_1"])
        (root / "transcripts").mkdir(parents=True, exist_ok=True)
        (root / "transcripts" / f"gen_{p.qid}_1.jsonl").write_text(json.dumps(K.events_for({}, cost)[-1]) + "\n")
    return state


@pytest.mark.parametrize("cost, action, cancelled", [(1.0, "none", 0), (4.5, "cancel_slot3", 6), (10.0, "stop_drafting", 6)])
def test_reestimate_branches(tmp_path, mods, cost, action, cancelled):
    S = mods["state_a"]
    slots = S.slot_plan(S.load_segments())
    state = _pilot_state(S, slots, tmp_path, cost)
    doc = S.reestimate(state, tmp_path, slots)
    assert doc["action"] == action and len(doc["cancelled"]) == cancelled and doc["remaining_slots"] == 23
    new = S.apply_reestimate(state, doc)
    assert new["drafting_stopped"] is (action == "stop_drafting")
    if action == "stop_drafting":
        assert S.plan_round(new, slots, "main") == [] and S.is_complete(new, slots, "main")
    if action == "cancel_slot3":
        assert all(S.slot_done(new, s) for s in slots if s.key in doc["cancelled"])
    with pytest.raises(H.HoError):
        S.apply_reestimate(new, doc)
