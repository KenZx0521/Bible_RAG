"""S5 records from the mini text layer equal the hand-built struct layer."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import rows
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.stages.s05_struct.view import text_view

MINI = TokenCounter(mini_build.count_tokens, {"tokenizer": "mini"})


def _view():
    _, snap = check_schema(mini_build.files("text"), ("text",))
    return text_view(snap)


@pytest.mark.parametrize("name", rows.STRUCT_TYPES)
def test_struct_rows_reproduce_the_hand_built_layer(name):
    assert rows.struct_rows(_view(), MINI)[name] == mini_build.struct_layer()[name]


def test_a_unit_no_passage_starts_is_refused():
    passages = [p for p in mini_build.struct_layer()["passages"] if p["passage_id"] != "ps:act.10.1"]
    with pytest.raises(StageError, match="act.10.1"):
        rows.verse_index_rows(_view(), passages)
