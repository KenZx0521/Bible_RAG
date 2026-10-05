"""diff_kg: live vs staging comparison for the batch-0 R2 gate (docs/build_database.md R2).

Every read goes through a fake Neo4j driver that answers diff_kg's own
profile queries and export_event_registry's anchor query, and records the
access mode of each session: the tool must never open a write session.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from neo4j import READ_ACCESS

from scripts.tools import diff_kg as dk


class FakeRecord(dict):
    def data(self) -> dict:
        return dict(self)


class FakeDriver:
    """Answers diff_kg.PROFILE_QUERIES from `rows` and the registry anchor query
    from `anchors(event_id) -> list[str]`."""

    def __init__(self, rows: dict, anchors=lambda eid: ["gen:1:0"]):
        self.rows, self.anchors, self.sessions, self.closed = rows, anchors, [], False

    def answer(self, cypher: str, params: dict) -> list[FakeRecord]:
        for name, query in dk.PROFILE_QUERIES.items():
            if cypher == query:
                return [FakeRecord(r) for r in self.rows.get(name, [])]
        if "UNWIND $ids" in cypher:
            return [FakeRecord(id=eid, name="甲事件", aliases=[], anchors=self.anchors(eid))
                    for eid in params["ids"]]
        raise AssertionError(f"unexpected query: {cypher[:80]}")

    def session(self, **kwargs):
        self.sessions.append(kwargs)
        driver = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def run(self, cypher, **params):
                return driver.answer(cypher, params)

            def execute_read(self, fn):
                return fn(SimpleNamespace(run=lambda cypher, **params: driver.answer(cypher, params)))

            def execute_write(self, fn):
                raise AssertionError("diff_kg must never write")
        return Session()

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def profile(**over) -> dict:
    rows = {
        "labels": [{"key": "Entity", "n": 3}, {"key": "Person", "n": 2}, {"key": "Event", "n": 1}],
        "relationships": [{"key": "FATHER_OF", "n": 10}, {"key": "MENTIONS", "n": 50}],
        "ee_edges": [{"type": "FATHER_OF", "phase": 4, "source": None, "n": 7},
                     {"type": "FATHER_OF", "phase": 3, "source": "prior", "n": 3}],
        "mentions": [{"source_label": "Pericope", "source": None, "n": 45},
                     {"source_label": "Chunk", "source": "manual_patch", "n": 5}],
        "xrefs": [{"source": "tsk", "n": 100}, {"source": "markdown", "n": 4}],
        "xref_provenance": [{"source": "tsk", "curated": None, "tsk": None, "n": 100},
                            {"source": "markdown", "curated": None, "tsk": None, "n": 4}],
        "entities": [{"entity_id": "person:yabolahan", "description": "信心之父", "aliases": ["亞伯蘭"]},
                     {"entity_id": "person:yisa", "description": None, "aliases": None},
                     {"entity_id": "event:xianyisa", "description": "獻以撒", "aliases": ["甲", "乙"]}],
    }
    rows.update(over)
    return rows


def keys(diffs: list[dict], section: str) -> list[str]:
    return [d["key"] for d in diffs if d["section"] == section]


# ---------------------------------------------------------------------------
# profile diff
# ---------------------------------------------------------------------------

def test_identical_targets_have_no_differences():
    diffs, errors = dk.compare(FakeDriver(profile()), FakeDriver(profile()), with_registry=False)
    assert diffs == [] and errors == []


def test_count_sections_report_each_changed_key_with_its_delta():
    b = profile(ee_edges=[{"type": "FATHER_OF", "phase": 4, "source": None, "n": 9},
                          {"type": "FATHER_OF", "phase": 3, "source": "prior", "n": 3},
                          {"type": "OCCURRED_IN", "phase": 5, "source": "cooccurrence", "n": 2}],
                mentions=[{"source_label": "Pericope", "source": None, "n": 45}],
                xrefs=[{"source": "tsk", "n": 99}, {"source": "markdown", "n": 4}],
                labels=[{"key": "Entity", "n": 3}, {"key": "Person", "n": 2}])
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(b), with_registry=False)
    by_key = {(d["section"], d["key"]): d for d in diffs}
    assert by_key[("ee_edges", "FATHER_OF phase=4 source=-")]["delta"] == 2
    assert by_key[("ee_edges", "OCCURRED_IN phase=5 source=cooccurrence")]["delta"] == 2
    assert by_key[("mentions", "Chunk source=manual_patch")]["delta"] == -5
    assert by_key[("xrefs", "source=tsk")]["delta"] == -1
    assert by_key[("labels", "Event")]["delta"] == -1
    assert keys(diffs, "relationships") == []


def flagged_xrefs() -> list[dict]:
    """Staging-style provenance: every edge carries curated and tsk (Steps 5 and 9, 1B)."""
    return [{"source": "markdown", "curated": True, "tsk": True, "n": 3},
            {"source": "markdown", "curated": True, "tsk": False, "n": 1},
            {"source": "tsk", "curated": False, "tsk": True, "n": 100}]


def test_xref_provenance_keys_and_delta():
    # prod-style rows (curated and tsk unset) against staging-style rows: same edges per source
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(profile(xref_provenance=flagged_xrefs())),
                          with_registry=False)
    assert {d["key"]: d["delta"] for d in diffs if d["section"] == "xref_provenance"} == {
        "source=markdown curated=- tsk=-": -4, "source=tsk curated=- tsk=-": -100,
        "source=markdown curated=True tsk=True": 3, "source=markdown curated=True tsk=False": 1,
        "source=tsk curated=False tsk=True": 100}
    assert keys(diffs, "xrefs") == []  # the per-source totals did not move


def test_xref_provenance_matches_the_xref_probe_expect_keys():
    # xref_probe fingerprint --expect compares these keys, so both must read and spell them alike
    from scripts.tools import xref_projection as xproj
    assert dk.PROFILE_QUERIES["xref_provenance"].split() == xproj.PROVENANCE_CYPHER.split()
    for row in flagged_xrefs() + profile()["xref_provenance"]:
        assert dk._COUNT_KEYS["xref_provenance"](row) == xproj.provenance_key(row["source"], row["curated"], row["tsk"])


def test_descriptions_compare_verbatim_and_aliases_as_sets():
    b = profile(entities=[
        {"entity_id": "person:yabolahan", "description": "信心之父 ", "aliases": "[\"亞伯蘭\"]"},
        {"entity_id": "person:yisa", "description": "", "aliases": []},       # None == empty
        {"entity_id": "event:xianyisa", "description": "獻以撒", "aliases": ["乙", "甲"]},  # same set
        {"entity_id": "person:new", "description": None, "aliases": []}])
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(b), with_registry=False)
    assert keys(diffs, "descriptions") == ["person:yabolahan"]   # a trailing space counts
    assert keys(diffs, "aliases") == ["person:yabolahan"]        # a JSON string is not the list
    assert keys(diffs, "entity_ids") == ["person:new"]


def test_profile_reads_use_read_sessions_only():
    a, b = FakeDriver(profile()), FakeDriver(profile())
    dk.compare(a, b, with_registry=False)
    assert a.sessions and all(s.get("default_access_mode") == READ_ACCESS for s in a.sessions + b.sessions)


# ---------------------------------------------------------------------------
# event registry
# ---------------------------------------------------------------------------

def registry(*events, dropped=()):
    return {"version": 1, "events": list(events), "dropped": list(dropped)}


def event(eid, anchors=("gen:1:0",), triggers=("甲",)):
    return {"id": eid, "name": eid, "provenance": "manual_patch", "triggers": list(triggers), "anchors": list(anchors)}


def test_registry_diff_names_changed_and_one_sided_events():
    a = registry(event("event:a"), event("event:b"))
    b = registry(event("event:a", anchors=("gen:2:0",)), event("event:c"),
                 dropped=[{"id": "event:b", "name": "b", "reason": "no anchors"}])
    diffs = dk.diff_registry(a, b)
    by_key = {d["key"]: d for d in diffs}
    assert set(by_key) == {"event:a", "event:b", "event:c", "dropped:event:b"}
    assert by_key["event:a"]["fields"] == ["anchors"]
    assert by_key["event:b"]["b"] is None


def test_registry_is_built_from_each_driver_read_only(monkeypatch):
    # the real build_registry (curated ids, book order from output/books.jsonl); only the triggers are faked
    import export_event_registry as eer
    monkeypatch.setattr(eer, "event_keywords", lambda: {"甲事件"})
    monkeypatch.setattr(eer, "get_neo4j", lambda: pytest.fail("build_registry must use the driver it is given"))
    moved = sorted(eer.curated_event_ids())[0]
    a = FakeDriver(profile())
    b = FakeDriver(profile(), anchors=lambda eid: ["exo:1:0"] if eid == moved else ["gen:1:0"])

    diffs, errors = dk.compare(a, b)
    assert errors == []
    assert keys(diffs, "registry") == [moved]
    assert not a.closed and not b.closed  # diff_kg owns closing the real drivers
    assert all(s.get("default_access_mode") == READ_ACCESS for s in a.sessions + b.sessions)


def test_registry_build_failure_is_an_error_not_a_pass():
    a, b = FakeDriver(profile()), FakeDriver(profile())

    def broken(driver):
        raise RuntimeError("curated events missing from Neo4j: ['event:shounanzhou']")
    diffs, errors = dk.compare(a, b, registry_builder=broken)
    assert errors and "curated events missing" in errors[0]


# ---------------------------------------------------------------------------
# allow list
# ---------------------------------------------------------------------------

def write_allow(tmp_path, entries) -> str:
    path = tmp_path / "allow.yaml"
    path.write_text(json.dumps({"version": 1, "allow": entries}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_allow_entries_match_by_section_glob_and_delta(tmp_path):
    diffs = [{"section": "ee_edges", "key": "OCCURRED_IN phase=5 source=cooccurrence", "a": 0, "b": 2, "delta": 2},
             {"section": "ee_edges", "key": "FATHER_OF phase=4 source=-", "a": 7, "b": 9, "delta": 2},
             {"section": "mentions", "key": "Pericope source=-", "a": 45, "b": 40, "delta": -5},
             {"section": "descriptions", "key": "place:x", "a": "x", "b": "", "delta": None}]
    allow = dk.load_allowlist(write_allow(tmp_path, [
        {"section": "ee_edges", "key": "* phase=5 *", "delta": 2, "reason": "10.3 co-occurrence"},
        {"section": "mentions", "key": "Pericope *", "max_abs_delta": 3, "reason": "too small"},
        {"section": "descriptions", "key": "place:*", "reason": "rewritten on purpose"},
        {"section": "xrefs", "key": "source=tsk", "reason": "never used"}]))
    classified, unused = dk.classify(diffs, allow)
    allowed = {d["key"]: d["allowed_by"] for d in classified}
    assert allowed == {"OCCURRED_IN phase=5 source=cooccurrence": "10.3 co-occurrence",
                       "FATHER_OF phase=4 source=-": None, "Pericope source=-": None,
                       "place:x": "rewritten on purpose"}
    assert [e["key"] for e in unused] == ["Pericope *", "source=tsk"]


def test_xref_provenance_allow_entry_matches(tmp_path):
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(profile(xref_provenance=flagged_xrefs())),
                          with_registry=False)
    allow = dk.load_allowlist(write_allow(tmp_path, [
        {"section": "xref_provenance", "key": "source=* curated=- tsk=-", "reason": "Steps 5 and 9 flag every edge"},
        {"section": "xref_provenance", "key": "source=markdown curated=True tsk=True", "delta": 3, "reason": "TSK"},
        {"section": "xref_provenance", "key": "source=markdown curated=True tsk=False", "delta": 2, "reason": "no"},
        {"section": "xref_provenance", "key": "source=tsk curated=False tsk=True", "max_abs_delta": 100,
         "reason": "pure TSK"}]))
    classified, unused = dk.classify(diffs, allow)
    allowed = {d["key"]: d["allowed_by"] for d in classified if d["section"] == "xref_provenance"}
    assert allowed == {"source=markdown curated=- tsk=-": "Steps 5 and 9 flag every edge",
                       "source=tsk curated=- tsk=-": "Steps 5 and 9 flag every edge",
                       "source=markdown curated=True tsk=True": "TSK",
                       "source=markdown curated=True tsk=False": None,  # delta 1, not 2
                       "source=tsk curated=False tsk=True": "pure TSK"}
    assert [e["reason"] for e in unused] == ["no"]


@pytest.mark.parametrize("entry", [
    {"section": "ee_edges", "key": "*"},                                   # no reason
    {"section": "nodes", "key": "*", "reason": "r"},                       # unknown section
    {"section": "descriptions", "key": "*", "delta": 1, "reason": "r"},    # delta on a non-count section
    {"section": "ee_edges", "key": "FATHER_OF *", "max_delta": 2, "reason": "r"},  # misspelt bound
    {"section": "ee_edges", "key": "*", "detla": 2, "reason": "r"},       # misspelt bound
    {"section": "ee_edges", "key": "*", "delta": "2", "reason": "r"},      # delta not an int
    {"section": "ee_edges", "key": "*", "delta": True, "reason": "r"},     # a bool is not a delta
    {"section": "ee_edges", "key": "*", "delta": 2.5, "reason": "r"},
    {"section": "ee_edges", "key": "*", "max_abs_delta": "3", "reason": "r"},
    {"section": "ee_edges", "key": "*", "max_abs_delta": -1, "reason": "r"},
    {"section": "ee_edges", "key": "*", "max_abs_delta": False, "reason": "r"},
    {"section": "ee_edges", "key": "*", "delta": 1, "max_abs_delta": 3, "reason": "r"},  # two bounds
    {"section": "ee_edges", "key": 7, "reason": "r"},                      # key not a glob string
    {"section": "ee_edges", "key": "*", "reason": ["r"]},                  # reason not a string
    {"section": "ee_edges", "key": "*", "reason": "  "},                   # blank reason
    "ee_edges *",                                                          # not a mapping
])
def test_allow_entries_are_validated(tmp_path, entry):
    # a misspelt or mistyped bound must not turn into an unconditional allowance
    with pytest.raises(ValueError, match=r"allow\[0\]"):
        dk.load_allowlist(write_allow(tmp_path, [entry]))


@pytest.mark.parametrize("doc", [
    {"allow": []},                                    # no version
    {"version": 2, "allow": []},                      # unknown version
    {"version": 1, "allows": []},                     # misspelt key
    {"version": 1, "allow": {"section": "xrefs"}},    # allow not a list
    ["allow"],                                        # not a mapping
])
def test_allow_file_shape_is_validated(tmp_path, doc):
    path = tmp_path / "allow.yaml"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="allow.yaml"):
        dk.load_allowlist(path)


def test_misspelt_bound_no_longer_allows_any_delta(tmp_path):
    # review finding: max_delta (sic) used to be ignored and let a delta of 893 through
    path = write_allow(tmp_path, [{"section": "ee_edges", "key": "FATHER_OF *", "max_delta": 2, "reason": "r"}])
    with pytest.raises(ValueError, match="max_delta"):
        dk.load_allowlist(path)
    allow = dk.load_allowlist(write_allow(tmp_path, [{"section": "ee_edges", "key": "FATHER_OF *",
                                                     "max_abs_delta": 2, "reason": "r"}]))
    big = {"section": "ee_edges", "key": "FATHER_OF phase=4 source=-", "a": 7, "b": 900, "delta": 893}
    assert dk.classify([big], allow)[0][0]["allowed_by"] is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def two_targets(monkeypatch):
    drivers = {"prod": FakeDriver(profile()),
               "staging": FakeDriver(profile(xrefs=[{"source": "tsk", "n": 100}, {"source": "markdown", "n": 3}]))}
    monkeypatch.setattr(dk, "resolve_target", lambda name: SimpleNamespace(name=name, neo4j_uri=f"bolt://{name}"))
    monkeypatch.setattr(dk, "open_neo4j", lambda target: drivers[target.name])
    return drivers


def test_cli_fails_on_a_difference_outside_the_allow_list(two_targets, capsys):
    assert dk.main(["--no-registry", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["exit_code"] == 1
    assert [(d["section"], d["key"], d["delta"]) for d in report["differences"]] == [("xrefs", "source=markdown", -1)]
    assert all(d.closed for d in two_targets.values())


def test_cli_passes_when_every_difference_is_allowed(two_targets, tmp_path, capsys):
    allow = write_allow(tmp_path, [{"section": "xrefs", "key": "source=markdown", "delta": -1,
                                    "reason": "1B re-anchors one supplementary edge"}])
    assert dk.main(["--no-registry", "--allow", allow]) == 0
    out = capsys.readouterr().out
    assert "1B re-anchors" in out and "exit 0" in out


def test_cli_unreadable_target_exits_1(monkeypatch, capsys):
    def refuse(name):
        raise ValueError("--target prod refused: shell NEO4J_URI=bolt://localhost:7688 differs")
    monkeypatch.setattr(dk, "resolve_target", refuse)
    assert dk.main([]) == 1
    assert "refused" in capsys.readouterr().err


def test_cli_rejects_comparing_a_target_with_itself(capsys):
    with pytest.raises(SystemExit):
        dk.main(["--a", "staging", "--b", "staging"])
