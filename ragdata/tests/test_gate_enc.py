"""G-ENC: the stored encoder fingerprint is the pinned one and this environment reproduces it."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import fake_encoder
from ragcommon import encoder as pins
from ragdata.gates import enc
from ragdata.stages.s06_emb import fingerprint
from ragdata.store import vectors as vector_files

STORED = fingerprint.encoder_fingerprint(fake_encoder.make())
CLEAN = {"probes": ({"probes": 0}, []), "legacy": ({"sampled": 0}, []),
         "reencoded": ({"sampled": 0}, [])}
TEXTS = [f"經文 {i}" for i in range(30)]
IDS = [f"vs:gen.1.{i + 1}" for i in range(30)]


def _check(stored=None, observed=None, max_tokens=100, checks=None):
    stored = copy.deepcopy(STORED) if stored is None else stored
    return enc.check_enc(stored, copy.deepcopy(STORED) if observed is None else observed,
                         max_tokens, CLEAN if checks is None else checks)


def _with(section, **changes):
    doc = copy.deepcopy(STORED)
    doc[section].update(changes)
    return doc


def _vector_set(matrix=None, probes=None):
    matrix = fake_encoder.embed(TEXTS) if matrix is None else matrix
    probes = fake_encoder.embed(pins.BGE_M3.probes) if probes is None else probes
    return vector_files.decode_vectors(vector_files.encode_vectors(
        [(i, "a" * 64) for i in IDS], matrix, probes))


def test_the_pinned_fingerprint_reproduced_passes():
    result = _check()
    assert result.passed and result.name == "G-ENC", result.details


@pytest.mark.parametrize("stored", [
    _with("bge_m3", tokenizer_sha="0" * 64),
    _with("bge_m3", probe_ids_sha="0" * 64),
    _with("bge_m3", revision="0" * 40),
    _with("bge_m3", model="BAAI/bge-large-zh"),
    _with("bge_m3", normalize=False),
    _with("bge_m3", pair_template_ok=False),
    _with("reranker", tokenizer_sha="0" * 64),
    _with("reranker", revision="0" * 40),
], ids=["m3 tokenizer", "m3 probe ids", "m3 revision", "model", "normalize", "pair",
        "reranker tokenizer", "reranker revision"])
def test_a_fingerprint_off_its_pins_fails(stored):
    assert not _check(stored=stored, observed=stored).passed


@pytest.mark.parametrize("observed", [
    _with("bge_m3", unk_count=99), _with("bge_m3", batch_size=64), _with("bge_m3", probes=3),
    _with("bge_m3", extra=1), {**STORED, "schema": "ragdata.encoder_fingerprint.v1"},
    {**STORED, "probe_vectors_sha": "0" * 64},
], ids=["unk", "batch", "probe count", "extra key", "schema", "extra section"])
def test_another_environment_must_reproduce_the_whole_fingerprint(observed):
    assert not _check(observed=observed).passed


def test_a_fingerprint_section_that_is_not_an_object_fails():
    assert not _check(stored={**STORED, "reranker": "x"}).passed


def test_stored_probes_reproduced_here_pass():
    seen, violations = enc.check_probes(_vector_set(), fake_encoder.embed(pins.BGE_M3.probes))
    assert violations == [] and seen["min_cos"] == pytest.approx(1.0)
    assert seen["probes"] == len(pins.BGE_M3.probes) and seen["sha_equal"] is True


def test_probes_that_moved_here_fail():
    here = fake_encoder.embed(pins.BGE_M3.probes)
    here[0] = -here[0]
    _, violations = enc.check_probes(_vector_set(), here)
    assert violations and violations[0].startswith("probe 0: cos")


def test_tiny_probe_drift_is_tolerated_and_its_sha_only_reported():
    here = fake_encoder.embed(pins.BGE_M3.probes) * np.float32(1 + 1e-4)
    seen, violations = enc.check_probes(_vector_set(), here)
    assert violations == [] and seen["sha_equal"] is False


def test_stored_probes_must_be_the_pinned_probes():
    fewer = _vector_set(probes=fake_encoder.embed(pins.BGE_M3.probes[:-1]))
    here = fake_encoder.embed(pins.BGE_M3.probes)
    _, violations = enc.check_probes(fewer, here)
    assert violations and "probe vectors" in violations[0]


def test_a_record_longer_than_the_model_reads_fails():
    assert not _check(max_tokens=8191).passed and _check(max_tokens=8190).passed


def test_sub_check_violations_fail_the_gate():
    bad = ({"sampled": 1}, ["vs:gen.1.1: cos 0.5 < 0.9999"])
    for name in CLEAN:
        result = _check(checks={**CLEAN, name: bad})
        assert not result.passed and result.observed[name] == {"sampled": 1}
        assert result.details[0].startswith(f"{name}: ")


def test_stored_rows_reencode_to_themselves():
    matrix = fake_encoder.embed(TEXTS)
    observed, violations = enc.check_reencoded(fake_encoder.embed, IDS, TEXTS, matrix, 10)
    assert violations == [] and observed["sampled"] == 10 and observed["min_cos"] > 0.9999


def test_rows_stored_for_other_texts_are_caught():
    shifted = np.roll(fake_encoder.embed(TEXTS), 1, axis=0)
    _, violations = enc.check_reencoded(fake_encoder.embed, IDS, TEXTS, shifted, 10)
    assert len(violations) == 10


class _Rec:
    def __init__(self, i):
        self.record_id, self.text, self.token_count = IDS[i], TEXTS[i], 10


def _run(vector_set, tmp_path, encoder=None):
    stored = enc.StoredEncoding(STORED, vector_set)
    options = enc.EncOptions(legacy_dir=tmp_path)
    return enc.run_enc([_Rec(i) for i in range(30)], stored, encoder or fake_encoder.make(),
                       options)


@pytest.mark.parametrize("matrix", [None, np.zeros((29, fake_encoder.DIM), np.float32)])
def test_run_enc_fails_closed_without_one_vector_per_record(tmp_path, matrix):
    vector_set = None if matrix is None else vector_files.VectorSet(
        matrix, (), fake_encoder.embed(pins.BGE_M3.probes).astype(np.float64), "0" * 64)
    result = _run(vector_set, tmp_path)
    assert not result.passed
    assert {d.split(":")[0] for d in result.details} == {"probes", "reencoded", "legacy"}


def test_run_enc_compares_the_stored_probes_with_this_environments(tmp_path):
    other = fake_encoder.make(embed_fn=lambda t: fake_encoder.embed([x + "?" for x in t]))
    result = _run(_vector_set(), tmp_path, encoder=other)
    assert any(d.startswith("probes: probe 0") for d in result.details)
