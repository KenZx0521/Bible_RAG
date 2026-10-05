"""validate_output: the Step 0 cross-reference gate (1B-C7).

Step 0 writes one curated CROSS_REFERENCES row per (start, end) pair
(bible_chunking/curated_xrefs.aggregate_curated); Step 5 MERGEs on the pair
and Step 9 adds TSK votes to it. validate_cross_references checks those rows
before anything is imported:

- errors (exit 1): a duplicate pair; an endpoint that is not a Pericope (a
  chapter fallback such as 'isa:9'); curated flags that are not curated true,
  tsk false, curated_sources sorted ⊆ {markdown, supplementary} and source =
  the first of them; a source's lists missing, misaligned or present without
  the source; a None value or list element; a supplementary anchor that does
  not parse or names verses outside its endpoint pericopes; and definition
  coverage: the anchors in the rows must be, as a multiset of (start, end,
  anchor), exactly what the definitions resolve to.
- warnings: markdown∩supplementary pairs (X4, aggregated; expected after 2D)
  and markdown anchors marked '-?' or ',?' (XREF-5, owned by 2D). Markdown
  verses are not checked.
"""

import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest

import process_bible
import validate_output
from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS
from validate_output import validate_cross_references

BIBLE_MD = validate_output.ROOT / "bible_md"


def _pericope(pid: str, *nums: str) -> dict:
    book, chapter, _ = pid.split(":")
    return {"id": pid, "metadata": {"book_id": book, "chapter_num": int(chapter)},
            "verses": [{"num": num} for num in nums]}


PERICOPES = [
    _pericope("gen:5:0", "1-32"), _pericope("1ch:1:0", "1", "2", "3-4"),
    _pericope("mat:1:0", "18-25"), _pericope("isa:7:0", "10-16"),
    _pericope("mat:4:0", "12-17"), _pericope("isa:9:0", "1"), _pericope("isa:9:1", "2-7"),
]

DEFINITIONS = [
    SimpleNamespace(src="mat 1:23", tgt="isa 7:14", ref_type="quotation",
                    description="童女懷孕", tsk_exempt=None),
    # straddles isa:9:0 / isa:9:1: one anchor per touched pericope pair
    SimpleNamespace(src="mat 4:15-16", tgt="isa 9:1-2", ref_type="quotation",
                    description="外邦的加利利", tsk_exempt=None),
]


def _supp(start: str, end: str, anchor: str, description: str) -> dict:
    return {"start": start, "end": end, "type": "CROSS_REFERENCES",
            "properties": {"source": "supplementary", "curated": True, "tsk": False,
                           "curated_sources": ["supplementary"], "supp_anchors": [anchor],
                           "supp_ref_types": ["quotation"], "supp_descriptions": [description]}}


def _rows() -> list[dict]:
    """A minimal valid Step 0 relationship set for PERICOPES and DEFINITIONS."""
    return [
        {"start": "gen:5:0", "end": "1ch:1:0", "type": "CROSS_REFERENCES",
         "properties": {"source": "markdown", "curated": True, "tsk": False,
                        "curated_sources": ["markdown"], "md_ref_texts": ["代上1‧1－4"],
                        "md_anchors": ["gen 5:?>1ch 1:1-4"]}},
        _supp("mat:1:0", "isa:7:0", "mat 1:23>isa 7:14", "童女懷孕"),
        _supp("mat:4:0", "isa:9:0", "mat 4:15-16>isa 9:1", "外邦的加利利"),
        _supp("mat:4:0", "isa:9:1", "mat 4:15-16>isa 9:2", "外邦的加利利"),
        # only CROSS_REFERENCES rows are checked
        {"start": "gen:5:0", "end": "gen:5:0:c0", "type": "CONTAINS", "properties": {}},
        {"start": "gen:5:0", "end": "gen:5:0:c0", "type": "CONTAINS", "properties": {}},
    ]


