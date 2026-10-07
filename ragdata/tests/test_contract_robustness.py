"""A row of the wrong JSON shape is a ContractError, never a crash.

G-SCHEMA only turns ContractError into a ``file:line`` violation; any other
exception aborts the whole gate run without a report.
"""

from __future__ import annotations

import pytest

import mini_build
from ragdata.contract import ContractError, parse_record
from ragdata.gates import check_schema

ODD_VALUES = (["present"], {"a": 1}, [], {}, 1.5, True, None, "", -1, "x" * 3)


def _rows():
    for layer in mini_build.build().values():
        for type_name, rows in layer.items():
            yield from ((type_name, row) for row in rows)


def _paths(value, prefix=()):
    """Every position inside a JSON value, nested objects and lists included."""
    items = value.items() if isinstance(value, dict) else enumerate(value) \
        if isinstance(value, list) else ()
    for key, child in items:
        yield (*prefix, key)
        yield from _paths(child, (*prefix, key))


def _replaced(value, path, new):
    if not path:
        return new
    head, rest = path[0], path[1:]
    if isinstance(value, dict):
        return {**value, head: _replaced(value[head], rest, new)}
    return [_replaced(v, rest, new) if i == head else v for i, v in enumerate(value)]


@pytest.mark.parametrize("type_name,row", list(_rows()), ids=lambda v: v
                         if isinstance(v, str) else "")
def test_any_position_with_any_json_value_parses_or_raises_contract_error(type_name, row):
    for path in _paths(row):
        for value in ODD_VALUES:
            try:
                parse_record(type_name, _replaced(row, path, value))
            except ContractError:
                pass


@pytest.mark.parametrize("type_name,key,field", [
    ("verse_slots", "slot_key", "status"),
    ("verse_slots", "slot_key", "provenance_class"),
    ("footnotes", "fn_id", "kind"),
    ("headings", "heading_id", "pos"),
])
@pytest.mark.parametrize("value", [["present"], {"status": "present"}])
def test_choice_fields_reject_lists_and_objects(type_name, key, field, value):
    row = dict(mini_build.text_layer()[type_name][0])
    row[field] = value
    with pytest.raises(ContractError, match=field):
        parse_record(type_name, row)


def test_g_schema_reports_a_list_status_at_its_file_and_line():
    files = mini_build.files("text")
    files["verse_slots.jsonl"][4]["status"] = ["present"]
    result, snapshot = check_schema(files, ("text",))
    assert not result.passed
    assert any(d.startswith("verse_slots.jsonl:5: status:") for d in result.details)
    assert len(snapshot.of("verse_slots")) == len(files["verse_slots.jsonl"]) - 1
