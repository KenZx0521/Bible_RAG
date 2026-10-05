#!/usr/bin/env python3
"""Import TSK cross references as Pericope-level CROSS_REFERENCES edges (P0).

Source: scrollmapper/bible_databases sources/extras/cross_references.txt
(openbible.info, CC-BY) — ~344k verse-level pairs with community votes.

Pipeline:
  1. Build (book, chapter, verse) → pericope_id map from
     output/embedding_queue.jsonl verse entries (ids like ``gen:1:0:v:3``;
     range verse numbers like ``1-2`` are expanded).
  2. Parse TSK lines (OSIS refs like ``Gen.1.1`` / ranges
     ``Prov.8.22-Prov.8.30``), drop negative-vote pairs.
  3. Aggregate to unique (from_pericope, to_pericope) pairs
     (self-loops removed, max votes, verse-pair count kept).
  4. Precondition (read only, also on --dry-run): every CROSS_REFERENCES edge
     already carries curated and tsk, as Step 5 writes every curated row and
     this script every TSK edge. A graph built before batch 1 is refused
     before anything is written.
     Support gate (read only, also on --dry-run): every supplementary anchor
     on the graph ('rev 19:16>dan 2:47') needs a TSK line from one of its
     source verses to one of its target verses, unless the edge lists it in
     supp_tsk_exempt_anchors. Support only in reverse does not count. The
     check is per verse because at pericope level every definition, the
     wrong ones included, has TSK support (XREF-1/2).
  5. MERGE into Neo4j. votes, verse_pairs and tsk = true are SET on every
     matched pair, including a pair Step 5 wrote as a curated edge (its source
     and curated stay; before batch 1 such a pair kept no votes, XREF-4). A
     new edge is source 'tsk', curated false.
  6. Gates (exit 1): matched == pairs, count(tsk) == pairs,
     count(tsk and curated) == attached_to_curated, no unflagged edge. Then
     the edge fingerprint (curated_xrefs.edge_fingerprint) is printed.

There is no refresh mode: Step 5 rebuilds the graph, so a second run only
creates 0 edges and prints the same fingerprint.

Usage:
    uv run python import_tsk_crossrefs.py path/to/cross_references.txt [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from dotenv import load_dotenv
from neo4j import READ_ACCESS, GraphDatabase

import kg_target

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from bible_chunking.curated_xrefs import (  # noqa: E402
    EDGE_FINGERPRINT_CYPHER, XrefDefinitionError, edge_fingerprint, parse_anchor)

BATCH_SIZE = 5000
MAX_RANGE_VERSES = 60  # sanity cap when expanding "to" ranges

# OSIS (openbible.info) → project USFM-style book ids (output/books.jsonl)
OSIS_TO_BOOK = {
    "Gen": "gen", "Exod": "exo", "Lev": "lev", "Num": "num", "Deut": "deu",
    "Josh": "jos", "Judg": "jdg", "Ruth": "rut", "1Sam": "1sa", "2Sam": "2sa",
    "1Kgs": "1ki", "2Kgs": "2ki", "1Chr": "1ch", "2Chr": "2ch", "Ezra": "ezr",
    "Neh": "neh", "Esth": "est", "Job": "job", "Ps": "psa", "Prov": "pro",
    "Eccl": "ecc", "Song": "sng", "Isa": "isa", "Jer": "jer", "Lam": "lam",
    "Ezek": "ezk", "Dan": "dan", "Hos": "hos", "Joel": "jol", "Amos": "amo",
    "Obad": "oba", "Jonah": "jon", "Mic": "mic", "Nah": "nam", "Hab": "hab",
    "Zeph": "zep", "Hag": "hag", "Zech": "zec", "Mal": "mal",
    "Matt": "mat", "Mark": "mrk", "Luke": "luk", "John": "jhn", "Acts": "act",
    "Rom": "rom", "1Cor": "1co", "2Cor": "2co", "Gal": "gal", "Eph": "eph",
    "Phil": "php", "Col": "col", "1Thess": "1th", "2Thess": "2th",
    "1Tim": "1ti", "2Tim": "2ti", "Titus": "tit", "Phlm": "phm", "Heb": "heb",
    "Jas": "jas", "1Pet": "1pe", "2Pet": "2pe", "1John": "1jn", "2John": "2jn",
    "3John": "3jn", "Jude": "jud", "Rev": "rev",
}

# ON CREATE names a pure TSK edge; the plain SET also reaches a curated edge.
_MERGE_CYPHER = """
UNWIND $rows AS row
MATCH (a:Pericope {id: row.from_id})
MATCH (b:Pericope {id: row.to_id})
MERGE (a)-[r:CROSS_REFERENCES]->(b)
ON CREATE SET r.source = 'tsk', r.curated = false
SET r.votes = row.votes, r.verse_pairs = row.verse_pairs, r.tsk = true
RETURN count(r) AS matched
"""

_COUNTS_CYPHER = """
MATCH ()-[r:CROSS_REFERENCES]->()
RETURN count(r) AS total,
       count(CASE WHEN r.curated = true THEN 1 END) AS curated,
       count(CASE WHEN r.curated IS NULL OR r.tsk IS NULL THEN 1 END) AS unflagged,
       count(CASE WHEN r.tsk = true THEN 1 END) AS tsk,
       count(CASE WHEN r.tsk = true AND r.curated = true THEN 1 END) AS tsk_curated
