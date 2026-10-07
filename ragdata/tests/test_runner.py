"""Gate runner over stored layers, and the G-DET comparison of two runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_build
from ragdata import store
from ragdata.gates import check_det
from ragdata.gates import runner
from ragdata.gates.runner import GateInputError, gate_layer

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
GATES = ["G-SCHEMA", "G-COUNT", "G-REFINT"]


def test_text_layer_report_lists_every_gate_and_passes(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    report = gate_layer(text.path, "text", counts_path=MINI_COUNTS)
    doc = report.to_json()
    assert report.passed and doc["pass"]
    assert [g["name"] for g in doc["gates"]] == GATES
    assert (doc["layer"], doc["layer_version"]) == ("text", text.version)


def test_struct_layer_is_gated_with_its_declared_text_layer(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    report = gate_layer(struct.path, "struct", deps=[text.path], counts_path=MINI_COUNTS)
    assert report.passed, report.to_json()
    assert report.to_json()["depends_on"] == {"text": text.version}


def test_real_pdf_counts_turn_the_mini_layer_red_on_g_count_only(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    doc = gate_layer(text.path, "text").to_json()
    assert not doc["pass"]
    assert {g["name"]: g["pass"] for g in doc["gates"]} == {
        "G-SCHEMA": True, "G-COUNT": False, "G-REFINT": True}


def test_struct_without_its_dependency_is_an_input_error(tmp_path):
    _, struct = mini_build.write_layers(tmp_path)
    with pytest.raises(GateInputError):
        gate_layer(struct.path, "struct", counts_path=MINI_COUNTS)


def test_dependency_version_must_match_the_manifest(tmp_path):
    _, struct = mini_build.write_layers(tmp_path / "a")
    rows = mini_build.text_layer()
    rows["ref_aliases"] = []
    other_text, _ = mini_build.write_layers(tmp_path / "b", text=rows)
    with pytest.raises(GateInputError):
        gate_layer(struct.path, "struct", deps=[other_text.path], counts_path=MINI_COUNTS)


def _other_text_rows():
    rows = mini_build.text_layer()
    rows["ref_aliases"] = []
    return rows


def test_identical_struct_bytes_on_a_new_text_version_get_their_own_version(tmp_path):
    text_a, struct_a = mini_build.write_layers(tmp_path)
    text_b, struct_b = mini_build.write_layers(tmp_path, text=_other_text_rows())
    assert struct_a.version != struct_b.version
    report = gate_layer(struct_b.path, "struct", [text_b.path], MINI_COUNTS)
    assert report.depends_on == {"text": text_b.version}


def test_repointing_the_manifest_at_another_text_version_is_refused(tmp_path):
    _, struct = mini_build.write_layers(tmp_path / "a")
    other_text, _ = mini_build.write_layers(tmp_path / "b", text=_other_text_rows())
    manifest_path = struct.path / store.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["depends_on"] = {"text": other_text.version}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(store.IntegrityError):
        gate_layer(struct.path, "struct", [other_text.path], MINI_COUNTS)


def test_layer_dir_must_hold_the_requested_layer(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    with pytest.raises(GateInputError):
        gate_layer(text.path, "struct", deps=[text.path], counts_path=MINI_COUNTS)


def test_tampered_layer_is_refused_before_gating(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    (text.path / "verse_units.jsonl").write_bytes(b"")
    with pytest.raises(store.IntegrityError):
        gate_layer(text.path, "text", counts_path=MINI_COUNTS)


def _struct_carrying_text_file(layer):
    units = mini_build.text_layer()["verse_units"]
    next(u for u in units if u["unit_key"] == "act.9.1")["is_poetry"] = True
    layer["verse_units"] = units


def _text_carrying_struct_file(layer):
    layer["pericopes"] = mini_build.struct_layer()["pericopes"]


def _text_carrying_unknown_file(layer):
    layer["verses"] = [{"unit_key": "act.9.1"}]


@pytest.mark.parametrize("smuggle,gated", [
    (_struct_carrying_text_file, "struct"),
    (_text_carrying_struct_file, "text"),
    (_text_carrying_unknown_file, "text"),
], ids=["struct-has-text-file", "text-has-struct-file", "text-has-unknown-file"])
def test_a_layer_holding_files_of_another_layer_is_refused(tmp_path, smuggle, gated):
    text_rows, struct_rows = mini_build.text_layer(), mini_build.struct_layer()
    smuggle(struct_rows if gated == "struct" else text_rows)
    text, struct = mini_build.write_layers(tmp_path, text=text_rows, struct=struct_rows)
    target, deps = (struct.path, [text.path]) if gated == "struct" else (text.path, [])
    with pytest.raises(GateInputError, match="does not belong"):
        gate_layer(target, gated, deps, MINI_COUNTS)


def test_a_file_outside_every_contract_is_refused_whatever_its_type(tmp_path):
    files = {f"{name}.jsonl": store.encode_jsonl(rows)
             for name, rows in mini_build.text_layer().items()}
    text = store.write_layer(tmp_path, "text", {**files, "notes.txt": b"unchecked\n"})
    with pytest.raises(GateInputError, match="notes.txt"):
        gate_layer(text.path, "text", counts_path=MINI_COUNTS)


def test_merging_layers_never_lets_one_file_replace_another(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    loaded = store.read_layer(text.path)
    with pytest.raises(GateInputError, match="twice"):
        runner.merge_files([loaded, loaded])


def test_det_passes_for_identical_runs(tmp_path):
    a, _ = mini_build.write_layers(tmp_path / "run1")
    b, _ = mini_build.write_layers(tmp_path / "run2")
    result = check_det(a.path, b.path)
    assert result.passed and result.name == "G-DET" and result.hard
    assert result.observed["differing_files"] == 0


def test_det_names_the_files_that_differ(tmp_path):
    a, _ = mini_build.write_layers(tmp_path / "run1")
    rows = mini_build.text_layer()
    rows["books"][0]["ord"] = 18
    b, _ = mini_build.write_layers(tmp_path / "run2", text=rows)
    result = check_det(a.path, b.path)
    assert not result.passed
    assert result.details == ("books.jsonl: sha256 differs",)


def test_det_reports_files_present_in_only_one_run(tmp_path):
    a, _ = mini_build.write_layers(tmp_path / "run1")
    rows = mini_build.text_layer()
    del rows["ref_aliases"]
    b, _ = mini_build.write_layers(tmp_path / "run2", text=rows)
    result = check_det(a.path, b.path)
    assert not result.passed
    assert result.details == ("ref_aliases.jsonl: only in the first run",)


def test_det_refuses_to_call_different_layers_identical(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    result = check_det(text.path, struct.path)
    assert not result.passed
    assert result.details[-1] == "layers differ: text vs struct"


def test_det_sees_runs_built_on_different_dependencies(tmp_path):
    _, struct_a = mini_build.write_layers(tmp_path)
    _, struct_b = mini_build.write_layers(tmp_path, text=_other_text_rows())
    result = check_det(struct_a.path, struct_b.path)
    assert not result.passed
    assert result.details == ("depends_on.json: sha256 differs",)


def test_det_refuses_to_compare_a_run_with_itself(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(text.path)
    for second in (text.path, alias, text.path / ".." / text.path.name):
        with pytest.raises(GateInputError, match="same"):
            check_det(text.path, second)


def test_a_report_without_gates_does_not_pass():
    from ragdata.gates.runner import GateReport
    assert not GateReport("text", "text@0123456789ab", {}, ()).passed
