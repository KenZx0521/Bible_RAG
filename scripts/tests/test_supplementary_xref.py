"""Supplementary cross references in Step 0 (1B-C3c, XREF-1(a)).

The definitions in bible_chunking/nt_cross_references.py name both ends in
verse coordinates. process_bible resolves every verse of both ends to its
pericope (bible_chunking/curated_xrefs.py) and writes one CROSS_REFERENCES
row per touched pericope pair. A definition that does not resolve stops Step 0
before any JSONL is written: the old code skipped a definition whose source
pericope id did not exist (16 of 161) and let a target fall back to the
chapter.

fixtures/xref/supp_expected_anchors.json is the golden [anchor, start, end]
table, sorted: golden_s3.json of docs/records/2026-10-04_kg_fix/batch1/w1_1B/
(equal after json.load), one row per line.
"""

import json
import sys
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
    assert "definition 161: 'mat 99:1': verses 1 are in no pericope" in caplog.text


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