"""

_CURATED_PAIRS_CYPHER = """
MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
WHERE r.curated = true
RETURN a.id AS a, b.id AS b
"""

# The lists Step 5 writes on a supplementary edge (curated_xrefs.aggregate_curated).
_SUPP_ANCHORS_CYPHER = """
MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
WHERE r.supp_anchors IS NOT NULL
RETURN a.id AS a, b.id AS b, r.supp_anchors AS anchors,
       coalesce(r.supp_tsk_exempt_anchors, []) AS exempt
"""

Verse = tuple[str, int, int]


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def build_verse_map(queue_path: Path) -> dict[tuple[str, int, int], str]:
    """(book, chapter, verse) → pericope_id from embedding queue verse ids."""
    vmap: dict[tuple[str, int, int], str] = {}
    with queue_path.open("r", encoding="utf-8") as f:
        for line in f:
            if '"verse"' not in line:
                continue
            rec = json.loads(line)
            if rec.get("type") != "verse":
                continue
            vid = rec["id"]  # e.g. gen:1:0:v:3  or  gen:1:0:v:1-2
            if ":v:" not in vid:
                continue
            peri_id, verse_part = vid.split(":v:", 1)
            parts = peri_id.split(":")
            if len(parts) < 3:
                continue
            book, chapter = parts[0], int(parts[1])
            if "-" in verse_part:
                lo, hi = verse_part.split("-", 1)
                nums = range(int(lo), int(hi) + 1)
            else:
                nums = [int(verse_part)]
            for n in nums:
                vmap[(book, chapter, n)] = peri_id
    return vmap


def parse_ref(ref: str) -> tuple[str, int, int] | None:
    """``Gen.1.1`` → ('gen', 1, 1); None if book unknown."""
    parts = ref.split(".")
    if len(parts) != 3:
        return None
    book = OSIS_TO_BOOK.get(parts[0])
    if not book:
        return None
    try:
        return book, int(parts[1]), int(parts[2])
    except ValueError:
        return None


def to_verses(ref: str) -> list[Verse]:
    """A 'to' ref's verses: a single verse, a same-chapter range capped at
    MAX_RANGE_VERSES past its start, or a cross-chapter range's two endpoints."""
    if "-" not in ref:
        single = parse_ref(ref)
        return [single] if single else []
    lo_s, hi_s = ref.split("-", 1)
    lo, hi = parse_ref(lo_s), parse_ref(hi_s)
    if not lo or not hi:
        return []
    if lo[0] == hi[0] and lo[1] == hi[1]:  # same book+chapter
        return [(lo[0], lo[1], n) for n in range(lo[2], min(hi[2], lo[2] + MAX_RANGE_VERSES) + 1)]
    return [lo, hi]  # cross-chapter range: endpoints only


def expand_to_range(ref: str, vmap: dict) -> list[str]:
    """Resolve a 'to' ref (single verse or range) to pericope ids."""
    peris: list[str] = []
    for verse in to_verses(ref):
        p = vmap.get(verse)
        if p and p not in peris:
            peris.append(p)
    return peris


