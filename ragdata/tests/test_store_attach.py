"""Attachments: files kept beside a layer version without entering it (the emb vectors)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ragdata import store
from ragdata.store import IntegrityError, LayerExistsError, StoreError, attach, vectors

LAYER_FILES = {"books.jsonl": store.encode_jsonl([{"book_id": "gen"}])}
FILES = {"vectors.npy": b"\x93NUMPY fake", "vector_index.jsonl": b"{}\n"}
META = {"device": "cuda", "batch_size": 32}


def _layer(tmp_path):
    return store.write_layer(tmp_path, "text", LAYER_FILES)


def test_an_attachment_reads_back_beside_its_layer_version(tmp_path):
    layer = _layer(tmp_path)
    written = attach.write_attachment(layer, "vectors", FILES, META)
    assert written.path == tmp_path / "text" / f"{layer.version}.vectors"
    found, contents = attach.read_attachment(layer.path, "vectors")
    assert (found.layer_version, found.meta, contents) == (layer.version, META, FILES)
    assert store.read_layer(layer.path).version == layer.version  # the layer is untouched


def test_an_attachment_is_never_overwritten_but_may_be_reused(tmp_path):
    layer = _layer(tmp_path)
    first = attach.write_attachment(layer, "vectors", FILES, META)
    with pytest.raises(LayerExistsError):
        attach.write_attachment(layer, "vectors", {**FILES, "vectors.npy": b"other"}, META)
    assert attach.write_attachment(layer, "vectors", {"x.bin": b"?"}, {}, exist_ok=True) == first
    assert attach.read_attachment(layer.path, "vectors")[1] == FILES


@pytest.mark.parametrize("tamper", ["file", "extra", "version"])
def test_a_tampered_attachment_is_refused(tmp_path, tamper):
    layer = _layer(tmp_path)
    path = attach.write_attachment(layer, "vectors", FILES, META).path
    if tamper == "file":
        (path / "vectors.npy").write_bytes(b"changed")
    elif tamper == "extra":
        (path / "notes.txt").write_text("hi")
    else:
        manifest = json.loads((path / attach.MANIFEST).read_text())
        (path / attach.MANIFEST).write_text(json.dumps({**manifest,
                                                       "layer_version": "text@000000000000"}))
    with pytest.raises(IntegrityError):
        attach.read_attachment(layer.path, "vectors")


def test_a_missing_attachment_or_layer_is_a_store_error(tmp_path):
    layer = _layer(tmp_path)
    with pytest.raises(StoreError, match="no vectors attachment"):
        attach.read_attachment(layer.path, "vectors")
    gone = store.StoredLayer("text", "text@0123456789ab", tmp_path / "text" / "text@0123456789ab")
    with pytest.raises(StoreError):
        attach.write_attachment(gone, "vectors", FILES, META)


@pytest.mark.parametrize("name, files", [("Vectors", FILES), ("vectors", {}),
                                         ("vectors", {"../x.npy": b""})])
def test_bad_names_or_no_files_are_refused(tmp_path, name, files):
    with pytest.raises(StoreError):
        attach.write_attachment(_layer(tmp_path), name, files, META)


def test_vector_files_round_trip_with_a_row_hash_per_record():
    matrix = np.arange(12, dtype=np.float32).reshape(3, 4) / 10
    rows = [("vs:gen.1.1", "a" * 64), ("vs:gen.1.2", "b" * 64), ("ps:gen.1.1", "c" * 64)]
    files = vectors.encode_vectors(rows, matrix)
    loaded, index = vectors.decode_vectors(files)
    assert loaded.dtype == np.dtype("<f4") and np.array_equal(loaded, matrix)
    assert [(r["record_id"], r["row"], r["text_sha"]) for r in index] == [
        (rid, i, sha) for i, (rid, sha) in enumerate(rows)]
    assert [r["vec_sha"] for r in index] == [vectors.row_sha(v) for v in matrix]
    assert vectors.encode_vectors(rows, matrix.astype(np.float64)) == files


@pytest.mark.parametrize("matrix", [np.zeros((2, 4), np.float32), np.zeros(3, np.float32)])
def test_vectors_must_be_one_row_per_record(matrix):
    with pytest.raises(StoreError):
        vectors.encode_vectors([("vs:gen.1.1", "a" * 64)] * 3, matrix)


def test_decoding_refuses_pickles_and_other_dtypes():
    with pytest.raises(StoreError):
        vectors.decode_vectors({"vectors.npy": b"not npy", "vector_index.jsonl": b""})
    files = vectors.encode_vectors([("vs:gen.1.1", "a" * 64)], np.zeros((1, 2), np.float32))
    import io
    buf = io.BytesIO()
    np.save(buf, np.zeros((1, 2), np.int64))
    with pytest.raises(StoreError, match="float32"):
        vectors.decode_vectors({**files, "vectors.npy": buf.getvalue()})
