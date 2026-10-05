"""diff_kg: live vs staging comparison for the batch-0 R2 gate (docs/build_database.md R2).

Every read goes through a fake Neo4j driver that answers diff_kg's own
profile queries and export_event_registry's anchor query, and records the
access mode of each session: the tool must never open a write session.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
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
        "entities": [{"entity_id": "person:yabolahan", "description": "信心之父", "aliases": ["亞伯蘭"],
                      "mention_count": 12},
                     {"entity_id": "person:yisa", "description": None, "aliases": None},  # no mention_count
                     {"entity_id": "event:xianyisa", "description": "獻以撒", "aliases": ["甲", "乙"],
                      "mention_count": 4}],
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
        {"entity_id": "person:yabolahan", "description": "信心之父 ", "aliases": "[\"亞伯蘭\"]", "mention_count": 12},
        {"entity_id": "person:yisa", "description": "", "aliases": []},       # None == empty
        {"entity_id": "event:xianyisa", "description": "獻以撒", "aliases": ["乙", "甲"], "mention_count": 4},  # same set
        {"entity_id": "person:new", "description": None, "aliases": []}])
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(b), with_registry=False)
    assert keys(diffs, "descriptions") == ["person:yabolahan"]   # a trailing space counts
    assert keys(diffs, "aliases") == ["person:yabolahan"]        # a JSON string is not the list
    assert keys(diffs, "entity_ids") == ["person:new"]


ABSENT = object()


def recount(counts: dict) -> list[dict]:
    """profile()'s entity rows with mention_count set per entity_id (ABSENT drops the key)."""
    rows = []
    for row in profile()["entities"]:
        if row["entity_id"] in counts:
            row = {k: v for k, v in row.items() if k != "mention_count"}
            if counts[row["entity_id"]] is not ABSENT:
                row["mention_count"] = counts[row["entity_id"]]
        rows.append(row)
    return rows


def test_mention_count_section_per_entity():
    assert "e.mention_count AS mention_count" in dk.PROFILE_QUERIES["entities"]
    b = profile(entities=recount({"event:xianyisa": 1}) + [
        {"entity_id": "person:new", "description": None, "aliases": [], "mention_count": 2}])
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(b), with_registry=False)
    assert [(d["key"], d["a"], d["b"], d["delta"]) for d in diffs if d["section"] == "mention_count"] == [
        ("event:xianyisa", 4, 1, -3)]
    assert keys(diffs, "entity_ids") == ["person:new"]  # a one-sided entity is not a mention_count difference


def test_rows_without_mention_count_are_equal():
    # an unset mention_count (key absent, as person:yisa in profile(), or null) equals another unset one
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(profile(entities=recount({"person:yisa": None}))),
                          with_registry=False)
    assert diffs == []
    diffs, _ = dk.compare(FakeDriver(profile(entities=recount({"event:xianyisa": ABSENT}))),
                          FakeDriver(profile(entities=recount({"event:xianyisa": None}))), with_registry=False)
    assert diffs == []
    # ... but never a number: unset -> 0 is a difference without a delta
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(profile(entities=recount({"person:yisa": 0}))),
                          with_registry=False)
    assert [(d["section"], d["key"], d["a"], d["b"], d["delta"]) for d in diffs] == [
        ("mention_count", "person:yisa", None, 0, None)]


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


def test_mention_count_allow_entry_with_delta(tmp_path):
    b = profile(entities=recount({"event:xianyisa": 1, "person:yabolahan": 30, "person:yisa": 5}))
    diffs, _ = dk.compare(FakeDriver(profile()), FakeDriver(b), with_registry=False)
    allow = dk.load_allowlist(write_allow(tmp_path, [
        {"section": "mention_count", "key": "event:*", "delta": -3, "reason": "K10 residual"},
        {"section": "mention_count", "key": "person:yabolahan", "max_abs_delta": 10, "reason": "too small"},
        {"section": "mention_count", "key": "person:yisa", "max_abs_delta": 10, "reason": "unset -> 5"}]))
    classified, unused = dk.classify(diffs, allow)
    assert {d["key"]: d["allowed_by"] for d in classified} == {
        "event:xianyisa": "K10 residual",
        "person:yabolahan": None,  # +18 is over 10
        "person:yisa": None}       # null -> 5 has no delta, so no bound matches it
    assert [e["reason"] for e in unused] == ["too small", "unset -> 5"]


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


K10 = {"section": "mention_count", "key": "event:shanshangbaoxun", "delta": -22, "reason": "K10 residual"}


