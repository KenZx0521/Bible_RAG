"""Content-addressed layer store: versions, atomic publish, refusal to overwrite, integrity."""

from __future__ import annotations

import json
import os
import re

import pytest

from ragdata import store
from ragdata.store import IntegrityError, LayerExistsError, StoreError

FILES = {
    "books.jsonl": store.encode_jsonl([{"book_id": "gen", "name": "創世記"}]),
    "chapters.jsonl": store.encode_jsonl([{"chapter_key": "gen.1"}, {"chapter_key": "gen.2"}]),
}


def test_written_layer_reads_back_with_its_rows(tmp_path):
    stored = store.write_layer(tmp_path, "text", FILES)
    assert re.fullmatch(r"text@[0-9a-f]{12}", stored.version)
    assert stored.path == tmp_path / "text" / stored.version
    loaded = store.read_layer(stored.path)
    assert (loaded.layer, loaded.version) == ("text", stored.version)
    assert loaded.rows["books.jsonl"] == ({"book_id": "gen", "name": "創世記"},)
    assert len(loaded.rows["chapters.jsonl"]) == 2


def test_version_depends_only_on_file_names_and_bytes(tmp_path):
    a = store.write_layer(tmp_path / "a", "text", FILES)
    b = store.write_layer(tmp_path / "b", "text", dict(reversed(FILES.items())))
    changed = store.write_layer(tmp_path / "c", "text", {**FILES, "books.jsonl": b"{}\n"})
    renamed = store.write_layer(tmp_path / "d", "text", {
        "verse_units.jsonl" if k == "books.jsonl" else k: v for k, v in FILES.items()})
    assert a.version == b.version
    assert len({a.version, changed.version, renamed.version}) == 3


def test_existing_version_is_never_overwritten(tmp_path):
    first = store.write_layer(tmp_path, "text", FILES)
    before = (first.path / "books.jsonl").read_bytes()
    with pytest.raises(LayerExistsError):
        store.write_layer(tmp_path, "text", FILES)
    assert (first.path / "books.jsonl").read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "text").iterdir()) == [first.version]


def test_failed_publish_leaves_no_version_and_no_temp_dir(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(OSError):
        store.write_layer(tmp_path, "text", FILES)
    assert list((tmp_path / "text").iterdir()) == []


def test_manifest_records_file_shas_and_dependencies(tmp_path):
    dep = "text@0123456789ab"
    stored = store.write_layer(tmp_path, "struct", FILES, depends_on={"text": dep})
    manifest = json.loads((stored.path / "layer_manifest.json").read_text())
    assert manifest["layer_version"] == stored.version
    assert set(manifest["files"]) == set(FILES)
    assert store.read_layer(stored.path).depends_on == {"text": dep}


@pytest.mark.parametrize("depends_on", [
    {"text": "struct@0123456789ab"}, {"text": "text@xyz"}, {"nope": "text@0123456789ab"}])
def test_bad_dependencies_are_rejected(tmp_path, depends_on):
    with pytest.raises(StoreError):
        store.write_layer(tmp_path, "struct", FILES, depends_on=depends_on)


@pytest.mark.parametrize("name", [
    "../escape.jsonl", "sub/books.jsonl", ".hidden.jsonl", "layer_manifest.json", "Books.JSONL"])
def test_unsafe_or_reserved_file_names_are_rejected(tmp_path, name):
    with pytest.raises(StoreError):
        store.write_layer(tmp_path, "text", {name: b"{}\n"})


def test_unknown_layer_and_empty_layer_are_rejected(tmp_path):
    with pytest.raises(StoreError):
        store.write_layer(tmp_path, "verses", FILES)
    with pytest.raises(StoreError):
        store.write_layer(tmp_path, "text", {})


def _tamper(tmp_path, action):
    stored = store.write_layer(tmp_path, "text", FILES)
    action(stored.path)
    return stored.path


@pytest.mark.parametrize("action", [
    lambda p: (p / "books.jsonl").write_bytes(b'{"book_id": "exo"}\n'),
    lambda p: (p / "books.jsonl").unlink(),
    lambda p: (p / "extra.jsonl").write_bytes(b"{}\n"),
    lambda p: (p / "layer_manifest.json").unlink(),
    lambda p: os.rename(p, p.with_name("text@ffffffffffff")),
], ids=["edited", "deleted", "extra", "no-manifest", "renamed-dir"])
def test_read_rejects_a_tampered_layer(tmp_path, action):
    path = _tamper(tmp_path, action)
    target = path if path.exists() else path.with_name("text@ffffffffffff")
    with pytest.raises(IntegrityError):
        store.read_layer(target)


def test_jsonl_encoding_is_canonical():
    assert store.encode_jsonl([{"b": 1, "a": "上帝"}]) == '{"a":"上帝","b":1}\n'.encode()
    assert store.encode_jsonl([]) == b""


@pytest.mark.parametrize("data", [b"[1]\n", b"{bad\n", b'{"a":1}\n\n{"a":2}\n', b'{"a":1}'])
def test_jsonl_decoding_is_strict(data):
    with pytest.raises(StoreError):
        store.decode_jsonl(data, "x.jsonl")


def test_nan_is_not_written_as_json():
    with pytest.raises(StoreError):
        store.encode_jsonl([{"x": float("nan")}])


def test_published_version_is_readable_by_other_users(tmp_path):
    stored = store.write_layer(tmp_path, "text", FILES)
    assert stored.path.stat().st_mode & 0o755 == 0o755
