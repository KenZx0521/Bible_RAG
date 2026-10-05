#!/usr/bin/env python3
"""W1 sha pre-check that replaces Step 1 in the W1 rebuild chain (batch 1A-T1).

W1 rebuilds the graph from the entities.jsonl and entity_mentions.jsonl that
are already in output/: the batch-0 build, which Step 1's freeze-grounded
recorded as the "source" of output/frozen/grounded_manifest.json. So W1 skips
Step 1 and runs this check in its place (docs/records/
2026-10-04_kg_batch1_plan.md §6 #10). Re-running Step 1 is not harmless:
`--stage merge` rebuilds both files from output/ner_*.jsonl, an older NER half
in which 流珥 is no entity of its own (batch 0's dictionary maps it to 葉忒羅).
person:liuer would vanish, and 6.05 (relation_postprocess) would hard-fail on
the relations rows whose endpoint is missing from entities.jsonl.

Both files are hashed with check_step0.file_digest and compared with
manifest["source"][...]["sha256"]. A mismatch means something already rewrote
them: restore them from the R0 backup (docs/staging_promotion.md R0,
llm_artifacts.tgz) before going on. W1 only: W2 runs Step 1 again.

Exit codes: 0 both match; 1 a file differs or is missing (expected and actual
printed); 2 cannot check (manifest missing or malformed).

Usage (from the project root):
    scripts/.venv/bin/python scripts/tools/check_merged_inputs.py
    scripts/.venv/bin/python scripts/tools/check_merged_inputs.py \\
        --output-dir output --manifest output/frozen/grounded_manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.tools.check_step0 import file_digest  # noqa: E402

DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "output"
# Where extract_entities.py --stage freeze-grounded writes it, under --output-dir.
MANIFEST_RELPATH = Path("frozen") / "grounded_manifest.json"

# manifest["source"] key → file name in the output directory, in Step 1's order.
SOURCE_FILES = (
    ("entities", "entities.jsonl"),
    ("entity_mentions", "entity_mentions.jsonl"),
)

HAZARD = (
    "W1 skips Step 1 and rebuilds from these two files as they are. A Step 1 merge "
    "rebuilds them from output/ner_*.jsonl, which has no person:liuer (流珥), so 6.05 "
    "would hard-fail on relations rows with an endpoint missing from entities.jsonl. "
    "Do not continue the rebuild chain. Restore both files from the R0 backup "
    "(docs/staging_promotion.md R0) and re-run this check:\n"
    "    tar -C output -xzf bak/<D>/output/llm_artifacts.tgz entities.jsonl entity_mentions.jsonl\n"
    "and compare them with bak/<D>/output/MANIFEST.sha256."
)


class ManifestError(Exception):
    """The manifest is missing or cannot be read as a grounded manifest."""


def load_expected(manifest_path: Path) -> dict[str, dict]:
    """file name → the manifest's source record ({sha256, lines?, ...})."""
    if not manifest_path.is_file():
        raise ManifestError(f"no manifest at {manifest_path} (written by "
                            "extract_entities.py --stage freeze-grounded)")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ManifestError(f"{manifest_path} is not valid JSON ({e})") from e
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if not isinstance(source, dict):
        raise ManifestError(f"{manifest_path} has no 'source' mapping")
    expected = {}
    for key, name in SOURCE_FILES:
        entry = source.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise ManifestError(f"{manifest_path}: source[{key!r}] has no sha256")
        expected[name] = entry
    return expected


def compare(output_dir: Path, expected: dict[str, dict]) -> list[tuple[str, str, dict, dict | None]]:
    """(status, name, expected, actual) per file; status OK | MISMATCH | MISSING."""
    rows = []
    for _key, name in SOURCE_FILES:
        path = output_dir / name
        actual = file_digest(path) if path.is_file() else None
        if actual is None:
            status = "MISSING"
        elif actual["sha256"] != expected[name]["sha256"]:
            status = "MISMATCH"
        else:
            status = "OK"
        rows.append((status, name, expected[name], actual))
    return rows


def _describe(entry: dict | None) -> str:
    if entry is None:
        return "(no file)"
    # lines is informative only; a hand-edited manifest may lack it.
    lines = entry.get("lines")
    return entry["sha256"] + (f"  {lines:,} lines" if type(lines) is int else "")


def run_check(output_dir: Path, manifest_path: Path) -> int:
    # A broken manifest must not exit 1: that code means "the files moved".
    try:
        expected = load_expected(manifest_path)
    except ManifestError as e:
        print(f"CANNOT CHECK: {e}")
        return 2

    rows = compare(output_dir, expected)
    for status, name, want, got in rows:
        print(f"  {status:<9}{name}  {_describe(got)}")
        if status != "OK":
            print(f"             expected {_describe(want)}")
            print(f"             actual   {_describe(got)}")

    drift = [name for status, name, *_ in rows if status != "OK"]
    if drift:
        print(f"DRIFT: {', '.join(drift)} in {output_dir} differ from the source "
              f"recorded in {manifest_path}.\n{HAZARD}")
        return 1
    print(f"OK: both Step 1 files match {manifest_path}; skip Step 1 in W1 (W2 runs it again)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"directory holding entities.jsonl and entity_mentions.jsonl "
                             f"(default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--manifest", type=Path, default=None,
                        help=f"grounded manifest whose 'source' pins the two files "
                             f"(default: <output-dir>/{MANIFEST_RELPATH})")
    args = parser.parse_args(argv)
    return run_check(args.output_dir, args.manifest or args.output_dir / MANIFEST_RELPATH)


if __name__ == "__main__":
    sys.exit(main())
