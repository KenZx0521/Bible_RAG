"""Data gates: each returns a GateResult; any failing hard gate blocks the layer."""

from ragdata.gates.base import GateResult, Snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.schema import check_schema

__all__ = ["GateResult", "Snapshot", "check_counts", "check_schema"]
