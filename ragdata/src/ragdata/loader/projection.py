"""Comparing a projection with its snapshot (G-PROJ C2, C3; design §7.7). No database here.

Rows are compared by id through the sha256 of their normalized JSON: keys sorted,
strings NFC, a float with an integral value written as an integer (a jsonb
``1.0`` and a JSON ``1`` are the same number), and the fields that
``projection_exempt_fields.yaml`` lists for that side left out. Any other field
that is missing, extra or different makes the row differ.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

EXEMPT_PATH = Path(__file__).resolve().parents[1] / "contract" / "projection_exempt_fields.yaml"
EXEMPT_SCHEMA = "ragdata.projection_exempt.v1"
SIDES = ("snapshot", "projection")
MAX_LISTED = 20


class ProjectionError(ValueError):
    """The exemption file is malformed."""


@dataclass(frozen=True)
class Exempt:
    snapshot: frozenset[str] = frozenset()      # fields the snapshot has and the projection not
    projection: frozenset[str] = frozenset()    # fields only the projection has


NONE = Exempt()


def _sides(where: str, doc: Any) -> Exempt:
    if not isinstance(doc, dict) or not set(doc) <= set(SIDES) \
            or not all(isinstance(doc[s], dict) and doc[s] for s in doc):
        raise ProjectionError(f"{where}: expected snapshot/projection maps of field: reason")
    return Exempt(*(frozenset(doc.get(side, {})) for side in SIDES))


def load_exempt(path: Path = EXEMPT_PATH) -> Mapping[str, Mapping[str, Exempt]]:
    """{store: {table: Exempt}} from the exemption file."""
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectionError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != EXEMPT_SCHEMA:
        raise ProjectionError(f"{path}: not {EXEMPT_SCHEMA}")
    stores = {k: v for k, v in doc.items() if k != "schema"}
    if not all(isinstance(v, dict) for v in stores.values()):
        raise ProjectionError(f"{path}: expected store: table: sides")
    return MappingProxyType({store: MappingProxyType(
        {t: _sides(f"{store}.{t}", s) for t, s in tables.items()})
        for store, tables in stores.items()})


def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, (float, Decimal)):
        number = float(value)
        return int(number) if number.is_integer() else number
    if isinstance(value, Mapping):
        return {normalize(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    raise ProjectionError(f"cannot normalize a {type(value).__name__}")


def row_hash(row: Mapping[str, Any], drop: Iterable[str] = ()) -> str:
    dropped = set(drop)
    kept = {k: v for k, v in row.items() if k not in dropped}
    text = json.dumps(normalize(kept), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def id_violations(what: str, expected: Iterable[str], found: Iterable[str]) -> list[str]:
    """C2: the id sets are equal (and the projection has no id twice)."""
    found = list(found)
    want, got = set(expected), set(found)
    out = [f"{what}: missing {i}" for i in sorted(want - got)[:MAX_LISTED]]
    out += [f"{what}: unexpected {i}" for i in sorted(got - want)[:MAX_LISTED]]
    if len(got) != len(found):
        out.append(f"{what}: {len(found) - len(got)} duplicate ids")
    return out


def row_violations(what: str, expected: Mapping[str, Mapping[str, Any]],
                   found: Mapping[str, Mapping[str, Any]], exempt: Exempt = NONE) -> list[str]:
    """C3: every expected id is there with the same normalized row (exempt fields aside);
    an id the projection lacks cannot be checked, so it counts against C3 too."""
    unchecked = len(set(expected) - set(found))
    out = [f"{what}: {unchecked} rows not in the projection, fields unchecked"] if unchecked \
        else []
    for key in sorted(set(expected) & set(found)):
        want, got = expected[key], found[key]
        if row_hash(want, exempt.snapshot) != row_hash(got, exempt.projection):
            fields = sorted(k for k in {*want, *got} - exempt.snapshot - exempt.projection
                            if normalize(want.get(k)) != normalize(got.get(k))
                            or (k in want) != (k in got))
            out.append(f"{what} {key}: differs in {fields}")
    return out
