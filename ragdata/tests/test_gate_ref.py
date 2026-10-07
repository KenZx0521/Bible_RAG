"""G-REF: references resolve, and ragcommon's verse grid and aliases are the text layer's."""

from __future__ import annotations

import pytest

import mini_build
from ragcommon.versification import OmittedSlot, RefAlias
from ragdata.gates import check_schema
from ragdata.gates.ref import check_ref

GRID = mini_build.GRID
_vers = mini_build.versification


def _gate(change=None, vers=None):
    files = mini_build.files("text")
    if change is not None:
        change(files)
    schema, snap = check_schema(files, ("text",))
    assert schema.passed, schema.details
    return check_ref(snap, vers or _vers())


def test_the_mini_snapshot_agrees_with_its_versification():
    result = _gate()
    assert result.passed, result.details
    assert (result.name, result.hard) == ("G-REF", True)


def _row(files, type_name, pk, key):
    return next(r for r in files[f"{type_name}.jsonl"] if r[pk] == key)


def _target(pr_id, **changes):
    return lambda f: _row(f, "parallel_refs", "pr_id", pr_id)["targets"][0].update(changes)


CASES = {
    "max verse differs": (None, _vers(grid={**GRID, "eph": (1,) * 5 + (5,)}), "eph.6"),
    "last chapter differs": (None, _vers(grid={**GRID, "sng": (1, 1)}), "sng"),
    "omitted slot missing": (None, _vers(omitted={}), "mat.18.3"),
    "omitted slot elsewhere": (None, _vers(omitted={"mat.18.3": OmittedSlot("mat.18.3",
                                                                           "mat.18.1")}),
                               "mat.18.3"),
    "alias missing": (None, _vers(aliases={}), "mat.18.5"),
    "parallel target off the grid": (_target("pr:hd:mat.18.1#1#1", end_slot="act.9.9"), None,
                                     "act.9.9"),
    "section range into another book": (
        _target("pr:hd:act.9.1#1#1", book_id="eph", start_slot="eph.6.1", end_slot="eph.6.4"),
        None, "pr:hd:act.9.1#1#1"),
}


@pytest.mark.parametrize("change, vers, needle", CASES.values(), ids=CASES.keys())
def test_each_disagreement_turns_the_gate_red(change, vers, needle):
    result = _gate(change, vers)
    assert not result.passed
    assert any(needle in d for d in result.details), result.details


def test_an_alias_to_an_omitted_slot_is_red():
    aliases = {"mat.18.5": RefAlias("mat.18.5", "contained_in", "mat.18.3", "測試",
                                    "external_reference")}
    change = lambda f: _row(f, "ref_aliases", "external_ref", "mat.18.5").update(  # noqa: E731
        target="mat.18.3")
    result = _gate(change, _vers(aliases=aliases))
    assert any("mat.18.3" in d for d in result.details), result.details
