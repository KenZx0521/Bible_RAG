"""Edge-set equality gate (scripts/tools/check_edge_set.py, batch 1A-T2).

The reference is a 6.05 output and its report, built here with
relation_postprocess's own serialize and expected_after_10_2: the clean file
minus the rows on the 10.2 generic events. "Live" is a fake read_query that
answers the gate's Cypher with the records 6.1 + 10.2 would leave: one per
remaining row, carrying its source and extraction_phase.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import import_relations_neo4j
from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST
from relation_extraction import relation_postprocess as pp
from scripts.tools import check_edge_set as ces

ROOT = Path(__file__).resolve().parents[2]
GENERIC = "event:rizi"
ENTITIES = {GENERIC: {"type": "Event", "canonical_name": GENERIC_EVENT_STOPLIST[0]},
            "event:chuai": {"type": "Event", "canonical_name": "出埃及"}}


def _row(head, relation, tail, source, phase):
    return {"head_id": head, "relation": relation, "tail_id": tail, "source": source,
            "extraction_phase": phase, "sources": [source], "pp_version": "pp-test"}


ROWS = sorted([
    _row("person:yabolahan", "FATHER_OF", "person:yisa", "prior", 3),
    _row("person:yisa", "SON_OF", "person:yabolahan", "anchored_rule", 6),
    _row("person:mose", "PARTICIPATED_IN", "event:chuai", "llm", 4),
    _row("person:mose", "VISITED", "place:xinai", "llm", 4),
    _row("person:mose", "PARTICIPATED_IN", GENERIC, "llm", 4),  # gone with 10.2
], key=lambda r: (r["head_id"], r["relation"], r["tail_id"]))


def live_record(row) -> dict:
    """What the gate's Cypher returns for an edge 6.1 wrote from `row`."""
    return {key: row.get(key) for key in ("head_id", "relation", "tail_id", "source", "extraction_phase")}


def after_10_2() -> list[dict]:
    return [live_record(r) for r in ROWS if GENERIC not in (r["head_id"], r["tail_id"])]


def write_reference(tmp_path, rows=ROWS, **patch) -> Path:
    """relations_clean.jsonl and its report; `patch` overrides report sections."""
    clean = tmp_path / "relations_clean.jsonl"
    data = pp.serialize(rows)
    clean.write_bytes(data)
    report = {"format": pp.REPORT_FORMAT,
              "output": {"path": str(clean), "sha256": hashlib.sha256(data).hexdigest(), "rows": len(rows)},
              "expected_after_10_2": pp.expected_after_10_2(list(rows), ENTITIES), **patch}
    path = tmp_path / "relations_clean.report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def write_expect(tmp_path, sha: str) -> Path:
    path = tmp_path / "relations_expected.json"
    path.write_text(json.dumps({"edge_set_sha256": sha, "edges": 4}), encoding="utf-8")
    return path


class FakeDriver:
    def __init__(self):
        self.closed = False

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def live(monkeypatch):
    """Patch the target read; set .records to what the graph holds."""
    state = SimpleNamespace(records=after_10_2(), resolved=[], driver=FakeDriver())

    def resolve(name, environ=None):
        state.resolved.append(name)
        return SimpleNamespace(name=name, neo4j_uri="bolt://localhost:7688")

    def read_query(driver, cypher, **params):
        assert driver is state.driver and cypher == ces.LIVE_EDGES_CYPHER
        return [dict(r) for r in state.records]

    monkeypatch.setattr(ces, "resolve_target", resolve)
    monkeypatch.setattr(ces, "open_neo4j", lambda target: state.driver)
    monkeypatch.setattr(ces, "read_query", read_query)
    return state


def run(report: Path, *extra: str) -> int:
    return ces.main(["--target", "staging", "--report", str(report), *extra])


