"""GD experiment E2 pool, V1 stop rule, D5≈ and [SHORTCUT] (evaluate.py, _eval_report.py).

Unit tests on hand-built items: the E2 pool OLD31 ∪ HO is clustered as one table, with the
by-set strata, the 16-question exclusion, the HO-only note and H3 without [SHORTCUT]
questions all computed (§5); V1 stops on ≥3 discordant units with losses ≥ wins and
reports nothing else (§6); D5≈ is the R20 top 5 by (−score, pid) (§4). With the store
mounted, merge() joins two real question sets into one table.
"""

import importlib.util
import sys
from fractions import Fraction as F
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if "gd_evaluate" in sys.modules:
    ev = sys.modules["gd_evaluate"]
else:
    _SPEC_EV = importlib.util.spec_from_file_location("gd_evaluate", _DIR / "evaluate.py")
    ev = importlib.util.module_from_spec(_SPEC_EV)
    sys.modules["gd_evaluate"] = ev
    _SPEC_EV.loader.exec_module(ev)
M, R = ev.M, ev.R

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

FILL = [f"ps:f{i}" for i in range(5)]
SCORES = {**{p: 0.9 - 0.1 * i for i, p in enumerate(FILL)}, "ps:a": 0.95, "ps:b": 0.95, "ps:s": 0.95,
          **{f"ps:h{i}": 0.95 for i in range(1, 7)}}
SHARED = frozenset({"ps:s"})                    # stands for the NEW82 gold


def item(qid, set_name, gold, shortcut=None, prod=None):
    return R.Item(qid, set_name, gd.KIN, (frozenset(gold),), frozenset({0}), None, F(1, 2),
                  shortcut, prod)


def e2_table():
    """OLD31 O1/O2 share ps:a (one unit), O3 shares ps:s with NEW82; HO H1..H6, H2 [SHORTCUT].
    GD finds the gold everywhere but O2; C never; L finds it on H2 and H3, LEXPRF on H2."""
    items = [item("O1", "old31", {"ps:a"}, prod=frozenset({0})),
             item("O2", "old31", {"ps:a", "ps:b"}, prod=frozenset()),
             item("O3", "old31", {"ps:s"}, prod=frozenset({0}))]
    items += [item(f"H{i}", "ho", {f"ps:h{i}"}, shortcut=(i == 2)) for i in range(1, 7)]
    gold = {it.qid: sorted(it.gold[0])[0] for it in items}
    hits = {"C": set(), "GD": set(gold) - {"O2"}, "L": {"H2", "H3"}, "LEXPRF": {"H2"}}
    pools = {arm: {q: tuple(FILL) + ((gold[q],) if q in won else ()) for q in gold}
             for arm, won in hits.items()}
    return items, R.Table(items, pools, {q: SCORES for q in gold})


def test_the_e2_pool_is_clustered_as_one_table_and_split_by_set():
    items, table = e2_table()
    assert R.unit_table(items)["n_units"] == 8
    strata = R.subsets(items, SHARED)
    assert {k: len(v) for k, v in strata["by_set"].items()} == {"ho": 6, "old31": 3}
    assert [it.qid for it in strata["excl_new82_shared"]["kept"]] == ["O1", "O2", *[f"H{i}" for i in range(1, 7)]]
    row = R.sensitivity(table, SHARED)["GD-C@10"]
    assert (row["by_set"]["old31"]["n_units"], row["by_set"]["ho"]["n_units"]) == (2, 6)
    assert row["excl_new82_shared"]["kept"]["n_questions"] == 8


def test_h1_on_the_pool_and_the_attached_notes():
    _, table = e2_table()
    hyp = R.hypotheses(table)
    assert (hyp["H1"]["unit_W:L"], hyp["H1"]["p_exact"], hyp["H1"]["pass"]) == ("8:0", "1/128", True)
    notes = R.attached_notes(table, hyp, SHARED)
    assert notes == {"ho_only_mean_le_0": False, "excl_new82_shared_mean_le_0": False}


def test_h3_is_also_reported_without_the_shortcut_questions():
    _, table = e2_table()
    out = R.sensitivity(table, SHARED)["H3_excl_shortcut"]
    assert out["excluded"] == ["H2"]
    assert out["GD-L@10"]["n_questions"] == 8 and out["GD-L@10"]["question_W:L"] == "6:0"
    assert out["GD-LEXPRF@10"]["question_W:L"] == "7:0"


def test_h3_without_shortcut_needs_the_flag_on_every_ho_item():
    items, table = e2_table()
    broken = [R.Item(**{**it.__dict__, "shortcut": None}) if it.qid == "H1" else it for it in items]
    with pytest.raises(gd.GdError, match="SHORTCUT"):
        R.h3_without_shortcut(R.Table(broken, table.pools, table.scores))
    only_old = [it for it in items if it.set_name == "old31"]
    assert "not_applicable" in R.h3_without_shortcut(R.Table(only_old, table.pools, table.scores))


