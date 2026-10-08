"""The contract directory of a build: manifest names the build, every file hashes to it."""

import json
import shutil
from pathlib import Path

import pytest

from serving import contracts

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
BUILD = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))
BUILD_ID = BUILD["build_id"]


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
    assert json.loads(found.files["event_registry.json"])["schema"] == "ragdata.event_registry.v2"


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


def test_an_unreadable_manifest_is_a_mismatch(directory):
    (directory / "manifest.json").write_text("{not json", encoding="utf-8")

    found = contracts.verify(directory, BUILD_ID)

    assert len(found.mismatches) == 1 and "manifest.json" in found.mismatches[0]


def test_resolve_dir_reroots_under_the_mount(tmp_path):
    assert contracts.resolve_dir("/mnt/store/contracts/b1", None) == Path("/mnt/store/contracts/b1")
    assert contracts.resolve_dir("/mnt/store/contracts/b1", str(tmp_path)) == tmp_path / "b1"
