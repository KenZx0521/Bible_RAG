"""R1 gates G-NONINF and G-ANS (experiments/2026-10-08_r1/prereg.md).

Synthetic runs over 500 question ids: the A/A pair sets the margins
(δ = max(0.02, 2B), δ_wl = max(0.02, 2·B_wl), δ_ans = max(0.01, 2·B_ans)),
C1 / C2 / C3 judge the treatment against L1, invalid questions are dropped
from pairing (fewer than 495 pairs fails: rerun the arm), and inputs the
protocol does not allow are refused before anything is computed.
"""

import copy
import json
import math
from types import MappingProxyType

import pytest

import r1_gate
from src import noninf
from src.ab_stats import bootstrap_ci, sign_test_p
from src.data_loader import load_gt
from src.r1_frozen import FrozenR1

TYPES = ("VERSE_LOOKUP", "TOPIC_QUESTION", "PERSON_QUESTION", "EVENT_QUESTION",
         "GENERAL_BIBLE_QUESTION")
IDS = [f"Q{i:03d}" for i in range(500)]
LABELS = noninf.GtLabels("gtsha", {
    q: noninf.Label(TYPES[i % 5], "legacy_head" if i < 100 else "paraphrase")
    for i, q in enumerate(IDS)})
# Damaged union = IDS[:64]: G01 0–55, G15 53–63, G02 55–63 (56 / 11 / 9 questions).
FROZEN = FrozenR1(
    frozenset(IDS[:64]),
    MappingProxyType({"G01": frozenset(IDS[0:56]), "G15": frozenset(IDS[53:64]),
                      "G02": frozenset(IDS[55:64])}),
    frozenset(IDS[100:300]))
SUBSET = sorted(FROZEN.gans_subset)
LEGACY, R1 = "legacy-20261004", "b20261008_6daa4f31"
FAST = 1000     # bootstrap resamples where the prereg's 10,000 is not under test
# /health "encoder" of :8001 and :8002 (one E0b query tokenizer); prod :8000 reports none.
ENCODER = {"embedder": {"tokenizer_sha": "2110", "probe_ids_sha": "a0e8", "unk_count": 3,
                        "pair_template_ok": True},
           "reranker": {"tokenizer_sha": "6956", "probe_ids_sha": "0e76", "unk_count": 2,
                        "pair_template_ok": True}}
OTHER_ENCODER = {**ENCODER, "embedder": {**ENCODER["embedder"], "unk_count": 9}}


def retrieval_run(build=LEGACY, *, vrec=None, mrr=None, invalid=(), routes=None, meta=None,
                  **config):
    """A quick_retrieval_eval.py result: per-question metrics, meta and config."""
    vrec, mrr, routes = vrec or {}, mrr or {}, routes or {}
    per_question = {
        q: {"verse_recall_at_k": vrec.get(q, (i % 7) / 6), "mrr": mrr.get(q, 1 / (1 + i % 5)),
            "anchor_coverage_at_k": 0.5, "hit_rate": 1.0, "route": routes.get(q, "R1"),
            "invalid": q in invalid}
        for i, q in enumerate(IDS)}
    return {
        "meta": {"data_build_id": build, "gt_version": "v2", "gt_sha": "gtsha",
                 "encoder_fingerprint": ENCODER, **(meta or {})},
        "config": {"top_k": 5, "metric_k": 6, "metric_version": "mv1", "use_graph": True,
                   "fusion_alpha": None, "graph_strategies_requested": None, **config},
        "per_question": per_question,
    }


def shifted(run, metric, delta, ids, build=None):
    """A copy of ``run`` with ``metric`` moved by ``delta`` on ``ids``."""
    out = copy.deepcopy(run)
    for q in ids:
        out["per_question"][q][metric] += delta
    if build is not None:
        out["meta"]["data_build_id"] = build
    return out


def gate(l1=None, l2=None, r=None, frozen=FROZEN, n_boot=FAST):
    l1 = l1 or retrieval_run()
    return noninf.retrieval_gate(l1, l2 or copy.deepcopy(l1), r or retrieval_run(R1),
                                 frozen, LABELS, n_boot=n_boot)


