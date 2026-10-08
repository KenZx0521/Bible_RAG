"""``python -m ragdata pipeline run``: exit status, report, what stderr says on a stop."""

from __future__ import annotations

import argparse
import dataclasses
import json

import pytest

import mini_pipeline
from ragdata import cli, paths
from ragdata.pipeline import cli as pipeline_cli
from ragdata.pipeline import derived
from ragdata.pipeline.steps import ORDER
from ragdata.store import DEFAULT_ROOT, StoredLayer

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")


@pytest.fixture()
def mini(tmp_path):
    return mini_pipeline.make(tmp_path)


def _use(monkeypatch, pipeline):
    seen = []
    monkeypatch.setattr(pipeline_cli, "default_pipeline",
                        lambda args: seen.append(args) or pipeline)
    return seen


def test_a_green_run_exits_0_and_writes_its_report(mini, monkeypatch, capsys, tmp_path):
    seen = _use(monkeypatch, mini.pipeline())
    report = tmp_path / "pipeline.json"
    assert cli.main(["pipeline", "run", "--load", "--verify", "--date", "20261008",
                     "--report", str(report)]) == 0
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert doc["pass"] is True and doc["stopped"] is None
    assert json.loads(capsys.readouterr().out) == doc
    assert (seen[0].load, seen[0].verify, seen[0].date) == (True, True, "20261008")


def test_a_red_gate_exits_1_and_names_the_layer_and_the_gate(mini, monkeypatch, capsys):
    counts = mini.root / "red_counts.yaml"
    counts.write_text(mini.sources.counts.read_text(encoding="utf-8").replace(
        "  pericopes: {value: 6,", "  pericopes: {value: 7,"), encoding="utf-8")
    _use(monkeypatch, mini.pipeline(sources=dataclasses.replace(mini.sources, counts=counts)))
    assert cli.main(["pipeline", "run"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ragdata pipeline: stopped at struct:\n  G-COUNT:")


def test_stale_derived_files_exit_2_and_print_the_commands(mini, monkeypatch, capsys):
    mini.files.versification.write_text(json.dumps({"source": {"layer_version": "x"}}),
                                        encoding="utf-8")
    _use(monkeypatch, mini.pipeline())
    assert cli.main(["pipeline", "run"]) == 2
    err = capsys.readouterr().err
    assert "stopped at derived:" in err and "run, in order:\n  1. scripts/.venv/bin/python " \
        "scripts/derive_ragcommon_data.py versification" in err


def test_a_layer_gate_stop_names_the_version(mini, monkeypatch, capsys):
    text = mini_pipeline.text_step(mini.root / "store", mini.sources, full_gates=True)
    _use(monkeypatch, mini.pipeline(text=text))
    assert cli.main(["pipeline", "run"]) == 1
    assert f"stopped at text ({mini.text_version}):" in capsys.readouterr().err


def _args(**changes):
    fields = {"date": "20261008", "load": False, "verify": False, "device": "cpu",
              "store": DEFAULT_ROOT, "releases": paths.RELEASES, "report": None}
    return argparse.Namespace(**{**fields, **changes})


def test_the_default_pipeline_reads_the_repository(monkeypatch):
    monkeypatch.setattr(pipeline_cli.rel, "git_date", lambda repo: pytest.fail("dated by git"))
    p = pipeline_cli.default_pipeline(_args())
    assert [s.layer for s in p.steps] == list(ORDER) and p.store == DEFAULT_ROOT
    assert p.files == derived.DerivedFiles() and p.databases is None
    assert p.files.gt == paths.GT_V2 and p.files.versification.name == "versification.json"


def test_load_and_verify_are_wired_only_when_asked(monkeypatch):
    dated = []
    monkeypatch.setattr(pipeline_cli.rel, "git_date", lambda repo: dated.append(repo) or "20261008")
    p = pipeline_cli.default_pipeline(_args(date=None, load=True))
    assert dated == [paths.REPO]
    assert p.databases.load is not None and p.databases.verify is None
    p = pipeline_cli.default_pipeline(_args(verify=True))
    assert p.databases.load is None and p.databases.verify is not None


def test_the_databases_come_from_the_repository_env_file(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline_cli.loader_cli, "environment",
                        lambda path: seen.append(path) or {})
    monkeypatch.setattr(pipeline_cli.loader_cli, "connect", lambda env: ("pg", "qdrant"))
    p = pipeline_cli.default_pipeline(_args(verify=True))
    assert p.databases.connect() == ("pg", "qdrant") and seen == [paths.REPO / ".env"]


GT_UNIVERSE = json.loads(paths.GT_V2_FREEZE.read_text(encoding="utf-8"))["slot_universe"]
GT_LAYER = DEFAULT_ROOT / "text" / GT_UNIVERSE


@pytest.mark.skipif(not GT_LAYER.is_dir(), reason=f"text layer {GT_UNIVERSE} not in the store")
def test_g_gt_runs_over_the_committed_gt_v2_and_its_text_layer():
    report = derived.gt_report({"text": StoredLayer("text", GT_UNIVERSE, GT_LAYER)},
                               derived.DerivedFiles())
    assert report.passed and report.slot_universe == GT_UNIVERSE
