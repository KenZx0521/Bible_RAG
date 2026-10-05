"""W1 expected file and allowlist fragment for the semantic edges
(scripts/tools/relations_expect.py, batch 1A-T4).

The reference is a 6.05 output and its report, built with relation_postprocess's
own serialize and expected_after_10_2, as in test_check_edge_set. The a side
(prod) is a fake diff_kg profile: diff_kg.read_profile runs for real over a
read_query that answers its PROFILE_QUERIES, so the keys are diff_kg's own.
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

from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST
from relation_extraction import relation_postprocess as pp
from scripts.tools import diff_kg as dk
from scripts.tools import relations_expect as rx

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

# prod before 1A: every semantic edge without a source, except one VISITED edge whose
# key and count W1 keeps (no entry for it); CAUSED disappears; MENTIONS is not 1A's.
PROD = {
    "relationships": [{"key": "FATHER_OF", "n": 3}, {"key": "SON_OF", "n": 2},
                      {"key": "PARTICIPATED_IN", "n": 5}, {"key": "CAUSED", "n": 1},
                      {"key": "VISITED", "n": 1}, {"key": "MENTIONS", "n": 50},
                      {"key": "CROSS_REFERENCES", "n": 100}],
    "ee_edges": [{"type": "FATHER_OF", "phase": 4, "source": None, "n": 2},
                 {"type": "FATHER_OF", "phase": 5, "source": None, "n": 1},
                 {"type": "SON_OF", "phase": 5, "source": None, "n": 2},
                 {"type": "PARTICIPATED_IN", "phase": None, "source": None, "n": 5},
                 {"type": "CAUSED", "phase": 4, "source": None, "n": 1},
                 {"type": "VISITED", "phase": 4, "source": "llm", "n": 1}],
}
REL = [("FATHER_OF", -2), ("SON_OF", -1), ("PARTICIPATED_IN", -4), ("CAUSED", -1)]
NEW = [("FATHER_OF phase=3 source=prior", 1), ("SON_OF phase=6 source=anchored_rule", 1),
       ("PARTICIPATED_IN phase=4 source=llm", 1)]
# What staging holds after the W1 chain: ROWS minus the edge 10.2 takes along, counted by hand.
W1_BY_TYPE = {"FATHER_OF": 1, "PARTICIPATED_IN": 1, "SON_OF": 1, "VISITED": 1}
W1_BY_EE_KEY = {**dict(NEW), "VISITED phase=4 source=llm": 1}


def write_reference(tmp_path, rows=ROWS) -> Path:
    clean = tmp_path / "relations_clean.jsonl"
    data = pp.serialize(rows)
    clean.write_bytes(data)
    report = {"format": pp.REPORT_FORMAT, "pp_version": "pp-test", "run_id": "6.05-test",
              "output": {"path": str(clean), "sha256": hashlib.sha256(data).hexdigest(), "rows": len(rows)},
              "expected_after_10_2": pp.expected_after_10_2(list(rows), ENTITIES)}
    path = tmp_path / "relations_clean.report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def edge_set_sha(report: Path) -> str:
    return json.loads(report.read_text(encoding="utf-8"))["expected_after_10_2"]["edge_set_sha256"]


class FakeDriver:
    def __init__(self):
        self.closed = False

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def prod(monkeypatch):
    """The a side: diff_kg.read_profile over PROFILE_QUERIES answered from PROD."""
    state = SimpleNamespace(rows=PROD, resolved=[], driver=FakeDriver())

    def resolve(name):
        state.resolved.append(name)
        return SimpleNamespace(name=name, neo4j_uri="bolt://localhost:7687")

    def read_query(driver, cypher, **params):
        assert driver is state.driver
        section = next(name for name, query in dk.PROFILE_QUERIES.items() if query == cypher)
        return [dict(r) for r in state.rows.get(section, [])]

    monkeypatch.setattr(rx, "resolve_shell_target", resolve)
    monkeypatch.setattr(rx, "open_neo4j", lambda target: state.driver)
    monkeypatch.setattr(dk, "read_query", read_query)
    return state


def run(tmp_path, report: Path, sha: str, *extra: str) -> int:
    return rx.main(["--report", str(report), "--expect-edge-set-sha", sha,
                    "--out", str(tmp_path / "relations_expected.json"),
                    "--allow-out", str(tmp_path / "relations_allow.yaml"), *extra])


def test_fragment_from_fake_profile(tmp_path, prod, capsys):
    report = write_reference(tmp_path)

    assert run(tmp_path, report, edge_set_sha(report)) == 0

    entries = dk.load_allowlist(tmp_path / "relations_allow.yaml")
    assert prod.resolved == ["prod"] and prod.driver.closed
    assert [(e["section"], e["key"], e.get("delta")) for e in entries] == (
        [("relationships", key, delta) for key, delta in sorted(REL)]
        + [("ee_edges", "* source=-", None)]
        + [("ee_edges", key, delta) for key, delta in sorted(NEW)])
    assert all(e["reason"].startswith("1A ") for e in entries)
    # 6.05 drops the LLM's Event–Event rows; E–E (Entity–Entity) edges of the LLM stay
    assert all("LLM 的 Event–Event 邊" in e["reason"] and "E–E" not in e["reason"]
               for e in entries if e["section"] == "relationships")
    expected = json.loads((tmp_path / "relations_expected.json").read_text(encoding="utf-8"))
    assert expected["edge_set_sha256"] == edge_set_sha(report) and expected["edges"] == 4
    assert expected["pp_version"] == "pp-test" and expected["run_id"] == "6.05-test"
    assert expected["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert expected["by_type"] == W1_BY_TYPE and expected["by_ee_key"] == W1_BY_EE_KEY
    assert expected["a"]["target"] == "prod" and expected["a"]["edges"] == 12
    assert expected["deltas"]["relationships"] == dict(sorted(REL))
    assert expected["deltas"]["ee_edges"]["FATHER_OF phase=4 source=-"] == -2
    assert "VISITED phase=4 source=llm" not in expected["deltas"]["ee_edges"]
    out = capsys.readouterr().out
    assert 'glob "* source=-" covers 5 keys, -11' in out
    assert "anchored_rule 1 (+1), llm 1 (+1), prior 1 (+1)" in out


def test_output_bytes_do_not_depend_on_the_run(tmp_path, prod):
    """Nor on the order Neo4j returns the a side's rows in (the expected file is pre-registered by sha)."""
    report = write_reference(tmp_path)
    assert run(tmp_path, report, edge_set_sha(report)) == 0
    first = [(tmp_path / name).read_bytes() for name in ("relations_expected.json", "relations_allow.yaml")]
    prod.rows = {section: list(reversed(rows)) for section, rows in PROD.items()}
    assert run(tmp_path, report, edge_set_sha(report)) == 0
    assert [(tmp_path / name).read_bytes() for name in ("relations_expected.json", "relations_allow.yaml")] == first


