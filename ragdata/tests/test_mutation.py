"""Mutation tests for audit G58: the old gates went green after data was deleted.

Each mutation is applied to the mini snapshot, written to a fresh store, gated
end to end with the gates built so far, and must turn the named hard gates red.
(The full run also lists the gates not built yet, which are red by
construction; leaving them out here shows what the built gates catch.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mini_build
from ragdata.gates import runner

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


def _drop(type_name, pk_field, key):
    def mutate(layer):
        layer[type_name] = [r for r in layer[type_name] if r[pk_field] != key]
    return mutate


def _set(type_name, pk_field, key, **changes):
    def mutate(layer):
        next(r for r in layer[type_name] if r[pk_field] == key).update(changes)
    return mutate


def _empty_all(layer):
    for name in layer:
        layer[name] = []


def _remove_file(name):
    def mutate(layer):
        del layer[name]
    return mutate


def _duplicate_first(type_name):
    def mutate(layer):
        layer[type_name].append(dict(layer[type_name][0]))
    return mutate


def _edit_text(layer):
    unit = next(r for r in layer["verse_units"] if r["unit_key"] == "act.9.1")
    unit["text"] = unit["text_pdf"] = unit["text"].replace("掃羅", "大衛")


TEXT_MUTATIONS = {
    "delete a unit": (_drop("verse_units", "unit_key", "act.9.2"), {"G-COUNT", "G-REFINT"}),
    "redirect a slot to another unit": (
        _set("verse_slots", "slot_key", "eph.6.3", unit_key="eph.6.3-4"), {"G-REFINT"}),
    "point a slot at a unit that cannot hold it": (
        _set("verse_slots", "slot_key", "act.9.1", unit_key="act.9.2"), {"G-SCHEMA"}),
    "delete a slot": (_drop("verse_slots", "slot_key", "eph.6.3"), {"G-COUNT", "G-REFINT"}),
    "delete a footnote": (_drop("footnotes", "fn_id", "fn:eph.6.1#1"), {"G-COUNT"}),
    "delete the variant footnote": (
        _drop("footnotes", "fn_id", "fn:mat.18.2#1"), {"G-COUNT", "G-REFINT"}),
    "delete a heading": (_drop("headings", "heading_id", "hd:psa.42.1#1"), {"G-COUNT"}),
    "delete an underline span": (_drop("name_spans", "span_id", "ns:act.10.1@1"), {"G-COUNT"}),
    "delete the superscription": (
        _drop("chapter_texts", "id", "sp:psa.42"), {"G-COUNT", "G-REFINT"}),
    "delete an errata row": (_drop("errata_applied", "errata_id", "er:0001"), {"G-REFINT"}),
    "treat a section_range as parallel": (
        _set("parallel_refs", "pr_id", "pr:hd:act.9.1#1#1", kind="parallel"), {"G-COUNT"}),
    "edit verse text, keep its sha": (_edit_text, {"G-SCHEMA"}),
    "duplicate a unit": (_duplicate_first("verse_units"), {"G-SCHEMA"}),
    "drop the footnotes file": (_remove_file("footnotes"), {"G-SCHEMA", "G-COUNT"}),
    "empty every file": (_empty_all, {"G-COUNT"}),
}

STRUCT_MUTATIONS = {
    "delete a passage": (_drop("passages", "passage_id", "ps:act.10.1"), {"G-COUNT", "G-REFINT"}),
    "delete a pericope": (_drop("pericopes", "pericope_id", "pc:act.9.1"), {"G-COUNT", "G-REFINT"}),
    "break the next chain": (
        _set("pericopes", "pericope_id", "pc:act.9.3b", prev_id=None), {"G-REFINT"}),
    "empty every file": (_empty_all, {"G-COUNT"}),
}


def _red(report) -> set[str]:
    return {g.name for g in report.gates if g.hard and not g.passed}


def _gate(path, layer, deps=()):
    return runner.gate_layer(path, layer, deps, MINI_COUNTS,
                             gates=runner.implemented_gates(layer))


def test_unmutated_mini_layers_are_green(tmp_path):
    text, struct = mini_build.write_layers(tmp_path)
    assert _red(_gate(text.path, "text")) == set()
    assert _red(_gate(struct.path, "struct", [text.path])) == set()


@pytest.mark.parametrize("case", sorted(TEXT_MUTATIONS))
def test_text_mutation_turns_hard_gates_red(tmp_path, case):
    mutate, expected_red = TEXT_MUTATIONS[case]
    layer = mini_build.text_layer()
    mutate(layer)
    text, _ = mini_build.write_layers(tmp_path, text=layer)
    assert expected_red <= _red(_gate(text.path, "text"))


@pytest.mark.parametrize("case", sorted(STRUCT_MUTATIONS))
def test_struct_mutation_turns_hard_gates_red(tmp_path, case):
    mutate, expected_red = STRUCT_MUTATIONS[case]
    layer = mini_build.struct_layer()
    mutate(layer)
    text, struct = mini_build.write_layers(tmp_path, struct=layer)
    assert expected_red <= _red(_gate(struct.path, "struct", [text.path]))
