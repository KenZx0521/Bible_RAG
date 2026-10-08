"""R2's G-NONINF / G-ANS (experiments/2026-10-09_r2/prereg.md): the R1 gates with R2's
protocol (C3 = the route-change slice of frozen_r2.json, sizes pinned by its sha256 only;
C2 = P1, CI lower of mean ΔMRR > −δ_mrr, δ_mrr = max(0.02, 2·B_mrr) from the A/A ΔMRR CI,
mean sign / W/L / sign test report-only) and src/r2_frozen.load_frozen, which refuses
everything until the freeze is pinned. R1's behaviour is test_noninf.py's and
test_freeze_r1.py's, unchanged; the R1 regression tests here pin its C2 and report layout.
"""

import hashlib
import json
from types import MappingProxyType

import pytest

import r1_gate
from src import noninf, r2_frozen
from src.ab_stats import sign_test_p
from src.gt_v2 import FREEZE_PATH
from src.r1_frozen import FrozenR1, FrozenR1Error

from test_noninf import FROZEN as FROZEN_R1
from test_noninf import IDS, LABELS, LEGACY, R1, answer_run, retrieval_run, shifted

R2 = "b20261009_0000abcd"
FAST = 1000
# route 0–29, books 28–31, lane 40–44: a 39-question slice, sizes the R1 prereg never fixed
FROZEN = FrozenR1(
    frozenset(IDS[0:32] + IDS[40:45]),
    MappingProxyType({"route": frozenset(IDS[0:30]), "books": frozenset(IDS[28:32]),
                      "lane": frozenset(IDS[40:45])}),
    frozenset(IDS[100:300]))


def gate(r=None, frozen=FROZEN, l2=None, n_boot=FAST):
    control = retrieval_run(R1)
    return noninf.retrieval_gate(control, l2 or control, r or retrieval_run(R2), frozen, LABELS,
                                 n_boot=n_boot, protocol=noninf.R2_PROTOCOL)


def mrr_moved(*moves, control=R1, build=R2):
    """The ``control`` build's run with MRR moved by each (delta, ids) of ``moves``, as
    ``build``."""
    run = retrieval_run(control)
    for delta, ids in moves:
        run = shifted(run, "mrr", delta, ids)
    run["meta"]["data_build_id"] = build
    return run


def r1_protocol_gate(*moves):
    """The same MRR moves judged by R1's protocol: legacy control, R1 treatment."""
    control = retrieval_run(LEGACY)
    return noninf.retrieval_gate(control, control, mrr_moved(*moves, control=LEGACY, build=R1),
                                 FROZEN_R1, LABELS, n_boot=FAST)


# 60 tiny losses, 10 large wins: mean sign −0.1, mean ΔMRR +0.0099
SMALL_LOSSES = ((-0.001, IDS[100:160]), (0.5, IDS[200:210]))
# 20 large losses, 60 tiny wins: mean sign +0.08, mean ΔMRR −0.0199
LARGE_LOSSES = ((-0.5, IDS[100:120]), (0.001, IDS[200:260]))
R1_AA_KEYS = ["pairing", "delta_vrec", "B", "delta", "mrr_win_loss", "B_wl", "delta_wl",
              "delta_mrr"]
R1_C2_KEYS = ["mean_sign", "threshold", "passed", "delta_mrr", "wins", "losses", "ties",
              "sign_test_p"]
R1_REPORT_ONLY_KEYS = ["strata", "deltas", "route_differs", "large_drops"]


def test_r2_protocol_takes_any_slice_size_and_the_same_200_subset():
    report = gate()
    assert report["passed"] and report["criteria"]["C3"]["union"]["n"] == 37
    assert set(report["criteria"]["C3"]["sub_slices"]) == {"route", "books", "lane"}
    small = FROZEN._replace(gans_subset=frozenset(IDS[100:150]))
    with pytest.raises(noninf.GateInputError, match="gans_subset has 50 questions, prereg 200"):
        gate(frozen=small)


def test_harm_on_the_route_change_slice_fails_c3_by_its_name():
    hurt = shifted(retrieval_run(R2), "verse_recall_at_k", -0.01, sorted(FROZEN.damaged_union))
    report = gate(r=hurt)
    assert not report["criteria"]["C3"]["passed"]
    assert any(r.startswith("C3: route-change-slice mean") for r in report["fail_reasons"])


