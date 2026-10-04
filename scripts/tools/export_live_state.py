#!/usr/bin/env python3
"""Freeze live-only KG state before any rebuild (read-only, one-off).

Plan docs/records/2026-10-04_kg_data_layer_fix_plan.md §3.5.1 / EV-08: some
state exists only in live Neo4j, and a full rebuild (import_neo4j.py wipes the
graph) would lose it — Step 7's Person/Place/Group descriptions (no JSONL ever
held them), the descriptions of curated nodes (also in no JSONL; the other
Event/Object/Theme ones equal entities.jsonl as of 2026-10-04 and are frozen
too, so a rebuild can be diffed against them), aliases backfilled in place,
and the curated MENTIONS anchors behind the event registry. This script
snapshots them to output/frozen/live_state/<YYYYMMDD>/:

  descriptions.jsonl      seed for desc_generator's description cache, same
                          line format (make_cache_entry). model,
                          prompt_version and git_commit are
                          'live_export_unknown', temperature is null and
                          quality_flag is 'unreviewed': how each text was made
                          is recorded nowhere. generated_at is the export time.
                          titles_sha is desc_generator's title computation over
                          the CURRENT MENTIONS — a fingerprint that lets
                          --replay detect change on a rebuilt graph, not the
                          input the text was generated from (Step 7 read
                          pre-cleanup MENTIONS in store order). Live MENTIONS
                          are post-10.x (10.2 deleted 但's mis-hits, 10.4/10.5
                          added curated edges), so a rebuild must replay after
                          its own 10.1–10.5, not at Step 7's original place.
  entities.jsonl          entity_id, labels, canonical_name, aliases
  curated_mentions.jsonl  MENTIONS with curated=true or a curated source
                          (head_event_backfill, manual_patch), with properties
  manifest.json           counts and sha256 per file; written last, so its
                          presence marks a complete export

Every query runs inside execute_read, so a write would be refused by the
server rather than applied. NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD select
the instance. What it freezes is production's state, so it refuses to run
under KG_TARGET=staging (a shell that sourced scripts/tools/staging.env);
comparing a staging rebuild with production is scripts/tools/diff_kg.py's job.

`--promote` (no Neo4j) copies a complete export's descriptions.jsonl to the
official cache, desc_generator's default --cache (output/frozen/descriptions.jsonl
unless DESC_CACHE_PATH is set), after checking it against the manifest's
sha256 and the cache line format, and that the manifest's neo4j_uri is
production (port 7687, implicit or explicit, or .env's NEO4J_URI). A
non-production export, or an existing cache (after batch 2B it also holds
generated entries), is promoted only with --force. Every rebuild then replays
that one file:
    python -m scripts.relation_extraction.desc_generator --replay --fail-on-stale

Usage (from the project root):
    scripts/.venv/bin/python scripts/tools/export_live_state.py --dry-run
    scripts/.venv/bin/python scripts/tools/export_live_state.py [--out-dir DIR] [--force]
    scripts/.venv/bin/python scripts/tools/export_live_state.py --promote \\
        --out-dir output/frozen/live_state/<YYYYMMDD> [--cache PATH] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Run as a file, `scripts.` is not importable until the root is on the path.
sys.path.insert(0, str(_PROJECT_ROOT))

from neo4j import GraphDatabase  # noqa: E402

from scripts import kg_target  # noqa: E402
from scripts.relation_extraction.config import Neo4jConfig  # noqa: E402
from scripts.relation_extraction.desc_generator import (  # noqa: E402  (also loads .env)
    QUALITY_UNREVIEWED,
    default_cache_path,
    load_cache,
    make_cache_entry,
    titles_cypher,
)

LIVE_EXPORT_UNKNOWN = "live_export_unknown"
CURATED_SOURCES = ("head_event_backfill", "manual_patch")
DEFAULT_OUT_ROOT = _PROJECT_ROOT / "output" / "frozen" / "live_state"
SEED_FILE = "descriptions.jsonl"

# Step 7's own title computation, over every entity, so the seed's titles_sha
# is comparable with what --replay computes on a rebuilt graph.
_ENTITY_STATE_CYPHER = titles_cypher("true")

_CURATED_MENTIONS_CYPHER = """
MATCH (src)-[m:MENTIONS]->(e:Entity)
WHERE m.curated = true OR m.source IN $curated_sources
RETURN src.id AS source_id,
       [l IN labels(src) WHERE l <> 'Bible'][0] AS source_label,
       e.entity_id AS entity_id,
       properties(m) AS props
