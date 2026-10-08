"""SQL text for the PG projection: DDL, COPY data (text format) and rag_meta.

Identifiers are checked against ``[a-z_][a-z0-9_]*`` and always double-quoted (a
contract field may be a reserved word: ``order``, ``end``). COPY data is the text
format: ``\\N`` for null, ``t``/``f``, jsonb as compact JSON, and backslash, tab,
newline and carriage return escaped; a value of the wrong type raises instead of
being coerced.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from ragdata.loader.tables import Column, ForeignKey, Table

IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*")
MAX_IDENT = 63
ESCAPES = str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"})
META = "rag_meta"
META_DDL = (
    f'CREATE SCHEMA IF NOT EXISTS "{META}"',
    f'CREATE TABLE IF NOT EXISTS "{META}"."builds" ('
    '"build_id" text PRIMARY KEY, "release_sha" text NOT NULL, "manifest_sha" text NOT NULL, '
    '"pg_schema" text NOT NULL, "qdrant_collection" text NOT NULL, "contracts_dir" text NOT NULL, '
    '"kg_enabled" boolean NOT NULL, "points" integer NOT NULL, '
    '"synthetic" boolean NOT NULL DEFAULT false, "manifest" jsonb NOT NULL, '
    '"loaded_at" timestamptz NOT NULL DEFAULT now())',
    f'CREATE TABLE IF NOT EXISTS "{META}"."serving" ('
    "\"env\" text PRIMARY KEY CHECK (\"env\" IN ('prod', 'staging')), "
    f'"build_id" text NOT NULL REFERENCES "{META}"."builds" ("build_id"), '
    '"backend_image_digest" text NOT NULL, "activated_at" timestamptz NOT NULL)',
)
BUILD_COLUMNS = ("build_id", "release_sha", "manifest_sha", "pg_schema", "qdrant_collection",
                 "contracts_dir", "kg_enabled", "points", "manifest")


class SqlError(ValueError):
    """A name or a value cannot be written as SQL."""


def ident(name: str) -> str:
    if not isinstance(name, str) or not IDENT_RE.fullmatch(name) or len(name) > MAX_IDENT:
        raise SqlError(f"not a safe SQL identifier: {name!r}")
    return f'"{name}"'


def qualified(schema: str, name: str) -> str:
    return f"{ident(schema)}.{ident(name)}"


def _cols(names: Sequence[str]) -> str:
    return ", ".join(ident(n) for n in names)


def _column_ddl(column: Column) -> str:
    return f"{ident(column.name)} {column.sql}{'' if column.nullable else ' NOT NULL'}"


def create_table(schema: str, table: Table) -> str:
    parts = [*map(_column_ddl, table.columns),
             f"CONSTRAINT {ident('pk_' + table.name)} PRIMARY KEY ({_cols(table.key)})"]
    parts += [f"CONSTRAINT {ident(unique_name(table, u))} UNIQUE ({_cols(u)})"
              for u in table.unique]
    return f"CREATE TABLE {qualified(schema, table.name)} ({', '.join(parts)})"


def unique_name(table: Table, columns: Sequence[str]) -> str:
    return f"uq_{table.name}_{'_'.join(columns)}"


def add_fk(schema: str, table: Table, key: ForeignKey) -> str:
    return (f"ALTER TABLE {qualified(schema, table.name)} ADD CONSTRAINT "
            f"{ident(key.name(table.name))} FOREIGN KEY ({_cols(key.columns)}) REFERENCES "
            f"{qualified(schema, key.target)} ({_cols(key.target_columns)})")


def create_index(schema: str, table: Table, columns: Sequence[str]) -> str:
    name = f"ix_{table.name}_{'_'.join(columns)}"
    return f"CREATE INDEX {ident(name)} ON {qualified(schema, table.name)} ({_cols(columns)})"


def copy_sql(schema: str, table: Table) -> str:
    return f"COPY {qualified(schema, table.name)} ({_cols(table.column_names)}) FROM STDIN"


def _text(value: Any, column: Column) -> str:
    sql = column.sql
    if sql == "jsonb":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if sql == "boolean" and isinstance(value, bool):
        return "t" if value else "f"
    if sql == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if sql == "text" and isinstance(value, str):
        return value
    raise SqlError(f"{column.name}: {value!r} is not a {sql} value")


def copy_value(value: Any, column: Column) -> str:
    if value is None:
        if not column.nullable:
            raise SqlError(f"{column.name}: null in a NOT NULL column")
        return "\\N"
    return _text(value, column).translate(ESCAPES)


def copy_data(table: Table, rows: Sequence[Mapping[str, Any]]) -> str:
    """The COPY text-format data of ``rows`` (each holding exactly the table's columns)."""
    names = set(table.column_names)
    lines = []
    for row in rows:
        if set(row) != names:
            raise SqlError(f"{table.name}: row columns {sorted(set(row) ^ names)} differ")
        lines.append("\t".join(copy_value(row[c.name], c) for c in table.columns))
    return "".join(line + "\n" for line in lines)


def insert_build(row: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """The rag_meta.builds insert (manifest as JSON text, cast to jsonb)."""
    values = tuple(json.dumps(row[c], ensure_ascii=False) if c == "manifest" else row[c]
                   for c in BUILD_COLUMNS)
    marks = ", ".join("%s::jsonb" if c == "manifest" else "%s" for c in BUILD_COLUMNS)
    return (f'INSERT INTO "{META}"."builds" ({_cols(BUILD_COLUMNS)}) VALUES ({marks})', values)
