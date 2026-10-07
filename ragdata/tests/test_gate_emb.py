"""G-EMB: records are S6 of their layers under a declared template, and the vectors match them."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import fake_encoder
import mini_build
from ragdata.gates import check_schema
from ragdata.gates.base import snapshot
from ragdata.gates.emb import EmbFiles, check_emb
from ragdata.stages.s06_emb import records, template
from ragdata.stages.s06_emb.records import emb_report
from ragdata.store import vectors as vector_files

STATS = fake_encoder.make().stats


def _base():
    files = {**mini_build.files("text", "struct")}
    _, snap = check_schema(files, ("text", "struct"))
    return snap


def _gate(rows=None, report=None, matrix=None, index=None):
    base = _base()
    rows = records.emb_records(base, template.V1C, STATS) if rows is None else rows
    _, own = check_schema({"embedding_records.jsonl": rows}, ("emb",))
    snap = snapshot({**base.records, **own.records})
    report = emb_report("struct@000000000000", "text@000000000000", template.V1C, rows) \
        if report is None else report
    texts = [r["text"] for r in rows]
    matrix = fake_encoder.embed(texts) if matrix is None else matrix
    stored = vector_files.encode_vectors([(r["record_id"], r["text_sha"]) for r in rows], matrix)
    decoded, decoded_index = vector_files.decode_vectors(stored)
    files = EmbFiles(report, decoded, decoded_index if index is None else index)
    return check_emb(snap, files, STATS)


def _rows():
    return records.emb_records(_base(), template.V1C, STATS)


def test_the_s6_records_with_their_vectors_pass():
    result = _gate()
    assert result.passed, result.details
    assert result.observed["records"] == {"verse": 14, "passage": 6, "chunk": 2, "total": 22}
    assert result.observed["formula"] == {"units": 14, "unchunked_passages": 6, "chunks": 2}


def _set_payload(rows, record_id, **changes):
    next(r for r in rows if r["record_id"] == record_id)["payload"].update(changes)
    return rows


def _retext(rows, record_id, new_text):
    row = next(r for r in rows if r["record_id"] == record_id)
    row["text"] = new_text
    row["text_sha"] = row["payload"]["text_sha"] = mini_build.sha(new_text)
    row["payload"]["content_preview"] = new_text[:200] if row["kind"] != "verse" \
        else row["payload"]["content_preview"]
    return rows


MUTATIONS = {
    "payload title": lambda rows: _set_payload(rows, "vs:act.10.1", title="別的標題"),
    "payload split": lambda rows: _set_payload(rows, "vs:act.9.3", split_passage_ids=[]),
    "old template text": lambda rows: _retext(rows, "vs:act.10.1",
                                               "使徒行傳 第10章 (無標題) 第1節：在凱撒利亞有一個人名叫哥尼流。"),
    "dropped record": lambda rows: [r for r in rows if r["record_id"] != "vs:psa.42.3"],
    "chunked passage embedded": lambda rows: rows + [_ps_act_9_1()],
    "reordered": lambda rows: [rows[1], rows[0], *rows[2:]],
    "token count": lambda rows: [{**r, "token_count": r["token_count"] + 1}
                                 if r["record_id"] == "ps:mat.18.1" else r for r in rows],
}


def _ps_act_9_1():
    text = mini_build.EMBED["ps:act.9.1"]
    row = copy.deepcopy(next(r for r in _rows() if r["record_id"] == "ck:act.9.1~act.9.2"))
    from ragcommon import ids
    row.update(record_id="ps:act.9.1", kind="passage", source_id="ps:act.9.1", text=text,
               text_sha=mini_build.sha(text), token_count=mini_build.count_tokens(text),
               unk_count=mini_build.count_unk(text), point_id=ids.point_id("ps:act.9.1"))
    row["payload"].update(record_id="ps:act.9.1", kind="passage", type="pericope",
                          verse_range="1-3", end_key="act.9.3", content_preview=text[:200],
                          text_sha=mini_build.sha(text))
    return row


@pytest.mark.parametrize("mutate", MUTATIONS.values(), ids=MUTATIONS.keys())
def test_records_that_are_not_s6_of_their_layers_fail(mutate):
    assert not _gate(rows=mutate(_rows())).passed


def test_an_undeclared_or_altered_template_fails():
    rows = _rows()
    report = emb_report("struct@000000000000", "text@000000000000", template.V1C, rows)
    altered = copy.deepcopy(report)
    altered["template"]["formats"]["verse"] = "{書名}{章}{n}：{經文}"
    unknown = copy.deepcopy(report)
    unknown["template"]["template_id"] = "v9"
    for bad in (altered, unknown, {**report, "counts": {**report["counts"], "verse": 13}}):
        assert not _gate(rows=rows, report=bad).passed


def test_vectors_must_be_one_unit_row_per_record_with_matching_hashes():
    rows = _rows()
    m = fake_encoder.embed([r["text"] for r in rows])
    assert not _gate(matrix=m * 2).passed                           # not unit length
    _, index = vector_files.decode_vectors(vector_files.encode_vectors(
        [(r["record_id"], r["text_sha"]) for r in rows], m))
    index = [dict(r) for r in index]
    index[0]["vec_sha"] = "0" * 64
    assert not _gate(index=index).passed
    assert not _gate(index=index[1:]).passed


def test_missing_vectors_fail_closed():
    rows = _rows()
    base = _base()
    _, own = check_schema({"embedding_records.jsonl": rows}, ("emb",))
    snap = snapshot({**base.records, **own.records})
    report = emb_report("struct@000000000000", "text@000000000000", template.V1C, rows)
    files = EmbFiles(report, None, ())
    result = check_emb(snap, files, STATS)
    assert not result.passed and any("vectors" in d for d in result.details)