def test_live_query_reads_the_layer_6_1_writes():
    """The gate certifies import_relations_neo4j's _LAYER (what 6.1 writes and --replace deletes),
    not a restatement of it that could drift; the records carry the fields live_record gives."""
    norm = lambda text: " ".join(text.split())  # noqa: E731
    query = norm(ces.LIVE_EDGES_CYPHER).replace("(a:Entity)", "(:Entity)").replace("(b:Entity)", "(:Entity)")
    layer = norm(import_relations_neo4j._LAYER)

    assert query.startswith(layer + " RETURN "), (query, layer)
    returned = query[len(layer + " RETURN "):].split(", ")
    assert sorted(part.rsplit(" AS ", 1)[1] for part in returned) == sorted(
        ["head_id", "relation", "tail_id", "source", "extraction_phase"])


def test_equal_set_exits_0(tmp_path, live, capsys):
    report = write_reference(tmp_path)
    sha = json.loads(report.read_text(encoding="utf-8"))["expected_after_10_2"]["edge_set_sha256"]

    assert run(report, "--expect", str(write_expect(tmp_path, sha))) == 0

    out = capsys.readouterr().out
    assert live.resolved == ["staging"] and live.driver.closed
    assert "4 edges" in out and sha[:12] in out
    assert out.rstrip().splitlines()[-1].startswith("exit 0")


def test_extra_edge_exits_1_with_sample(tmp_path, live, capsys):
    added = [{"head_id": "person:mose", "relation": "VISITED", "tail_id": f"place:p{n:02d}",
              "source": "llm", "extraction_phase": 4} for n in range(12)]
    live.records += added

    assert run(write_reference(tmp_path)) == 1

    out = capsys.readouterr().out
    assert "VISITED phase=4 source=llm: 1 -> 13 (+12)" in out
    assert "extra in live: 12" in out and "missing from live: 0" in out
    shown = [line.strip() for line in out.splitlines() if "\tVISITED\tplace:p" in line]
    assert shown == [f"person:mose\tVISITED\tplace:p{n:02d}\tllm" for n in range(10)]  # first 10 only


def test_count_only_swap_is_caught_by_sha(tmp_path, live, capsys):
    """Same count in every ee key, one edge pointing elsewhere: only the sha sees it."""
    swapped = next(r for r in live.records if r["relation"] == "VISITED")
    swapped["tail_id"] = "place:xiyan"

    assert run(write_reference(tmp_path)) == 1

    out = capsys.readouterr().out
    assert "ee key deltas" not in out and "4 edges" in out
    assert "missing from live: 1" in out and "person:mose\tVISITED\tplace:xinai\tllm" in out
    assert "extra in live: 1" in out and "person:mose\tVISITED\tplace:xiyan\tllm" in out


def test_phase_only_change_is_caught_by_ee_keys(tmp_path, live, capsys):
    """The sha has no phase; an edge written without its extraction_phase shows as an ee-key delta."""
    next(r for r in live.records if r["source"] == "anchored_rule")["extraction_phase"] = None

    assert run(write_reference(tmp_path)) == 1

    out = capsys.readouterr().out
    assert "SON_OF phase=6 source=anchored_rule: 1 -> 0 (-1)" in out
    assert "SON_OF phase=- source=anchored_rule: 0 -> 1 (+1)" in out


def test_expected_file_mismatch_exits_1(tmp_path, live, capsys):
    """Live equals the report, but not the committed expected sha (a report regenerated after it)."""
    assert run(write_reference(tmp_path), "--expect", str(write_expect(tmp_path, "0" * 64))) == 1

    out = capsys.readouterr().out
    assert "expect" in out.rstrip().splitlines()[-1] and "0" * 12 in out


def _not_json(tmp_path):
    path = tmp_path / "relations_clean.report.json"
    path.write_text("{", encoding="utf-8")
    return path


def _clean_edited(tmp_path):
    report = write_reference(tmp_path)
    clean = tmp_path / "relations_clean.jsonl"
    clean.write_bytes(clean.read_bytes().replace(b"place:xinai", b"place:xiyan"))
    return report


def _clean_nonedge_edited(tmp_path):
    """A field outside the edge set edited: the edge lines and the claim still match, only the hash tells."""
    report = write_reference(tmp_path)
    clean = tmp_path / "relations_clean.jsonl"
    clean.write_bytes(clean.read_bytes().replace(b"pp-test", b"pp-tesx"))
    return report


