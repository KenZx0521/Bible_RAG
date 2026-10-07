"""G-SCHEMA: rows pass their contracts, layer files are complete, ids are unique and
numbered sequences (``#n``, ``seg_idx``, ``idx``) run without gaps (design §3.2, §8)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping, Sequence

from ragcommon import ids
from ragdata.contract import (
    ContractError, Record, layer_types, parse_record, primary_key, record_type_for_file,
)
from ragdata.gates.base import MAX_DETAILS, GateResult, Snapshot, snapshot, violations_result

NAME = "G-SCHEMA"


def _seq(raw_id: str) -> int:
    return ids.parse(raw_id).seq


# record type -> (group of the sequence, number within it, first number)
SEQUENCES: Mapping[str, tuple[Callable[[Any], str], Callable[[Any], int], int]] = {
    "headings": (lambda r: ids.parse(r.heading_id).parent.raw, lambda r: _seq(r.heading_id), 1),
    "footnotes": (lambda r: r.unit_key, lambda r: r.n, 1),
    "speakers": (lambda r: r.unit_key, lambda r: _seq(r.sk_id), 1),
    "parallel_refs": (lambda r: r.heading_id, lambda r: r.seg_idx, 0),
    "passages": (lambda r: r.pericope_id, lambda r: r.seg_idx, 0),
    "chunks": (lambda r: r.passage_id, lambda r: r.idx, 0),
}


def _parse_file(file_name: str, rows: Iterable[Mapping], violations: list[str]) -> list[Record]:
    type_name = record_type_for_file(file_name).name
    good = []
    for line, raw in enumerate(rows, start=1):
        try:
            good.append(parse_record(type_name, raw))
        except ContractError as exc:
            violations.append(f"{file_name}:{line}: {exc}")
    return good


def _duplicates(type_name: str, records: Sequence[Record]) -> list[str]:
    seen: set[str] = set()
    found = []
    for record in records:
        key = primary_key(record, type_name)
        if key in seen:
            found.append(f"{type_name}: duplicate primary key {key}")
        seen.add(key)
    return found


def _sequence_gaps(type_name: str, records: Sequence[Record]) -> list[str]:
    if type_name not in SEQUENCES:
        return []
    group_of, number_of, first = SEQUENCES[type_name]
    groups: dict[str, list[int]] = defaultdict(list)
    for record in records:
        groups[group_of(record)].append(number_of(record))
    return [f"{type_name}: sequence under {group} is {sorted(numbers)}, expected "
            f"{first}..{first + len(numbers) - 1}"
            for group, numbers in sorted(groups.items())
            if sorted(numbers) != list(range(first, first + len(numbers)))]


def check_schema(files: Mapping[str, Sequence[Mapping]], layers: Sequence[str],
                 max_details: int = MAX_DETAILS) -> tuple[GateResult, Snapshot]:
    """Gate the raw rows of ``layers``; return the result and the records that passed."""
    violations: list[str] = []
    required = {t.file_name for layer in layers for t in layer_types(layer)}
    violations += [f"{name}: missing file" for name in sorted(required - set(files))]
    parsed: dict[str, list[Record]] = {}
    for file_name in sorted(files):
        if file_name not in required:
            violations.append(f"{file_name}: not a file of the {'/'.join(layers)} layers")
            continue
        parsed[record_type_for_file(file_name).name] = _parse_file(file_name, files[file_name],
                                                                   violations)
    for type_name, records in parsed.items():
        violations += _duplicates(type_name, records)
        violations += _sequence_gaps(type_name, records)
    return violations_result(NAME, violations, max_details=max_details), snapshot(parsed)
