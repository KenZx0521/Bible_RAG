"""Vector comparisons: G-DET's tolerance for two encodings, and the legacy twin check."""

from __future__ import annotations

import json

import numpy as np
import pytest

import fake_encoder
from ragdata.gates import emb_legacy, vectors
from ragdata.store import vectors as store_vectors

RNG = np.random.default_rng(7)


def _unit(rows, dim=16, rng=RNG):
    m = rng.normal(size=(rows, dim))
    return (m / np.linalg.norm(m, axis=1, keepdims=True)).astype(np.float32)


def _ids(n):
    return [f"vs:gen.1.{i + 1}" for i in range(n)]


def test_two_runs_within_tolerance_pass():
    a = _unit(300)
    b = (a + 1e-7).astype(np.float32)
    observed, violations = vectors.compare_runs(_ids(300), a, _ids(300), b)
    assert violations == [] and observed["min_cos"] >= vectors.DET_COS
    assert observed["queries"] == vectors.QUERIES and observed["topk_differ"] == 0


def test_a_row_off_by_more_than_the_tolerance_fails():
    a = _unit(50)
    b = a.copy()
    b[3] = _unit(1)[0]
    _, violations = vectors.compare_runs(_ids(50), a, _ids(50), b)
    assert any("vs:gen.1.4" in v for v in violations)


def test_a_different_neighbourhood_fails_even_when_rows_are_close():
    a = _unit(40)
    b = a.copy()
    b[:, 0] += np.where(np.arange(40) % 2, 2e-3, -2e-3).astype(np.float32)
    observed, violations = vectors.compare_runs(_ids(40), a, _ids(40), b, cos_min=0.99)
    assert observed["topk_differ"] > 0 and any("top-20" in v for v in violations)


def test_runs_over_other_records_or_shapes_are_not_compared():
    a = _unit(5)
    _, violations = vectors.compare_runs(_ids(5), a, _ids(4), a[:4])
    assert violations and "records" in violations[0]


def _set(matrix, probes):
    return store_vectors.decode_vectors(store_vectors.encode_vectors(
        [(i, "a" * 64) for i in _ids(len(matrix))], matrix, probes))


def test_two_vector_sets_compare_their_rows_and_their_probes():
    a, probes = _unit(30), _unit(4)
    observed, violations = vectors.compare_sets(_set(a, probes), _set(a, probes * 1.0001))
    assert violations == [] and observed["probes"]["min_cos"] >= vectors.DET_COS
    moved = probes.copy()
    moved[2] = _unit(1)[0]
    _, violations = vectors.compare_sets(_set(a, probes), _set(a, moved))
    assert violations == [f"probe 2: cos {vectors.rowwise_cos(probes, moved)[2]:.7f} < "
                          f"{vectors.DET_COS}"]
    _, violations = vectors.compare_sets(_set(a, probes), _set(a, probes[:3]))
    assert violations and "probe vectors" in violations[0]


def test_topk_returns_the_k_nearest_rows_by_dot_product():
    m = np.eye(4, dtype=np.float32)
    assert vectors.topk_sets(m, m[[2]], 1) == [frozenset({2})]


# ---------------------------------------------------------------- legacy twins


def _legacy(tmp_path, rows):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "embedding_queue.jsonl").write_text("".join(
        json.dumps({"id": i, "type": "verse", "text": t}, ensure_ascii=False) + "\n"
        for i, t, _ in rows), encoding="utf-8")
    (tmp_path / "embeddings.jsonl").write_text("".join(
        json.dumps({"id": i, "type": "verse", "embedding": v}) + "\n" for i, _, v in rows),
        encoding="utf-8")
    return tmp_path


TEXTS = ["甲 第1節：一", "甲 第2節：二", "甲 第3節：三", "乙 第1節：四"]


def _records():
    return [(f"vs:gen.1.{i + 1}", t) for i, t in enumerate(TEXTS)]


def test_records_with_an_identical_old_text_reuse_its_vector(tmp_path):
    new = fake_encoder.embed(TEXTS)
    old = [(f"gen:1:0:v:{i}", t, fake_encoder.vector(t).tolist()) for i, t in enumerate(TEXTS[:3])]
    old.append(("gen:2:0:v:1", "舊模板的文字", fake_encoder.vector("x").tolist()))
    observed, violations = emb_legacy.check_compat(_records(), new, _legacy(tmp_path, old), 3)
    assert violations == []
    assert (observed["identical_texts"], observed["sampled"]) == (3, 3)
    assert observed["min_cos"] >= emb_legacy.MIN_COS


def test_a_twin_with_another_vector_fails(tmp_path):
    new = fake_encoder.embed(TEXTS)
    old = [(f"gen:1:0:v:{i}", t, fake_encoder.vector(t + "!").tolist())
           for i, t in enumerate(TEXTS)]
    _, violations = emb_legacy.check_compat(_records(), new, _legacy(tmp_path, old), 4)
    assert len(violations) == 4 and "cos" in violations[0]


def test_too_few_twins_or_no_legacy_files_fail_closed(tmp_path):
    new = fake_encoder.embed(TEXTS)
    old = [("gen:1:0:v:0", TEXTS[0], fake_encoder.vector(TEXTS[0]).tolist())]
    _, violations = emb_legacy.check_compat(_records(), new, _legacy(tmp_path / "a", old), 2)
    assert violations and "1 record" in violations[0]
    _, violations = emb_legacy.check_compat(_records(), new, tmp_path / "missing", 2)
    assert violations and "missing" in violations[0]


def test_the_sample_is_fixed_by_its_seed(tmp_path):
    texts = [f"丙 第{i}節：{i}" for i in range(30)]
    old = [(f"x:{i}", t, fake_encoder.vector(t).tolist()) for i, t in enumerate(texts)]
    recs = [(f"vs:gen.2.{i + 1}", t) for i, t in enumerate(texts)]
    legacy = _legacy(tmp_path, old)
    first = emb_legacy.check_compat(recs, fake_encoder.embed(texts), legacy, 5)[0]
    again = emb_legacy.check_compat(recs, fake_encoder.embed(texts), legacy, 5)[0]
    assert first["sampled_ids"] == again["sampled_ids"] and len(first["sampled_ids"]) == 5


@pytest.mark.parametrize("bad_line", ['{"id": "a"', '{"type": "verse"}'])
def test_a_malformed_legacy_queue_fails_closed(tmp_path, bad_line):
    tmp_path.joinpath("embedding_queue.jsonl").write_text(bad_line + "\n", encoding="utf-8")
    tmp_path.joinpath("embeddings.jsonl").write_text("", encoding="utf-8")
    _, violations = emb_legacy.check_compat(_records(), fake_encoder.embed(TEXTS), tmp_path, 1)
    assert violations
