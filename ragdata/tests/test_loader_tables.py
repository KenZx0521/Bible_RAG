"""The PG tables of a build (loader.tables), their SQL (loader.sql) and the C3 row hash
(loader.projection)."""

from __future__ import annotations

import dataclasses

import pytest

import mini_build
import mini_kg
from ragdata.contract import record_type
from ragdata.loader import projection, sql, tables
from ragdata.loader.tables import Column

REQUIRED = {"books", "chapters", "verse_units", "verse_slots", "chapter_texts", "headings",
            "footnotes", "speakers", "parallel_refs", "pericopes", "passages", "chunks", "names",
            "extra_spans", "parallel_links", "events", "event_anchors"}


def _fields(type_name):
    return {f.metadata.get("key") or f.name
            for f in dataclasses.fields(record_type(type_name).cls)}


def test_the_build_has_the_design_tables_plus_embedding_records():
    assert {t.name for t in tables.TABLES} == REQUIRED | {"embedding_records"}
    assert tables.BUILD_INFO.name == "build_info" and tables.BUILD_INFO.key == ("build_id",)


@pytest.mark.parametrize("table", [t for t in tables.TABLES if t.source],
                         ids=lambda t: t.name)
def test_columns_are_the_record_fields_but_what_the_exemption_file_lists(table):
    exempt = projection.load_exempt()["pg"].get(table.name, projection.NONE)
    fields, columns = _fields(table.source), set(table.column_names)
    assert fields - columns == exempt.snapshot
    assert columns - fields == exempt.projection


def test_the_exemption_file_names_only_tables_and_payload_that_exist():
    exempt = projection.load_exempt()
    assert set(exempt) == {"pg", "qdrant"}
    assert set(exempt["pg"]) <= {t.name for t in tables.TABLES}
    assert exempt["qdrant"]["payload"].projection == {"build_id"}


def test_column_types_follow_the_contract_annotations():
    units = {c.name: c for c in tables.table("verse_units").columns}
    assert units["text"] == Column("text", "text", False)
    assert units["v_start"] == Column("v_start", "integer", False)
    assert units["is_poetry"] == Column("is_poetry", "boolean", False)
    assert units["line_breaks"].sql == units["prov"].sql == "jsonb"
    slots = {c.name: c for c in tables.table("verse_slots").columns}
    assert slots["unit_key"] == Column("unit_key", "text", True)
    footnotes = {c.name: c for c in tables.table("footnotes").columns}
    assert footnotes["anchor"] == Column("anchor", "jsonb", True)


def test_every_foreign_key_targets_a_key_or_unique_columns_of_a_table():
    for t in tables.TABLES:
        for key in t.fks:
            target = tables.table(key.target)
            assert set(key.columns) <= set(t.column_names), (t.name, key)
            assert key.target_columns in (target.key, *target.unique), (t.name, key)


def _files():
    files = {f"{k}.jsonl": v for layer in mini_build.build().values() for k, v in layer.items()}
    files["events.jsonl"] = mini_kg.events()
    files["embedding_records.jsonl"] = [
        {"record_id": "vs:eph.6.2-3", "kind": "verse", "source_id": "eph.6.2-3"},
        {"record_id": "ps:eph.6.1", "kind": "passage", "source_id": "ps:eph.6.1"},
        {"record_id": "ck:act.9.1~act.9.2", "kind": "chunk", "source_id": "ck:act.9.1~act.9.2"}]
    return files


def test_events_lose_their_anchors_to_event_anchors_in_order():
    files = _files()
    assert all("anchors" not in row for row in tables.table("events").rows(files))
    anchors = tables.table("event_anchors").rows(files)
    assert [(a["event_id"], a["ord"], a["passage_id"]) for a in anchors] == [
        ("ev0001", 0, "ps:psa.42.1"), ("ev0002", 0, "ps:mat.18.1"),
        ("ev0003", 0, "ps:act.9.1"), ("ev0003", 1, "ps:act.9.3b"),
        ("ev0003", 2, "ps:act.10.1"), ("ev0005", 0, "ps:sng.1.1")]
    assert set(anchors[0]) == set(tables.table("event_anchors").column_names)
    columns = {c.name: c.sql for c in tables.table("event_anchors").columns}
    assert (columns["evidence"], columns["pericope_id"]) == ("jsonb", "text")


def test_embedding_records_name_their_source_in_its_own_fk_column():
    rows = tables.table("embedding_records").rows(_files())
    picked = [{k: r[k] for k in ("fk_unit_key", "fk_passage_id", "fk_chunk_id")} for r in rows]
    assert picked == [
        {"fk_unit_key": "eph.6.2-3", "fk_passage_id": None, "fk_chunk_id": None},
        {"fk_unit_key": None, "fk_passage_id": "ps:eph.6.1", "fk_chunk_id": None},
        {"fk_unit_key": None, "fk_passage_id": None, "fk_chunk_id": "ck:act.9.1~act.9.2"}]


def test_record_tables_copy_the_rows_as_they_are():
    files = _files()
    assert tables.table("verse_units").rows(files) == files["verse_units.jsonl"]
    assert tables.table("verse_slots").row_id(files["verse_slots.jsonl"][0]) == "psa.42.1"
    assert tables.table("event_anchors").row_id({"event_id": "ev0003", "ord": 1}) == "ev0003|1"
    with pytest.raises(KeyError):
        tables.table("name_spans")


# ------------------------------------------------------------------ SQL