def test_r1_protocol_still_pins_the_damaged_slice_sizes():
    control = retrieval_run()
    with pytest.raises(noninf.GateInputError, match="damaged union has 37 questions, prereg 64"):
        noninf.retrieval_gate(control, control, retrieval_run(R1), FROZEN, LABELS, n_boot=FAST)


# ---------------------------------------------------------------- the control arm's build

GATES = {"retrieval": (noninf.retrieval_gate, retrieval_run),
         "answer": (noninf.answer_gate, answer_run)}


@pytest.mark.parametrize("kind", sorted(GATES))
def test_each_protocol_fixes_its_control_build(kind):
    judge, run = GATES[kind]
    assert noninf.R1_PROTOCOL.control_build == LEGACY
    assert noninf.R2_PROTOCOL.control_build == R1
    control = run(LEGACY)
    with pytest.raises(noninf.GateInputError, match=(
            rf"control \w1 ran {LEGACY}, but {noninf.R2_PROTOCOL.prereg} fixes the control "
            rf"on {R1}")):
        judge(control, control, run(R2), FROZEN, LABELS, n_boot=FAST,
              protocol=noninf.R2_PROTOCOL)


@pytest.mark.parametrize("kind", sorted(GATES))
def test_r2_runs_judged_under_the_default_r1_protocol_are_refused(kind):
    judge, run = GATES[kind]
    control = run(R1)
    with pytest.raises(noninf.GateInputError, match=(
            rf"control \w1 ran {R1}, but {noninf.R1_PROTOCOL.prereg} fixes the control "
            rf"on {LEGACY}")):
        judge(control, control, run(R2), FROZEN_R1, LABELS, n_boot=FAST)


# ---------------------------------------------------------------- C2 = P1 (mean ΔMRR)

def test_identical_aa_sets_b_mrr_zero_and_the_floor_delta_mrr():
    report = gate()

    aa, c2 = report["aa"], report["criteria"]["C2"]
    assert noninf.R2_PROTOCOL.c2 == noninf.C2_DELTA_MRR
    assert aa["delta_mrr"]["ci"] == [0, 0]
    assert aa["B_mrr"] == 0 and aa["delta_mrr_margin"] == 0.02
    assert not {"mrr_win_loss", "B_wl", "delta_wl"} & set(aa)
    assert c2 == {"n": 500, "mean": 0, "ci": [0, 0], "threshold": -0.02, "passed": True}


def test_aa_mrr_noise_widens_delta_mrr_to_twice_b_mrr():
    l2 = mrr_moved((0.5, IDS[100:130]), (-0.5, IDS[130:160]), build=R1)
    r = mrr_moved((-0.1, IDS[300:420]))     # mean ΔMRR −0.024, CI lower ≈ −0.028

    report = gate(r=r, l2=l2)

    aa, c2 = report["aa"], report["criteria"]["C2"]
    lo, hi = aa["delta_mrr"]["ci"]
    assert aa["B_mrr"] == max(abs(lo), abs(hi)) > 0.01
    assert aa["delta_mrr_margin"] == 2 * aa["B_mrr"] > 0.02
    assert c2["threshold"] == -aa["delta_mrr_margin"]
    assert c2["threshold"] < c2["ci"][0] < -0.02    # passes on 2·B_mrr; the floor alone fails
    assert c2["passed"] and report["passed"]


def test_p1_passes_a_mean_mrr_drop_inside_delta_mrr():
    report = gate(r=mrr_moved((-0.1, IDS[100:150])))     # mean −0.01, CI lower ≈ −0.013

    c2 = report["criteria"]["C2"]
    assert c2["mean"] == pytest.approx(-0.01) and -0.02 < c2["ci"][0] < -0.01
    assert c2["passed"] and report["passed"] and report["fail_reasons"] == []


def test_p1_fails_a_mean_mrr_drop_beyond_delta_mrr():
    report = gate(r=mrr_moved((-0.05, IDS)))

    c2 = report["criteria"]["C2"]
    assert c2["ci"][0] == pytest.approx(-0.05) and c2["threshold"] == -0.02
    assert not c2["passed"] and not report["passed"]
    assert report["criteria"]["C1"]["passed"] and report["criteria"]["C3"]["passed"]
    assert report["fail_reasons"] == ["C2: CI lower of mean ΔMRR -0.0500 not > -0.0200"]


