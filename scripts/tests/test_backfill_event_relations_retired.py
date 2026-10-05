"""backfill_event_relations (Step 10.3) is out of the default chain (D2, K7).

10.3 turned every Event–Person / Event–Place pair of the 2026-05
relations_unclassified.jsonl snapshot into a typed PARTICIPATED_IN or
OCCURRED_IN edge: 9,060 edges whose only evidence is sharing a pericope
(strict precision about 0.2), written after Step 6.05, so its provenance gate
never saw them (370 of them hang off the 「但」 false hits). Kay kept the script
for the K8 P1 control and for reproducing the paper's numbers only.

Without --legacy-cooccurrence the script now explains why and exits 2 before
it checks KG_TARGET or creates a driver. With the flag it writes the old edges,
labelled as what they are: source 'cooccurrence' and extraction_phase 7
(ExtractionPhase.COOCCURRENCE), no longer the phase 5 it shared with R5's
inverse edges (REL-09).

The driver is a fake that records each statement with its parameters; KG_TARGET
is unset, so assert_target lets the run through without connecting.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

import backfill_event_relations
from relation_extraction.models import ExtractionPhase, derive_source

ROOT = Path(__file__).resolve().parents[2]
UNCLASSIFIED = ROOT / "output" / "relations_unclassified.jsonl"

_SET = re.compile(r"r\.(\w+) = (\$\w+|'[^']*'|true|false|row\.\w+)")


class _Reached(Exception):
    """A refused run must never get this far."""


class _Result:
    def __init__(self, record: dict):
        self._record = record

    def single(self):
        return self._record


class _Session:
    def __init__(self, log: list):
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query: str, **params):
        self._log.append((query, params))
        if "rows" in params:
            n = len(params["rows"])
            return _Result({"matched": n, "created": n})
        return _Result({"total": 2, "with_participant": 1, "with_place": 1})


class _FakeDriver:
    def __init__(self):
        self.log: list = []

    def session(self):
        return _Session(self.log)

    def close(self):
        pass


def _pair(head: str, tail: str, tail_type: str, pericope: str = "gen_1") -> dict:
    return {"head_id": head, "head_type": "Event", "head_canonical": head.split(":")[1],
            "tail_id": tail, "tail_type": tail_type, "tail_canonical": tail.split(":")[1],
            "source_pericope_id": pericope}


def _unclassified(tmp_path: Path) -> Path:
    rows = [_pair("event:a", "person:x", "Person"),
            _pair("event:a", "person:x", "Person", "gen_2"),
            _pair("event:a", "place:y", "Place"),
            _pair("event:a", "event:b", "Event")]
    path = tmp_path / "relations_unclassified.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _main(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["backfill_event_relations.py", *argv])
    return backfill_event_relations.main()


def _on_create(query: str, params: dict, row: dict) -> dict:
    """The properties an edge created from `row` gets, read off ON CREATE SET."""
    block = query.split("ON CREATE SET", 1)[1].split("RETURN", 1)[0]
    found = _SET.findall(block)
    assert len(found) == block.count("r."), block   # every assignment was parsed
    props = {}
    for prop, expr in found:
        if expr.startswith("$"):
            props[prop] = params[expr[1:]]
        elif expr.startswith("row."):
            props[prop] = row[expr[4:]]
        elif expr.startswith("'"):
            props[prop] = expr[1:-1]
        else:
            props[prop] = expr == "true"
    return props


def test_refuses_without_legacy_flag(monkeypatch, tmp_path, capsys):
    reached = []

    def recorder(name):
        def call(*args, **kwargs):
            reached.append(name)
            raise _Reached(name)
        return call

    monkeypatch.setattr(backfill_event_relations, "get_driver", recorder("get_driver"))
    monkeypatch.setattr(backfill_event_relations.kg_target, "assert_target",
                        recorder("assert_target"))

    code = _main(monkeypatch, "--input", str(_unclassified(tmp_path)))

    assert code == 2
    assert reached == []
    err = capsys.readouterr().err
    assert "--legacy-cooccurrence" in err
    assert "D2" in err and "6.05" in err


def test_legacy_flag_writes_cooccurrence_source_and_phase_7(monkeypatch, tmp_path):
    monkeypatch.delenv("KG_TARGET", raising=False)
    driver = _FakeDriver()
    monkeypatch.setattr(backfill_event_relations, "get_driver", lambda: driver)

    code = _main(monkeypatch, "--legacy-cooccurrence", "--input", str(_unclassified(tmp_path)))

    assert code == 0
    merges = {re.search(r"MERGE \(\w+\)-\[r:(\w+)\]", q).group(1): (q, p)
              for q, p in driver.log if "MERGE" in q}
    assert sorted(merges) == ["OCCURRED_IN", "PARTICIPATED_IN"]
    query, params = merges["PARTICIPATED_IN"]
    assert params["rows"] == [{"event_id": "event:a", "person_id": "person:x",
                               "evidence_count": 2, "source_pericope_id": "gen_1",
                               "head_canonical": "a", "tail_canonical": "x"}]
    assert _on_create(query, params, params["rows"][0]) == {
        "confidence": 0.35, "extraction_phase": 7, "source": "cooccurrence",
        "notes": "cooccurrence-backfill", "evidence_count": 2,
        "source_pericope_id": "gen_1", "head_canonical": "a", "tail_canonical": "x",
        "backfilled": True,
    }
    for query, params in merges.values():
        props = _on_create(query, params, params["rows"][0])
        assert ExtractionPhase(props["extraction_phase"]) is ExtractionPhase.COOCCURRENCE
        assert derive_source(props["extraction_phase"], props["notes"],
                             props["backfilled"]) == props["source"] == "cooccurrence"


def test_event_event_skips_are_counted_and_reported_as_rows(monkeypatch, tmp_path, capsys):
    # Two rows of one Event–Event pair are two skips: the count is of rows, not pairs.
    monkeypatch.delenv("KG_TARGET", raising=False)
    monkeypatch.setattr(backfill_event_relations, "get_driver", _FakeDriver)
    path = _unclassified(tmp_path)
    path.write_text(path.read_text(encoding="utf-8")
                    + json.dumps(_pair("event:a", "event:b", "Event", "gen_2")) + "\n",
                    encoding="utf-8")

    assert _main(monkeypatch, "--legacy-cooccurrence", "--input", str(path)) == 0

    out = capsys.readouterr().out
    assert "Event–Event rows skipped (no temporal direction inferable): 2" in out
    assert "Event–Event pairs skipped" not in out


@pytest.mark.skipif(not UNCLASSIFIED.exists(),
                    reason="output/relations_unclassified.jsonl is a gitignored build product")
def test_load_pairs_on_real_output():
    participated, occurred, ee_skipped = backfill_event_relations.load_pairs(UNCLASSIFIED)

    assert (len(participated), len(occurred), ee_skipped) == (5946, 3616, 277)
    assert sum(r["evidence_count"] for r in participated) == 6419
    assert sum(r["evidence_count"] for r in occurred) == 3951
    # The 277 skipped are rows: 257 distinct (head_id, tail_id) pairs (module docstring).
    with UNCLASSIFIED.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    ee_pairs = {(r["head_id"], r["tail_id"]) for r in rows
                if r.get("head_type") == r.get("tail_type") == "Event"}
    assert len(ee_pairs) == 257