def test_ddl_quotes_every_identifier_and_names_its_constraints():
    ddl = sql.create_table("bb20261008_0123abcd", tables.table("chapter_texts"))
    assert ddl.startswith('CREATE TABLE "bb20261008_0123abcd"."chapter_texts" (')
    assert '"order" text,' in ddl and '"pages" jsonb NOT NULL' in ddl
    assert 'CONSTRAINT "pk_chapter_texts" PRIMARY KEY ("id")' in ddl
    chapters = sql.create_table("s", tables.table("chapters"))
    assert 'CONSTRAINT "uq_chapters_book_id_chapter" UNIQUE ("book_id", "chapter")' in chapters
    units = tables.table("verse_units")
    assert sql.add_fk("s", units, units.fks[1]) == (
        'ALTER TABLE "s"."verse_units" ADD CONSTRAINT "fk_verse_units_book_id_chapter" FOREIGN '
        'KEY ("book_id", "chapter") REFERENCES "s"."chapters" ("book_id", "chapter")')
    assert sql.create_index("s", units, ("book_id", "chapter")) == (
        'CREATE INDEX "ix_verse_units_book_id_chapter" ON "s"."verse_units" ("book_id", "chapter")')


@pytest.mark.parametrize("name", ["Upper", "a-b", "x;drop", "", "a" * 64, None])
def test_unsafe_identifiers_are_refused(name):
    with pytest.raises(sql.SqlError):
        sql.ident(name)


def test_copy_data_escapes_text_and_writes_nulls_booleans_and_json():
    t = tables.Table("t", (Column("a", "text", False), Column("b", "integer", True),
                           Column("c", "boolean", False), Column("d", "jsonb", False)),
                     ("a",), lambda files: [])
    data = sql.copy_data(t, [{"a": "x\ty\\z\n上帝\r", "b": None, "c": True,
                              "d": {"k": "a\tb", "n": [1, 2.5]}}])
    assert data == 'x\\ty\\\\z\\n上帝\\r\t\\N\tt\t{"k":"a\\\\tb","n":[1,2.5]}\n'
    assert sql.copy_sql("s", t) == 'COPY "s"."t" ("a", "b", "c", "d") FROM STDIN'


@pytest.mark.parametrize("row, match", [
    ({"a": None, "b": 1, "c": True, "d": {}}, "NOT NULL"),
    ({"a": "x", "b": True, "c": True, "d": {}}, "integer"),
    ({"a": "x", "b": "1", "c": True, "d": {}}, "integer"),
    ({"a": 1, "b": 1, "c": True, "d": {}}, "text"),
    ({"a": "x", "b": 1, "c": 1, "d": {}}, "boolean"),
    ({"a": "x", "b": 1, "c": True}, "differ"),
    ({"a": "x", "b": 1, "c": True, "d": float("nan")}, "Out of range"),
])
def test_copy_data_refuses_values_of_the_wrong_type(row, match):
    t = tables.Table("t", (Column("a", "text", False), Column("b", "integer", True),
                           Column("c", "boolean", False), Column("d", "jsonb", False)),
                     ("a",), lambda files: [])
    with pytest.raises((sql.SqlError, ValueError), match=match):
        sql.copy_data(t, [row])


def test_the_builds_insert_casts_the_manifest_to_jsonb():
    row = {c: c for c in sql.BUILD_COLUMNS} | {"manifest": {"build_id": "b1"}, "points": 3}
    statement, values = sql.insert_build(row)
    assert statement.startswith('INSERT INTO "rag_meta"."builds" ("build_id", ')
    assert "%s::jsonb" in statement and values[-1] == '{"build_id": "b1"}'


# ------------------------------------------------------------------ C3 hash


def test_the_row_hash_normalizes_numbers_strings_and_key_order():
    nfd = "e\u0301"
    assert projection.row_hash({"a": 1.0, "b": [nfd]}) == projection.row_hash({"b": ["é"], "a": 1})
    assert projection.row_hash({"a": 1, "x": 2}, drop=["x"]) == projection.row_hash({"a": 1})
    assert projection.row_hash({"a": 0.5}) != projection.row_hash({"a": 0.25})
    with pytest.raises(projection.ProjectionError):
        projection.normalize(object())


def test_row_violations_name_the_fields_that_differ():
    want = {"x": {"a": 1, "b": "s", "anchors": []}}
    got = {"x": {"a": 2, "b": "s", "fk": None}}
    exempt = projection.Exempt(frozenset({"anchors"}), frozenset({"fk"}))
    assert projection.row_violations("t", want, got, exempt) == ["t x: differs in ['a']"]
    got["x"]["a"] = 1
    assert projection.row_violations("t", want, got, exempt) == []
    got["x"]["extra"] = 0
    assert projection.row_violations("t", want, got, exempt) == ["t x: differs in ['extra']"]


def test_id_violations_report_missing_extra_and_duplicate_ids():
    out = projection.id_violations("t", ["a", "b"], ["b", "c", "c"])
    assert out == ["t: missing a", "t: unexpected c", "t: 1 duplicate ids"]


@pytest.mark.parametrize("text, match", [
    ("schema: other\n", "not ragdata"),
    ("schema: ragdata.projection_exempt.v1\npg: [1]\n", "store: table"),
    ("schema: ragdata.projection_exempt.v1\npg:\n  t:\n    snapshot: {}\n", "snapshot/projection"),
    ("schema: ragdata.projection_exempt.v1\npg:\n  t:\n    other:\n      a: b\n", "snapshot"),
    ("{", "unreadable"),
])
def test_a_malformed_exemption_file_is_refused(tmp_path, text, match):
    path = tmp_path / "exempt.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(projection.ProjectionError, match=match):
        projection.load_exempt(path)
