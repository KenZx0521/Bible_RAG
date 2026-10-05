"""W1 residual expectations (scripts/tools/residuals_expect.py, batch 1A-T5): the
per-entity mention_count residuals, the per-property MENTIONS residual and R1, read while
staging still holds the batch-0 build; and --check, which re-reads the MENTIONS residual
of the W1 staging at R2 against the registered file.

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


def _mention(label: str, sid: str, eid: str, **props) -> dict:
    return {"source_label": label, "source_id": sid, "entity_id": eid, "props": props}


# the batch-0 pattern: a source_granularity on every non-curated staging edge; the backfilled prod
# edges carry backfilled/verse_mention_freq but no position; the manual patch gains created_from
PROD_MENTIONS = [
    _mention("Pericope", "mat_005_001", "event:shanshangbaoxun", text_span="山上", start_pos=0, end_pos=2),
    _mention("Pericope", "exo_018_001", "person:yeteluo", text_span="葉忒羅", backfilled=True,
             source_granularity="verse", verse_mention_freq=1),
    _mention("Chunk", "exo_018_001", "person:yeteluo", text_span="葉忒羅", start_pos=4, end_pos=7),
    _mention("Pericope", "act_009_001", "event:jinniudushijian", source="manual_patch", curated=True),
    _mention("Pericope", "mrk_001_001", "person:make", text_span="馬可", start_pos=1, end_pos=3,
             source_granularity="verse"),
]
STAGING_MENTIONS = [
    _mention("Pericope", "mat_005_001", "event:shanshangbaoxun", text_span="山上", start_pos=0, end_pos=2,
             source_granularity="pericope"),
    _mention("Pericope", "exo_018_001", "person:yeteluo", text_span="葉忒羅", start_pos=10, end_pos=13,
             source_granularity="verse"),
    _mention("Chunk", "exo_018_001", "person:yeteluo", text_span="葉忒羅", start_pos=4, end_pos=7,
             source_granularity="chunk"),
    _mention("Pericope", "act_009_001", "event:jinniudushijian", source="manual_patch", curated=True,
             created_from="manual_patch"),
    _mention("Pericope", "mrk_001_001", "person:make", text_span="馬可", start_pos=1, end_pos=3,
             source_granularity="verse"),
]
EXPECTED_MENTIONS = {"edges": {"a": 5, "b": 5}, "only_a": 0, "only_b": 0,
                     "differing": {"backfilled": 1, "created_from": 1, "end_pos": 1, "source_granularity": 2,
                                   "start_pos": 1, "verse_mention_freq": 1}}


class FakeDriver:
    def __init__(self, name: str):
        self.name, self.closed = name, False

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def graphs(monkeypatch):
    """Two fake targets: entity rows, the count of semantic edges carrying a source, MENTIONS rows."""
    state = SimpleNamespace(entities={"prod": PROD, "staging": STAGING}, sourced={"prod": 0, "staging": 0},
                            mentions={"prod": PROD_MENTIONS, "staging": STAGING_MENTIONS},
                            opened=[], drivers=[], queries=[])

    def open_neo4j(target):
        state.opened.append(target.name)
        state.drivers.append(FakeDriver(target.name))
        return state.drivers[-1]

    def read_query(driver, cypher, **params):
        state.queries.append(cypher)
        if cypher == dk.PROFILE_QUERIES["entities"]:
            return [dict(r) for r in state.entities[driver.name]]
        if cypher == rx.SOURCED_EDGES_CYPHER:
            return [{"n": state.sourced[driver.name]}]
        assert cypher == rx.MENTIONS_CYPHER
        return [dict(r, props=dict(r["props"])) for r in state.mentions[driver.name]]

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


# --- MENTIONS properties (plan §2.1: the batch-0 residual diff_kg cannot see) ----

def test_mentions_props_counted_per_property_from_fake_reads(tmp_path, graphs, capsys):
    assert run(tmp_path) == 0

    assert _expected(tmp_path)["mentions_props"] == EXPECTED_MENTIONS
    out = capsys.readouterr().out
    assert "MENTIONS: 5 -> 5 edges, only a 0, only b 0" in out
    assert "source_granularity 2" in out and "created_from 1" in out


def test_mention_edges_on_one_side_only_are_counted_not_compared(tmp_path, graphs):
    """An edge only in a or only in b has no property to compare; it is counted as such."""
    graphs.mentions["staging"] = STAGING_MENTIONS[:-1] + [
        _mention("Pericope", "mrk_001_002", "person:make", text_span="馬可", source_granularity="verse")]

    assert run(tmp_path) == 0

    assert _expected(tmp_path)["mentions_props"] == dict(EXPECTED_MENTIONS, only_a=1, only_b=1)


def test_mention_key_read_twice_exits_2(tmp_path, graphs, capsys):
    """(source label, source id, entity_id) must name one edge; a Chunk and a Pericope may share an id."""
    graphs.mentions["staging"] = STAGING_MENTIONS + [STAGING_MENTIONS[1]]

    assert run(tmp_path) == 2

    assert _nothing_written(tmp_path)
    assert "exo_018_001" in capsys.readouterr().err


def check(registered: Path, *extra: str) -> int:
    return rx.main(["--a", "prod", "--b", "staging", "--check", str(registered), *extra])


def _w1_staging(graphs) -> None:
    """After W1 step 2: b holds 1A's semantic edges; MENTIONS and entities are what batch 0 left."""
    graphs.sourced["staging"] = 5616
    graphs.opened.clear()
    graphs.queries.clear()


