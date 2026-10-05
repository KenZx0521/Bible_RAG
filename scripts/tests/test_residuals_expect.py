"""W1 residual expectations (scripts/tools/residuals_expect.py, batch 1A-T5): the
per-entity mention_count residuals and R1, read while staging still holds the batch-0 build.

Both targets are fakes: read_query answers the tool's own statements from per-target
rows, and the entity rows are diff_kg's PROFILE_QUERIES["entities"] rows, so the
fragment is checked against diff_kg.diff_entities as R2 will run it. The validate_kg
files are written in validate_kg --json's shape.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.tools import diff_kg as dk
from scripts.tools import residuals_expect as rx

URIS = {"prod": "bolt://localhost:7687", "staging": "bolt://localhost:7688"}


def _entity(eid: str, mention_count, aliases=None) -> dict:
    return {"entity_id": eid, "description": f"{eid} 的描述", "aliases": aliases or [], "mention_count": mention_count}


PROD = [_entity("event:shanshangbaoxun", 23), _entity("person:yeteluo", 3), _entity("person:make", 794),
        _entity("place:dan", 22), _entity("event:jinniudushijian", 5)]
# batch-0 staging: two mention_count residuals; an aliases difference is diff_kg's aliases section, not this tool's
STAGING = [_entity("event:shanshangbaoxun", 1), _entity("person:yeteluo", 30, aliases=["流珥"]),
           _entity("person:make", 794), _entity("place:dan", 22), _entity("event:jinniudushijian", 5)]
EXPECTED = {"event:shanshangbaoxun": {"a": 23, "b": 1, "delta": -22},
            "person:yeteluo": {"a": 3, "b": 30, "delta": 27}}


class FakeDriver:
    def __init__(self, name: str):
        self.name, self.closed = name, False

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def graphs(monkeypatch):
    """Two fake targets: entity rows and the count of semantic edges carrying a source."""
    state = SimpleNamespace(entities={"prod": PROD, "staging": STAGING}, sourced={"prod": 0, "staging": 0},
                            opened=[], drivers=[])

    def open_neo4j(target):
        state.opened.append(target.name)
        state.drivers.append(FakeDriver(target.name))
        return state.drivers[-1]

    def read_query(driver, cypher, **params):
        if cypher == dk.PROFILE_QUERIES["entities"]:
            return [dict(r) for r in state.entities[driver.name]]
        assert cypher == rx.SOURCED_EDGES_CYPHER
        return [{"n": state.sourced[driver.name]}]

    monkeypatch.setattr(rx, "resolve_target", lambda name: SimpleNamespace(name=name, neo4j_uri=URIS[name]))
    monkeypatch.setattr(rx, "open_neo4j", open_neo4j)
    monkeypatch.setattr(rx, "read_query", read_query)
    monkeypatch.setattr(rx, "git_head", lambda: "0123456789abcdef0123456789abcdef01234567")
    return state


def validate_json(tmp_path: Path, name: str, r1, origin: str | None = None, checks: dict | None = None) -> Path:
    """A validate_kg --live --json report whose R1 reads `r1`."""
    r1_check = {"title": "MENTIONS whose first position falls in the book-name region", "severity": "record",
                "metrics": {"book_region_mentions": {"value": r1, "baseline": 1938, "target": 0,
                                                     "direction": "down", "status": "ok"}},
                "detail": {}, "samples": [], "status": "ok"}
    doc = {"origin": origin or f"live:{name} ({URIS[name]})", "baseline": "config/kg_quality_baseline",
           "partial": [], "exit_code": 1, "failures": ["H11"], "hard_failures": ["H11"], "regressions": [],
           "checks": {"R1": r1_check} if checks is None else checks}
    path = tmp_path / f"validate_{name}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run(tmp_path: Path, va: Path | None = None, vb: Path | None = None) -> int:
    va = va or validate_json(tmp_path, "prod", 1938)
    vb = vb or validate_json(tmp_path, "staging", 2124)
    return rx.main(["--a", "prod", "--b", "staging", "--validate-a", str(va), "--validate-b", str(vb),
                    "--out", str(tmp_path / "residuals_expected.json"),
                    "--allow-out", str(tmp_path / "residuals_allow.yaml")])


def _expected(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "residuals_expected.json").read_text(encoding="utf-8"))


def _nothing_written(tmp_path: Path) -> bool:
    return not any((tmp_path / name).exists() for name in ("residuals_expected.json", "residuals_allow.yaml"))


def test_mention_count_diff_from_fake_reads(tmp_path, graphs, capsys):
    assert run(tmp_path) == 0

    entries = dk.load_allowlist(tmp_path / "residuals_allow.yaml")
    assert [(e["section"], e["key"], e["delta"]) for e in entries] == [
        ("mention_count", eid, d["delta"]) for eid, d in EXPECTED.items()]
    assert all(e["reason"].startswith("1A ") for e in entries)
    doc = _expected(tmp_path)
    assert doc["mention_count"] == EXPECTED
    assert graphs.opened == ["prod", "staging"] and all(d.closed for d in graphs.drivers)
    basis = doc["basis"]
    assert basis["a"] == {"target": "prod", "neo4j_uri": URIS["prod"], "entities": 5, "sourced_semantic_edges": 0}
    assert basis["b"] == {"target": "staging", "neo4j_uri": URIS["staging"], "entities": 5,
                          "sourced_semantic_edges": 0}
    assert basis["git_head"] == "0123456789abcdef0123456789abcdef01234567"
    assert basis["at"] and basis["premise"]
    out = capsys.readouterr().out
    assert "2 of 5 entities differ" in out and "event:shanshangbaoxun 23 -> 1 (-22)" in out


def test_r1_taken_from_validate_json(tmp_path, graphs):
    va, vb = validate_json(tmp_path, "prod", 1938), validate_json(tmp_path, "staging", 2124)

    assert run(tmp_path, va, vb) == 0

    doc = _expected(tmp_path)
    assert doc["validate_kg"] == {"R1": {"a": 1938, "b": 2124}}
    assert doc["basis"]["validate_kg"] == {
        side: {"origin": f"live:{name} ({URIS[name]})", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for side, name, path in (("a", "prod", va), ("b", "staging", vb))}


@pytest.mark.parametrize("broken", ["other-target", "snapshot", "no-r1", "r1-not-measured"])
def test_validate_json_not_this_targets_live_r1_exits_2(tmp_path, graphs, broken, capsys):
    """R1 comes from validate_kg itself, on the very target this tool reads; decided before any read."""
    vb = {"other-target": lambda: validate_json(tmp_path, "staging", 2124, origin=f"live:prod ({URIS['prod']})"),
          "snapshot": lambda: validate_json(tmp_path, "staging", 2124, origin="snapshot:output/kg"),
          "no-r1": lambda: validate_json(tmp_path, "staging", 2124, checks={}),
          "r1-not-measured": lambda: validate_json(tmp_path, "staging", None)}[broken]()

    assert run(tmp_path, vb=vb) == 2

    assert graphs.opened == [] and _nothing_written(tmp_path)
    assert "validate_staging.json" in capsys.readouterr().err


@pytest.mark.parametrize("change", ["only-in-b", "only-in-a"])
def test_unequal_entity_sets_exit_1(tmp_path, graphs, change, capsys):
    """The premise: W1 changes no entity, so both sides must hold the same entity ids."""
    if change == "only-in-b":
        graphs.entities["staging"] = STAGING + [_entity("person:liuer", 1)]
    else:
        graphs.entities["staging"] = STAGING[:-1]

    assert run(tmp_path) == 1

    assert _nothing_written(tmp_path)
    err = capsys.readouterr().err
    assert ("person:liuer" if change == "only-in-b" else "event:jinniudushijian") in err


def test_b_that_holds_1a_semantic_edges_exits_2(tmp_path, graphs, capsys):
    """Read after W1 step 2, b is the W1 build: a residual read off it would certify itself (plan §3)."""
    graphs.sourced["staging"] = 5616

    assert run(tmp_path) == 2

    assert _nothing_written(tmp_path)
    assert "batch-0" in capsys.readouterr().err


def test_differing_mention_count_that_is_not_a_number_exits_2(tmp_path, graphs, capsys):
    """diff_kg reports null vs a number with no delta: no exact entry could allow it."""
    graphs.entities["staging"] = [dict(r, mention_count=None) if r["entity_id"] == "place:dan" else r
                                  for r in STAGING]

    assert run(tmp_path) == 2

    assert _nothing_written(tmp_path)
    assert "place:dan" in capsys.readouterr().err


def test_unreadable_target_exits_2_and_writes_nothing(tmp_path, graphs, monkeypatch, capsys):
    def refuse(name):
        raise ValueError(f"--target {name} refused: KG_TARGET=staging is exported")
    monkeypatch.setattr(rx, "resolve_target", refuse)

    assert run(tmp_path) == 2

    assert _nothing_written(tmp_path)
    assert "refused" in capsys.readouterr().err


def _merged_diff(a_rows: list[dict], b_rows: list[dict]) -> list[dict]:
    """diff_kg's entity differences of b against a, as compare() computes them."""
    by_id = lambda rows: {r["entity_id"]: r for r in rows}  # noqa: E731
    return dk.diff_entities(by_id(a_rows), by_id(b_rows))


