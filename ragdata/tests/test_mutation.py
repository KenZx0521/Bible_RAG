"""Mutation tests for audit G58: the old gates went green after data was deleted.

Each mutation is applied to the mini snapshot, written to a fresh store, gated
end to end with the gates built so far, and must turn the named hard gates red.
(G-CONSERVE and G-XCHECK re-read the PDFs and are exercised by the build tests.
Leaving them out here shows what the record gates catch. G-STRUCT counts tokens with
the mini stand-in counter.)
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import fake_encoder
import mini_build
import mini_emb
from ragcommon import ids
from ragdata import store
from ragdata.gates import runner
from ragdata.store import attach
from ragdata.stages.s05_struct.tokens import TokenCounter

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
MINI_COUNTER = TokenCounter(mini_build.count_tokens, {})


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


def _edit_serving_text(layer):
    unit = next(r for r in layer["verse_units"] if r["unit_key"] == "act.9.3")
    unit["text"] = unit["text"].replace("小河", "大河")
    unit["text_sha256"] = mini_build.sha(unit["text"])


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
    "change serving text outside errata": (_edit_serving_text, {"G-TEXT"}),
    "redirect a ref alias": (
        _set("ref_aliases", "external_ref", "mat.18.5", target="mat.18.2"), {"G-REF"}),
}

def _edit_content(layer):
    passage = next(r for r in layer["passages"] if r["passage_id"] == "ps:eph.6.1")
    passage["content"] = passage["content"].replace("父母", "長輩")
    passage["content_sha"] = mini_build.sha(passage["content"])


def _drop_last_piece(layer):
    passage = next(r for r in layer["passages"] if r["passage_id"] == "ps:mat.18.1")
    passage.update(unit_refs=passage["unit_refs"][:2], end_key="mat.18.2", end_slot="mat.18.2",
                   verse_range="1-2")


STRUCT_MUTATIONS = {
    "delete a passage": (_drop("passages", "passage_id", "ps:act.10.1"),
                         {"G-COUNT", "G-REFINT", "G-STRUCT"}),
    "delete a pericope": (_drop("pericopes", "pericope_id", "pc:act.9.1"),
                          {"G-COUNT", "G-REFINT", "G-STRUCT"}),
    "break the next chain": (
        _set("pericopes", "pericope_id", "pc:act.9.3b", prev_id=None), {"G-REFINT", "G-STRUCT"}),
    "empty every file": (_empty_all, {"G-COUNT", "G-STRUCT"}),
    "edit passage content, keep its sha": (_edit_content, {"G-STRUCT"}),
    "drop a verse from a passage": (_drop_last_piece, {"G-STRUCT"}),
    "change a payload field (token count)": (
        _set("chunks", "chunk_id", "ck:act.9.1~act.9.2", token_count=700), {"G-STRUCT"}),
    "drop the verse index row of a cut unit": (
        _drop("verse_index", "unit_key", "act.9.3"), {"G-STRUCT"}),
    "point a legacy id at a missing passage": (
        _set("legacy_ids", "legacy_id", "sng:1:0", new_ids=["ps:sng.1.2"]), {"G-REFINT"}),
}

# text mutations of design §8 G-MUT (L0/L1) that the struct layer built on them must catch
TEXT_UNDER_STRUCT = {
    "delete a heading": (_drop("headings", "heading_id", "hd:eph.6.1#1"), {"G-REFINT", "G-STRUCT"}),
    "mark a verse fragment as a heading": (
        lambda layer: layer["headings"].append({
            **next(h for h in layer["headings"] if h["heading_id"] == "hd:eph.6.1#1"),
            "heading_id": "hd:eph.6.4#1", "anchor_unit_key": "eph.6.4", "text_pdf": "不要惹兒女的氣",
            "text": "不要惹兒女的氣", "display_title": "不要惹兒女的氣",
            "prov": {"style_class": "body", "glyph_range": [5, 11]}}), {"G-STRUCT"}),
    "delete a verse": (_drop("verse_units", "unit_key", "eph.6.4"), {"G-REFINT", "G-STRUCT"}),
}


def _red(report) -> set[str]:
    return {g.name for g in report.gates if g.hard and not g.passed}


def _gate(path, layer, deps=()):
    return runner.gate_layer(path, layer, deps, MINI_COUNTS, gates=runner.record_gates(layer),
                             inputs=runner.GateInputs(versification=mini_build.versification(),
                                                      token_counter=MINI_COUNTER))


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


@pytest.mark.parametrize("case", sorted(TEXT_UNDER_STRUCT))
def test_text_mutation_turns_the_struct_gates_red(tmp_path, case):
    mutate, expected_red = TEXT_UNDER_STRUCT[case]
    layer = mini_build.text_layer()
    mutate(layer)
    text, struct = mini_build.write_layers(tmp_path, text=layer)
    assert expected_red <= _red(_gate(struct.path, "struct", [text.path]))


def _embed_omitted_slot(layer):
    row = copy.deepcopy(next(r for r in layer["embedding_records"]
                             if r["record_id"] == "vs:mat.18.2"))
    row.update(record_id="vs:mat.18.3", source_id="mat.18.3",
               point_id=ids.point_id("vs:mat.18.3"))
    row["payload"].update(record_id="vs:mat.18.3", verse_range="3", start_key="mat.18.3",
                          end_key="mat.18.3")
    layer["embedding_records"].insert(6, row)


def _edit_record_text(layer):
    row = next(r for r in layer["embedding_records"] if r["record_id"] == "vs:eph.6.4")
    row["text"] = row["text"].replace("父親", "母親")


EMB_MUTATIONS = {
    "change a payload field": (
        _set("embedding_records", "record_id", "vs:act.10.1", payload={
            **mini_build.EMB_PAYLOADS["ps:act.10.1"], "record_id": "vs:act.10.1",
            "kind": "verse", "type": "verse"}), {"G-SCHEMA", "G-EMB"}),
    "change the payload title": (lambda layer: next(
        r for r in layer["embedding_records"] if r["record_id"] == "vs:act.10.1"
    )["payload"].update(title="(無標題)"), {"G-EMB"}),
    "delete a verse record": (_drop("embedding_records", "record_id", "vs:psa.42.3"),
                              {"G-COUNT", "G-EMB"}),
    "embed an omitted slot": (_embed_omitted_slot, {"G-COUNT", "G-EMB"}),
    "edit record text, keep its sha": (_edit_record_text, {"G-SCHEMA"}),
}


def _write_emb(tmp_path, emb, mutate):
    built = store.read_layer(emb.path)
    layer = {"embedding_records": [dict(r) for r in built.rows["embedding_records.jsonl"]]}
    mutate(layer)
    files = {name: (emb.path / name).read_bytes() for name in built.file_shas
             if name != store.DEPENDS_ON}
    files["embedding_records.jsonl"] = store.encode_jsonl(layer["embedding_records"])
    mutated = store.write_layer(tmp_path / "mutated", "emb", files, depends_on=built.depends_on)
    _, vector_files = attach.read_attachment(emb.path, "vectors")
    attach.write_attachment(mutated, "vectors", vector_files, {})
    return mutated


@pytest.mark.parametrize("case", sorted(EMB_MUTATIONS))
def test_emb_mutation_turns_hard_gates_red(tmp_path, case):
    mutate, expected_red = EMB_MUTATIONS[case]
    text, struct, result = mini_emb.build(tmp_path)
    mutated = _write_emb(tmp_path, result.layers["emb"], mutate)
    inputs = runner.GateInputs(encoder=fake_encoder.make(), compat_sample=mini_emb.SAMPLE,
                               legacy_dir=mini_emb.legacy_dir(tmp_path / "old"))
    report = runner.gate_layer(mutated.path, "emb", [struct.path, text.path], MINI_COUNTS,
                               inputs=inputs)
    assert expected_red <= _red(report)