def test_p1_is_strict_a_ci_lower_equal_to_minus_delta_mrr_fails():
    control = retrieval_run(R1, mrr={q: 1.0 for q in IDS})     # dyadic steps stay exact
    l2 = shifted(control, "mrr", 1 / 64, IDS)                   # A/A CI [1/64, 1/64]
    r = shifted(control, "mrr", -1 / 32, IDS, build=R2)

    report = noninf.retrieval_gate(control, l2, r, FROZEN, LABELS, n_boot=FAST,
                                   protocol=noninf.R2_PROTOCOL)

    c2 = report["criteria"]["C2"]
    assert report["aa"]["delta_mrr_margin"] == 1 / 32
    assert c2["ci"][0] == c2["threshold"] == -1 / 32 and not c2["passed"]


def test_p1_fails_a_few_large_losses_that_mean_sign_lets_through():
    report = gate(r=mrr_moved(*LARGE_LOSSES))

    c2, signs = report["criteria"]["C2"], report["report_only"]["mrr_sign"]["r_vs_l1"]
    assert c2["mean"] == pytest.approx((0.06 - 10) / 500) and c2["ci"][0] < -0.02
    assert not c2["passed"] and not report["passed"]
    assert (signs["wins"], signs["losses"]) == (60, 20) and signs["mean_sign"]["ci"][0] > -0.02
    assert r1_protocol_gate(*LARGE_LOSSES)["criteria"]["C2"]["passed"]


def test_mean_sign_wins_losses_and_the_sign_test_are_report_only():
    report = gate(r=mrr_moved(*SMALL_LOSSES))

    c2, signs = report["criteria"]["C2"], report["report_only"]["mrr_sign"]
    assert list(c2) == ["n", "mean", "ci", "threshold", "passed"]
    assert c2["mean"] == pytest.approx((5 - 0.06) / 500) and c2["passed"] and report["passed"]
    r_vs_l1 = signs["r_vs_l1"]
    assert (r_vs_l1["wins"], r_vs_l1["losses"], r_vs_l1["ties"]) == (10, 60, 430)
    assert r_vs_l1["mean_sign"]["mean"] == pytest.approx(-50 / 500)
    assert r_vs_l1["mean_sign"]["ci"][0] < -0.02           # R1's C2 would have failed it
    assert r_vs_l1["sign_test_p"] == sign_test_p(10, 60) < 0.05
    assert signs["aa"] == {"mean_sign": {"n": 500, "mean": 0, "ci": [0, 0]},
                           "wins": 0, "losses": 0, "ties": 500, "sign_test_p": 1.0}


def test_r1_protocol_still_judges_c2_by_mean_sign_in_its_report_layout():
    report = r1_protocol_gate(*SMALL_LOSSES)

    aa, c2 = report["aa"], report["criteria"]["C2"]
    assert noninf.R1_PROTOCOL.c2 == noninf.C2_MEAN_SIGN
    assert list(aa) == R1_AA_KEYS and list(c2) == R1_C2_KEYS
    assert list(report["report_only"]) == R1_REPORT_ONLY_KEYS
    assert aa["B_wl"] == 0 and aa["delta_wl"] == 0.02 and c2["threshold"] == -aa["delta_wl"]
    assert c2["mean_sign"]["mean"] == pytest.approx(-50 / 500) and c2["delta_mrr"]["mean"] > 0
    assert (c2["wins"], c2["losses"], c2["ties"]) == (10, 60, 430)
    assert not c2["passed"] and not report["passed"]
    [reason] = report["fail_reasons"]
    assert reason.startswith("C2: CI lower of mean sign(ΔMRR) ") and reason.endswith(
        "not > -0.0200")


# ---------------------------------------------------------------- r2_frozen

def _freeze_doc(gt=None):
    pinned = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    block = lambda ids: {"question_ids": sorted(ids), "n_questions": len(ids)}  # noqa: E731
    return {"schema": r2_frozen.SCHEMA,
            "gt": gt or {"sha256": pinned["sha256"], "slot_universe": pinned["slot_universe"]},
            r2_frozen.SLICE_KEY: {"sub_slices": {k: block(v) for k, v in
                                                 FROZEN.sub_slices.items()},
                                  "union": block(FROZEN.damaged_union)},
            "gans_subset": block(FROZEN.gans_subset)}


