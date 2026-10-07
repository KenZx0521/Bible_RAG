"""G-ENC: the stored encoder fingerprint is the pinned one and this environment reproduces it."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import fake_encoder
from ragcommon import encoder as pins
from ragdata.gates import enc
from ragdata.stages.s06_emb import fingerprint

STORED = fingerprint.encoder_fingerprint(fake_encoder.make())
CLEAN = {"legacy": ({"sampled": 0}, []), "reencoded": ({"sampled": 0}, [])}


def _check(stored=None, observed=None, max_tokens=100, checks=None):
    stored = copy.deepcopy(STORED) if stored is None else stored
    return enc.check_enc(stored, copy.deepcopy(STORED) if observed is None else observed,
                         max_tokens, CLEAN if checks is None else checks)


def _with(section, **changes):
    doc = copy.deepcopy(STORED)
    doc[section].update(changes)
    return doc


def test_the_pinned_fingerprint_reproduced_passes():
    result = _check()
    assert result.passed and result.name == "G-ENC", result.details
    assert result.observed["probe_min_cos"] == pytest.approx(1.0)


@pytest.mark.parametrize("stored", [
    _with("bge_m3", tokenizer_sha="0" * 64),
    _with("bge_m3", probe_ids_sha="0" * 64),
    _with("bge_m3", revision="0" * 40),
    _with("bge_m3", model="BAAI/bge-large-zh"),
    _with("bge_m3", normalize=False),
    _with("bge_m3", pair_template_ok=False),
    _with("reranker", tokenizer_sha="0" * 64),
    _with("reranker", revision="0" * 40),
    _with("bge_m3", probe_vectors_sha="0" * 64),
    _with("bge_m3", probe_vectors_e6=STORED["bge_m3"]["probe_vectors_e6"][:-1]),
], ids=["m3 tokenizer", "m3 probe ids", "m3 revision", "model", "normalize", "pair",
        "reranker tokenizer", "reranker revision", "probe sha", "probe rows"])
def test_a_fingerprint_off_its_pins_fails(stored):
    assert not _check(stored=stored, observed=stored).passed


def test_another_environment_must_reproduce_tokenizers_settings_and_probe_vectors():
    assert not _check(observed=_with("bge_m3", unk_count=99)).passed
    assert not _check(observed=_with("bge_m3", batch_size=64)).passed
    ints = np.array(STORED["bge_m3"]["probe_vectors_e6"])
    ints[0] = -ints[0]
    moved = _with("bge_m3", probe_vectors_e6=ints.tolist(),
                  probe_vectors_sha=fingerprint.ints_sha(ints.tolist()))
    result = _check(observed=moved)
    assert not result.passed and any("probe 0" in d for d in result.details)


def test_tiny_probe_drift_is_tolerated_and_only_reported():
    ints = np.array(STORED["bge_m3"]["probe_vectors_e6"]) + 1
    drifted = _with("bge_m3", probe_vectors_e6=ints.tolist(),
                    probe_vectors_sha=fingerprint.ints_sha(ints.tolist()))
    result = _check(observed=drifted)
    assert result.passed and result.observed["probe_vectors_sha_equal"] is False


def test_a_record_longer_than_the_model_reads_fails():
    assert not _check(max_tokens=8191).passed and _check(max_tokens=8190).passed


def test_legacy_or_reencoding_violations_fail_the_gate():
    bad = ({"sampled": 1}, ["vs:gen.1.1: cos 0.5 < 0.9999"])
    for name in CLEAN:
        result = _check(checks={**CLEAN, name: bad})
        assert not result.passed and result.observed[name] == {"sampled": 1}
        assert result.details[0].startswith(f"{name}: ")


TEXTS = [f"經文 {i}" for i in range(30)]
IDS = [f"vs:gen.1.{i + 1}" for i in range(30)]


def test_stored_rows_reencode_to_themselves():
    matrix = fake_encoder.embed(TEXTS)
    observed, violations = enc.check_reencoded(fake_encoder.embed, IDS, TEXTS, matrix, 10)
    assert violations == [] and observed["sampled"] == 10 and observed["min_cos"] > 0.9999


def test_rows_stored_for_other_texts_are_caught():
    shifted = np.roll(fake_encoder.embed(TEXTS), 1, axis=0)
    _, violations = enc.check_reencoded(fake_encoder.embed, IDS, TEXTS, shifted, 10)
    assert len(violations) == 10


def test_the_fingerprint_probe_count_is_ragcommons():
    assert STORED["bge_m3"]["probes"] == len(pins.BGE_M3.probes)


class _Rec:
    def __init__(self, i):
        self.record_id, self.text, self.token_count = IDS[i], TEXTS[i], 10


@pytest.mark.parametrize("matrix", [None, np.zeros((29, fake_encoder.DIM), np.float32)])
def test_run_enc_fails_closed_without_one_vector_per_record(tmp_path, matrix):
    recs = [_Rec(i) for i in range(30)]
    result = enc.run_enc(recs, matrix, STORED, fake_encoder.make(), tmp_path)
    assert not result.passed
    assert {d.split(":")[0] for d in result.details} == {"reencoded", "legacy"}
