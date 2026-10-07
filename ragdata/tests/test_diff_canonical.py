"""Field-by-field diff of the text layer against the audit's canonical_full.jsonl."""

from __future__ import annotations

import json

import pytest

from ragdata.stages.diffs import canonical as dc

PDF_SHA = "a" * 64


def _rows():
    unit = {"unit_key": "psa.1.4", "book_id": "psa", "chapter": 1, "label": "4", "v_start": 4,
            "v_end": 4, "text_pdf": "乃像糠詷被風吹散", "text": "乃像糠秕被風吹散",
            "line_breaks": [{"offset": 4, "kind": "soft"}], "pages": [1],
            "markers": [], "prov": {"pdf_sha256": PDF_SHA, "first_glyph": [1.0, 2.0, 3.0]}}
    selah = {**unit, "unit_key": "psa.3.2", "chapter": 3, "label": "2", "v_start": 2,
             "v_end": 2, "text_pdf": "他得不着（細拉）", "text": "他得不着（細拉）",
             "line_breaks": [], "markers": [{"type": "selah", "start": 4, "end": 8}]}
    return {
        "books": [{"book_id": "psa", "file_name": "詩篇"}], "verse_units": [unit, selah],
        "verse_slots": [{"slot_key": "psa.1.5", "status": "omitted_variant",
                         "variant_footnote_id": "fn:psa.1.4#1"}],
        "headings": [{"heading_id": "hd:psa.1.4#1", "anchor_unit_key": "psa.1.4",
                      "anchor_offset": 0, "pos": "before", "text_pdf": "惡人"}],
        "parallel_refs": [{"heading_id": "hd:psa.1.4#1", "raw": "（太3‧12）"}],
        "speakers": [],
        "name_spans": [{"container_id": "psa.1.4", "region": "body", "start": 0, "end": 1,
                        "surface": "乃"}],
        "footnotes": [{"fn_id": "fn:psa.1.4#1", "unit_key": "psa.1.4", "n": 1,
                       "text_pdf": "或譯：牛詴", "text": "或譯：牛虻", "anchor": None}],
        "errata_applied": [
            {"errata_id": "er:0001", "container_id": "psa.1.4", "offset": 3,
             "pdf_char": "詷", "corrected_char": "秕"},
            {"errata_id": "er:0002", "container_id": "fn:psa.1.4#1", "offset": 4,
             "pdf_char": "詴", "corrected_char": "虻"}],
    }


def _canonical():
    unit = {"id": "psa.1.4", "book": "psa", "book_file": "詩篇", "chapter": 1, "verse": "4",
            "v_start": 4, "v_end": 4, "status": "present", "text": "乃像糠詷被風吹散",
            "line_starts": [0, 4], "pages": [1],
            "annotations": [{"type": "heading", "offset": 0, "pos": "before", "text": "惡人"},
                            {"type": "parallel_ref", "offset": 0, "pos": "before",
                             "text": "（太3‧12）", "heading_ref": 0},
                            {"type": "name", "start": 0, "end": 1, "surface": "乃"},
                            {"type": "footnote", "n": 1, "text": "或譯：牛詴", "anchor": None}],
            "prov": {"pdf": "詩篇.pdf", "pdf_sha256": PDF_SHA, "first_glyph": [1.0, 2.0, 3.0]}}
    selah = {**unit, "id": "psa.3.2", "chapter": 3, "verse": "2", "v_start": 2, "v_end": 2,
             "text": "他得不着（細拉）", "line_starts": [0], "prov": dict(unit["prov"]),
             "annotations": [{"type": "selah", "start": 4, "end": 8}]}
    omitted = {"id": "psa.1.5", "book": "psa", "chapter": 1, "verse": "5", "v_start": 5,
               "v_end": 5, "status": "omitted_variant", "text": None,
               "variant_in_footnote_of": "psa.1.4"}
    other_book = {**unit, "id": "rut.1.1", "book": "rut"}
    return [unit, selah, omitted, other_book]


def _write(tmp_path, records):
    path = tmp_path / "canonical_full.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")
    return path


def _diff(tmp_path, records=None, rows=None):
    return dc.diff_canonical(rows or _rows(), _write(tmp_path, records or _canonical()))


def test_only_the_errata_differ_and_they_are_classified(tmp_path):
    result = _diff(tmp_path)
    assert [(r.record, r.field, r.layer, r.canonical, r.cls) for r in result.rows] == [
        ("psa.1.4", "text@serving[3]", "秕", "詷", "errata"),
        ("psa.1.4", "ann.footnote@serving[4]", "虻", "詴", "errata"),
    ]
    assert result.summary["records_compared"] == 3
    assert result.summary["by_class"] == {"errata": 2, "other": 0}


@pytest.mark.parametrize("edit, field", [
    (lambda c: c[0].update(text="乃像糠秕被風吹散"), "text"),
    (lambda c: c[0].update(line_starts=[0, 5]), "line_starts"),
    (lambda c: c[0]["annotations"][0].update(text="義人"), "ann.heading"),
    (lambda c: c[0]["annotations"][1].update(text="（太3‧11）"), "ann.parallel_ref"),
    (lambda c: c[0]["annotations"].pop(2), "ann.name"),
    (lambda c: c[1]["annotations"].clear(), "ann.selah"),
    (lambda c: c[0]["prov"].update(first_glyph=[9.0, 2.0, 3.0]), "prov.first_glyph"),
    (lambda c: c[2].update(variant_in_footnote_of="psa.1.3"), "variant_in_footnote_of"),
    (lambda c: c.pop(1), "id"),
    (lambda c: c.append({**c[1], "id": "psa.3.3", "verse": "3", "v_start": 3, "v_end": 3}),
     "id"),
], ids=["text", "lines", "heading", "parallel", "name", "selah", "glyph", "variant",
        "layer only", "canonical only"])
def test_any_other_difference_is_other(tmp_path, edit, field):
    records = _canonical()
    edit(records)
    result = _diff(tmp_path, records)
    others = [r for r in result.rows if r.cls == "other"]
    assert [r.field for r in others] == [field], others


def test_a_text_difference_outside_errata_at_serving_is_other(tmp_path):
    rows = _rows()
    rows["verse_units"][0]["text"] = "乃像糠秕被風吹走"
    assert [r.cls for r in _diff(tmp_path, rows=rows).rows] == ["errata", "other", "errata"]


def test_a_missing_reference_file_is_an_error(tmp_path):
    with pytest.raises(dc.DiffError, match="canonical"):
        dc.diff_canonical(_rows(), tmp_path / "canonical_full.jsonl")


def test_the_tsv_has_a_header_and_one_line_per_row(tmp_path):
    lines = dc.encode_tsv(_diff(tmp_path).rows).decode("utf-8").splitlines()
    assert lines[0].split("\t") == list(dc.TSV_COLUMNS) and len(lines) == 3
