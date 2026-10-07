"""``gate emb``: a stored emb layer with its struct and text layers, its vectors and encoder."""

from __future__ import annotations

import shutil

import pytest

import fake_encoder
import mini_build
import mini_emb
from ragdata import store
from ragdata.gates import runner
from ragdata.gates.runner import GateInputError, GateInputs, gate_layer
from ragdata.store import attach, vectors


def _inputs(tmp_path, **changes):
    fields = {"encoder": fake_encoder.make(), "legacy_dir": mini_emb.legacy_dir(tmp_path / "old"),
              "compat_sample": mini_emb.SAMPLE}
    return GateInputs(**{**fields, **changes})


def _built(tmp_path):
    text, struct, result = mini_emb.build(tmp_path)
    assert result.passed
    return text, struct, result.layers["emb"]


def _gate(tmp_path, emb, deps, **changes):
    return gate_layer(emb.path, "emb", [d.path for d in deps], mini_emb.MINI_COUNTS,
                      inputs=_inputs(tmp_path, **changes))


def test_a_built_emb_layer_passes_every_required_gate(tmp_path):
    text, struct, emb = _built(tmp_path)
    report = _gate(tmp_path, emb, [struct, text])
    assert report.passed, report.to_json()
    assert [g.name for g in report.gates] == ["G-SCHEMA", "G-COUNT", "G-EMB", "G-ENC"]
    assert list(runner.REQUIRED_GATES["emb"]) == ["G-SCHEMA", "G-COUNT", "G-EMB", "G-ENC"]


def test_missing_vectors_turn_g_emb_and_g_enc_red(tmp_path):
    text, struct, emb = _built(tmp_path)
    shutil.rmtree(attach.attachment_dir(emb.path, vectors.NAME))
    red = {g.name for g in _gate(tmp_path, emb, [struct, text]).gates if not g.passed}
    assert red == {"G-EMB", "G-ENC"}


def test_an_encoder_that_cannot_load_fails_closed(tmp_path):
    text, struct, emb = _built(tmp_path)
    report = _gate(tmp_path, emb, [struct, text], encoder=None,
                   tokenizer=tmp_path / "missing.json")
    red = {g.name: g for g in report.gates if not g.passed}
    assert set(red) == {"G-EMB", "G-ENC"}
    assert all(g.observed == "missing input" for g in red.values())


def test_another_environment_must_reproduce_the_probes(tmp_path):
    text, struct, emb = _built(tmp_path)
    other = fake_encoder.make(embed_fn=lambda t: fake_encoder.embed([x + "?" for x in t]))
    report = _gate(tmp_path, emb, [struct, text], encoder=other)
    assert {g.name for g in report.gates if not g.passed} == {"G-ENC"}


def test_emb_needs_its_struct_and_the_text_layer_struct_was_built_on(tmp_path):
    text, struct, emb = _built(tmp_path)
    with pytest.raises(GateInputError, match="needs dependencies"):
        _gate(tmp_path, emb, [struct])
    other, _ = mini_build.write_layers(tmp_path / "other", text={
        **mini_build.text_layer(), "ref_aliases": []})
    with pytest.raises(GateInputError, match="built on"):
        _gate(tmp_path, emb, [struct, other])


@pytest.mark.parametrize("name", ["emb_report.json", "encoder_fingerprint.json"])
def test_an_emb_layer_without_its_report_or_fingerprint_is_refused(tmp_path, name):
    text, struct, emb = _built(tmp_path)
    built = store.read_layer(emb.path)
    files = {f: (emb.path / f).read_bytes() for f in built.file_shas
             if f not in (name, store.DEPENDS_ON)}
    broken = store.write_layer(tmp_path / "broken", "emb", files, depends_on=built.depends_on)
    with pytest.raises(GateInputError, match=name):
        _gate(tmp_path, broken, [struct, text])


def test_tampered_vectors_say_why_they_were_not_read(tmp_path):
    text, struct, emb = _built(tmp_path)
    path = attach.attachment_dir(emb.path, vectors.NAME) / vectors.VECTORS
    path.write_bytes(path.read_bytes()[:-4] + b"\0\0\0\0")
    gate = next(g for g in _gate(tmp_path, emb, [struct, text]).gates if g.name == "G-EMB")
    assert not gate.passed and "sha256 differs" in gate.details[0]
