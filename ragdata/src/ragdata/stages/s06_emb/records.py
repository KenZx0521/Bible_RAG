"""S6: one embedding record per unit, unchunked passage and chunk (design §2.16, §6).

Records come in file order: the units in canonical order (a merged unit once;
omitted slots have no unit and are never embedded), then the passages that are
not chunked, then the chunks. A passage or chunk text is the v1c rendering of
the blocks S5 assembled for its pieces, so its token count is the one S5 counted;
a verse text is the whole unit under the title of the passage that owns it
(verse_index). Token counts exclude special tokens, as S5 counts them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ragcommon import ids
from ragdata.contract.emb import KIND_TYPE, PREVIEW_CHARS
from ragdata.contract.fields import sha256_text
from ragdata.gates.base import Snapshot
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import content
from ragdata.stages.s05_struct.view import Piece, TextView, text_view
from ragdata.stages.s06_emb.template import Template

PDF = "pdf_deterministic"
REPORT_SCHEMA = "ragdata.emb_report.v1"
KINDS = tuple(KIND_TYPE)   # file order: verse, passage, chunk

__all__ = ["KINDS", "REPORT_SCHEMA", "StageError", "Sources", "TokenStats", "counts",
           "emb_records", "emb_report", "sources"]


@dataclass(frozen=True)
class TokenStats:
    """``text -> (tokens, <unk> tokens)`` under the pinned BGE-M3 tokenizer, no special tokens."""

    of: Callable[[str], tuple[int, int]]


@dataclass(frozen=True)
class Sources:
    """The text and struct records S6 reads, indexed."""

    view: TextView
    passages: tuple[Any, ...]                  # canonical order
    passage: Mapping[str, Any]                 # passage_id -> passage
    chunks: tuple[Any, ...]                    # canonical order
    owner: Mapping[str, Any]                   # unit_key -> verse_index row


def sources(snapshot: Snapshot) -> Sources:
    passages = tuple(snapshot.of("passages"))
    return Sources(view=text_view(snapshot), passages=passages,
                   passage=MappingProxyType({p.passage_id: p for p in passages}),
                   chunks=tuple(snapshot.of("chunks")),
                   owner=MappingProxyType({r.unit_key: r for r in snapshot.of("verse_index")}))


def _passage(src: Sources, passage_id: str, where: str) -> Any:
    if passage_id not in src.passage:
        raise StageError(f"{where}: passage {passage_id} is not in the struct layer")
    return src.passage[passage_id]


def _pieces(src: Sources, refs: Sequence[Any], where: str) -> tuple[Piece, ...]:
    missing = [r.unit_key for r in refs if r.unit_key not in src.view.unit]
    if missing:
        raise StageError(f"{where}: units {missing} are not in the text layer")
    return tuple(Piece(src.view.unit[r.unit_key], r.from_, r.to) for r in refs)


def _record(kind: str, record_id: str, source_id: str, text: str, payload: dict[str, Any],
            template: Template, stats: TokenStats) -> dict[str, Any]:
    tokens, unk = stats.of(text)
    text_sha = sha256_text(text)
    return {"record_id": record_id, "kind": kind, "source_id": source_id,
            "template_id": template.template_id, "text": text, "text_sha": text_sha,
            "token_count": tokens, "unk_count": unk, "point_id": ids.point_id(record_id),
            "payload": {"record_id": record_id, "kind": kind, "type": KIND_TYPE[kind],
                        **payload, "text_sha": text_sha, "template_id": template.template_id},
            "provenance_class": PDF}


def _place(src: Sources, passage: Any, start_key: str, end_key: str, verse_range: str,
           split: Sequence[str] = ()) -> dict[str, Any]:
    """The payload fields that say where a record lies."""
    start = ids.parse(start_key)
    return {"book_id": start.book_id, "book_name": src.view.book_name(start.book_id),
            "chapter_num": start.chapter, "chapter_end": start.chapter,
            "title": passage.title or "", "verse_range": verse_range, "start_key": start_key,
            "end_key": end_key, "passage_id": passage.passage_id,
            "parent_pericope_id": passage.passage_id, "split_passage_ids": list(split),
            "pericope_id": passage.pericope_id}


def verse_record(src: Sources, unit: Any, template: Template, stats: TokenStats
                 ) -> dict[str, Any]:
    if unit.unit_key not in src.owner:
        raise StageError(f"{unit.unit_key}: no verse_index row names its passage")
    owner = src.owner[unit.unit_key]
    passage = _passage(src, owner.passage_id, unit.unit_key)
    body = content.verse_body(unit, 0, None, ())
    text = template.render_verse(src.view.book_name(unit.book_id), unit.chapter, passage.title,
                                 unit.label, body)
    start = ids.verse_key(unit.book_id, unit.chapter, unit.v_start)
    end = ids.verse_key(unit.book_id, unit.chapter, unit.v_end)
    payload = {**_place(src, passage, start, end, unit.label, owner.split_passage_ids),
               "content_preview": body[:PREVIEW_CHARS]}
    return _record("verse", ids.verse_record_id(unit.unit_key), unit.unit_key, text, payload,
                   template, stats)


def _ranged_record(src: Sources, kind: str, record_id: str, passage: Any, row: Any,
                   template: Template, stats: TokenStats) -> dict[str, Any]:
    """A passage or chunk record: the v1c text of the blocks of ``row``'s pieces."""
    pieces = _pieces(src, row.unit_refs, record_id)
    first = pieces[0].unit
    bodies = content.bodies(content.piece_blocks(src.view, pieces))
    text = template.render_passage(src.view.book_name(first.book_id), first.chapter,
                                   passage.title, row.verse_range, bodies)
    payload = {**_place(src, passage, row.start_key, row.end_key, row.verse_range),
               "content_preview": text[:PREVIEW_CHARS]}
    return _record(kind, record_id, record_id, text, payload, template, stats)


def emb_records(snapshot: Snapshot, template: Template, stats: TokenStats
                ) -> list[dict[str, Any]]:
    """Every embedding record of the text and struct records in ``snapshot``, in file order."""
    src = sources(snapshot)
    verses = [verse_record(src, unit, template, stats)
              for book in src.view.books for unit in src.view.units[book.book_id]]
    passages = [_ranged_record(src, "passage", p.passage_id, p, p, template, stats)
                for p in src.passages if not p.requires_chunking]
    chunks = [_ranged_record(src, "chunk", c.chunk_id,
                             _passage(src, c.passage_id, c.chunk_id), c, template, stats)
              for c in src.chunks]
    return [*verses, *passages, *chunks]


def counts(kinds: Sequence[str]) -> dict[str, int]:
    tally = {kind: sum(1 for k in kinds if k == kind) for kind in KINDS}
    return {**tally, "total": len(kinds)}


def emb_report(struct_version: str, text_version: str, template: Template,
               rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``emb_report.json``: the inputs, the declared template, and the counts S6 found
    (the counts are the expectation G-COUNT checks; design §6 writes them for review)."""
    return {"schema": REPORT_SCHEMA, "struct_layer": struct_version, "text_layer": text_version,
            "template": template.declaration(), "counts": counts([r["kind"] for r in rows]),
            "tokens": {"max": max((r["token_count"] for r in rows), default=0),
                       "records_with_unk": sum(1 for r in rows if r["unk_count"]),
                       "unk_tokens": sum(r["unk_count"] for r in rows)}}
