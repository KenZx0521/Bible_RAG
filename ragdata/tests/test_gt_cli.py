"""python -m ragdata gt {build,gate}: files written, gate exit codes, provenance refusals."""

from __future__ import annotations

import json
import subprocess

import pytest
import yaml

import gt_fixture
import mini_build
from ragdata import cli
from ragdata.gt import cli as gt_cli
from ragdata.gt.build import encode_doc


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_provenance_names_head_and_tree_shas_of_a_clean_checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("x = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    prov = gt_cli.git_provenance(repo, ("pkg",))
    assert len(prov["git_sha"]) == 40 and len(prov["files"]["pkg"]) == 40
    assert prov["script"] == "ragdata/src/ragdata/gt/build.py"
    (repo / "pkg" / "a.py").write_text("x = 2\n")
    with pytest.raises(gt_cli.GtCliError, match="commit these"):
        gt_cli.git_provenance(repo, ("pkg",))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    text, _ = mini_build.write_layers(tmp_path / "store")
    monkeypatch.setattr(gt_cli, "versification_for", lambda version: mini_build.versification())
    monkeypatch.setattr(gt_cli, "git_provenance",
                        lambda repo, tracked: {"command": "test", "git_sha": "0" * 40, "files": {}})
    (tmp_path / "v1.json").write_bytes(gt_fixture.v1_bytes())
    (tmp_path / "curated.yaml").write_text(yaml.safe_dump(gt_fixture.CURATED, allow_unicode=True))
    files = {name: tmp_path / name for name in ("v2.json", "changes.jsonl", "freeze.json")}
    common = ["--v1", tmp_path / "v1.json", "--changes", files["changes.jsonl"],
              "--freeze", files["freeze.json"]]
    return text, files, common, tmp_path


def _main(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_build_writes_v2_log_and_freeze_and_gates_them(setup, capsys):
    text, files, common, tmp = setup
    code, out = _main(capsys, "gt", "build", "--text-layer", text.path, "--curated",
                      tmp / "curated.yaml", "--out", files["v2.json"], *common)
    assert code == 0, out.out
    assert json.loads(out.out)["pass"] is True
    doc = json.loads(files["v2.json"].read_text())
    assert doc["metadata"]["slot_universe"] == text.version
    assert json.loads(files["freeze.json"].read_text())["slot_universe"] == text.version
    assert files["changes.jsonl"].read_text().count("\n") == doc["metadata"]["changes"]["count"]
    code, _ = _main(capsys, "gt", "gate", files["v2.json"], "--store", tmp / "store", *common)
    assert code == 0


def test_gate_fails_on_an_edited_v2_and_exits_2_on_missing_files(setup, capsys):
    text, files, common, tmp = setup
    _main(capsys, "gt", "build", "--text-layer", text.path, "--curated", tmp / "curated.yaml",
          "--out", files["v2.json"], *common)
    doc = json.loads(files["v2.json"].read_text())
    doc["questions"][0]["reference_answer"] += "（補充）"
    files["v2.json"].write_bytes(encode_doc(doc))
    code, out = _main(capsys, "gt", "gate", files["v2.json"], "--text-layer", text.path, *common)
    assert code == 1
    failed = {g["name"] for g in json.loads(out.out)["gates"] if not g["pass"]}
    assert failed == {"G-GT.changes", "G-GT.freeze"}
    code, out = _main(capsys, "gt", "gate", tmp / "nope.json", "--text-layer", text.path, *common)
    assert code == 2 and "nope.json" in out.err


def test_gate_needs_a_slot_universe_or_a_text_layer(setup, capsys):
    _, _, common, tmp = setup
    (tmp / "bare.json").write_text(json.dumps({"metadata": {}, "questions": []}))
    code, out = _main(capsys, "gt", "gate", tmp / "bare.json", *common)
    assert code == 2 and "slot_universe" in out.err


def test_versification_from_another_layer_is_refused():
    with pytest.raises(gt_cli.GtCliError, match="not text@000000000000"):
        gt_cli.versification_for("text@000000000000")
