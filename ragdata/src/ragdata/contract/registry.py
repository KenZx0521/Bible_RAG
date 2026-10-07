"""Which record types make up each layer, their files and primary keys."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ragdata.contract import struct, text
from ragdata.contract.fields import Record, parse

LAYERS = ("text", "struct")
# non-record files a layer's build writes beside its records (S3, S4 and the diff reports)
XCHECK_REPORT = "xcheck_report.json"
OVERLAY_REPORT = "overlay_report.json"
DIFF_MD_REPORT = "diff_vs_bible_md.tsv"
DIFF_CANONICAL_REPORT = "diff_vs_canonical_full.tsv"
DIFF_SUMMARY_REPORT = "diff_summary.json"
LAYER_REPORTS = {"text": (XCHECK_REPORT, OVERLAY_REPORT, DIFF_MD_REPORT, DIFF_CANONICAL_REPORT,
                          DIFF_SUMMARY_REPORT), "struct": ()}


@dataclass(frozen=True)
class RecordType:
    name: str
    layer: str
    cls: type[Record]
    pk: str

    @property
    def file_name(self) -> str:
        return f"{self.name}.jsonl"


RECORD_TYPES = tuple(RecordType(*row) for row in (
    ("books", "text", text.Book, "book_id"),
    ("chapters", "text", text.Chapter, "chapter_key"),
    ("verse_units", "text", text.VerseUnit, "unit_key"),
    ("verse_slots", "text", text.VerseSlot, "slot_key"),
    ("chapter_texts", "text", text.ChapterText, "id"),
    ("headings", "text", text.Heading, "heading_id"),
    ("parallel_refs", "text", text.ParallelRef, "pr_id"),
    ("footnotes", "text", text.Footnote, "fn_id"),
    ("speakers", "text", text.Speaker, "sk_id"),
    ("name_spans", "text", text.NameSpan, "span_id"),
    ("errata_applied", "text", text.ErrataApplied, "errata_id"),
    ("ref_aliases", "text", text.RefAlias, "external_ref"),
    ("pericopes", "struct", struct.Pericope, "pericope_id"),
    ("passages", "struct", struct.Passage, "passage_id"),
    ("chunks", "struct", struct.Chunk, "chunk_id"),
))
_BY_NAME = MappingProxyType({t.name: t for t in RECORD_TYPES})
_BY_FILE = MappingProxyType({t.file_name: t for t in RECORD_TYPES})


def record_type(name: str) -> RecordType:
    if name not in _BY_NAME:
        raise KeyError(f"unknown record type {name!r}")
    return _BY_NAME[name]


def record_type_for_file(file_name: str) -> RecordType | None:
    return _BY_FILE.get(file_name)


def layer_types(layer: str) -> tuple[RecordType, ...]:
    if layer not in LAYERS:
        raise KeyError(f"unknown layer {layer!r}")
    return tuple(t for t in RECORD_TYPES if t.layer == layer)


def parse_record(type_name: str, raw: Any) -> Record:
    """Validate one JSON row against its record contract; raise ContractError."""
    return parse(record_type(type_name).cls, raw)


def primary_key(record: Record, type_name: str) -> str:
    return getattr(record, record_type(type_name).pk)
