"""S1: unclipped per-glyph extraction with mutool, and validation of its rows."""

from __future__ import annotations

from pathlib import Path

import pytest

import pdf_lines as pl
from ragdata.stages import s01_extract as s1
from ragdata.store import decode_jsonl, encode_jsonl

REPO = Path(__file__).resolve().parents[2]
RUTH = REPO / "bible_pdf" / "路得記.pdf"
EZRA = REPO / "bible_pdf" / "以斯拉記.pdf"


def _rows():
    return [pl.page(1), pl.verse(1, 186.2, "1", "當士師秉政的時候"), pl.stroke(1, 106.7, 130.6, 204.6),
            pl.page(2), pl.body(2, 100.0, "國中遭遇饑荒")]


def test_load_types_pages_lines_and_strokes():
    book = s1.load_s1(encode_jsonl(_rows()), "mini")
    assert book.pages == {1: (0, 0, 419.53, 595.28), 2: (0, 0, 419.53, 595.28)}
    assert [ln.page for ln in book.lines] == [1, 2]
    assert book.lines[0].runs[0].text == "1"
    assert book.strokes[0].page == 1 and book.strokes[0].lw == 0.3985
    assert book.strokes[0].path == (("m", 106.7, 204.6), ("l", 130.6, 204.6))


def test_glyphs_are_numbered_in_file_order_across_lines_and_pages():
    book = s1.load_s1(encode_jsonl(_rows()), "mini")
    seqs = [g.seq for ln in book.lines for g in ln.glyphs]
    assert seqs == list(range(len(seqs)))
    assert book.lines[1].glyphs[0].seq == len(book.lines[0].glyphs)


@pytest.mark.parametrize("mutate, message", [
    (lambda rows: rows.pop(0), "page row"),
    (lambda rows: rows[3].update(p=3), "page 3"),
    (lambda rows: rows[1].update(p=2), "page 2"),
    (lambda rows: rows[1].update(chars=[]), "chars"),
    (lambda rows: rows[1]["chars"][0].pop(), "char"),
    (lambda rows: rows[1]["chars"][0].__setitem__(0, "ab"), "char"),
    (lambda rows: rows[1]["chars"][0].__setitem__(6, "navy"), "char"),
    (lambda rows: rows[1]["chars"][0].__setitem__(1, "1"), "char"),
    (lambda rows: rows[2].update(path=[["q", 1, 2]]), "path"),
    (lambda rows: rows[2].update(lw=0), "lw"),
    (lambda rows: rows[2].update(extra=1), "keys"),
    (lambda rows: rows.append({"k": "image", "p": 2}), "kind"),
    (lambda rows: rows[0].update(bounds=[0, 0, 1]), "bounds"),
], ids=["no-first-page", "page-skips", "line-on-other-page", "empty-line", "short-char",
        "two-codepoints", "bad-colour", "string-coordinate", "bad-path-op", "zero-width",
        "extra-key", "unknown-kind", "short-bounds"])
def test_malformed_rows_are_rejected(mutate, message):
    rows = _rows()
    mutate(rows)
    with pytest.raises(s1.ExtractError, match=message):
        s1.load_s1(encode_jsonl(rows), "mini")


def test_non_json_output_is_rejected():
    with pytest.raises(s1.ExtractError, match="mini"):
        s1.load_s1(b'{"k":"page"\n', "mini")


def test_ruth_extracts_deterministically_into_canonical_rows():
    first, book = s1.extract_pdf(RUTH)
    second, _ = s1.extract_pdf(RUTH)
    assert first == second
    assert encode_jsonl(decode_jsonl(first, "rut")) == first
    assert len(book.pages) == 8 and len(book.lines) == 247
    assert {s.lw for s in book.strokes} == {0.3985}


def test_glyphs_typeset_past_the_page_edge_are_kept():
    _, book = s1.extract_pdf(EZRA)
    assert s1.overflow_glyphs(book) == 123


def test_a_file_mutool_cannot_open_is_an_extract_error(tmp_path):
    bogus = tmp_path / "bogus.pdf"
    bogus.write_bytes(b"not a pdf")
    with pytest.raises(s1.ExtractError, match="bogus.pdf"):
        s1.extract_pdf(bogus)


def test_extract_all_keys_results_by_book(tmp_path):
    results = s1.extract_all({"rut": RUTH}, workers=2)
    assert list(results) == ["rut"] and results["rut"][0] == s1.extract_pdf(RUTH)[0]


def test_tool_versions_are_read_from_the_tools():
    assert s1.mutool_version().count(".") == 2