@pytest.mark.parametrize("w1_staging", ["as-batch-0", "one-mention-more"])
def test_fragment_allows_exactly_diff_kg_mention_count(tmp_path, graphs, w1_staging):
    """The fragment loads with diff_kg, joins another fragment without overlap, allows exactly
    the residuals, uses every entry, and still refuses a W1 staging one mention off."""
    assert run(tmp_path) == 0
    relations = tmp_path / "relations_allow.yaml"
    relations.write_text(dk.render_allowlist(
        [{"section": "relationships", "key": "FATHER_OF", "delta": -2, "reason": "1A test"}], ["test"]),
        encoding="utf-8")
    merged, counts = dk.merge_allowlists([relations, tmp_path / "residuals_allow.yaml"])
    allow = dk.parse_allowlist(merged, "merged")
    w1 = STAGING if w1_staging == "as-batch-0" else [
        dict(r, mention_count=31) if r["entity_id"] == "person:yeteluo" else r for r in STAGING]

    classified, unused = dk.classify([d for d in _merged_diff(PROD, w1) if d["section"] == "mention_count"], allow)

    assert counts == [1, 2]
    assert [d["key"] for d in classified if d["allowed_by"] is None] == (
        [] if w1_staging == "as-batch-0" else ["person:yeteluo"])
    assert [e["section"] for e in unused] == (["relationships"] if w1_staging == "as-batch-0"
                                              else ["relationships", "mention_count"])


def test_fragment_bytes_do_not_depend_on_the_run(tmp_path, graphs, monkeypatch):
    """Only basis.at (when b was read) may change between two runs over the same graphs."""
    monkeypatch.setattr(rx, "now", lambda: "2026-10-05T23:00:00+08:00")
    assert run(tmp_path) == 0
    fragment, first = (tmp_path / "residuals_allow.yaml").read_bytes(), _expected(tmp_path)
    monkeypatch.setattr(rx, "now", lambda: "2026-10-05T23:59:59+08:00")

    assert run(tmp_path) == 0

    assert (tmp_path / "residuals_allow.yaml").read_bytes() == fragment
    second = _expected(tmp_path)
    assert second["basis"].pop("at") != first["basis"].pop("at") and second == first
