"""G-SCHEMA: every row passes its contract, files are complete, keys and sequences are sound."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema

BOTH = ("text", "struct")


def test_mini_snapshot_passes_and_yields_typed_records():
    result, snapshot = check_schema(mini_build.files(*BOTH), BOTH)
    assert result.passed, result.details
    assert result.to_json() == {"name": "G-SCHEMA", "hard": True, "pass": True,
                                "observed": {"violations": 0}, "expected": {"violations": 0},
                                "details": []}
    assert len(snapshot.of("verse_units")) == 14
    assert snapshot.index("verse_slots")["eph.6.3"].unit_key == "eph.6.2-3"


def test_broken_row_fails_with_its_location_and_is_dropped():
    files = mini_build.files("text")
    files["verse_units.jsonl"][2]["text_sha256"] = "0" * 64
    result, snapshot = check_schema(files, ("text",))
    assert not result.passed
    assert result.details[0].startswith("verse_units.jsonl:3: ")
    assert len(snapshot.of("verse_units")) == 13


def _fails(files, layers=("text",)) -> list[str]:
    result, _ = check_schema(files, layers)
    assert not result.passed and result.hard
    return list(result.details)


def test_missing_and_unknown_files_fail():
    files = mini_build.files("text")
    del files["footnotes.jsonl"]
    files["verses.jsonl"] = []
    details = _fails(files)
    assert any("footnotes.jsonl" in d for d in details)
    assert any("verses.jsonl" in d for d in details)


def test_struct_layer_requires_its_text_dependency_files_only_when_gated_together():
    assert check_schema(mini_build.files("struct"), ("struct",))[0].passed
    _fails(mini_build.files("struct"), BOTH)


def test_duplicate_primary_key_fails():
    files = mini_build.files("text")
    files["headings.jsonl"].append(dict(files["headings.jsonl"][0]))
    assert any("hd:psa.42.1#1" in d for d in _fails(files))


def _renumber_footnote(files):
    row = next(r for r in files["footnotes.jsonl"] if r["fn_id"] == "fn:act.9.1#1")
    row.update(fn_id="fn:act.9.1#2", n=2)


def _renumber_heading(files):
    row = next(r for r in files["headings.jsonl"] if r["heading_id"] == "hd:eph.6.1#1")
    row["heading_id"] = "hd:eph.6.1#3"


def _skip_parallel_segment(files):
    files["parallel_refs.jsonl"] = [r for r in files["parallel_refs.jsonl"]
                                    if r["pr_id"] != "pr:hd:mat.18.1#1#1"]


def _skip_chunk(files):
    files["chunks.jsonl"] = files["chunks.jsonl"][1:]


@pytest.mark.parametrize("mutate", [_renumber_footnote, _renumber_heading,
                                    _skip_parallel_segment, _skip_chunk])
def test_sequence_gaps_fail(mutate):
    files = mini_build.files(*BOTH)
    mutate(files)
    assert any("sequence" in d for d in _fails(files, BOTH))


def test_details_are_capped_but_the_count_is_exact():
    files = mini_build.files("text")
    for row in files["name_spans.jsonl"]:
        row["source"] = "lexicon"
    files["name_spans.jsonl"] = files["name_spans.jsonl"] * 10
    result, _ = check_schema(files, ("text",), max_details=5)
    assert result.observed == {"violations": 90}
    assert len(result.details) == 6 and result.details[-1] == "… 85 more"
