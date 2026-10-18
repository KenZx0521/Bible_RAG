"""Experiment A confirmation set: agent limits, the §8.2 hard-cap stop and the F2 → F3 handoff
(ho_a/claude_a.py agent_limit, runs_a.py, run_ho_a.py stop-drafting, freeze_a.py → collect_ctx.py).

claude_a.launch is monkeypatched by kgca_helpers.FakeLauncher (nothing is launched, no USD, no Ollama).
Covered: a run that ends on an agent limit is not rerun and counts one slot attempt (draft) or drops
the draft (audit); an infrastructure failure is still rerun and not counted; after the hard cap the
loop stops drafting, settles the waiting drafts and the passed questions go on to the Kay page, K-U2
and F2; freeze_a's output is accepted as is by collect_ctx.frozen_questions and the F2 guard.
Needs the store (segments.json, layers) and skips without it.
"""

import importlib

import pytest

import kgca_helpers as K
import test_kg_cards_confirm_a_runner as T

pytestmark = pytest.mark.skipif(not K.STORE_OK, reason=f"store not mounted ({K.C.SEGMENTS})")
H = K.H
BURN_GEN, BURN_AUDIT, FLAKY, SWAPPED = "QJ2s1", "QI6s1a1", "QI8s1a1", "QI9s1a1"
FALLBACK_EVENT = {"type": "system", "subtype": "model_refusal_fallback", "trigger": "refusal",
                  "original_model": "claude-opus-5-5", "fallback_model": "claude-opus-4-8"}


@pytest.fixture(scope="module")
def mods():
    return {m: importlib.import_module(m) for m in ("claude_a", "state_a", "run_ho_a", "kay_a", "freeze_a",
                                                     "runs_a")}


class Limits(T.Agent):
    """Every J2 slot-1 draft ends on its budget cap; one audit too; one draft has a lost result once;
    one draft is answered once by a fallback model."""

    def __init__(self):
        super().__init__()
        self.flaky = self.swapped = 0

    def __call__(self, kind, qid, user, root):
        if kind == "gen" and qid.startswith(BURN_GEN):
            return None, 4.05, []
        if kind == "audit" and qid == BURN_AUDIT:
            return None, 1.5, []
        if kind == "gen" and qid == FLAKY and not self.flaky:
            self.flaky += 1
            return K.NO_RESULT, 0.0, []
        out = super().__call__(kind, qid, user, root)
        if kind == "gen" and qid == SWAPPED and not self.swapped:
            self.swapped += 1
            return out[0], out[1], [*out[2], FALLBACK_EVENT]
        return out


def test_agent_limit_classification(mods):
    CL = mods["claude_a"]
    assert CL.agent_limit({"subtype": "error_max_budget_usd", "is_error": True}, 4) == "error_max_budget_usd"
    assert CL.agent_limit({"subtype": "success", "is_error": True, "total_cost_usd": 4.2}, 4)
    assert CL.agent_limit({"subtype": "success", "is_error": True, "total_cost_usd": 0.2}, 4) is None  # API error
    assert CL.agent_limit(None, 4) is None                                                            # no result
    ok = {"subtype": "success", "is_error": False, "structured_output": {}, "modelUsage": {"claude-opus-5-5": {}}}
    assert CL.run_error(0, ok, []) is None
    assert "opus-4-8" in CL.run_error(0, ok, [FALLBACK_EVENT])
    assert "opus-4-8" in CL.run_error(0, {**ok, "modelUsage": {"claude-opus-5-5": {}, "claude-opus-4-8": {}}}, [])
    assert CL.agent_limit(ok, 4) is None                              # a fallback is an infrastructure failure


