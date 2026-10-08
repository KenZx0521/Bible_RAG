"""G-PROV: every record names a class of the closed provenance enumeration and carries
the evidence that class requires (design §8, §9.1; ``contract.provenance``).

Each row of the layer's own record files is checked, and so is every object nested
in it that names its own class (an event's anchors and triggers). A row without a
class, or an empty layer, is red.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Sequence

from ragdata.contract.provenance import COORDINATE_KEYS, EVIDENCE, PROVENANCE_CLASSES
from ragdata.gates.base import GateResult, violations_result

NAME = "G-PROV"


def _set(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != ()


def _units(value: Any, where: str) -> Iterator[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        if "provenance_class" in value:
            yield where, value
        for key, inner in value.items():
            yield from _units(inner, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            yield from _units(inner, f"{where}[{i}]")


def _has_slot_range(unit: Mapping[str, Any]) -> bool:
    if _set(unit.get("start_slot")) and _set(unit.get("end_slot")):
        return True
    anchors = unit.get("anchors")
    return isinstance(anchors, (list, tuple)) and bool(anchors) and all(
        isinstance(a, Mapping) and _set(a.get("start_slot")) and _set(a.get("end_slot"))
        for a in anchors)


def _evidence(unit: Mapping[str, Any], need: str) -> bool:
    if need == "coordinate":
        return any(_set(unit.get(key)) for key in COORDINATE_KEYS)
    if need == "rule":
        return _set(unit.get("rule_id")) or _set(unit.get("norm_rule_ids"))
    if need == "slot_range":
        return _has_slot_range(unit)
    return _set(unit.get(need))


def _unit_violations(where: str, unit: Mapping[str, Any]) -> list[str]:
    cls = unit.get("provenance_class")
    if cls not in PROVENANCE_CLASSES:
        return [f"{where}: provenance_class {cls!r} is not in the closed enumeration"]
    return [f"{where}: {cls} needs {need}" for need in EVIDENCE[cls]
            if not _evidence(unit, need)]


def check_prov(files: Mapping[str, Sequence[Mapping[str, Any]]]) -> GateResult:
    """Gate the rows of the layer's record files (``{file name: rows}``)."""
    violations = [] if any(files.values()) else ["the layer holds no records"]
    for file_name, rows in sorted(files.items()):
        for line, row in enumerate(rows, start=1):
            where = f"{file_name}:{line}"
            if "provenance_class" not in row:
                violations.append(f"{where}: no provenance_class")
            for path, unit in _units(row, where):
                violations += _unit_violations(path, unit)
    return violations_result(NAME, violations)