def test_sha_mismatch_exits_1(tmp_path, prod, capsys):
    """The report must reproduce an independent simulation's edge set: it cannot certify itself (plan §3)."""
    assert run(tmp_path, write_reference(tmp_path), "0" * 64) == 1

    assert prod.resolved == []  # decided before the target is touched
    assert not (tmp_path / "relations_expected.json").exists()
    assert not (tmp_path / "relations_allow.yaml").exists()
    assert "0" * 12 in capsys.readouterr().err


def _staging_profile(extra_edge: bool) -> dict:
    """What diff_kg reads on a staging that holds exactly the W1 semantic layer: prod's MENTIONS and
    CROSS_REFERENCES, and the hand-counted W1 edges (no CAUSED), never the tool's own deltas."""
    rel = {r["key"]: r["n"] for r in PROD["relationships"] if r["key"] in ("MENTIONS", "CROSS_REFERENCES")}
    rel.update(W1_BY_TYPE)
    ee = dict(W1_BY_EE_KEY)
    if extra_edge:
        ee["VISITED phase=4 source=llm"] += 1
        rel["VISITED"] += 1
    return {"relationships": rel, "ee_edges": ee}


@pytest.mark.parametrize("extra_edge", [False, True], ids=["as-expected", "one-edge-more"])
def test_fragment_parses_with_diff_kg_load_allowlist(tmp_path, prod, extra_edge):
    """The fragment loads with diff_kg, allows exactly the expected diff, uses every entry,
    and still refuses one edge more than expected."""
    report = write_reference(tmp_path)
    assert run(tmp_path, report, edge_set_sha(report)) == 0
    allow = dk.load_allowlist(tmp_path / "relations_allow.yaml")
    a = dk.read_profile(prod.driver)
    b = _staging_profile(extra_edge)

    diffs = [d for section in ("relationships", "ee_edges") for d in dk.diff_counts(section, a[section], b[section])]
    classified, unused = dk.classify(diffs, allow)

    refused = [d["key"] for d in classified if d["allowed_by"] is None]
    assert refused == (["VISITED", "VISITED phase=4 source=llm"] if extra_edge else [])
    assert unused == []


