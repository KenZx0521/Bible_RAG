"""Gate results and the typed snapshot that gates read.

Every gate returns a ``GateResult`` serialised as
``{name, hard, pass, observed, expected, details}``. A gate fails closed: an
empty or partial snapshot must turn it red, never green (audit G58).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata.contract import Record, primary_key

MAX_DETAILS = 50


class GateInputError(ValueError):
    """The layers handed to a gate do not fit together; nothing was gated."""


@dataclass(frozen=True)
class GateResult:
    name: str
    hard: bool
    passed: bool
    observed: Any
    expected: Any
    details: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "hard": self.hard, "pass": self.passed,
                "observed": self.observed, "expected": self.expected,
                "details": list(self.details)}


def capped(details: Sequence[str], limit: int = MAX_DETAILS) -> tuple[str, ...]:
    if len(details) <= limit:
        return tuple(details)
    return (*details[:limit], f"… {len(details) - limit} more")


def violations_result(name: str, violations: Sequence[str], hard: bool = True,
                      max_details: int = MAX_DETAILS) -> GateResult:
    """A gate whose target is zero violations."""
    return GateResult(name=name, hard=hard, passed=not violations,
                      observed={"violations": len(violations)}, expected={"violations": 0},
                      details=capped(violations, max_details))


@dataclass(frozen=True)
class Snapshot:
    """Records that passed their contracts, by record type."""

    records: Mapping[str, tuple[Record, ...]]

    def of(self, type_name: str) -> tuple[Record, ...]:
        return self.records.get(type_name, ())

    def index(self, type_name: str) -> Mapping[str, Record]:
        """Records by primary key (first occurrence wins; G-SCHEMA reports duplicates)."""
        table: dict[str, Record] = {}
        for record in self.of(type_name):
            table.setdefault(primary_key(record, type_name), record)
        return MappingProxyType(table)


def snapshot(records: Mapping[str, Sequence[Record]]) -> Snapshot:
    return Snapshot(MappingProxyType({k: tuple(v) for k, v in records.items()}))
