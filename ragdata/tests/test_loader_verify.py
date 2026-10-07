"""S14: G-PROJ turns red when the projection drifts from the release in any checked way.

Each case names the reason its gate must give, so one check of a gate cannot hide another.
"""

from __future__ import annotations

import json
import os
import uuid

import numpy as np
import pytest
from qdrant_client import models

import fake_encoder
import mini_loaded
import mini_release
from ragcommon import ids
from ragdata.loader.plan import Point
from ragdata.loader import verify as verifier

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("verify_mini"))


@pytest.fixture()
def loaded(tmp_path, mini):
    return mini_loaded.load(tmp_path, mini)


def _rows(loaded, table):
    return loaded.pg.schemas[loaded.targets.schema][table]


def _row(loaded, table, field, key):
    return next(r for r in _rows(loaded, table) if r[field] == key)


def _set_payload(loaded, record_id, **changes):
    client, name = loaded.qdrant._client, loaded.targets.collection
    point = next(p for p in loaded.qdrant.points(name) if p.payload["record_id"] == record_id)
    client.set_payload(name, payload=changes, points=[point.id], wait=True)


def _set_vector(loaded, record_id, vector):
    name = loaded.targets.collection
    point = next(p for p in loaded.qdrant.points(name) if p.payload["record_id"] == record_id)
    loaded.qdrant.upsert(name, [Point(point.id, vector, point.payload)])


def _rewrite_contract(loaded, name, change):
    path = loaded.targets.contracts_dir / name
    doc = json.loads(path.read_bytes())
    change(doc)
    os.chmod(path, 0o644)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _drop_row(table, field, key):
    def mutate(loaded):
        rows = _rows(loaded, table)
        rows.remove(_row(loaded, table, field, key))
    return mutate


def _edit_row(table, field, key, **changes):
    return lambda loaded: _row(loaded, table, field, key).update(changes)


def _move_anchor(doc):
    doc["events"][0]["anchors"][0]["end_slot"] = "psa.42.9"


def _unsourced_term(doc):
    doc["persons"].append({"name": "無名", "aliases": ["無名"]})


