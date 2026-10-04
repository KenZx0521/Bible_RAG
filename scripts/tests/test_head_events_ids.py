"""backfill_head_events.NEW_EVENTS carries literal entity_ids (ID-7).

The ids used to be derived at run time by `_pinyin_id(canonical_name)`, so a
pypinyin upgrade or a renamed event would silently mint a new id and orphan
every consumer keyed on the old one (event_registry.json, eval records). The
18 ids below were checked against live Neo4j (read-only, 2026-10-04): each
exists as an :Event with source='head_event_backfill' and the same name.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

import backfill_head_events as bhe

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "backend" / "data" / "event_registry.json"


def _new_events_literal_ids() -> dict[str, object]:
    """canonical_name → the AST node of each NEW_EVENTS entry's entity_id."""
    tree = ast.parse(Path(bhe.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) else None)
        if getattr(target, "id", None) == "NEW_EVENTS":
            out = {}
            for entry in node.value.elts:
                fields = {k.value: v for k, v in zip(entry.keys, entry.values)}
                out[fields["canonical_name"].value] = fields.get("entity_id")
            return out
    raise AssertionError("NEW_EVENTS assignment not found")


def test_every_new_event_has_a_literal_string_id():
    ids = _new_events_literal_ids()

    assert len(ids) == 18
    for name, node in ids.items():
        assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
            f"{name}: entity_id must be a string literal, not computed")
        assert node.value.startswith("event:")


def test_new_event_ids_are_unique_and_disjoint_from_alias_targets():
    ids = [ev["entity_id"] for ev in bhe.NEW_EVENTS]

    assert len(set(ids)) == len(ids)
    assert not set(ids) & set(bhe.ALIAS_INJECTIONS)


def test_new_event_ids_match_committed_registry():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    listed = {e["id"]: e for e in registry["events"]}
    dropped = {d["id"]: d for d in registry["dropped"]}
    new_ids = {ev["entity_id"]: ev["canonical_name"] for ev in bhe.NEW_EVENTS}

    for eid, name in new_ids.items():
        row = listed.get(eid) or dropped.get(eid)
        assert row is not None, f"{eid} ({name}) absent from event_registry.json"
        assert row["name"] == name
        if eid in listed:
            assert row["provenance"] == "head_event_backfill"
    head_rows = {eid for eid, e in listed.items()
                 if e["provenance"] == "head_event_backfill"}
    assert head_rows <= set(new_ids)


def test_export_registry_reads_the_same_literal_ids():
    import export_event_registry

    curated = export_event_registry.curated_event_ids()

    for ev in bhe.NEW_EVENTS:
        assert curated.get(ev["entity_id"]) == "head_event_backfill"


@pytest.mark.parametrize("module", ["backfill_head_events", "export_event_registry"])
def test_curated_event_ids_no_longer_depend_on_pypinyin(module):
    # Neither the writer (10.4) nor the registry export (10.6 --check) may
    # derive an id from a name again; pypinyin stays a dependency of the
    # extraction scripts only.
    source = (ROOT / "scripts" / f"{module}.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {node.module or "", *(alias.name for alias in node.names)}

    assert "pypinyin" not in imported
    assert "_pinyin_id" not in imported
    assert "_pinyin_id" not in source


# ---------------------------------------------------------------------------
# validate() uses the literal ids
# ---------------------------------------------------------------------------

class _Result(list):
    def single(self):
        return self[0] if self else None


class _ValidateSession:
    """Answers validate()'s three read queries; `taken` maps id → foreign name."""

    def __init__(self, taken: dict[str, str] | None = None):
        self.taken = taken or {}

    def run(self, query: str, **params):
        if "UNWIND $ids AS eid OPTIONAL MATCH (e:Event" in query:
            return _Result({"eid": eid, "name": "existing"} for eid in params["ids"])
        if "UNWIND $ids AS pid" in query:
            return _Result({"pid": pid, "found": pid} for pid in params["ids"])
        if "$eid" in query:
            return _Result([{"name": self.taken.get(params["eid"])}])
        raise AssertionError(f"unexpected query: {query}")


def test_validate_returns_the_literal_ids():
    enriched = bhe.validate(_ValidateSession())

    assert [ev["entity_id"] for ev in enriched] == [
        ev["entity_id"] for ev in bhe.NEW_EVENTS]


def test_validate_fails_when_id_is_owned_by_another_name():
    first = bhe.NEW_EVENTS[0]["entity_id"]

    with pytest.raises(SystemExit):
        bhe.validate(_ValidateSession(taken={first: "別的事件"}))


# ---------------------------------------------------------------------------
# Store targets: kg_target guard and the Qdrant endpoint
# ---------------------------------------------------------------------------

STAGING = {
    "KG_TARGET": "staging",
    "NEO4J_URI": "bolt://localhost:7688",
    "POSTGRES_DB": "bible_rag_staging",
    "QDRANT_ENTITY_COLLECTION": "bible_entities_v2",
}


def _no_connection():
    raise AssertionError("connected before the target guard ran")


def test_main_refuses_a_staging_run_that_reaches_production(monkeypatch):
    # 10.4 writes all three stores; one forgotten export (here POSTGRES_DB
    # left at the production name) must stop it before any connection.
    for name, value in {**STAGING, "POSTGRES_DB": "bible_rag"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(bhe, "get_neo4j", _no_connection)
    monkeypatch.setattr(bhe, "get_pg", _no_connection)
    monkeypatch.setattr(sys, "argv", ["backfill_head_events.py", "--dry-run"])

    with pytest.raises(SystemExit, match="POSTGRES_DB"):
        bhe.main()


def test_main_guards_every_store_it_writes(monkeypatch):
    import kg_target
    seen = []

    def _record(*stores):
        seen.append(stores)
        raise SystemExit("stop after the guard")
    monkeypatch.setattr(kg_target, "assert_target", _record)
    monkeypatch.setattr(bhe, "get_neo4j", _no_connection)
    monkeypatch.setattr(sys, "argv", ["backfill_head_events.py", "--skip-qdrant"])

    with pytest.raises(SystemExit, match="stop after the guard"):
        bhe.main()

    # Qdrant is guarded even with --skip-qdrant: a half-exported staging
    # shell is exactly the mistake the guard exists for.
    assert seen == [("neo4j", "postgres", "qdrant")]


@pytest.mark.parametrize("env, port", [
    ({"QDRANT_PORT": "6400", "QDRANT_HTTP_PORT": "6333"}, 6400),
    ({"QDRANT_HTTP_PORT": "6555"}, 6555),
    ({}, 6333),
])
def test_qdrant_port_prefers_qdrant_port(monkeypatch, env, port):
    for name in ("QDRANT_HOST", "QDRANT_PORT", "QDRANT_HTTP_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    assert bhe.qdrant_endpoint() == ("localhost", port)
