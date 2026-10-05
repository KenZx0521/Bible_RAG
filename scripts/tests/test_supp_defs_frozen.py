"""The 161 supplementary definitions of a32fbea are frozen as JSON.

1B rewrote SUPPLEMENTARY_CROSS_REFS in verse coordinates. The archived
evidence scripts that measured the old definitions read
docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json instead of the
live module, so they replay on any HEAD (README of that directory). The
ledger test pins the live list to the mechanical conversion of the frozen one
plus each documented change.
"""

import json
import re
from pathlib import Path

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
# The module name, not "_supplement_cross_references" (process_bible's method
# until 1B-C4a, which two docstrings and comments cite and which contains it as
# a suffix).
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


# Changes to the a32fbea definitions, keyed by the converted (src, tgt); each
# lands in the commit that makes it, with its evidence in that commit.
DELETED: set[tuple[str, str]] = set()
RETARGETED: dict[tuple[str, str], tuple[str, str]] = {}


def _converted(row) -> tuple[str, str]:
    """The mechanical conversion: 'mat:1:2' + '22-23' → 'mat 1:22-23', both ends."""
    ends = []
    for pid, verses in ((row["source_pericope_id"], row["source_verses"]),
                        (row["target_pericope_id"], row["target_verses"])):
        book, chapter, _ = pid.split(":")
        ends.append(f"{book} {chapter}:{verses}")
    return ends[0], ends[1]


def test_definition_ledger():
    converted = [_converted(row) for row in _frozen()]
    assert DELETED | set(RETARGETED) <= set(converted)
    expected = [
        (*RETARGETED.get(ends, ends), row["ref_type"], row["description"], None)
        for ends, row in zip(converted, _frozen()) if ends not in DELETED
    ]
    live = [(ref.src, ref.tgt, ref.ref_type, ref.description, ref.tsk_exempt)
            for ref in SUPPLEMENTARY_CROSS_REFS]
    assert live == expected