def test_missing_hops_are_counted_per_set_and_prod_d5_only_on_old31():
    _, table = e2_table()
    m = R.arm_metrics(table, "GD", 10)
    assert m["missing_hops_hit"] == 8 and m["missing_hops_hit_by_set"] == {"ho": 6, "old31": 2}
    assert m["missing_hops_hit_prod_d5"] == 2                       # O1 and O3 carry prod D5 hop 0
    summary = R.missing_summary(table.items)
    assert summary["old31"]["prod_d5_hops"] == 2 and "prod_d5_hops" not in summary["ho"]


# ---------------------------------------------------------------- §6 V1

@pytest.mark.parametrize("values, stop", [
    ([F(1), F(-1), F(-1)], True),                  # 3 discordant, losses ≥ wins
    ([F(-1), F(-1), F(0)], False),                 # only 2 discordant
    ([F(1), F(1), F(-1), F(-1)], True),            # 2:2
    ([F(1), F(1), F(1), F(-1)], False),            # 3:1
    ([F(1, 2), F(-1, 3), F(-1, 4), F(0), F(0)], True),
])
def test_v1_stops_on_three_discordant_units_with_losses_at_least_wins(values, stop):
    out = R.v1_decision(values)
    assert out["stop"] is stop and out["n_units"] == len(values)


def test_v1_reports_only_the_decision_and_the_unit_w_l():
    items, table = e2_table()
    old = [it for it in items if it.set_name == "old31"]
    out = R.v1(R.Table(old, table.pools, table.scores))
    assert set(out) == {"n_units", "unit_W:L", "discordant_units", "stop", "rule"}
    assert (out["n_units"], out["unit_W:L"], out["stop"]) == (2, "2:0", False)


# ---------------------------------------------------------------- §4 D5≈

def test_d5_approx_takes_the_r20_top_five_by_score_then_pid():
    scores = {"ps:a": 0.5, "ps:b": 0.9, "ps:c": 0.5, "ps:d": 0.1, "ps:e": 0.7, "ps:f": 0.5, "ps:g": 0.2}
    r20 = ["ps:g", "ps:f", "ps:e", "ps:d", "ps:c", "ps:b", "ps:a"]
    assert M.d5_approx(r20, scores) == ("ps:b", "ps:e", "ps:a", "ps:c", "ps:f")
    gold = (frozenset({"ps:d"}), frozenset({"ps:a", "ps:x"}), frozenset({"ps:g"}))
    assert M.d5_missing(gold, r20, scores) == {0, 2}
    with pytest.raises(gd.GdError):
        M.d5_approx([], scores)


# ---------------------------------------------------------------- store: merge()

def fake_part(qs, d5_hit):
    """Lists / scores stand-ins: pool = 5 fillers + the first gold passage; R20 = fillers, plus
    the gold for the questions in d5_hit (so D5≈ finds it there)."""
    gold = {q.qid: sorted(gd.question_gold(q)[0])[0] for q in qs.questions}
    pools = {a: {q: tuple(FILL) + (g,) for q, g in gold.items()} for a in M.TESTED_ARMS}
    r20 = {q: tuple(FILL) + ((g,) if q in d5_hit else ()) for q, g in gold.items()}
    scores = {q: {**SCORES, g: 0.95} for q, g in gold.items()}
    return ev.Part(qs, SimpleNamespace(arms=M.TESTED_ARMS, pools=pools, r20=r20),
                   SimpleNamespace(by_qid=scores))


def renamed(qs, name, ids):
    return gd.QuestionSet(name, tuple(gd.Question(i, q.question, q.category, q.hops, None, q.core,
                                                  shortcut=False if name == "ho" else None)
                                      for i, q in zip(ids, qs.questions[:len(ids)])),
                          MappingProxyType({}))


@needs_store
def test_merge_joins_two_sets_with_d5_missing_hops_and_refuses_overlaps():
    old = gd.QuestionSet("old31", gd.load_old31().questions[:2], MappingProxyType({}))
    ho = renamed(gd.load_new82(), "ho", ["H_KIN_01", "H_KIN_02"])
    items, table = ev.merge([fake_part(old, {old.ids[0]}), fake_part(ho, set())])
    assert [it.set_name for it in items] == ["old31", "old31", "ho", "ho"]
    assert all(it.missing_source == R.SOURCE_D5 for it in items)
    assert 0 not in items[0].missing and 0 in items[1].missing and 0 in items[2].missing
    assert set(table.pools["GD"]) == {it.qid for it in items} and table.arms == M.TESTED_ARMS
    with pytest.raises(gd.IntegrityError):
        ev.merge([fake_part(old, set()), fake_part(old, set())])
    other = fake_part(ho, set())
    other.lists.arms = ("C", "GD")
    with pytest.raises(gd.GdError, match="different arms"):
        ev.merge([fake_part(old, set()), other])