# ---------------------------------------------------------------- statistics

def test_bootstrap_is_the_prereg_one_and_deterministic():
    diffs = [math.sin(i) / 3 for i in range(500)]

    first, second = noninf.summarize(diffs), noninf.summarize(diffs)

    assert (noninf.N_BOOT, noninf.SEED, noninf.MIN_PAIRED) == (10_000, 20261008, 495)
    assert first == second
    assert first["ci"] == list(bootstrap_ci(diffs, n_boot=10_000, seed=20261008))
    assert noninf.summarize(diffs, seed=1)["ci"] != first["ci"]
    assert first["n"] == 500 and first["mean"] == pytest.approx(sum(diffs) / 500)


def test_margins_take_the_floor_or_twice_the_band():
    assert noninf.noise_band([-0.004, 0.011]) == 0.011
    assert noninf.margin(0.004, 0.02) == 0.02
    assert noninf.margin(0.015, 0.02) == 0.03
    assert noninf.margin(None, 0.02) is None


# ---------------------------------------------------------------- retrieval gate

def test_identical_runs_have_zero_noise_and_the_floor_margins():
    report = gate(n_boot=noninf.N_BOOT)

    assert report["aa"]["B"] == 0 and report["aa"]["delta"] == 0.02
    assert report["aa"]["B_wl"] == 0 and report["aa"]["delta_wl"] == 0.02
    assert report["criteria"]["C1"]["ci"] == [0, 0]
    assert report["criteria"]["C3"]["union"]["mean"] == 0
    assert report["passed"] and report["fail_reasons"] == []
    assert report["params"]["n_boot"] == 10_000 and report["params"]["seed"] == 20261008


def test_aa_noise_widens_delta_to_twice_the_band():
    l1 = retrieval_run()
    l2 = shifted(shifted(l1, "verse_recall_at_k", 0.5, IDS[100:120]),
                 "verse_recall_at_k", -0.5, IDS[120:140])

    aa = gate(l1, l2)["aa"]

    lo, hi = aa["delta_vrec"]["ci"]
    assert aa["B"] == max(abs(lo), abs(hi)) > 0.01
    assert aa["delta"] == pytest.approx(2 * aa["B"])


def test_known_vrec_drop_fails_c1():
    l1 = retrieval_run()
    report = gate(l1, r=shifted(l1, "verse_recall_at_k", -0.1, IDS, build=R1))

    c1 = report["criteria"]["C1"]
    assert c1["ci"][0] == pytest.approx(-0.1) and c1["threshold"] == -0.02
    assert not c1["passed"] and not report["passed"]
    assert any(reason.startswith("C1") for reason in report["fail_reasons"])
    assert report["criteria"]["C2"]["passed"]


def test_vrec_drop_inside_the_margin_passes_c1():
    l1 = retrieval_run()
    report = gate(l1, r=shifted(l1, "verse_recall_at_k", -0.01, IDS[64:], build=R1))

    assert report["criteria"]["C1"]["passed"]
    assert report["criteria"]["C3"]["passed"]


def test_c2_counts_signs_not_sizes():
    l1 = retrieval_run()
    r = shifted(shifted(l1, "mrr", -0.001, IDS[100:160], build=R1), "mrr", 0.5, IDS[200:210])

    c2 = gate(l1, r=r)["criteria"]["C2"]

    assert (c2["wins"], c2["losses"], c2["ties"]) == (10, 60, 430)
    assert c2["mean_sign"]["mean"] == pytest.approx(-50 / 500)
    assert c2["delta_mrr"]["mean"] > 0
    assert c2["sign_test_p"] == sign_test_p(10, 60)
    assert not c2["passed"]