def _props(rows: list[dict], start: str, end: str) -> dict:
    return next(r["properties"] for r in rows
                if (r["start"], r["end"]) == (start, end) and r["type"] == "CROSS_REFERENCES")


def _check(rows: list[dict], definitions=DEFINITIONS):
    return validate_cross_references(rows, PERICOPES, definitions)


def test_minimal_valid_rows_pass_with_stats():
    errors, warnings, stats = _check(_rows())

    assert errors == []
    assert warnings == []
    assert stats == {"rows": 4, "markdown": 1, "supplementary": 3, "duplicates": 0,
                     "non_pericope_endpoints": 0, "anchors": 3, "definitions": 2,
                     "definitions_covered": 2, "overlap": 0, "md_unknown_end": 0,
                     "md_unread_ranges": 0}


def _set(start, end, key, value):
    def mutate(rows):
        _props(rows, start, end)[key] = value
    return mutate


def _delete(start, end, key):
    def mutate(rows):
        del _props(rows, start, end)[key]
    return mutate


def _duplicate(rows):
    rows.append(copy.deepcopy(rows[1]))


def _chapter_endpoint(rows):
    # the old chapter fallback of an unresolved markdown target
    rows[0]["end"] = "isa:9"


def _drop(start, end):
    def mutate(rows):
        rows.remove(next(r for r in rows if (r["start"], r["end"]) == (start, end)))
    return mutate


def _add_markdown_lists(rows):
    # the lists of a source the pair does not have
    _props(rows, "mat:1:0", "isa:7:0").update(md_ref_texts=["賽7‧14"],
                                              md_anchors=["mat 1:?>isa 7:14"])


def _extra_anchor(rows):
    props = _props(rows, "mat:1:0", "isa:7:0")
    props["supp_anchors"].append("mat 1:22>isa 7:14")
    props["supp_ref_types"].append("quotation")
    props["supp_descriptions"].append("應驗先知的話")


ERROR_CASES = {
    "duplicate pair": (_duplicate, "duplicate pair: mat:1:0→isa:7:0 (2 rows)"),
    "chapter endpoint": (_chapter_endpoint, "not a Pericope: end isa:9 of gen:5:0→isa:9"),
    "tsk missing": (_delete("gen:5:0", "1ch:1:0", "tsk"), "gen:5:0→1ch:1:0: tsk is not false"),
    "curated false": (_set("mat:1:0", "isa:7:0", "curated", False),
                      "mat:1:0→isa:7:0: curated is not true"),
    "unknown source": (_set("gen:5:0", "1ch:1:0", "curated_sources", ["markdown", "tsk"]),
                       "curated_sources ['markdown', 'tsk']"),
    "not the priority source": (_set("gen:5:0", "1ch:1:0", "source", "supplementary"),
                                "source 'supplementary' is not 'markdown'"),
    "None in supp_descriptions": (_set("mat:1:0", "isa:7:0", "supp_descriptions", [None]),
                                  "mat:1:0→isa:7:0: supp_descriptions holds None"),
    "None value": (_set("gen:5:0", "1ch:1:0", "md_anchors", None),
                   "gen:5:0→1ch:1:0: md_anchors is None"),
    "misaligned lists": (_set("gen:5:0", "1ch:1:0", "md_ref_texts", ["代上1‧1－4", "代上1‧1"]),
                         "markdown lists misaligned: md_ref_texts 2, md_anchors 1"),
    "list missing": (_delete("mat:1:0", "isa:7:0", "supp_ref_types"),
                     "mat:1:0→isa:7:0: supp_ref_types missing (supplementary is a source)"),
    "list without its source": (_add_markdown_lists,
                                "md_anchors present but markdown is not a source"),
    "list that is not a list": (_set("gen:5:0", "1ch:1:0", "md_anchors", "gen 5:?>1ch 1:1-4"),
                                "md_anchors is not a non-empty list: 'gen 5:?>1ch 1:1-4'"),
    "exempt anchor of another pair": (
        _set("mat:1:0", "isa:7:0", "supp_tsk_exempt_anchors", ["mat 4:15-16>isa 9:1"]),
        "supp_tsk_exempt_anchors ['mat 4:15-16>isa 9:1'] not among supp_anchors"),
    "anchor verse outside the pericope": (
        _set("mat:1:0", "isa:7:0", "supp_anchors", ["mat 1:23>isa 7:17"]),
        "'mat 1:23>isa 7:17': verses 17 are not in isa:7:0"),
    "anchor in the wrong chapter": (
        _set("mat:1:0", "isa:7:0", "supp_anchors", ["mat 1:23>isa 8:14"]),
        "'mat 1:23>isa 8:14': isa 8 is not the chapter of isa:7:0"),
    "unparseable anchor": (_set("mat:1:0", "isa:7:0", "supp_anchors", ["mat 1:23 isa 7:14"]),
                           "mat:1:0→isa:7:0: unparseable anchor 'mat 1:23 isa 7:14'"),
    "definition without an anchor": (
        _drop("mat:1:0", "isa:7:0"), "definition 0 (mat 1:23>isa 7:14) has no anchor in the rows"),
    "anchor missing": (_drop("mat:4:0", "isa:9:1"),
                       "anchor missing from the rows: mat:4:0→isa:9:1 'mat 4:15-16>isa 9:2'"),
    "extra anchor": (_extra_anchor,
                     "anchor from no definition: mat:1:0→isa:7:0 'mat 1:22>isa 7:14'"),
}


