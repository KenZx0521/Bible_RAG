"""PostgreSQL side of the loader (design §7.2), over a psycopg2 connection.

``apply`` writes one build in a single transaction: CREATE SCHEMA, CREATE TABLE,
COPY (each table's row count checked), foreign keys, indexes, ANALYZE, the
rag_meta tables (created only if missing) and the build's ``rag_meta.builds``
row; ``during`` (the Qdrant and contract-file writes) runs before the commit.
Any failure rolls the transaction back, and the schema this call created is
dropped if it is still there: the only DROP the loader has. It never writes
``rag_meta.serving`` (``promote`` does) and never touches another schema.
``drop_build`` is unload's side (``loader.unload``): one named build's schema and row.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, Sequence

import psycopg2

from ragdata.loader import sql
from ragdata.loader.config import PgSettings
from ragdata.loader.plan import LoaderError, PgPlan
from ragdata.loader.tables import Table


class PgError(LoaderError):
    """The database refused a step, or holds what the loader did not expect."""


class PgDb:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._conn.autocommit = False

    @classmethod
    def connect(cls, settings: PgSettings) -> "PgDb":
        try:
            conn = psycopg2.connect(host=settings.host, port=settings.port,
                                    dbname=settings.dbname, user=settings.user,
                                    password=settings.password)
        except psycopg2.Error as exc:
            raise PgError(f"cannot connect to {settings!r}: {exc}") from None
        return cls(conn)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """A cursor whose work commits when the block ends and rolls back if it raises."""
        try:
            with self._conn.cursor() as cur:
                yield cur
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def query(self, statement: str, params: Sequence[Any] = ()) -> list[tuple]:
        with self.transaction() as cur:
            cur.execute(statement, tuple(params))
            return list(cur.fetchall())

    def schema_exists(self, schema: str) -> bool:
        return bool(self.query("SELECT 1 FROM pg_namespace WHERE nspname = %s", [schema]))

    def table_exists(self, schema: str, table: str) -> bool:
        found = self.query("SELECT to_regclass(%s) IS NOT NULL", [sql.qualified(schema, table)])
        return bool(found and found[0][0])

    def serving(self) -> dict[str, str]:
        """{env: build_id} of rag_meta.serving (empty when it does not exist yet)."""
        if not self.table_exists(sql.META, "serving"):
            return {}
        return dict(self.query(f'SELECT "env", "build_id" FROM "{sql.META}"."serving"'))

    def build_row(self, build_id: str) -> dict[str, Any] | None:
        if not self.table_exists(sql.META, "builds"):
            return None
        cols = (*sql.BUILD_COLUMNS, "synthetic")
        found = self.query(f'SELECT {", ".join(sql.ident(c) for c in cols)} FROM '
                           f'"{sql.META}"."builds" WHERE "build_id" = %s', [build_id])
        return dict(zip(cols, found[0])) if found else None

    def apply(self, plan: PgPlan, build: Mapping[str, Any], during: Callable[[], None]) -> None:
        created = False
        try:
            with self.transaction() as cur:
                cur.execute(f"CREATE SCHEMA {sql.ident(plan.schema)}")
                created = True
                _write(cur, plan, build)
                during()
        except BaseException:
            if created:
                self._drop_own(plan.schema)
            raise

    def drop_build(self, schema: str, build_id: str, during: Callable[[], None]) -> None:
        """Unload (``loader.unload``): in one transaction refuse a build ``rag_meta.serving``
        points at (its rows locked), drop ``schema`` and delete the build's builds row;
        ``during`` (the Qdrant and contract-file deletes) runs before the commit."""
        meta = {name: self.table_exists(sql.META, name) for name in ("serving", "builds")}
        with self.transaction() as cur:
            if meta["serving"]:
                cur.execute(f'SELECT "env" FROM "{sql.META}"."serving" WHERE "build_id" = %s '
                            'FOR UPDATE', (build_id,))
                envs = sorted(row[0] for row in cur.fetchall())
                if envs:
                    raise PgError(f"{build_id} is serving {envs}")
            cur.execute(f"DROP SCHEMA IF EXISTS {sql.ident(schema)} CASCADE")
            if meta["builds"]:
                cur.execute(f'DELETE FROM "{sql.META}"."builds" WHERE "build_id" = %s',
                            (build_id,))
            during()

    def _drop_own(self, schema: str) -> None:
        """Drop the schema this load created and could not commit (if still there)."""
        if self.schema_exists(schema):
            with self.transaction() as cur:
                cur.execute(f"DROP SCHEMA {sql.ident(schema)} CASCADE")

    def fetch(self, schema: str, table: Table) -> list[dict[str, Any]]:
        names = table.column_names
        rows = self.query(f"SELECT {', '.join(sql.ident(c) for c in names)} FROM "
                          f"{sql.qualified(schema, table.name)}")
        return [dict(zip(names, row)) for row in rows]

    def constraints(self, schema: str) -> set[tuple[str, str, str]]:
        """(table, constraint name, type) of every constraint in ``schema``."""
        return {(t, n, k) for t, n, k in self.query(
            "SELECT c.relname, con.conname, con.contype::text FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s", [schema])}


def _write(cur: Any, plan: PgPlan, build: Mapping[str, Any]) -> None:
    for statement in plan.create:
        cur.execute(statement)
    for step in plan.copies:
        cur.copy_expert(step.sql, io.StringIO(step.data))
        cur.execute(f"SELECT count(*) FROM {sql.qualified(plan.schema, step.table)}")
        found = cur.fetchone()[0]
        if found != step.rows:
            raise PgError(f"{step.table}: COPY wrote {found} rows, expected {step.rows}")
    for statement in (*plan.finish, *sql.META_DDL):
        cur.execute(statement)
    cur.execute(*sql.insert_build(build))
