"""export_event_registry: literal curated ids and an offline-callable core.

* curated_event_ids() must key NEW_EVENTS by their literal entity_id (ID-7).
  Deriving the id from the pinyin of canonical_name made the 10.6 --check
  depend on the pypinyin version and on nobody renaming an event.
* registry_from_rows() is the pure core (anchor rows in, registry out), so
  validate_kg's snapshot mode and a future diff_kg can build the registry from
  a JSONL projection without Neo4j. build_registry() only adds the live fetch.
* --check keeps its contract: compare everything but generated_at, never write.
"""

import json
import sys

import pytest

import export_event_registry as exr

BOOK_ORDER = {"gen": 1, "exo": 2, "mat": 40}
KEYWORDS = {"最後的晚餐", "主的晚餐", "十災", "巴別塔", "晚餐"}
CURATED = {
    "event:zuihoudewancan": "head_event_backfill",
    "event:shizai": "alias_injection",
    "event:babieta": "manual_edges",
    "event:wuzhaoling": "head_event_backfill",
}
ROWS = [
    {"id": "event:zuihoudewancan", "name": "最後的晚餐", "aliases": ["主的晚餐", "設立聖餐"],
     "anchors": ["mat:26:3", "gen:10:0", "gen:9:1", "gen:9:0"]},
    {"id": "event:shizai", "name": "十災", "aliases": None, "anchors": []},
    {"id": "event:babieta", "name": "巴別塔", "aliases": [], "anchors": ["gen:11:0"]},
    # No keyword equals the name or an alias: dropped even without anchors.
    {"id": "event:wuzhaoling", "name": "無召令", "aliases": ["晚餐會"], "anchors": []},
]


def _registry(rows=ROWS, curated=CURATED, **kw):
    return exr.registry_from_rows(rows, curated, KEYWORDS, BOOK_ORDER, **kw)


# ---------------------------------------------------------------------------
# curated_event_ids
# ---------------------------------------------------------------------------

@pytest.fixture
def no_manual_patches(tmp_path, monkeypatch):
    path = tmp_path / "manual_graph_patches.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(exr, "MANUAL_PATCHES", path)
    return path


def test_curated_ids_use_the_literal_entity_id(monkeypatch, no_manual_patches):
    # A renamed event keeps its frozen id; pinyin of the new name would be
    # event:gaiguodemingzi and orphan the registry entry.
    monkeypatch.setattr(exr, "ALIAS_INJECTIONS", {})
    monkeypatch.setattr(exr, "NEW_EVENTS", [
        {"entity_id": "event:frozen", "canonical_name": "改過的名字"}])

    assert exr.curated_event_ids() == {"event:frozen": "head_event_backfill"}


def test_curated_ids_keep_the_first_provenance(monkeypatch, no_manual_patches):
    no_manual_patches.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"kind": "meta"},
        {"kind": "node", "entity_id": "event:a", "labels": ["Entity", "Event"], "origin": "manual"},
        {"kind": "node", "entity_id": "event:m", "labels": ["Entity", "Event"], "origin": "manual"},
        {"kind": "node", "entity_id": "event:x", "labels": ["Entity", "Event"], "origin": "extracted"},
        {"kind": "node", "entity_id": "person:p", "labels": ["Entity", "Person"], "origin": "manual"},
        {"kind": "edge", "entity_id": "event:x", "pericope_id": "gen:1:0"},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(exr, "ALIAS_INJECTIONS", {"event:a": ["甲"]})
    monkeypatch.setattr(exr, "NEW_EVENTS", [{"entity_id": "event:n", "canonical_name": "乙"}])

    assert exr.curated_event_ids() == {
        "event:a": "alias_injection",
        "event:n": "head_event_backfill",
        "event:m": "manual_patch",
        "event:x": "manual_edges",
    }


def test_export_module_has_no_pinyin_dependency():
    assert not hasattr(exr, "_pinyin_id")


# ---------------------------------------------------------------------------
# registry_from_rows: the pure core
# ---------------------------------------------------------------------------

def test_triggers_are_keywords_equal_to_the_name_or_an_alias():
    events = {e["id"]: e for e in _registry()["events"]}

    # "晚餐" is a substring, not an exact match, so it is not a trigger.
    assert events["event:zuihoudewancan"]["triggers"] == ["主的晚餐", "最後的晚餐"]


def test_anchors_sort_by_book_order_then_numeric_chapter_and_index():
    events = {e["id"]: e for e in _registry()["events"]}

    assert events["event:zuihoudewancan"]["anchors"] == [
        "gen:9:0", "gen:9:1", "gen:10:0", "mat:26:3"]


def test_events_and_dropped_follow_id_order_with_reasons():
    registry = _registry()

    assert [(e["id"], e["provenance"]) for e in registry["events"]] == [
        ("event:babieta", "manual_edges"),
        ("event:zuihoudewancan", "head_event_backfill"),
    ]
    assert registry["dropped"] == [
        {"id": "event:shizai", "name": "十災", "reason": "no anchors"},
        {"id": "event:wuzhaoling", "name": "無召令", "reason": "no EVENT_KEYWORDS exact match"},
    ]