@pytest.mark.parametrize("case", ERROR_CASES)
def test_each_error_class_fails_the_gate(case):
    mutate, expected = ERROR_CASES[case]
    rows = _rows()
    mutate(rows)

    errors, _, _ = _check(rows)

    assert any(expected in error for error in errors), errors


def test_tsk_exempt_anchors_of_the_pair_pass():
    rows = _rows()
    _props(rows, "mat:1:0", "isa:7:0")["supp_tsk_exempt_anchors"] = ["mat 1:23>isa 7:14"]

    errors, warnings, _ = _check(rows)

    assert (errors, warnings) == ([], [])


def test_partly_present_definition_is_not_covered():
    rows = _rows()
    _drop("mat:4:0", "isa:9:1")(rows)

    errors, _, stats = _check(rows)

    assert stats["definitions_covered"] == 1
    assert not any("definition 1" in error for error in errors), errors


def test_definition_that_does_not_resolve_is_an_error():
    bad = SimpleNamespace(src="mat 99:1", tgt="isa 7:14", ref_type="quotation",
                          description="mat 99 does not exist", tsk_exempt=None)

    errors, _, stats = _check(_rows(), [*DEFINITIONS, bad])

    assert any("definition 2: 'mat 99:1': verses 1 are in no pericope" in e for e in errors)
    assert (stats["definitions_covered"], stats["definitions"]) == (2, 3)


def test_pre_1b_rows_fail_the_gate():
    # the row shapes of the pre-1B output/ (sha 15ed2505…): no curated flags
    rows = [
        {"start": "gen:5:0", "end": "1ch:1:0", "type": "CROSS_REFERENCES",
         "properties": {"ref_text": "代上1‧1－4", "verse_start": 1, "verse_end": 4,
                        "source": "markdown"}},
        {"start": "mat:1:0", "end": "isa:7:0", "type": "CROSS_REFERENCES",
         "properties": {"source": "supplementary", "ref_type": "quotation",
                        "source_verses": "23", "target_verses": "14", "description": "童女懷孕"}},
    ]

    errors, _, stats = _check(rows)

    assert any("gen:5:0→1ch:1:0: curated is not true" in e for e in errors), errors
    assert any("definition 1 (mat 4:15-16>isa 9:1-2) has no anchor" in e for e in errors)
    assert stats["definitions_covered"] == 0