def test_aa_mrr_flips_widen_delta_wl():
    l1 = retrieval_run()
    l2 = shifted(shifted(l1, "mrr", 0.1, IDS[100:120]), "mrr", -0.1, IDS[120:140])
    r = shifted(l1, "mrr", -0.1, IDS[300:330], build=R1)

    report = gate(l1, l2, r)

    assert report["aa"]["mrr_win_loss"] == {"wins": 20, "losses": 20, "ties": 460}
    assert report["aa"]["B_wl"] == pytest.approx(40 / 500)
    assert report["aa"]["delta_wl"] == pytest.approx(0.16)
    assert report["criteria"]["C2"]["passed"]       # −0.06 sits inside the A/A flip rate


def test_harm_on_the_damaged_slice_fails_c3_alone():
    l1 = retrieval_run()
    report = gate(l1, r=shifted(l1, "verse_recall_at_k", -0.2, IDS[:5], build=R1))

    c3 = report["criteria"]["C3"]
    assert report["criteria"]["C1"]["passed"]
    assert c3["union"]["n"] == 64 and c3["union"]["mean"] == pytest.approx(-1 / 64)
    assert not c3["passed"] and not report["passed"]
    assert c3["sub_slices"]["G01"]["mean"] == pytest.approx(-1 / 56)
    assert c3["sub_slices"]["G15"]["mean"] == 0 and c3["sub_slices"]["G02"]["mean"] == 0


def test_damaged_questions_dropped_from_pairing_are_listed():
    report = gate(r=retrieval_run(R1, invalid={IDS[54], IDS[60]}))

    c3 = report["criteria"]["C3"]
    assert c3["union"]["n"] == 62 and c3["union"]["unpaired"] == [IDS[54], IDS[60]]
    assert c3["sub_slices"]["G01"]["unpaired"] == [IDS[54]]


def test_invalid_questions_are_dropped_from_the_pair_and_listed():
    report = gate(l1=retrieval_run(invalid={IDS[100]}),
                  r=retrieval_run(R1, invalid={IDS[101], IDS[102]}))

    pairing = report["pairing"]
    assert pairing["n"] == 497 and pairing["dropped_invalid"] == [IDS[100], IDS[101], IDS[102]]
    assert report["aa"]["pairing"]["dropped_invalid"] == [IDS[100]]
    assert report["passed"]


def test_fewer_than_495_pairs_fails_rerun_arm():
    report = gate(r=retrieval_run(R1, invalid=set(IDS[400:406])))

    assert report["pairing"]["n"] == 494 and not report["passed"]
    assert report["fail_reasons"] == [
        "rerun arm: R–L1 has 494 paired questions (< 495; R invalid 6)"]


def test_aa_pair_below_495_fails_too():
    l1 = retrieval_run()
    l2 = retrieval_run(invalid=set(IDS[400:406]))

    report = gate(l1, l2)

    assert report["aa"]["pairing"]["n"] == 494 and not report["passed"]
    assert report["fail_reasons"][0].startswith("rerun arm: A/A L1–L2 has 494")


def test_report_only_routes_strata_and_large_drops():
    l1 = retrieval_run()
    r = shifted(retrieval_run(R1, routes={IDS[200]: "R4", IDS[201]: "R5"}),
                "verse_recall_at_k", -0.5, [IDS[200]])

    ro = gate(l1, r=r)["report_only"]

    assert ro["route_differs"]["r_vs_l1"] == {"n": 2, "ids": [IDS[200], IDS[201]]}
    assert ro["route_differs"]["aa"]["n"] == 0
    assert ro["large_drops"] == [{
        "question_id": IDS[200], "question_type": TYPES[0], "family": "paraphrase",
        "route_l1": "R1", "route_r": "R4", "vrec_l1": 4 / 6, "vrec_r": pytest.approx(4 / 6 - 0.5),
        "delta_vrec": pytest.approx(-0.5)}]
    assert ro["strata"]["head_vs_expanded"]["legacy_head"]["n"] == 100
    assert ro["strata"]["by_type"][TYPES[0]]["delta_vrec"] == pytest.approx(-0.5 / 100)
    assert set(ro["deltas"]) == {"anchor_coverage_at_k", "hit_rate"}


