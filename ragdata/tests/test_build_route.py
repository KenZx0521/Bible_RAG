"""``build route``, G-ROUTE and ``freeze route``/``freeze probe`` on the mini text layer and a
fake backend (the frozen matches themselves: test_k4_live)."""

from __future__ import annotations

import json
import shutil
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


def _frozen(given):
    root = given["root"] / "route_live"
    fake_backend.freeze_live(given["backend"], given["text"].path, given["lexicon"], given["gt"],
                             root)
    return root


def test_the_gate_reads_the_frozen_matches_without_a_backend(given):
    first, second = _build(given, "a"), _build(given, "b")
    assert check_det(first.layers["route"].path, second.layers["route"].path).passed
    inputs = GateInputs(frozen_lexicon=given["lexicon"], ground_truth=given["gt"],
                        route_live=_frozen(given))
    report = gate_layer(first.layers["route"].path, "route", [given["text"].path], MINI_COUNTS,
                        inputs=inputs)
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]


@pytest.mark.parametrize("change", ["frozen", "live", "gt"])
def test_the_gate_fails_closed_without_its_inputs(given, change):
    layer = _build(given).layers["route"].path
    inputs = {"frozen_lexicon": given["lexicon"], "ground_truth": given["gt"],
              "route_live": _frozen(given)}
    key = {"frozen": "frozen_lexicon", "live": "route_live", "gt": "ground_truth"}[change]
    inputs[key] = given["root"] / "missing"
    report = gate_layer(layer, "route", [given["text"].path], MINI_COUNTS,
                        inputs=GateInputs(**inputs))
    assert not report.passed


def test_a_failing_live_backend_is_reported(given):
    with pytest.raises(StageError, match="route_live probe failed"):
        k4_route.subprocess_probe(Path(sys.executable), given["root"] / "nowhere", ["掃羅"])


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_freeze_build_and_gate_route(given, capsys):
    out, live = given["root"] / "cli_lexicon.json", given["root"] / "cli_live"
    backend = ("--backend-python", sys.executable, "--backend-dir", given["backend"])
    code, captured = _cli(capsys, "freeze", "route", *backend, "--out", out)
    assert code == 0, captured.err
    assert out.read_bytes() == given["lexicon"].read_bytes()
    inputs = ("--lexicon", out, "--ground-truth", given["gt"], "--route-live", live)
    code, captured = _cli(capsys, "freeze", "probe", "--text", given["text"].path, *backend,
                          *inputs)
    assert code == 0, captured.err
    assert json.loads(captured.out)["probes"]["total"] == 3 + 14 + 6
    code, captured = _cli(capsys, "build", "route", "--text", given["text"].path, *inputs,
                          "--counts", MINI_COUNTS, "--store", given["root"] / "cli")
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["route"]["path"]
    code, captured = _cli(capsys, "gate", "route", layer, "--dep", given["text"].path, *inputs,
                          "--counts", MINI_COUNTS)
    assert code == 0 and json.loads(captured.out)["pass"] is True


def test_cli_freeze_needs_a_backend_python(given, capsys):
    code, captured = _cli(capsys, "freeze", "route", "--backend-python", given["root"] / "none",
                          "--backend-dir", given["backend"], "--out", given["root"] / "x.json")
    assert code == 2 and "--backend-python" in captured.err


def _freeze_probe(capsys, given, backend: Path, live: Path):
    return _cli(capsys, "freeze", "probe", "--text", given["text"].path,
                "--backend-python", sys.executable, "--backend-dir", backend,
                "--lexicon", given["lexicon"], "--ground-truth", given["gt"], "--route-live", live)


def test_cli_freeze_probe_refuses_a_backend_the_lexicon_was_not_frozen_from(given, capsys):
    parser = given["root"] / "repo" / "backend" / "utils" / "verse_parser.py"
    parser.write_text(parser.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    code, captured = _freeze_probe(capsys, given, given["backend"], given["root"] / "live")
    assert code == 2 and "backend/utils/verse_parser.py" in captured.err
    assert not (given["root"] / "live").exists()


def test_cli_freeze_probe_checks_the_files_imported_not_the_backend_siblings(given, capsys):
    """``--backend-dir`` not named backend/: its own utils/ run, beside an unchanged backend/."""
    changed = given["root"] / "repo" / "backend_mod"
    shutil.copytree(given["backend"], changed)
    dicts = changed / "utils" / "entity_dicts.py"
    dicts.write_text(dicts.read_text(encoding="utf-8").replace('"天國"', '"天國", "耶穌"'),
                     encoding="utf-8")
    code, captured = _freeze_probe(capsys, given, changed, given["root"] / "live")
    assert code == 2 and "backend/utils/entity_dicts.py" in captured.err
    assert not (given["root"] / "live").exists()
    code, captured = _freeze_probe(capsys, given, given["backend"], given["root"] / "live")
    assert code == 0, captured.err
