"""``build_kg0`` and the kg0 gates through the runner and the CLI, on the mini snapshot."""

from __future__ import annotations

import json

import pytest
import yaml

import mini_build
import mini_kg
from ragdata import cli, store
from ragdata.gates import check_det
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg.k0_build import build_kg0
from ragdata.stages.errors import StageError


@pytest.fixture()
def given(tmp_path):
    text, struct = mini_build.write_layers(tmp_path / "given")
    versions = mini_kg.write_registries(tmp_path / "registries")
    counts = tmp_path / "kg0_counts.yaml"
    counts.write_bytes(mini_kg.dump(mini_kg.kg0_counts(versions, text.version, struct.version)))
    return {"text": text, "struct": struct, "versions": versions, "counts": counts,
            "registries": tmp_path / "registries", "root": tmp_path}


def _build(given, store_dir="store", counts=None):
    return build_kg0(given["text"].path, given["struct"].path, given["root"] / store_dir,
                     given["registries"], counts or given["counts"])


def test_build_stores_the_oracle_rows_on_text_and_struct(given):
    result = _build(given)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-REFINT", "G-KG0", "G-PROV"]
    built = store.read_layer(result.layers["kg0"].path)
    assert built.depends_on == {"text": given["text"].version, "struct": given["struct"].version}
    assert {k: list(v) for k, v in built.rows.items()} == {
        f"{k}.jsonl": v for k, v in mini_kg.kg0_layer(given["versions"]).items()}
    report = json.loads((built.path / "kg0_report.json").read_text(encoding="utf-8"))
    assert report["registries"] == given["versions"]


def test_the_stored_layer_passes_its_gates_and_rebuilds_identically(given):
    first, second = _build(given, "a"), _build(given, "b")
    assert check_det(first.layers["kg0"].path, second.layers["kg0"].path).passed
    report = gate_layer(first.layers["kg0"].path, "kg0",
                        [given["text"].path, given["struct"].path],
                        inputs=GateInputs(kg0_counts=given["counts"]))
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]


def test_a_red_build_stores_nothing(given):
    counts = given["root"] / "red.yaml"
    doc = yaml.safe_load(given["counts"].read_text(encoding="utf-8"))
    counts.write_bytes(mini_kg.dump({**doc, "names": 6}))
    result = _build(given, counts=counts)
    assert not result.passed and result.layers == {}
    assert not (given["root"] / "store").exists()


def test_struct_must_be_built_on_the_given_text(given):
    other, _ = mini_build.write_layers(given["root"] / "other",
                                       text={**mini_build.text_layer(), "speakers": []})
    with pytest.raises(StageError, match="was built on"):
        build_kg0(other.path, given["struct"].path, given["root"] / "s", given["registries"],
                  given["counts"])
    with pytest.raises(StageError, match="not a struct layer"):
        build_kg0(given["text"].path, given["text"].path, given["root"] / "s",
                  given["registries"], given["counts"])


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_expect_build_and_gate_kg0(given, capsys):
    out = given["root"] / "expect.yaml"
    code, _ = _cli(capsys, "expect", "kg0", "--text", given["text"].path,
                   "--struct", given["struct"].path, "--registries", given["registries"],
                   "--out", out)
    assert code == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == yaml.safe_load(
        given["counts"].read_text(encoding="utf-8"))
    code, captured = _cli(capsys, "build", "kg0", "--text", given["text"].path,
                          "--struct", given["struct"].path, "--registries", given["registries"],
                          "--kg0-counts", out, "--store", given["root"] / "cli")
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["kg0"]["path"]
    code, captured = _cli(capsys, "gate", "kg0", layer, "--dep", given["text"].path,
                          "--dep", given["struct"].path, "--kg0-counts", out)
    assert code == 0 and json.loads(captured.out)["pass"] is True


def test_cli_build_kg0_needs_struct(given, capsys):
    code, captured = _cli(capsys, "build", "kg0", "--text", given["text"].path)
    assert code == 2 and "--struct" in captured.err