def _row_without_relation(tmp_path):
    """A report whose output.sha256 matches a file with a row that is no relation row."""
    report = write_reference(tmp_path)
    clean = tmp_path / "relations_clean.jsonl"
    rows = [json.loads(line) for line in clean.read_text(encoding="utf-8").splitlines()]
    del rows[0]["relation"]
    clean.write_bytes(pp.serialize(rows))
    doc = json.loads(report.read_text(encoding="utf-8"))
    doc["output"]["sha256"] = hashlib.sha256(clean.read_bytes()).hexdigest()
    report.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return report


@pytest.mark.parametrize("make, why", [
    (_not_json, "is not readable JSON"),
    (lambda tmp_path: write_reference(tmp_path, format="something/v0"), "'something/v0' report"),
    (lambda tmp_path: write_reference(tmp_path, expected_after_10_2=None), "is not a 6.05 report"),
    (_clean_edited, "output.sha256"),  # the file no longer hashes to output.sha256
    (_clean_nonedge_edited, "output.sha256"),
    (lambda tmp_path: write_reference(  # the report's claim does not follow from its file
        tmp_path, expected_after_10_2=pp.expected_after_10_2(ROWS[1:], ENTITIES)), "does not follow from"),
    (_row_without_relation, "has a line without"),
], ids=["not-json", "format", "no-expected-section", "clean-edited", "clean-nonedge-edited", "claim-mismatch",
        "row-without-relation"])
def test_bad_report_exits_2(tmp_path, live, capsys, make, why):
    assert run(make(tmp_path)) == 2
    assert live.resolved == []  # inputs are checked before the target is touched
    err = capsys.readouterr().err
    assert "CANNOT CHECK" in err and why in err, err


@pytest.mark.parametrize("doc", ['{"edges": 4}', '{"edge_set_sha256": "abc"}', "[]"])
def test_bad_expect_exits_2(tmp_path, live, doc):
    expect = tmp_path / "relations_expected.json"
    expect.write_text(doc, encoding="utf-8")
    assert run(write_reference(tmp_path), "--expect", str(expect)) == 2
    assert live.resolved == []


def test_unreadable_target_exits_2(tmp_path, live, monkeypatch, capsys):
    def refuse(name, environ=None):
        raise ValueError("--target staging refused: NEO4J_URI is the prod endpoint")
    monkeypatch.setattr(ces, "resolve_target", refuse)

    assert run(write_reference(tmp_path)) == 2
    assert "refused" in capsys.readouterr().err


def test_json_reports_deltas(tmp_path, live, capsys):
    live.records = live.records[1:]

    assert run(write_reference(tmp_path), "--json") == 1

    doc = json.loads(capsys.readouterr().out)
    assert doc["exit"] == 1 and doc["target"] == "staging"
    assert (doc["live"]["edges"], doc["report"]["edges"]) == (3, 4)
    assert set(doc["failed"]) == {"edges", "edge_set_sha256", "by_ee_key"}
    assert doc["missing"]["count"] == 1 and doc["extra"] == {"count": 0, "sample": []}
    (key, delta), = doc["ee_key_deltas"].items()
    assert delta == {"report": 1, "live": 0, "delta": -1}


def test_target_is_resolved_from_the_shell_not_from_dotenv():
    """Importing relation_postprocess runs entity_extraction's load_dotenv(), which copies .env
    (prod's NEO4J_URI) into os.environ. --target staging in a shell without staging exports
    must still get the staging defaults, as check_identity documents, not a refusal."""
    if not (ROOT / ".env").exists():
        pytest.skip("no .env: load_dotenv has nothing to copy, so there is nothing to guard against")
    store_keys = ("NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION", "KG_TARGET")
    env = {k: v for k, v in os.environ.items() if k not in store_keys}
    code = ("from scripts.tools import check_edge_set as c; import os; "
            "assert 'NEO4J_URI' in os.environ, 'load_dotenv did not run: the test proves nothing'; "
            "print(c.resolve_shell_target('staging').neo4j_uri)")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "bolt://localhost:7688"