def test_w1_key_without_source_exits_2(tmp_path, prod, capsys):
    """The glob over source=- keys has no bound, so a W1 edge without a source would hide behind it."""
    rows = [dict(r, source=None) if r["relation"] == "VISITED" else r for r in ROWS]
    report = write_reference(tmp_path, rows)

    assert run(tmp_path, report, edge_set_sha(report)) == 2

    assert prod.resolved == [] and not (tmp_path / "relations_allow.yaml").exists()
    assert "VISITED phase=4 source=-" in capsys.readouterr().err


def test_report_that_does_not_describe_its_file_exits_2(tmp_path, prod, capsys):
    report = write_reference(tmp_path)
    clean = tmp_path / "relations_clean.jsonl"
    clean.write_bytes(clean.read_bytes().replace(b"place:xinai", b"place:xiyan"))

    assert run(tmp_path, report, edge_set_sha(report)) == 2

    assert prod.resolved == [] and not (tmp_path / "relations_expected.json").exists()
    assert "output.sha256" in capsys.readouterr().err


def test_report_whose_by_type_does_not_sum_its_by_ee_key_exits_2(tmp_path, prod, capsys):
    """by_type is not in the clean file or the claim check_edge_set checks, so the tool sums it itself."""
    report = write_reference(tmp_path)
    doc = json.loads(report.read_text(encoding="utf-8"))
    doc["expected_after_10_2"]["by_type"]["VISITED"] += 1
    report.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert run(tmp_path, report, edge_set_sha(report)) == 2

    assert prod.resolved == [] and not (tmp_path / "relations_expected.json").exists()
    assert not (tmp_path / "relations_allow.yaml").exists()
    assert "does not sum its by_ee_key" in capsys.readouterr().err


def test_out_and_allow_out_on_one_path_is_a_usage_error(tmp_path, prod):
    report = write_reference(tmp_path)
    same = tmp_path / "relations_expected.json"

    with pytest.raises(SystemExit) as e:
        rx.main(["--report", str(report), "--expect-edge-set-sha", edge_set_sha(report),
                 "--out", str(same), "--allow-out", str(same)])

    assert e.value.code == 2 and prod.resolved == [] and not same.exists()


@pytest.mark.parametrize("section, key", [("relationships", "A[1]"), ("ee_edges", "SON_OF phase=* source=llm"),
                                          ("ee_edges", "SON_OF phase=? source=llm")])
def test_exact_entry_with_a_glob_character_cannot_be_made(section, key):
    """An exact delta keyed by a glob would allow every key it matches."""
    delta = {"relationships": {}, "ee_edges": {}}
    delta[section][key] = 1

    with pytest.raises(rx.CannotCheck, match="is a glob"):
        rx.allow_entries(delta, "tag", "prod")


def test_unreadable_target_exits_2_and_writes_nothing(tmp_path, prod, monkeypatch, capsys):
    def refuse(name):
        raise ValueError("--target prod refused: shell NEO4J_URI=bolt://localhost:7688 differs")
    monkeypatch.setattr(rx, "resolve_shell_target", refuse)
    report = write_reference(tmp_path)

    assert run(tmp_path, report, edge_set_sha(report)) == 2

    assert not (tmp_path / "relations_expected.json").exists()
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("sha", ["abc", "G" * 64, "A" * 64])
def test_expect_sha_must_be_64_lowercase_hex(tmp_path, prod, sha):
    with pytest.raises(SystemExit) as e:
        run(tmp_path, write_reference(tmp_path), sha)
    assert e.value.code == 2 and prod.resolved == []


def test_target_is_resolved_from_the_shell_not_from_dotenv():
    """relations_expect imports relation_postprocess (through check_edge_set), whose
    entity_extraction import copies .env into os.environ. The a target must still be
    judged on the shell the tool started in: --a staging resolves to the staging default."""
    if not (ROOT / ".env").exists():
        pytest.skip("no .env: load_dotenv has nothing to copy, so there is nothing to guard against")
    store_keys = ("NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION", "KG_TARGET")
    env = {k: v for k, v in os.environ.items() if k not in store_keys}
    code = ("from scripts.tools import relations_expect as r; import os; "
            "assert 'NEO4J_URI' in os.environ, 'load_dotenv did not run: the test proves nothing'; "
            "print(r.resolve_shell_target('staging').neo4j_uri)")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "bolt://localhost:7688"
