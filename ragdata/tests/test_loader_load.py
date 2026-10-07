"""S13: the loader writes a release to PG, Qdrant and its contract directory, or nothing."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from qdrant_client import QdrantClient

import mini_loaded
import mini_release
from fake_pg import FakePg
from ragcommon import ids
from ragdata.loader import load as loader
from ragdata.loader.contracts_emit import ContractsExistError, read_contracts, write_contracts
from ragdata.loader.qdrant import QdrantDb
from ragdata.release.contracts import CONTRACT_FILES
from ragdata.store import StoredLayer, attach, encode_jsonl, vectors

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("load_mini"))


@pytest.fixture()
def loaded(tmp_path, mini):
    return mini_loaded.load(tmp_path, mini)


def test_targets_are_named_after_the_build():
    t = loader.targets("b20261008_0123abcd", mini_release.Path("/c"))
    assert (t.schema, t.collection) == ("bb20261008_0123abcd", "passages__b20261008_0123abcd")
    assert str(t.contracts_dir) == "/c/b20261008_0123abcd"
    assert loader.targets("legacy-20261004").schema == "blegacy20261004"


def test_the_release_lands_in_all_three_places(loaded):
    t, release = loaded.targets, loaded.release
    rows = loaded.pg.schemas[t.schema]
    assert len(rows["verse_units"]) == 14 and len(rows["embedding_records"]) == 22
    assert rows["build_info"][0]["build_id"] == release.build_id
    assert loaded.report["points"] == loaded.qdrant.count(t.collection) == 22
    built = loaded.pg.build_row(release.build_id)
    assert (built["pg_schema"], built["qdrant_collection"]) == (t.schema, t.collection)
    files = read_contracts(t.contracts_dir)
    assert set(files) == {*CONTRACT_FILES, "manifest.json"}
    manifest = json.loads(files["manifest.json"])
    assert manifest["build_id"] == release.build_id and manifest["points"] == 22
    assert manifest["files"] == dict(release.doc["contracts"])


def test_points_carry_the_payload_and_the_build_id(loaded):
    points = {p.payload["record_id"]: p for p in loaded.qdrant.points(loaded.targets.collection)}
    point = points["vs:act.9.3"]
    assert point.payload["build_id"] == loaded.release.build_id
    assert point.payload["split_passage_ids"] == ["ps:act.9.1", "ps:act.9.3b"]
    assert point.id == ids.point_id("vs:act.9.3")


def test_a_fresh_load_verifies_green(loaded):
    report = loaded.verify()
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    names = [g.name for g in report.gates]
    assert names == ["G-SCHEMA.pg", *(f"G-PROJ.C{i}" for i in range(1, 7))]


@pytest.mark.parametrize("taken", ["schema", "collection", "contracts", "serving", "registered"])
def test_a_taken_target_is_refused_before_anything_is_written(tmp_path, mini, taken):
    release = mini_loaded.assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    t = loader.targets(release.build_id, tmp_path / "contracts")
    if taken == "schema":
        pg.schemas[t.schema] = {}
    elif taken == "collection":
        qdrant.create(t.collection, 8)
    elif taken == "contracts":
        write_contracts(t.contracts_dir, {"x.json": b"{}"})
    elif taken == "serving":
        pg.serving_rows["prod"] = release.build_id
    else:
        pg.builds[release.build_id] = {"build_id": release.build_id}
    with pytest.raises(loader.LoadError, match="refusing"):
        loader.load(release, pg, qdrant, tmp_path / "contracts")
    assert pg.applied == 0


def test_loading_the_same_release_twice_is_refused(loaded):
    with pytest.raises(loader.LoadError, match="registered in rag_meta.builds"):
        loader.load(loaded.release, loaded.pg, loaded.qdrant, loaded.contracts)


def test_a_failed_pg_copy_writes_nothing_anywhere(tmp_path, mini):
    release = mini_loaded.assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    pg.fail_on = "embedding_records"
    with pytest.raises(loader.LoadError, match="PG rolled back") as caught:
        loader.load(release, pg, qdrant, tmp_path / "contracts")
    t = loader.targets(release.build_id, tmp_path / "contracts")
    assert not pg.schemas and not qdrant.exists(t.collection) and not t.contracts_dir.exists()
    assert "left behind" not in str(caught.value)


def test_a_failure_after_qdrant_names_what_was_left_behind(tmp_path, mini, monkeypatch):
    release = mini_loaded.assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    monkeypatch.setattr(loader, "write_contracts",
                        lambda d, f: (_ for _ in ()).throw(ContractsExistError("raced")))
    with pytest.raises(loader.LoadError, match="left behind.*passages__") as caught:
        loader.load(release, pg, qdrant, tmp_path / "contracts")
    assert not pg.schemas and "raced" in str(caught.value)


def test_a_short_collection_fails_the_load(tmp_path, mini, monkeypatch):
    release = mini_loaded.assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    monkeypatch.setattr(qdrant, "count", lambda name: 21)
    with pytest.raises(loader.LoadError, match="21 points, expected 22"):
        loader.load(release, pg, qdrant, tmp_path / "contracts")
    assert not pg.schemas


def _with_vectors(tmp_path, mini, change):
    """The mini release whose emb attachment is replaced by ``change(found)``'s files."""
    release = mini_loaded.assembled(mini)
    emb = release.layers["emb"]
    _, contents = attach.read_attachment(emb.path, vectors.NAME)
    found = vectors.decode_vectors(contents)
    files = change(found)
    copy = tmp_path / "copy" / "emb" / emb.version
    copy.parent.mkdir(parents=True)
    shutil.copytree(emb.path, copy)
    stored = type(release.layers["emb"])(emb.layer, emb.version, copy, emb.depends_on,
                                         emb.file_shas, emb.rows)
    attach.write_attachment(StoredLayer("emb", emb.version, copy), "vectors", files, {})
    layers = {**release.layers, "emb": stored}
    return type(release)(release.build_id, release.release_sha, release.doc, release.data,
                         layers, release.contracts)


