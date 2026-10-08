"""The R1 evaluation's frozen question sets (experiments/2026-10-08_r1/prereg.md).

``experiments/2026-10-08_r1/freeze_r1.py`` derives ``frozen_r1.json`` from the
text layer's diff report and GT v2 before any R1 result exists. Tools that
score the R1 arms read the sets back through :func:`load_frozen` only, which
accepts only the bytes :data:`FROZEN_R1_SHA256` pins, and only while they
record the GT v2 sha256 and slot_universe that ``config/gold/gt_v2_freeze.json``
pins. So a gate never scores a slice re-derived or edited after the results,
or one of another GT; new sets take ``freeze_r1.py --force`` and a new pin here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, NamedTuple

from .gt_v2 import FREEZE_PATH

SCHEMA = "evaluation.r1_frozen.v1"
SUB_SLICES = ("G01", "G15", "G02")
FROZEN_R1_PATH = (Path(__file__).resolve().parent.parent
                  / "experiments" / "2026-10-08_r1" / "frozen_r1.json")
# sha256 of the pre-registered frozen_r1.json bytes; re-pin only for a re-freeze made
# before any R1 result exists.
FROZEN_R1_SHA256 = "6ad9c464b9750057a37c54ab8b80c15779b2c235c7ed6a4b61af43b3e70301c0"


class FrozenR1Error(ValueError):
    """frozen_r1.json cannot be read, is not the pinned freeze, or contradicts itself."""


class FrozenR1(NamedTuple):
    damaged_union: frozenset[str]
    sub_slices: Mapping[str, frozenset[str]]
    gans_subset: frozenset[str]


def _ids(block: dict, where: str) -> frozenset[str]:
    qids = block["question_ids"]
    if len(set(qids)) != len(qids) or len(qids) != block["n_questions"]:
        raise FrozenR1Error(f"{where}: question_ids repeat or disagree with n_questions")
    return frozenset(qids)


def _check_gt(doc: dict, path: Path | str) -> None:
    """The freeze must record the GT v2 sha256 and slot_universe FREEZE_PATH pins."""
    try:
        pinned = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenR1Error(f"cannot read GT v2 freeze record {FREEZE_PATH}: {exc}") from None
    gt = doc["gt"] if isinstance(doc.get("gt"), dict) else {}
    for field in ("sha256", "slot_universe"):
        if gt.get(field) != pinned.get(field):
            raise FrozenR1Error(f"{path}: gt.{field} {gt.get(field)!r} is not GT v2's frozen "
                                f"{pinned.get(field)!r} ({FREEZE_PATH})")


def load_frozen(path: Path | str = FROZEN_R1_PATH) -> FrozenR1:
    """Read frozen_r1.json → ``FrozenR1(damaged_union, sub_slices, gans_subset)``.

    A NamedTuple, so it unpacks as a 3-tuple or reads by name:

    * ``damaged_union``: frozenset of question ids, the damaged slice
      (受損切片) G01 ∪ G15 ∪ G02, 64 ids. C3 scores this set only.
    * ``sub_slices``: read-only mapping ``"G01" | "G15" | "G02"`` → frozenset
      of question ids (56 / 11 / 9), reported separately.
    * ``gans_subset``: frozenset of question ids, the G-ANS answer-side
      subset, 200 ids.

    Raises FrozenR1Error when the file cannot be read, is not
    ``evaluation.r1_frozen.v1``, records another GT v2 sha256 or slot_universe
    than the freeze record, its lists disagree with its counts or the union
    with its sub-slices, or (checked last) its bytes are not FROZEN_R1_SHA256.
    """
    try:
        data = Path(path).read_bytes()
        doc = json.loads(data)
    except (OSError, ValueError) as exc:
        raise FrozenR1Error(f"cannot read {path}: {exc}") from None
    if doc.get("schema") != SCHEMA:
        raise FrozenR1Error(f"{path}: schema {doc.get('schema')!r}, not {SCHEMA!r}")
    _check_gt(doc, path)
    try:
        damaged = doc["damaged_slice"]
        subs = {name: _ids(damaged["sub_slices"][name], name) for name in SUB_SLICES}
        union = _ids(damaged["union"], "union")
        gans = _ids(doc["gans_subset"], "gans_subset")
    except (KeyError, TypeError) as exc:
        raise FrozenR1Error(f"{path}: missing or malformed field {exc}") from None
    if union != frozenset().union(*subs.values()):
        raise FrozenR1Error(f"{path}: damaged union is not G01 ∪ G15 ∪ G02")
    digest = hashlib.sha256(data).hexdigest()
    if digest != FROZEN_R1_SHA256:
        raise FrozenR1Error(f"{path}: sha256 {digest} is not the pinned freeze "
                            f"{FROZEN_R1_SHA256} (src/r1_frozen.py FROZEN_R1_SHA256)")
    return FrozenR1(union, MappingProxyType(subs), gans)
