"""Struct-layer record contracts (design §2.13–2.15)."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.contract import ContractError, layer_types, parse_record, record_to_dict

STRUCT = mini_build.struct_layer()


def test_struct_layer_declares_pericopes_passages_chunks():
    assert {t.name for t in layer_types("struct")} == {"pericopes", "passages", "chunks"}


@pytest.mark.parametrize("type_name", sorted(STRUCT))
def test_every_mini_row_parses_and_round_trips(type_name):
    for raw in STRUCT[type_name]:
        assert record_to_dict(parse_record(type_name, raw)) == raw


def _with(type_name, key, **changes):
    pk = {t.name: t.pk for t in layer_types("struct")}[type_name]
    row = next(r for r in mini_build.struct_layer()[type_name] if r[pk] == key)
    row.update(changes)
    return type_name, row


BROKEN = {
    "untitled pericope with heading": _with("pericopes", "pc:psa.42.1",
                                            untitled_reason="book_opening"),
    "titled pericope without title": _with("pericopes", "pc:psa.42.1", title=None),
    "pericope id off start": _with("pericopes", "pc:psa.42.1", start_slot="psa.42.2",
                                   start={"unit_key": "psa.42.2", "offset": 0}),
    "half start without b": _with("pericopes", "pc:psa.42.1",
                                  start={"unit_key": "psa.42.1", "offset": 3}),
    "pericope range descends": _with("pericopes", "pc:mat.18.1", end_slot="mat.17.4",
                                     end={"unit_key": "mat.17.4", "offset": None},
                                     chapters=[17, 18]),
    "chapters skip": _with("pericopes", "pc:act.9.3b", chapters=[9]),
    "pericope crosses books": _with("pericopes", "pc:mat.18.1", end_slot="act.9.1"),
    "pericope next is itself": _with("pericopes", "pc:act.9.1", next_id="pc:act.9.1"),
    "pericope without passages": _with("pericopes", "pc:act.9.1", passage_ids=[]),
    "end slot outside end unit": _with("pericopes", "pc:eph.6.1", end_slot="eph.6.3"),
    "b end key that ends early": _with("passages", "ps:act.9.3b", end_partial=True),
    "passage id off start key": _with("passages", "ps:mat.18.1", start_key="mat.18.2",
                                      start_slot="mat.18.2", verse_range="2-4"),
    "verse range": _with("passages", "ps:mat.18.1", verse_range="1-3"),
    "passage crosses chapters": _with("passages", "ps:act.9.1", end_key="act.10.1",
                                      end_slot="act.10.1"),
    "chapter key": _with("passages", "ps:mat.18.1", chapter_key="mat.17"),
    "continued flag": _with("passages", "ps:act.10.1", continued=False),
    "segment index": _with("passages", "ps:act.10.1", seg_idx=2),
    "partial flag": _with("passages", "ps:act.9.3b", start_partial=False),
    "end slot off end key": _with("passages", "ps:act.9.1", end_slot="act.9.2"),
    "content sha": _with("passages", "ps:mat.18.1", content_sha="0" * 64),
    "requires chunking": _with("passages", "ps:act.9.1", requires_chunking=False),
    "superscription elsewhere": _with("passages", "ps:psa.42.1", superscription_id="sp:psa.41"),
    "empty unit ref": _with("passages", "ps:mat.18.1",
                            unit_refs=[{"unit_key": "mat.18.1", "from": 3, "to": 3}]),
    "chunk id": _with("chunks", "ck:act.9.1~act.9.2", end_key="act.9.3", verse_range="1-3"),
    "chunk too long": _with("chunks", "ck:act.9.1~act.9.2", token_count=769),
    "chunk verse range": _with("chunks", "ck:act.9.1~act.9.2", verse_range="1"),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_rows_raise_contract_error(case):
    type_name, raw = BROKEN[case]
    with pytest.raises(ContractError):
        parse_record(type_name, raw)