@pytest.mark.parametrize(("runs", "match"), [
    (lambda: (retrieval_run(), retrieval_run(), retrieval_run(R1, meta={"gt_sha": "other"})),
     "gt_sha differs"),
    (lambda: (retrieval_run(), retrieval_run(metric_k=5), retrieval_run(R1)), "metric_k 5"),
    (lambda: (retrieval_run(), retrieval_run(), retrieval_run(LEGACY)), "control's build"),
    (lambda: (retrieval_run(), retrieval_run(R1), retrieval_run(R1)), "share a data build"),
    (lambda: (retrieval_run(meta={"gt_version": "v1"}), retrieval_run(), retrieval_run(R1)),
     "needs GT v2"),
    (lambda: (retrieval_run(), retrieval_run(), retrieval_run(R1, top_k=6)), "top_k 6"),
    (lambda: (retrieval_run(), retrieval_run(), retrieval_run(R1, metric_version="mv2")),
     "metric_version differs"),
    (lambda: (retrieval_run(), retrieval_run(), retrieval_run(R1, fusion_alpha=0.3)),
     "overrides backend defaults"),
    (lambda: tuple(retrieval_run(b, meta={"gt_sha": "x"}) for b in (LEGACY, LEGACY, R1)),
     "ground_truth.v2.json"),
    # An L rerun that forgot BACKEND_URL hits prod :8000: same build id, no encoder report.
    (lambda: (retrieval_run(), retrieval_run(meta={"encoder_fingerprint": None}),
              retrieval_run(R1)), "L2: meta has no encoder_fingerprint"),
    (lambda: (retrieval_run(), retrieval_run(meta={"encoder_fingerprint": OTHER_ENCODER}),
              retrieval_run(R1)), "L2 ran another encoder than the control L1"),
    (lambda: (retrieval_run(), retrieval_run(),
              retrieval_run(R1, meta={"encoder_fingerprint": OTHER_ENCODER})),
     "R ran another encoder"),
])
def test_runs_the_protocol_does_not_allow_are_refused(runs, match):
    with pytest.raises(noninf.GateInputError, match=match):
        noninf.retrieval_gate(*runs(), FROZEN, LABELS, n_boot=FAST)


def test_frozen_sets_off_the_prereg_sizes_are_refused():
    small = FROZEN._replace(gans_subset=frozenset(IDS[100:150]))
    with pytest.raises(noninf.GateInputError, match="gans_subset has 50"):
        gate(frozen=small)


# ---------------------------------------------------------------- answer gate

def answer_run(build=LEGACY, *, strict=None, drop=(), extra=(), meta=None, coverage=None,
               flagged=None):
    """A quick_faithfulness_eval.py report over the frozen subset (plus ``extra`` ids);
    ``flagged`` maps ids to the row's "invalid" flag ("infra" / "generation")."""
    strict, coverage, flagged = strict or {}, coverage or {}, flagged or {}
    rows = [{"question_id": q, "question_type": "VERSE_LOOKUP", "family": "paraphrase",
             "invalid": flagged.get(q), "ragas_faithfulness": 0.95,
             "ragas_faithfulness_strict": strict.get(q, 0.9 + (i % 10) / 100),
             **({"coverage": coverage[q]} if q in coverage else {})}
            for i, q in enumerate([*SUBSET, *extra]) if q not in drop]
    return {"meta": {"data_build_id": build, "gt_version": "v2", "gt_sha": "gtsha",
                     "encoder_fingerprint": ENCODER, "strict_enabled": True,
                     "context_format": "generator_blocks", "judge_provider": "ollama",
                     "judge_model": "gemma4:26b-a4b-it-q8_0", "unjudged_samples": 0,
                     **(meta or {})},
            "overall": {}, "samples": rows}


def unflagged(run):
    """``run`` as a quick_faithfulness_eval.py from before rows carried the "invalid" flag."""
    out = copy.deepcopy(run)
    for row in out["samples"]:
        del row["invalid"]
    return out


def answer(a1=None, a2=None, r=None, n_boot=FAST):
    return noninf.answer_gate(a1 or answer_run(), a2 or answer_run(), r or answer_run(R1),
                              FROZEN, LABELS, n_boot=n_boot)