def _reformat_contract(name):
    """Other bytes, the same JSON: only the per-file sha256 can tell."""
    def mutate(loaded):
        path = loaded.targets.contracts_dir / name
        raw = path.read_bytes()
        os.chmod(path, 0o644)
        path.write_text(json.dumps(json.loads(raw), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        assert path.read_bytes() != raw
    return mutate


def _drop_points(passage_id):
    """The passage and chunk points of ``passage_id`` (PG and the contracts untouched)."""
    def mutate(loaded):
        name = loaded.targets.collection
        gone = [p.id for p in loaded.qdrant.points(name)
                if p.payload["kind"] in ("passage", "chunk")
                and p.payload.get("passage_id") == passage_id]
        assert gone
        loaded.qdrant._client.delete(name, points_selector=models.PointIdsList(points=gone),
                                     wait=True)
    return mutate


def _rekey_point(record_id):
    """The record's point stored again under a random id instead of uuid5(record_id)."""
    def mutate(loaded):
        name = loaded.targets.collection
        point = next(p for p in loaded.qdrant.points(name) if p.payload["record_id"] == record_id)
        loaded.qdrant._client.delete(name, points_selector=models.PointIdsList(
            points=[point.id]), wait=True)
        loaded.qdrant.upsert(name, [Point(str(uuid.uuid4()), point.vector, point.payload)])
    return mutate


def _drop_unique(loaded):
    constraints = loaded.pg.constraint_sets[loaded.targets.schema]
    constraints.discard(("embedding_records", "uq_embedding_records_point_id", "u"))


def _builds_row(**changes):
    return lambda loaded: loaded.pg.builds[loaded.release.build_id].update(changes)


OTHER = "b20000101_00000000"
MUTATIONS = {
    "build_info names another build": (
        lambda l: _rows(l, "build_info")[0].update(build_id=OTHER), "G-PROJ.C1",
        f"build_info holds ['{OTHER}']"),
    "rag_meta.builds names another release file": (
        _builds_row(manifest_sha="0" * 64), "G-PROJ.C1", "rag_meta.builds manifest_sha"),
    "rag_meta.builds names another collection": (
        _builds_row(qdrant_collection="passages__other"), "G-PROJ.C1",
        "rag_meta.builds qdrant_collection"),
    "a point names another build": (
        lambda l: _set_payload(l, "vs:eph.6.4", build_id=OTHER), "G-PROJ.C1",
        "payload build_id of vs:eph.6.4"),
    "the contract manifest names another build": (lambda l: _rewrite_contract(
        l, "manifest.json", lambda d: d.update(build_id=OTHER)), "G-PROJ.C1",
        f"contracts manifest.json names '{OTHER}'"),
    "a verse is missing in PG": (_drop_row("verse_units", "unit_key", "eph.6.4"), "G-PROJ.C2",
                                 "verse_units: missing eph.6.4"),
    "an event anchor is missing in PG": (
        _drop_row("event_anchors", "passage_id", "ps:act.9.3b"), "G-PROJ.C2",
        "event_anchors: missing ev0003|1"),
    "a point is missing": (lambda l: l.qdrant._client.delete(
        l.targets.collection, points_selector=models.PointIdsList(points=[
            ids.point_id("vs:eph.6.4")]), wait=True), "G-PROJ.C2", "qdrant: missing vs:eph.6.4"),
    "a point is stored under a random id": (
        _rekey_point("vs:eph.6.4"), "G-PROJ.C2", "is not uuid5 of vs:eph.6.4"),
    "a PG field differs": (_edit_row("headings", "heading_id", "hd:psa.42.1#1", text="改了"),
                           "G-PROJ.C3", "headings hd:psa.42.1#1: differs in ['text']"),
    "a jsonb field differs": (_edit_row("passages", "passage_id", "ps:eph.6.1", unit_refs=[]),
                              "G-PROJ.C3", "passages ps:eph.6.1: differs in ['unit_refs']"),
    "a payload field differs": (lambda l: _set_payload(l, "vs:act.9.3", title="(無標題)"),
                                "G-PROJ.C3", "qdrant payload vs:act.9.3: differs in ['title']"),
    "PG text_sha differs from the payload": (
        _edit_row("embedding_records", "record_id", "vs:eph.6.4", text_sha="0" * 64), "G-PROJ.C4",
        "vs:eph.6.4: payload text_sha is not PG's"),
    "a point vector is another record's": (
        lambda l: _set_vector(l, "vs:eph.6.4", fake_encoder.vector("別的")),
        "G-PROJ.C4", "vs:eph.6.4: point vector is not the layer's"),
    "an anchor moves to a slot that does not exist": (
        lambda l: _rewrite_contract(l, "event_registry.json", _move_anchor), "G-PROJ.C5",
        "anchor ps:psa.42.1: slot psa.42.9 not in PG"),
    "an anchor's passage is gone from PG": (
        _drop_row("passages", "passage_id", "ps:act.9.3b"), "G-PROJ.C5",
        "anchor ps:act.9.3b: passage not in PG"),
    "an anchor's passage is gone from Qdrant": (
        _drop_points("ps:act.9.1"), "G-PROJ.C5", "anchor ps:act.9.1: passage not in Qdrant"),
    "a routing term without provenance": (
        lambda l: _rewrite_contract(l, "routing_lexicon.json", _unsourced_term), "G-PROJ.C5",
        "persons[3]: no provenance_class/source"),
    "a contract file's bytes change, not its content": (
        _reformat_contract("books.json"), "G-PROJ.C5", "books.json: sha256 is not the release's"),
    "the contract manifest lists another sha": (lambda l: _rewrite_contract(
        l, "manifest.json", lambda d: d["files"].update({"books.json": "0" * 64})), "G-PROJ.C5",
        "manifest.json files are not the release's contract shas"),
    "a contract file goes missing": (
        lambda l: (l.targets.contracts_dir / "books.json").unlink(), "G-PROJ.C5",
        "contract files ['books.json'] differ from the release"),
    "a gold slot is no longer present": (
        _edit_row("verse_slots", "slot_key", "mat.18.4", status="omitted_variant"), "G-PROJ.C6",
        "Q1: gold slot mat.18.4 is omitted_variant"),
    "a foreign key is missing": (
        lambda l: l.pg.constraint_sets[l.targets.schema].discard(
            ("verse_slots", "fk_verse_slots_unit_key", "f")), "G-SCHEMA.pg",
        "verse_slots: no constraint fk_verse_slots_unit_key (f)"),
    "a unique constraint is missing": (
        _drop_unique, "G-SCHEMA.pg",
        "embedding_records: no constraint uq_embedding_records_point_id (u)"),
}


@pytest.mark.parametrize("case", sorted(MUTATIONS))
def test_a_drifted_projection_turns_its_check_red(loaded, case):
    mutate, gate, reason = MUTATIONS[case]
    mutate(loaded)
    found = mini_loaded.red_details(loaded.verify())
    assert mini_loaded.turned_red(found, gate, reason), found


def _drift(vector, cos):
    """A unit vector at cosine ``cos`` from ``vector``."""
    v = np.asarray(vector, dtype=np.float64)
    v = v / np.linalg.norm(v)
    other = np.roll(v, 1) - np.dot(np.roll(v, 1), v) * v
    other /= np.linalg.norm(other)
    return v * cos + other * np.sqrt(1 - cos * cos)


def test_a_point_vector_a_hair_off_the_layer_turns_c4_red(loaded):
    """cos 0.9999 is below 0.99999: both the stored-row and the re-encode comparisons see it."""
    point = next(p for p in loaded.qdrant.points(loaded.targets.collection)
                 if p.payload["record_id"] == "vs:eph.6.4")
    _set_vector(loaded, "vs:eph.6.4", _drift(point.vector, 0.9999))
    found = mini_loaded.red_details(loaded.verify(sample=100))
    assert mini_loaded.turned_red(found, "G-PROJ.C4", "vs:eph.6.4: point vector is not the layer's")
    assert mini_loaded.turned_red(found, "G-PROJ.C4", "re-encoded vs:eph.6.4: cos 0.9999")


def test_lexicon_terms_without_provenance_or_source_are_named():
    doc = {"persons": [{"term": "甲", "provenance_class": "pdf_text", "source": "x"},
                       {"term": "乙", "source": "x"}],
           "places": [{"term": "丙", "provenance_class": "pdf_text"}], "books": ["丁"]}
    found = verifier._lexicon_violations(doc)
    assert [v.split(":")[0] for v in found] == [
        "routing_lexicon.json persons[1]", "routing_lexicon.json places[0]",
        "routing_lexicon.json books[0]"]
    assert verifier._lexicon_violations({"persons": doc["persons"][:1]}) == []


def test_the_text_sha_check_compares_payload_with_pg(loaded):
    _set_payload(loaded, "ps:eph.6.1", text_sha="1" * 64)
    red = mini_loaded.red(loaded.verify())
    assert {"G-PROJ.C3", "G-PROJ.C4"} <= red


def test_re_encoding_compares_pg_text_with_the_point(loaded):
    """A PG text whose vector is not its point's turns C4 red (the re-encode sample is all)."""
    _edit_row("embedding_records", "record_id", "vs:act.9.1", text="另一段文字")(loaded)
    c4 = next(g for g in loaded.verify(sample=100).gates if g.name == "G-PROJ.C4")
    assert not c4.passed and any(d.startswith("re-encoded vs:act.9.1") for d in c4.details)
    assert c4.observed["reencoded"] == 22


def test_c4_fails_closed_without_an_encoder(loaded, monkeypatch):
    def broken(*args, **kwargs):
        raise verifier.StageError("offline model missing")
    monkeypatch.setattr(verifier, "load_encoder", broken)
    c4 = next(g for g in loaded.verify(encoder=None).gates if g.name == "G-PROJ.C4")
    assert not c4.passed and "offline model missing" in c4.details[-1]


def test_a_gt_that_is_not_the_frozen_one_turns_c6_red(loaded, tmp_path):
    gt = tmp_path / "gt.json"
    gt.write_bytes(loaded.mini.gt.read_bytes() + b" ")
    assert "G-PROJ.C6" in mini_loaded.red(loaded.verify(gt=gt))
    other, freeze = mini_release.write_gt(tmp_path, "text@000000000000")
    assert "G-PROJ.C6" in mini_loaded.red(loaded.verify(gt=other, freeze=freeze))
    assert "G-PROJ.C6" in mini_loaded.red(loaded.verify(gt=tmp_path / "none.json"))


def test_an_omitted_slot_used_as_gold_turns_c6_red(loaded, tmp_path):
    gt, freeze = mini_release.write_gt(tmp_path, loaded.release.doc["layers"]["text"],
                                       gold={"Q1": ["mat.18.3"]}, omitted={"Q1": ["mat.18.4"]})
    c6 = next(g for g in loaded.verify(gt=gt, freeze=freeze).gates if g.name == "G-PROJ.C6")
    assert not c6.passed and len(c6.details) == 2


def test_nothing_loaded_is_red_everywhere(tmp_path, mini):
    loaded = mini_loaded.load(tmp_path, mini)
    loaded.pg.schemas.clear()
    loaded.qdrant._client.delete_collection(loaded.targets.collection)
    for path in loaded.targets.contracts_dir.iterdir():
        path.unlink()
    loaded.targets.contracts_dir.rmdir()
    report = loaded.verify()
    assert not report.passed and mini_loaded.red(report) == {g.name for g in report.gates}
    assert report.to_json()["pass"] is False


def test_a_dropped_table_is_red_not_a_crash(loaded):
    del loaded.pg.schemas[loaded.targets.schema]["speakers"]
    loaded.pg.constraint_sets[loaded.targets.schema] = {
        c for c in loaded.pg.constraint_sets[loaded.targets.schema] if c[0] != "speakers"}
    assert {"G-SCHEMA.pg", "G-PROJ.C2", "G-PROJ.C3"} <= mini_loaded.red(loaded.verify())


def test_the_report_is_json(loaded):
    doc = loaded.verify().to_json()
    assert doc["schema"] == "ragdata.projection_report.v1" and doc["pass"] is True
    assert json.loads(json.dumps(doc)) == doc
    c4 = next(g for g in doc["gates"] if g["name"] == "G-PROJ.C4")
    assert c4["observed"]["reencoded"] == 5 and c4["observed"]["min_cos"] > 0.99999


def test_point_vectors_are_compared_row_by_row(loaded):
    rows = np.stack([p.vector for p in loaded.qdrant.points(loaded.targets.collection)])
    assert rows.shape == (22, fake_encoder.DIM)
