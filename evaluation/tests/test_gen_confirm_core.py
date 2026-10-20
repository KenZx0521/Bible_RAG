"""GEN confirmation set: store guard, test replica, power model, gate and writing order (prereg §2, §7).

Unit tests use a made-up pool (ids, edges and persons only). Store tests read pool.json and
power/power_g_tables.json, recompute cells next to the 0.70 cutoff with the frozen gate, and skip when the store
is not mounted. Nothing calls Ollama or any LLM.
"""

import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import g_common as GC  # noqa: E402
import order_g as O  # noqa: E402
import power_g as PG  # noqa: E402
from src import ab_stats  # noqa: E402

needs_store = pytest.mark.skipif(not GC.POOL.is_file(), reason=f"store not mounted ({GC.POOL})")
TABLES = GC.OUT_ROOT / "power/power_g_tables.json"


def fake_pool() -> list[dict]:
    """Two chains of six persons; F1/F5 slots on pairs at distance 2–4 (made-up ids)."""
    slots, k = [], 0
    for ch, tag in ((5, "a"), (11, "b")):
        chain = [f"{tag}{i}" for i in range(6)]
        for i in range(6):
            for j in range(i + 2, min(i + 5, 6)):
                for qt in ("F1", "F5"):
                    slots.append(dict(sid=f"S{k:02d}", qtype=qt, chapter=ch, stratum=f"{qt}c{ch}", x=chain[i],
                                      y=chain[j], edges=[f"{chain[t]}>{chain[t + 1]}" for t in range(i, j)],
                                      homonym=(j == 5)))
                    k += 1
    return slots


# ---------------------------------------------------------------- store guard
def test_writable_refuses_the_repo_and_every_frozen_store_folder(tmp_path):
    for p in (GC.REPO / "x.json", GC.STAGE0_OUT / "x.json", GC.STORE / "reports/kg_cards_20261018/A/x.json",
              GC.STORE / "reports/other/x.json", GC.STORE / "layers/x.json"):
        with pytest.raises(SystemExit):
            GC.writable(p)
    assert GC.writable(GC.OUT_ROOT / "power/x.json") == (GC.OUT_ROOT / "power/x.json").resolve()
    assert GC.writable(tmp_path / "x.json") == (tmp_path / "x.json").resolve()


def test_g_common_imports_neither_a_nor_stage0_constants():
    code = f"import sys; sys.path.insert(0, {str(H)!r}); import g_common; print('c_common' in sys.modules, 'x_common' in sys.modules)"
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False", "False"]


def test_the_money_constants_are_this_experiments():
    assert Path(GC.__file__).resolve().parent == H.resolve()
    assert GC.OUT_ROOT == GC.STORE / "reports/gen_confirm_20261020"
    assert GC.HO_ROOT.parent == GC.OUT_ROOT and GC.QSET_ROOT.parent == GC.OUT_ROOT
    assert (GC.USD_CAP, GC.START_MARGIN_USD, GC.PROBE_CAP_USD, GC.QSET_CAP_USD, GC.KP_BUDGET_USD) == (50.0, 1.0, 1.0, 3.0, 47.0)
    assert GC.JOB_CAP_USD == {"draft": 2.0, "fix": 1.5, "audit": 1.0}
    assert (GC.MAX_ATTEMPTS, GC.FIX_SOURCES, GC.MAX_FIX_ROUNDS, GC.MAX_INFRA_RETRIES, GC.PILOT, GC.KAY_QUESTIONS) == (
        3, ("mech", "audit", "kay"), 1, 2, 12, 10)
    assert (GC.PROBE_MAX_RUNS, GC.QSET_JOB_CAP_USD) == (2, {"gen": 0.2, "label": 0.2})
    for path in (GC.POOL, GC.GEN_NAMES, GC.F1A_LOG, GC.F1_MANIFEST, GC.ORDER, GC.QUESTIONS_FROZEN):
        assert path.parent == GC.OUT_ROOT
    assert O.F1_MANIFEST == GC.F1_MANIFEST and O.ORDER == GC.ORDER


def test_stage0_modules_come_from_stage0s_folder():
    S = GC.stage0()
    for name in ("x_common", "gen_layer", "items_x", "engine_x", "keys_x"):
        assert Path(getattr(S, name).__file__).resolve().parent == GC.STAGE0_DIR.resolve()


def test_backend_pins_cover_the_parity_and_trigger_files():
    pins = GC.backend_pins() if GC.R4_LAYER.is_file() else {f: "" for f in GC.BACKEND_PIN_FILES}
    for f in ("backend/utils/generator.py", "backend/utils/regnal/trigger.py"):
        assert f in pins