def test_check_passes_on_a_w1_staging_that_keeps_the_registered_residual(tmp_path, graphs, capsys):
    assert run(tmp_path) == 0
    registered = tmp_path / "residuals_expected.json"
    before = registered.read_bytes()
    _w1_staging(graphs)
    capsys.readouterr()

    assert check(registered) == 0

    assert registered.read_bytes() == before and not (tmp_path / "bak").exists()
    assert graphs.opened == ["prod", "staging"] and all(d.closed for d in graphs.drivers)
    assert graphs.queries == [rx.MENTIONS_CYPHER, rx.MENTIONS_CYPHER]   # MENTIONS only, both sides
    out = capsys.readouterr().out
    assert str(registered) in out and "source_granularity 2" in out


@pytest.mark.parametrize("change", ["property-dropped", "property-added", "edge-added", "edge-gone"])
def test_check_exits_1_naming_each_differing_field(tmp_path, graphs, change, capsys):
    assert run(tmp_path) == 0
    _w1_staging(graphs)
    staging = [dict(m, props=dict(m["props"])) for m in STAGING_MENTIONS]
    if change == "property-dropped":       # the manual patch lost created_from: 1 -> 0
        del staging[3]["props"]["created_from"]
    elif change == "property-added":       # a field batch 0 did not touch now differs
        staging[4]["props"]["text_span"] = "馬可福音"
    elif change == "edge-added":
        staging.append(_mention("Pericope", "mrk_001_002", "person:make", text_span="馬可"))
    else:
        staging = staging[:-1]
    graphs.mentions["staging"] = staging
    capsys.readouterr()

    assert check(tmp_path / "residuals_expected.json") == 1

    err = capsys.readouterr().err
    expected = {"property-dropped": ["differing.created_from: registered 1, now 0"],
                "property-added": ["differing.text_span: registered 0, now 1"],
                "edge-added": ["edges.b: registered 5, now 6", "only_b: registered 0, now 1"],
                "edge-gone": ["edges.b: registered 5, now 4", "only_a: registered 0, now 1"]}[change]
    assert all(line in err for line in expected), err
    assert "MISMATCH" in err and "source_granularity" not in err


def _registered(tmp_path: Path, broken: str) -> Path:
    path = tmp_path / "registered.json"
    if broken == "missing":
        return path
    if broken == "not-json":
        path.write_text("{", encoding="utf-8")
        return path
    assert run(tmp_path) == 0
    doc = _expected(tmp_path)
    if broken == "no-mentions-props":      # a file written before mentions_props existed
        del doc["mentions_props"]
    elif broken == "count-not-integer":
        doc["mentions_props"]["differing"]["created_from"] = "106"
    elif broken == "other-uri":            # registered against another staging than this run resolves
        doc["basis"]["b"]["neo4j_uri"] = "bolt://localhost:7689"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.mark.parametrize("broken", ["missing", "not-json", "no-mentions-props", "count-not-integer", "other-uri"])
def test_check_on_a_bad_registered_file_exits_2_before_any_read(tmp_path, graphs, broken, capsys):
    registered = _registered(tmp_path, broken)
    graphs.opened.clear()

    assert check(registered) == 2

    assert graphs.opened == []
    assert "CANNOT CHECK" in capsys.readouterr().err


def test_check_on_an_unreadable_target_exits_2(tmp_path, graphs, monkeypatch, capsys):
    assert run(tmp_path) == 0

    def refuse(target):
        raise OSError(f"connection to {target.neo4j_uri} refused")
    monkeypatch.setattr(rx, "open_neo4j", refuse)

    assert check(tmp_path / "residuals_expected.json") == 2

    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["--check", "r.json", "--out", "x.json"],              # --check writes nothing
    ["--check", "r.json", "--validate-a", "v.json"],       # and reads no report
    ["--validate-a", "a.json", "--validate-b", "b.json", "--out", "x.json"],   # generating needs all four
])
def test_check_and_generate_flags_do_not_mix(argv, graphs):
    with pytest.raises(SystemExit) as exc:
        rx.main(argv)

    assert exc.value.code == 2 and graphs.opened == []
