"""A scripted psycopg2-style connection: it logs every call and answers queries with
``answer(sql, params) -> rows``; ``fail`` makes any statement containing it raise."""

from __future__ import annotations

from typing import Any, Callable


class FakeDbError(Exception):
    pass


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn, self._rows = conn, []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, statement: str, params: tuple = ()) -> None:
        self._conn.log.append(("execute", statement, tuple(params)))
        if self._conn.fail and self._conn.fail in statement:
            raise FakeDbError(f"failed: {statement[:40]}")
        self._rows = list(self._conn.answer(statement, tuple(params)))

    def copy_expert(self, statement: str, handle: Any) -> None:
        self._conn.log.append(("copy", statement, handle.read()))

    def fetchall(self) -> list:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, answer: Callable[[str, tuple], list] = lambda s, p: [],
                 fail: str | None = None) -> None:
        self.answer, self.fail, self.log = answer, fail, []
        self.autocommit = True

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.log.append(("commit",))

    def rollback(self) -> None:
        self.log.append(("rollback",))

    def close(self) -> None:
        self.log.append(("close",))

    def statements(self) -> list[str]:
        return [entry[1] for entry in self.log if entry[0] in ("execute", "copy")]
