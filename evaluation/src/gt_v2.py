"""Load ground_truth.v2.json, but only the frozen bytes (design §11.2–11.3).

The file must hash to the sha256 in ``config/gold/gt_v2_freeze.json`` and
declare the same slot_universe; anything else raises, so a run can never score
against an edited or half-written GT. Items are the v1 items plus structured
``refs`` and the gold/omitted slot lists of the slot universe.

The runners reach it through ``data_loader.load_gt("v2")`` (``--gt v2``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from .models import GroundTruthItem

_REPO = Path(__file__).resolve().parent.parent.parent
GT_V2_PATH = _REPO / "ground_truth.v2.json"
FREEZE_PATH = _REPO / "config" / "gold" / "gt_v2_freeze.json"


class GtV2Error(ValueError):
    """GT v2 is not the frozen file, or does not have the v2 shape."""


class VerseRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    book_id: str
    ch: int
    v_start: int | None
    v_end: int | None
    ch_end: int


class GroundTruthItemV2(GroundTruthItem):
    refs: list[VerseRef]
    gold_slots: list[str]
    omitted_slots: list[str]


@dataclass(frozen=True)
class GroundTruthV2:
    items: tuple[GroundTruthItemV2, ...]
    slot_universe: str
    sha256: str
    kay_review: tuple[str, ...]


def _freeze(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GtV2Error(f"cannot read GT v2 freeze record {path}: {exc}") from None


def load_ground_truth_v2(path: Path | None = None,
                         freeze_path: Path | None = None) -> GroundTruthV2:
    data = (path or GT_V2_PATH).read_bytes()
    freeze = _freeze(freeze_path or FREEZE_PATH)
    digest = hashlib.sha256(data).hexdigest()
    if digest != freeze.get("sha256"):
        raise GtV2Error(f"GT v2 sha256 {digest} is not the frozen {freeze.get('sha256')}")
    meta = json.loads(data)["metadata"]
    if meta.get("gt_version") != "v2":
        raise GtV2Error(f"gt_version is {meta.get('gt_version')!r}, not 'v2'")
    if meta.get("slot_universe") != freeze.get("slot_universe"):
        raise GtV2Error(f"slot_universe {meta.get('slot_universe')} is not the frozen "
                        f"{freeze.get('slot_universe')}")
    try:
        items = tuple(GroundTruthItemV2(**q) for q in json.loads(data)["questions"])
    except ValidationError as exc:
        raise GtV2Error(f"GT v2 item does not validate: {exc}") from None
    return GroundTruthV2(items, meta["slot_universe"], digest,
                         tuple(k["qid"] for k in meta.get("kay_review", [])))
