"""``build_emb``: S6 + S7 over stored struct and text layers, their gates, the store, G-DET."""

from __future__ import annotations

import json

import numpy as np
import pytest

import fake_encoder
import mini_build
import mini_emb
from ragcommon import encoder as pins
from ragdata import store
from ragdata.gates import check_det
from ragdata.stages.errors import StageError
from ragdata.store import attach, vectors


def test_build_stores_the_emb_layer_and_its_vectors(tmp_path):
    text, struct, result = mini_emb.build(tmp_path)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-COUNT", "G-EMB", "G-ENC"]
    built = store.read_layer(result.layers["emb"].path)
    assert built.depends_on == {"struct": struct.version, "text": text.version}
    assert set(built.file_shas) == {"embedding_records.jsonl", "emb_report.json",
                                    "encoder_fingerprint.json", "depends_on.json"}
    rows = built.rows["embedding_records.jsonl"]
    assert tuple(r["record_id"] for r in rows) == mini_build.EMB_RECORD_IDS
    report = json.loads((built.path / "emb_report.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"verse": 14, "passage": 6, "chunk": 2, "total": 22}
    assert report["struct_layer"] == struct.version and report["template"]["template_id"] == "v1c"
    found, files = attach.read_attachment(built.path, vectors.NAME)
    stored = vectors.decode_vectors(files)
    assert np.array_equal(stored.matrix, fake_encoder.embed([r["text"] for r in rows]))
    assert [r["record_id"] for r in stored.index] == list(mini_build.EMB_RECORD_IDS)
    assert np.allclose(stored.probes, fake_encoder.embed(pins.BGE_M3.probes), atol=1e-6)
    assert found.meta["runtime"]["stand_in"] is True
    assert result.to_json()["attachments"]["emb"]["path"] == str(found.path)


def _drift(scale, probes=False):
    """The stand-in encoder with its corpus rows (and, if asked, its probe rows) scaled."""
    def embed(texts):
        stable = tuple(texts) == pins.BGE_M3.probes and not probes
        return fake_encoder.embed(texts) * np.float32(1 if stable else scale)
    return fake_encoder.make(embed_fn=embed)


def _moved():
    """The stand-in encoder with its probes in place but every corpus row elsewhere."""
    def embed(texts):
        stable = tuple(texts) == pins.BGE_M3.probes
        return fake_encoder.embed(texts if stable else [t + "!" for t in texts])
    return fake_encoder.make(embed_fn=embed)


def test_the_version_ignores_vectors_and_two_builds_agree(tmp_path):
    _, _, first = mini_emb.build(tmp_path, "a")
    _, _, second = mini_emb.build(tmp_path, "b", given=_same_given(tmp_path),
                                  encoder=_drift(1 + 1e-7))
    a, b = first.layers["emb"], second.layers["emb"]
    assert a.version == b.version
    det = check_det(a.path, b.path)
    assert det.passed, det.details
    assert det.observed["vectors"]["min_cos"] > 0.99999


def test_probe_vectors_that_differ_in_their_last_digits_keep_the_version(tmp_path):
    _, _, first = mini_emb.build(tmp_path, "a")
    _, _, second = mini_emb.build(tmp_path, "b", given=_same_given(tmp_path),
                                  encoder=_drift(1 + 1e-4, probes=True))
    a, b = first.layers["emb"], second.layers["emb"]
    probe_files = [attach.read_attachment(x.path, vectors.NAME)[1][vectors.PROBES] for x in (a, b)]
    assert probe_files[0] != probe_files[1]
    assert a.version == b.version
    assert check_det(a.path, b.path).passed


def _same_given(tmp_path):
    layers = {p.parent.name: p for p in (tmp_path / "given").glob("*/*@*")}
    text, struct = store.read_layer(layers["text"]), store.read_layer(layers["struct"])
    return (store.StoredLayer("text", text.version, text.path),
            store.StoredLayer("struct", struct.version, struct.path))


def test_det_catches_vectors_that_moved(tmp_path):
    _, _, first = mini_emb.build(tmp_path, "a")
    _, _, second = mini_emb.build(tmp_path, "b", given=_same_given(tmp_path), encoder=_moved(),
                                  compat_sample=0)
    assert second.layers, [g.details for g in second.gates if not g.passed]
    det = check_det(first.layers["emb"].path, second.layers["emb"].path)
    assert not det.passed and any("cos" in d for d in det.details)


def test_a_red_build_stores_nothing(tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text(mini_emb.MINI_COUNTS.read_text(encoding="utf-8").replace(
        "embedding_records: {value: 22,", "embedding_records: {value: 23,"), encoding="utf-8")
    _, _, result = mini_emb.build(tmp_path, counts=counts)
    assert not result.passed and result.layers == {}
    assert not (tmp_path / "store").exists()


def test_vectors_unlike_the_legacy_index_turn_g_enc_red(tmp_path):
    other = fake_encoder.make(embed_fn=lambda t: fake_encoder.embed([x[::-1] for x in t]))
    _, _, result = mini_emb.build(tmp_path, encoder=other)
    enc = next(g for g in result.gates if g.name == "G-ENC")
    assert not enc.passed and any(d.startswith("legacy: ") for d in enc.details)


def test_the_layers_must_be_a_struct_layer_and_the_text_layer_it_was_built_on(tmp_path):
    text, struct = mini_build.write_layers(tmp_path / "given")
    other, _ = mini_build.write_layers(tmp_path / "other", text={
        **mini_build.text_layer(), "ref_aliases": []})
    with pytest.raises(StageError, match="struct layer"):
        mini_emb.build(tmp_path, given=(struct, text))
    with pytest.raises(StageError, match="built on"):
        mini_emb.build(tmp_path, given=(other, struct))


def test_a_rebuild_into_the_same_store_keeps_the_stored_vectors(tmp_path):
    _, _, first = mini_emb.build(tmp_path)
    _, _, again = mini_emb.build(tmp_path, given=_same_given(tmp_path), encoder=_drift(1 + 1e-7))
    assert again.layers["emb"] == first.layers["emb"]
    with pytest.raises(StageError, match="already stored"):
        mini_emb.build(tmp_path, given=_same_given(tmp_path), encoder=_moved(), compat_sample=0)


def test_a_rebuild_whose_probes_moved_is_refused(tmp_path):
    mini_emb.build(tmp_path)

    def embed(texts):
        moved = tuple(texts) == pins.BGE_M3.probes
        return fake_encoder.embed([t + "!" for t in texts] if moved else texts)
    with pytest.raises(StageError, match="probe"):
        mini_emb.build(tmp_path, given=_same_given(tmp_path),
                       encoder=fake_encoder.make(embed_fn=embed))
