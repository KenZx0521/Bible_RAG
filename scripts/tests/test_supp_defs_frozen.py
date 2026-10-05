"""The 161 supplementary definitions of a32fbea are frozen as JSON.

1B rewrote SUPPLEMENTARY_CROSS_REFS in verse coordinates. The archived
evidence scripts that measured the old definitions read
docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json instead of the
live module, so they replay on any HEAD (README of that directory). The
ledger test pins the live list to the mechanical conversion of the frozen one
plus each documented change; the file's sha256 (the one w1_1B/README.md
records) pins its bytes, so an edit made to it and the live list alike fails.
"""

import hashlib
import json
import re
from pathlib import Path

from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "docs/records/2026-10-04_kg_fix"
FROZEN = RECORDS / "xref/supp_defs_a32fbea.json"
FROZEN_SHA256 = "aa1d76c058031726c0672d81f77b5c5f4123411f2e4d27ed2ef530119d9de9ea"
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


def test_frozen_definitions_bytes_match_the_recorded_sha256():
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_SHA256
    readme = (RECORDS / "batch1/w1_1B/README.md").read_text(encoding="utf-8")
    assert f"| `xref/supp_defs_a32fbea.json` | `{FROZEN_SHA256}` |" in readme


def test_archived_scripts_do_not_import_live_definitions():
    for path in ARCHIVED:
        source = path.read_text(encoding="utf-8")
        assert not LIVE_MODULE.search(source), path
        assert "docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json" in source, path


# Changes to the a32fbea definitions, keyed by the converted (src, tgt); each
# lands in the commit that makes it, with its evidence in that commit.
DELETED: set[tuple[str, str]] = {
    # XREF-2 (1B-C5a): no verse-level TSK support in either direction (60-verse
    # cap, w1_1B/sup_s3.py). TSK Rev.20.4 points nowhere in Isaiah (新天新地 is
    # rev 21:1 → isa 65:17, its own definition); Ps 118:1 has no 哈利路亞 and
    # TSK Rev.19.1 points to eight other psalms, never Ps 118.
    ("rev 20:4", "isa 65:17"),
    ("rev 19:1", "psa 118:1"),
}
RETARGETED: dict[tuple[str, str], tuple[str, str]] = {
    # X2 (1B-C5b, D10 (a)): no verse of rev 19:11-16 has TSK to dan 7:13-14
    # (w1_1B/sup_s3.py). 萬王之王萬主之主 is rev 19:16, and TSK Rev.19.16 →
    # Dan.2.47 萬神之神、萬王之主 has votes 8 (reverse 3). rev:19:2 → dan:7:1
    # stays a TSK edge (Rev.19.20 → Dan.7.7-14, votes 8).
    ("rev 19:11-16", "dan 7:13-14"): ("rev 19:16", "dan 2:47"),
}


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
