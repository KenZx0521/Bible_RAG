"""Text-layer record contracts (design §2.2–2.12): valid rows parse, broken rows raise."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.contract import ContractError, layer_types, parse_record, record_to_dict

TEXT = mini_build.text_layer()


def test_text_layer_declares_the_twelve_record_types():
    names = {t.name for t in layer_types("text")}
    assert names == {
        "books", "chapters", "verse_units", "verse_slots", "chapter_texts", "headings",
        "parallel_refs", "footnotes", "speakers", "name_spans", "errata_applied", "ref_aliases",
    }


@pytest.mark.parametrize("type_name", sorted(TEXT))
def test_every_mini_row_parses_and_round_trips(type_name):
    for raw in TEXT[type_name]:
        record = parse_record(type_name, raw)
        assert record_to_dict(record) == raw


def test_parsed_records_are_immutable():
    unit = parse_record("verse_units", TEXT["verse_units"][0])
    with pytest.raises(AttributeError):
        unit.text = "x"
    assert isinstance(unit.line_breaks, tuple)


def _row(type_name: str, key: str) -> dict:
    pk = {t.name: t.pk for t in layer_types("text")}[type_name]
    rows = [r for r in mini_build.text_layer()[type_name] if r[pk] == key]
    assert len(rows) == 1, key
    return rows[0]


def _with(type_name, key, **changes):
    row = _row(type_name, key)
    row.update(changes)
    return type_name, row


def _without(type_name, key, field):
    row = _row(type_name, key)
    del row[field]
    return type_name, row


BROKEN = {
    "unknown field": _with("verse_units", "act.9.1", extra=1),
    "missing field": _without("verse_units", "act.9.1", "text_sha256"),
    "bool as int": _with("verse_units", "act.9.1", chapter=True),
    "unknown book": _with("verse_units", "act.9.1", unit_key="xyz.9.1", book_id="xyz"),
    "label disagrees with key": _with("verse_units", "eph.6.2-3", label="2"),
    "key disagrees with range": _with("verse_units", "eph.6.2-3", v_end=4),
    "text length differs": _with("verse_units", "act.9.1", text="掃羅"),
    "stale text sha": _with("verse_units", "act.9.1", text_sha256="0" * 64),
    "text differs without errata": _with("verse_units", "act.9.3", errata_ids=[]),
    "selah marker off target": _with(
        "verse_units", "psa.42.2", markers=[{"type": "selah", "start": 0, "end": 4}]),
    "line break past end": _with(
        "verse_units", "act.9.1", line_breaks=[{"offset": 99, "kind": "soft"}]),
    "unknown line break kind": _with(
        "verse_units", "act.9.1", line_breaks=[{"offset": 3, "kind": "wrap"}]),
    "wrong provenance": _with("verse_units", "act.9.1", provenance_class="external_reference"),
    "omitted slot with unit": _with("verse_slots", "mat.18.3", unit_key="mat.18.2"),
    "omitted slot without footnote": _with("verse_slots", "mat.18.3", variant_footnote_id=None),
    "present slot with footnote": _with("verse_slots", "act.9.1",
                                        variant_footnote_id="fn:act.9.1#1"),
    "present slot on other unit": _with("verse_slots", "act.9.1", unit_key="act.9.2"),
    "merged slot outside unit": _with("verse_slots", "eph.6.4", unit_key="eph.6.2-3",
                                      status="merged"),
    "merged status on single unit": _with("verse_slots", "act.9.1", status="merged"),
    "chapter slot rows": _with("chapters", "mat.18", slot_rows=3),
    "chapter max verse": _with("chapters", "mat.18", max_verse=5),
    "chapter key": _with("chapters", "mat.18", chapter=17),
    "omitted slot of other chapter": _with("chapters", "mat.18", omitted_slots=["mat.17.3"]),
    "division of other chapter": _with("chapters", "psa.42", book_division_id="dv:psa.41"),
    "book slot rows": _with("books", "mat", slot_rows=3),
    "book file name flag": _with("books", "mat", file_name_mismatch=True),
    "book testament": _with("books", "mat", testament="AT"),
    "superscription id kind": _with("chapter_texts", "sp:psa.42", kind="book_division"),
    "superscription without order": _with("chapter_texts", "sp:psa.42", order=None),
    "chapter text of other chapter": _with("chapter_texts", "sp:psa.42", chapter_key="psa.41"),
    "before heading with offset": _with("headings", "hd:psa.42.1#1", anchor_offset=3),
    "mid heading id without b": _with("headings", "hd:act.9.3b#1", heading_id="hd:act.9.3#1"),
    "heading anchored elsewhere": _with("headings", "hd:psa.42.1#1", anchor_unit_key="psa.42.2"),
    "heading is own parent": _with("headings", "hd:act.9.1#2", parent_heading_id="hd:act.9.1#2"),
    "parallel seq off by one": _with("parallel_refs", "pr:hd:mat.18.1#1#1", seg_idx=1),
    "parallel of other heading": _with("parallel_refs", "pr:hd:mat.18.1#1#1",
                                       heading_id="hd:eph.6.1#1"),
    "parallel without targets": _with("parallel_refs", "pr:hd:mat.18.1#1#1", targets=[]),
    "parallel target descends": _with("parallel_refs", "pr:hd:mat.18.1#1#1", targets=[
        {"book_id": "act", "start_slot": "act.9.2", "end_slot": "act.9.1"}]),
    "parallel target crosses books": _with("parallel_refs", "pr:hd:mat.18.1#1#1", targets=[
        {"book_id": "act", "start_slot": "act.9.1", "end_slot": "eph.6.1"}]),
    "parallel kind": _with("parallel_refs", "pr:hd:mat.18.1#1#1", kind="xref"),
    "footnote n": _with("footnotes", "fn:mat.18.2#1", n=2),
    "footnote unit": _with("footnotes", "fn:mat.18.2#1", unit_key="mat.18.1"),
    "variant slot on non-variant": _with("footnotes", "fn:eph.6.1#1", variant_slot_key="eph.6.2"),
    "variant slot of other chapter": _with("footnotes", "fn:mat.18.2#1",
                                           variant_slot_key="mat.17.3"),
    "empty footnote anchor": _with("footnotes", "fn:act.9.1#1", anchor={"start": 2, "end": 2}),
    "footnote kind": _with("footnotes", "fn:act.9.1#1", kind="note"),
    "speaker of other unit": _with("speakers", "sk:sng.1.1#1", unit_key="sng.1.2"),
    "mid speaker at zero": _with("speakers", "sk:sng.1.1#1", pos="mid"),
    "span length": _with("name_spans", "ns:act.9.1@0", end=3),
    "span id start": _with("name_spans", "ns:act.9.1@0", start=1, end=3),
    "footnote span in unit": _with("name_spans", "ns:act.9.1@0", region="footnote"),
    "span source": _with("name_spans", "ns:act.9.1@0", source="lexicon"),
    "errata container kind": _with("errata_applied", "er:0001", container_kind="footnote"),
    "errata no-op": _with("errata_applied", "er:0001", corrected_char="詵"),
    "errata two chars": _with("errata_applied", "er:0001", pdf_char="詵詵"),
    "errata id": _with("errata_applied", "er:0001", errata_id="er:1"),
    "alias to itself": _with("ref_aliases", "mat.18.5", target="mat.18.5"),
    "alias relation": _with("ref_aliases", "mat.18.5", relation="same_as"),
    "alias provenance": _with("ref_aliases", "mat.18.5", provenance_class="pdf_deterministic"),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_rows_raise_contract_error(case):
    type_name, raw = BROKEN[case]
    with pytest.raises(ContractError):
        parse_record(type_name, raw)


def test_non_mapping_row_is_rejected():
    with pytest.raises(ContractError):
        parse_record("verse_units", ["not", "a", "row"])


def test_unknown_record_type_is_rejected():
    with pytest.raises(KeyError):
        parse_record("verses", {})


def test_error_names_the_offending_field():
    type_name, raw = BROKEN["unknown line break kind"]
    with pytest.raises(ContractError, match="line_breaks"):
        parse_record(type_name, raw)
