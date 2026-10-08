"""The contract files of a release (design §7.5), derived from its layers alone.

The backend reads them from ``store/contracts/{build_id}/``; the loader writes them
there and the release pins their sha256s, so they must be a pure function of the
layers. Layer files that already are contracts are copied byte for byte
(the event registry, the routing lexicon and its query aliases, the encoder fingerprint,
legacy_ids);
the rest are canonical JSON over the text and struct rows:

- ``books.json``: the text layer's book rows in canon order;
- ``verse_index.json``: every slot (canon order) with its status, unit, variant
  footnote and the passage that owns its unit (``split_passage_ids`` for a unit a
  mid-verse heading cuts); an omitted slot has no unit and no passage;
- ``ref_aliases.json``: the text layer's external reference aliases.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ragdata.contract.registry import (
    ENCODER_FINGERPRINT, EVENT_REGISTRY_V2, QUERY_ALIASES, ROUTING_LEXICON,
)
from ragdata.store import LayerData
from ragdata.store.cas import sha256_bytes

COPIED = {
    "event_registry.json": ("events", EVENT_REGISTRY_V2),
    "routing_lexicon.json": ("route", ROUTING_LEXICON),
    "query_aliases.json": ("route", QUERY_ALIASES),
    "encoder_fingerprint.json": ("emb", ENCODER_FINGERPRINT),
    "legacy_ids.jsonl": ("struct", "legacy_ids.jsonl"),
}
DERIVED = ("books.json", "verse_index.json", "ref_aliases.json")
CONTRACT_FILES = (*DERIVED, *COPIED)


class ContractFileError(ValueError):
    """The layers do not give a contract file (a missing file or a dangling slot)."""


def encode(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")


def _rows(layer: LayerData, file_name: str) -> tuple[dict[str, Any], ...]:
    if file_name not in layer.rows:
        raise ContractFileError(f"{layer.version} holds no {file_name}")
    return layer.rows[file_name]


def _slot_entry(slot: Mapping[str, Any], owners: Mapping[str, Mapping[str, Any]]
                ) -> dict[str, Any]:
    unit = slot["unit_key"]
    if unit is not None and unit not in owners:
        raise ContractFileError(f"slot {slot['slot_key']}: unit {unit} has no verse_index row")
    owner = owners.get(unit, {}) if unit is not None else {}
    return {"slot_key": slot["slot_key"], "status": slot["status"], "unit_key": unit,
            "variant_footnote_id": slot["variant_footnote_id"],
            "passage_id": owner.get("passage_id"),
            "split_passage_ids": list(owner.get("split_passage_ids", [])),
            "pericope_id": owner.get("pericope_id")}


def verse_index(text: LayerData, struct: LayerData) -> bytes:
    owners = {row["unit_key"]: row for row in _rows(struct, "verse_index.jsonl")}
    slots = [_slot_entry(s, owners) for s in _rows(text, "verse_slots.jsonl")]
    return encode({"schema": "ragdata.contract.verse_index.v1", "text": text.version,
                   "struct": struct.version, "slots": slots})


def _derived(layers: Mapping[str, LayerData]) -> dict[str, bytes]:
    text = layers["text"]
    return {
        "books.json": encode({"schema": "ragdata.contract.books.v1", "text": text.version,
                              "books": list(_rows(text, "books.jsonl"))}),
        "verse_index.json": verse_index(text, layers["struct"]),
        "ref_aliases.json": encode({"schema": "ragdata.contract.ref_aliases.v1",
                                    "text": text.version,
                                    "aliases": list(_rows(text, "ref_aliases.jsonl"))}),
    }


def _copied(layers: Mapping[str, LayerData]) -> dict[str, bytes]:
    files = {}
    for name, (layer_name, source) in COPIED.items():
        layer = layers[layer_name]
        if source not in layer.file_shas:
            raise ContractFileError(f"{layer.version} holds no {source}")
        data = (layer.path / source).read_bytes()
        if sha256_bytes(data) != layer.file_shas[source]:
            raise ContractFileError(f"{layer.path / source}: sha256 differs from its manifest")
        files[name] = data
    return files


def contract_files(layers: Mapping[str, LayerData]) -> dict[str, bytes]:
    """Every contract file (but manifest.json, which names the build) by name."""
    missing = sorted({"text", "struct", *(l for l, _ in COPIED.values())} - set(layers))
    if missing:
        raise ContractFileError(f"contract files need the layers {missing}")
    return {**_derived(layers), **_copied(layers)}
