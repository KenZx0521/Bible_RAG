"""Supplementary cross references in Step 0 (1B-C3c, XREF-1(a)).

The definitions in bible_chunking/nt_cross_references.py name both ends in
verse coordinates. process_bible resolves every verse of both ends to its
pericope (bible_chunking/curated_xrefs.py), one anchor per touched pericope
pair. A definition that does not resolve stops Step 0
before any JSONL is written: the old code skipped a definition whose source
pericope id did not exist (16 of 161) and let a target fall back to the
chapter.

Step 0 then writes one row per (start, end) pair for markdown and
supplementary together (1B-C4a, XREF-1(b)): Step 5 MERGEs on the pair, so a
second row of the same pair used to overwrite the first. A markdown anchor
marks with '?' what CrossRefParser left unread: the end verse of a
cross-chapter ref ('-?') and the ranges after a comma (',?').

fixtures/xref/supp_expected_anchors.json is the golden [anchor, start, end]
table, sorted: golden_s3.json of docs/records/2026-10-04_kg_fix/batch1/w1_1B/
(equal after json.load) less the two XREF-2 deletions (1B-C5a), one row per
line.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import process_bible
from bible_chunking.curated_xrefs import (
    parse_anchor, resolve_definitions, verse_map_from_pericopes,
)
from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS

ROOT = Path(__file__).resolve().parents[2]
BIBLE_MD = ROOT / "bible_md"
PERICOPES = ROOT / "output/pericopes.jsonl"
GOLDEN = Path(__file__).parent / "fixtures/xref/supp_expected_anchors.json"

needs_output = pytest.mark.skipif(not PERICOPES.is_file(),
                                  reason="output/pericopes.jsonl missing (run Step 0 first)")


@pytest.fixture(scope="module")
def pericopes() -> list[dict]:
    with PERICOPES.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="module")
def anchors(pericopes):
    found, errors = resolve_definitions(SUPPLEMENTARY_CROSS_REFS, verse_map_from_pericopes(pericopes))
    assert errors == []
    return found


def test_process_bible_stops_before_writing_on_a_bad_definition(tmp_path, monkeypatch, caplog):
    # Both shapes, so the same test runs against the a32fbea code: there the
    # source pericope id mat:99:0 is not a node and the definition was skipped.
    bad = SimpleNamespace(
        source_pericope_id="mat:99:0", target_pericope_id="isa:7:0",
        source_verses="1", target_verses="14",
        src="mat 99:1", tgt="isa 7:14",
        ref_type="quotation", description="mat 99 does not exist", tsk_exempt=None)
    monkeypatch.setattr(process_bible, "SUPPLEMENTARY_CROSS_REFS", [*SUPPLEMENTARY_CROSS_REFS, bad])
    monkeypatch.setattr(sys, "argv", ["process_bible.py", "--input-dir", str(BIBLE_MD),
                                      "--output-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as stopped:
        process_bible.main()

    assert stopped.value.code == 1
    assert sorted(path.name for path in tmp_path.glob("*.jsonl")) == []
    assert (f"definition {len(SUPPLEMENTARY_CROSS_REFS)}: 'mat 99:1': verses 1 are in no pericope"
            in caplog.text)


def test_process_bible_stops_before_writing_on_a_non_string_value(tmp_path, monkeypatch,
                                                                 caplog):
    # resolves, but a null description cannot be stored in a Neo4j list
    bad = SimpleNamespace(src="mat 1:23", tgt="isa 7:14", ref_type="quotation",
                          description=None, tsk_exempt=None)
    monkeypatch.setattr(process_bible, "SUPPLEMENTARY_CROSS_REFS", [*SUPPLEMENTARY_CROSS_REFS, bad])
    monkeypatch.setattr(sys, "argv", ["process_bible.py", "--input-dir", str(BIBLE_MD),
                                      "--output-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as stopped:
        process_bible.main()

    assert stopped.value.code == 1
    assert sorted(path.name for path in tmp_path.glob("*.jsonl")) == []
    assert "supp_descriptions holds a non-string" in caplog.text
    assert "no JSONL written" in caplog.text


@needs_output
def test_step0_verse_map_equals_pericopes_jsonl(tmp_path, pericopes):
    """Step 0 resolves through the same (book, chapter, verse) map that
    validate_output and Step 9 rebuild from output/pericopes.jsonl."""
    processor = process_bible.BibleProcessor(BIBLE_MD, tmp_path)
    assert processor._parse_books()
    assert processor._verse_map() == verse_map_from_pericopes(pericopes)


@needs_output
def test_definitions_resolve_to_golden(anchors):
    table = sorted([anchor.text, anchor.start, anchor.end] for anchor in anchors)
    assert table == json.loads(GOLDEN.read_text(encoding="utf-8"))


@needs_output
def test_every_anchor_verse_inside_its_pericopes(anchors, pericopes):
    verses_of = {}
    for record in pericopes:
        meta, numbers = record["metadata"], set()
        for verse in record["verses"]:
            lo, _, hi = verse["num"].partition("-")
            numbers.update(range(int(lo), int(hi or lo) + 1))
        verses_of[record["id"]] = (meta["book_id"], meta["chapter_num"], numbers)
    for anchor in anchors:
        for coord, pid in zip(parse_anchor(anchor.text), (anchor.start, anchor.end)):
            book, chapter, numbers = verses_of[pid]
            assert (coord.book, coord.chapter) == (book, chapter), anchor
            assert set(coord.verses) <= numbers, anchor


@pytest.fixture(scope="module")
def step0(tmp_path_factory):
    """The CROSS_REFERENCES rows of a real Step 0 run, and its markdown ref count."""
    out = tmp_path_factory.mktemp("step0")
    processor = process_bible.BibleProcessor(BIBLE_MD, out)
    assert processor.run()
    md_refs = sum(1 for book in processor.books for chapter in book.chapters
                  for pericope in chapter.pericopes for cr in pericope.cross_references
                  if cr.book_id and cr.chapter)
    with (out / "neo4j_relationships.jsonl").open(encoding="utf-8") as f:
        rows = [row for row in map(json.loads, f) if row["type"] == "CROSS_REFERENCES"]
    return rows, md_refs


# XREF-2 (1B-C5a): two definitions with no verse-level TSK support in either
# direction, deleted (evidence in test_supp_defs_frozen.DELETED); their anchors
# must not come back through another definition either.
XREF2_DELETED = {("rev 20:4", "isa 65:17"): ("rev:20:0", "isa:65:1"),
                 ("rev 19:1", "psa 118:1"): ("rev:19:0", "psa:118:0")}


def test_xref2_deleted_definitions_absent(step0):
    assert {(ref.src, ref.tgt) for ref in SUPPLEMENTARY_CROSS_REFS}.isdisjoint(XREF2_DELETED)
    rows, _ = step0
    supp_pairs = {(r["start"], r["end"]) for r in rows if r["properties"].get("supp_anchors")}
    assert supp_pairs.isdisjoint(XREF2_DELETED.values())


def test_step0_writes_one_curated_row_per_pair(step0):
    rows, md_refs = step0
    assert Counter((r["start"], r["end"]) for r in rows).most_common(1)[0][1] == 1
    props = [r["properties"] for r in rows]
    assert all(p["curated"] is True and p["tsk"] is False and p["curated_sources"]
               for p in props)
    # no markdown ref and no supplementary anchor is swallowed by its pair
    assert sum(len(p.get("md_anchors", [])) for p in props) == md_refs
    table = sorted([anchor, r["start"], r["end"]]
                   for r in rows for anchor in r["properties"].get("supp_anchors", []))
    assert table == json.loads(GOLDEN.read_text(encoding="utf-8"))
    # what the parser left unread is marked '?', never stored as a plausible range:
    # 代下15‧16－16‧6 is '2ch 15:16-?', not '2ch 15:16' (XREF-5, 2D)
    marked = Counter()
    for p in props:
        for text, anchor in zip(p.get("md_ref_texts", []), p.get("md_anchors", [])):
            ends = re.fullmatch(r"[0-9a-z]+ \d+:\?>[0-9a-z]+ \d+:(\?|\d+(-\d+|-\?)?)(,\?)?",
                                anchor)
            assert ends, anchor
            lo, _, hi = ends.group(1).partition("-")
            assert hi in ("", "?") or int(lo) < int(hi), anchor
            cross_chapter = bool(re.search(r"[－\-]\d+[‧·.]\d+", text))
            assert (hi == "?") == cross_chapter, (text, anchor)
            assert bool(ends.group(3)) == ("，" in text), (text, anchor)
            marked.update(["-?"] * cross_chapter + [",?"] * bool(ends.group(3)))
    assert marked["-?"] and marked[",?"]
