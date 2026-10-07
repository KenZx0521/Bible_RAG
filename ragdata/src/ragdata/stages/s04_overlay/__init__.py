"""S4: the overlay that finalises the text layer — errata, normalization, ref_aliases.

``overlay`` takes the S2 rows and the registries directory (``config/registries``):
it applies the decided errata (``text`` changes at their offsets only), emits
``errata_applied`` and ``ref_aliases`` (both checked against the rows), and
records the normalization rules with their application counts. Nothing here
reads the PDFs again; a registry that does not fit the rows raises OverlayError.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata.stages.s04_overlay import errata, normalization, versification

REPORT_FILE = "overlay_report.json"
REPORT_SCHEMA = "ragdata.overlay_report.v1"


@dataclass(frozen=True)
class OverlayResult:
    rows: Mapping[str, tuple[dict[str, Any], ...]]
    ascii_allowed: Mapping[str, frozenset[str]]
    report: Mapping[str, Any]


def overlay(rows: Mapping[str, Sequence[Mapping[str, Any]]], registries: Path) -> OverlayResult:
    books = {b["book_id"] for b in rows["books"]}
    fixed = errata.apply_errata(rows, errata.load_errata(Path(registries) / "errata.yaml"),
                                books)
    merged = {**{k: tuple(v) for k, v in rows.items()}, **fixed.rows}
    decls = versification.load_aliases(Path(registries) / "versification.yaml")
    aliases = versification.alias_rows(merged, decls, books)
    norm = normalization.load_normalization(Path(registries) / "normalization.yaml")
    out = {**merged, "errata_applied": fixed.applied, "ref_aliases": aliases}
    report = {"schema": REPORT_SCHEMA, "errata": fixed.report,
              "normalization": normalization.report(norm, out),
              "ref_aliases": {"declared": len(decls), "emitted": len(aliases)}}
    return OverlayResult(MappingProxyType(out), norm.ascii_allowed, report)


def encode_report(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()
