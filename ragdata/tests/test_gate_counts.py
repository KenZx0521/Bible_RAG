"""G-COUNT: absolute counts against the expectation file, with no silent omissions."""

from __future__ import annotations

from pathlib import Path

import pytest

import mini_build
from ragdata.contract.counts import PDF_COUNTS_PATH, CountsError, load_counts
from ragdata.gates import check_counts, check_schema
from ragdata.gates.base import Snapshot
from ragdata.gates.counts import COUNTERS

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
BOTH = ("text", "struct")


def _mini_snapshot() -> Snapshot:
    return check_schema(mini_build.files(*BOTH), BOTH)[1]


@pytest.mark.parametrize("layer", BOTH)
def test_mini_snapshot_matches_its_hand_tallied_counts(layer):
    result = check_counts(_mini_snapshot(), layer, load_counts(MINI_COUNTS)[layer])
    assert result.passed, result.details
    assert result.name == "G-COUNT" and result.hard


@pytest.mark.parametrize("layer", BOTH)
def test_empty_snapshot_is_red(layer):
    result = check_counts(Snapshot({}), layer, load_counts(MINI_COUNTS)[layer])
    assert not result.passed


def test_mismatch_names_the_count_and_its_source():
    snap = check_schema(mini_build.files("text"), ("text",))[1]
    counts = dict(load_counts(MINI_COUNTS)["text"])
    counts["footnotes"] = counts["footnotes"]._replace(value=5)
    result = check_counts(snap, "text", counts)
    assert not result.passed
    assert result.observed["footnotes"] == 4 and result.expected["footnotes"] == 5
    assert result.details == ("footnotes: observed 4, expected 5 (G58)",)


def test_counter_without_expectation_and_expectation_without_counter_both_fail():
    counts = dict(load_counts(MINI_COUNTS)["text"])
    counts["verses"] = counts.pop("books")
    result = check_counts(_mini_snapshot(), "text", counts)
    assert not result.passed
    assert any("books" in d for d in result.details)
    assert any("verses" in d for d in result.details)


def test_old_rows_dropped_from_the_legacy_map_turn_the_count_red():
    files = mini_build.files(*BOTH)
    files["legacy_ids.jsonl"] = [r for r in files["legacy_ids.jsonl"] if r["kind"] != "chunk"]
    snap = check_schema(files, BOTH)[1]
    result = check_counts(snap, "struct", load_counts(MINI_COUNTS)["struct"])
    assert not result.passed
    assert result.details == ("legacy_chunks: observed 0, expected 2 (G17)",)


def test_list_counts_ignore_order():
    counts = dict(load_counts(MINI_COUNTS)["text"])
    snap = _mini_snapshot()
    assert check_counts(snap, "text", counts).passed
    counts["omitted_slot_keys"] = counts["omitted_slot_keys"]._replace(value=("mat.18.4",))
    assert not check_counts(snap, "text", counts).passed


@pytest.mark.parametrize("body", [
    "schema: other\ntext: {}\n",
    "schema: ragdata.pdf_counts.v1\nverses: {}\n",
    "schema: ragdata.pdf_counts.v1\ntext:\n  books: {value: 66}\n",
    "schema: ragdata.pdf_counts.v1\ntext:\n  books: {value: 66, g: [g4]}\n",
    "schema: ragdata.pdf_counts.v1\ntext:\n  books: {value: -1, g: [G04]}\n",
    "schema: ragdata.pdf_counts.v1\ntext:\n  books: {value: true, g: [G04]}\n",
    "schema: ragdata.pdf_counts.v1\ntext:\n  books: {value: 66, g: [G04], extra: 1}\n",
    "- not a mapping\n",
])
def test_malformed_expectation_files_are_rejected(tmp_path, body):
    path = tmp_path / "counts.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(CountsError):
        load_counts(path)


def test_pdf_counts_cover_exactly_the_counters_and_cite_findings():
    counts = load_counts(PDF_COUNTS_PATH)
    for layer in (*BOTH, "emb"):
        assert set(counts[layer]) == set(COUNTERS[layer])
        assert all(e.g and e.definition for e in counts[layer].values())


def test_pdf_counts_are_internally_consistent():
    text = {k: e.value for k, e in load_counts(PDF_COUNTS_PATH)["text"].items()}
    struct = {k: e.value for k, e in load_counts(PDF_COUNTS_PATH)["struct"].items()}
    assert text["present_slots"] + text["omitted_slots"] == text["slot_rows"]
    assert len(text["omitted_slot_keys"]) == text["omitted_slots"]
    assert text["headings_before"] + text["headings_mid"] == text["headings"]
    kinds = sum(text[k] for k in text if k.startswith("footnotes_"))
    assert kinds <= text["footnotes"]
    assert text["section_ranges"] <= text["parallel_segments"]
    assert struct["passages"] == struct["pericopes"] + struct["passages_continued"]
    assert struct["legacy_verses"] == text["verse_units"] + struct["legacy_verses_retired"]
    assert struct["legacy_verses_retired"] < text["omitted_slots"]
    emb = {k: e.value for k, e in load_counts(PDF_COUNTS_PATH)["emb"].items()}
    assert emb["emb_verses"] == text["verse_units"]
    assert emb["embedding_records"] == emb["emb_verses"] + emb["emb_passages"] + emb["emb_chunks"]
    assert emb["emb_passages"] < struct["passages"]


def test_list_expectation_for_a_scalar_count_is_red_not_a_crash():
    counts = dict(load_counts(MINI_COUNTS)["text"])
    counts["books"] = counts["books"]._replace(value=("psa",))
    assert not check_counts(_mini_snapshot(), "text", counts).passed


def test_a_stage_can_check_only_the_counts_of_the_records_it_writes():
    snap = check_schema(mini_build.files("text"), ("text",))[1]
    counts = load_counts(MINI_COUNTS)["text"]
    keys = ("books", "verse_units", "omitted_slot_keys")
    result = check_counts(snap, "text", counts, keys=keys)
    assert result.passed and set(result.observed) == set(result.expected) == set(keys)
    unknown = check_counts(snap, "text", {k: counts[k] for k in keys[:2]}, keys=(*keys, "nope"))
    assert not unknown.passed
    assert set(unknown.details) == {"nope: no counter", "nope: no expectation",
                                    "omitted_slot_keys: no expectation"}
