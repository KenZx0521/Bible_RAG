"""``convert events`` and ``build events`` on the mini snapshot, through the runner and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import mini_build
import mini_kg
from ragdata import cli, store
from ragdata.gates import check_det
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg import k1_build
from ragdata.kg.k1_events import EventRegistryError

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


@pytest.fixture()
def given(tmp_path):
    text, struct = mini_build.write_layers(tmp_path / "given")
    legacy = tmp_path / "event_registry.json"
    legacy.write_text(json.dumps(mini_kg.legacy_registry(), ensure_ascii=False), encoding="utf-8")
    events_yaml = tmp_path / "events.yaml"
    events_yaml.write_text(k1_build.convert(text.path, struct.path, legacy), encoding="utf-8")
    return {"text": text, "struct": struct, "legacy": legacy, "yaml": events_yaml,
            "root": tmp_path}


def _build(given, store_dir="store", legacy=None, counts=MINI_COUNTS):
    return k1_build.build_events(given["text"].path, given["struct"].path,
                                 given["root"] / store_dir, given["yaml"],
                                 legacy or given["legacy"], counts)


def test_build_stores_the_registry_and_its_contract_files(given):
    result = _build(given)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-COUNT", "G-REFINT", "G-EVENT",
                                              "G-PROV"]
    built = store.read_layer(result.layers["events"].path)
    events = list(built.rows["events.jsonl"])
    assert [e["event_id"] for e in events] == ["ev0001", "ev0002", "ev0003"]
    assert [c["change"] for c in built.rows["anchor_changes.jsonl"]] == ["narrowed", "widened"]
    v1 = json.loads((built.path / "event_registry_v1.json").read_text(encoding="utf-8"))
    assert v1["events"][0]["anchors"] == ["ps:psa.42.1"]
    report = json.loads((built.path / "events_report.json").read_text(encoding="utf-8"))
    assert report["counts"]["anchors"] == 4 and report["source"]["file"] == "event_registry.json"


def test_gate_and_det(given):
    first, second = _build(given, "a"), _build(given, "b")
    assert check_det(first.layers["events"].path, second.layers["events"].path).passed
    report = gate_layer(first.layers["events"].path, "events",
                        [given["text"].path, given["struct"].path], MINI_COUNTS,
                        inputs=GateInputs(legacy_registry=given["legacy"]))
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]


def test_without_the_legacy_registry_the_build_is_red(given):
    result = _build(given, legacy=given["root"] / "missing.json")
    assert not result.passed and result.layers == {}


def test_a_hand_edited_registry_is_refused(given):
    doc = yaml.safe_load(given["yaml"].read_text(encoding="utf-8"))
    doc["events"][0]["anchors"][0]["change"] = "widened"
    given["yaml"].write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(EventRegistryError, match="drifted"):
        _build(given)


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_convert_build_and_gate_events(given, capsys):
    out = given["root"] / "cli_events.yaml"
    code, _ = _cli(capsys, "convert", "events", "--text", given["text"].path,
                   "--struct", given["struct"].path, "--legacy-registry", given["legacy"],
                   "--out", out)
    assert code == 0 and out.read_text(encoding="utf-8") == given["yaml"].read_text(
        encoding="utf-8")
    code, captured = _cli(capsys, "build", "events", "--text", given["text"].path,
                          "--struct", given["struct"].path, "--events-yaml", out,
                          "--legacy-registry", given["legacy"], "--counts", MINI_COUNTS,
                          "--store", given["root"] / "cli")
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["events"]["path"]
    code, captured = _cli(capsys, "gate", "events", layer, "--dep", given["text"].path,
                          "--dep", given["struct"].path, "--counts", MINI_COUNTS,
                          "--legacy-registry", given["legacy"])
    assert code == 0 and json.loads(captured.out)["pass"] is True


def test_cli_convert_reports_an_unconvertible_registry(given, capsys):
    doc = mini_kg.legacy_registry()
    doc["events"][0]["anchors"] = ["psa:1:0"]
    given["legacy"].write_text(json.dumps(doc), encoding="utf-8")
    code, captured = _cli(capsys, "convert", "events", "--text", given["text"].path,
                          "--struct", given["struct"].path, "--legacy-registry", given["legacy"],
                          "--out", given["root"] / "x.yaml")
    assert code == 2 and "psa:1:0" in captured.err
