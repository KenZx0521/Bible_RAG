"""biblical_relations.yaml says which relations carry their direction in their name.

REL-03 groundwork: an llm row of a directed relation whose head and tail share a
type (LOCATED_IN, …) arrives with its ends in id order, so 6.05 marks it
direction-unverified and H11 counts the ones left unmarked. Kinship and teacher
rows are different: choosing FATHER_OF over SON_OF is how the classifier states
the direction. That exemption used to be read off `inverse`, which only R5
reads and which C6a nulls for every gendered relation; read that way, every llm
kinship edge would be flagged. `direction_pairs` is a table of its own, and
id_order_relations() is derived from it and the domain/range alone.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from relation_extraction.schema_loader import RelationSchema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "config" / "relations" / "biblical_relations.yaml"

DIRECTION_PAIRS = (
    ("FATHER_OF", "SON_OF"), ("FATHER_OF", "DAUGHTER_OF"),
    ("MOTHER_OF", "SON_OF"), ("MOTHER_OF", "DAUGHTER_OF"),
    ("ANCESTOR_OF", "DESCENDANT_OF"), ("TEACHER_OF", "DISCIPLE_OF"),
)
ID_ORDER = {"CAUSED", "LOCATED_IN", "PRECEDED_BY", "SUCCEEDED_BY"}

# each table breaks exactly one rule; SIBLING_OF is undirected, BORN_IN is
# Person→Place and LOCATED_IN Place→Place, so they do not mirror
BAD_PAIRS = {
    "unknown_relation": [["FATHER_OF", "NOT_A_RELATION"]],
    "undirected_member": [["FATHER_OF", "SIBLING_OF"]],
    "not_mirrored": [["BORN_IN", "LOCATED_IN"]],
    "same_relation_twice": [["LOCATED_IN", "LOCATED_IN"]],
    "one_member": [["FATHER_OF"]],
    "not_a_list": {"FATHER_OF": "SON_OF"},
}


@pytest.fixture(scope="module")
def schema():
    return RelationSchema.load(SCHEMA_PATH)


def test_id_order_relations_are_the_four_unpaired_same_type_relations(schema):
    assert schema.id_order_relations() == ID_ORDER
    paired = {name for pair in DIRECTION_PAIRS for name in pair}
    assert {n for n in schema.all_names() if schema.is_direction_paired(n)} == paired
    assert not schema.is_direction_paired("NOT_A_RELATION")
    # decoupled from R5: with every inverse nulled the answer is the same
    no_inverse = RelationSchema(
        {e.name: dataclasses.replace(e, inverse=None) for e in schema.iter_entries()},
        version=schema.version, direction_pairs=schema.direction_pairs)
    assert no_inverse.id_order_relations() == ID_ORDER


def test_direction_pairs_reference_mirrored_directed_relations(schema):
    assert schema.direction_pairs == DIRECTION_PAIRS
    for one_end, other_end in schema.direction_pairs:
        a, b = schema.get(one_end), schema.get(other_end)
        assert a.direction == b.direction == "directed"
        assert set(a.domain_types) == set(b.range_types)
        assert set(a.range_types) == set(b.domain_types)


@pytest.mark.parametrize("case", sorted(BAD_PAIRS))
def test_malformed_direction_pairs_fail_to_load(tmp_path, case):
    data = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    data["direction_pairs"] = BAD_PAIRS[case]
    path = tmp_path / "biblical_relations.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="direction_pairs"):
        RelationSchema.load(path)
