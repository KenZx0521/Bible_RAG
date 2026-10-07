"""The GT v2 change log (``config/gold/gt_v2_changes.jsonl``).

A change replaces ``before`` with ``after`` at ``offset`` of one answer field
(``reference_answer`` or ``expected_answer_points[i]``) of one question, or adds
a field that v1 lacks (``family``: ``offset`` and ``before`` are null). Changes
are listed in the order they were applied and each offset is valid at its turn,
so replaying the log on v1 gives v2 and replaying it backwards gives v1 again.
Every step checks that the text it replaces is there; a log that does not fit
raises instead of producing a third version.
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

POINTS = "expected_answer_points"
TEXT_FIELD_RE = re.compile(rf"reference_answer|{POINTS}\[(0|[1-9][0-9]*)\]")
ADDED_FIELDS = frozenset({"family"})
KEYS = ("qid", "field", "offset", "before", "after", "rule", "evidence_slot")


class ChangeError(ValueError):
    """A change that does not fit the question it names."""


@dataclass(frozen=True)
class Edit:
    """Replace ``value[start:end]`` with ``after``; ``evidence_slot`` backs the new text."""

    start: int
    end: int
    after: str
    evidence_slot: str | None


@dataclass(frozen=True)
class Change:
    qid: str
    field: str
    offset: int | None
    before: str | None
    after: str | None
    rule: str
    evidence_slot: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def change_from_json(row: Mapping[str, Any]) -> Change:
    if set(row) != set(KEYS):
        raise ChangeError(f"change keys must be {KEYS}, got {sorted(row)}")
    return Change(**{k: row[k] for k in KEYS})


def get_field(question: Mapping[str, Any], field: str) -> Any:
    m = TEXT_FIELD_RE.fullmatch(field)
    if m and m.group(1) is not None:
        points = question[POINTS]
        index = int(m.group(1))
        if index >= len(points):
            raise ChangeError(f"{question['question_id']}: no {field}")
        return points[index]
    return question.get(field)


def set_field(question: dict[str, Any], field: str, value: Any) -> None:
    """Set ``field`` of a working copy in place (None removes an added field)."""
    m = TEXT_FIELD_RE.fullmatch(field)
    if m and m.group(1) is not None:
        question[POINTS][int(m.group(1))] = value
    elif value is None:
        del question[field]
    else:
        question[field] = value


def _check_field(change: Change) -> None:
    if TEXT_FIELD_RE.fullmatch(change.field):
        if not (isinstance(change.offset, int) and isinstance(change.before, str)
                and isinstance(change.after, str)):
            raise ChangeError(f"{change}: a text change needs offset, before and after")
    elif change.field in ADDED_FIELDS:
        if change.offset is not None or change.before is not None:
            raise ChangeError(f"{change}: an added field has no offset or before")
    else:
        raise ChangeError(f"{change.qid}: {change.field} is not an answer field")


def _step(question: dict[str, Any], change: Change, forward: bool) -> None:
    _check_field(change)
    old, new = (change.before, change.after) if forward else (change.after, change.before)
    current = get_field(question, change.field)
    if change.offset is None:
        if current != old:
            raise ChangeError(f"{change.qid}: {change.field} is already {current!r}")
        set_field(question, change.field, new)
        return
    end = change.offset + len(old)
    if current is None or current[change.offset:end] != old:
        raise ChangeError(f"{change.qid}: {change.field}[{change.offset}:{end}] == {old!r} "
                          f"does not hold")
    set_field(question, change.field, current[:change.offset] + new + current[end:])


def _run(questions: Sequence[Mapping[str, Any]], changes: Iterable[Change],
         forward: bool) -> list[dict[str, Any]]:
    out = [copy.deepcopy(dict(q)) for q in questions]
    by_id = {q["question_id"]: q for q in out}
    for change in changes:
        if change.qid not in by_id:
            raise ChangeError(f"no question {change.qid}")
        _step(by_id[change.qid], change, forward)
    return out


def apply_changes(questions: Sequence[Mapping[str, Any]],
                  changes: Iterable[Change]) -> list[dict[str, Any]]:
    """Replay the log forwards on copies of ``questions``."""
    return _run(questions, list(changes), forward=True)


def revert_changes(questions: Sequence[Mapping[str, Any]],
                   changes: Iterable[Change]) -> list[dict[str, Any]]:
    """Undo the log, last change first, on copies of ``questions``."""
    return _run(questions, list(reversed(list(changes))), forward=False)


def apply_edits(qid: str, field: str, value: str, edits: Iterable[Edit],
                rule: str) -> tuple[str, list[Change]]:
    """Apply non-overlapping edits right to left; return the new value and its changes."""
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for left, right in zip(ordered, ordered[1:]):
        if right.start < left.end:
            raise ChangeError(f"{qid} {field}: edits overlap at {right.start}")
    changes = []
    for edit in reversed(ordered):
        before = value[edit.start:edit.end]
        if before == edit.after:
            continue
        changes.append(Change(qid, field, edit.start, before, edit.after, rule,
                              edit.evidence_slot))
        value = value[:edit.start] + edit.after + value[edit.end:]
    return value, changes
