"""Text-layer record contracts (design §2.2–2.12, decisions D-03(b), D-04(a)).

Every record that carries wording has ``text_pdf`` (PDF as printed) and
``text`` (serving text, errata applied) of equal length. Ids are validated by
``ragcommon.ids``; each record also checks that its id agrees with the fields
it is derived from (e.g. ``unit_key`` with book/chapter/label).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ragcommon import books, ids
from ragdata.contract.fields import (
    Check, Record, boolean, check_dual_text, hex64, id_of, integer, json_object, list_of, nested,
    number, one_of, optional, parsed, require, sha256_text, spec, string, verse_order,
)

PDF = one_of("pdf_deterministic")
SELAH = "（細拉）"
FOOTNOTE_KINDS = ("alt_rendering", "original", "name_meaning", "variant", "lxx", "gloss", "other")
ERRATA_ID_RE = re.compile(r"er:[0-9]{4}")
ERRATA_CONTAINERS = {
    "unit": "unit", "footnote": "footnote", "heading": "heading",
    "superscription": "superscription", "speaker": "speaker",
}


def errata_id() -> Check:
    """``er:NNNN``; errata ids are not part of the ragcommon grammar (design §2.12)."""
    def check(value):
        require(isinstance(value, str) and ERRATA_ID_RE.fullmatch(value) is not None,
                f"errata id must look like er:0001, got {value!r}")
        return value
    return check


def _pages() -> Check:
    return list_of(integer(1), min_len=1)


def _same_chapter(a: str, b: str, what: str) -> None:
    pa, pb = parsed(a), parsed(b)
    require((pa.book_id, pa.chapter) == (pb.book_id, pb.chapter), f"{what}: {a} vs {b}")


# ------------------------------------------------------------------ books, chapters


@dataclass(frozen=True)
class Book(Record):
    book_id: str = spec(id_of("book"))
    ord: int = spec(integer(1, books.BOOK_COUNT))
    name: str = spec(string())
    name_source: str = spec(one_of("pdf_title_line"))
    file_name: str = spec(string())
    file_name_mismatch: bool = spec(boolean())
    short_names: tuple = spec(list_of(string()))
    name_en: str = spec(string())
    testament: str = spec(one_of("OT", "NT"))
    category: str = spec(one_of(*books.CATEGORIES))
    chapter_count: int = spec(integer(1))
    unit_count: int = spec(integer(1))
    present_slot_count: int = spec(integer(1))
    slot_rows: int = spec(integer(1))
    omitted_count: int = spec(integer(0))
    pdf_sha256: str = spec(hex64())
    provenance_class: str = spec(PDF)
    meta_provenance: str = spec(one_of("curated_metadata"))

    def check(self) -> None:
        require(self.slot_rows == self.present_slot_count + self.omitted_count,
                "slot_rows must equal present_slot_count + omitted_count")
        require(self.file_name_mismatch == (self.file_name != self.name),
                "file_name_mismatch must say whether file_name differs from name")
        require(len(set(self.short_names)) == len(self.short_names), "short_names repeat")


@dataclass(frozen=True)
class Chapter(Record):
    chapter_key: str = spec(id_of("chapter"))
    book_id: str = spec(id_of("book"))
    chapter: int = spec(integer(1))
    unit_count: int = spec(integer(1))
    present_slot_count: int = spec(integer(1))
    slot_rows: int = spec(integer(1))
    max_verse: int = spec(integer(1))
    omitted_slots: tuple = spec(list_of(id_of("slot")))
    has_superscription: bool = spec(boolean())
    book_division_id: str | None = spec(optional(id_of("division")))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        require(self.chapter_key == ids.chapter_key(self.book_id, self.chapter),
                "chapter_key must be {book_id}.{chapter}")
        require(self.slot_rows == self.present_slot_count + len(self.omitted_slots),
                "slot_rows must equal present_slot_count + len(omitted_slots)")
        require(self.slot_rows == self.max_verse, "every verse number 1..max_verse has a slot row")
        require(self.unit_count <= self.present_slot_count, "more units than present slots")
        require(len(set(self.omitted_slots)) == len(self.omitted_slots), "omitted_slots repeat")
        for slot in self.omitted_slots:
            p = parsed(slot)
            require((p.book_id, p.chapter) == (self.book_id, self.chapter),
                    f"omitted slot {slot} lies outside the chapter")
        require(self.book_division_id in (None, ids.division_id(self.chapter_key)),
                "book_division_id must be dv:{chapter_key}")


# ------------------------------------------------------------------ units and slots


@dataclass(frozen=True)
class LineBreak(Record):
    offset: int = spec(integer(1))
    kind: str = spec(one_of("soft", "hard", "indent"))


@dataclass(frozen=True)
class Marker(Record):
    type: str = spec(one_of("selah"))
    start: int = spec(integer(0))
    end: int = spec(integer(1))


@dataclass(frozen=True)
class UnitProv(Record):
    pdf_sha256: str = spec(hex64())
    first_glyph: tuple = spec(list_of(number(), length=3))


@dataclass(frozen=True)
class VerseUnit(Record):
    unit_key: str = spec(id_of("unit"))
    book_id: str = spec(id_of("book"))
    chapter: int = spec(integer(1))
    label: str = spec(string())
    v_start: int = spec(integer(1))
    v_end: int = spec(integer(1))
    ord: int = spec(integer(0))
    text_pdf: str = spec(string())
    text: str = spec(string())
    text_sha256: str = spec(hex64())
    errata_ids: tuple = spec(list_of(errata_id()))
    line_breaks: tuple = spec(list_of(nested(LineBreak)))
    markers: tuple = spec(list_of(nested(Marker)))
    is_poetry: bool = spec(boolean())
    pages: tuple = spec(_pages())
    prov: UnitProv = spec(nested(UnitProv))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        require(self.v_end >= self.v_start, "v_end must not precede v_start")
        label = str(self.v_start) if self.v_end == self.v_start else f"{self.v_start}-{self.v_end}"
        require(self.label == label, f"label must be {label!r}")
        key = ids.unit_key(self.book_id, self.chapter, self.v_start, self.v_end)
        require(self.unit_key == key, f"unit_key must be {key!r}")
        check_dual_text(self.text_pdf, self.text, self.errata_ids)
        require(self.text_sha256 == sha256_text(self.text), "text_sha256 is not sha256(text)")
        offsets = [b.offset for b in self.line_breaks]
        require(offsets == sorted(set(offsets)) and all(o < len(self.text) for o in offsets),
                "line_breaks offsets must ascend inside the text")
        for m in self.markers:
            require(self.text_pdf[m.start:m.end] == SELAH, f"selah marker {m.start}-{m.end} "
                    f"does not cover {SELAH}")


@dataclass(frozen=True)
class VerseSlot(Record):
    slot_key: str = spec(id_of("slot"))
    unit_key: str | None = spec(optional(id_of("unit")))
    status: str = spec(one_of("present", "merged", "omitted_variant"))
    variant_footnote_id: str | None = spec(optional(id_of("footnote")))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        omitted = self.status == "omitted_variant"
        require(omitted == (self.unit_key is None), "only omitted slots have no unit")
        require(omitted == (self.variant_footnote_id is not None),
                "omitted slots (and only they) point at their variant footnote")
        if omitted:
            _same_chapter(self.slot_key, parsed(self.variant_footnote_id).parent.raw,
                          "variant footnote outside the slot's chapter")
            return
        unit, slot = parsed(self.unit_key), parsed(self.slot_key)
        merged = unit.kind == "unit"
        require(merged == (self.status == "merged"), "status must be merged iff the unit is")
        require((unit.book_id, unit.chapter) == (slot.book_id, slot.chapter)
                and unit.verse <= slot.verse <= (unit.verse_end or unit.verse),
                f"slot {self.slot_key} lies outside unit {self.unit_key}")


# ------------------------------------------------------------------ chapter texts, headings


@dataclass(frozen=True)
class ChapterText(Record):
    id: str = spec(string())
    kind: str = spec(one_of("superscription", "book_division"))
    chapter_key: str = spec(id_of("chapter"))
    text_pdf: str = spec(string())
    text: str = spec(string())
    order: str | None = spec(optional(one_of("before_heading", "after_heading", "no_heading")))
    pages: tuple = spec(_pages())
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        superscription = self.kind == "superscription"
        build = ids.superscription_id if superscription else ids.division_id
        require(self.id == build(self.chapter_key), f"id must be {build(self.chapter_key)!r}")
        require(not superscription or self.order is not None, "superscriptions record order")
        check_dual_text(self.text_pdf, self.text)


@dataclass(frozen=True)
class HeadingProv(Record):
    style_class: str = spec(string())
    glyph_range: tuple = spec(list_of(integer(0), length=2))


@dataclass(frozen=True)
class Heading(Record):
    heading_id: str = spec(id_of("heading"))
    book_id: str = spec(id_of("book"))
    anchor_unit_key: str = spec(id_of("unit"))
    anchor_offset: int = spec(integer(0))
    pos: str = spec(one_of("before", "mid"))
    level: int = spec(integer(1, 3))
    parent_heading_id: str | None = spec(optional(id_of("heading")))
    text_pdf: str = spec(string())
    text: str = spec(string())
    display_title: str = spec(string())
    ord: int = spec(integer(0))
    prov: HeadingProv = spec(nested(HeadingProv))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        mid = self.pos == "mid"
        require(mid == (self.anchor_offset > 0), "pos is mid iff anchor_offset > 0")
        key, unit = parsed(self.heading_id).parent, parsed(self.anchor_unit_key)
        require((key.book_id, key.chapter, key.verse, key.half)
                == (unit.book_id, unit.chapter, unit.verse, mid),
                "heading_id must start at the anchor unit (with b when mid)")
        require(self.book_id == unit.book_id, "book_id must match the anchor unit")
        require(self.parent_heading_id != self.heading_id, "a heading cannot be its own parent")
        start, end = self.prov.glyph_range
        require(start <= end, "glyph_range must ascend")
        check_dual_text(self.text_pdf, self.text)


@dataclass(frozen=True)
class SlotRange(Record):
    book_id: str = spec(id_of("book"))
    start_slot: str = spec(id_of("slot"))
    end_slot: str = spec(id_of("slot"))

    def check(self) -> None:
        for slot in (self.start_slot, self.end_slot):
            require(parsed(slot).book_id == self.book_id, f"{slot} is not in {self.book_id}")
        require(verse_order(self.start_slot) <= verse_order(self.end_slot), "range descends")


@dataclass(frozen=True)
class ParallelRef(Record):
    pr_id: str = spec(id_of("parallel_ref"))
    heading_id: str = spec(id_of("heading"))
    raw: str = spec(string())
    seg_idx: int = spec(integer(0))
    kind: str = spec(one_of("parallel", "section_range"))
    targets: tuple = spec(list_of(nested(SlotRange), min_len=1))
    parse_rule: str = spec(string())
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        expected = ids.parallel_ref_id(self.heading_id, self.seg_idx + 1)
        require(self.pr_id == expected, f"pr_id must be {expected!r}")


# ------------------------------------------------------------------ footnotes, speakers


@dataclass(frozen=True)
class Span(Record):
    start: int = spec(integer(0))
    end: int = spec(integer(1))

    def check(self) -> None:
        require(self.start < self.end, "span must not be empty")


@dataclass(frozen=True)
class Footnote(Record):
    fn_id: str = spec(id_of("footnote"))
    unit_key: str = spec(id_of("unit"))
    n: int = spec(integer(1))
    kind: str = spec(one_of(*FOOTNOTE_KINDS))
    anchor: Span | None = spec(optional(nested(Span)))
    text_pdf: str = spec(string())
    text: str = spec(string())
    variant_slot_key: str | None = spec(optional(id_of("slot")))
    refs: tuple = spec(list_of(nested(SlotRange)))
    errata_ids: tuple = spec(list_of(errata_id()))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        expected = ids.footnote_id(self.unit_key, self.n)
        require(self.fn_id == expected, f"fn_id must be {expected!r}")
        check_dual_text(self.text_pdf, self.text, self.errata_ids)
        if self.variant_slot_key is not None:
            require(self.kind == "variant", "only variant footnotes name an omitted slot")
            _same_chapter(self.variant_slot_key, self.unit_key, "variant slot outside chapter")


@dataclass(frozen=True)
class Speaker(Record):
    sk_id: str = spec(id_of("speaker"))
    unit_key: str = spec(id_of("unit"))
    offset: int = spec(integer(0))
    pos: str = spec(one_of("before", "mid"))
    text_pdf: str = spec(string())
    text: str = spec(string())
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        require(parsed(self.sk_id).parent.raw == self.unit_key, "sk_id must be sk:{unit_key}#n")
        require((self.pos == "mid") == (self.offset > 0), "pos is mid iff offset > 0")
        check_dual_text(self.text_pdf, self.text)


# ------------------------------------------------------------------ spans, errata, aliases


@dataclass(frozen=True)
class NameSpan(Record):
    span_id: str = spec(id_of("name_span"))
    container_id: str = spec(string())
    region: str = spec(one_of("body", "footnote"))
    start: int = spec(integer(0))
    end: int = spec(integer(1))
    surface: str = spec(string())
    source: str = spec(one_of("pdf_underline"))
    norm_key: str = spec(string())
    norm_rule_ids: tuple = spec(list_of(string()))
    merge_group: str | None = spec(optional(id_of("merge_group")))
    provenance_class: str = spec(one_of("pdf_deterministic", "pdf_rule"))

    def check(self) -> None:
        expected = ids.name_span_id(self.container_id, self.start)
        require(self.span_id == expected, f"span_id must be {expected!r}")
        require(self.end - self.start == len(self.surface), "end - start must equal len(surface)")
        kinds = {"body": ("slot", "unit"), "footnote": ("footnote",)}[self.region]
        require(parsed(self.container_id).kind in kinds,
                f"a {self.region} span must sit in a {'/'.join(kinds)}")


@dataclass(frozen=True)
class ErrataApplied(Record):
    errata_id: str = spec(errata_id())
    container_id: str = spec(string())
    container_kind: str = spec(one_of(*ERRATA_CONTAINERS))
    offset: int = spec(integer(0))
    pdf_char: str = spec(string())
    corrected_char: str = spec(string())
    class_: str = spec(string(), key="class")
    evidence: object = spec(json_object())
    decided_by: str = spec(string())
    provenance_class: str = spec(one_of("curated_human"))

    def check(self) -> None:
        require(ids.is_valid(self.container_id, ERRATA_CONTAINERS[self.container_kind]),
                f"container_id is not a {self.container_kind} id")
        require(len(self.pdf_char) == 1 and len(self.corrected_char) == 1,
                "errata replace exactly one character")
        require(self.pdf_char != self.corrected_char, "errata must change the character")


@dataclass(frozen=True)
class RefAlias(Record):
    external_ref: str = spec(id_of("slot"))
    relation: str = spec(one_of("contained_in"))
    target: str = spec(id_of("slot"))
    note: str = spec(string())
    provenance_class: str = spec(one_of("external_reference"))

    def check(self) -> None:
        require(self.external_ref != self.target, "an alias cannot point at itself")
