"""Pieces shared by the validate_kg tests, split from test_validate_kg.py.

test_validate_kg_checks.py (each check on the kg_snapshot fixture),
test_validate_kg_gate.py (exit codes, ratchet, CLI, live) and
test_validate_kg_shipped.py (the shipped config files) import from here.
snap is a pytest fixture: a test module gets it by importing it.

Exit codes and ratchet direction run through main() against a baseline built
from the shipped config/kg_quality_baseline/ with its values cleared, so the
shipped severities/directions are what is being tested.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import validate_kg as vk

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kg_snapshot"
REPO = Path(__file__).resolve().parents[2]
SHIPPED_BASELINE = REPO / "config" / "kg_quality_baseline"
SHIPPED_PROBES = REPO / "config" / "kg_probes.yaml"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def snap(tmp_path: Path) -> Path:
    dest = tmp_path / "snap"
    shutil.copytree(FIXTURE, dest)
    return dest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def append_row(path: Path, row: dict) -> None:
    write_rows(path, read_rows(path) + [row])


def edit_rows(path: Path, match, **changes) -> None:
    rows = read_rows(path)
    hit = 0
    for r in rows:
        if match(r):
            r.update(changes)
            hit += 1
    assert hit, f"no row matched in {path.name}"
    write_rows(path, rows)


def write_step0_sha(path: Path, sha: str) -> None:
    path.write_text(json.dumps({"version": 1, "files": {"embedding_queue.jsonl": {"sha256": sha}}}),
                    encoding="utf-8")


def fresh_baseline(tmp_path: Path, snap: Path) -> Path:
    """Shipped specs with every value cleared; H7's sha target (step0_sha.json
    next to the baseline, see cli) = the fixture's. Written as one file: the
    shipped parts merged, exactly as the gate reads them."""
    doc = vk.load_baseline(SHIPPED_BASELINE)
    for check in doc["checks"]:
        for metric in check["metrics"].values():
            metric["value"] = None
    write_step0_sha(tmp_path / "step0_sha.json", _sha(snap / "embedding_queue.jsonl"))
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def measure(snap: Path, baseline: Path | None = None) -> dict:
    ctx = vk.Context(
        baseline=vk.load_baseline(baseline or SHIPPED_BASELINE),
        probes=vk.load_probes(snap / "probes.yaml"),
        embedding_queue=snap / "embedding_queue.jsonl",
    )
    return vk.run_checks(vk.load_snapshot(snap), ctx)


def metric(results: dict, check_id: str, name: str):
    return results[check_id].metrics[name]


def argv(snap: Path, baseline: Path, *extra: str) -> list[str]:
    return ["--snapshot", str(snap), "--baseline", str(baseline), "--probes", str(snap / "probes.yaml"),
            "--embedding-queue", str(snap / "embedding_queue.jsonl"),
            "--step0-sha", str(baseline.with_name("step0_sha.json")), "--json", *extra]


def cli(snap: Path, baseline: Path, capsys, *extra: str) -> tuple[int, dict]:
    code = vk.main(argv(snap, baseline, *extra))
    return code, json.loads(capsys.readouterr().out)


def unsupported_edge(**over) -> dict:
    """馬可 VISITED 摩利亞, sourced from gen:22:0 where 馬可 is never mentioned.

    Deliberately not a kinship edge, so it moves H3 and nothing else (R6's
    functionality rate would change with a FATHER_OF)."""
    row = {"head_id": "person:make", "relation": "VISITED", "tail_id": "place:moliya",
           "source_pericope_id": "gen:22:0", "extraction_phase": 4, "notes": ""}
    row.update(over)
    return row


def _stored(baseline: Path, check_id: str, name: str):
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    return next(c for c in doc["checks"] if c["id"] == check_id)["metrics"][name]["value"]
