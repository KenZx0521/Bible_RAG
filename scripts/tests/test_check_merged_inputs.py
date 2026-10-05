"""W1 sha pre-check that replaces Step 1 (scripts/tools/check_merged_inputs.py).

W1 skips Step 1 and rebuilds from the entities.jsonl / entity_mentions.jsonl
already in output/. The check only passes when both are byte-identical to the
source that Step 1's freeze-grounded recorded in frozen/grounded_manifest.json;
the manifest here is written by the real freeze_grounded, not by hand.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from entity_extraction import stages
from scripts.tools import check_merged_inputs as cmi

FILES = ("entities.jsonl", "entity_mentions.jsonl")
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "stages"
REAL_OUTPUT = Path(__file__).resolve().parents[2] / "output"
# The W1 snapshot (same pins as test_relation_postprocess_output.W1_PINS).
W1_SHA256 = {
    "entities.jsonl": "9f2d1f39251d9a3ce5834f52d129bda8e13cd2e1afdfa30d04962d23c7034142",
    "entity_mentions.jsonl": "ba7ed1884355e3f8d60952b4e89bff6c6dfb094818caee168dd5c387cd9e896c",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def merged(tmp_path):
    """A fake output/ whose two Step 1 files were frozen by freeze_grounded."""
    out = tmp_path / "output"
    out.mkdir()
    for name in FILES:
        shutil.copy(FIXTURE_DIR / name, out / name)
    stages.freeze_grounded(out / "entities.jsonl", out / "entity_mentions.jsonl", out / "frozen")
    return out


def _run(out, *extra):
    return cmi.main(["--output-dir", str(out), *extra])


def test_matching_files_exit_0(merged, capsys):
    assert _run(merged) == 0

    report = capsys.readouterr().out
    assert re.search(r"OK\s+entities\.jsonl", report)
    assert re.search(r"OK\s+entity_mentions\.jsonl", report)


def _drop_first_line(data: bytes) -> bytes:
    """Step 1 re-run in W1: the file rebuilt without one NER row."""
    return b"".join(data.splitlines(keepends=True)[1:])


def _flip_one_byte(data: bytes) -> bytes:
    """One byte of line 2 changed: same size and line count, so only the sha256 tells."""
    lines = data.splitlines(keepends=True)
    lines[1] = lines[1].replace(b'"', b"'", 1)
    edited = b"".join(lines)
    assert len(edited) == len(data) and edited != data
    return edited


@pytest.mark.parametrize("edit", [_drop_first_line, _flip_one_byte], ids=["line-dropped", "same-length"])
@pytest.mark.parametrize("name", FILES)
def test_changed_file_exit_1(merged, capsys, name, edit):
    expected = _sha(merged / name)
    (merged / name).write_bytes(edit((merged / name).read_bytes()))
    actual = _sha(merged / name)

    assert _run(merged) == 1

    report = capsys.readouterr().out
    assert expected in report and actual in report
    assert report.count(actual) == 1                     # on the actual line only, not the status line too
    assert [line.split()[1] for line in report.splitlines()
            if line.lstrip().startswith("MISMATCH")] == [name]
    # The hazard and the way back, not just the hashes.
    assert "person:liuer" in report and "6.05" in report
    assert "llm_artifacts.tgz" in report
    # ... for the directory checked, not a hardcoded output/.
    assert f"tar -C {merged} -xzf" in report and f"{merged}/ner_*.jsonl" in report
    assert "tar -C output " not in report


def test_missing_file_exit_1(merged, capsys):
    (merged / "entity_mentions.jsonl").unlink()

    assert _run(merged) == 1
    assert re.search(r"MISSING\s+entity_mentions\.jsonl", capsys.readouterr().out)


def test_missing_manifest_exit_2(merged, tmp_path, capsys):
    moved = tmp_path / "elsewhere.json"
    (merged / "frozen" / "grounded_manifest.json").rename(moved)

    assert _run(merged) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out
    # --manifest points at a manifest outside <output-dir>/frozen/.
    assert _run(merged, "--manifest", str(moved)) == 0


def test_unreadable_file_exit_2(merged, monkeypatch, capsys):
    """An unreadable file is a setup error (2), not drift (1); chmod is no test under root."""
    real = cmi.file_digest

    def digest(path):
        if path.name == "entity_mentions.jsonl":
            raise PermissionError(13, "Permission denied", str(path))
        return real(path)
    monkeypatch.setattr(cmi, "file_digest", digest)

    assert _run(merged) == 2

    report = capsys.readouterr().out
    assert "CANNOT CHECK" in report and "entity_mentions.jsonl unreadable" in report
    assert "Permission denied" in report and "DRIFT" not in report


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    '{"files": {}}',
    '{"source": {"entities": {"sha256": "0"}}}',
    '{"source": {"entities": {"sha256": 1}, "entity_mentions": {"sha256": "0"}}}',
])
def test_malformed_manifest_exit_2(merged, capsys, text):
    """A broken manifest is a setup error (2), never a mismatch (1)."""
    (merged / "frozen" / "grounded_manifest.json").write_text(text, encoding="utf-8")

    assert _run(merged) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_real_output_matches(capsys):
    paths = [REAL_OUTPUT / name for name in FILES]
    manifest_path = REAL_OUTPUT / "frozen" / "grounded_manifest.json"
    if not all(path.is_file() for path in (*paths, manifest_path)):
        pytest.skip("output/ Step 1 files or grounded_manifest.json are not present")
    if any(_sha(path) != W1_SHA256[path.name] for path in paths):
        pytest.skip("output/ is not the W1 snapshot (W2 runs Step 1 again)")

    assert cmi.main([]) == 0

    report = capsys.readouterr().out
    assert "9,120 lines" in report and "173,896 lines" in report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {key: entry["sha256"] for key, entry in manifest["source"].items()} == {
        "entities": W1_SHA256["entities.jsonl"],
        "entity_mentions": W1_SHA256["entity_mentions.jsonl"],
    }