# ---------------------------------------------------------------- the test replica
@pytest.mark.parametrize("seed", range(6))
def test_signflip_replica_equals_ab_stats_on_both_branches(seed):
    g = np.random.default_rng(seed)
    for _ in range(12):
        n = int(g.integers(3, 59))
        D3 = (g.integers(-3, 4, n) * (g.random(n) > g.random())).astype(np.float32)
        real = ab_stats.sign_flip_p([x / 3 for x in D3.tolist()], seed=GC.TEST_SEED)
        assert float(PG.signflip_p(D3[None, :])[0]) == pytest.approx(real, abs=0)


def test_signflip_of_all_zero_is_one():
    assert PG.signflip_p(np.zeros((2, 7)))[0] == 1.0


# ---------------------------------------------------------------- model and gate
def test_mean_match_centres_the_arm_mean():
    mu = PG.mean_match(0.5648, 3.9)
    z = np.random.default_rng(1).normal(0, 1, 400000)
    assert float(PG.expit(mu + 3.9 * z).mean()) == pytest.approx(0.5648, abs=0.003)


def test_allocation_is_proportional_and_sums_to_n():
    P = PG.Pool(fake_pool())
    for n in (5, 17, 30, P.n):
        alloc = P.allocation(n)
        assert sum(alloc) == n and all(a >= 0 for a in alloc)
    assert P.allocation(P.n) == np.bincount(P.STRAT, minlength=4).tolist()


def test_draw_sets_respects_the_strata_counts():
    P = PG.Pool(fake_pool())
    alloc = P.allocation(10)
    sets = P.draw_sets(np.random.default_rng(0), 50, alloc)
    for row in sets:
        assert np.bincount(P.STRAT[row], minlength=4).tolist() == alloc
        assert len(set(row.tolist())) == 10


def test_power_is_deterministic_and_ordered():
    P = PG.Pool(fake_pool())
    one = PG.power(P, nsim=300)
    assert one == PG.power(P, nsim=300)
    assert 0 <= one["pow_H1_and_H2"] <= one["pow_H1"] <= 1


def test_gate_caps_a_and_floors_w():
    P = PG.Pool(fake_pool())
    out = PG.gate(P, 0.99, 0.0, alloc=P.allocation(P.n))
    assert (out["a"], out["w"]) == (0.875, 0.05)
    assert out["pow_H1_and_H2"] == PG.power(P, alloc=P.allocation(P.n), a=0.875, w=0.05)["pow_H1_and_H2"]
    kept = PG.gate(P, 0.80, 0.07, alloc=P.allocation(P.n))
    assert (kept["a"], kept["w"]) == (0.8, 0.07)


def test_coverage_is_centred_on_the_evaluated_slots():
    P = PG.Pool(fake_pool())
    cols = np.where(~P.HOM)[0]
    cov = PG._coverage(np.random.default_rng(0), P, 200, 0.80, PG.M1, cols)
    assert np.allclose(cov[:, cols].mean(1), 0.80, atol=1e-6)
    pool_wide = PG._coverage(np.random.default_rng(0), P, 200, 0.80, PG.M1)
    assert np.allclose(pool_wide.mean(1), 0.80, atol=1e-6)
    assert pool_wide[:, cols].mean() > 0.80          # homonym ends are shifted down, so the rest sit higher


def test_power_sorts_slot_idx_and_refuses_duplicates():
    P = PG.Pool(fake_pool())
    a = PG.power(P, slot_idx=[5, 1, 3, 2, 9, 7], nsim=200)
    b = PG.power(P, slot_idx=[1, 2, 3, 5, 7, 9], nsim=200)
    assert a == b
    with pytest.raises(ValueError):
        PG.power(P, slot_idx=[1, 1, 2], nsim=50)


def test_kp_n_rounds_half_up_in_exact_fractions():
    assert PG.kp_n(9, 12, 54) == 41                  # 40.5 -> 41 (Python's round would give 40)
    assert PG.kp_n(12, 12, 58) == 53                 # capped at 0.914: 53.012 -> 53
    assert PG.kp_n(10, 12, 51) == 43                 # 42.5 -> 43


def test_g1_uses_point_estimates_and_floors_w():
    P = PG.Pool(fake_pool())
    out = PG.g1(P, 40, 1, 50, n=20)
    assert (out["a"], out["w"], out["n"]) == (0.8, 0.05, 20)
    assert PG.g1(P, 40, 4, 50, n=20)["w"] == 0.08


def test_p_g1_pass_is_a_probability():
    thr = {0: 37, 1: 37, 2: 37}
    assert PG.p_g1_pass(thr, 1.0, 0.0) == pytest.approx(1.0)
    assert 0 < PG.p_g1_pass(thr, 0.8, 0.02) < 1
    assert PG.p_g1_pass({}, 0.9, 0.0) == 0.0


