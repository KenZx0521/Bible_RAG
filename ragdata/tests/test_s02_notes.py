"""S2b footnote records: kind, in-verse anchor, cross-references and variant slots."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.contract import parse_record
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import notes, stream, units


@pytest.mark.parametrize("text, kind", [
    ("或譯：是銅匠鐵匠的祖師", "alt_rendering"), ("得：或譯成", "alt_rendering"),
    ("原文是我", "original"), ("就是得的意思", "name_meaning"),
    ("有古卷加：11人子來，為要拯救失喪的人。", "variant"), ("有古卷無此節", "variant"),
    ("又名約雅斤", "other"), ("七十士譯本是以色列", "other"),
])
def test_the_kind_follows_the_marker_the_note_prints(text, kind):
    assert notes.note_kind(text, "t") == kind


def test_a_note_with_two_kind_markers_is_a_parse_error():
    with pytest.raises(ParseError, match="kinds"):
        notes.note_kind("或譯：原文是我", "fn:gen.1.1#1")


@pytest.mark.parametrize("text, verse, anchor", [
    ("得：或譯成", "我們也在他裏面得了基業", {"start": 7, "end": 8}),
    ("得孩子：原文是被建立", "或者我可以因她得孩子", {"start": 7, "end": 10}),
    ("民：原文是產業", "直等到上帝的產業被贖", None),
    ("方：原文是風", "四方四方", None),
    ("原文是我", "我觀看", None),
    ("你們……我：原文是", "你們要聽從我", {"start": 0, "end": 6}),
    ("你們……他：原文是", "你們要聽從我", None),
], ids=["unique", "word", "absent", "repeated", "no-lemma", "ellipsis", "ellipsis-absent"])
def test_a_lemma_found_once_in_the_verse_anchors_the_note(text, verse, anchor):
    assert notes.lemma_anchor(text, verse) == anchor


@pytest.mark.parametrize("text, book, refs", [
    ("在歷代上三章一節作但以利", "2sa", [("1ch.3.1", "1ch.3.1")]),
    ("在創世記第四十六章十三節是約伯", "1ch", [("gen.46.13", "gen.46.13")]),
    ("見二十九章十節", "ezk", [("ezk.29.10", "ezk.29.10")]),
    ("約翰在馬太十六章十七節稱約拿", "jhn", [("mat.16.17", "mat.16.17")]),
    ("原文是血；本章同", "lev", []),
    ("原文是割陽皮；十四、二十三節同", "gen", []),
])
def test_chapter_and_verse_references_resolve_to_slot_ranges(text, book, refs):
    found = notes.note_refs(text, book, "t")
    assert [(r["start_slot"], r["end_slot"]) for r in found] == refs


def test_a_reference_to_no_verse_is_a_parse_error():
    with pytest.raises(ParseError, match="fn:ezk.30.6#1"):
        notes.note_refs("見九十九章十節", "ezk", "fn:ezk.30.6#1")


def _book(*lines):
    rows = [pl.line(1, 60.0, (pl.TITLE, "馬太福音", 182.9)), *lines, *pl.colophon_page(9)]
    s = stream.parse_rows(layout.rows_of(pl.s1_lines(rows)), "mat")
    return units.build_book(s, "mat", "馬太福音", "ab" * 32, 1)


def _note(y, ref, *runs):
    return pl.line(1, y, (pl.NOTE_REF, f"{ref}:", 70.0), *runs)


def test_footnote_rows_link_variants_to_their_omitted_slot():
    rec = _book(pl.verse(1, 100, "1", "你們要小心"), pl.verse(1, 120, "3", "一個人若有一百隻羊"),
                _note(500, "1:1", (pl.NOTE, " 有古卷加：", 95.0), (pl.VNUM, "2", 150.0),
                      (pl.NOTE, "人子來", 160.0)),
                _note(510, "1:1", (pl.NOTE, " 小：原文是微小", 95.0)))
    rows = notes.footnote_rows("mat", rec.footnotes, rec.units, rec.slots)
    for row in rows:
        parse_record("footnotes", row)
    assert [(r["fn_id"], r["n"], r["kind"], r["variant_slot_key"], r["anchor"], r["text_pdf"])
            for r in rows] == [
        ("fn:mat.1.1#1", 1, "variant", "mat.1.2", None, "有古卷加：2人子來"),
        ("fn:mat.1.1#2", 2, "original", None, {"start": 3, "end": 4}, "小：原文是微小")]
