"""S3: poppler cross-check of the text layer (containment, verse numbers, running heads)."""

from __future__ import annotations

import hashlib

import pytest

from ragdata.stages import s03_xcheck as s3

RUT = {"book_id": "rut", "name": "路得記", "file_name": "路得記", "pdf_sha256": ""}
PAGE_1 = "\n".join([
    "路得記 1:1 i 路得記 1:2", "路得記", "1", "1 當士師秉政的時候，", "國中遭遇饑荒。",
    "2 那人名叫以利米勒，", "1:1: 原文是猶大",
])
PAGE_2 = "\n".join(["路得記 1:3 ii 路得記 1:4-5", "他妻名叫拿娥米。", "3 後來 以利米勒死了，",
                    "4-5 他們住了十年。"])
PAGE_3 = "\n".join(["路得記 1:4 iii 路得記 1:4", "又娶了妻。"])
PAGE_4 = "新標點和合本\n"


def _unit(key, ch, vs, ve, lines, pages, ord_):
    text = "".join(lines)
    offsets, at = [], 0
    for line in lines[:-1]:
        at += len(line)
        offsets.append({"offset": at, "kind": "soft"})
    label = str(vs) if vs == ve else f"{vs}-{ve}"
    return {"unit_key": key, "book_id": "rut", "chapter": ch, "label": label, "v_start": vs,
            "v_end": ve, "ord": ord_, "text_pdf": text, "line_breaks": offsets, "pages": pages}


def _units():
    return [
        _unit("rut.1.1", 1, 1, 1, ["當士師秉政的時候，", "國中遭遇饑荒。"], [1], 1),
        _unit("rut.1.2", 1, 2, 2, ["那人名叫以利米勒，", "他妻名叫拿娥米。"], [1, 2], 2),
        _unit("rut.1.3", 1, 3, 3, ["後來以利米勒死了，"], [2], 3),
        _unit("rut.1.4-5", 1, 4, 5, ["他們住了十年。", "又娶了妻。"], [2, 3], 4),
    ]


def _text(*pages):
    return "\f".join(pages) + "\f"


def _book(raw=None, layout=None, units=None):
    text = _text(PAGE_1, PAGE_2, PAGE_3, PAGE_4)
    texts = {"raw": text if raw is None else raw, "layout": text if layout is None else layout}
    return s3.check_book(texts, s3.units_of(units or _units())["rut"], "路得記")


def test_a_faithful_poppler_text_passes_every_check():
    result = _book()
    assert result["containment"]["raw"] == {"contained": 4, "misses": [], "max_gap": 9}
    assert result["containment"]["layout"]["contained"] == 4
    assert result["boundaries"] == {"ok": 4, "misses": []}
    heads = result["running_heads"]
    assert (heads["pages"], heads["with_head"], heads["ok"], heads["continued"]) == (4, 3, 3, 1)
    assert heads["mismatches"] == [] and heads["without_head_not_last"] == []


def test_a_line_poppler_does_not_have_is_a_miss_and_later_units_still_match():
    raw = _text(PAGE_1.replace("國中遭遇饑荒。", "國中。"), PAGE_2, PAGE_3, PAGE_4)
    result = _book(raw=raw)
    assert result["containment"]["raw"]["misses"] == ["rut.1.1"]
    assert result["containment"]["raw"]["contained"] == 3


def test_lines_out_of_order_are_a_miss():
    raw = _text(PAGE_1.replace("2 那人", "3 後來以利米勒死了，\n2 那人"),
                PAGE_2.replace("3 後來 以利米勒死了，\n", ""), PAGE_3, PAGE_4)
    assert _book(raw=raw)["containment"]["raw"]["misses"] == ["rut.1.3"]


def test_a_line_found_too_far_from_the_line_before_is_a_miss():
    filler = "\n".join(["註" * 150, "註" * 100])
    raw = _text(PAGE_1, PAGE_2.replace("4-5 他們住了十年。", "4-5 他們住了十年。\n" + filler),
                PAGE_3, PAGE_4)
    result = _book(raw=raw)
    assert result["containment"]["raw"]["misses"] == ["rut.1.4-5"]


