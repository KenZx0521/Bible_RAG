"""What every layer build returns: the stored layers, the gates it ran, its timings."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from ragdata.gates.base import GateResult
from ragdata.store import StoredLayer

REPORT_SCHEMA = "ragdata.build_report.v1"


def gates_pass(gates: Sequence[GateResult]) -> bool:
    """True when gates ran and every hard one passed."""
    return bool(gates) and all(g.passed for g in gates if g.hard)


@dataclass(frozen=True)
class BuildResult:
    layers: Mapping[str, StoredLayer]
    gates: tuple[GateResult, ...]
    timings: Mapping[str, float]
    attachments: Mapping[str, Mapping[str, Any]] = MappingProxyType({})   # by layer

    @property
    def passed(self) -> bool:
        return gates_pass(self.gates)

    def to_json(self) -> dict[str, Any]:
        doc = {"schema": REPORT_SCHEMA, "pass": self.passed,
               "layers": {k: {"version": v.version, "path": str(v.path)}
                          for k, v in self.layers.items()},
               "gates": [g.to_json() for g in self.gates],
               "timings_s": {k: round(v, 2) for k, v in self.timings.items()}}
        if self.attachments:
            doc["attachments"] = {k: dict(v) for k, v in self.attachments.items()}
        return doc


@dataclass
class Clock:
    laps: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def lap(self, name: str) -> Iterator[None]:
        start = time.monotonic()
        yield
        self.laps[name] = self.laps.get(name, 0.0) + time.monotonic() - start