def test_type_one_sharp_null_rejects_rarely():
    P = PG.Pool(fake_pool())
    out = PG.type_one(P, P.n, nsim=600)
    assert out["two_sided"] < 0.09 and out["claim"] <= out["two_sided"]


# ---------------------------------------------------------------- order
def test_order_is_deterministic_complete_and_near_proportional():
    slots = fake_pool()
    a, b = O.order(slots, 123), O.order(slots, 123)
    assert a == b and sorted(a) == sorted(s["sid"] for s in slots)
    assert O.order(slots, 124) != a
    strat = {s["sid"]: s["stratum"] for s in slots}
    N = {st: sum(s["stratum"] == st for s in slots) for st in O.STRATA}
    for k in (8, 12, 20):
        got = {st: sum(strat[x] == st for x in a[:k]) for st in O.STRATA}
        assert all(abs(got[st] - k * N[st] / len(slots)) <= 1 for st in O.STRATA)


def test_order_seed_comes_from_the_canonical_files_map():
    assert O.seed_from("00000000000000ff" + "0" * 48) == 255
    a = {"utc": "2026-10-21T01:00:00Z", "files": {"b.py": "22", "a.py": "11"}}
    b = {"utc": "2026-10-22T09:00:00Z", "files": {"a.py": "11", "b.py": "22"}}
    assert O.files_digest(a) == O.files_digest(b)
    assert O.files_digest(a) != O.files_digest({"files": {"a.py": "11", "b.py": "23"}})


def test_order_refuses_before_f1(monkeypatch, tmp_path):
    monkeypatch.setattr(O, "F1_MANIFEST", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        O.main()


def test_order_refuses_a_second_draw(monkeypatch, tmp_path):
    (tmp_path / "f1.json").write_text(json.dumps({"files": {"a.py": "11"}}))
    (tmp_path / "order.json").write_text("{}")
    monkeypatch.setattr(O, "F1_MANIFEST", tmp_path / "f1.json")
    monkeypatch.setattr(O, "ORDER", tmp_path / "order.json")
    with pytest.raises(SystemExit):
        O.main()


# ---------------------------------------------------------------- store
@needs_store
def test_pool_is_the_registered_pool():
    assert GC.sha256_file(GC.POOL) == PG.POOL_SHA256
    s = GC.read_json(GC.POOL)["summary"]
    assert s["n"] == 58 and s["by_stratum"] == {"F1c5": 14, "F1c11": 12, "F5c5": 26, "F5c11": 6}
    assert (s["pairs"], s["top_x"], s["edges"], s["marker_required"], s["homonym_end"]) == (44, 15, 17, 6, 14)
    assert s["k0_gold"] == "58/58" and s["k0_card"] == "58/58" and s["k0_lines"] == "96/96"
    assert s["coincide"] == 0 and s["max_chars_g"] <= 900 and s["dev_slots_held_out"] == 14


@needs_store
def test_order_on_the_real_pool_keeps_every_slot():
    slots = GC.read_json(GC.POOL)["pool"]
    ids = O.order(slots, O.seed_from("ab" * 32))
    assert sorted(ids) == sorted(s["sid"] for s in slots) and len(ids) == 58


def test_signs_are_drawn_like_ab_stats():
    u = random.Random(GC.TEST_SEED)
    first = [1.0 if u.random() < 0.5 else -1.0 for _ in range(17 * 3)]
    assert PG._mc_signs(17)[:3].ravel().tolist() == first


@needs_store
def test_tables_were_made_by_this_power_g():
    t = json.loads(TABLES.read_text(encoding="utf-8"))
    assert t["power_g_sha256"] == GC.sha256_file(H / "power_g.py")
    assert t["pool_sha256"] == GC.POOL_SHA256 and t["numpy"] == np.__version__


@needs_store
def test_frozen_gate_reproduces_cells_next_to_the_cutoff():
    t = json.loads(TABLES.read_text(encoding="utf-8"))
    P = PG.load_pool()
    a53 = t["amin"]["w0.05"]["53"]
    assert PG.gate(P, a53, 0.05, alloc=P.allocation(53))["pass"]
    assert not PG.gate(P, round(a53 - 0.025, 3), 0.05, alloc=P.allocation(53))["pass"]
    k = t["g1"]["R_wrong=0"]
    assert PG.g1(P, k, 0, 50)["pass"] and not PG.g1(P, k - 1, 0, 50)["pass"]
    c = t["ka_thresholds_n53"]["0"]
    assert PG.ka_threshold(P, 53, 0) == c
    ii53 = next(c for c in t["corners"] if c["tag"] == "ii" and c["n"] == 53)
    assert PG.power(P, alloc=P.allocation(53))["pow_H1_and_H2"] == ii53["pow_H1_and_H2"]
