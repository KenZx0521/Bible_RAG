"""S14: G-PROJ turns red when the projection drifts from the release in any checked way."""

from __future__ import annotations

import json
import os

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


MUTATIONS = {
    "build_info names another build": (
        lambda l: _rows(l, "build_info")[0].update(build_id="b20000101_00000000"), "G-PROJ.C1"),
    "a point names another build": (
        lambda l: _set_payload(l, "vs:eph.6.4", build_id="b20000101_00000000"), "G-PROJ.C1"),
    "the contract manifest names another build": (lambda l: _rewrite_contract(
        l, "manifest.json", lambda d: d.update(build_id="b20000101_00000000")), "G-PROJ.C1"),
    "a verse is missing in PG": (_drop_row("verse_units", "unit_key", "eph.6.4"), "G-PROJ.C2"),
    "an event anchor is missing in PG": (
        _drop_row("event_anchors", "passage_id", "ps:act.9.3b"), "G-PROJ.C2"),
    "a point is missing": (lambda l: l.qdrant._client.delete(
        l.targets.collection, points_selector=models.PointIdsList(points=[
            ids.point_id("vs:eph.6.4")]), wait=True), "G-PROJ.C2"),
    "a PG field differs": (_edit_row("headings", "heading_id", "hd:psa.42.1#1", text="改了"),
                           "G-PROJ.C3"),
    "a jsonb field differs": (_edit_row("passages", "passage_id", "ps:eph.6.1", unit_refs=[]),
                              "G-PROJ.C3"),
    "a payload field differs": (lambda l: _set_payload(l, "vs:act.9.3", title="(無標題)"),
                                "G-PROJ.C3"),
    "PG text_sha differs from the payload": (
        _edit_row("embedding_records", "record_id", "vs:eph.6.4", text_sha="0" * 64), "G-PROJ.C3"),
    "a point vector is another record's": (
        lambda l: _set_vector(l, "vs:eph.6.4", fake_encoder.vector("別的")),
        "G-PROJ.C4"),
    "an anchor moves to a slot that does not exist": (
        lambda l: _rewrite_contract(l, "event_registry.json", _move_anchor), "G-PROJ.C5"),
    "a routing term without provenance": (
        lambda l: _rewrite_contract(l, "routing_lexicon.json", _unsourced_term), "G-PROJ.C5"),
    "a contract file goes missing": (
        lambda l: (l.targets.contracts_dir / "books.json").unlink(), "G-PROJ.C5"),
    "a gold slot is no longer present": (
        _edit_row("verse_slots", "slot_key", "mat.18.4", status="omitted_variant"), "G-PROJ.C6"),
    "a foreign key is missing": (
        lambda l: l.pg.constraint_sets[l.targets.schema].discard(
            ("verse_slots", "fk_verse_slots_unit_key", "f")), "G-SCHEMA.pg"),
}


@pytest.mark.parametrize("case", sorted(MUTATIONS))
def test_a_drifted_projection_turns_its_check_red(loaded, case):
    mutate, gate = MUTATIONS[case]
    mutate(loaded)
    assert gate in mini_loaded.red(loaded.verify())


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