def test_registry_layout_matches_the_committed_file():
    committed = json.loads(exr.OUT_PATH.read_text(encoding="utf-8"))
    registry = _registry(generated_at="2026-10-04T00:00:00")

    assert list(registry) == list(committed)
    assert registry["generated_at"] == "2026-10-04T00:00:00"
    assert {k: registry[k] for k in ("version", "generator", "trigger_rule", "anchor_order")} == {
        k: committed[k] for k in ("version", "generator", "trigger_rule", "anchor_order")}
    assert list(registry["events"][0]) == list(committed["events"][0])
    assert list(registry["dropped"][0]) == list(committed["dropped"][0])


def test_rows_outside_the_curated_set_are_ignored():
    extra = {"id": "event:other", "name": "十災", "aliases": [], "anchors": ["exo:7:2"]}

    assert _registry(rows=[*ROWS, extra]) == _registry()


def test_missing_curated_event_fails_and_names_it():
    with pytest.raises(RuntimeError, match="event:shizai"):
        _registry(rows=[r for r in ROWS if r["id"] != "event:shizai"])


def test_duplicate_rows_for_one_id_fail():
    # Without the :Entity(entity_id) constraint one id can sit on two nodes;
    # picking either row silently would make the registry order-dependent.
    with pytest.raises(RuntimeError, match="event:babieta"):
        _registry(rows=[*ROWS, dict(ROWS[2])])


def test_pure_core_is_deterministic_and_never_connects(monkeypatch):
    def _no_neo4j():
        raise AssertionError("registry_from_rows must not connect")
    monkeypatch.setattr(exr, "get_neo4j", _no_neo4j)
    rows = json.loads(json.dumps(ROWS))

    first = _registry(rows=rows)

    assert rows == ROWS  # inputs untouched
    assert _registry(rows=rows) == first


def test_rendering_is_indented_utf8_json_with_a_trailing_newline():
    text = exr.render_registry({"version": 1, "events": [{"name": "十災"}]})

    assert text == '{\n  "version": 1,\n  "events": [\n    {\n      "name": "十災"\n    }\n  ]\n}\n'


# ---------------------------------------------------------------------------
# build_registry: live fetch + the pure core
# ---------------------------------------------------------------------------

class _AnchorSession:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self._calls.append((query, params))
        return [dict(r) for r in ROWS if r["id"] in params["ids"]]


class _AnchorDriver:
    def __init__(self):
        self.calls = []
        self.closed = False

    def session(self):
        return _AnchorSession(self.calls)

    def close(self):
        self.closed = True


@pytest.fixture
def fixture_inputs(monkeypatch):
    monkeypatch.setattr(exr, "curated_event_ids", lambda: dict(CURATED))
    monkeypatch.setattr(exr, "event_keywords", lambda: set(KEYWORDS))
    monkeypatch.setattr(exr, "load_book_order", lambda path=None: dict(BOOK_ORDER))


def test_build_registry_feeds_the_live_rows_to_the_pure_core(fixture_inputs):
    driver = _AnchorDriver()

    registry = exr.build_registry(driver)

    assert driver.calls == [(exr._ANCHOR_QUERY, {"ids": sorted(CURATED)})]
    assert registry["generated_at"]
    assert exr._comparable(registry) == exr._comparable(_registry())
    assert not driver.closed  # the caller owns a driver it passed in


def test_build_registry_closes_the_driver_it_opened(fixture_inputs, monkeypatch):
    driver = _AnchorDriver()
    monkeypatch.setattr(exr, "get_neo4j", lambda: driver)

    exr.build_registry()

    assert driver.closed


# ---------------------------------------------------------------------------
# main: --check never writes; plain run writes the rendered registry
# ---------------------------------------------------------------------------

@pytest.fixture
def committed_file(tmp_path, monkeypatch):
    path = tmp_path / "event_registry.json"
    path.write_text(exr.render_registry(_registry(generated_at="2026-10-03T20:21:00")),
                    encoding="utf-8")
    monkeypatch.setattr(exr, "OUT_PATH", path)
    return path


def _run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["export_event_registry.py", *argv])
    return exr.main()


def test_check_ignores_generated_at_and_writes_nothing(committed_file, monkeypatch):
    before = committed_file.read_bytes()
    monkeypatch.setattr(exr, "build_registry",
                        lambda: _registry(generated_at="2099-01-01T00:00:00"))

    assert _run_main(monkeypatch, "--check") == 0
    assert committed_file.read_bytes() == before


def test_check_reports_drift_and_writes_nothing(committed_file, monkeypatch):
    before = committed_file.read_bytes()
    drifted = [r for r in ROWS if r["id"] != "event:babieta"] + [
        {**ROWS[2], "anchors": ["gen:11:0", "exo:1:0"]}]
    monkeypatch.setattr(exr, "build_registry", lambda: _registry(rows=drifted))

    assert _run_main(monkeypatch, "--check") == 1
    assert committed_file.read_bytes() == before


def test_plain_run_writes_the_rendered_registry(committed_file, monkeypatch):
    fresh = _registry(generated_at="2099-01-01T00:00:00")
    monkeypatch.setattr(exr, "build_registry", lambda: fresh)

    assert _run_main(monkeypatch) == 0
    assert committed_file.read_text(encoding="utf-8") == exr.render_registry(fresh)
