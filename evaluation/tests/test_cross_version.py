"""Comparing runs across versions: one ground truth required, different data builds reported.

R1 compares the legacy build with a new one, so ab_compare pairs runs of
different data_build_id; it refuses runs scored against different GT
(gt_version or gt_sha), which would compare two rulers instead of two systems.
"""

import json
import sys

import pytest

import ab_compare as cli
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