def test_limits_count_and_infra_is_rerun(tmp_path, monkeypatch, mods):
    S, R = mods["state_a"], mods["run_ho_a"]
    root, fake, ctx = T._setup(tmp_path, monkeypatch, mods, Limits())
    state = R.pilot(root, ctx)                                    # one call finishes the pilot
    assert S.is_complete(state, ctx.slots, "pilot")
    j2 = S.records(state, slot="J2_1")
    assert [r["status"] for r in j2] == [S.ABANDONED] * 3 and S.attempts_used(state, "J2_1") == 3
    assert all(r.get("agent_limit") and not r.get("infra_failure") for r in j2)
    assert sum(1 for c in fake.calls if c[1].startswith(BURN_GEN)) == 3                     # never rerun
    burnt = S.record(state, BURN_AUDIT)
    assert burnt["status"] == S.DROPPED and burnt["agent_limit"] == "error_max_turns"
    assert sum(1 for c in fake.calls if c[0] == "audit" and c[1] == BURN_AUDIT) == 1
    assert S.passed_record(state, "I6_1")["id"] == "QI6s1a2"                                  # slot drafted again
    flaky = S.record(state, FLAKY)
    assert flaky["status"] == S.PASSED and flaky["attempt"] == 1 and len(flaky["runs"]) >= 3   # gen rerun once
    assert sum(1 for c in fake.calls if c[0] == "gen" and c[1] == FLAKY) == 2
    swapped = S.record(state, SWAPPED)                                # fallback model: rerun, not counted
    assert swapped["status"] == S.PASSED and swapped["attempt"] == 1
    assert sum(1 for c in fake.calls if c[0] == "gen" and c[1] == SWAPPED) == 2


def test_hard_cap_stops_drafting_and_reaches_freeze(tmp_path, monkeypatch, mods):
    S, R, KA, F = mods["state_a"], mods["run_ho_a"], mods["kay_a"], mods["freeze_a"]
    root, fake, ctx = T._setup(tmp_path, monkeypatch, mods, T.Agent(gen_cost=1.0))
    R.pilot(root, ctx)
    H.write_json(tmp_path / "k1.json", {"stop": False, "n_pass": 12, "wording": "K1＝12/12"})
    assert R.budget(root, apply=True)["applied"]["action"] == "none"
    with pytest.raises(H.HoError, match="未達硬上限"):
        R.stop_drafting(root, ctx.slots)
    S.reserve(root, "external_spend", 140 - S.ledger(root)["total_usd"] - 9.0)               # later runs cost more

    state = R.loop(root, ctx)
    summ = S.summary(state, ctx.slots)
    assert state["drafting_stopped"] and state["cap_stop"]["spent_usd"] + 4 > 140 and summ["cap_stop"]
    assert summ["main_complete"] and not S.records(state, S.UNRESOLVED)
    assert S.ledger(root)["total_usd"] <= 140 + 1e-9
    n_passed = summ["slots_passed"]
    assert 12 < n_passed < 35

    doc = KA.draw(root)
    KA.apply(root, {"layer": {n: "ok" for n in doc["layer_nodes"]},
                    "questions": {q: {"decision": "accept", "note": ""} for q in doc["question_ids"]}})
    out = F.freeze(root)
    assert out["stop"] is False and out["n"] == n_passed
    man = H.read_json(tmp_path / F.MANIFEST)
    assert man["cap_stop"] == state["cap_stop"] and man["summary"]["drafting_stopped"]


def test_freeze_output_feeds_collect_ctx(tmp_path, monkeypatch, mods):
    import collect_ctx as CX
    import guards_c as G
    S, R, KA, F = mods["state_a"], mods["run_ho_a"], mods["kay_a"], mods["freeze_a"]
    root, fake, ctx = T._setup(tmp_path, monkeypatch, mods, T.Agent())
    R.pilot(root, ctx)
    H.write_json(tmp_path / "k1.json", {"stop": False, "n_pass": 12, "wording": "K1＝12/12"})
    R.budget(root, apply=True)
    R.loop(root, ctx)
    doc = KA.draw(root)
    KA.apply(root, {"layer": {n: "ok" for n in doc["layer_nodes"]},
                    "questions": {q: {"decision": "accept", "note": ""} for q in doc["question_ids"]}})
    H.write_json(tmp_path / "inputs_manifest.json", {"note": "kept"})
    out = F.freeze(root)
    q, man, ku2 = tmp_path / F.FROZEN, tmp_path / F.INPUTS, tmp_path / F.KU2
    assert H.read_json(man)["frozen"] == {F.FROZEN: out["questions_frozen_sha256"]}
    assert H.read_json(man)["note"] == "kept"
    qs, sha = CX.frozen_questions(q, man, ku2)                     # no hand-written manifest
    assert sha == out["questions_frozen_sha256"] and len(qs) == out["n"]
    assert G.frozen_problems(man, (q,), stage0=False) == []       # what run_c.py prepare checks
    for name in (F.FROZEN, F.MANIFEST, F.KU2):
        (tmp_path / name).unlink()
    with pytest.raises(H.HoError, match="already records"):
        F.freeze(root)                                             # a stale F2 sha is never overwritten
