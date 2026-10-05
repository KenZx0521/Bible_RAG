"""biblical_relations.yaml says which relations carry their direction in their name.

REL-03 groundwork: an llm row of a directed relation whose head and tail share a
type (LOCATED_IN, …) arrives with its ends in id order, so 6.05 marks it
direction-unverified and H11 counts the ones left unmarked. Kinship and teacher
rows are different: choosing FATHER_OF over SON_OF is how the classifier states
the direction. That exemption used to be read off `inverse`, which only R5
reads and which C6a nulls for every gendered relation; read that way, every llm
kinship edge would be flagged. `direction_pairs` is a table of its own, and
id_order_relations() is derived from it and the domain/range alone.

REL-02 (C6a): `inverse` is read only by R5, which extract_relations runs only
with --inverse. A gendered relation has no single reverse (FATHER_OF(x, y)
reads back as SON_OF or DAUGHTER_OF depending on y), and R5 wrote SON_OF for
daughters and FATHER_OF for mothers, so only the two gender-neutral pairs keep
an inverse.

REL-03 (C6c): PRECEDED_BY(X, Y) reads "X is preceded by Y", so Y is the earlier
event. The description and the example said the opposite (X before Y, head
創世, tail 洪水). No code reads either field (the classifier prompt lists only
relation names), so this is the documentation half of REL-03.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from relation_extraction import extract_relations
from relation_extraction.models import ExtractedRelation, ExtractionPhase
from relation_extraction.schema_loader import RelationSchema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "config" / "relations" / "biblical_relations.yaml"

DIRECTION_PAIRS = (
    ("FATHER_OF", "SON_OF"), ("FATHER_OF", "DAUGHTER_OF"),
    ("MOTHER_OF", "SON_OF"), ("MOTHER_OF", "DAUGHTER_OF"),
    ("ANCESTOR_OF", "DESCENDANT_OF"), ("TEACHER_OF", "DISCIPLE_OF"),
)
ID_ORDER = {"CAUSED", "LOCATED_IN", "PRECEDED_BY", "SUCCEEDED_BY"}
GENDERED = {"FATHER_OF", "MOTHER_OF", "SON_OF", "DAUGHTER_OF"}
# the only inverses R5 may write: each reads the same tie from the other end whatever the sexes
INVERSES = {"ANCESTOR_OF": "DESCENDANT_OF", "DESCENDANT_OF": "ANCESTOR_OF",
            "TEACHER_OF": "DISCIPLE_OF", "DISCIPLE_OF": "TEACHER_OF"}

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


def test_declared_inverses_are_gender_neutral_and_mirrored(schema):
    declared = {e.name: e.inverse for e in schema.iter_entries() if e.inverse}
    assert declared == INVERSES
    assert not GENDERED & (set(declared) | set(declared.values()))
    for name, inverse in declared.items():
        assert schema.inverse_of(inverse) == name
        # a direction pair is checked on load to be two directed relations with mirrored domain/range
        assert (name, inverse) in schema.direction_pairs or (inverse, name) in schema.direction_pairs


def test_id_order_relations_unchanged_after_inverse_nulling(schema):
    # the four gendered relations now lack an inverse, like the id-order ones: read off
    # `inverse` they would be id-order (82 llm rows flagged); read off direction_pairs they are not
    same_type_without_inverse = {
        e.name for e in schema.iter_entries()
        if e.direction == "directed" and not e.inverse and set(e.domain_types) == set(e.range_types)}
    assert same_type_without_inverse == ID_ORDER | GENDERED
    assert schema.id_order_relations() == ID_ORDER


def _triple(head: str, relation: str, tail: str, confidence: float) -> ExtractedRelation:
    return ExtractedRelation(head_id=head, tail_id=tail, relation=relation, confidence=confidence,
                             evidence_span="", source_pericope_id="gen:5:1",
                             extraction_phase=ExtractionPhase.GROUNDED_LLM)


def test_r5_is_off_by_default(monkeypatch, schema):
    assert extract_relations._parse_args([]).inverse is False
    assert extract_relations._parse_args(["--inverse"]).inverse is True
    with pytest.raises(SystemExit):
        extract_relations._parse_args(["--no-inverse"])

    calls, materialize = [], extract_relations.materialize_inverses

    def spy(triples, schema_):
        calls.append(len(triples))
        return materialize(triples, schema_)

    monkeypatch.setattr(extract_relations, "materialize_inverses", spy)
    triples = [_triple("person:a", "FATHER_OF", "person:b", 0.7),
               _triple("person:a", "FATHER_OF", "person:b", 0.8),
               _triple("person:c", "ANCESTOR_OF", "person:d", 0.7)]
    kept = extract_relations._finalize_triples(triples, schema, inverse=False)
    assert calls == []
    assert [(t.relation, t.confidence) for t in kept] == [("FATHER_OF", 0.8), ("ANCESTOR_OF", 0.7)]

    # opt in: R5 runs once over every row; FATHER_OF has no inverse left, ANCESTOR_OF does
    kept = extract_relations._finalize_triples(triples, schema, inverse=True)
    assert calls == [3] and len(triples) == 3
    derived = [(t.head_id, t.relation, t.tail_id) for t in kept
               if t.extraction_phase == ExtractionPhase.INVERSE_DERIVED]
    assert derived == [("person:d", "DESCENDANT_OF", "person:c")]


def test_preceded_by_description_and_example_agree_with_the_name(schema):
    entry = schema.get("PRECEDED_BY")
    assert entry.description_zh == "事件 X 之前先發生了事件 Y（Y 早於 X）"
    assert entry.examples == [{"head": "洪水", "tail": "創世", "sentence": "創世之後不久便有洪水"}]
    # the example's sentence names the tail first, then 之後, then the head: the tail is earlier
    (example,) = entry.examples
    sentence = example["sentence"]
    assert sentence.index(example["tail"]) < sentence.index("之後") < sentence.index(example["head"])
