"""G-REFINT: every reference resolves, and references agree with what they point at."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_refint, check_schema

BOTH = ("text", "struct")


def _refint(files, layer):
    schema, snap = check_schema(files, BOTH if layer == "struct" else ("text",))
    assert schema.passed, schema.details  # each case below breaks references only
    return check_refint(snap, layer)


@pytest.mark.parametrize("layer", BOTH)
def test_mini_snapshot_is_referentially_sound(layer):
    result = _refint(mini_build.files(*BOTH), layer)
    assert result.passed, result.details
    assert (result.name, result.hard) == ("G-REFINT", True)


def test_struct_without_its_text_layer_is_red():
    _, snap = check_schema(mini_build.files("struct"), ("struct",))
    assert not check_refint(snap, "struct").passed


def _row(files, type_name, pk_field, key):
    return next(r for r in files[f"{type_name}.jsonl"] if r[pk_field] == key)


def _drop(files, type_name, pk_field, key):
    files[f"{type_name}.jsonl"] = [r for r in files[f"{type_name}.jsonl"] if r[pk_field] != key]


def _set(type_name, pk_field, key, **changes):
    return lambda f: _row(f, type_name, pk_field, key).update(changes)


def _unit_text(f, key, text):
    _row(f, "verse_units", "unit_key", key).update(
        text_pdf=text, text=text, text_sha256=mini_build.sha(text), line_breaks=[])


TEXT_CASES = {
    "slot to a unit that does not exist": (
        _set("verse_slots", "slot_key", "eph.6.3", unit_key="eph.6.3-4"), "eph.6.3-4"),
    "merged unit missing one of its slots": (
        lambda f: _drop(f, "verse_slots", "slot_key", "eph.6.3"), "eph.6.2-3"),
    "chapter grid with a hole": (
        lambda f: _drop(f, "verse_slots", "slot_key", "mat.18.3"), "mat.18"),
    "variant footnote forgets its slot": (
        _set("footnotes", "fn_id", "fn:mat.18.2#1", variant_slot_key=None), "mat.18.3"),
    "variant footnote names a present slot": (
        _set("footnotes", "fn_id", "fn:mat.18.2#1", variant_slot_key="mat.18.4"), "mat.18.4"),
    "omitted slot names another footnote": (
        _set("verse_slots", "slot_key", "mat.18.3", variant_footnote_id="fn:mat.18.1#1"),
        "fn:mat.18.1#1"),
    "chapter unit count": (_set("chapters", "chapter_key", "mat.18", unit_count=2), "unit_count"),
    "chapter superscription flag": (
        _set("chapters", "chapter_key", "mat.18", has_superscription=True), "has_superscription"),
    "chapter division missing": (
        lambda f: _drop(f, "chapter_texts", "id", "dv:psa.42"), "dv:psa.42"),
    "book chapter count": (_set("books", "book_id", "act", chapter_count=1), "chapter_count"),
    "book of a chapter missing": (lambda f: _drop(f, "books", "book_id", "sng"), "sng"),
    "unit in a missing chapter": (lambda f: _drop(f, "chapters", "chapter_key", "act.10"), "act.10"),
    "heading anchored to a missing unit": (
        lambda f: _drop(f, "verse_units", "unit_key", "psa.42.1"), "psa.42.1"),
    "heading parent missing": (
        _set("headings", "heading_id", "hd:act.9.1#2", parent_heading_id="hd:act.9.1#3"),
        "hd:act.9.1#3"),
    "parallel ref of a missing heading": (
        lambda f: _drop(f, "headings", "heading_id", "hd:mat.18.1#1"), "hd:mat.18.1#1"),
    "parallel target past the chapter": (
        _set("parallel_refs", "pr_id", "pr:hd:mat.18.1#1#1",
             targets=[{"book_id": "act", "start_slot": "act.9.1", "end_slot": "act.9.9"}]),
        "act.9.9"),
    "mid heading beyond its unit": (
        _set("headings", "heading_id", "hd:act.9.3b#1", anchor_offset=99), "anchor_offset"),
    "footnote anchor beyond its unit": (
        _set("footnotes", "fn_id", "fn:act.9.1#1", anchor={"start": 40, "end": 42}), "anchor"),
    "speaker beyond its unit": (
        _set("speakers", "sk_id", "sk:sng.1.1#1", offset=30, pos="mid"), "offset"),
    "span surface differs from the text": (
        _set("name_spans", "span_id", "ns:act.9.1@0", surface="大衛", norm_key="大衛"), "大衛"),
    "span in a missing container": (
        lambda f: _drop(f, "footnotes", "fn_id", "fn:act.9.1#1"), "fn:act.9.1#1"),
    "span outside its container": (
        lambda f: _unit_text(f, "act.9.1", "掃"), "ns:act.9.1@0"),
    "errata offset off target": (_set("errata_applied", "errata_id", "er:0001", offset=0), "er:0001"),
    "errata row missing": (lambda f: _drop(f, "errata_applied", "errata_id", "er:0002"), "er:0002"),
    "errata listed by the wrong container": (
        _set("errata_applied", "errata_id", "er:0001", container_id="act.9.2"), "er:0001"),
    "alias target missing": (_set("ref_aliases", "external_ref", "mat.18.5", target="mat.18.9"),
                             "mat.18.9"),
    "alias shadows a real slot": (
        _set("ref_aliases", "external_ref", "mat.18.5", external_ref="mat.18.1"), "mat.18.1"),
    "alias onto an omitted slot": (
        _set("ref_aliases", "external_ref", "mat.18.5", target="mat.18.3"), "mat.18.3"),
}


@pytest.mark.parametrize("case", sorted(TEXT_CASES))
def test_broken_text_references_are_red(case):
    mutate, needle = TEXT_CASES[case]
    files = mini_build.files(*BOTH)
    mutate(files)
    result = _refint(files, "text")
    assert not result.passed
    assert any(needle in d for d in result.details), result.details


STRUCT_CASES = {
    "pericope lists a missing passage": (
        lambda f: _drop(f, "passages", "passage_id", "ps:act.10.1"), "ps:act.10.1"),
    "passage of a missing pericope": (
        _set("passages", "passage_id", "ps:eph.6.1", pericope_id="pc:eph.6.9"), "pc:eph.6.9"),
    "passage order disagrees with pericope": (
        _set("pericopes", "pericope_id", "pc:act.9.3b",
             passage_ids=["ps:act.10.1", "ps:act.9.3b"]), "pc:act.9.3b"),
    "seg_count disagrees with pericope": (
        _set("passages", "passage_id", "ps:eph.6.1", seg_count=2), "seg_count"),
    "next without matching prev": (
        _set("pericopes", "pericope_id", "pc:act.9.3b", prev_id=None), "prev_id"),
    "pericope heading missing": (
        lambda f: _drop(f, "headings", "heading_id", "hd:psa.42.1#1"), "hd:psa.42.1#1"),
    "chunk of a missing passage": (
        lambda f: [c.update(passage_id="ps:act.9.2") for c in f["chunks.jsonl"]], "ps:act.9.2"),
    "chunk refers to a missing unit": (
        _set("chunks", "chunk_id", "ck:act.9.2~act.9.3", overlap_unit_keys=["act.9.5"]),
        "act.9.5"),
    "passage superscription missing": (
        lambda f: _drop(f, "chapter_texts", "id", "sp:psa.42"), "sp:psa.42"),
    "continued passage drops the title": (
        _set("passages", "passage_id", "ps:act.10.1", title="別的標題"), "title"),
    "next book missing": (_set("pericopes", "pericope_id", "pc:psa.42.1", next_book_id="gen"),
                          "gen"),
}


@pytest.mark.parametrize("case", sorted(STRUCT_CASES))
def test_broken_struct_references_are_red(case):
    mutate, needle = STRUCT_CASES[case]
    files = mini_build.files(*BOTH)
    mutate(files)
    result = _refint(files, "struct")
    assert not result.passed
    assert any(needle in d for d in result.details), result.details
