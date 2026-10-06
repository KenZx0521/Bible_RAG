"""Pieces shared by the validate_kg tests, split from test_validate_kg.py.

test_validate_kg_checks.py (each check on the kg_snapshot fixture),
test_validate_kg_gate.py (exit codes, ratchet, CLI, live) and
test_validate_kg_shipped.py (the shipped config files) import from here.
snap is a pytest fixture: a test module gets it by importing it.

Exit codes and ratchet direction run through main() against a baseline built
from the shipped config/kg_quality_baseline/ with its values cleared, so the
shipped severities/directions are what is being tested; a test of the record
mechanics that breaks a hard check on purpose relabels it (`severities`). A
hard target that counts the real graph is pinned to the fixture's own count
(pin_data_count_targets).
"""

from __future__ import annotations

import copy
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


def _tsk_votes_rows(snap: Path) -> int:
    return sum(r.get("votes") is not None for r in read_rows(snap / "cross_references.jsonl"))


# Hard targets that count the real graph (R11: W1's 250,358 TSK edges), keyed
# (check, metric) -> the same count taken on a snapshot. A batch that makes
# another such target hard adds it here.
DATA_COUNT_TARGETS = {("R11", "tsk_votes_edges"): _tsk_votes_rows}


def pin_data_count_targets(checks: list[dict], snap: Path) -> list[dict]:
    """A copy of `checks` whose DATA_COUNT_TARGETS targets are the fixture's
    own counts, as H7's sha target is the fixture's sha. fresh_baseline (one
    file) and split_baseline (the parts) both pin through here, so the two
    layouts keep scoring alike."""
    pinned = copy.deepcopy(checks)
    for check in pinned:
        for name, metric in check["metrics"].items():
            count = DATA_COUNT_TARGETS.get((check["id"], name))
            if count is not None:
                metric["target"] = count(snap)
    return pinned


def fresh_baseline(tmp_path: Path, snap: Path, severities: dict[str, str] | None = None) -> Path:
    """Shipped specs with every value cleared; H7's sha target (step0_sha.json
    next to the baseline, see cli) = the fixture's, and so are the data-count
    targets. Written as one file: the shipped parts merged, exactly as the
    gate reads them. `severities` ({check id: severity}) overrides the shipped
    severity of the checks it names."""
    doc = vk.load_baseline(SHIPPED_BASELINE)
    for check in doc["checks"]:
        check["severity"] = (severities or {}).get(check["id"], check["severity"])
        for metric in check["metrics"].values():
            metric["value"] = None
    doc["checks"] = pin_data_count_targets(doc["checks"], snap)
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
    """馬可 VISITED 摩利亞, an llm row sourced from gen:22:0 where 馬可 is never mentioned.

    Deliberately not a kinship edge, so it moves H3 and nothing else (R6's
    functionality rate would change with a FATHER_OF)."""
    row = {"head_id": "person:make", "relation": "VISITED", "tail_id": "place:moliya",
           "source_pericope_id": "gen:22:0", "extraction_phase": 4, "notes": "", "source": "llm"}
    row.update(over)
    return row


def _stored(baseline: Path, check_id: str, name: str):
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    return next(c for c in doc["checks"] if c["id"] == check_id)["metrics"][name]["value"]
