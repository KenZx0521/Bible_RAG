"""Emb-layer record contract (design §2.16, §6; decision D-11(a)).

One record per embedded text: a unit (``vs:``; a merged unit once, omitted slots
never), an unchunked passage (``ps:``) or a chunk (``ck:``). The payload is what
Qdrant stores: the fields the current backend reads (``record_id``, ``type``,
``book_id``, ``book_name``, ``chapter_num``, ``title``, ``verse_range``,
``content_preview``, ``parent_pericope_id``) with their old meaning, and the new
fields of §2.16. The old ``type`` of a passage is ``pericope`` (an old pericope
is a new passage), and ``parent_pericope_id`` is the passage that holds the
record. ``build_id`` is not here: the release that names it is built from this
layer, so the loader adds it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ragcommon import ids
from ragdata.contract.fields import (
    Check, Record, hex64, id_of, integer, list_of, nested, one_of, parsed, require,
    sha256_text, spec, string,
)
from ragdata.contract.struct import _check_key_range

KIND_TYPE = MappingProxyType({"verse": "verse", "passage": "pericope", "chunk": "chunk"})
ID_KIND = MappingProxyType({"verse": "verse_record", "passage": "passage", "chunk": "chunk"})
TEMPLATE_IDS = ("v1c",)
PREVIEW_CHARS = 200


def _plain_text() -> Check:
    """A string that may be empty (the title of an untitled book opening)."""
    def check(value: Any) -> str:
        require(isinstance(value, str), f"expected a string, got {value!r}")
        return value
    return check


def _record_id() -> Check:
    def check(value: Any) -> str:
        require(isinstance(value, str) and ids.is_valid(value)
                and ids.parse(value).kind in ID_KIND.values(),
                f"expected a vs:/ps:/ck: record id, got {value!r}")
        return value
    return check


@dataclass(frozen=True)
class EmbPayload(Record):
    record_id: str = spec(_record_id())
    kind: str = spec(one_of(*KIND_TYPE))
    type: str = spec(one_of(*KIND_TYPE.values()))
    book_id: str = spec(id_of("book"))
    book_name: str = spec(string())
    chapter_num: int = spec(integer(1))
    chapter_end: int = spec(integer(1))
    title: str = spec(_plain_text())
    verse_range: str = spec(string())
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    passage_id: str = spec(id_of("passage"))
    parent_pericope_id: str = spec(id_of("passage"))
    split_passage_ids: tuple = spec(list_of(id_of("passage")))
    pericope_id: str = spec(id_of("pericope"))
    content_preview: str = spec(string())
    text_sha: str = spec(hex64())
    template_id: str = spec(one_of(*TEMPLATE_IDS))

    def check(self) -> None:
        require(self.type == KIND_TYPE[self.kind], f"type of a {self.kind} must be "
                f"{KIND_TYPE[self.kind]!r}")
        require(self.parent_pericope_id == self.passage_id,
                "parent_pericope_id is the passage holding the record")
        _check_key_range(self.start_key, self.end_key, self.verse_range)
        start = parsed(self.start_key)
        require((self.book_id, self.chapter_num) == (start.book_id, start.chapter),
                "book_id/chapter_num must be those of start_key")
        require(self.chapter_end == self.chapter_num, "a record stays in one chapter")
        split = self.split_passage_ids
        require(not split or (len(split) >= 2 and split[0] == self.passage_id),
                "split_passage_ids lists the owning passage first and at least one more")
        require(len(self.content_preview) <= PREVIEW_CHARS,
                f"content_preview is at most {PREVIEW_CHARS} characters")


def _source_matches(kind: str, record_id: str, source_id: str) -> bool:
    if kind == "verse":
        return ids.is_valid(source_id, "unit") and record_id == ids.verse_record_id(source_id)
    return source_id == record_id


@dataclass(frozen=True)
class EmbeddingRecord(Record):
    record_id: str = spec(_record_id())
    kind: str = spec(one_of(*KIND_TYPE))
    source_id: str = spec(string())
    template_id: str = spec(one_of(*TEMPLATE_IDS))
    text: str = spec(string())
    text_sha: str = spec(hex64())
    token_count: int = spec(integer(1))
    unk_count: int = spec(integer(0))
    point_id: str = spec(string())
    payload: EmbPayload = spec(nested(EmbPayload))
    provenance_class: str = spec(one_of("pdf_deterministic"))

    def check(self) -> None:
        require(ids.parse(self.record_id).kind == ID_KIND[self.kind],
                f"a {self.kind} record id is {ID_KIND[self.kind]}")
        require(_source_matches(self.kind, self.record_id, self.source_id),
                f"source_id {self.source_id!r} does not name record {self.record_id}")
        require(self.text_sha == sha256_text(self.text), "text_sha is not sha256(text)")
        require(self.unk_count <= self.token_count, "more <unk> than tokens")
        require(self.point_id == ids.point_id(self.record_id),
                "point_id must be uuid5(NS_RAG, record_id)")
        p = self.payload
        require((p.record_id, p.kind, p.text_sha, p.template_id)
                == (self.record_id, self.kind, self.text_sha, self.template_id),
                "payload record_id/kind/text_sha/template_id must be the record's")
        require(self.kind != "passage" or p.passage_id == self.record_id,
                "a passage record's payload names the passage itself")
        require(p.content_preview in self.text, "content_preview must be part of the text")
