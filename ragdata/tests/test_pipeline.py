"""``ragdata pipeline run`` over the mini snapshot: order, reuse, stops and their reasons."""

from __future__ import annotations

import dataclasses
import json

import pytest

import mini_pipeline
from ragdata.gates.base import GateResult
from ragdata.gt.gate import GtReport
from ragdata.loader.config import ConfigError
from ragdata.pipeline import derived
from ragdata.pipeline.run import GATE, INPUT, run
from ragdata.pipeline.steps import ORDER

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")
OTHER_TEXT = "text@000000000000"


@pytest.fixture()
def mini(tmp_path):
    return mini_pipeline.make(tmp_path)


def _stopped(report):
    assert not report.passed, "the run was expected to stop"
    return report.stop


def test_a_run_builds_every_layer_then_releases_loads_and_verifies(mini):
    report = run(mini.pipeline())
    assert report.passed, report.stop and report.stop.to_json()
    doc = report.to_json()
    assert list(doc["layers"]) == list(ORDER)
    assert doc["layers"]["text"]["version"] == mini.text_version
    assert doc["layers"]["struct"]["version"] == mini.struct_version
    assert not any(entry["reused"] for entry in doc["layers"].values())
    assert all(all(entry["gates"].values()) for entry in doc["layers"].values())
    assert "embedding_records.jsonl" in doc["layers"]["emb"]["files"]
    assert "vectors.npy" in doc["layers"]["emb"]["vectors"]
    build_id = doc["release"]["build_id"]
    assert doc["release"]["existed"] is False
    assert (mini.releases / f"{build_id}.json").is_file()
    assert doc["load"]["reused"] is False and doc["load"]["build_id"] == build_id
    assert doc["verify"]["pass"] is True and doc["gt"]["slot_universe"] == mini.text_version
    assert mini.pg.build_row(build_id) is not None


def test_a_second_run_reuses_every_layer_and_names_the_same_build(mini):
    first = run(mini.pipeline()).to_json()
    second = run(mini.pipeline()).to_json()
    assert second["pass"] is True
    assert all(entry["reused"] for entry in second["layers"].values())
    assert {k: v["version"] for k, v in second["layers"].items()} == \
        {k: v["version"] for k, v in first["layers"].items()}
    assert {k: v["files"] for k, v in second["layers"].items()} == \
        {k: v["files"] for k, v in first["layers"].items()}
    assert second["release"]["build_id"] == first["release"]["build_id"]
    assert second["release"]["existed"] is True and second["load"]["reused"] is True
    assert second["verify"]["pass"] is True


def test_a_red_build_gate_stops_at_its_layer_and_nothing_after_it_runs(mini):
    counts = mini.root / "red_counts.yaml"
    counts.write_text(mini.sources.counts.read_text(encoding="utf-8").replace(
        "  pericopes: {value: 6,", "  pericopes: {value: 7,"), encoding="utf-8")
    assert counts.read_text(encoding="utf-8") != mini.sources.counts.read_text(encoding="utf-8")
    sources = dataclasses.replace(mini.sources, counts=counts)
    report = run(mini.pipeline(sources=sources))
    stop = _stopped(report)
    assert (stop.where, stop.kind, stop.version) == ("struct", GATE, None)
    assert stop.red[0].startswith("G-COUNT:")
    assert list(report.to_json()["layers"]) == ["text"]
    assert not mini.releases.exists() and not mini.pg.builds


def test_a_required_gate_that_did_not_run_stops_the_layer_it_belongs_to(mini):
    store = mini.root / "store"
    text = mini_pipeline.text_step(store, mini.sources, full_gates=True)
    stop = _stopped(run(mini.pipeline(text=text)))
    assert (stop.where, stop.version) == ("text", mini.text_version)
    assert set(stop.red) == {"G-CONSERVE: not run", "G-XCHECK: not run"}


def test_stale_derived_files_stop_after_struct_with_the_commands_in_order(mini):
    mini.files.versification.write_text(json.dumps({"source": {"layer_version": OTHER_TEXT}}),
                                        encoding="utf-8")
    mini.files.gt.write_text(json.dumps({"metadata": {"slot_universe": OTHER_TEXT}}),
                             encoding="utf-8")
    kg0 = mini.files.kg0_counts
    kg0.write_text(kg0.read_text(encoding="utf-8").replace(mini.struct_version,
                                                           "struct@000000000000"),
                   encoding="utf-8")
    report = run(mini.pipeline())
    stop = _stopped(report)
    assert (stop.where, stop.kind) == ("derived", INPUT)
    assert [line.split(" names ")[0] for line in stop.red] == [
        str(mini.files.versification), str(kg0), str(mini.files.gt)]
    commands = list(stop.commands)
    assert "derive_ragcommon_data.py versification" in commands[0]
    assert commands[1].startswith("git add packages/ragcommon/data")
    assert " expect kg0 " in commands[2] and mini.struct_version in commands[2]
    assert " gt build --text-layer " in commands[3] and mini.text_version in commands[3]
    assert commands[-1].endswith("(again; finished layers are reused)")
    assert list(report.to_json()["layers"]) == ["text", "struct"]


