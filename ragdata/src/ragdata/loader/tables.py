"""The PG projection of a release (design §7.2): one table per record type, in schema
``b{build_id}``.

Columns are the record contract's fields (JSON names): ``str`` and ``int`` and
``bool`` fields become text, integer and boolean columns, everything else
(lists, nested records, free objects) jsonb; ``X | None`` is nullable. Where a
table differs from its records, ``contract/projection_exempt_fields.yaml`` says
so and why (G-PROJ C3 compares every other field):

- ``events`` leaves ``anchors`` out: each anchor is a row of ``event_anchors``
  (``event_id``, its position ``ord`` in the event, and the anchor's fields);
- ``embedding_records`` adds ``fk_unit_key``/``fk_passage_id``/``fk_chunk_id``,
  the record's source as a foreign key into its own table.

``embedding_records`` is not among the tables design §7.2 lists: G-PROJ C4 compares
Qdrant's ``text_sha`` with PG and re-encodes texts read from PG, so PG holds them.
Foreign keys name only plain columns (a reference inside a jsonb list is G-REFINT's);
``build_info`` holds the release the schema was loaded from.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from ragdata.contract import record_type
from ragdata.contract.kg import Anchor

SQL_TYPES = {"str": "text", "int": "integer", "bool": "boolean"}
Rows = Mapping[str, Sequence[Mapping[str, Any]]]     # {file name: raw rows}


@dataclass(frozen=True)
class Column:
    name: str
    sql: str                # text | integer | boolean | jsonb
    nullable: bool


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    target: str
    target_columns: tuple[str, ...]

    def name(self, table: str) -> str:
        return f"fk_{table}_{'_'.join(self.columns)}"


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]
    rows: Callable[[Rows], list[dict[str, Any]]]
    fks: tuple[ForeignKey, ...] = ()
    unique: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[tuple[str, ...], ...] = ()
    source: str | None = None          # the record type its rows come from

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def row_id(self, row: Mapping[str, Any]) -> str:
        return "|".join(str(row[k]) for k in self.key)


def _column(field: dataclasses.Field) -> Column:
    name = field.metadata.get("key") or field.name
    base, _, none = str(field.type).partition(" | ")
    return Column(name, SQL_TYPES.get(base, "jsonb"), none == "None")


def record_columns(type_name: str, drop: Iterable[str] = ()) -> tuple[Column, ...]:
    dropped = set(drop)
    return tuple(c for c in map(_column, dataclasses.fields(record_type(type_name).cls))
                 if c.name not in dropped)


def fk(columns: str, target: str, target_columns: str | None = None) -> ForeignKey:
    cols = tuple(columns.split(","))
    return ForeignKey(cols, target, tuple((target_columns or columns).split(",")))


def _copy(type_name: str, drop: Iterable[str] = (),
          extra: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
          ) -> Callable[[Rows], list[dict[str, Any]]]:
    dropped = set(drop)

    def rows(files: Rows) -> list[dict[str, Any]]:
        out = []
        for raw in files[f"{type_name}.jsonl"]:
            row = {k: v for k, v in raw.items() if k not in dropped}
            out.append({**row, **(extra(raw) if extra else {})})
        return out
    return rows


def _record_table(type_name: str, key: str, fks: Sequence[ForeignKey] = (),
                  indexes: Sequence[str] = (), unique: Sequence[str] = ()) -> Table:
    return Table(type_name, record_columns(type_name), (key,), _copy(type_name), tuple(fks),
                 tuple(tuple(u.split(",")) for u in unique),
                 tuple(tuple(i.split(",")) for i in indexes), type_name)


def _anchor_rows(files: Rows) -> list[dict[str, Any]]:
    return [{"event_id": event["event_id"], "ord": i, **anchor}
            for event in files["events.jsonl"] for i, anchor in enumerate(event["anchors"])]


ANCHOR_COLUMNS = (Column("event_id", "text", False), Column("ord", "integer", False),
                  *map(_column, dataclasses.fields(Anchor)))
EMB_FK_COLUMNS = {"verse": "fk_unit_key", "passage": "fk_passage_id", "chunk": "fk_chunk_id"}


def _emb_fks(raw: Mapping[str, Any]) -> dict[str, Any]:
    source = {"verse": raw["source_id"]}.get(raw["kind"], raw["record_id"])
    return {col: (source if raw["kind"] == kind else None)
            for kind, col in EMB_FK_COLUMNS.items()}


def _text_tables() -> tuple[Table, ...]:
    slots = "verse_slots"
    return (
        _record_table("books", "book_id"),
        _record_table("chapters", "chapter_key", [fk("book_id", "books"),
                                                  fk("book_division_id", "chapter_texts", "id")],
                      unique=["book_id,chapter"]),
        _record_table("verse_units", "unit_key", [fk("book_id", "books"),
                                                  fk("book_id,chapter", "chapters")],
                      indexes=["book_id,chapter"]),
        _record_table(slots, "slot_key", [fk("unit_key", "verse_units"),
                                          fk("variant_footnote_id", "footnotes", "fn_id")],
                      indexes=["unit_key"]),
        _record_table("chapter_texts", "id", [fk("chapter_key", "chapters")]),
        _record_table("headings", "heading_id", [
            fk("book_id", "books"), fk("anchor_unit_key", "verse_units", "unit_key"),
            fk("parent_heading_id", "headings", "heading_id")], indexes=["anchor_unit_key"]),
        _record_table("footnotes", "fn_id", [fk("unit_key", "verse_units"),
                                             fk("variant_slot_key", slots, "slot_key")],
                      indexes=["unit_key"]),
        _record_table("speakers", "sk_id", [fk("unit_key", "verse_units")]),
        _record_table("parallel_refs", "pr_id", [fk("heading_id", "headings")]),
    )


def _struct_tables() -> tuple[Table, ...]:
    slot = "verse_slots"
    return (
        _record_table("pericopes", "pericope_id", [
            fk("book_id", "books"), fk("heading_id", "headings"),
            fk("section_heading_id", "headings", "heading_id"),
            fk("start_slot", slot, "slot_key"), fk("end_slot", slot, "slot_key"),
            fk("prev_id", "pericopes", "pericope_id"), fk("next_id", "pericopes", "pericope_id"),
            fk("next_book_id", "books", "book_id")]),
        _record_table("passages", "passage_id", [
            fk("pericope_id", "pericopes"), fk("chapter_key", "chapters"),
            fk("start_slot", slot, "slot_key"), fk("end_slot", slot, "slot_key"),
            fk("superscription_id", "chapter_texts", "id")],
            indexes=["pericope_id", "chapter_key"]),
        _record_table("chunks", "chunk_id", [fk("passage_id", "passages")],
                      indexes=["passage_id"]),
    )


def _kg_tables() -> tuple[Table, ...]:
    slot = "verse_slots"
    return (
        _record_table("names", "name_id"),
        _record_table("extra_spans", "span_id", indexes=["container_id"]),
        _record_table("parallel_links", "link_key", [
            fk("pr_id", "parallel_refs"), fk("from_pericope", "pericopes", "pericope_id"),
            fk("to_pericope", "pericopes", "pericope_id"),
            fk("target_start_slot", slot, "slot_key"), fk("target_end_slot", slot, "slot_key")]),
        Table("events", record_columns("events", drop=["anchors"]), ("event_id",),
              _copy("events", drop=["anchors"]), source="events"),
        Table("event_anchors", ANCHOR_COLUMNS, ("event_id", "ord"), _anchor_rows,
              (fk("event_id", "events"), fk("passage_id", "passages"),
               fk("start_slot", slot, "slot_key"), fk("end_slot", slot, "slot_key")),
              unique=(("event_id", "passage_id"),), indexes=(("passage_id",),)),
    )


def _emb_table() -> Table:
    columns = (*record_columns("embedding_records"),
               *(Column(c, "text", True) for c in EMB_FK_COLUMNS.values()))
    return Table("embedding_records", columns, ("record_id",),
                 _copy("embedding_records", extra=_emb_fks),
                 (fk("fk_unit_key", "verse_units", "unit_key"),
                  fk("fk_passage_id", "passages", "passage_id"),
                  fk("fk_chunk_id", "chunks", "chunk_id")),
                 unique=(("point_id",),), indexes=(("kind",),), source="embedding_records")


BUILD_INFO = Table("build_info", (
    Column("build_id", "text", False), Column("release_sha", "text", False),
    Column("kg_enabled", "boolean", False), Column("release", "jsonb", False),
    Column("vectors", "jsonb", False)), ("build_id",), lambda files: [])
TABLES: tuple[Table, ...] = (*_text_tables(), *_struct_tables(), *_kg_tables(), _emb_table())
BY_NAME = {t.name: t for t in (*TABLES, BUILD_INFO)}


def table(name: str) -> Table:
    if name not in BY_NAME:
        raise KeyError(f"no PG table {name!r}")
    return BY_NAME[name]
