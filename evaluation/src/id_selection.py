"""A run's question subset from an ids file (``--ids-file``).

The file is a JSON list of question ids, or plain text with one id per line
(any whitespace separates ids; blank lines are ignored). Repeated ids count
once. An empty file, a JSON value that is not a list of strings, or an id the
ground truth does not have is refused: a subset run never quietly asks fewer
questions than the file names.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from .models import GroundTruthItem


class IdsFileError(ValueError):
    """The ids file cannot be read, is empty or malformed, or names unknown ids."""


def parse_ids_text(text: str) -> tuple[str, ...]:
    """Ids in file order, each once."""
    stripped = text.strip()
    if stripped.startswith("{"):
        raise IdsFileError("a JSON object is not an ids list (give a JSON list or one id per line)")
    if stripped.startswith("["):
        try:
            ids = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise IdsFileError(f"not a JSON list: {exc}") from None
        if not all(isinstance(i, str) and i.strip() for i in ids):
            raise IdsFileError("the JSON list must hold non-empty strings only")
        ids = [i.strip() for i in ids]
    else:
        ids = stripped.split()
    if not ids:
        raise IdsFileError("names no question ids")
    return tuple(dict.fromkeys(ids))


def read_ids_file(path: Path) -> tuple[str, ...]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise IdsFileError(f"cannot read {path}: {exc}") from None
    return parse_ids_text(text)


def select_questions(items: Iterable[GroundTruthItem],
                     ids: Sequence[str] | None) -> list[GroundTruthItem]:
    """The items ``ids`` names, in ground-truth order (every item when ``ids`` is None)."""
    items = list(items)
    if ids is None:
        return items
    unknown = sorted(set(ids) - {item.question_id for item in items})
    if unknown:
        raise IdsFileError(f"unknown question ids: {unknown}")
    wanted = set(ids)
    return [item for item in items if item.question_id in wanted]