def test_identical_answer_arms_pass_with_the_floor_margin():
    report = answer(n_boot=noninf.N_BOOT)

    assert report["aa"]["B_ans"] == 0 and report["aa"]["delta_ans"] == 0.01
    assert report["criteria"]["no_invalid"]["n_invalid"] == {"A1": 0, "A2": 0, "R": 0}
    assert report["passed"]
    assert "coverage" not in report["report_only"]
    assert report["report_only"]["strict_absolute"]["R"]["below_reference"] is True


def test_strict_drop_fails_g_ans():
    r = answer_run(R1, strict={q: 0.85 for q in SUBSET})

    report = answer(r=r)

    ds = report["criteria"]["delta_strict"]
    assert ds["threshold"] == -0.01 and ds["ci"][1] < -0.01
    assert not report["passed"]


@pytest.mark.parametrize("arm", ["A1", "A2", "R"])
@pytest.mark.parametrize(("broken", "why"), [
    ({"strict": {SUBSET[3]: None}}, "unjudged"),
    ({"strict": {SUBSET[3]: float("nan")}}, "unjudged"),
    ({"drop": (SUBSET[3],)}, "no row"),
    ({"flagged": {SUBSET[3]: "generation"}}, "generation"),
    ({"flagged": {SUBSET[3]: "infra"}, "strict": {SUBSET[3]: None}}, "infra"),
])
def test_an_unjudged_missing_or_failed_row_is_invalid_and_fails(arm, broken, why):
    runs = {"A1": answer_run(), "A2": answer_run(), "R": answer_run(R1)}
    runs[arm] = answer_run(runs[arm]["meta"]["data_build_id"], **broken)

    report = answer(runs["A1"], runs["A2"], runs["R"])

    assert report["invalid"][arm] == {SUBSET[3]: why}
    assert report["criteria"]["no_invalid"]["n_invalid"][arm] == 1
    assert not report["passed"] and "rerun arm" in report["fail_reasons"][0]


def test_judged_generation_failures_are_invalid_and_do_not_widen_the_margin():
    """prereg n_invalid counts 生成失敗: the backend answers HTTP 200 with
    "生成回答時發生錯誤…", which a judge can score 0.0. Scored as valid, two such A2 rows
    would widen B_ans and δ_ans enough to pass a treatment that should fail."""
    failed = {SUBSET[10]: 0.0, SUBSET[20]: 0.0}
    r = answer_run(R1, strict={q: 0.86 for q in SUBSET[:20]})
    widened = answer(a2=answer_run(strict=failed), r=r)
    assert widened["criteria"]["delta_strict"]["passed"]    # the unflagged failures pass R

    report = answer(a2=answer_run(strict=failed, flagged=dict.fromkeys(failed, "generation")),
                    r=r)

    assert report["invalid"]["A2"] == dict.fromkeys(sorted(failed), "generation")
    assert report["criteria"]["no_invalid"]["n_invalid"] == {"A1": 0, "A2": 2, "R": 0}
    assert report["aa"]["delta_strict"]["n"] == 198 and report["aa"]["B_ans"] == 0
    assert not report["criteria"]["delta_strict"]["passed"] and not report["passed"]
    assert report["fail_reasons"][0].startswith("A2 has 2 invalid questions (rerun arm)")


def test_coverage_is_reported_when_rows_carry_it():
    full = {q: 0.6 for q in SUBSET}
    r = answer_run(R1, coverage={**full, SUBSET[0]: None})

    cov = answer(answer_run(coverage=full), answer_run(coverage=full), r)["report_only"]["coverage"]

    assert cov["mean"] == {"A1": 0.6, "A2": 0.6, "R": 0.6}
    assert cov["delta_r_vs_a1"]["n"] == 199 and cov["noise_floor"] == 0.06


