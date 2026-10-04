"""Step 0 sha gate (scripts/tools/check_step0.py).

The gate is what lets the rebuild chain skip Step 2/2.1/4/4.1 and keep the
PG structure tables: it only passes when the five Step 0 outputs are
byte-identical to the git-tracked baseline config/step0_sha.json.
"""

import hashlib
import json
import re

import pytest

from scripts.tools import check_step0

FILES = ("books.jsonl", "chapters.jsonl", "pericopes.jsonl", "chunks.jsonl", "embedding_queue.jsonl")


@pytest.fixture
def step0(tmp_path):
    """A fake output/ with the five Step 0 files and a baseline path next to it."""
    out = tmp_path / "output"
    out.mkdir()
    for i, name in enumerate(FILES):
        (out / name).write_text(f'{{"id": "{name}", "n": {i}}}\n{{"id": "x"}}\n', encoding="utf-8")
    return out, tmp_path / "step0_sha.json"


def _run(out, baseline, *extra):
    return check_step0.main(["--output-dir", str(out), "--baseline", str(baseline), *extra])


def test_step0_file_set_is_the_five_rebuild_inputs():
    assert set(check_step0.STEP0_FILES) == set(FILES)


def test_record_writes_sha256_of_every_step0_file(step0):
    out, baseline = step0

    assert _run(out, baseline, "--record") == 0

    recorded = json.loads(baseline.read_text(encoding="utf-8"))["files"]
    assert set(recorded) == set(FILES)
    for name in FILES:
        data = (out / name).read_bytes()
        assert recorded[name]["sha256"] == hashlib.sha256(data).hexdigest()
        assert recorded[name]["bytes"] == len(data)
        assert recorded[name]["lines"] == 2


def test_matching_outputs_exit_zero(step0, capsys):
    out, baseline = step0
    _run(out, baseline, "--record")
    capsys.readouterr()

    assert _run(out, baseline) == 0
    assert "OK" in capsys.readouterr().out


def test_changed_file_exits_one_and_names_only_that_file(step0, capsys):
    out, baseline = step0
    _run(out, baseline, "--record")
    old_sha = hashlib.sha256((out / "pericopes.jsonl").read_bytes()).hexdigest()
    (out / "pericopes.jsonl").write_text('{"id": "changed"}\n', encoding="utf-8")
    new_sha = hashlib.sha256((out / "pericopes.jsonl").read_bytes()).hexdigest()
    capsys.readouterr()

    assert _run(out, baseline) == 1

    report = capsys.readouterr().out
    assert "pericopes.jsonl" in report
    assert old_sha[:12] in report and new_sha[:12] in report
    changed = [line for line in report.splitlines() if line.lstrip().startswith("CHANGED")]
    assert len(changed) == 1


def test_missing_output_file_exits_one(step0, capsys):
    out, baseline = step0
    _run(out, baseline, "--record")
    (out / "chunks.jsonl").unlink()
    capsys.readouterr()

    assert _run(out, baseline) == 1
    assert re.search(r"MISSING\s+chunks\.jsonl", capsys.readouterr().out)


def test_missing_baseline_cannot_check(step0, capsys):
    out, baseline = step0

    assert _run(out, baseline) == 2
    assert "--record" in capsys.readouterr().out


def test_corrupt_baseline_cannot_check(step0, capsys):
    """A broken baseline is a setup error (2), not Step 0 drift (1)."""
    out, baseline = step0
    baseline.write_text("{not json", encoding="utf-8")

    assert _run(out, baseline) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_record_dry_run_writes_nothing(step0):
    out, baseline = step0

    assert _run(out, baseline, "--record", "--dry-run") == 0
    assert not baseline.exists()


def test_record_refuses_incomplete_step0(step0):
    out, baseline = step0
    (out / "books.jsonl").unlink()

    assert _run(out, baseline, "--record") == 2
    assert not baseline.exists()


def test_rerecord_unchanged_outputs_keeps_baseline_bytes(step0):
    """No spurious git diff (recorded_at) when Step 0 reproduced byte-identically."""
    out, baseline = step0
    _run(out, baseline, "--record")
    before = baseline.read_bytes()

    assert _run(out, baseline, "--record") == 0
    assert baseline.read_bytes() == before


def test_rerecord_after_change_accepts_new_sha(step0):
    out, baseline = step0
    _run(out, baseline, "--record")
    (out / "books.jsonl").write_text('{"id": "gen"}\n', encoding="utf-8")
    assert _run(out, baseline) == 1

    assert _run(out, baseline, "--record") == 0
    assert _run(out, baseline) == 0


def test_committed_baseline_pins_current_step0():
    """config/step0_sha.json is git-tracked; output/ is not, so check the file itself."""
    baseline = json.loads(check_step0.DEFAULT_BASELINE.read_text(encoding="utf-8"))

    assert set(baseline["files"]) == set(FILES)
    for entry in baseline["files"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    # Plan §1.2 run-of-record: embedding_queue 34,072 rows, sha 5d2ac0e5460c…
    queue = baseline["files"]["embedding_queue.jsonl"]
    assert queue["sha256"].startswith("5d2ac0e5460c")
    assert queue["lines"] == 34072
