"""The regnal layer (Kay's P5 exception, 2026-10-19): its build reproduces the audited
experiment-A layer, G-REGNAL pins it, and a release may carry it as an optional layer
without changing the bytes of a release that does not."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ragcommon import regnal
from ragdata.gates.regnal import (
    check_regnal, expectation_doc, load_regnal_expect, report_doc,
)
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg.regnal_build import build_regnal, encode_layer, regnal_files
from ragdata.release import assemble as rel
from ragdata.release.gating import default_checks
from ragdata.store import read_layer

STORE = Path("/mnt/ollama-data/bible_rag_store")
TEXT = STORE / "layers/text/text@247eafe44b02"
R2 = STORE / "releases/b20261008_e05d3e55.json"
AUDITED = STORE / "reports/kg_cards_20261018/A/layer_auto.json"
needs_text = pytest.mark.skipif(not TEXT.is_dir(), reason=f"{TEXT.name} not in the store")
needs_r2 = pytest.mark.skipif(not R2.is_file(), reason=f"{R2.name} not in the store")


@pytest.fixture(scope="module")
def text():
    return read_layer(TEXT)


@pytest.fixture(scope="module")
def files(text):
    return regnal_files(text)


@pytest.fixture(scope="module")
def expect():
    return load_regnal_expect()


def _gate(data: bytes, expect, text_version="text@247eafe44b02", report=None):
    doc = json.loads(data)
    report = report if report is not None else report_doc(doc, text_version, hashlib.sha256(data).hexdigest())
    return check_regnal(data, report, {"text": text_version}, expect)


@needs_text
def test_the_build_on_the_served_text_is_the_audited_layer_byte_for_byte(files, expect):
    data = files["regnal_layer.json"]
    assert hashlib.sha256(data).hexdigest() == expect["layer_sha256"]
    if AUDITED.is_file():
        assert data == AUDITED.read_bytes()


@needs_text
def test_the_chains_are_the_divided_kingdoms_from_jeroboam_and_solomon(files, expect):
    chains = regnal.load(json.loads(files["regnal_layer.json"])).chain_names()
    assert chains == expect["chains"]
    assert chains["I"][0] == "耶羅波安" and chains["I"][-1] == "何細亞" and len(chains["I"]) == 19
    assert chains["J"][:2] == ["所羅門", "羅波安"] and chains["J"][-1] == "西底家"


@needs_text
def test_g_regnal_passes_the_audited_layer(files, expect):
    gate = check_regnal(files["regnal_layer.json"], json.loads(files["regnal_report.json"]),
                        {"text": "text@247eafe44b02"}, expect)
    assert gate.passed, gate.details
    assert gate.observed["chains"] == {"I": 19, "J": 20} and gate.observed["conflicts"] == 7


@needs_text
def test_g_regnal_refuses_another_text_layer(files, expect):
    gate = _gate(files["regnal_layer.json"], expect, text_version="text@0123456789ab")
    assert not gate.passed and "audit the layer of this text again" in gate.details[0]


def _mutated(files, change) -> bytes:
    doc = json.loads(files["regnal_layer.json"])
    change(doc)
    return encode_layer(doc)


@needs_text
@pytest.mark.parametrize("change, needle", [
    (lambda d: d["nodes"][3].update(name="某王"), "sha256"),
    (lambda d: d.update(union_classes=[["A01", "A02"]]), "union_classes"),
    (lambda d: d["edges"].append(["A01", "Z99", "son", None]), "names no node"),
    (lambda d: d["conflicts"].pop(), "field conflicts"),
])
def test_g_regnal_turns_red_on_any_change_to_the_layer(files, expect, change, needle):
    gate = _gate(_mutated(files, change), expect)
    assert not gate.passed and any(needle in d for d in gate.details), gate.details


@needs_text
def test_g_regnal_wants_the_chains_and_report_it_was_given(files, expect):
    wrong = copy.deepcopy(dict(expect))
    wrong["chains"] = {**wrong["chains"], "J": wrong["chains"]["J"][1:]}
    assert not check_regnal(files["regnal_layer.json"], json.loads(files["regnal_report.json"]),
                            {"text": "text@247eafe44b02"}, wrong).passed
    gate = check_regnal(files["regnal_layer.json"], None, {"text": "text@247eafe44b02"}, expect)
    assert not gate.passed and any("regnal_report.json" in d for d in gate.details)
    assert not check_regnal(None, None, {"text": "text@247eafe44b02"}, expect).passed


def test_the_expectation_of_a_text_without_regnal_formulas_is_empty_chains():
    doc = {"policy": "occ", "fn_rule": "slot", "nodes": [], "edges": [], "fallback_edges": [],
           "syncs": [], "conflicts": [], "log": [], "occ_alias": [], "union_classes": None}
    data = encode_layer(doc)
    want = expectation_doc(doc, "text@0123456789ab", hashlib.sha256(data).hexdigest())
    assert want["chains"] == {"I": [], "J": []}
    assert _gate(data, want, text_version="text@0123456789ab").passed


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    if not TEXT.is_dir():
        pytest.skip(f"{TEXT.name} not in the store")
    root = tmp_path_factory.mktemp("regnal_store")
    (root / "text").mkdir()
    (root / "text" / TEXT.name).symlink_to(TEXT)
    result = build_regnal(TEXT, root)
    assert result.passed, [g.to_json() for g in result.gates]
    return root, result.layers["regnal"]


def test_build_stores_the_layer_and_the_stored_layer_passes_its_gates(stored):
    root, layer = stored
    data = read_layer(layer.path)
    assert data.depends_on == {"text": "text@247eafe44b02"}
    assert set(data.file_shas) >= {"regnal_layer.json", "regnal_report.json"}
    report = gate_layer(layer.path, "regnal", [TEXT], inputs=GateInputs())
    assert report.passed, report.to_json()
    again = build_regnal(TEXT, root)
    assert again.layers["regnal"].version == layer.version


@needs_r2
def test_a_release_without_the_optional_layer_keeps_its_bytes():
    again = rel.read_release(R2, STORE / "layers", default_checks())
    assert again.build_id == "b20261008_e05d3e55"
    assert "regnal" not in again.doc["layers"] and again.doc["contract_version"] == "1.1.0"


@needs_r2
def test_a_release_with_the_regnal_layer_carries_its_contract_file(stored, tmp_path):
    root, layer = stored
    r2 = json.loads(R2.read_text(encoding="utf-8"))
    for name, version in r2["layers"].items():
        if version and name != "text":
            (root / name).mkdir(exist_ok=True)
            link = root / name / version
            if not link.exists():
                link.symlink_to(STORE / "layers" / name / version)
    vectors = STORE / "layers/emb" / f"{r2['layers']['emb']}.vectors"
    if vectors.exists() and not (root / "emb" / vectors.name).exists():
        (root / "emb" / vectors.name).symlink_to(vectors)
    versions = [v for k, v in r2["layers"].items() if v and k != "src"] + [layer.version]
    release = rel.assemble(root, versions, r2["build_date"], default_checks())
    assert release.doc["contract_version"] == "1.2.0"
    assert release.doc["layers"]["regnal"] == layer.version
    assert release.doc["contracts"]["regnal_layer.json"] == load_regnal_expect()["layer_sha256"]
    assert {k: v for k, v in release.doc["contracts"].items() if k != "regnal_layer.json"} \
        == r2["contracts"]
    assert {k: v for k, v in release.doc["layer_digests"].items() if k != "regnal"} \
        == r2["layer_digests"]
    assert release.build_id != r2["build_id"]