def test_many_problems_of_one_check_are_listed_with_a_count():
    rows = [{"start": "gen:5:0", "end": f"isa:{n}", "type": "CROSS_REFERENCES",
             "properties": {}} for n in range(1, 16)]

    errors, _, stats = _check(rows)

    endpoint_errors = [e for e in errors if e.startswith("not a Pericope")]
    assert len(endpoint_errors) == validate_output.MAX_LISTED + 1
    assert endpoint_errors[-1] == f"not a Pericope: … and {15 - validate_output.MAX_LISTED} more"
    assert stats["non_pericope_endpoints"] == 15


def test_markdown_supplementary_overlap_is_a_warning():
    rows = _rows()
    _props(rows, "mat:1:0", "isa:7:0").update(
        source="markdown", curated_sources=["markdown", "supplementary"],
        md_ref_texts=["賽7‧14"], md_anchors=["mat 1:?>isa 7:14"])

    errors, warnings, stats = _check(rows)

    assert errors == []
    assert [w.split(" (")[0] for w in warnings] == ["markdown∩supplementary pairs: 1"]
    assert (stats["markdown"], stats["supplementary"], stats["overlap"]) == (2, 3, 1)


@pytest.mark.parametrize("anchor, warning, stat", [
    ("gen 5:?>1ch 1:1-?", "markdown anchors with unknown target end: 1", "md_unknown_end"),
    ("gen 5:?>1ch 1:1-4,?", "markdown anchors with unread ranges after a comma: 1",
     "md_unread_ranges"),
])
def test_markdown_unread_markers_are_warnings(anchor, warning, stat):
    rows = _rows()
    _props(rows, "gen:5:0", "1ch:1:0")["md_anchors"] = [anchor]

    errors, warnings, stats = _check(rows)

    assert errors == []
    assert [w.split(" (")[0] for w in warnings] == [warning]
    assert stats[stat] == 1


@pytest.fixture(scope="module")
def step0_dir(tmp_path_factory):
    """A scratch Step 0 output of this checkout."""
    if not BIBLE_MD.is_dir():
        pytest.skip("bible_md missing")
    out = tmp_path_factory.mktemp("step0")
    assert process_bible.BibleProcessor(BIBLE_MD, out).run()
    return out


def _main(monkeypatch, output_dir) -> int:
    monkeypatch.setattr(sys, "argv", ["validate_output.py", str(output_dir)])
    with pytest.raises(SystemExit) as stopped:
        validate_output.main()
    return stopped.value.code


def test_real_step0_output_passes_the_gate(step0_dir, monkeypatch, capsys):
    n = len(SUPPLEMENTARY_CROSS_REFS)

    assert _main(monkeypatch, step0_dir) == 0

    out = capsys.readouterr().out
    assert "\n  Duplicate pairs: 0\n" in out
    assert "\n  Non-Pericope endpoints: 0\n" in out
    assert f"\n  Definitions covered: {n}/{n}\n" in out
    assert "[ERROR]" not in out


def test_real_step0_output_with_a_duplicate_pair_fails(step0_dir, tmp_path, monkeypatch,
                                                      capsys):
    for path in step0_dir.iterdir():
        os.symlink(path, tmp_path / path.name)
    rels = tmp_path / "neo4j_relationships.jsonl"
    rows = (step0_dir / rels.name).read_text(encoding="utf-8").splitlines()
    rels.unlink()
    xref = next(row for row in rows if json.loads(row)["type"] == "CROSS_REFERENCES")
    rels.write_text("\n".join([*rows, xref]) + "\n", encoding="utf-8")

    assert _main(monkeypatch, tmp_path) == 1

    pair = json.loads(xref)
    assert f"[ERROR] duplicate pair: {pair['start']}→{pair['end']} (2 rows)" in (
        capsys.readouterr().out)