ORDER BY entity_id, source_id, source_label
"""

_CRITERIA = {
    "descriptions.jsonl": "Entity.description non-empty; titles_sha = "
                          "desc_generator.titles_sha over current MENTIONS",
    "entities.jsonl": "every :Entity",
    "curated_mentions.jsonl": "MENTIONS with curated = true or source in "
                              + ", ".join(CURATED_SOURCES),
}


def fetch_live_state(tx) -> dict[str, list[dict]]:
    """Every row the export needs, read in one read transaction."""
    return {
        "entities": [dict(r) for r in tx.run(_ENTITY_STATE_CYPHER)],
        "curated_mentions": [dict(r) for r in tx.run(
            _CURATED_MENTIONS_CYPHER, curated_sources=list(CURATED_SOURCES))],
    }


def build_records(state: dict[str, list[dict]], exported_at: str) -> dict[str, list[dict]]:
    """Output file name -> records, in query (entity_id) order."""
    entities = state["entities"]
    descriptions = [
        make_cache_entry(
            entity_id=r["entity_id"], description=r["description"],
            model=LIVE_EXPORT_UNKNOWN, temperature=None,
            prompt_version=LIVE_EXPORT_UNKNOWN, titles=r["titles"],
            quality_flag=QUALITY_UNREVIEWED, git_commit=LIVE_EXPORT_UNKNOWN,
            generated_at=exported_at,
        )
        for r in entities if r.get("description")
    ]
    identity = [
        {"entity_id": r["entity_id"], "labels": sorted(r["labels"]),
         "canonical_name": r["canonical_name"], "aliases": r["aliases"]}
        for r in entities
    ]
    return {
        "descriptions.jsonl": descriptions,
        "entities.jsonl": identity,
        "curated_mentions.jsonl": [dict(r) for r in state["curated_mentions"]],
    }


def _counts(state: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    def tally(values) -> dict[str, int]:
        return dict(sorted(Counter(values).items()))

    entities = state["entities"]
    return {
        "entities_by_type": tally(r["type"] for r in entities),
        "descriptions_by_type": tally(r["type"] for r in entities if r.get("description")),
        "curated_mentions_by_source": tally(
            r["props"].get("source") or "(none)" for r in state["curated_mentions"]),
    }


def _jsonl_bytes(records: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")


def _git_head() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_PROJECT_ROOT,
                             capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _print_counts(files: dict[str, dict], counts: dict[str, dict[str, int]]) -> None:
    for name, meta in files.items():
        print(f"  {name:<24} {meta['count']:>7,}")
    for key, tally in counts.items():
        print(f"  {key}: {tally}")


def export(session, out_dir: Path, *, dry_run: bool = False, force: bool = False,
           exported_at: Optional[str] = None, neo4j_uri: Optional[str] = None) -> dict:
    """Read live state and write the export (or, with dry_run, only count it).

    Returns the manifest (dry run: counts only, no sha256).
    """
    manifest_path = out_dir / "manifest.json"
    if not dry_run and manifest_path.exists() and not force:
        raise SystemExit(f"{out_dir} already holds an export (manifest.json); "
                         "pass --force to replace it")

    exported_at = exported_at or _now()
    state = session.execute_read(fetch_live_state)
    records = build_records(state, exported_at)
    counts = _counts(state)

    if dry_run:
        files = {name: {"count": len(rows)} for name, rows in records.items()}
        print(f"Dry run — nothing written (would write to {out_dir}):")
        _print_counts(files, counts)
        return {"exported_at": exported_at, "neo4j_uri": neo4j_uri,
                "files": files, "counts": counts}

    out_dir.mkdir(parents=True, exist_ok=True)
    # Drop the old manifest first: if this run dies midway, the directory must
    # not look like a complete export of mixed old and new files.
    manifest_path.unlink(missing_ok=True)
    files = {}
    for name, rows in records.items():
        data = _jsonl_bytes(rows)
        (out_dir / name).write_bytes(data)
        files[name] = {"count": len(rows), "sha256": hashlib.sha256(data).hexdigest()}

    manifest = {
        "exported_at": exported_at,
        "neo4j_uri": neo4j_uri,
        "git_head": _git_head(),
        "script": "scripts/tools/export_live_state.py",
        # Pins the exact title computation behind titles_sha, independent of
        # whether the working tree was committed.
        "titles_query_sha256": hashlib.sha256(_ENTITY_STATE_CYPHER.encode("utf-8")).hexdigest(),
        "criteria": _CRITERIA,
        "files": files,
        "counts": counts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(f"Exported to {out_dir}:")
    _print_counts(files, counts)
    return manifest


def promote(out_dir: Path, cache: Path, *, force: bool = False, dry_run: bool = False) -> None:
    """Make an export's description seed the official cache --replay reads.

    Checked first, so a half-written or edited export, or one in an older
    line format, never becomes what every rebuild replays: manifest.json must
    exist (it is written last), the seed must match its sha256, and every
    line must load as a cache entry. Force alone lets through an export whose
    manifest does not name production Neo4j (a staging export would make
    every rebuild replay staging) and the replacement of an existing cache,
    which may hold generated descriptions the seed lacks.
    """
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"{out_dir}: no manifest.json — not a complete export")
    seed = out_dir / SEED_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("files", {}).get(SEED_FILE, {}).get("sha256")
    actual = hashlib.sha256(seed.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{seed}: sha256 {actual} does not match the manifest's {expected}")
    entities = load_cache(seed)  # exits on a line missing any CACHE_FIELDS
    source = manifest.get("neo4j_uri")
    if not (source and kg_target.is_production("neo4j", source)) and not force:
        raise SystemExit(f"{manifest_path}: exported from neo4j_uri={source!r}, not production "
                         "(port 7687 or .env's NEO4J_URI); pass --force to promote it anyway")
    if cache.exists() and not force:
        raise SystemExit(f"{cache} already exists; pass --force to replace it with {seed}")

    if not dry_run:
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Copy then rename: the official cache is never seen half-written.
        tmp = cache.with_name(cache.name + ".tmp")
        shutil.copyfile(seed, tmp)
        os.replace(tmp, cache)
    print(f"{'Dry run — would promote' if dry_run else 'Promoted'} {seed} "
          f"({len(entities):,} entities, sha256 {actual}) -> {cache}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path,
                        default=DEFAULT_OUT_ROOT / datetime.now().strftime("%Y%m%d"),
                        help="Export directory (default: output/frozen/live_state/<YYYYMMDD>); "
                             "with --promote, the export to promote")
    parser.add_argument("--dry-run", action="store_true",
                        help="Query and print counts (with --promote: check only); write nothing")
    parser.add_argument("--force", action="store_true",
                        help="Replace an existing export in --out-dir (with --promote: replace "
                             "the existing official cache, or promote a non-production export)")
    parser.add_argument("--promote", action="store_true",
                        help="Copy --out-dir's descriptions.jsonl to the official cache "
                             "(--cache); no Neo4j access")
    parser.add_argument("--cache", type=Path, default=default_cache_path(),
                        help="--promote target; default is desc_generator's default --cache "
                             "(DESC_CACHE_PATH, else output/frozen/descriptions.jsonl)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    kg_target.refuse_under_staging(
        "export_live_state freezes production's live-only state (R0) and --promote makes it "
        "the cache every rebuild replays; run it from a shell without staging.env")
    if args.promote:
        promote(args.out_dir, args.cache, force=args.force, dry_run=args.dry_run)
        return 0
    cfg = Neo4jConfig.from_env()
    print(f"Neo4j source: {cfg.uri}")
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))
    try:
        with driver.session() as session:
            export(session, args.out_dir, dry_run=args.dry_run, force=args.force,
                   neo4j_uri=cfg.uri)
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
