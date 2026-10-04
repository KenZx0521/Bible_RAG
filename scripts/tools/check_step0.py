#!/usr/bin/env python3
"""Step 0 sha gate: are process_bible.py's outputs byte-identical to the baseline?

The rebuild chain (docs/build_database.md「執行順序」) keeps everything that is
derived from Step 0 but NOT rebuilt per batch — PG books/chapters/pericopes/
chunks (Step 3 structure tables), the passage vectors (Step 2 → Step 4/4.1)
and the BM25 vocabulary (Step 2.1) — on the promise that Step 0 did not move.
This script turns that promise into a gate (plan §3.2 K0, docs/records/
2026-10-04_kg_data_layer_fix_plan.md): it hashes the five Step 0 files that
feed those layers and compares them with the git-tracked config/step0_sha.json.

Why these five and not all seven Step 0 outputs: neo4j_nodes.jsonl and
neo4j_relationships.jsonl only feed Step 5, which wipes and rebuilds Neo4j on
every rebuild anyway, and batch 1B changes the cross-reference rows in them on
purpose. embedding_queue.jsonl is the hard invariant (it is the embedding
input); the other four guard the PG structure tables.

A batch that changes Step 0 on purpose (1B/2D touch pericopes.jsonl's
cross_references field) re-records with --record; the baseline diff then shows
up in the commit next to the code that caused it. If embedding_queue.jsonl
changed, Step 2/2.1/4/4.1 must be re-run before the gate is re-recorded.

Exit codes: 0 all five match; 1 drift (changed or missing file, each listed);
2 cannot check (no baseline, or --record with an incomplete output/).

Usage (from the project root):
    scripts/.venv/bin/python scripts/tools/check_step0.py                      # gate
    scripts/.venv/bin/python scripts/tools/check_step0.py --record --dry-run   # preview
    scripts/.venv/bin/python scripts/tools/check_step0.py --record             # accept
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "output"
DEFAULT_BASELINE = _PROJECT_ROOT / "config" / "step0_sha.json"

# Hierarchy order (book → chapter → pericope → chunk → embedding input), which
# is also the order the report and the baseline list them in.
STEP0_FILES = (
    "books.jsonl",
    "chapters.jsonl",
    "pericopes.jsonl",
    "chunks.jsonl",
    "embedding_queue.jsonl",
)

_CHUNK = 1 << 20


def file_digest(path: Path) -> dict:
    """sha256 plus size and line count (the latter two only help read a drift)."""
    sha = hashlib.sha256()
    size = lines = 0
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            sha.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    return {"sha256": sha.hexdigest(), "bytes": size, "lines": lines}


def compute_manifest(output_dir: Path) -> dict[str, dict | None]:
    """file name → digest, or None when the file is missing."""
    return {
        name: file_digest(output_dir / name) if (output_dir / name).is_file() else None
        for name in STEP0_FILES
    }


def compare(baseline_files: dict, current: dict[str, dict | None]) -> list[tuple[str, str, dict | None, dict | None]]:
    """(status, name, expected, actual) for every file; status OK | CHANGED | MISSING."""
    rows = []
    for name in STEP0_FILES:
        expected, actual = baseline_files.get(name), current.get(name)
        if actual is None:
            status = "MISSING"
        elif expected is None or expected.get("sha256") != actual["sha256"]:
            status = "CHANGED"
        else:
            status = "OK"
        rows.append((status, name, expected, actual))
    return rows


def _describe(entry: dict | None) -> str:
    if entry is None:
        return "(none)"
    # lines/bytes are informative only; a hand-edited baseline may lack them.
    size = f" {entry['lines']:,} lines {entry['bytes']:,} B" if {"lines", "bytes"} <= entry.keys() else ""
    return f"{str(entry.get('sha256', '?'))[:12]}…{size}"


class BaselineError(Exception):
    """The baseline file exists but cannot be read as a baseline."""


def _load_baseline(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BaselineError(f"{path} is not valid JSON ({e})") from e
    if not isinstance(baseline, dict) or not isinstance(baseline.get("files"), dict):
        raise BaselineError(f"{path} has no 'files' mapping")
    return baseline


def run_check(output_dir: Path, baseline_path: Path) -> int:
    # A broken baseline must not exit 1: that code means "Step 0 drifted".
    try:
        baseline = _load_baseline(baseline_path)
    except BaselineError as e:
        print(f"CANNOT CHECK: {e}; restore it from git or re-run with --record")
        return 2
    if baseline is None:
        print(f"CANNOT CHECK: no baseline at {baseline_path}; review output/ and run with --record")
        return 2

    rows = compare(baseline["files"], compute_manifest(output_dir))
    drift = [r for r in rows if r[0] != "OK"]
    for status, name, expected, actual in rows:
        print(f"  {status:<8}{name}")
        if status != "OK":
            print(f"            expected {_describe(expected)}")
            print(f"            actual   {_describe(actual)}")

    if drift:
        print(f"DRIFT: {len(drift)}/{len(rows)} Step 0 files differ from {baseline_path}. "
              "Do not continue the rebuild chain; if the change is intended, re-run "
              "Step 2/2.1/4/4.1 when embedding_queue.jsonl changed, then --record.")
        return 1
    print(f"OK: {len(rows)} Step 0 files match {baseline_path}")
    return 0


def run_record(output_dir: Path, baseline_path: Path, dry_run: bool) -> int:
    current = compute_manifest(output_dir)
    missing = [name for name, entry in current.items() if entry is None]
    if missing:
        print(f"CANNOT RECORD: missing in {output_dir}: {', '.join(missing)} (run process_bible.py first)")
        return 2

    try:
        old = _load_baseline(baseline_path)
    except BaselineError as e:
        print(f"replacing unreadable baseline: {e}")
        old = None
    old_files = old["files"] if old else {}
    rows = compare(old_files, current)
    for status, name, expected, actual in rows:
        label = "same" if status == "OK" else ("new" if expected is None else "CHANGED")
        print(f"  {label:<8}{name}  {_describe(actual)}")

    if old is not None and all(status == "OK" for status, *_ in rows):
        # Re-recording a byte-identical Step 0 must not churn recorded_at in git.
        print(f"unchanged: {baseline_path} already pins these files")
        return 0

    baseline = {
        "version": 1,
        "generator": "scripts/tools/check_step0.py",
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "files": current,
    }
    if dry_run:
        print(f"[dry-run] would write {baseline_path}")
        return 0
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {baseline_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"directory holding the Step 0 outputs (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help=f"sha baseline JSON (default: {DEFAULT_BASELINE})")
    parser.add_argument("--record", action="store_true",
                        help="write the current sha256 of the Step 0 files as the new baseline")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --record: show what would be recorded without writing")
    args = parser.parse_args(argv)

    if args.dry_run and not args.record:
        parser.error("--dry-run only applies to --record (the check never writes)")
    if args.record:
        return run_record(args.output_dir, args.baseline, args.dry_run)
    return run_check(args.output_dir, args.baseline)


if __name__ == "__main__":
    sys.exit(main())
