"""The contract directory of a build: manifest names the build, every file hashes to it."""

import json
import shutil
from pathlib import Path

import pytest

from serving import contracts

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
BUILD = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))
BUILD_ID = BUILD["build_id"]
R1_BUILD_ID = "b20261008_1bb6912e"  # fixtures/r1_contracts: the R1 mini build's contracts


@pytest.fixture
def directory(tmp_path):
    target = tmp_path / BUILD_ID
    shutil.copytree(FIXTURE / "contracts" / BUILD_ID, target)
    return target


def _edit_manifest(directory: Path, **changes) -> None:
    path = directory / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**doc, **changes}), encoding="utf-8")


def test_a_good_directory_verifies_and_yields_its_files(directory):
    found = contracts.verify(directory, BUILD_ID)

    assert found.mismatches == ()
    assert found.manifest["build_id"] == BUILD_ID
    assert set(contracts.REQUIRED) <= set(found.files)
    registry = json.loads(found.files["event_registry.json"])
    assert (registry["schema"], registry["variant"]) == ("ragdata.event_registry.v2", "R2")


def test_a_missing_directory_is_a_mismatch(tmp_path):
    found = contracts.verify(tmp_path / "nowhere", BUILD_ID)

    assert len(found.mismatches) == 1 and "manifest.json" in found.mismatches[0]
    assert found.files == {}


def test_a_manifest_of_another_build_is_a_mismatch(directory):
    _edit_manifest(directory, build_id="b20990101_deadbeef")

    found = contracts.verify(directory, BUILD_ID)

    assert any("b20990101_deadbeef" in m for m in found.mismatches)


def test_a_file_whose_sha_differs_is_a_mismatch(directory):
    path = directory / "routing_lexicon.json"
    path.write_bytes(path.read_bytes() + b" ")

    found = contracts.verify(directory, BUILD_ID)

    assert any("routing_lexicon.json" in m and "sha256" in m for m in found.mismatches)
    assert "routing_lexicon.json" not in found.files


def test_a_listed_file_that_is_missing_is_a_mismatch(directory):
    (directory / "event_registry.json").unlink()

    found = contracts.verify(directory, BUILD_ID)

    assert any("event_registry.json" in m for m in found.mismatches)


def test_a_required_file_the_manifest_does_not_list_is_a_mismatch(directory):
    doc = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    files = {k: v for k, v in doc["files"].items() if k != "encoder_fingerprint.json"}
    _edit_manifest(directory, files=files)

    found = contracts.verify(directory, BUILD_ID)

    assert any("encoder_fingerprint.json" in m for m in found.mismatches)


def test_an_r1_contract_directory_lacks_the_query_alias_table(tmp_path):
    r1 = FIXTURE.parent / "r1_contracts" / R1_BUILD_ID
    shutil.copytree(r1, tmp_path / R1_BUILD_ID)

    found = contracts.verify(tmp_path / R1_BUILD_ID, R1_BUILD_ID)

    assert found.mismatches == ("contracts: manifest does not list query_aliases.json",)


def test_an_unreadable_manifest_is_a_mismatch(directory):
    (directory / "manifest.json").write_text("{not json", encoding="utf-8")

    found = contracts.verify(directory, BUILD_ID)

    assert len(found.mismatches) == 1 and "manifest.json" in found.mismatches[0]


def test_resolve_dir_reroots_under_the_mount(tmp_path):
    assert contracts.resolve_dir("/mnt/store/contracts/b1", None) == Path("/mnt/store/contracts/b1")
    assert contracts.resolve_dir("/mnt/store/contracts/b1", str(tmp_path)) == tmp_path / "b1"


# ---------------------------------------------------------------- kg_meta.json
KG_META = {"schema_version": "ragdata.kg.v1", "nodes_sha256": "a" * 64, "edges_sha256": "b" * 64,
           "counts": {"nodes": {"Person": 2, "Verse": 3}, "edges": {"PARENT_OF": 1}}}


def _kg_bytes(**changes) -> bytes:
    return json.dumps({**KG_META, **changes}).encode("utf-8")


def test_kg_meta_parses_into_its_counts_shas_and_file_sha():
    data = _kg_bytes()
    meta = contracts.parse_kg_meta(data)
    assert meta.schema_version == "ragdata.kg.v1"
    assert meta.nodes == {"Person": 2, "Verse": 3} and meta.edges == {"PARENT_OF": 1}
    assert (meta.nodes_sha256, meta.edges_sha256) == ("a" * 64, "b" * 64)
    assert meta.sha256 == contracts.hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("data, message", [
    (b"not json", "kg_meta.json"),
    (b"[]", "object"),
    (_kg_bytes(schema_version="ragdata.kg.v0"), "schema_version"),
    (_kg_bytes(counts={"nodes": {"Person": 2}}), "counts"),
    (_kg_bytes(counts={"nodes": {"Person": "2"}, "edges": {}}), "counts"),
    (_kg_bytes(counts={"nodes": {"Person": True}, "edges": {}}), "counts"),
    (_kg_bytes(counts=None), "counts"),
    (_kg_bytes(nodes_sha256="short"), "nodes_sha256"),
    (_kg_bytes(edges_sha256=None), "edges_sha256"),
])
def test_a_kg_meta_that_does_not_parse_is_a_value_error(data, message):
    with pytest.raises(ValueError, match=message):
        contracts.parse_kg_meta(data)
