"""``build events`` (K1, R2) on the mini snapshot, through the runner and the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_build
import mini_kg
from ragdata import cli, store
from ragdata.gates import check_det
from ragdata.gates.runner import gate_layer
from ragdata.kg import k1_build
from ragdata.kg.k1_events import EventRegistryError

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


@pytest.fixture()
def given(tmp_path):
    text, struct = mini_build.write_layers(tmp_path / "given")
    return {"text": text, "struct": struct, "root": tmp_path,
            "yaml": mini_kg.write_events_yaml(tmp_path / "events.yaml")}


def _build(given, store_dir="store"):
    return k1_build.build_events(given["text"].path, given["struct"].path,
                                 given["root"] / store_dir, given["yaml"], MINI_COUNTS)


def test_build_stores_the_records_the_contract_and_the_report(given):
    result = _build(given)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-COUNT", "G-REFINT", "G-EVENT",
                                              "G-PROV"]
    built = store.read_layer(result.layers["events"].path)
    assert set(built.rows) == {"events.jsonl"}
    assert list(built.rows["events.jsonl"]) == mini_kg.events()
    assert built.depends_on == {"text": given["text"].version, "struct": given["struct"].version}
    v2 = json.loads((built.path / "event_registry_v2.json").read_text(encoding="utf-8"))
    assert v2["variant"] == "R2" and v2["struct"] == given["struct"].version
    report = json.loads((built.path / "events_report.json").read_text(encoding="utf-8"))
    assert report["registry"].startswith("events@") and report["counts"]["anchors"] == 6


def test_gate_and_det(given):
    first, second = _build(given, "a"), _build(given, "b")
    assert check_det(first.layers["events"].path, second.layers["events"].path).passed
    report = gate_layer(first.layers["events"].path, "events",
                        [given["text"].path, given["struct"].path], MINI_COUNTS)
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]


def test_a_red_gate_stores_nothing(given):
    doc = mini_kg.events_yaml()
    doc["events"][1]["pdf_terms"].append({"text": "門徒", "at": "act.9.1"})
    mini_kg.write_events_yaml(given["yaml"], doc)
    result = _build(given)
    assert not result.passed and result.layers == {}
    red = {g.name for g in result.gates if not g.passed}
    assert red == {"G-COUNT", "G-EVENT"}


def test_a_registry_that_does_not_compile_is_refused(given):
    doc = mini_kg.events_yaml()
    doc["events"][0]["anchors"] = ["pc:psa.41.1"]
    mini_kg.write_events_yaml(given["yaml"], doc)
    with pytest.raises(EventRegistryError, match="pc:psa.41.1"):
        _build(given)


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_build_and_gate_events(given, capsys):
    code, captured = _cli(capsys, "build", "events", "--text", given["text"].path,
                          "--struct", given["struct"].path, "--events-yaml", given["yaml"],
                          "--counts", MINI_COUNTS, "--store", given["root"] / "cli")
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["events"]["path"]
    code, captured = _cli(capsys, "gate", "events", layer, "--dep", given["text"].path,
                          "--dep", given["struct"].path, "--counts", MINI_COUNTS)
    assert code == 0 and json.loads(captured.out)["pass"] is True


def test_cli_reports_a_registry_that_does_not_compile(given, capsys):
    given["yaml"].write_text("schema: ragdata.events.v1\n", encoding="utf-8")
    code, captured = _cli(capsys, "build", "events", "--text", given["text"].path,
                          "--struct", given["struct"].path, "--events-yaml", given["yaml"],
                          "--counts", MINI_COUNTS, "--store", given["root"] / "cli")
    assert code == 2 and "events.yaml" in captured.err
