"""The committed GT v2 passes G-GT against the text layer it was frozen on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragdata.gt.cli import DEFAULTS, gate_files
from ragdata.store import DEFAULT_ROOT

UNIVERSE = json.loads(DEFAULTS["freeze"].read_text(encoding="utf-8"))["slot_universe"]
LAYER = Path(DEFAULT_ROOT) / "text" / UNIVERSE


@pytest.mark.skipif(not LAYER.is_dir(), reason=f"text layer {UNIVERSE} not in the store")
def test_committed_gt_v2_passes_g_gt():
    report = gate_files(DEFAULTS["out"], LAYER, DEFAULTS["v1"], DEFAULTS["changes"],
                        DEFAULTS["freeze"])
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    assert {g.name for g in report.gates if g.passed} >= {"G-GT.refs", "G-GT.freeze"}
