"""Ordered-chain arithmetic stage-0 power report (power_x.py; prereg §7-5).

The model is a copy of the store's powerA_strong.py; the copy check and the pin check need the store and
skip without it. The pooling and adjustment tests use made-up item values. Ollama is never called.
"""

import importlib
import sys
from fractions import Fraction
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import x_common as X  # noqa: E402
import power_x as P  # noqa: E402

needs_src = pytest.mark.skipif(not X.POWER_SRC.is_file(), reason=f"store not mounted ({X.POWER_SRC})")
ARGS = dict(C=9, m=3, a=0.875, h=0.85, pR=0.65, gap=0.23, nsim=60)


def row(i, family, covered, nested, pG, pR, pC):
    return {"id": f"{family}_{i:02d}", "family": family, "covered": covered, "nested": nested,
            "pG": pG, "pR": pR, "pC": pC}


ROWS = [row(1, "DYN", True, True, Fraction(1), Fraction(1, 3), Fraction(0)),
        row(2, "DYN", True, False, Fraction(2, 3), Fraction(0), Fraction(0)),
        row(3, "DYN", True, False, Fraction(1), Fraction(2, 3), Fraction(1, 3)),
        row(4, "DYN", False, False, Fraction(0), Fraction(1, 3), Fraction(0))]


# ---------------------------------------------------------------- the copied model
def test_two_identical_cell_calls_give_identical_results():
    assert P.cell(**ARGS) == P.cell(**ARGS)


def test_cell_does_not_depend_on_call_order():
    first = P.cell(**ARGS)
    P.cell(C=17, m=4, a=0.5, h=0.6, pR=0.3, gap=0.1, nsim=40)
    P.cell(C=5, m=2, a=0.9, h=0.9, pR=0.2, gap=0.05, nsim=40)
    assert P.cell(**ARGS) == first


def test_cell_keeps_the_store_models_output_fields():
    out = P.cell(**ARGS)
    assert set(out) == {"C", "m", "a", "h", "pR", "gap", "pow_H1", "pow_H1_and_H2", "mean_d1", "mean_d2"}
    assert 0 <= out["pow_H1_and_H2"] <= out["pow_H1"] <= 1


@needs_src
def test_the_copied_block_is_the_store_model_verbatim():
    src = X.POWER_SRC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(src) if ln.startswith("rng = np.random.default_rng("))
    end = next(i for i, ln in enumerate(src) if ln.startswith("if __name__"))
    want = "\n".join(src[start:end]).strip().replace("\ndef cell(", "\ndef _cell(")
    assert P.copied_block().strip() == want
    assert P.SOURCE_CHECKED is True


@needs_src
def test_import_refuses_a_source_that_is_not_the_pinned_one(monkeypatch):
    monkeypatch.setattr(X, "POWER_SRC_SHA256", "0" * 64)
    with pytest.raises(SystemExit):
        importlib.reload(P)
    monkeypatch.undo()
    importlib.reload(P)


# ---------------------------------------------------------------- inputs (i) template, (ii) shrink-adjusted
def test_pooled_inputs_are_item_weighted_and_exact():
    p = P.pooled(ROWS)
    assert (p["n_items"], p["n_covered"], p["a"], p["h"], p["pR"], p["pC"]) == (
        4, 3, Fraction(3, 4), Fraction(8, 9), Fraction(1, 3), Fraction(1, 12))


def test_model_inputs_template_and_shrink_adjusted():
    p = P.pooled(ROWS)
    i, ii = P.model_inputs(p, adjusted=False), P.model_inputs(p, adjusted=True)
    assert i == pytest.approx({"a": 0.75, "h": 8 / 9, "pR": 1 / 3, "pC": 1 / 12, "gap": 0.25, "gap_raw": 0.25})
    assert ii == pytest.approx({"a": 0.75, "h": 8 / 9 - 0.05, "pR": 1 / 3 + 0.25, "pC": 1 / 12 + 0.22,
                                "gap": 0.28, "gap_raw": 0.28})
    full = P.model_inputs(dict(p, a=Fraction(1)), adjusted=True)
    assert full["a"] == 0.875


