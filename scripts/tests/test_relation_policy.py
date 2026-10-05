"""relation_policy: which relation row Step 6.05 prefers (source rank, source, parent/child).

Moved from test_relation_postprocess.py to keep that file under 800 lines:
the policy itself (1A-C4i) and its functions called directly on hand-made
rows (1A-C4j); the rules that use the policy are tested there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from relation_extraction import relation_policy as policy
from relation_extraction.relation_policy import SOURCE_RANK, parent_child, rank, source_of
from relation_extraction.schema_loader import RelationSchema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = RelationSchema.load(ROOT / "config" / "relations" / "biblical_relations.yaml")


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


def _ranked(head: str, relation: str, tail: str, source: str, pid: str = "", verse: int | None = None) -> dict:
    return {"head_id": head, "relation": relation, "tail_id": tail, "source": source,
            "source_pericope_id": pid, **({} if verse is None else {"verse": verse})}


def _canon(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def test_resolve_kinship_direction_breaks_ties_explicitly():
    # equal ranks fall to the smallest (source_pericope_id, verse, head_id); the kept rows
    # stay in input order, a non-parent row (SPOUSE_OF) passes untouched
    given = [_ranked("person:a", "FATHER_OF", "person:b", "llm", "gen:2:0"),
             _ranked("person:b", "FATHER_OF", "person:a", "llm", "gen:1:0"),
             _ranked("person:c", "SON_OF", "person:d", "anchored_rule", "1ch:1:0", 5),
             _ranked("person:d", "SON_OF", "person:c", "anchored_rule", "1ch:1:0", 3),
             _ranked("person:f", "MOTHER_OF", "person:e", "llm", "gen:3:0"),
             _ranked("person:e", "MOTHER_OF", "person:f", "llm", "gen:3:0"),
             _ranked("person:g", "DAUGHTER_OF", "person:h", "prior"),
             _ranked("person:g", "FATHER_OF", "person:h", "curated"),
             _ranked("person:g", "SPOUSE_OF", "person:h", "llm", "gen:3:0")]
    kept, conflicts = policy.resolve_kinship_direction(given)
    assert kept == [given[1], given[3], given[5], given[7], given[8]]
    assert [(c["head_id"], c["relation"], c["tail_id"], c["kept"]["head_id"]) for c in conflicts] == [
        ("person:a", "FATHER_OF", "person:b", "person:b"), ("person:c", "SON_OF", "person:d", "person:d"),
        ("person:f", "MOTHER_OF", "person:e", "person:e"), ("person:g", "DAUGHTER_OF", "person:h", "person:g")]


def test_dedup_undirected_keeps_one_row_per_pair():
    # a key the llm and the anchored rule both give (密迦 SPOUSE_OF 拿鶴) keeps one row too;
    # directed rows are not this rule's, a pair in both orientations included
    given = [_ranked("person:mijia", "SPOUSE_OF", "person:nahe", "anchored_rule", "gen:11:2", 29),
             _ranked("person:mijia", "SPOUSE_OF", "person:nahe", "llm", "gen:11:2"),
             _ranked("person:a", "FATHER_OF", "person:b", "llm", "gen:1:0"),
             _ranked("person:b", "FATHER_OF", "person:a", "llm", "gen:1:0")]
    kept, dropped = policy.dedup_undirected(given, SCHEMA)
    assert (kept, dropped) == (given[1:], given[:1])


def test_choices_are_those_of_the_row_set():
    # each function's choice and conflict list are those of the row set, in any input order
    given = [_ranked("person:a", "FATHER_OF", "person:b", "llm", "gen:1:0"),
             _ranked("person:a", "SON_OF", "person:b", "llm", "gen:1:0"),
             _ranked("person:b", "FATHER_OF", "person:a", "llm", "gen:1:0"),
             _ranked("person:c", "SPOUSE_OF", "person:d", "llm", "gen:1:0"),
             _ranked("person:d", "SPOUSE_OF", "person:c", "llm", "gen:1:0")]
    results = []
    for shift in range(len(given)):
        rotated = given[shift:] + given[:shift]
        kept, conflicts = policy.resolve_kinship_direction(rotated)
        deduped, dropped = policy.dedup_undirected(rotated, SCHEMA)
        results.append((sorted(map(_canon, kept)), conflicts, sorted(map(_canon, deduped)), dropped))
    assert all(result == results[0] for result in results)
    # head_id, then relation, decides a full tie: 甲 FATHER_OF 乙 stands, so 甲 SON_OF 乙 goes
    assert [(c["head_id"], c["relation"]) for c in results[0][1]] == [("person:a", "SON_OF"),
                                                                      ("person:b", "FATHER_OF")]
    assert results[0][3] == [given[4]]