def test_only_the_stale_files_get_their_commands(mini):
    mini.files.freeze.write_text(json.dumps({"slot_universe": OTHER_TEXT}), encoding="utf-8")
    stop = _stopped(run(mini.pipeline()))
    assert [c.split(" -m ragdata ")[-1].split(" ")[0:2] for c in stop.commands[:1]] == \
        [["gt", "build"]]
    assert not any("derive_ragcommon_data" in c or "expect kg0" in c for c in stop.commands)


def test_a_red_g_gt_stops_at_gt(mini):
    red = GateResult("G-GT.quote", True, False, {}, {}, ("Q1: not service text",))
    stop = _stopped(run(mini.pipeline(gt=lambda built: GtReport(OTHER_TEXT, (red,)))))
    assert (stop.where, stop.kind) == ("gt", GATE)
    assert stop.red == ("G-GT.quote: ['Q1: not service text']",)


def test_a_red_projection_stops_at_verify(mini):
    inputs = mini.verify_inputs(freeze=mini.root / "other_freeze.json")
    (mini.root / "other_freeze.json").write_text(json.dumps({"sha256": "0" * 64,
                                                             "slot_universe": OTHER_TEXT}))
    report = run(mini.pipeline(databases=mini.databases(verify_inputs=inputs)))
    stop = _stopped(report)
    assert (stop.where, stop.kind) == ("verify", GATE)
    assert [r.split(":")[0] for r in stop.red] == ["G-PROJ.C6"]
    assert report.to_json()["load"]["reused"] is False


def test_bad_input_inside_a_step_stops_there_as_input(mini):
    sources = dataclasses.replace(mini.sources, events_yaml=mini.root / "missing.yaml")
    stop = _stopped(run(mini.pipeline(sources=sources)))
    assert (stop.where, stop.kind) == ("events", INPUT)
    assert stop.red[0].startswith("EventRegistryError:")


def test_a_build_registered_with_another_release_is_not_loaded_over(mini):
    build_id = run(mini.pipeline()).to_json()["release"]["build_id"]
    mini.pg.builds[build_id]["manifest_sha"] = "0" * 64
    stop = _stopped(run(mini.pipeline()))
    assert (stop.where, stop.kind) == ("load", INPUT)
    assert "refusing to load" in stop.red[0]


def test_databases_that_cannot_be_reached_stop_at_load(mini):
    def refuse():
        raise ConfigError("missing settings ['POSTGRES_HOST']")
    stop = _stopped(run(mini.pipeline(databases=mini.databases(connect=refuse))))
    assert (stop.where, stop.kind) == ("load", INPUT)


def test_verify_alone_checks_a_build_loaded_before(mini):
    run(mini.pipeline())
    report = run(mini.pipeline(databases=mini.databases(load=False)))
    assert report.passed and "load" not in report.to_json()


def test_a_stop_also_lists_the_commands_for_files_that_may_explain_it(mini):
    mini.files.versification.write_text(json.dumps({"source": {"layer_version": OTHER_TEXT}}),
                                        encoding="utf-8")
    store = mini.root / "store"
    stop = _stopped(run(mini.pipeline(text=mini_pipeline.text_step(store, mini.sources, True))))
    assert stop.where == "text"
    assert "derive_ragcommon_data.py versification" in stop.commands[0]


def test_derived_files_that_cannot_be_read_are_said_so_with_the_stop(mini):
    mini.files.versification.unlink()
    store = mini.root / "store"
    stop = _stopped(run(mini.pipeline(text=mini_pipeline.text_step(store, mini.sources, True))))
    assert stop.where == "text"
    assert stop.commands[0].startswith("(the derived files could not be checked:")


def test_without_text_nothing_is_stale():
    assert derived.stale({}, derived.DerivedFiles()) == []
    assert derived.commands({}, []) == []


@pytest.mark.parametrize("content, message", [("[]", "not a JSON object"),
                                              ("{", "unreadable")])
def test_a_derived_file_that_is_not_a_json_object_is_bad_input(mini, content, message):
    mini.files.gt.write_text(content, encoding="utf-8")
    stop = _stopped(run(mini.pipeline()))
    assert (stop.where, stop.kind) == ("derived", INPUT)
    assert stop.red[0].startswith("DerivedError:") and message in stop.red[0]


def test_a_field_under_a_value_that_is_not_an_object_reads_as_none(mini):
    mini.files.versification.write_text(json.dumps({"source": "text"}), encoding="utf-8")
    stop = _stopped(run(mini.pipeline()))
    assert stop.red == (f"{mini.files.versification} names None, this run built "
                        f"{mini.text_version}",)