@pytest.mark.parametrize(("runs", "match"), [
    (lambda: (answer_run(extra=(IDS[0],)), answer_run(), answer_run(R1)),
     "outside the frozen 200-question subset"),
    (lambda: (answer_run(), answer_run(meta={"strict_enabled": False}), answer_run(R1)),
     "strict judge did not run"),
    (lambda: (answer_run(), answer_run(R1), answer_run(R1)), "share a data build"),
    (lambda: (answer_run(), answer_run(), answer_run(LEGACY)), "control's build"),
    (lambda: (answer_run(), answer_run(), answer_run(R1, meta={"gt_sha": "x"})), "gt_sha"),
    (lambda: (answer_run(), answer_run(), answer_run(R1, meta={"judge_model": "other"})),
     "judge_model differs"),
    (lambda: (answer_run(meta={"context_format": "headerless"}), answer_run(), answer_run(R1)),
     "context_format"),
    (lambda: (answer_run(meta={"gt_version": "v1"}), answer_run(), answer_run(R1)),
     "needs GT v2"),
    (lambda: (answer_run(), unflagged(answer_run()), answer_run(R1)),
     "A2: rows carry no 'invalid' flag"),
    (lambda: (answer_run(), answer_run(meta={"encoder_fingerprint": None}), answer_run(R1)),
     "A2: meta has no encoder_fingerprint"),
    (lambda: (answer_run(), answer_run(),
              answer_run(R1, meta={"encoder_fingerprint": OTHER_ENCODER})),
     "R ran another encoder than the control A1"),
])
def test_answer_reports_the_protocol_does_not_allow_are_refused(runs, match):
    with pytest.raises(noninf.GateInputError, match=match):
        noninf.answer_gate(*runs(), FROZEN, LABELS, n_boot=FAST)


# ---------------------------------------------------------------- CLI

def test_gt_labels_come_from_gt_v2():
    labels = r1_gate.gt_labels()

    assert labels.sha256 == load_gt("v2").sha256 and len(labels.labels) == 500
    assert sum(lab.family == "legacy_head" for lab in labels.labels.values()) == 100


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """r1_gate.main on runs written to tmp_path, with the synthetic GT and frozen sets."""
    monkeypatch.setattr(r1_gate, "gt_labels", lambda: LABELS)
    monkeypatch.setattr(r1_gate, "load_frozen", lambda path: FROZEN)
    (tmp_path / "frozen.json").write_text("{}")

    def run(kind, runs, *extra):
        paths = []
        for name, data in zip(("c", "aa", "t"), runs):
            paths.append(tmp_path / f"{name}.json")
            paths[-1].write_text(json.dumps(data))
        out = tmp_path / "report.json"
        code = r1_gate.main([kind, "--aa", str(paths[0]), str(paths[1]), "--treatment",
                             str(paths[2]), "--frozen", str(tmp_path / "frozen.json"),
                             "--out", str(out), *extra])
        return code, (json.loads(out.read_text()) if out.exists() else None)
    return run


def test_cli_retrieval_pass_and_fail_exit_codes(cli, capsys):
    l1 = retrieval_run()

    code, report = cli("retrieval", (l1, l1, retrieval_run(R1)))
    assert code == 0 and report["passed"] and report["inputs"]["L1"].endswith("c.json")
    assert "G-NONINF: PASS" in capsys.readouterr().out

    drop = shifted(l1, "verse_recall_at_k", -0.1, IDS, build=R1)
    code, report = cli("retrieval", (l1, l1, drop), "--overwrite")
    assert code == 1 and not report["passed"]
    assert "G-NONINF: FAIL" in capsys.readouterr().out


def test_cli_input_errors_exit_2_without_a_report(cli, capsys):
    code, report = cli("retrieval", (retrieval_run(), retrieval_run(), retrieval_run(LEGACY)))

    assert code == 2 and report is None
    assert "control's build" in capsys.readouterr().err


def test_cli_refuses_to_replace_a_report_without_overwrite(cli):
    runs = (answer_run(), answer_run(), answer_run(R1))
    assert cli("answer", runs)[0] == 0
    assert cli("answer", runs)[0] == 2
    assert cli("answer", runs, "--overwrite")[0] == 0
