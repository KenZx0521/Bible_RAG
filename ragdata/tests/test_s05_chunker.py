"""S5 chunking: bible_chunking.hierarchical_chunker, ported to passages and pieces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import chunker, tokens
from ragdata.stages.s05_struct.view import Piece, text_view

MINI = tokens.TokenCounter(mini_build.count_tokens, {"tokenizer": "mini"})


@pytest.mark.parametrize("counts, budget, expected", [
    ([100, 100], 450, [(0, 2)]),
    ([300, 100, 300, 100], 450, [(0, 2), (1, 3), (2, 4)]),
    ([400, 40, 30], 450, [(0, 3)]),                       # a small tail of <=3 pieces merges back
    ([400, 40, 30, 20, 10], 450, [(0, 2), (1, 5)]),       # ... but not a tail of 4
    ([300, 100, 300, 200], 450, [(0, 2), (1, 3), (2, 4)]),  # a tail of 128 tokens or more stays
])
def test_plan_follows_the_old_chunker(counts, budget, expected):
    assert chunker.plan_chunks(counts, budget) == expected


def test_a_piece_over_the_budget_cannot_be_chunked():
    with pytest.raises(StageError, match="budget"):
        chunker.plan_chunks([100, 500, 100], 450)


def _act_9_1():
    _, snap = check_schema(mini_build.files("text"), ("text",))
    view = text_view(snap)
    mid = mini_build.ACT_MID
    pieces = (Piece(view.unit["act.9.1"]), Piece(view.unit["act.9.2"]),
              Piece(view.unit["act.9.3"], 0, mid))
    return view, pieces


def test_chunk_rows_of_the_mini_passage_are_the_hand_built_chunks():
    view, pieces = _act_9_1()
    rows = chunker.chunk_rows(view, "ps:act.9.1", pieces, "掃羅歸主－在路上", MINI)
    assert rows == mini_build.struct_layer()["chunks"]


def test_a_chunk_over_768_tokens_stops_the_build():
    view, pieces = _act_9_1()
    heavy = tokens.TokenCounter(lambda text: 1000 if len(text) > 50 else 1, {})
    with pytest.raises(StageError, match="768"):
        chunker.chunk_rows(view, "ps:act.9.1", pieces, "掃羅歸主－在路上", heavy)


def test_a_missing_or_unpinned_tokenizer_stops_the_build(tmp_path):
    with pytest.raises(StageError, match="tokenizer"):
        tokens.pinned_counter(tmp_path / "tokenizer.json")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StageError, match="sha256"):
        tokens.pinned_counter(tmp_path / "tokenizer.json")


HF_HOME = Path(os.environ.get("HF_HOME", "/mnt/ollama-data/huggingface"))


@pytest.mark.skipif(not (HF_HOME / "hub").is_dir(), reason="no local HF cache")
def test_the_pinned_counter_counts_bge_m3_tokens_without_special_tokens(monkeypatch):
    monkeypatch.setenv("HF_HOME", str(HF_HOME))
    counter = tokens.pinned_counter()
    assert counter.count("起初，上帝創造天地。") == 8
    assert counter.fingerprint["tokenizer_sha"].startswith("21106b6d")
