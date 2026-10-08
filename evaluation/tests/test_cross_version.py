"""Comparing runs across versions: one ground truth required, different data builds reported.

R1 compares the legacy build with a new one, so ab_compare and d3_gate pair runs
of different data_build_id; they refuse runs scored against different GT
(gt_version or gt_sha), which would compare two rulers instead of two systems.
"""

import copy
import json
import sys

import pytest

import ab_compare as cli
import d3_gate as gate
from src.ab_compare import compare, identity_report, same_gt

V1 = {"gt_version": "v1", "gt_sha": "1" * 64}
V2 = {"gt_version": "v2", "gt_sha": "2" * 64}
LEGACY, NEW = "legacy-20261004", "b20261007_68412f4f"
IDS = [f"a:{i}:0" for i in range(5)]


def _entry():
    return {"sources": list(IDS), "route": "R4", "invalid": False,
            "source_detail": [{"id": i, "gold": False, "context_sha256": f"s-{i}"} for i in IDS],
            "context_sha": "ctx", "graph_strategies": ["event_registry"],
            "verse_recall_at_k": 0.5, "anchor_coverage_at_k": 0.5, "mrr": 0.5, "hit_rate": 1.0}


def _run(gt=V2, build=LEGACY):
    run = {"config": {"top_k": 5, "metric_k": 6, "metric_version": "m", "include_context": True,
                      "use_graph": True, "fusion_alpha": None, "graph_strategies_requested": None,
                      "graph_strategies_applied": {"event_registry": 1}},
           "per_question": {"Q1": _entry()}}
    if gt is not None:
        run["meta"] = {"data_build_id": build, **gt, "encoder_fingerprint": None}
    return run


@pytest.mark.parametrize("judge", [compare, identity_report])
def test_different_builds_are_compared_and_both_builds_reported(judge):
    report = judge(_run(build=LEGACY), _run(build=NEW))

    assert report["builds"] == {"control": LEGACY, "treatment": NEW}
    assert report["gt"] == V2


@pytest.mark.parametrize("judge", [compare, identity_report])
@pytest.mark.parametrize("treatment_gt", [V1, {**V2, "gt_sha": "3" * 64}, None])
def test_runs_scored_against_different_gt_are_refused(judge, treatment_gt):
    with pytest.raises(ValueError, match="different ground truth"):
        judge(_run(), _run(gt=treatment_gt, build=NEW))


def test_an_extended_control_on_another_gt_is_refused():
    with pytest.raises(ValueError, match="control_ext"):
        compare(_run(), _run(), _run(gt=V1))


def test_runs_from_before_the_meta_record_pair_only_with_each_other():
    assert same_gt({"control": _run(gt=None), "treatment": _run(gt=None)}) == {
        "gt": {"gt_version": None, "gt_sha": None},
        "builds": {"control": None, "treatment": None}}


def test_the_cli_prints_gt_and_builds(tmp_path, monkeypatch, capsys):
    paths = []
    for name, build in (("c", LEGACY), ("t", NEW)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(_run(build=build)))
        paths.append(str(path))
    monkeypatch.setattr(sys, "argv", ["ab_compare.py", *paths, "--require-identical"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert f"control={LEGACY}" in out and f"treatment={NEW}" in out and "GT v2" in out


def test_the_cli_exits_non_zero_on_different_gt(tmp_path, monkeypatch, capsys):
    paths = []
    for name, gt in (("c", V1), ("t", V2)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(_run(gt=gt)))
        paths.append(str(path))
    monkeypatch.setattr(sys, "argv", ["ab_compare.py", *paths, "--require-identical"])

    assert cli.main() == 1
    assert "different ground truth" in capsys.readouterr().err


# --- d3_gate --------------------------------------------------------------------

@pytest.mark.parametrize("meta", [{"data_build_id": NEW}, {"gt_sha": "9" * 64}])
def test_a_reask_against_another_build_or_gt_is_not_merged(meta):
    base = _run()
    rerun = copy.deepcopy(base)
    rerun["meta"] = {**rerun["meta"], **meta}

    with pytest.raises(ValueError, match="different"):
        gate.merge_rerun(base, rerun, ["Q1"])


def test_a_merged_run_keeps_its_meta():
    base = _run(build=NEW)

    assert gate.merge_rerun(base, copy.deepcopy(base), ["Q1"])["meta"] == base["meta"]


def test_the_gt_choice_reaches_every_quick_eval_run(tmp_path, monkeypatch):
    calls = []

    def runner(url, label, ids, gt=None):
        calls.append(gt)
        return _run(build=LEGACY if "prod" in label else NEW)

    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(gate, "subprocess_runner", runner)
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "r1", "--gt", "v2",
                                      "--control-url", "http://c", "--treatment-url", "http://t",
                                      "--route-residual-max", "0"])

    assert gate.main() == 0
    report = json.loads((tmp_path / "d3_r1.json").read_text(encoding="utf-8"))
    assert calls == ["v2", "v2"]
    assert report["identity"]["builds"] == {"control": LEGACY, "treatment": NEW}
    assert gate.quick_eval_command("x", gt="v2")[-2:] == ["--gt", "v2"]


def test_the_ab_report_prints_gt_and_builds(tmp_path, monkeypatch, capsys):
    paths = []
    for name, build in (("c", LEGACY), ("t", NEW)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(_run(build=build)))
        paths.append(str(path))
    monkeypatch.setattr(sys, "argv", ["ab_compare.py", *paths])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert f"control={LEGACY}" in out and f"treatment={NEW}" in out
