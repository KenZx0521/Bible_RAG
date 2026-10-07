"""Gate runner over stored layers, and the G-DET comparison of two runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_build
from ragdata import store
from ragdata.gates import check_det
from ragdata.gates import runner
from ragdata.gates.runner import GateInputError, GateInputs, gate_layer
from ragdata.stages.s05_struct.tokens import TokenCounter

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
BUILT = {"G-SCHEMA", "G-COUNT", "G-REFINT"}
RECORD = {"G-SCHEMA", "G-COUNT", "G-REFINT", "G-TEXT", "G-REF"}
MINI = GateInputs(versification=mini_build.versification(),
                  token_counter=TokenCounter(mini_build.count_tokens, {}))


def _verdicts(report) -> dict[str, bool]:
    return {g.name: g.passed for g in report.gates}


def test_every_gate_design_section_8_requires_is_in_the_report(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    for path, layer, deps in ((text.path, "text", []), (struct.path, "struct", [text.path])):
        doc = gate_layer(path, layer, deps, MINI_COUNTS).to_json()
        assert [g["name"] for g in doc["gates"]] == list(runner.REQUIRED_GATES[layer])
        assert doc["required_gates"] == list(runner.REQUIRED_GATES[layer])
    assert {"G-TEXT", "G-CONSERVE", "G-XCHECK", "G-REF"} <= set(runner.REQUIRED_GATES["text"])
    assert "G-STRUCT" in runner.REQUIRED_GATES["struct"]


def test_a_gate_not_built_yet_fails_closed(tmp_path, monkeypatch):
    required = (*runner.REQUIRED_GATES["struct"], "G-FUTURE")
    monkeypatch.setattr(runner, "REQUIRED_GATES", {**runner.REQUIRED_GATES, "struct": required})
    text, struct = mini_build.write_layers(tmp_path)
    report = gate_layer(struct.path, "struct", [text.path], MINI_COUNTS, inputs=MINI)
    unbuilt = [g for g in report.gates if g.observed == "not implemented"]
    assert [g.name for g in unbuilt] == ["G-FUTURE"] and not report.passed
    assert all(g.hard and not g.passed for g in unbuilt)
    assert all(_verdicts(report)[name] for name in runner.implemented_gates("struct"))


def test_the_struct_layer_passes_every_required_gate(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    report = gate_layer(struct.path, "struct", [text.path], MINI_COUNTS, inputs=MINI)
    assert report.passed, report.to_json()


def test_g_struct_without_its_tokenizer_fails_closed(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    report = gate_layer(struct.path, "struct", [text.path], MINI_COUNTS, gates=["G-STRUCT"],
                        inputs=GateInputs(tokenizer=tmp_path / "tokenizer.json"))
    (gate,) = report.gates
    assert (gate.passed, gate.observed) == (False, "missing input")


def test_a_gate_whose_input_is_not_given_fails_closed(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    report = gate_layer(text.path, "text", counts_path=MINI_COUNTS, inputs=MINI)
    red = {g.name: g for g in report.gates if not g.passed}
    assert set(red) == {"G-CONSERVE", "G-XCHECK"} and not report.passed
    assert all(g.hard and g.observed == "missing input" for g in red.values())
    assert all(_verdicts(report)[name] for name in RECORD)


def test_record_gates_alone_never_make_a_passing_report(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    report = gate_layer(text.path, "text", counts_path=MINI_COUNTS, inputs=MINI,
                        gates=runner.record_gates("text"))
    assert set(_verdicts(report)) == RECORD and all(_verdicts(report).values())
    assert not report.passed
    assert set(report.to_json()["missing_gates"]) == set(runner.REQUIRED_GATES["text"]) - RECORD


def test_g_ref_uses_ragcommon_unless_told_otherwise(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    report = gate_layer(text.path, "text", counts_path=MINI_COUNTS, gates=["G-REF"])
    assert _verdicts(report) == {"G-REF": False}  # the mini grid is not the PDF's


def test_report_passes_once_every_required_gate_runs_and_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REQUIRED_GATES", {"text": tuple(sorted(BUILT)),
                                                   "struct": tuple(sorted(BUILT))})
    text, struct = mini_build.write_layers(tmp_path)
    assert gate_layer(text.path, "text", counts_path=MINI_COUNTS).passed
    report = gate_layer(struct.path, "struct", [text.path], MINI_COUNTS)
    assert report.passed and report.to_json()["missing_gates"] == []
    assert (report.layer, report.layer_version) == ("struct", struct.version)
    assert report.to_json()["depends_on"] == {"text": text.version}


@pytest.mark.parametrize("gates", [(), ("G-NOPE",), ("G-SCHEMA", "G-SCHEMA"), ("G-STRUCT",)],
                         ids=["none", "unknown", "twice", "other-layer"])
def test_asking_for_gates_the_layer_does_not_have_is_an_input_error(tmp_path, gates):
    text, _ = mini_build.write_layers(tmp_path)
    with pytest.raises(GateInputError):
        gate_layer(text.path, "text", counts_path=MINI_COUNTS, gates=gates)


def test_real_pdf_counts_turn_the_mini_layer_red_on_g_count_only(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    report = gate_layer(text.path, "text", gates=sorted(BUILT))
    assert _verdicts(report) == {"G-SCHEMA": True, "G-COUNT": False, "G-REFINT": True}


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
    report = gate_layer(struct_b.path, "struct", [text_b.path], MINI_COUNTS,
                        gates=runner.implemented_gates("struct"), inputs=MINI)
    assert report.depends_on == {"text": text_b.version}
    assert all(_verdicts(report).values())


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


def test_a_report_without_gates_or_requirements_does_not_pass():
    from ragdata.gates.base import GateResult
    from ragdata.gates.runner import GateReport
    green = GateResult("G-SCHEMA", True, True, 0, 0, ())
    assert not GateReport("text", "text@0123456789ab", {}, (), ("G-SCHEMA",)).passed
    assert not GateReport("text", "text@0123456789ab", {}, (green,), ()).passed
    assert GateReport("text", "text@0123456789ab", {}, (green,), ("G-SCHEMA",)).passed


def test_a_text_layer_built_on_a_src_layer_is_gated_on_its_records(tmp_path):
    files = {f"{name}.jsonl": store.encode_jsonl(rows)
             for name, rows in mini_build.text_layer().items()}
    text = store.write_layer(tmp_path, "text", files, depends_on={"src": "src@0123456789ab"})
    report = gate_layer(text.path, "text", counts_path=MINI_COUNTS, inputs=MINI,
                        gates=runner.record_gates("text"))
    assert all(_verdicts(report).values())
    assert report.to_json()["depends_on"] == {"src": "src@0123456789ab"}


@pytest.mark.parametrize("dep", ["emb", "kg0"])
def test_a_dependency_other_than_src_that_holds_no_records_is_refused(tmp_path, dep):
    files = {f"{name}.jsonl": store.encode_jsonl(rows)
             for name, rows in mini_build.text_layer().items()}
    text = store.write_layer(tmp_path, "text", files,
                             depends_on={"src": "src@0123456789ab", dep: f"{dep}@0123456789ab"})
    with pytest.raises(GateInputError, match=dep):
        gate_layer(text.path, "text", counts_path=MINI_COUNTS,
                   gates=runner.record_gates("text"))


def _src(root, extra=b""):
    return store.write_layer(root, "src", {"source_manifest.json": b"{}\n" + extra})


def _text_on(root, src_version):
    files = {f"{name}.jsonl": store.encode_jsonl(rows)
             for name, rows in mini_build.text_layer().items()}
    return store.write_layer(root, "text", files, depends_on={"src": src_version})


def test_the_src_layer_is_a_verified_input_not_a_record_layer(tmp_path):
    src = _src(tmp_path)
    text = _text_on(tmp_path, src.version)
    report = gate_layer(text.path, "text", [src.path], MINI_COUNTS, inputs=MINI,
                        gates=runner.record_gates("text"))
    assert all(_verdicts(report).values())


def test_a_src_layer_other_than_the_one_built_on_is_refused(tmp_path):
    text = _text_on(tmp_path, _src(tmp_path).version)
    other = _src(tmp_path, b"\n")
    with pytest.raises(GateInputError, match="built on"):
        gate_layer(text.path, "text", [other.path], MINI_COUNTS, gates=["G-SCHEMA"])


def test_src_given_twice_or_to_struct_is_refused(tmp_path):
    src = _src(tmp_path)
    text = _text_on(tmp_path, src.version)
    with pytest.raises(GateInputError, match="once"):
        gate_layer(text.path, "text", [src.path, src.path], MINI_COUNTS, gates=["G-SCHEMA"])
    _, struct = mini_build.write_layers(tmp_path / "s")
    plain_text = store.read_layer(struct.path).depends_on["text"]
    with pytest.raises(GateInputError, match="built on"):
        gate_layer(struct.path, "struct", [tmp_path / "s" / "text" / plain_text, src.path],
                   MINI_COUNTS, gates=["G-SCHEMA"])


def test_a_text_layer_may_hold_its_build_reports(tmp_path):
    files = {f"{name}.jsonl": store.encode_jsonl(rows)
             for name, rows in mini_build.text_layer().items()}
    reports = {name: b"{}\n" for name in ("xcheck_report.json", "diff_summary.json")}
    text = store.write_layer(tmp_path, "text", {**files, **reports})
    assert gate_layer(text.path, "text", counts_path=MINI_COUNTS, gates=["G-SCHEMA"]).gates
