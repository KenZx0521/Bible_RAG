"""Field checks and the frozen record base shared by every snapshot contract.

A record type is a frozen dataclass whose fields are declared with ``spec()``.
``parse()`` turns one JSON row into a record: the key set must match the
fields exactly, every value goes through its field check (which also freezes
it: lists become tuples, objects become nested records or read-only mappings),
and then the record's own ``check()`` enforces cross-field invariants.
Any violation raises ``ContractError`` naming the field.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from ragcommon import ids

Check = Callable[[Any], Any]
HEX64 = frozenset("0123456789abcdef")


class ContractError(ValueError):
    """A snapshot row violates its record contract."""


@dataclasses.dataclass(frozen=True)
class Record:
    """Base class: subclasses add ``spec()`` fields and override ``check()``."""

    def check(self) -> None:
        return None


def spec(check: Check, key: str | None = None) -> Any:
    """Declare a record field; ``key`` is the JSON name when it differs."""
    return dataclasses.field(metadata={"check": check, "key": key})


def _json_key(field: dataclasses.Field) -> str:
    return field.metadata.get("key") or field.name


def parse(cls: type[Record], raw: Any) -> Record:
    if not isinstance(raw, Mapping):
        raise ContractError(f"{cls.__name__}: row must be a JSON object, got {type(raw).__name__}")
    fields = dataclasses.fields(cls)
    expected = {_json_key(f) for f in fields}
    missing, unknown = expected - set(raw), set(raw) - expected
    if missing or unknown:
        raise ContractError(f"{cls.__name__}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    values = {}
    for f in fields:
        try:
            values[f.name] = f.metadata["check"](raw[_json_key(f)])
        except ContractError as exc:
            raise ContractError(f"{_json_key(f)}: {exc}") from None
    record = cls(**values)
    try:
        record.check()
    except ids.IdError as exc:
        raise ContractError(f"{cls.__name__}: {exc}") from None
    return record


def _thaw(value: Any) -> Any:
    if isinstance(value, Record):
        return record_to_dict(value)
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    return value


def record_to_dict(record: Record) -> dict[str, Any]:
    """The JSON row of a record (inverse of ``parse``)."""
    return {_json_key(f): _thaw(getattr(record, f.name)) for f in dataclasses.fields(record)}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


# ------------------------------------------------------------------ field checks


def integer(minimum: int = 0, maximum: int | None = None) -> Check:
    def check(value: Any) -> int:
        require(isinstance(value, int) and not isinstance(value, bool),
                f"expected an integer, got {value!r}")
        require(value >= minimum and (maximum is None or value <= maximum),
                f"{value} outside [{minimum}, {maximum}]")
        return value
    return check


def number() -> Check:
    def check(value: Any) -> float | int:
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value), f"expected a finite number, got {value!r}")
        return value
    return check


def boolean() -> Check:
    def check(value: Any) -> bool:
        require(isinstance(value, bool), f"expected a boolean, got {value!r}")
        return value
    return check


def string() -> Check:
    """A non-empty string."""
    def check(value: Any) -> str:
        require(isinstance(value, str) and value != "", f"expected a non-empty string, got {value!r}")
        return value
    return check


def hex64() -> Check:
    def check(value: Any) -> str:
        require(isinstance(value, str) and len(value) == 64 and set(value) <= HEX64,
                f"expected 64 lowercase hex digits, got {value!r}")
        return value
    return check


def one_of(*allowed: Any) -> Check:
    choices = frozenset(allowed)

    def check(value: Any) -> Any:
        require(value in choices, f"{value!r} not in {sorted(map(str, choices))}")
        return value
    return check


def id_of(kind: str) -> Check:
    """An id that ``ragcommon.ids`` accepts as ``kind`` (or role)."""
    def check(value: Any) -> str:
        try:
            ids.validate(value, kind)
        except ids.IdError as exc:
            raise ContractError(str(exc)) from None
        return value
    return check


def optional(inner: Check) -> Check:
    def check(value: Any) -> Any:
        return None if value is None else inner(value)
    return check


def list_of(inner: Check, min_len: int = 0, length: int | None = None) -> Check:
    def check(value: Any) -> tuple:
        require(isinstance(value, list), f"expected a list, got {type(value).__name__}")
        require(len(value) >= min_len, f"expected at least {min_len} items")
        require(length is None or len(value) == length, f"expected exactly {length} items")
        items = []
        for i, item in enumerate(value):
            try:
                items.append(inner(item))
            except ContractError as exc:
                raise ContractError(f"[{i}]: {exc}") from None
        return tuple(items)
    return check


def nested(cls: type[Record]) -> Check:
    def check(value: Any) -> Record:
        return parse(cls, value)
    return check


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def json_object() -> Check:
    """A free-form JSON object, frozen into a read-only mapping."""
    def check(value: Any) -> Mapping[str, Any]:
        require(isinstance(value, Mapping), f"expected a JSON object, got {type(value).__name__}")
        return _freeze(value)
    return check


# ------------------------------------------------------------------ shared invariants


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_dual_text(text_pdf: str, text: str, errata_ids: Iterable[str] | None = None) -> None:
    """§2.0: ``text`` and ``text_pdf`` have equal length; they differ only through errata."""
    require(len(text_pdf) == len(text), f"text ({len(text)}) and text_pdf ({len(text_pdf)}) "
            "must have equal length")
    if errata_ids is not None and not tuple(errata_ids):
        require(text == text_pdf, "text differs from text_pdf but errata_ids is empty")


def parsed(raw: str):
    """``ids.parse`` for a value a field check already validated."""
    return ids.parse(raw)


def verse_order(raw: str) -> tuple[int, int, bool]:
    p = parsed(raw)
    return (p.chapter, p.verse, p.half)
