"""The old backend's matches frozen per probe set (kg.k4_live): K4's build and G-ROUTE use
them for exactly their probe texts and fail closed when they are missing, are for other
texts or other backend sources, or changed."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import fake_backend
import mini_build
import mini_kg
from ragcommon import routing
from ragdata import reference
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg import k4_build, k4_live
from ragdata.legacy import route_live
from ragdata.stages.errors import StageError

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
PROBES = 3 + 14 + 6   # GT questions, verses, headings of the mini text layer


def _gt(path: Path, questions) -> Path:
    path.write_text(json.dumps({"questions": [{"question": q} for q in questions]},
                               ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def given(tmp_path):
    text, _ = mini_build.write_layers(tmp_path / "given")
    backend = fake_backend.write(tmp_path / "repo")
    lexicon = tmp_path / "routing_lexicon.legacy.json"
    lexicon.write_bytes(routing.render_lexicon(route_live.freeze(backend)))
    gt = _gt(tmp_path / "gt.json", mini_kg.GT_QUESTIONS)
    root = tmp_path / "route_live"
    live = fake_backend.freeze_live(backend, text.path, lexicon, gt, root)
    return {"text": text, "lexicon": lexicon, "gt": gt, "root": root, "live": live,
            "tmp": tmp_path}


def _build(given, gt=None, store="store"):
    probe = k4_live.stored_probe(given["root"], given["lexicon"])
    return k4_build.build_route(given["text"].path, given["tmp"] / store, probe,
                                given["lexicon"], gt or given["gt"], MINI_COUNTS)


def _gate(given, layer, gt=None):
    inputs = GateInputs(frozen_lexicon=given["lexicon"], ground_truth=gt or given["gt"],
                        route_live=given["root"])
    report = gate_layer(layer, "route", [given["text"].path], MINI_COUNTS, inputs=inputs)
    return report, next(g for g in report.gates if g.name == "G-ROUTE")


def _rewrite(live: Path, edit) -> None:
    """Edit the stored live.json and list its new sha256 (as a regenerated copy would)."""
    doc = json.loads(live.read_text(encoding="utf-8"))
    edit(doc)
    for path in (live, live.parent / reference.SUMS):
        os.chmod(path, 0o644)
    live.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (live.parent / reference.SUMS).write_bytes(
        reference.encode_sums({k4_live.LIVE: reference.sha256_file(live)}))


def test_matches_stored_for_these_probe_texts_are_used(given):
    result = _build(given)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    layer = result.layers["route"].path
    report, route = _gate(given, layer)
    assert report.passed and route.observed["probes"] == PROBES
    assert route.observed["mismatches"] == 0
    _rewrite(given["live"], lambda doc: doc["results"][0].update(persons=["哥尼流"]))
    report, route = _gate(given, layer)
    assert not report.passed and route.observed["mismatches"] == 1


def test_matches_stored_for_other_probe_texts_fail_closed(given):
    layer = _build(given).layers["route"].path
    other = _gt(given["tmp"] / "gt_other.json", (*mini_kg.GT_QUESTIONS, "哥尼流是誰？"))
    stored = given["live"].parent.name[:12]
    with pytest.raises(StageError, match=f"no frozen live matches .*stored: {stored}.*"
                                         "freeze probe"):
        _build(given, other, "other")
    report, route = _gate(given, layer, other)
    assert not report.passed and route.observed == "missing input"
    assert "freeze probe" in route.details[0]


@pytest.mark.parametrize("edit, message", [
    (lambda doc: doc["probes"].update(sha256="0" * 64), "records the probe set 0000"),
    (lambda doc: doc["results"].pop(), f"{PROBES - 1} results for {PROBES} probe texts"),
    (lambda doc: doc["frozen_from"].update({fake_backend.SOURCES[0]: "0" * 64}),
     "other backend sources"),
])
def test_a_file_that_does_not_match_its_probe_set_or_lexicon_fails_closed(given, edit, message):
    _rewrite(given["live"], edit)
    with pytest.raises(StageError, match=message):
        _build(given)


def test_no_stored_matches_fail_closed(given):
    layer = _build(given).layers["route"].path
    shutil.rmtree(given["root"])
    with pytest.raises(StageError, match="nothing stored under .*freeze probe"):
        _build(given, store="again")
    report, route = _gate(given, layer)
    assert not report.passed and route.observed == "missing input"


def test_a_changed_copy_fails_closed(given):
    os.chmod(given["live"], 0o644)
    given["live"].write_bytes(given["live"].read_bytes().replace(b"\n", b" \n"))
    with pytest.raises(StageError, match="reference copy changed.*freeze probe"):
        _build(given)


def test_a_stored_probe_set_is_never_rewritten(given):
    data, sha = given["live"].read_bytes(), given["live"].parent.name
    assert k4_live.write_live(given["root"], sha, data) == given["live"]
    with pytest.raises(StageError, match="never rewritten"):
        k4_live.write_live(given["root"], sha, data + b" ")
    assert reference.verified(given["live"].parent, [k4_live.LIVE])
