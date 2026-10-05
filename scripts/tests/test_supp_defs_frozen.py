"""The 161 supplementary definitions of a32fbea are frozen as JSON.

1B rewrites SUPPLEMENTARY_CROSS_REFS in verse coordinates. The archived
evidence scripts that measured the old definitions read
docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json instead of the
live module, so they replay on any HEAD (README of that directory).
"""

import json
import re
from pathlib import Path

import pytest

from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "docs/records/2026-10-04_kg_fix"
FROZEN = RECORDS / "xref/supp_defs_a32fbea.json"
KEYS = ["source_pericope_id", "target_pericope_id", "source_verses",
        "target_verses", "ref_type", "description"]
ARCHIVED = [
    RECORDS / "xref/supp.py",
    RECORDS / "verifier_xref/mdpairs.py",
    RECORDS / "batch1/1B/sim_supp.py",
    RECORDS / "batch1/1B-reviewer/r1_supp.py",
    RECORDS / "batch1/w1_1B/sim_w1_1b.py",
    RECORDS / "batch1/w1_1B/sim_states.py",
    RECORDS / "batch1/w1_1B/golden.py",
]
# The module name, not "_supplement_cross_references" (process_bible's method,
# which two docstrings and comments cite and which contains it as a suffix).
LIVE_MODULE = re.compile(r"(?<![A-Za-z0-9_])nt_cross_references")


def _frozen():
    return json.loads(FROZEN.read_text(encoding="utf-8"))


def test_frozen_definitions_shape():
    rows = _frozen()
    assert len(rows) == 161
    assert all(list(row) == KEYS for row in rows)
    assert all(isinstance(v, str) and v for row in rows for v in row.values())


def test_archived_scripts_do_not_import_live_definitions():
    for path in ARCHIVED:
        source = path.read_text(encoding="utf-8")
        assert not LIVE_MODULE.search(source), path
        assert "docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json" in source, path


def test_frozen_equals_live_until_coordinates():
    if not hasattr(SUPPLEMENTARY_CROSS_REFS[0], "source_pericope_id"):
        pytest.skip("live definitions are in verse coordinates; the ledger test covers them")
    live = [{key: getattr(ref, key) for key in KEYS} for ref in SUPPLEMENTARY_CROSS_REFS]
    assert _frozen() == live
