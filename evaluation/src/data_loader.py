"""Ground truth for a run: v1 (ground_truth.json) or the frozen v2.

``load_gt(version)`` takes the version from the CLI (``--gt v1|v2``) or, when
none is given, from the EVAL_GT_VERSION setting. v2 always goes through
gt_v2's sha256 and freeze checks. The returned set carries the version and
the sha256 of the bytes it was read from, which every result records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .gt_v2 import load_ground_truth_v2
from .models import GroundTruthItem

_GT_PATH = Path(__file__).resolve().parent.parent.parent / "ground_truth.json"
GT_VERSIONS = ("v1", "v2")


@dataclass(frozen=True)
class GroundTruthSet:
    version: str
    sha256: str
    items: tuple[GroundTruthItem, ...]
    slot_universe: str | None = None    # v2 only: the text layer its slots belong to

    def by_id(self) -> dict[str, GroundTruthItem]:
        return {item.question_id: item for item in self.items}

    def meta(self) -> dict[str, str]:
        return {"gt_version": self.version, "gt_sha": self.sha256}


def load_ground_truth(path: Path | None = None) -> list[GroundTruthItem]:
    """The v1 items (ground_truth.json)."""
    return list(_load_v1(path or _GT_PATH).items)


def _load_v1(path: Path) -> GroundTruthSet:
    data = path.read_bytes()
    items = tuple(GroundTruthItem(**q) for q in json.loads(data)["questions"])
    return GroundTruthSet("v1", hashlib.sha256(data).hexdigest(), items)


def load_gt(version: str | None = None) -> GroundTruthSet:
    """Load GT ``version`` (default: the EVAL_GT_VERSION setting)."""
    chosen = version or settings.eval_gt_version
    if chosen == "v1":
        return _load_v1(_GT_PATH)
    if chosen == "v2":
        gt = load_ground_truth_v2()
        return GroundTruthSet("v2", gt.sha256, gt.items, gt.slot_universe)
    raise ValueError(f"unknown GT version {chosen!r}; choose one of {GT_VERSIONS}")
