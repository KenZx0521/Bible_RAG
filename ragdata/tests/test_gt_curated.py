"""The curated GT v2 decisions file: schema errors are refused, the real file parses."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragdata.gt.curated import CuratedError, load_curated, parse_curated

REAL = Path(__file__).resolve().parents[2] / "config" / "gold" / "gt_v2_curated.yaml"
FIX = {"qid": "Q", "field": "reference_answer", "before": "a", "after": "b",
       "evidence_slot": "gen.1.1", "reason": "r"}


@pytest.mark.parametrize("doc, message", [
    ({"quote_fixes": []}, "schema"),
    ({"schema": "ragdata.gt_v2_curated.v1", "notes": []}, "unknown sections"),
    ({"schema": "ragdata.gt_v2_curated.v1", "quote_fixes": [{"qid": "Q"}]}, "keys"),
    ({"schema": "ragdata.gt_v2_curated.v1", "quote_fixes": [{**FIX, "after": ""}]}, "non-empty"),
])
def test_a_file_that_breaks_the_schema_is_refused(doc, message):
    with pytest.raises(CuratedError, match=message):
        parse_curated(doc)


def test_the_committed_decisions_parse_and_kay_review_stays_short():
    curated = load_curated(REAL)
    assert curated.quote_fixes and curated.quote_exempt
    assert len(curated.kay_review) <= 5
