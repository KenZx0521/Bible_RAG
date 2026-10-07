"""The embedding record contract (design §2.16): ids, hashes and payload agree."""

from __future__ import annotations

import copy

import pytest

import mini_build
from ragcommon import ids
from ragdata.contract import ContractError, layer_types, parse_record, record_to_dict


def _row(record_id="vs:act.9.3"):
    text = mini_build.emb_text(record_id)
    payload = copy.deepcopy(mini_build.EMB_PAYLOADS[record_id])
    source = record_id[3:] if record_id.startswith("vs:") else record_id
    return {"record_id": record_id, "kind": payload["kind"], "source_id": source,
            "template_id": "v1c", "text": text, "text_sha": mini_build.sha(text),
            "token_count": mini_build.count_tokens(text), "unk_count": 1,
            "point_id": ids.point_id(record_id), "payload": payload,
            "provenance_class": "pdf_deterministic"}


def test_emb_layer_declares_its_record_type():
    assert [(t.name, t.pk) for t in layer_types("emb")] == [("embedding_records", "record_id")]


@pytest.mark.parametrize("record_id", sorted(mini_build.EMB_PAYLOADS))
def test_hand_written_rows_parse_and_round_trip(record_id):
    raw = _row(record_id)
    assert record_to_dict(parse_record("embedding_records", raw)) == raw


def _broken(record_id="vs:act.9.3", payload=None, **changes):
    row = _row(record_id)
    row.update(changes)
    row["payload"].update(payload or {})
    return row


BROKEN = {
    "text sha": _broken(text_sha="0" * 64),
    "point id": _broken(point_id=ids.point_id("vs:act.9.2")),
    "kind off the id": _broken(kind="passage"),
    "verse source": _broken(source_id="act.9.2"),
    "passage source": _broken("ps:act.10.1", source_id="ps:act.9.3b"),
    "unk over tokens": _broken(unk_count=10_000),
    "template": _broken(template_id="v2"),
    "payload record id": _broken(payload={"record_id": "vs:act.9.2"}),
    "payload kind": _broken(payload={"kind": "chunk"}),
    "legacy type": _broken("ps:act.10.1", payload={"type": "passage"}),
    "parent off passage": _broken(payload={"parent_pericope_id": "ps:act.9.3b"}),
    "passage payload elsewhere": _broken("ps:act.10.1", payload={
        "passage_id": "ps:act.9.3b", "parent_pericope_id": "ps:act.9.3b"}),
    "payload text sha": _broken(payload={"text_sha": "0" * 64}),
    "verse range": _broken(payload={"verse_range": "2"}),
    "chapter": _broken(payload={"chapter_num": 8, "chapter_end": 8}),
    "chapter end": _broken(payload={"chapter_end": 10}),
    "book": _broken(payload={"book_id": "mat"}),
    "preview not in text": _broken(payload={"content_preview": "別的話"}),
    "split without owner first": _broken(payload={"split_passage_ids": ["ps:act.9.3b"]}),
    "provenance": _broken(provenance_class="external_legacy"),
}


@pytest.mark.parametrize("raw", BROKEN.values(), ids=BROKEN.keys())
def test_contract_rejects(raw):
    with pytest.raises(ContractError):
        parse_record("embedding_records", raw)
