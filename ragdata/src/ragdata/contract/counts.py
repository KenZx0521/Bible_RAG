"""Load count expectations (``expectations/pdf_counts.yaml``) for G-COUNT.

Each entry is ``{value, g, evidence?, definition?}``: ``value`` is a non-negative
integer or a list of ids, ``g`` names the audit findings behind it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, NamedTuple

import yaml

from ragdata.contract.registry import LAYERS

PDF_COUNTS_PATH = Path(__file__).resolve().parent / "expectations" / "pdf_counts.yaml"
SCHEMA = "ragdata.pdf_counts.v1"
_G_RE = re.compile(r"G[0-9]{2}")
_ENTRY_KEYS = {"value", "g", "evidence", "definition"}


class CountsError(ValueError):
    """The expectation file is malformed."""


class Expectation(NamedTuple):
    value: int | tuple[str, ...]
    g: tuple[str, ...]
    evidence: str | None = None
    definition: str | None = None


def _value(raw: Any, where: str) -> int | tuple[str, ...]:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    if isinstance(raw, list) and all(isinstance(v, str) and v for v in raw):
        return tuple(raw)
    raise CountsError(f"{where}: value must be a non-negative integer or a list of ids")


def _entry(raw: Any, where: str) -> Expectation:
    if not isinstance(raw, dict) or not {"value", "g"} <= set(raw) <= _ENTRY_KEYS:
        raise CountsError(f"{where}: entry needs value and g (optional evidence, definition)")
    g = raw["g"]
    if not isinstance(g, list) or not g or not all(isinstance(x, str) and _G_RE.fullmatch(x)
                                                   for x in g):
        raise CountsError(f"{where}: g must list audit findings like G12")
    texts = [raw.get(k) for k in ("evidence", "definition")]
    if any(t is not None and not (isinstance(t, str) and t) for t in texts):
        raise CountsError(f"{where}: evidence/definition must be non-empty strings")
    return Expectation(_value(raw["value"], where), tuple(g), *texts)


def load_counts(path: Path | str = PDF_COUNTS_PATH) -> Mapping[str, Mapping[str, Expectation]]:
    """Return ``{layer: {count key: Expectation}}``; raise CountsError when malformed."""
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise CountsError(f"{path}: schema must be {SCHEMA}")
    sections = {k: v for k, v in doc.items() if k != "schema"}
    unknown = set(sections) - set(LAYERS)
    if unknown:
        raise CountsError(f"{path}: unknown layers {sorted(unknown)}")
    result = {}
    for layer, entries in sections.items():
        if not isinstance(entries, dict):
            raise CountsError(f"{path}: {layer} must map count keys to entries")
        result[layer] = MappingProxyType(
            {key: _entry(raw, f"{layer}.{key}") for key, raw in entries.items()})
    return MappingProxyType(result)
