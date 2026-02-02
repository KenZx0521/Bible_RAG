"""
Load ground_truth.json from the project root.
"""

import json
from pathlib import Path

from .models import GroundTruthItem

_GT_PATH = Path(__file__).resolve().parent.parent.parent / "ground_truth.json"


def load_ground_truth(path: Path | None = None) -> list[GroundTruthItem]:
    """Load and parse the ground truth dataset."""
    p = path or _GT_PATH
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return [GroundTruthItem(**q) for q in data["questions"]]
