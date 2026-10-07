"""G-MUT for L0/L1 (design §8): each of the nine mutation classes turns a hard gate red.

Every class is injected where it can happen: into a layer (gated by the runner with the
gates that read only records) and/or into the loaded projection (gated by S14). Each
injection must turn at least the named hard gate red.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import mini_build
import mini_loaded
import mini_release
from ragdata import store
from ragdata.gates import runner
from ragdata.stages.s05_struct.tokens import TokenCounter

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")
MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
COUNTER = TokenCounter(mini_build.count_tokens, {})


def _red(report) -> set[str]:
    return {g.name for g in report.gates if g.hard and not g.passed}


def _inputs(loaded) -> runner.GateInputs:
    return runner.GateInputs(versification=mini_build.versification(), token_counter=COUNTER,
                             legacy_registry=loaded.mini.root / "event_registry.json")


# ------------------------------------------------------------ layer injections


def _text(loaded, mutate, layer="text"):
    rows = mini_build.text_layer()
    mutate(rows)
    text, struct = mini_build.write_layers(loaded.contracts.parent / "mutated", text=rows)
    target, deps = (text, []) if layer == "text" else (struct, [text.path])
    return _red(runner.gate_layer(target.path, layer, deps, MINI_COUNTS,
                                  gates=runner.record_gates(layer), inputs=_inputs(loaded)))


def _layer(loaded, name, file_name, mutate, gates):
    """A copy of the release's ``name`` layer with ``file_name``'s rows mutated, gated."""
    built = store.read_layer(loaded.mini.layers[name].path)
    rows = [json.loads(json.dumps(r)) for r in built.rows[file_name]]
    mutate(rows)
    files = {n: (built.path / n).read_bytes() for n in built.file_shas if n != store.DEPENDS_ON}
    files[file_name] = store.encode_jsonl(rows)
    copy = store.write_layer(loaded.contracts.parent / "mutated", name, files,
                             depends_on=built.depends_on)
    deps = [loaded.mini.layers[d].path for d in built.depends_on]
    return _red(runner.gate_layer(copy.path, name, deps, MINI_COUNTS, gates=gates,
                                  inputs=_inputs(loaded)))


def _drop(type_name, field, key):
    def mutate(rows):
        layer = rows if isinstance(rows, list) else rows[type_name]
        layer.remove(next(r for r in layer if r[field] == key))
    return mutate


def _set(type_name, field, key, **changes):
    return lambda rows: next(r for r in rows[type_name] if r[field] == key).update(changes)


def _fragment_heading(rows):
    heading = next(h for h in rows["headings"] if h["heading_id"] == "hd:eph.6.1#1")
    rows["headings"].append({**heading, "heading_id": "hd:eph.6.4#1", "anchor_unit_key": "eph.6.4",
                             "text_pdf": "不要惹兒女的氣", "text": "不要惹兒女的氣",
                             "display_title": "不要惹兒女的氣",
                             "prov": {"style_class": "body", "glyph_range": [5, 11]}})


def _anchor_off_the_page(rows):
    anchor = rows[0]["anchors"][0]
    anchor.update(end_key="psa.42.9", end_slot="psa.42.9")


def _term_without_provenance(rows):
    term = {k: v for k, v in rows[0].items() if k not in ("provenance_class", "source", "note")}
    rows.append({**term, "term_key": "persons/0099", "position": 99, "term": "無名"})


# ------------------------------------------------------------ projection injections


def _projected(loaded, mutate):
    mutate(loaded)
    return mini_loaded.red(loaded.verify())


def _pg(table, field, key, drop=False, **changes):
    def mutate(loaded):
        rows = loaded.pg.schemas[loaded.targets.schema][table]
        row = next(r for r in rows if r[field] == key)
        rows.remove(row) if drop else row.update(changes)
    return mutate


def _payload(record_id, **changes):
    def mutate(loaded):
        name = loaded.targets.collection
        point = next(p for p in loaded.qdrant.points(name) if p.payload["record_id"] == record_id)
        loaded.qdrant._client.set_payload(name, payload=changes, points=[point.id], wait=True)
    return mutate


def _contract(name, change):
    def mutate(loaded):
        path = loaded.targets.contracts_dir / name
        doc = json.loads(path.read_bytes())
        change(doc)
        os.chmod(path, 0o644)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return mutate


def _registry_anchor(doc):
    doc["events"][0]["anchors"][0]["end_slot"] = "psa.42.9"


def _lexicon_term(doc):
    doc["persons"].append({"name": "無名", "aliases": ["無名"]})


OTHER_BUILD = "b20000101_00000000"
CLASSES = {
    "delete a verse": [
        (lambda l: _text(l, _drop("verse_units", "unit_key", "eph.6.4"), "struct"), "G-STRUCT"),
        (lambda l: _projected(l, _pg("verse_units", "unit_key", "eph.6.4", drop=True)),
         "G-PROJ.C2")],
    "delete a heading": [
        (lambda l: _text(l, _drop("headings", "heading_id", "hd:psa.42.1#1")), "G-COUNT"),
        (lambda l: _projected(l, _pg("headings", "heading_id", "hd:psa.42.1#1", drop=True)),
         "G-PROJ.C2")],
    "delete an underline": [
        (lambda l: _text(l, _drop("name_spans", "span_id", "ns:act.10.1@1")), "G-COUNT")],
    "mark a verse fragment as a heading (style mismatch)": [
        (lambda l: _text(l, _fragment_heading, "struct"), "G-STRUCT")],
    "change a payload field": [
        (lambda l: _projected(l, _payload("vs:act.10.1", chapter_num=11)), "G-PROJ.C3")],
    "change a build_id": [
        (lambda l: _projected(l, _payload("vs:act.10.1", build_id=OTHER_BUILD)), "G-PROJ.C1"),
        (lambda l: _projected(l, _pg("build_info", "build_id", l.release.build_id,
                                     build_id=OTHER_BUILD)), "G-PROJ.C1")],
    "treat a section_range as parallel": [
        (lambda l: _text(l, _set("parallel_refs", "pr_id", "pr:hd:act.9.1#1#1", kind="parallel")),
         "G-COUNT"),
        (lambda l: _projected(l, _pg("parallel_refs", "pr_id", "pr:hd:act.9.1#1#1",
                                     kind="parallel")), "G-PROJ.C3")],
    "move an event anchor to a slot that does not exist": [
        (lambda l: _layer(l, "events", "events.jsonl", _anchor_off_the_page,
                          ("G-SCHEMA", "G-REFINT", "G-EVENT")), "G-REFINT"),
        (lambda l: _projected(l, _contract("event_registry.json", _registry_anchor)),
         "G-PROJ.C5")],
    "add a routing term without provenance": [
        (lambda l: _layer(l, "route", "routing_terms.jsonl", _term_without_provenance,
                          ("G-SCHEMA", "G-PROV")), "G-PROV"),
        (lambda l: _projected(l, _contract("routing_lexicon.json", _lexicon_term)),
         "G-PROJ.C5")],
}


def test_the_table_has_the_nine_l0_l1_classes():
    assert len(CLASSES) == 9


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("gmut"))


@pytest.mark.parametrize("case", [(c, i) for c, levels in CLASSES.items()
                                  for i in range(len(levels))], ids=lambda c: f"{c[0]}#{c[1]}")
def test_each_mutation_turns_a_hard_gate_red(tmp_path, mini, case):
    name, i = case
    inject, gate = CLASSES[name][i]
    loaded = mini_loaded.load(tmp_path, mini)
    assert mini_loaded.red(loaded.verify()) == set()
    assert gate in inject(loaded)