def _write(tmp_path, doc):
    path = tmp_path / "frozen_r2.json"
    path.write_text(json.dumps(doc, sort_keys=True))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_nothing_is_read_before_the_freeze_is_pinned(tmp_path, monkeypatch):
    monkeypatch.setattr(r2_frozen, "FROZEN_R2_SHA256", None)
    path, _ = _write(tmp_path, _freeze_doc())
    with pytest.raises(FrozenR1Error, match="no freeze is pinned yet"):
        r2_frozen.load_frozen(path)


def test_the_pinned_freeze_reads_back_as_frozen_sets(tmp_path, monkeypatch):
    path, digest = _write(tmp_path, _freeze_doc())
    monkeypatch.setattr(r2_frozen, "FROZEN_R2_SHA256", digest)
    assert r2_frozen.load_frozen(path) == FROZEN
    path.write_text(path.read_text() + " ")
    with pytest.raises(FrozenR1Error, match="is not the pinned freeze"):
        r2_frozen.load_frozen(path)


def test_a_freeze_whose_union_or_gt_is_off_is_refused(tmp_path, monkeypatch):
    doc = _freeze_doc()
    doc[r2_frozen.SLICE_KEY]["union"] = {"question_ids": IDS[:3], "n_questions": 3}
    path, digest = _write(tmp_path, doc)
    monkeypatch.setattr(r2_frozen, "FROZEN_R2_SHA256", digest)
    with pytest.raises(FrozenR1Error, match="route-change union is not route ∪ books ∪ lane"):
        r2_frozen.load_frozen(path)
    path, digest = _write(tmp_path, _freeze_doc(gt={"sha256": "0" * 64, "slot_universe": "x"}))
    monkeypatch.setattr(r2_frozen, "FROZEN_R2_SHA256", digest)
    with pytest.raises(FrozenR1Error, match="is not GT v2's frozen"):
        r2_frozen.load_frozen(path)


# ---------------------------------------------------------------- CLI

@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(r1_gate, "gt_labels", lambda: LABELS)
    monkeypatch.setattr(r1_gate, "load_frozen_r2", lambda path: FROZEN)
    monkeypatch.setattr(r1_gate, "load_frozen",
                        lambda path: pytest.fail("R2 must not read the R1 freeze"))

    def run(kind, runs, *extra, prereg="r2"):
        paths = []
        for name, data in zip(("c", "aa", "t"), runs):
            paths.append(tmp_path / f"{name}.json")
            paths[-1].write_text(json.dumps(data))
        out = tmp_path / "report.json"
        code = r1_gate.main([kind, *(("--prereg", prereg) if prereg else ()),
                             "--aa", str(paths[0]), str(paths[1]),
                             "--treatment", str(paths[2]), "--frozen", str(tmp_path / "f.json"),
                             "--out", str(out), "--overwrite", *extra])
        return code, json.loads(out.read_text()) if out.exists() else None
    return run


def test_cli_prereg_r2_reads_the_r2_freeze_and_names_the_r2_prereg(cli, capsys):
    code, report = cli("retrieval", (retrieval_run(R1), retrieval_run(R1), retrieval_run(R2)))
    assert code == 0 and report["prereg"] == noninf.R2_PROTOCOL.prereg
    out = capsys.readouterr().out
    assert "C3   route-change slice Δvrec@6" in out
    assert "B_mrr=0.0000  δ_mrr=0.0200" in out and "C2   ΔMRR +0.0000" in out
    assert "  MRR sign R−L1: mean +0.0000" in out and "B_wl" not in out
    code, report = cli("retrieval", (retrieval_run(R1), retrieval_run(R1),
                                     mrr_moved((-0.05, IDS))))
    assert code == 1 and report["fail_reasons"] == [
        "C2: CI lower of mean ΔMRR -0.0500 not > -0.0200"]
    assert "G-NONINF: FAIL" in capsys.readouterr().out
    code, report = cli("answer", (answer_run(R1), answer_run(R1), answer_run(R2)))
    assert code == 0 and report["params"]["subset_size"] == 200


@pytest.mark.parametrize("kind", sorted(GATES))
def test_cli_without_prereg_r2_refuses_r2_runs_even_with_the_r1_freeze(cli, monkeypatch,
                                                                        capsys, kind):
    monkeypatch.setattr(r1_gate, "load_frozen", lambda path: FROZEN_R1)
    run = GATES[kind][1]

    code, report = cli(kind, (run(R1), run(R1), run(R2)), prereg=None)

    assert code == r1_gate.EXIT_INPUT and report is None
    err = capsys.readouterr().err
    assert f"fixes the control on {LEGACY}" in err and "--prereg" in err
