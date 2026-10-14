"""Unit-level V1 OC and procedure power of the GD experiment (experiments/2026-10-14_graph_gd/
v1_power.py, prereg §6 / 附錄 A).

Synthetic checks of the s2_power port (exact sign-flip DP against brute force, the §6 stop
rule on questions and units, recheck's analytic OC against enumeration, the unit OC on
singletons against the analytic one, the prereg tally); the store-backed test runs the
reproduction of s2_power.json / recheck.json and the OLD31 unit sizes (gold only, §2).
"""

import importlib.util
import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
_SPEC = importlib.util.spec_from_file_location("gd_v1_power", _DIR / "v1_power.py")
vp = importlib.util.module_from_spec(_SPEC)
sys.modules["gd_v1_power"] = vp
_SPEC.loader.exec_module(vp)
gd = vp.gd

MAG = np.array([1 / 3, 1 / 2, 1 / 4])


def brute_p(vals):
    nz = [v for v in vals if v != 0]
    t = abs(sum(vals))
    hits = sum(abs(sum(s * v for s, v in zip(signs, nz))) >= t
               for signs in itertools.product((1, -1), repeat=len(nz)))
    return hits / 2 ** len(nz)


@pytest.mark.parametrize("vals", [[3, -1, 2, 0, 5], [1, 1, 1, 1], [4, -4], [0, 0], [7, 2, -3, 1, 1, -2]])
def test_exact_p_int_equals_brute_force(vals):
    assert vp.exact_p_int(vals) == pytest.approx(brute_p(vals) if any(vals) else 1.0, abs=1e-12)


@pytest.mark.parametrize("values,want", [([1, -1, -1, 0], True), ([1, 1, -1], False), ([-1, -1], False),
                                         ([1, -1, 0, 0, 1, -1], True), ([0, 0, 0], False)])
def test_stop_rule_needs_three_discordant_and_losses_at_least_wins(values, want):
    assert vp.stops(values) is want


def test_question_oc_equals_enumeration_of_the_rule():
    n, r, pw = 5, 0.3, 0.7
    stop = silent = 0.0
    for outcome in itertools.product((0, 1, -1), repeat=n):
        pr = np.prod([1 - r if o == 0 else r * (pw if o == 1 else 1 - pw) for o in outcome])
        w, los = outcome.count(1), outcome.count(-1)
        stop += pr if w + los >= 3 and los >= w else 0.0
        silent += pr if w + los < 3 and los > w else 0.0
    assert vp.question_oc(n, r, pw) == {vp.OC_KEYS[0]: round(stop, 3), vp.OC_KEYS[1]: round(silent, 3)}


def test_unit_oc_on_singletons_matches_the_question_oc():
    sizes = [1] * 31
    sim = vp.unit_oc(sizes, 0.2, 0.8, MAG, reps=200_000, seed=7)
    exact = vp.question_oc(31, 0.2, 0.8)
    for key in vp.OC_KEYS:
        assert sim[key] == pytest.approx(exact[key], abs=0.005)


def test_a_cancelling_unit_is_not_discordant():
    assert vp.scaled_units(np.array([1 / 3, -1 / 3, 0.5, -0.25, -0.25, 0.5]), [2, 3, 1]) == [0, 0, 540]


def test_prereg_tally_uses_unit_stop_and_strict_alpha():
    c = dict.fromkeys(vp.PREREG_KEYS, 0)
    vp.prereg_tally(c, q_stop=False, u_stop=True, p=0.01, pos=True)
    vp.prereg_tally(c, q_stop=True, u_stop=False, p=0.05, pos=True)      # p = α does not reject
    vp.prereg_tally(c, q_stop=False, u_stop=False, p=0.01, pos=False)    # wrong direction
    vp.prereg_tally(c, q_stop=False, u_stop=False, p=0.049, pos=True)
    assert c == {"stop": 1, "reject_nofut": 2, "reject": 1, "stop_question_rule": 1,
                 "reject_question_rule": 2}


def test_simulation_is_deterministic_in_its_seed():
    args = (0.2, 0.8, [3, 2, 1, 1], MAG, vp.prereg_tally, vp.PREREG_KEYS)
    assert vp.simulate(*args, reps=50, seed=3) == vp.simulate(*args, reps=50, seed=3)
    assert set(vp.simulate(*args, reps=5)) == set(vp.PREREG_KEYS)


def test_scenario_keys_follow_s2_power():
    assert vp.scenario_key(0.17, 0.8) == "r_ho=0.17,r_old=0.221,pw=0.8"
    assert vp.oc_key(14 / 63, 0.8) == "r=0.222,pwin=0.8"


needs_store = pytest.mark.skipif(not vp.S2_POWER.is_file(), reason=f"store not mounted ({gd.STORE})")


@needs_store
def test_the_port_reproduces_s2_power_and_recheck_on_the_old31_units():
    strata = vp._pinned_json(vp.S1_STRATA)
    sizes = vp.old31_sizes(strata)
    assert sizes == [9, 3, 2] + [1] * 17
    out = vp.reproduce(sizes, vp.magnitudes(strata), vp._pinned_json(vp.S2_POWER),
                       vp._pinned_json(vp.RECHECK))
    assert out["procedure_sim_equals_s2_power"] and out["question_oc_equals_recheck"]


@needs_store
def test_a_changed_archive_value_is_refused(monkeypatch):
    strata = vp._pinned_json(vp.S1_STRATA)
    key = vp.scenario_key(0.17, 0.8)
    s2 = {vp.ARCHIVE_PROC_KEY: {key: dict(vp._pinned_json(vp.S2_POWER)[vp.ARCHIVE_PROC_KEY][key])}}
    monkeypatch.setattr(vp, "SCENARIOS", ((0.17, 0.8),))
    args = ([9, 3, 2] + [1] * 17, vp.magnitudes(strata))
    assert vp.reproduce(*args, s2, vp._pinned_json(vp.RECHECK))["scenarios"] == 1
    s2[vp.ARCHIVE_PROC_KEY][key]["stop"] = 0.5
    with pytest.raises(gd.IntegrityError, match="s2_power.json"):
        vp.reproduce(*args, s2, vp._pinned_json(vp.RECHECK))
