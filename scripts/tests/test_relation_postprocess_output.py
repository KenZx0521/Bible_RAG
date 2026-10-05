"""Step 6.05 on the real output/ inputs (gitignored build products).

The counts are pinned to the W1 inputs: they hold only when output/ is the
batch-1 W1 snapshot, so the module-scoped run is skipped unless every input's
sha256 equals its pin (the run reads ~175k mention rows, so it happens once
per module). The hash-seed test only needs the inputs to exist.

None mode is the K8 staging-P1 control: its edge set after 10.2 is what the
batch-0 staging build (bolt://localhost:7688) holds per phase, rule 772 /
prior 64 / llm 5,278 / inverse 752 (read 2026-10-05; the 9,060 phase-5
cooccurrence edges come from 10.3, not from relations.jsonl).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from relation_extraction import relation_postprocess as pp

ROOT = Path(__file__).resolve().parents[2]
W1_PINS = {
    "relations": "fe7f0cfda391991a1d9768c3f4b4dce18df2e033b4bc68dbc353d8b188730f5c",
    "entities": "9f2d1f39251d9a3ce5834f52d129bda8e13cd2e1afdfa30d04962d23c7034142",
    "mentions": "ba7ed1884355e3f8d60952b4e89bff6c6dfb094818caee168dd5c387cd9e896c",
    "chunks": "46ca73105170489182c3bfb5c0ed6fbcef3083a21634197e0b9b62976a154f12",
    "pericopes": "2e46fea4817c538ae4b5b4c6535491277674dc140c8b81dbf2fec8235a038c2c",
}
# edge_set_sha256 of the none-mode rows left after 10.2 (6,866 lines). Computed
# independently on 2026-10-05 from both relations.jsonl minus the generic-event
# rows and the 7688 edges (source from phase 2/3/4/5); the two line sets were equal.
NONE_AFTER_10_2_SHA256 = "7fde48c7b815c1839d32adc64e005985e09c4e1d271caa66d0efa8ec010392f5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inputs_present() -> bool:
    return all(path.exists() for path in pp.default_paths().values())


@pytest.fixture(scope="module")
def real_inputs():
    """(Inputs, Config) of the default paths; skipped unless output/ is the W1 snapshot."""
    paths = pp.default_paths()
    if not _inputs_present():
        pytest.skip("output/ JSONL artifacts are not present (gitignored build products)")
    drifted = [name for name, pin in W1_PINS.items() if _sha256(paths[name]) != pin]
    if drifted:
        pytest.skip(f"output/ is not the W1 snapshot: {drifted} differ from their pins")
    return pp.load_inputs(paths)


@pytest.fixture(scope="module")
def none_run(real_inputs):
    return pp.postprocess(*real_inputs, "none")


def test_none_mode_counts(none_run):
    rows, report = none_run
    assert report["flow"]["input"] == report["flow"]["output"] == len(rows) == 6958
    assert report["output"]["by_source"] == {"inverse": 752, "llm": 5370, "prior": 64, "rule": 772}

    after = report["expected_after_10_2"]
    assert len(after["generic_event_ids"]) == 16
    assert (after["edges_on_generic_events"], after["edges"]) == (92, 6866)
    by_phase = Counter()
    for key, n in after["by_ee_key"].items():
        by_phase[key.split(" ", 1)[1]] += n
    assert by_phase == {"phase=2 source=rule": 772, "phase=3 source=prior": 64,
                        "phase=4 source=llm": 5278, "phase=5 source=inverse": 752}
    assert after["edge_set_sha256"] == NONE_AFTER_10_2_SHA256


@pytest.mark.skipif(not _inputs_present(), reason="output/ JSONL artifacts are not present")
def test_none_mode_is_byte_identical_across_hash_seeds(tmp_path):
    out, report = tmp_path / "relations_clean.jsonl", tmp_path / "relations_clean.report.json"
    runs = []
    for seed in ("1", "987"):
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.relation_extraction.relation_postprocess", "--rules", "none",
             "--out", str(out), "--report", str(report)],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONHASHSEED": seed})
        assert proc.returncode == 0, proc.stderr
        runs.append((out.read_bytes(), report.read_bytes()))
    assert runs[0] == runs[1]