def test_model_inputs_clamp_h_pr_pc_and_gap_but_not_a():
    p = {"n_items": 2, "n_covered": 2, "a": Fraction(1), "h": Fraction(1), "pR": Fraction(0), "pC": Fraction(1, 2)}
    i = P.model_inputs(p, adjusted=False)
    assert (i["a"], i["h"], i["pR"], i["pC"], i["gap"]) == (1.0, 0.99, 0.01, 0.5, 0.01)
    assert i["gap_raw"] == -0.5
    none = P.model_inputs(dict(p, h=None, n_covered=0, a=Fraction(0)), adjusted=False)
    assert (none["a"], none["h"]) == (0.0, 0.01)


def test_values_may_come_as_score_x_fraction_dicts():
    rows = [dict(r, pG={"frac": str(r["pG"]), "float": float(r["pG"])}) for r in ROWS]
    assert P.pooled(rows) == P.pooled(ROWS)


# ---------------------------------------------------------------- the report
@pytest.fixture(scope="module")
def report():
    return P.power_report(ROWS, C_values=(9,), m_values=(2, 3), nsim=40)


def test_report_has_both_input_sets_cells_and_minimal_c(report):
    a = report["subsets"]["all"]
    assert set(a["inputs"]) == {"i", "ii"} and set(a["cells"]) == {"i", "ii"}
    assert [(c["C"], c["m"]) for c in a["cells"]["ii"]] == [(9, 2), (9, 3)]
    for s in ("i", "ii"):
        for m in (2, 3):
            got = a["min_C"][s][str(m)]
            grid = {c["C"]: c["pow_H1_and_H2"] for c in a["search"][s][str(m)]}
            assert sorted(grid) == list(range(8, 18))
            ok = [C for C in sorted(grid) if grid[C] >= 0.7]
            assert got["C"] == (ok[0] if ok else None)
            assert got["note"] == (None if ok else "資料上限內達不到 0.7")
    assert report["model"]["seed"] == 20261018 and report["C_search"] == [8, 17]


def test_report_nested_subset_and_unit_note(report):
    nested = report["subsets"]["nested"]
    assert nested["pooled"]["n_items"] == 1
    assert report["nested_check"] == {"DYN": {"n_items": 4, "n_nested": 1, "redefine_units": True,
                                              "note": "確認集的單位要重新定義，C＝9／8 的檢定力不適用"}}


def test_report_without_nested_items_says_so():
    rows = [dict(r, nested=False) for r in ROWS]
    rep = P.power_report(rows, C_values=(9,), m_values=(3,), nsim=20)
    assert rep["subsets"]["nested"] is None and rep["nested_check"]["DYN"]["redefine_units"] is True


def test_report_is_reproducible():
    a = P.power_report(ROWS, C_values=(8,), m_values=(3,), nsim=20)
    b = P.power_report(ROWS, C_values=(8,), m_values=(3,), nsim=20)
    assert a == b


def test_no_effect_cannot_reach_target():
    rows = [row(i, "GEN", True, True, Fraction(1, 3), Fraction(1, 3), Fraction(1, 3)) for i in range(6)]
    rep = P.power_report(rows, C_values=(8,), m_values=(2,), nsim=20)
    assert rep["subsets"]["all"]["min_C"]["i"]["2"] == {"C": None, "note": "資料上限內達不到 0.7"}


def test_rows_from_scores_take_b0_as_pc_for_gen():
    scores = {"items": {
        "S5_01": {"mean": {"G": {"frac": "1"}, "T-rows": {"frac": "1/3"}, "T-canon": {"frac": "0"}, "B0": {"frac": "0"}}},
        "F1_01": {"mean": {"G": {"frac": "2/3"}, "T-rows": {"frac": "1/3"}, "B0": {"frac": "1/3"}}}}}
    items = [{"id": "S5_01", "family": "DYN", "nested": True}, {"id": "F1_01", "family": "GEN", "nested": False},
             {"id": "SY_01", "family": "SYNC", "nested": False}]
    rows = P.rows_from_scores(scores, items, covered={"S5_01": True, "F1_01": False}, families=("DYN", "GEN"))
    assert rows == [row(1, "S5", True, True, Fraction(1), Fraction(1, 3), Fraction(0)) | {"id": "S5_01", "family": "DYN"},
                    row(1, "F1", False, False, Fraction(2, 3), Fraction(1, 3), Fraction(1, 3)) | {"id": "F1_01",
                                                                                                    "family": "GEN"}]
