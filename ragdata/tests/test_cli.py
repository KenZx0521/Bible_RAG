"""python -m ragdata {build,gate,det}: exit 0 pass, 1 hard gate failed, 2 bad input."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import mini_build
from ragdata import cli, stages
from ragdata.store import StoredLayer

MINI_COUNTS = str(Path(__file__).with_name("mini_counts.yaml"))
REPO = Path(__file__).resolve().parents[2]


def _run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_gate_prints_a_passing_report(tmp_path, capsys):
    text, _ = mini_build.write_layers(tmp_path)
    code, out, _ = _run(capsys, "gate", "text", text.path, "--counts", MINI_COUNTS)
    assert code == 0
    assert json.loads(out)["pass"] is True


def test_gate_exits_1_and_still_reports_when_a_hard_gate_fails(tmp_path, capsys):
    text, _ = mini_build.write_layers(tmp_path)
    report = tmp_path / "report.json"
    code, out, _ = _run(capsys, "gate", "text", text.path, "--report", report)
    assert code == 1
    assert json.loads(report.read_text(encoding="utf-8")) == json.loads(out)
    assert not json.loads(out)["pass"]


def test_gate_struct_takes_its_text_layer_as_a_dependency(tmp_path, capsys):
    text, struct = mini_build.write_layers(tmp_path)
    code, _, _ = _run(capsys, "gate", "struct", struct.path, "--dep", text.path,
                      "--counts", MINI_COUNTS)
    assert code == 0


@pytest.mark.parametrize("argv", [
    lambda t, s, tmp: ["gate", "struct", s.path, "--counts", MINI_COUNTS],
    lambda t, s, tmp: ["gate", "text", tmp / "missing", "--counts", MINI_COUNTS],
    lambda t, s, tmp: ["gate", "text", t.path, "--counts", tmp / "missing.yaml"],
], ids=["missing-dependency", "missing-layer-dir", "missing-counts"])
def test_gate_input_errors_exit_2_with_a_message(tmp_path, capsys, argv):
    text, struct = mini_build.write_layers(tmp_path)
    code, out, err = _run(capsys, *argv(text, struct, tmp_path))
    assert code == 2 and out == ""
    assert err.startswith("ragdata gate: ")


def test_det_compares_two_runs(tmp_path, capsys):
    a, _ = mini_build.write_layers(tmp_path / "run1")
    b, _ = mini_build.write_layers(tmp_path / "run2")
    assert _run(capsys, "det", a.path, b.path)[0] == 0
    rows = mini_build.text_layer()
    rows["ref_aliases"] = []
    c, _ = mini_build.write_layers(tmp_path / "run3", text=rows)
    code, out, _ = _run(capsys, "det", a.path, c.path)
    assert code == 1 and json.loads(out)["name"] == "G-DET"


def test_build_text_needs_an_existing_pdf_dir(tmp_path, capsys):
    code, _, err = _run(capsys, "build", "text", "--pdf-dir", tmp_path / "nope",
                        "--store", tmp_path / "store")
    assert code == 2 and "pdf-dir" in err


def test_build_text_fails_loudly_until_the_stage_exists(tmp_path, capsys):
    (tmp_path / "pdf").mkdir()
    code, _, err = _run(capsys, "build", "text", "--pdf-dir", tmp_path / "pdf",
                        "--store", tmp_path / "store")
    assert code == 2 and "not implemented" in err
    assert not (tmp_path / "store").exists()


def test_build_reports_the_stored_layer(tmp_path, capsys, monkeypatch):
    (tmp_path / "pdf").mkdir()
    stored = StoredLayer("text", "text@0123456789ab", tmp_path / "store" / "text")
    monkeypatch.setattr(stages, "build", lambda layer, pdf_dir, store_root: stored)
    code, out, _ = _run(capsys, "build", "text", "--pdf-dir", tmp_path / "pdf",
                        "--store", tmp_path / "store")
    assert code == 0
    assert json.loads(out)["layer_version"] == "text@0123456789ab"


def test_module_entry_point_runs_the_cli(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'ragdata' / 'src'}{os.pathsep}{REPO / 'packages'}"}
    done = subprocess.run([sys.executable, "-m", "ragdata", "gate", "text", str(text.path),
                           "--counts", MINI_COUNTS], env=env, capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["layer_version"] == text.version
