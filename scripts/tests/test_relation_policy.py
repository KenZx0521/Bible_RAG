"""relation_policy: which relation row Step 6.05 prefers (source rank, source, parent/child).

Moved from test_relation_postprocess.py (1A-C4i) to keep that file under 800
lines; the rules that use the policy are tested there.
"""

from __future__ import annotations

import pytest

from relation_extraction.relation_policy import SOURCE_RANK, parent_child, rank, source_of


def test_source_rank_orders_curated_prior_llm_anchored():
    assert SOURCE_RANK == {"curated": 0, "prior": 1, "llm": 2, "anchored_rule": 3}
    assert rank({"source": "prior"}) < rank({"extraction_phase": 4}) < rank({"source": "anchored_rule"})


@pytest.mark.parametrize("row", [{"source": "inverse"}, {"extraction_phase": 2}, {"extraction_phase": 1},
                                 {"extraction_phase": 5, "notes": "cooccurrence-backfill"}])
def test_rank_fails_fast_on_an_unranked_source(row):
    with pytest.raises(ValueError, match="rank"):
        rank(row)


def test_source_of_and_parent_child_read_a_row():
    assert source_of({"extraction_phase": 5, "notes": "derived_from=SON_OF"}) == "inverse"
    assert source_of({"source": "curated", "extraction_phase": 3}) == "curated"
    assert parent_child({"head_id": "a", "relation": "SON_OF", "tail_id": "b"}) == ("b", "a")
    assert parent_child({"head_id": "a", "relation": "MOTHER_OF", "tail_id": "b"}) == ("a", "b")
    assert parent_child({"head_id": "a", "relation": "SPOUSE_OF", "tail_id": "b"}) is None
