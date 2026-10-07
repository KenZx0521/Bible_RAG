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
from ragdata.gates import runner
from ragdata.gates.base import GateResult
from ragdata.store import StoredLayer

MINI_COUNTS = str(Path(__file__).with_name("mini_counts.yaml"))
REPO = Path(__file__).resolve().parents[2]


def _run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def only_built_gates_required(monkeypatch):
    """Pretend every required gate exists, to reach the passing path of the CLI."""
    monkeypatch.setattr(runner, "REQUIRED_GATES",
                        {layer: ("G-SCHEMA", "G-COUNT", "G-REFINT")
                         for layer in ("text", "struct")})


def test_gate_prints_a_passing_report(tmp_path, capsys, only_built_gates_required):
    text, _ = mini_build.write_layers(tmp_path)
    code, out, _ = _run(capsys, "gate", "text", text.path, "--counts", MINI_COUNTS)
    assert code == 0
    assert json.loads(out)["pass"] is True


def test_gate_exits_1_while_a_required_gate_is_not_built(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(runner, "REQUIRED_GATES", {"text": ("G-SCHEMA",),
                                                   "struct": ("G-SCHEMA", "G-FUTURE")})
    text, struct = mini_build.write_layers(tmp_path)
    code, out, _ = _run(capsys, "gate", "struct", struct.path, "--dep", text.path,
                        "--counts", MINI_COUNTS)
    doc = json.loads(out)
    assert code == 1 and doc["pass"] is False
    assert any(g["observed"] == "not implemented" and not g["pass"] for g in doc["gates"])


def test_gate_exits_1_and_still_reports_when_a_hard_gate_fails(tmp_path, capsys):
    text, _ = mini_build.write_layers(tmp_path)
    report = tmp_path / "report.json"
    code, out, _ = _run(capsys, "gate", "text", text.path, "--report", report)
    assert code == 1
    assert json.loads(report.read_text(encoding="utf-8")) == json.loads(out)
    assert not json.loads(out)["pass"]


def test_gate_struct_takes_its_text_layer_as_a_dependency(tmp_path, capsys,
                                                         only_built_gates_required):
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


def test_build_text_refuses_a_dir_without_pdfs(tmp_path, capsys):
    (tmp_path / "pdf").mkdir()
    code, _, err = _run(capsys, "build", "text", "--pdf-dir", tmp_path / "pdf",
                        "--store", tmp_path / "store")
    assert code == 2 and "no PDF" in err
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("passed, code", [(True, 0), (False, 1)])
def test_build_reports_its_layers_and_gates(tmp_path, capsys, monkeypatch, passed, code):
    (tmp_path / "pdf").mkdir()
    stored = StoredLayer("text", "text@0123456789ab", tmp_path / "store" / "text")
    gate = GateResult("G-COUNT", True, passed, {}, {}, ())
    seen = {}

    def fake_build(layer, pdf_dir, store_root, **kwargs):
        seen.update(kwargs)
        return stages.BuildResult({"text": stored} if passed else {}, (gate,), {"s2_parse": 1.0})
    monkeypatch.setattr(stages, "build", fake_build)
    report = tmp_path / "build.json"
    code_, out, _ = _run(capsys, "build", "text", "--pdf-dir", tmp_path / "pdf", "--store",
                         tmp_path / "store", "--counts", MINI_COUNTS, "--workers", "3",
                         "--report", report)
    doc = json.loads(out)
    assert code_ == code and doc["pass"] is passed and json.loads(report.read_text()) == doc
    assert [v["version"] for v in doc["layers"].values()] == ["text@0123456789ab"] * passed
    assert seen["workers"] == 3 and str(seen["counts_path"]) == MINI_COUNTS
    assert seen["inputs"] == stages.TextInputs()


def test_build_struct_needs_its_text_layer(tmp_path, capsys):
    code, _, err = _run(capsys, "build", "struct", "--store", tmp_path / "store")
    assert code == 2 and "--text" in err


def test_build_struct_hands_its_inputs_to_the_stage(tmp_path, capsys, monkeypatch):
    seen = {}

    def fake_build_struct(text_dir, store_root, counts_path, inputs):
        seen.update(text_dir=text_dir, store_root=store_root, inputs=inputs)
        return stages.BuildResult({}, (GateResult("G-STRUCT", True, False, {}, {}, ()),), {})
    monkeypatch.setattr(stages, "build_struct", fake_build_struct)
    code, out, _ = _run(capsys, "build", "struct", "--text", tmp_path, "--store", tmp_path / "s",
                        "--legacy-dir", tmp_path / "old", "--tokenizer", tmp_path / "tok.json")
    assert code == 1 and json.loads(out)["pass"] is False
    assert seen["text_dir"] == tmp_path and seen["store_root"] == tmp_path / "s"
    assert seen["inputs"] == stages.StructInputs(legacy_dir=tmp_path / "old",
                                                 tokenizer=tmp_path / "tok.json")


def test_gate_struct_fails_closed_without_the_tokenizer(tmp_path, capsys):
    text, struct = mini_build.write_layers(tmp_path)
    code, out, _ = _run(capsys, "gate", "struct", struct.path, "--dep", text.path,
                        "--counts", MINI_COUNTS, "--tokenizer", tmp_path / "missing.json")
    gate = next(g for g in json.loads(out)["gates"] if g["name"] == "G-STRUCT")
    assert code == 1 and gate["observed"] == "missing input"


def test_gate_passes_the_pdfs_and_registries_to_the_gates(tmp_path, capsys, monkeypatch):
    seen = {}

    def fake_gate(layer_dir, layer, deps, counts, inputs):
        seen.update(deps=deps, inputs=inputs)
        raise runner.GateInputError("stop here")
    monkeypatch.setattr(cli, "gate_layer", fake_gate)
    code, _, _ = _run(capsys, "gate", "text", tmp_path / "t", "--dep", tmp_path / "src",
                      "--pdf-dir", tmp_path / "pdf", "--registries", tmp_path / "reg")
    assert code == 2 and seen["deps"] == [tmp_path / "src"]
    assert (seen["inputs"].pdf_dir, seen["inputs"].registries) == (tmp_path / "pdf",
                                                                   tmp_path / "reg")


def test_module_entry_point_runs_the_cli(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'ragdata' / 'src'}{os.pathsep}{REPO / 'packages'}"}
    done = subprocess.run([sys.executable, "-m", "ragdata", "gate", "text", str(text.path),
                           "--counts", MINI_COUNTS], env=env, capture_output=True, text=True,
                          check=False)
    assert done.returncode == 1, done.stderr  # red: no src layer, no PDFs given
    assert json.loads(done.stdout)["layer_version"] == text.version


def test_gate_reports_a_malformed_row_instead_of_crashing(tmp_path, capsys):
    rows = mini_build.text_layer()
    rows["verse_slots"][0]["status"] = ["present"]
    text, _ = mini_build.write_layers(tmp_path, text=rows)
    report = tmp_path / "report.json"
    code, out, _ = _run(capsys, "gate", "text", text.path, "--counts", MINI_COUNTS,
                        "--report", report)
    schema = next(g for g in json.loads(report.read_text(encoding="utf-8"))["gates"]
                  if g["name"] == "G-SCHEMA")
    assert code == 1 and not schema["pass"]
    assert schema["details"][0].startswith("verse_slots.jsonl:1: status:")


def test_a_crash_exits_3_so_it_is_never_read_as_a_gate_result(tmp_path, capsys, monkeypatch):
    def crash(*args, **kwargs):
        raise TypeError("boom")
    monkeypatch.setattr(cli, "gate_layer", crash)
    code, out, err = _run(capsys, "gate", "text", tmp_path, "--counts", MINI_COUNTS)
    assert code == 3 and out == ""
    assert "internal error" in err and "TypeError: boom" in err


def test_det_of_one_directory_against_itself_is_an_input_error(tmp_path, capsys):
    a, _ = mini_build.write_layers(tmp_path)
    code, out, err = _run(capsys, "det", a.path, a.path)
    assert code == 2 and out == "" and "same directory" in err
