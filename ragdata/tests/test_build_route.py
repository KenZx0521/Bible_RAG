"""``build route``, G-ROUTE and ``freeze route`` on the mini text layer and a fake backend."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import fake_backend
import mini_build
import mini_kg
from ragcommon import routing
from ragdata import cli, store
from ragdata.gates import check_det
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg import k4_build, k4_route
from ragdata.legacy import route_live
from ragdata.stages.errors import StageError

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


@pytest.fixture()
def given(tmp_path):
    text, _ = mini_build.write_layers(tmp_path / "given")
    backend = fake_backend.write(tmp_path / "repo")
    lexicon = tmp_path / "routing_lexicon.legacy.json"
    lexicon.write_bytes(routing.render_lexicon(route_live.freeze(backend)))
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps({"questions": [{"question": q} for q in mini_kg.GT_QUESTIONS]},
                             ensure_ascii=False), encoding="utf-8")
    return {"text": text, "backend": backend, "lexicon": lexicon, "gt": gt, "root": tmp_path,
            "live": lambda texts: route_live.probe(backend, texts)}


def _build(given, store_dir="store", live=None, lexicon=None):
    return k4_build.build_route(given["text"].path, given["root"] / store_dir,
                                live or given["live"], lexicon or given["lexicon"], given["gt"],
                                MINI_COUNTS)


def test_build_stores_the_frozen_lexicon_and_its_terms(given):
    result = _build(given)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-COUNT", "G-ROUTE", "G-PROV"]
    built = store.read_layer(result.layers["route"].path)
    assert (built.path / "routing_lexicon.json").read_bytes() == given["lexicon"].read_bytes()
    terms = list(built.rows["routing_terms.jsonl"])
    assert [t["term_key"] for t in terms][:2] == ["persons/0000", "persons/0001"]
    report = json.loads((built.path / "route_report.json").read_text(encoding="utf-8"))
    assert report["probes"]["ground_truth"] == 3 and report["probes"]["verses"] == 14
    assert report["zero_in_verses"]["places"] == ["死海"]
    gate = next(g for g in result.gates if g.name == "G-ROUTE")
    assert gate.observed["mismatches"] == 0 and gate.observed["probes"] == 3 + 14 + 6


def test_a_matcher_that_disagrees_with_the_live_one_is_red(given):
    def wrong(texts):
        return [{**r, "persons": []} for r in route_live.probe(given["backend"], texts)]
    result = _build(given, live=wrong)
    assert not result.passed and result.layers == {}


def test_terms_must_be_external_legacy_retiring_by_r2(given):
    doc = json.loads(given["lexicon"].read_text(encoding="utf-8"))
    doc["events"][0]["provenance_class"] = "external_query"
    changed = given["root"] / "changed.json"
    changed.write_bytes(routing.render_lexicon(doc))
    result = _build(given, lexicon=changed)
    route = next(g for g in result.gates if g.name == "G-ROUTE")
    assert not route.passed and "R2" in " ".join(route.details)


def test_the_gate_reruns_the_live_backend_in_a_subprocess(given):
    first, second = _build(given, "a"), _build(given, "b")
    assert check_det(first.layers["route"].path, second.layers["route"].path).passed
    inputs = GateInputs(frozen_lexicon=given["lexicon"], ground_truth=given["gt"],
                        backend_python=Path(sys.executable), backend_dir=given["backend"])
    report = gate_layer(first.layers["route"].path, "route", [given["text"].path], MINI_COUNTS,
                        inputs=inputs)
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]


@pytest.mark.parametrize("change", ["frozen", "python", "gt"])
def test_the_gate_fails_closed_without_its_inputs(given, change):
    layer = _build(given).layers["route"].path
    inputs = {"frozen_lexicon": given["lexicon"], "ground_truth": given["gt"],
              "backend_python": Path(sys.executable), "backend_dir": given["backend"]}
    key = {"frozen": "frozen_lexicon", "python": "backend_python", "gt": "ground_truth"}[change]
    inputs[key] = given["root"] / "missing"
    report = gate_layer(layer, "route", [given["text"].path], MINI_COUNTS,
                        inputs=GateInputs(**inputs))
    assert not report.passed


def test_a_failing_live_backend_is_reported(given):
    probe = k4_route.subprocess_probe(Path(sys.executable), given["root"] / "nowhere")
    with pytest.raises(StageError, match="route_live probe failed"):
        probe(["掃羅"])


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_freeze_build_and_gate_route(given, capsys):
    out = given["root"] / "cli_lexicon.json"
    code, captured = _cli(capsys, "freeze", "route", "--backend-python", sys.executable,
                          "--backend-dir", given["backend"], "--out", out)
    assert code == 0, captured.err
    assert out.read_bytes() == given["lexicon"].read_bytes()
    code, captured = _cli(capsys, "build", "route", "--text", given["text"].path,
                          "--lexicon", out, "--ground-truth", given["gt"],
                          "--backend-python", sys.executable, "--backend-dir", given["backend"],
                          "--counts", MINI_COUNTS, "--store", given["root"] / "cli")
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["route"]["path"]
    code, captured = _cli(capsys, "gate", "route", layer, "--dep", given["text"].path,
                          "--lexicon", out, "--ground-truth", given["gt"],
                          "--backend-python", sys.executable, "--backend-dir", given["backend"],
                          "--counts", MINI_COUNTS)
    assert code == 0 and json.loads(captured.out)["pass"] is True


def test_cli_freeze_needs_a_backend_python(given, capsys):
    code, captured = _cli(capsys, "freeze", "route", "--backend-python", given["root"] / "none",
                          "--out", given["root"] / "x.json")
    assert code == 2 and "--backend-python" in captured.err