def aggregate_tsk(tsk_path: Path, vmap: dict) -> tuple[dict, dict]:
    """(from_pericope, to_pericope) → {votes: max, verse_pairs: count}, and the
    drop counts. Negative votes and self loops are dropped."""
    pairs: dict[tuple[str, str], dict] = defaultdict(lambda: {"votes": 0, "verse_pairs": 0})
    stats = defaultdict(int)
    with tsk_path.open("r", encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            stats["lines"] += 1
            try:
                votes = int(cols[2])
            except ValueError:
                continue
            if votes < 0:
                stats["negative_votes_dropped"] += 1
                continue
            from_ref = parse_ref(cols[0])
            if not from_ref:
                stats["from_unparsed"] += 1
                continue
            from_p = vmap.get(from_ref)
            if not from_p:
                stats["from_unmapped"] += 1
                continue
            to_peris = expand_to_range(cols[1], vmap)
            if not to_peris:
                stats["to_unmapped"] += 1
                continue
            for to_p in to_peris:
                if to_p == from_p:
                    stats["self_loops_dropped"] += 1
                    continue
                slot = pairs[(from_p, to_p)]
                slot["votes"] = max(slot["votes"], votes)
                slot["verse_pairs"] += 1
    return dict(pairs), stats


def build_verse_pair_index(tsk_path: Path) -> dict[tuple[Verse, Verse], int]:
    """(from verse, to verse) → max votes over the TSK lines with votes >= 0,
    'to' ranges expanded by to_verses. No pericope map: the support gate looks
    up an anchor's own verses."""
    index: dict[tuple[Verse, Verse], int] = {}
    with tsk_path.open("r", encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            try:
                votes = int(cols[2])
            except ValueError:
                continue
            from_ref = parse_ref(cols[0])
            if votes < 0 or not from_ref:
                continue
            for to_ref in to_verses(cols[1]):
                key = (from_ref, to_ref)
                index[key] = max(index.get(key, votes), votes)
    return index


def anchor_votes(anchor: str, index: Mapping) -> tuple[int | None, int | None]:
    """Max votes of the anchor's (source verse, target verse) pairs, forward and
    reverse (target verse → source verse); None where no pair has a TSK line."""
    src, tgt = parse_anchor(anchor)
    pairs = [((src.book, src.chapter, s), (tgt.book, tgt.chapter, t))
             for s in src.verses for t in tgt.verses]
    forward = [index[pair] for pair in pairs if pair in index]
    reverse = [index[(t, s)] for s, t in pairs if (t, s) in index]
    return max(forward, default=None), max(reverse, default=None)


def _votes(value: int | None) -> str:
    return "none" if value is None else str(value)


def _anchor_failure(pair: str, anchor: str, index: Mapping) -> str | None:
    try:
        forward, reverse = anchor_votes(anchor, index)
    except XrefDefinitionError as err:  # the message quotes the anchor
        return f"{pair} {'; '.join(err.errors)}"
    if forward is not None:
        return None
    return (f"{pair} {anchor!r}: forward votes none, reverse votes {_votes(reverse)}"
            + (" (reverse only)" if reverse is not None else ""))


def unsupported_anchors(rows: Iterable[Mapping], index: Mapping) -> list[str]:
    """One line per anchor of _SUPP_ANCHORS_CYPHER's rows with no forward TSK
    verse pair and no tsk_exempt entry, in (a, b) order."""
    failures = []
    for row in sorted(rows, key=lambda r: (r["a"], r["b"])):
        for anchor in row["anchors"]:
            failure = None if anchor in row["exempt"] else _anchor_failure(
                f"{row['a']}→{row['b']}", anchor, index)
            if failure:
                failures.append(failure)
    return failures


def _read(driver, cypher: str) -> list[dict]:
    """One statement in a READ transaction (the server rejects writes)."""
    with driver.session(default_access_mode=READ_ACCESS) as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(cypher)])


def edge_counts(driver) -> dict:
    """CROSS_REFERENCES total, curated, unflagged, tsk and tsk_curated counts."""
    return _read(driver, _COUNTS_CYPHER)[0]


def precondition_failures(driver) -> list[str]:
    """Step 5 flags every curated row and this script every TSK edge, so an
    unflagged edge means a graph built before batch 1 (crit#5)."""
    counts = edge_counts(driver)
    print(f"Before: {counts['total']:,} CROSS_REFERENCES edges ({counts['curated']:,} curated)")
    if not counts["unflagged"]:
        return []
    return [f"{counts['unflagged']:,} of {counts['total']:,} CROSS_REFERENCES edges have "
            "curated or tsk unset: run Step 9 only on a graph Step 5 just built from a "
            "batch-1 Step 0 output"]


def support_failures(driver, index: Mapping) -> list[str]:
    """The support gate over the graph's supplementary anchors (XREF-1/2)."""
    rows = _read(driver, _SUPP_ANCHORS_CYPHER)
    print(f"  supplementary anchors: {sum(len(r['anchors']) for r in rows):,} on "
          f"{len(rows):,} edges, tsk_exempt {sum(len(r['exempt']) for r in rows):,}")
    return unsupported_anchors(rows, index)


