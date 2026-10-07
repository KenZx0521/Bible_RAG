"""An in-memory stand-in for ``loader.pg.PgDb`` with the same methods.

``apply`` decodes the plan's COPY text the way PostgreSQL reads the text format
(so the loader's encoding round-trips here), records the constraints the DDL
names, runs ``during`` and only then "commits"; ``fail_on`` makes a COPY of that
table fail first. Tests mutate ``schemas[...]`` to stand for a projection that
drifted.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from ragdata.loader.pg import PgError
from ragdata.loader.plan import PgPlan
from ragdata.loader.tables import Table, table

UNESCAPE = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}
CONSTRAINT_RE = re.compile(r'"([a-z0-9_]+)"\."([a-z0-9_]+)".*?CONSTRAINT "([a-z0-9_]+)" '
                           r'(PRIMARY KEY|UNIQUE|FOREIGN KEY)')
INLINE_RE = re.compile(r'CONSTRAINT "([a-z0-9_]+)" (PRIMARY KEY|UNIQUE)')
KINDS = {"PRIMARY KEY": "p", "UNIQUE": "u", "FOREIGN KEY": "f"}


def _value(text: str, sql: str) -> Any:
    if text == "\\N":
        return None
    text = re.sub(r"\\(.)", lambda m: UNESCAPE[m.group(1)], text)
    if sql == "integer":
        return int(text)
    if sql == "boolean":
        return {"t": True, "f": False}[text]
    return json.loads(text) if sql == "jsonb" else text


def decode_copy(tb: Table, data: str) -> list[dict[str, Any]]:
    rows = []
    for line in data.split("\n")[:-1]:
        fields = line.split("\t")
        assert len(fields) == len(tb.columns), (tb.name, line)
        rows.append({c.name: _value(f, c.sql) for c, f in zip(tb.columns, fields)})
    return rows


def _constraints(plan: PgPlan) -> set[tuple[str, str, str]]:
    found = set()
    for statement in plan.create:
        name = re.search(r'"[a-z0-9_]+"\."([a-z0-9_]+)"', statement).group(1)
        found |= {(name, c, KINDS[k]) for c, k in INLINE_RE.findall(statement)}
    for statement in plan.finish:
        m = CONSTRAINT_RE.search(statement)
        if m:
            found.add((m.group(2), m.group(3), KINDS[m.group(4)]))
    return found


class FakePg:
    def __init__(self) -> None:
        self.schemas: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.constraint_sets: dict[str, set[tuple[str, str, str]]] = {}
        self.builds: dict[str, dict[str, Any]] = {}
        self.serving_rows: dict[str, str] = {}
        self.fail_on: str | None = None
        self.applied = 0

    def schema_exists(self, schema: str) -> bool:
        return schema in self.schemas

    def serving(self) -> dict[str, str]:
        return dict(self.serving_rows)

    def build_row(self, build_id: str) -> dict[str, Any] | None:
        return self.builds.get(build_id)

    def apply(self, plan: PgPlan, build: Mapping[str, Any], during: Callable[[], None]) -> None:
        if plan.schema in self.schemas:
            raise PgError(f"schema {plan.schema} already exists")
        staged = {}
        for step in plan.copies:
            if step.table == self.fail_on:
                raise PgError(f"COPY into {step.table} failed")
            staged[step.table] = decode_copy(table(step.table), step.data)
            assert len(staged[step.table]) == step.rows
        during()
        self.applied += 1
        self.schemas[plan.schema] = staged
        self.constraint_sets[plan.schema] = _constraints(plan)
        self.builds[build["build_id"]] = {**build, "synthetic": False}

    def fetch(self, schema: str, tb: Table) -> list[dict[str, Any]]:
        return [dict(r) for r in self.schemas[schema].get(tb.name, [])]

    def constraints(self, schema: str) -> set[tuple[str, str, str]]:
        return set(self.constraint_sets.get(schema, set()))