def test_vectors_that_do_not_line_up_with_the_records_are_refused(tmp_path, mini):
    def swap(found):
        rows = [(r["record_id"], r["text_sha"]) for r in found.index]
        rows[0], rows[1] = rows[1], rows[0]
        return vectors.encode_vectors(rows, np.array(found.matrix), found.probes)
    release = _with_vectors(tmp_path, mini, swap)
    with pytest.raises(loader.LoadError, match="row 0"):
        loader.load(release, FakePg(), QdrantDb(QdrantClient(location=":memory:")), tmp_path)


def test_a_row_that_does_not_hash_to_its_vec_sha_is_refused(tmp_path, mini):
    def drift(found):
        files = vectors.encode_vectors([(r["record_id"], r["text_sha"]) for r in found.index],
                                       np.array(found.matrix), found.probes)
        index = [dict(r) for r in found.index]
        index[3]["vec_sha"] = "0" * 64
        return {**files, vectors.INDEX: encode_jsonl(index)}
    release = _with_vectors(tmp_path, mini, drift)
    with pytest.raises(loader.LoadError, match="vec_sha"):
        loader.load(release, FakePg(), QdrantDb(QdrantClient(location=":memory:")), tmp_path)


def test_vectors_narrower_than_the_fingerprint_are_refused(tmp_path, mini):
    def narrow(found):
        rows = [(r["record_id"], r["text_sha"]) for r in found.index]
        return vectors.encode_vectors(rows, np.array(found.matrix)[:, :4], found.probes)
    release = _with_vectors(tmp_path, mini, narrow)
    with pytest.raises(loader.LoadError, match="4 wide, the encoder fingerprint says 8"):
        loader.load(release, FakePg(), QdrantDb(QdrantClient(location=":memory:")), tmp_path)


def test_records_that_fail_their_contract_are_not_loaded(tmp_path, mini):
    release = mini_loaded.assembled(mini)
    text = release.layers["text"]
    units = [dict(r) for r in text.rows["verse_units.jsonl"]]
    units[0]["text_sha256"] = "0" * 64
    broken = type(text)(text.layer, text.version, text.path, text.depends_on, text.file_shas,
                        {**text.rows, "verse_units.jsonl": tuple(units)})
    release = type(release)(release.build_id, release.release_sha, release.doc, release.data,
                            {**release.layers, "text": broken}, release.contracts)
    with pytest.raises(loader.LoadError, match="G-SCHEMA"):
        loader.load(release, FakePg(), QdrantDb(QdrantClient(location=":memory:")), tmp_path)


def test_contract_directories_are_written_once(tmp_path):
    target = tmp_path / "b1"
    write_contracts(target, {"a.json": b"1\n"})
    assert read_contracts(target) == {"a.json": b"1\n"}
    assert read_contracts(tmp_path / "none") is None
    with pytest.raises(ContractsExistError):
        write_contracts(target, {"a.json": b"2\n"})
    assert (target / "a.json").read_bytes() == b"1\n"
