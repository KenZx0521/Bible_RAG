"""Which record types make up each layer, their files and primary keys."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ragdata.contract import emb, kg, struct, text
from ragdata.contract.fields import Record, parse

LAYERS = ("text", "struct", "emb", "kg0", "events", "route")
# non-record files a layer's build writes beside its records (S3, S4 and the diff reports)
XCHECK_REPORT = "xcheck_report.json"
OVERLAY_REPORT = "overlay_report.json"
DIFF_MD_REPORT = "diff_vs_bible_md.tsv"
DIFF_CANONICAL_REPORT = "diff_vs_canonical_full.tsv"
DIFF_SUMMARY_REPORT = "diff_summary.json"
STRUCT_REPORT = "struct_report.json"
EMB_REPORT = "emb_report.json"                  # template declaration and counts (S6)
ENCODER_FINGERPRINT = "encoder_fingerprint.json"  # BGE-M3 and reranker fingerprints (S7)
KG0_REPORT = "kg0_report.json"
EVENT_REGISTRY_V2 = "event_registry_v2.json"   # the event contract file (design §2.21)
EVENTS_REPORT = "events_report.json"
ROUTING_LEXICON = "routing_lexicon.json"       # the routing contract file (design §2.22)
QUERY_ALIASES = "query_aliases.json"           # its external_query part, a contract of its own
ROUTE_REPORT = "route_report.json"
LAYER_REPORTS = {"text": (XCHECK_REPORT, OVERLAY_REPORT, DIFF_MD_REPORT, DIFF_CANONICAL_REPORT,
                          DIFF_SUMMARY_REPORT), "struct": (STRUCT_REPORT,),
                 "emb": (EMB_REPORT, ENCODER_FINGERPRINT),
                 "kg0": (KG0_REPORT,),
                 "events": (EVENT_REGISTRY_V2, EVENTS_REPORT),
                 "route": (ROUTING_LEXICON, QUERY_ALIASES, ROUTE_REPORT)}


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
    ("verse_index", "struct", struct.VerseIndex, "unit_key"),
    ("legacy_ids", "struct", struct.LegacyId, "legacy_id"),
    ("embedding_records", "emb", emb.EmbeddingRecord, "record_id"),
    ("names", "kg0", kg.Name, "name_id"),
    ("extra_spans", "kg0", kg.ExtraSpan, "span_id"),
    ("parallel_links", "kg0", kg.ParallelLink, "link_key"),
    ("events", "events", kg.Event, "event_id"),
    ("routing_terms", "route", kg.RouteTerm, "term_key"),
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