@pytest.mark.parametrize("repeat", [
    K10,                                    # verbatim: the same entry in two W1 fragments
    {**K10, "reason": "1B fragment"},
    {**K10, "delta": -3},                   # a different bound is still the same (section, key)
    {"section": "mention_count", "key": "event:shanshangbaoxun", "reason": "unbounded"},
])
def test_allow_list_rejects_a_repeated_section_and_key(tmp_path, repeat):
    # the merged W1 allowlist concatenates fragments and classify credits only the first
    # match, so a repeat would surface only as "unused" at R2 (--fail-on-unused)
    entries = [K10, {"section": "xrefs", "key": "source=tsk", "delta": -68, "reason": "r"}, repeat]
    with pytest.raises(ValueError, match=r"allow\.yaml: allow\[2\] repeats .*allow\[0\]"):
        dk.load_allowlist(write_allow(tmp_path, entries))


def test_allow_list_keeps_distinct_keys_and_the_same_key_in_another_section(tmp_path):
    entries = [K10,
               {**K10, "key": "event:baoluoxushuguizhujingguo", "delta": -3},
               {"section": "descriptions", "key": "event:shanshangbaoxun", "reason": "other section"},
               # an overlapping glob is a different key: only verbatim repeats are refused
               {"section": "mention_count", "key": "event:*", "max_abs_delta": 3, "reason": "glob"}]
    assert dk.load_allowlist(write_allow(tmp_path, entries)) == entries
    # --help claims no more than that (staging_promotion.md R2: 互相涵蓋的 glob 仍要人工確認)
    doc = " ".join(dk.__doc__.split())
    assert "a verbatim repeat must fail" in doc and "an overlap must fail" not in doc
    assert "Overlapping globs that are different strings (event:* next to event:x) are not detected" in doc


# ---------------------------------------------------------------------------
# YAML level: repeated mapping keys, rendering, merging fragments
# ---------------------------------------------------------------------------

FRAGMENT_1A = ("# a 1A fragment\nversion: 1\nallow:\n  - section: mention_count\n"
               '    key: "event:shanshangbaoxun"\n    delta: -22\n    reason: "K10 residual"\n')
FRAGMENT_1B = ('version: 1\nallow:\n  - section: xrefs\n    key: "source=tsk"\n    delta: -68\n    reason: "1B"\n'
               '  - section: relationships\n    key: CROSS_REFERENCES\n    delta: -52\n    reason: "1B"\n')


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fragments(tmp_path) -> tuple[Path, Path]:
    a, b = tmp_path / "residuals_allow.yaml", tmp_path / "xref_allow.yaml"
    a.write_text(FRAGMENT_1A, encoding="utf-8")
    b.write_text(FRAGMENT_1B, encoding="utf-8")
    return a, b


@pytest.mark.parametrize("order", [(0, 1), (1, 0), (1, 1)])
def test_a_cat_of_whole_fragments_is_refused_not_cut_to_the_last_allow(tmp_path, order):
    # each fragment is a whole document: plain YAML keeps only the last `allow:` of a cat,
    # so the other fragments would vanish without an error (and dodge the repeat check)
    path = tmp_path / "cat.yaml"
    path.write_text("".join((FRAGMENT_1A, FRAGMENT_1B)[i] for i in order), encoding="utf-8")
    with pytest.raises(ValueError, match=r"cat\.yaml: .*repeats the mapping key 'version'"):
        dk.load_allowlist(path)


def test_an_entry_field_written_twice_is_refused(tmp_path):
    path = tmp_path / "allow.yaml"
    path.write_text("version: 1\nallow:\n  - section: xrefs\n    key: source=tsk\n    delta: -68\n"
                    "    delta: 5\n    reason: r\n", encoding="utf-8")
    with pytest.raises(ValueError, match="repeats the mapping key 'delta'"):
        dk.load_allowlist(path)


def test_render_allowlist_round_trips_every_bound_and_awkward_strings():
    entries = [{"section": "ee_edges", "key": "SON_OF phase=2 source=-", "delta": 1, "reason": "a: b # c"},
               {"section": "mentions", "key": "Pericope *", "max_abs_delta": 3,
                "reason": '"q" \\ 「全形」\u2028\x85\x7f'},
               {"section": "descriptions", "key": "person:yuehan（shitu）", "reason": "no bound"}]
    text = dk.render_allowlist(entries, ["header"])
    assert text.startswith("# header\nversion: 1\nallow:\n  - section: ee_edges\n"
                           '    key: "SON_OF phase=2 source=-"\n    delta: 1\n    reason: "a: b # c"\n')
    assert dk.parse_allowlist(text, "rendered") == entries
    assert dk.parse_allowlist(dk.render_allowlist([], []), "empty") == []


def test_render_allowlist_refuses_text_that_does_not_load_back(monkeypatch):
    monkeypatch.setattr(dk, "_yaml_str", lambda s: s)                  # a plain scalar drops "# c"
    with pytest.raises(ValueError, match="does not load back"):
        dk.render_allowlist([{"section": "xrefs", "key": "source=tsk", "reason": "b # c"}], [])


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


