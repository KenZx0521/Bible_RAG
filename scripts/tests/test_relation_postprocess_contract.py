"""Step 6.05 (relation_postprocess): the core's contract with its inputs and outputs.

test_relation_postprocess.py has the rules; this file pins three promises of
the module docstring that no rule test sees:

- postprocess is a pure core: neither mode changes the parsed inputs (every
  row goes through base_stamp, which hands the rules a copy).
- base_stamp keeps a row's own source and derives one from the phase only
  when the row has none (the fixture's one explicit source equals its phase's).
- write_outputs writes the jsonl first, then the report.
"""

from __future__ import annotations

import copy

import pytest

from relation_extraction import relation_postprocess as pp
from test_relation_postprocess import _paths, _run


@pytest.mark.parametrize("rules", ["none", "all"])
def test_postprocess_leaves_the_inputs_unchanged(rules):
    inputs, cfg = pp.load_inputs(_paths())
    before = copy.deepcopy(inputs)

    rows, _ = pp.postprocess(inputs, cfg, rules)

    assert rows and inputs == before


def test_base_stamp_keeps_the_rows_own_source():
    _, cfg = pp.load_inputs(_paths())
    # phase 3 alone would make it prior
    row = {"head_id": "person:tala", "relation": "FATHER_OF", "tail_id": "person:yabolahan",
           "extraction_phase": 3, "source": "curated"}

    assert pp.base_stamp(row, cfg)["source"] == "curated"
    assert pp.base_stamp({**row, "source": None}, cfg)["source"] == "prior"


def test_write_outputs_writes_the_jsonl_before_the_report(tmp_path, monkeypatch):
    rows, report = _run("all")
    written = []
    real = pp._write_atomic

    def recording(path, data):
        written.append(path.name)
        real(path, data)

    monkeypatch.setattr(pp, "_write_atomic", recording)
    pp.write_outputs(rows, report, tmp_path / "r.jsonl", tmp_path / "r.report.json")

    assert written == ["r.jsonl", "r.report.json"]
    assert (tmp_path / "r.jsonl").read_bytes() == pp.serialize(rows)
