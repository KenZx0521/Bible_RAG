"""S5 legacy map: old pericope, chunk and verse ids to the new records (design §3.3)."""

from __future__ import annotations

import json

import pytest

import mini_build
import ref_dirs
from ragdata.gates import check_schema
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import legacy
from ragdata.stages.s05_struct.view import text_view


def _view():
    _, snap = check_schema(mini_build.files("text"), ("text",))
    return text_view(snap)


def _inputs(pericopes=None, chunks=None):
    return legacy.LegacyInputs(tuple(mini_build.legacy_pericopes() if pericopes is None else pericopes),
                               tuple(mini_build.legacy_chunks() if chunks is None else chunks), {})


def _map(inputs):
    return legacy.legacy_rows(inputs, mini_build.struct_layer(), _view())


def test_the_mini_legacy_rows_map_as_hand_built():
    assert _map(_inputs()) == mini_build.struct_layer()["legacy_ids"]


def test_an_old_range_that_no_new_record_covers_is_refused():
    old = [{"id": "act:11:0", "metadata": {"book_id": "act", "chapter_num": 11, "verse_range": "1"},
            "verses": []}]
    with pytest.raises(StageError, match="act:11:0"):
        _map(_inputs(pericopes=old, chunks=[]))


def test_an_old_verse_that_is_neither_a_unit_nor_omitted_is_refused():
    old = mini_build.legacy_pericopes()
    old[-1]["verses"] = [{"num": "1"}, {"num": "2"}, {"num": "3"}, {"num": "4"}]  # eph 6:2-3 merged
    with pytest.raises(StageError, match="eph:6:0:v:2"):
        _map(_inputs(pericopes=old))


@pytest.mark.parametrize("metadata", [
    {"book_id": "act", "chapter_num": 9},
    {"book_id": "act", "chapter_num": 9, "verse_range": "3-1"},
    {"book_id": "act", "chapter_num": 9, "verse_range": "一"},
    {"book_id": "xyz", "chapter_num": 9, "verse_range": "1"},
])
def test_malformed_old_rows_are_refused(metadata):
    old = [{"id": "act:9:0", "metadata": metadata, "verses": []}]
    with pytest.raises(StageError, match="act:9:0"):
        _map(_inputs(pericopes=old, chunks=[]))


def test_an_old_row_without_an_id_or_with_a_bad_verse_is_refused():
    with pytest.raises(StageError, match="without an id"):
        _map(_inputs(pericopes=[{"metadata": {}}], chunks=[]))
    old = mini_build.legacy_pericopes()[:1]
    old[0]["verses"] = ["1"]
    with pytest.raises(StageError, match="psa:42:0:v:None"):
        _map(_inputs(pericopes=old, chunks=[]))


def test_load_reads_both_files_and_records_their_sha256(tmp_path):
    for name, rows in (("pericopes.jsonl", mini_build.legacy_pericopes()),
                       ("chunks.jsonl", mini_build.legacy_chunks())):
        (tmp_path / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                     encoding="utf-8")
    loaded = legacy.load_legacy(ref_dirs.sign(tmp_path))
    assert loaded == _inputs()._replace(sha256=loaded.sha256)
    assert set(loaded.sha256) == {"pericopes.jsonl", "chunks.jsonl"}


def test_load_refuses_a_missing_or_broken_file(tmp_path):
    with pytest.raises(StageError, match="pericopes.jsonl"):
        legacy.load_legacy(tmp_path)
    (tmp_path / "pericopes.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "chunks.jsonl").write_text("[1]\n", encoding="utf-8")
    with pytest.raises(StageError, match="SHA256SUMS"):
        legacy.load_legacy(tmp_path)
    with pytest.raises(StageError, match="chunks.jsonl:1"):
        legacy.load_legacy(ref_dirs.sign(tmp_path))


def test_load_refuses_a_file_its_sha256sums_does_not_list(tmp_path):
    for name, rows in (("pericopes.jsonl", mini_build.legacy_pericopes()),
                       ("chunks.jsonl", mini_build.legacy_chunks())):
        (tmp_path / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                     encoding="utf-8")
    ref_dirs.sign(tmp_path)
    with open(tmp_path / "chunks.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(StageError, match="chunks.jsonl: sha256 .* the reference copy changed"):
        legacy.load_legacy(tmp_path)