def test_a_verse_number_missing_before_its_first_line_is_a_boundary_miss():
    raw = _text(PAGE_1.replace("2 那人", "那人"), PAGE_2, PAGE_3, PAGE_4)
    result = _book(raw=raw)
    assert result["boundaries"] == {"ok": 3, "misses": ["rut.1.2"]}
    assert result["containment"]["raw"]["contained"] == 4


def test_merged_numbers_may_be_printed_with_any_dash():
    raw = _text(PAGE_1, PAGE_2.replace("4-5 他們", "4–5 他們"), PAGE_3, PAGE_4)
    assert _book(raw=raw)["boundaries"]["ok"] == 4


def test_a_running_head_naming_the_wrong_verse_or_book_is_a_mismatch():
    raw = _text(PAGE_1.replace("路得記 1:2", "路得記 1:3", 1), PAGE_2,
                PAGE_3.replace("路得記 1:4 iii", "約拿書 1:4 iii"), PAGE_4)
    mismatches = _book(raw=raw)["running_heads"]["mismatches"]
    assert [m["page"] for m in mismatches] == [1, 3]


def test_a_page_without_head_before_the_last_page_is_reported():
    raw = _text(PAGE_1, "\n".join(PAGE_2.split("\n")[1:]), PAGE_3, PAGE_4)
    heads = _book(raw=raw)["running_heads"]
    assert heads["without_head_not_last"] == [2] and heads["with_head"] == 2


def _report(**book):
    results = {"rut": _book(**book)}
    return s3.assemble(results, 4)


def test_the_gate_passes_a_clean_report_and_names_every_failure():
    assert s3.check_xcheck(_report()).passed
    bad = _report(raw=_text(PAGE_1.replace("2 那人", "那人"), PAGE_2, PAGE_3, PAGE_4))
    result = s3.check_xcheck(bad)
    assert not result.passed and result.hard and result.name == "G-XCHECK"
    assert any("rut.1.2" in d for d in result.details)


def test_the_gate_fails_when_units_were_not_all_checked():
    report = s3.assemble({"rut": _book()}, 5)
    assert not s3.check_xcheck(report).passed


def test_xcheck_reads_each_pdf_in_both_modes_after_checking_its_sha(tmp_path):
    pdf = tmp_path / "路得記.pdf"
    pdf.write_bytes(b"%PDF fake")
    book = {**RUT, "pdf_sha256": hashlib.sha256(b"%PDF fake").hexdigest()}
    calls = []

    def fake_run(path, mode):
        calls.append((path.name, mode))
        return _text(PAGE_1, PAGE_2, PAGE_3, PAGE_4)

    report = s3.xcheck(tmp_path, [book], _units(), run=fake_run)
    assert sorted(calls) == [("路得記.pdf", "layout"), ("路得記.pdf", "raw")]
    assert report["units"] == 4 and s3.check_xcheck(report).passed
    assert s3.encode_report(report) == s3.encode_report(report)


def test_xcheck_refuses_a_pdf_that_is_not_the_one_the_layer_came_from(tmp_path):
    (tmp_path / "路得記.pdf").write_bytes(b"other")
    with pytest.raises(s3.XcheckError, match="sha256"):
        s3.xcheck(tmp_path, [{**RUT, "pdf_sha256": "0" * 64}], _units(),
                  run=lambda path, mode: "")


def test_xcheck_refuses_a_missing_pdf(tmp_path):
    with pytest.raises(s3.XcheckError, match="missing"):
        s3.xcheck(tmp_path, [{**RUT, "pdf_sha256": "0" * 64}], _units(),
                  run=lambda path, mode: "")


def test_pdftotext_failure_is_an_error(tmp_path):
    with pytest.raises(s3.XcheckError, match="pdftotext"):
        s3.run_pdftotext(tmp_path / "missing.pdf", "raw")
