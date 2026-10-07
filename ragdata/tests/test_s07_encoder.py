"""S7: the encoder fingerprint, record encoding, and the real pinned BGE-M3 (when present)."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

import fake_encoder
from ragcommon import encoder as pins
from ragdata.stages.errors import StageError
from ragdata.stages.s06_emb import encoder, fingerprint


def test_fingerprint_records_both_tokenizers_the_model_and_the_probe_vectors():
    fp = fingerprint.encoder_fingerprint(fake_encoder.make())
    m3, rr = fp["bge_m3"], fp["reranker"]
    assert (m3["model"], m3["revision"]) == (pins.BGE_M3.repo_id, pins.BGE_M3.revision)
    assert m3["tokenizer_sha"] == pins.BGE_M3.tokenizer_sha256
    assert (rr["model"], rr["revision"]) == (pins.RERANKER.repo_id, pins.RERANKER.revision)
    assert rr["probe_ids_sha"] == pins.RERANKER.probe_ids_sha
    ints = np.array(m3["probe_vectors_e6"])
    assert ints.shape == (len(pins.BGE_M3.probes), fake_encoder.DIM)
    expected = np.rint(fake_encoder.embed(pins.BGE_M3.probes).astype(np.float64) * 1e6)
    assert np.array_equal(ints, expected)
    assert m3["probe_vectors_sha"] == fingerprint.ints_sha(m3["probe_vectors_e6"])


def test_probe_vectors_are_rounded_to_1e_6_as_integers():
    vec = np.array([[0.1234564, -0.1234566, 0.0]], dtype=np.float32)
    assert fingerprint.probe_ints(vec) == [[123456, -123457, 0]]


def test_the_fingerprint_file_is_canonical_json():
    fp = fingerprint.encoder_fingerprint(fake_encoder.make())
    data = fingerprint.encode(fp)
    assert data.endswith(b"\n") and json.loads(data) == fp
    assert fingerprint.encode(json.loads(data)) == data


def test_encode_returns_one_float32_row_per_text_in_order():
    enc = fake_encoder.make()
    out = encoder.encode_texts(enc, ["甲", "乙", "甲"])
    assert out.dtype == np.float32 and out.shape == (3, fake_encoder.DIM)
    assert np.array_equal(out[0], out[2]) and not np.array_equal(out[0], out[1])


@pytest.mark.parametrize("bad", [np.zeros((2, 8)), np.full((3, 8), np.nan), np.zeros((3, 8))])
def test_encode_refuses_rows_that_are_missing_not_finite_or_not_unit_length(bad):
    enc = fake_encoder.make(embed_fn=lambda texts: bad)
    with pytest.raises(StageError):
        encoder.encode_texts(enc, ["甲", "乙", "丙"])


def test_a_missing_tokenizer_file_stops_loading(tmp_path):
    with pytest.raises(StageError, match="tokenizer"):
        encoder.load_encoder(tokenizer=tmp_path / "missing.json")


HF_HUB = pins.hub_cache_dir()
M3_SNAPSHOT = HF_HUB / "models--BAAI--bge-m3" / "snapshots" / pins.BGE_M3.revision
needs_model = pytest.mark.skipif(
    not (M3_SNAPSHOT / "tokenizer.json").is_file() or not encoder.RERANKER_TOKENIZER.is_file()
    or os.environ.get("HF_HUB_OFFLINE") != "1",
    reason="needs the pinned BGE-M3 snapshot, the reranker tokenizer and HF_HUB_OFFLINE=1")


@needs_model
def test_the_real_encoder_is_the_pinned_bge_m3_with_its_pinned_tokenizer():
    enc = encoder.load_encoder()
    assert enc.model["revision"] == pins.BGE_M3.revision and enc.model["dim"] == 1024
    assert enc.tokenizers[pins.BGE_M3.name]["probe_ids_sha"] == pins.BGE_M3.probe_ids_sha
    assert enc.tokenizers[pins.RERANKER.name]["probe_ids_sha"] == pins.RERANKER.probe_ids_sha
    tokens, unk = enc.stats.of("騾子，稗子。")
    assert tokens >= 4 and unk >= 1
    vecs = encoder.encode_texts(enc, ["起初，上帝創造天地。", "起初，上帝創造天地。"])
    assert vecs.shape == (2, 1024) and np.allclose(np.linalg.norm(vecs, axis=1), 1, atol=1e-5)
