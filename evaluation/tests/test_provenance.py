"""Run provenance: build id and encoder from /health, run_meta.json, GT/build binding."""

import httpx
import pytest

from src import provenance as pv
from src.data_loader import load_gt
from src.models import SourceInfo
from src.slot_coverage import SlotCoverageError

BUILD = "b20261008_0000abcd"
FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}, "reranker": {"tokenizer_sha": "b"}}


# --- /health ---------------------------------------------------------------------

def test_a_backend_without_build_id_is_the_legacy_build_by_assumption():
    prov = pv.from_health({"status": "ok", "services": {}})

    assert prov.meta() == {"data_build_id": "legacy-20261004", "encoder_fingerprint": None}
    assert prov.reported is False


@pytest.mark.parametrize("build_id", [BUILD, "legacy-20261004"])
def test_build_id_and_encoder_come_from_health(build_id):
    prov = pv.from_health({"build_id": build_id, "encoder": FINGERPRINT})

    assert prov.meta() == {"data_build_id": build_id, "encoder_fingerprint": FINGERPRINT}
    assert prov.reported is True


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


def test_a_new_build_is_refused_against_gt_v1(tmp_path, write_contracts):
    with pytest.raises(pv.ProvenanceError, match="--gt v2"):
        pv.make_context(load_gt("v1"), pv.Provenance(BUILD), write_contracts(tmp_path))


def test_a_new_build_reads_its_contracts_from_the_store(tmp_path, monkeypatch, write_contracts):
    write_contracts(tmp_path / "contracts" / BUILD)
    monkeypatch.setattr(pv.settings, "rag_store", tmp_path)

    ctx = pv.make_context(load_gt("v2"), pv.Provenance(BUILD))

    assert ctx.ruler.build_id == BUILD


def test_a_contracts_dir_names_the_build_only_when_health_names_none(tmp_path, write_contracts):
    ctx = pv.make_context(load_gt("v2"), pv.from_health({"status": "ok"}),
                          write_contracts(tmp_path))

    assert ctx.meta()["data_build_id"] == BUILD and ctx.ruler.build_id == BUILD


def _legacy_run_meta(directory):
    pv.write_run_meta(directory, pv.Provenance("legacy-20261004"))
    return directory


@pytest.mark.parametrize("legacy", [
    lambda d: pv.from_health({"build_id": "legacy-20261004"}),
    lambda d: pv.read_run_meta(_legacy_run_meta(d / "run")),
    lambda d: pv.read_run_meta(d),
], ids=["health_handshake", "run_meta_legacy", "checkpoint_before_run_meta"])
def test_a_build_known_to_be_legacy_is_not_relabelled_by_a_contracts_dir(
        tmp_path, legacy, write_contracts):
    with pytest.raises(pv.ProvenanceError, match="legacy-20261004.*holds"):
        pv.make_context(load_gt("v2"), legacy(tmp_path), write_contracts(tmp_path / "c"))


def test_legacy_answers_under_a_contracts_dir_label_do_not_score(tmp_path, write_contracts):
    """BACKEND_URL left on the legacy prod backend while --contracts-dir names a build."""
    ctx = pv.make_context(load_gt("v2"), pv.from_health({"status": "ok"}),
                          write_contracts(tmp_path))
    item = ctx.gt.by_id()["VERSE_LOOKUP_001"]
    legacy = SourceInfo(id="jhn:3:16", book="約翰福音", chapter=3, verse_range="16")

    with pytest.raises(SlotCoverageError, match="legacy source"):
        ctx.ruler.verse_metrics(item, [legacy])


def test_a_contracts_dir_of_another_build_is_refused(tmp_path, write_contracts):
    with pytest.raises(pv.ProvenanceError, match="holds"):
        pv.make_context(load_gt("v2"), pv.Provenance("b20261009_ffffffff"),
                        write_contracts(tmp_path))


def test_a_contracts_dir_without_manifest_is_refused(tmp_path):
    with pytest.raises(pv.ProvenanceError, match="cannot read"):
        pv.make_context(load_gt("v2"), pv.from_health({}), tmp_path)
