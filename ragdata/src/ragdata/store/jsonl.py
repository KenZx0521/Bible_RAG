"""Canonical JSONL: one object per line, sorted keys, UTF-8, newline-terminated."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


class StoreError(ValueError):
    """A store operation or a stored file breaks the store contract."""


def encode_jsonl(rows: Iterable[Mapping[str, Any]]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
             for row in rows]
    return "".join(line + "\n" for line in lines).encode("utf-8")


def decode_jsonl(data: bytes, name: str) -> tuple[dict[str, Any], ...]:
    """Decode strictly: no blank lines, every line an object, final newline required."""
    if not data:
        return ()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreError(f"{name}: not UTF-8: {exc}") from None
    if not text.endswith("\n"):
        raise StoreError(f"{name}: missing final newline")
    rows = []
    for number, line in enumerate(text[:-1].split("\n"), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StoreError(f"{name}:{number}: invalid JSON: {exc.msg}") from None
        if not isinstance(row, dict):
            raise StoreError(f"{name}:{number}: expected a JSON object")
        rows.append(row)
    return tuple(rows)
