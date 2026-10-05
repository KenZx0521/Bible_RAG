"""Step 6.05 rules_to_anchored (REL-01): its three helpers, called directly.

The fixture run in test_relation_postprocess.py cannot see these: by the time
the guard reads parents the rule and inverse rows are already dropped, no two
hits of one key share a verse, and _anchored_rows already emits rows in key
order. Each test here feeds the helper the input that tells the documented
behaviour from the plausible wrong one.
"""

from __future__ import annotations

import pytest

from relation_extraction import relation_postprocess as pp
from test_relation_postprocess import AMRAM, P1, P3, _key_set_sha256, _paths, _row

MOSES = ("person:anlan", "FATHER_OF", "person:moxi")   # 「她給暗蘭生了亞倫、摩西」, num 26:59
AARON = ("person:anlan", "FATHER_OF", "person:yalun")


@pytest.mark.parametrize("source, abstains", [
    ("rule", False), ("inverse", False), ("curated", True), ("prior", True), ("llm", True)])
def test_guard_reads_parents_from_curated_prior_and_llm_rows_only(source, abstains):
    # the one row giving 摩西 a parent besides 暗蘭 (a mother counts) has this source
    inputs, cfg = pp.load_inputs(_paths())
    parent = _row("person:moxi", "SON_OF", "person:yuejibie", 4, source=source)

    hits, stats, conflicts = pp._anchored_hits([parent], inputs, cfg)

    keys = {(hit["head_id"], hit["relation"], hit["tail_id"]) for hit in hits}
    assert (MOSES in keys) is not abstains and AARON in keys
    assert stats["guard_other_parent"] == int(abstains)
    assert [conflict["reason"] for conflict in conflicts] == ["other_parent"] * abstains


def _hit(pattern: str, verse: int, text: str) -> dict:
    return {"head_id": MOSES[0], "relation": MOSES[1], "tail_id": MOSES[2], "source_pericope_id": "num:26:0",
            "verse": verse, "pattern": pattern, "evidence_span": text}


def test_anchored_row_counts_distinct_verses_and_takes_the_first_smallest_hit():
    inputs, _ = pp.load_inputs(_paths())
    hits = [_hit(P3, 59, AMRAM),
            _hit(P1, 59, AMRAM),           # the same verse by another pattern: no new evidence
            _hit(P3, 60, "num 26:60")]     # another verse of the same pericope: new evidence

    [row] = pp._anchored_rows(hits, inputs.entities)

    # the primary is the smallest (pericope, verse); of the two tied hits, the first
    assert (row["notes"], row["verse"], row["evidence_span"]) == (P3, 59, AMRAM)
    assert row["support_pericopes"] == ["num:26:0"]
    assert row["evidence_count"] == 2


def test_key_set_sha256_hashes_the_sorted_keys_whatever_the_row_order():
    inputs, cfg = pp.load_inputs(_paths())
    hits, stats, _ = pp._anchored_hits([], inputs, cfg)
    rows = pp._anchored_rows(hits, inputs.entities)

    flow = pp._anchored_flow(stats, rows[::-1])

    assert len(rows) == flow["unique_keys"] == 6
    assert flow["key_set_sha256"] == _key_set_sha256(rows)
