"""S0: discovering the PDFs, the source manifest, and the G-SRC / G-TOOL gates."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

import pdf_lines as pl
from ragdata.stages import layout, s00_source as s0
from ragdata.stages import s01_extract as s1

REPO = Path(__file__).resolve().parents[2]
PDF_DIR = REPO / "bible_pdf"
UUID = "c03bb35c-f042-59c2-88d7-1111d9a01842"


def _link(tmp_path, *names):
    for name in names:
        (tmp_path / name).symlink_to(PDF_DIR / name)
    return tmp_path


def test_discover_maps_file_names_to_books_in_canonical_order(tmp_path):
    pdfs = s0.discover(_link(tmp_path, "約拿書.pdf", "路得記.pdf", "尼西米記.pdf"))
    assert [p.book_id for p in pdfs] == ["rut", "neh", "jon"]
    assert pdfs[1].file == "尼西米記.pdf" and len(pdfs[1].sha256) == 64


@pytest.mark.parametrize("names, message", [((), "no PDF"), (("x.pdf",), "x.pdf")])
def test_discover_refuses_an_empty_dir_or_an_unknown_file(tmp_path, names, message):
    for name in names:
        (tmp_path / name).write_bytes(b"%PDF")
    with pytest.raises(s0.SourceError, match=message):
        s0.discover(tmp_path)


@pytest.fixture(scope="module")
def ruth_and_nehemiah(tmp_path_factory):
    pdf_dir = _link(tmp_path_factory.mktemp("pdf"), "路得記.pdf", "尼西米記.pdf")
    pdfs = s0.discover(pdf_dir)
    books = {p.book_id: s1.extract_pdf(p.path)[1] for p in pdfs}
    return pdfs, books, s0.build_manifest(pdfs, books, s0.toolchain())


def test_manifest_describes_each_pdf_from_its_own_pages(ruth_and_nehemiah):
    _, _, manifest = ruth_and_nehemiah
    rut, neh = manifest["pdfs"]
    assert (rut["book_title_line"], rut["pages"], rut["file_name_mismatch"]) == ("路得記", 8, False)
    assert rut["header_names"] == ["路得記"] and rut["strokes"] == 162
    assert rut["colophon_text"].startswith("新標點和合本 / Chinese Union Version (traditional) / ")
    assert (neh["file"], neh["book_title_line"], neh["file_name_mismatch"]) == \
        ("尼西米記.pdf", "尼希米記", True)
    assert manifest["ebible_uuid"] == UUID
    detection = manifest["edition_detection"]
    assert detection["verdict"] == "RCUV" and detection["markers"]["撒馬利亞"] > 0
    assert all(detection["markers"][cunp] == 0 for _, cunp in s0.EDITION_MARKERS)
    assert manifest["toolchain"]["mutool"] == s1.mutool_version()


def test_manifest_bytes_are_canonical(ruth_and_nehemiah):
    pdfs, books, manifest = ruth_and_nehemiah
    again = s0.build_manifest(pdfs, books, s0.toolchain())
    assert s0.encode_manifest(manifest) == s0.encode_manifest(again)


def _rows(*lines):
    return layout.rows_of(layout.to_line(r["p"], r["chars"]) for r in lines)


def test_edition_markers_count_the_text_outside_headers_and_colophon():
    rows = _rows(pl.line(1, 82.8, (pl.HEADER, "呂便", 70.0)), pl.verse(1, 100.0, "1", "呂"),
                 pl.body(1, 114.0, "便和塞魯士"), *[r for r in pl.colophon_page(2) if r["k"] == "line"])
    markers = s0.edition_markers({"rut": rows})
    assert markers["呂便"] == 1 and markers["塞魯士"] == 1 and markers["流便"] == 0


def _expect(manifest):
    return {
        "toolchain": {k: manifest["toolchain"][k] for k in ("mutool", "pdftotext")},
        "ebible_uuid": UUID,
        "pdfs": {p["file"]: p["sha256"] for p in manifest["pdfs"]},
        "edition_markers": dict(manifest["edition_detection"]["markers"]),
        "pages": 8 + manifest["pdfs"][1]["pages"],
        "overflow_glyphs": sum(p["overflow_glyphs"] for p in manifest["pdfs"]),
        "strokes": sum(p["strokes"] for p in manifest["pdfs"]),
        "style_groups": dict(manifest["style_fingerprint"]["char_counts"]),
    }


def test_g_src_passes_when_everything_matches(ruth_and_nehemiah):
    manifest = ruth_and_nehemiah[2]
    result = s0.check_source(manifest, _expect(manifest))
    assert result.name == "G-SRC" and result.passed, result.details


@pytest.mark.parametrize("break_it, detail", [
    (lambda m, e: m["pdfs"][0].update(sha256="0" * 64), "sha256"),
    (lambda m, e: e["pdfs"].update({"約拿書.pdf": "1" * 64}), "missing"),
    (lambda m, e: m["pdfs"][0].update(book_title_line="路得"), "title"),
    (lambda m, e: m["pdfs"][0].update(colophon_text="新標點和合本"), "colophon"),
    (lambda m, e: e["edition_markers"].update({"呂便": 1}), "呂便"),
    (lambda m, e: m["edition_detection"].update(verdict="unknown"), "verdict"),
    (lambda m, e: e.update(overflow_glyphs=0), "overflow_glyphs"),
    (lambda m, e: e["style_groups"].popitem(), "style group"),
    (lambda m, e: e.update(ebible_uuid="x"), "ebible_uuid"),
])
def test_g_src_turns_red_on_any_difference(ruth_and_nehemiah, break_it, detail):
    manifest = copy.deepcopy(ruth_and_nehemiah[2])
    expect = _expect(manifest)
    break_it(manifest, expect)
    result = s0.check_source(manifest, expect)
    assert not result.passed and any(detail in d for d in result.details), result.details


def test_g_tool_checks_the_pinned_versions(ruth_and_nehemiah):
    manifest = ruth_and_nehemiah[2]
    expect = _expect(manifest)
    assert s0.check_tools(manifest["toolchain"], expect).passed
    expect["toolchain"]["mutool"] = "0.0.1"
    result = s0.check_tools(manifest["toolchain"], expect)
    assert result.name == "G-TOOL" and not result.passed and "mutool" in result.details[0]


def test_the_shipped_expectations_load_and_pin_all_66_pdfs():
    expect = s0.load_expect()
    assert len(expect["pdfs"]) == 66 and expect["pages"] == 2543
    assert expect["overflow_glyphs"] == 852 and expect["strokes"] == 33599
    assert expect["edition_markers"]["流便"] == 0 and len(expect["style_groups"]) == 19
    assert expect["conserve"] == {"body": 1059384, "navy": 27568, "footnote": 13463, "division": 32}


@pytest.mark.parametrize("doc", [{}, {"schema": "nope"}, {"schema": s0.EXPECT_SCHEMA}],
                         ids=["empty", "wrong-schema", "missing-keys"])
def test_malformed_expectations_are_a_source_error(tmp_path, doc):
    path = tmp_path / "expect.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(s0.SourceError):
        s0.load_expect(path)

