"""Run provenance: build id and encoder from /health, run_meta.json, GT/build binding."""

import hashlib
import json

import httpx
import pytest

from src import provenance as pv
from src.data_loader import load_gt

BUILD = "b20261008_0000abcd"
FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}, "reranker": {"tokenizer_sha": "b"}}


def _contracts(root, build_id=BUILD):
    root.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"schema": "ragdata.contract.verse_index.v1",
                       "slots": [{"slot_key": "jhn.3.16", "unit_key": "jhn.3.16"}]}).encode()
    (root / "verse_index.json").write_bytes(data)
    (root / "manifest.json").write_text(json.dumps(
        {"build_id": build_id, "files": {"verse_index.json": hashlib.sha256(data).hexdigest()}}))
    return root


# --- /health ---------------------------------------------------------------------

def test_a_backend_without_build_id_is_the_legacy_build():
    prov = pv.from_health({"status": "ok", "services": {}})

    assert prov.meta() == {"data_build_id": "legacy-20261004", "encoder_fingerprint": None}


def test_build_id_and_encoder_come_from_health():
    prov = pv.from_health({"build_id": BUILD, "encoder": FINGERPRINT})

    assert prov.meta() == {"data_build_id": BUILD, "encoder_fingerprint": FINGERPRINT}


def test_an_encoder_not_yet_initialised_is_null():
    assert pv.from_health({"encoder": {"embedder": None, "reranker": None}}).encoder_fingerprint is None


def test_a_malformed_build_id_is_refused():
    with pytest.raises(pv.ProvenanceError, match="build id"):
        pv.from_health({"build_id": "b2026_bad"})


def test_fetch_health_reads_the_endpoint(monkeypatch):
    seen = []

    def fake_get(url, timeout):
        seen.append(url)
        return httpx.Response(200, json={"build_id": BUILD}, request=httpx.Request("GET", url))

    monkeypatch.setattr(pv.httpx, "get", fake_get)

    assert pv.fetch_health("http://x:8000") == {"build_id": BUILD}
    assert seen == ["http://x:8000/api/v1/health"]


# --- run_meta.json -------------------------------------------------------------------

def test_run_meta_round_trips(tmp_path):
    pv.write_run_meta(tmp_path / "out", pv.Provenance(BUILD, FINGERPRINT))

    assert pv.read_run_meta(tmp_path / "out").meta() == {"data_build_id": BUILD,
                                                         "encoder_fingerprint": FINGERPRINT}


def test_a_checkpoint_without_run_meta_came_from_the_legacy_build(tmp_path):
    assert pv.read_run_meta(tmp_path).data_build_id == "legacy-20261004"


def test_an_unreadable_run_meta_is_refused(tmp_path):
    (tmp_path / pv.RUN_META).write_text("{")
    with pytest.raises(pv.ProvenanceError, match="cannot read"):
        pv.read_run_meta(tmp_path)


# --- binding GT, build and ruler ------------------------------------------------------

def test_legacy_with_v1_has_no_ruler_and_records_everything():
    ctx = pv.make_context(load_gt("v1"), pv.Provenance("legacy-20261004"))

    assert ctx.ruler is None
    assert list(ctx.meta()) == ["data_build_id", "gt_version", "gt_sha", "encoder_fingerprint"]
    assert ctx.meta()["gt_version"] == "v1"


def test_legacy_with_v2_scores_on_the_slot_universe():
    ctx = pv.make_context(load_gt("v2"), pv.Provenance("legacy-20261004"))

    assert ctx.ruler.build_id == "legacy-20261004"
    assert ctx.meta()["gt_sha"] == load_gt("v2").sha256


def test_a_new_build_is_refused_against_gt_v1(tmp_path):
    with pytest.raises(pv.ProvenanceError, match="--gt v2"):
        pv.make_context(load_gt("v1"), pv.Provenance(BUILD), _contracts(tmp_path))


def test_a_new_build_reads_its_contracts_from_the_store(tmp_path, monkeypatch):
    _contracts(tmp_path / "contracts" / BUILD)
    monkeypatch.setattr(pv.settings, "rag_store", tmp_path)

    ctx = pv.make_context(load_gt("v2"), pv.Provenance(BUILD))

    assert ctx.ruler.build_id == BUILD


def test_a_contracts_dir_names_the_build_a_legacy_health_report_does_not(tmp_path):
    ctx = pv.make_context(load_gt("v2"), pv.Provenance("legacy-20261004"), _contracts(tmp_path))

    assert ctx.meta()["data_build_id"] == BUILD and ctx.ruler.build_id == BUILD


def test_a_contracts_dir_of_another_build_is_refused(tmp_path):
    with pytest.raises(pv.ProvenanceError, match="holds"):
        pv.make_context(load_gt("v2"), pv.Provenance("b20261009_ffffffff"), _contracts(tmp_path))


def test_a_contracts_dir_without_manifest_is_refused(tmp_path):
    with pytest.raises(pv.ProvenanceError, match="cannot read"):
        pv.make_context(load_gt("v2"), pv.Provenance("legacy-20261004"), tmp_path)