def stale_allow(tmp_path) -> str:
    """Allows two_targets' one difference, plus an entry that matches nothing."""
    return write_allow(tmp_path, [
        {"section": "xrefs", "key": "source=markdown", "delta": -1, "reason": "1B re-anchors one edge"},
        {"section": "xrefs", "key": "source=supplementary", "delta": 2, "reason": "stale fragment"}])


def test_fail_on_unused_exits_1_when_an_allowance_matches_nothing(two_targets, tmp_path, capsys):
    allow = stale_allow(tmp_path)
    assert dk.main(["--no-registry", "--allow", allow, "--fail-on-unused", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["exit_code"] == 1 and report["fail_on_unused"] is True and report["errors"] == []
    assert [d["allowed_by"] for d in report["differences"]] == ["1B re-anchors one edge"]
    assert [e["reason"] for e in report["unused_allowances"]] == ["stale fragment"]

    assert dk.main(["--no-registry", "--allow", allow, "--fail-on-unused"]) == 1
    out = capsys.readouterr().out
    assert "unused allowance: xrefs source=supplementary (stale fragment)" in out
    assert "exit 1: 0 differences not allowed, 0 errors, 1 unused allowances" in out

    # every entry used: the flag alone does not fail
    used = write_allow(tmp_path, [{"section": "xrefs", "key": "source=markdown", "delta": -1, "reason": "r"}])
    assert dk.main(["--no-registry", "--allow", used, "--fail-on-unused"]) == 0
    assert "exit 0: every difference is allowed and every allowance is used" in capsys.readouterr().out


def test_unused_is_informational_without_the_flag(two_targets, tmp_path, capsys):
    allow = stale_allow(tmp_path)
    assert dk.main(["--no-registry", "--allow", allow, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["exit_code"] == 0 and report["fail_on_unused"] is False
    assert [e["reason"] for e in report["unused_allowances"]] == ["stale fragment"]

    assert dk.main(["--no-registry", "--allow", allow]) == 0
    out = capsys.readouterr().out
    assert "unused allowance: xrefs source=supplementary (stale fragment)" in out
    assert out.rstrip().endswith("exit 0: every difference is allowed")  # default wording unchanged


def test_cli_refuses_a_repeated_allow_key_before_reading_a_target(monkeypatch, tmp_path, capsys):
    resolved = []
    monkeypatch.setattr(dk, "resolve_target", resolved.append)
    assert dk.main(["--no-registry", "--allow", write_allow(tmp_path, [K10, K10]), "--fail-on-unused"]) == 1
    assert dk.main(["--no-registry", "--allow", str(tmp_path / "missing.yaml"), "--json"]) == 1
    captured = capsys.readouterr()
    assert resolved == [] and captured.out == ""                      # no target, no report
    errors = captured.err.splitlines()                                # one line each, no traceback
    assert len(errors) == 2 and all(line.startswith("ERROR: --allow: ") for line in errors)
    assert "allow[1] repeats" in errors[0] and "missing.yaml" in errors[1]
    assert "the --allow file is unreadable or invalid" in " ".join(dk.__doc__.split())


def test_cli_unreadable_target_exits_1(monkeypatch, capsys):
    def refuse(name):
        raise ValueError("--target prod refused: shell NEO4J_URI=bolt://localhost:7688 differs")
    monkeypatch.setattr(dk, "resolve_target", refuse)
    assert dk.main([]) == 1
    assert "refused" in capsys.readouterr().err


def test_cli_rejects_comparing_a_target_with_itself(capsys):
    with pytest.raises(SystemExit):
        dk.main(["--a", "staging", "--b", "staging"])


@pytest.fixture
def no_target(monkeypatch):
    def refuse(name):
        raise AssertionError("merging fragments must not resolve a target")
    monkeypatch.setattr(dk, "resolve_target", refuse)


def merge(out, *fragment_paths) -> int:
    return dk.main(["--merge-out", str(out), *[arg for p in fragment_paths for arg in ("--allow", str(p))]])


def test_merge_out_joins_the_fragments_allow_lists_under_one_version(tmp_path, monkeypatch, no_target, capsys):
    a, b = fragments(tmp_path)
    out = tmp_path / "merged.yaml"
    assert merge(out, a, b) == 0
    assert out.read_text(encoding="utf-8") == (
        "# allowlist merged by diff_kg.py --merge-out from these fragments, in order; regenerate it, never edit it:\n"
        f"# residuals_allow.yaml: sha256 {sha(a)}, 1 entries\n"
        f"# xref_allow.yaml: sha256 {sha(b)}, 2 entries\n"
        "version: 1\nallow:\n"
        '  - section: mention_count\n    key: "event:shanshangbaoxun"\n    delta: -22\n    reason: "K10 residual"\n'
        '  - section: xrefs\n    key: "source=tsk"\n    delta: -68\n    reason: "1B"\n'
        '  - section: relationships\n    key: "CROSS_REFERENCES"\n    delta: -52\n    reason: "1B"\n')
    assert dk.load_allowlist(out) == dk.load_allowlist(a) + dk.load_allowlist(b)
    printed = capsys.readouterr().out
    assert "merged 3 entries (1 + 2)" in printed and f"{sha(out)}  {out}" in printed
    # the bytes depend on the fragments' content, not on how their paths are spelt
    monkeypatch.chdir(tmp_path)
    assert merge("again.yaml", "residuals_allow.yaml", "./xref_allow.yaml") == 0
    assert (tmp_path / "again.yaml").read_bytes() == out.read_bytes()


def test_merge_out_refuses_a_key_repeated_across_fragments_and_writes_nothing(tmp_path, no_target, capsys):
    a, b = fragments(tmp_path)
    copy = tmp_path / "residuals_copy.yaml"
    copy.write_text(FRAGMENT_1A, encoding="utf-8")
    assert merge(tmp_path / "merged.yaml", a, b, copy) == 1
    assert ("residuals_copy.yaml allow[0] repeats section mention_count key 'event:shanshangbaoxun' "
            "of residuals_allow.yaml allow[0]") in capsys.readouterr().err
    assert not (tmp_path / "merged.yaml").exists()


def test_merge_out_refuses_a_cat_fragment_and_writes_nothing(tmp_path, no_target, capsys):
    a, _ = fragments(tmp_path)
    cat = tmp_path / "cat.yaml"
    cat.write_text(FRAGMENT_1A + FRAGMENT_1B, encoding="utf-8")
    assert merge(tmp_path / "merged.yaml", a, cat) == 1
    assert "repeats the mapping key 'version'" in capsys.readouterr().err
    assert not (tmp_path / "merged.yaml").exists()


def test_sha_out_registers_the_merged_sha256_as_a_sha256sum_line(tmp_path, monkeypatch, no_target, capsys):
    # the merged file is committed only after R4 (plan §3); its sha256 is what W1 registers before the rebuild
    monkeypatch.chdir(tmp_path)
    fragments(tmp_path)
    argv = ["--merge-out", "merged.yaml", "--sha-out", "merged.sha256",
            "--allow", "residuals_allow.yaml", "--allow", "xref_allow.yaml"]
    assert dk.main(argv) == 0
    line = f"{sha(tmp_path / 'merged.yaml')}  merged.yaml\n"
    assert (tmp_path / "merged.sha256").read_text(encoding="utf-8") == line
    assert line in capsys.readouterr().out
    assert subprocess.run(["sha256sum", "--check", "--quiet", "merged.sha256"], cwd=tmp_path).returncode == 0


def test_sha_out_is_not_written_when_the_merge_fails(tmp_path, no_target, capsys):
    a, b = fragments(tmp_path)
    side = tmp_path / "merged.sha256"
    assert dk.main(["--merge-out", str(tmp_path / "merged.yaml"), "--sha-out", str(side),
                    "--allow", str(a), "--allow", str(b), "--allow", str(a)]) == 1
    assert "repeats section mention_count" in capsys.readouterr().err
    assert not side.exists() and not (tmp_path / "merged.yaml").exists()


@pytest.mark.parametrize("argv, message", [
    (["--merge-out", "m.yaml"], "--merge-out needs the fragments as --allow"),
    (["--merge-out", "x.yaml", "--allow", "./x.yaml"], "--merge-out would overwrite the fragment"),
    (["--allow", "a.yaml", "--allow", "b.yaml"], "a diff takes one merged --allow file"),  # plan §3
    (["--sha-out", "m.sha256", "--allow", "a.yaml"], "--sha-out needs --merge-out"),
    (["--merge-out", "m.yaml", "--sha-out", "./m.yaml", "--allow", "a.yaml"], "--sha-out would overwrite"),
    (["--merge-out", "m.yaml", "--sha-out", "x.yaml", "--allow", "x.yaml"], "--sha-out would overwrite"),
    # the diff-only flags: a merge exits 0 without a diff, which must not read as a passed gate
    (["--merge-out", "m.yaml", "--allow", "a.yaml", "--fail-on-unused"],
     "--merge-out does not diff; drop --fail-on-unused"),
    (["--merge-out", "m.yaml", "--allow", "a.yaml", "--no-registry"], "--merge-out does not diff; drop --no-registry"),
    (["--merge-out", "m.yaml", "--allow", "a.yaml", "--json", "--samples", "3"], "drop --json --samples"),
])
def test_merge_out_and_allow_usage_errors_exit_2(argv, message, tmp_path, monkeypatch, no_target, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        dk.main(argv)
    assert exc.value.code == 2 and message in capsys.readouterr().err
    assert not [p.name for p in tmp_path.iterdir()]