def read_curated_pairs(driver) -> set[tuple[str, str]]:
    return {(r["a"], r["b"]) for r in _read(driver, _CURATED_PAIRS_CYPHER)}


def _merge_batch(tx, batch: list[dict]) -> tuple[int, int]:
    result = tx.run(_MERGE_CYPHER, rows=batch)
    matched = int(result.single()["matched"])
    return matched, result.consume().counters.relationships_created


def write_rows(driver, rows: list[dict]) -> tuple[int, int]:
    """MERGE every row; (matched, created) summed over the batches."""
    matched = created = 0
    for start in range(0, len(rows), BATCH_SIZE):
        with driver.session() as session:
            m, c = session.execute_write(_merge_batch, rows[start:start + BATCH_SIZE])
        matched, created = matched + m, created + c
        if (start // BATCH_SIZE) % 10 == 0:
            print(f"  {min(start + BATCH_SIZE, len(rows)):,}/{len(rows):,} pairs...")
    return matched, created


def count_gate_failures(driver, n_rows: int, attached: int, matched: int) -> list[str]:
    counts = edge_counts(driver)
    checks = (("matched rows", matched, n_rows),
              ("edges with tsk = true", counts["tsk"], n_rows),
              ("edges with tsk and curated", counts["tsk_curated"], attached),
              ("edges with curated or tsk unset", counts["unflagged"], 0))
    return [f"{name}: {got:,}, expected {want:,}" for name, got, want in checks if got != want]


def _fail(header: str, failures: list[str]) -> int:
    print(f"✗ {header}", file=sys.stderr)
    for failure in failures:
        print(f"    {failure}", file=sys.stderr)
    return 1


def _load(driver, rows: list[dict], index: Mapping, dry_run: bool) -> int:
    """Steps 4-6 of the module docstring; every read is a READ session."""
    failures = precondition_failures(driver)
    if failures:
        return _fail("Precondition failed, nothing written:", failures)
    failures = support_failures(driver, index)
    if failures:
        return _fail("Supplementary anchors without same-direction TSK support (fix the "
                     "anchor or give it a tsk_exempt reason), nothing written:", failures)
    pairs = {(row["from_id"], row["to_id"]) for row in rows}
    attached = len(pairs & read_curated_pairs(driver))
    print(f"  attached_to_curated {attached:,} (TSK pairs that are a curated edge)")
    if dry_run:
        print("[dry-run] nothing written")
        return 0

    matched, created = write_rows(driver, rows)
    print(f"\nAfter: created {created:,}, attached_to_curated {attached:,}, matched {matched:,}")
    failures = count_gate_failures(driver, len(rows), attached, matched)
    if failures:
        return _fail("Count gates failed:", failures)
    print(f"fingerprint: {edge_fingerprint(_read(driver, EDGE_FINGERPRINT_CYPHER))}")
    return 0


def _run(args: argparse.Namespace) -> int:
    # Checked before the slow verse map too, and for --dry-run, whose
    # reads would otherwise describe production.
    kg_target.assert_target("neo4j")

    tsk_path = Path(args.input)
    if not tsk_path.exists():
        print(f"✗ Not found: {tsk_path}")
        return 2

    print("Building verse → pericope map from embedding_queue.jsonl ...")
    vmap = build_verse_map(ROOT / "output" / "embedding_queue.jsonl")
    print(f"  {len(vmap):,} verses mapped")
    pairs, stats = aggregate_tsk(tsk_path, vmap)
    print(f"  TSK lines: {stats['lines']:,} | negative votes dropped: "
          f"{stats['negative_votes_dropped']:,} | from unmapped: {stats['from_unmapped']:,} | "
          f"to unmapped: {stats['to_unmapped']:,} | self-loops dropped: {stats['self_loops_dropped']:,}")
    print(f"  Unique pericope pairs: {len(pairs):,}")
    rows = [
        {"from_id": a, "to_id": b, "votes": v["votes"], "verse_pairs": v["verse_pairs"]}
        for (a, b), v in pairs.items()
    ]
    index = build_verse_pair_index(tsk_path)
    print(f"  TSK verse pairs (support gate): {len(index):,}")

    driver = get_driver()
    try:
        return _load(driver, rows, index, args.dry_run)
    finally:
        driver.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=str, help="Path to cross_references.txt")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the precondition and the support gate and count "
                             "attached_to_curated, write nothing")
    return _run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
