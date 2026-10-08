"""The contract files a release derives from its layers (design §7.5)."""

from __future__ import annotations

import json

import pytest

import mini_release
from ragdata.release import contracts
from ragdata.store import read_layer


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mini = mini_release.build(tmp_path_factory.mktemp("contracts"))
    layers = {name: read_layer(layer.path) for name, layer in mini.layers.items()}
    return mini, layers, contracts.contract_files(layers)


def _doc(files, name):
    return json.loads(files[name].decode("utf-8"))


def test_the_release_ships_every_contract_file(built):
    _, _, files = built
    assert set(files) == set(contracts.CONTRACT_FILES)
    assert all(data.endswith(b"\n") for data in files.values())


def test_layer_files_are_copied_byte_for_byte(built):
    mini, _, files = built
    copies = {"event_registry.json": ("events", "event_registry_v2.json"),
              "routing_lexicon.json": ("route", "routing_lexicon.json"),
              "query_aliases.json": ("route", "query_aliases.json"),
              "encoder_fingerprint.json": ("emb", "encoder_fingerprint.json"),
              "legacy_ids.jsonl": ("struct", "legacy_ids.jsonl")}
    for name, (layer, source) in copies.items():
        assert files[name] == (mini.layers[layer].path / source).read_bytes(), name


def test_verse_index_maps_every_slot_to_its_unit_and_owning_passage(built):
    _, layers, files = built
    doc = _doc(files, "verse_index.json")
    assert (doc["text"], doc["struct"]) == (layers["text"].version, layers["struct"].version)
    slots = {s["slot_key"]: s for s in doc["slots"]}
    assert list(slots) == [r["slot_key"] for r in layers["text"].rows["verse_slots.jsonl"]]
    assert slots["eph.6.3"] == {"slot_key": "eph.6.3", "status": "merged", "unit_key": "eph.6.2-3",
                                "variant_footnote_id": None, "passage_id": "ps:eph.6.1",
                                "split_passage_ids": [], "pericope_id": "pc:eph.6.1"}
    assert slots["mat.18.3"]["status"] == "omitted_variant"
    assert slots["mat.18.3"]["passage_id"] is None
    assert slots["mat.18.3"]["variant_footnote_id"] == "fn:mat.18.2#1"
    assert slots["act.9.3"]["split_passage_ids"] == ["ps:act.9.1", "ps:act.9.3b"]


def test_books_and_ref_aliases_carry_the_text_rows(built):
    _, layers, files = built
    books = _doc(files, "books.json")
    assert books["text"] == layers["text"].version
    assert books["books"] == list(layers["text"].rows["books.jsonl"])
    aliases = _doc(files, "ref_aliases.json")
    assert aliases["aliases"] == list(layers["text"].rows["ref_aliases.jsonl"])


def test_contract_files_are_deterministic(built):
    _, layers, files = built
    assert contracts.contract_files(layers) == files


def test_a_slot_whose_unit_has_no_index_row_is_refused(built):
    _, layers, _ = built
    struct = layers["struct"]
    rows = {**struct.rows, "verse_index.jsonl": struct.rows["verse_index.jsonl"][1:]}
    broken = {**layers, "struct": type(struct)(struct.layer, struct.version, struct.path,
                                               struct.depends_on, struct.file_shas, rows)}
    with pytest.raises(contracts.ContractFileError, match="psa.42.1"):
        contracts.contract_files(broken)
