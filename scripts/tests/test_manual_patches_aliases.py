"""backfill_manual_patches --apply replays aliases on every node (EV-06, ID-7).

Before the fix, node rows were replayed with `MERGE ... ON CREATE SET e +=
row.props`, so an *extracted* node (present in entities.jsonl, e.g. 山上寶訓)
kept the empty aliases of a fresh rebuild and lost the hand-added triggers
(八福, 登山寶訓, 保羅歸主). The same MERGE would also mint a zombie node when
an extracted id had disappeared upstream. These tests pin the fixed contract:

* every node row merges its aliases (order-preserving union, canonical removed);
* an extracted id that is missing — from Neo4j, PG or Qdrant — fails hard,
  before anything is written to any store;
* PG/Qdrant sync of extracted rows touches aliases only, and the backup holds
  every store's aliases_before;
* --export honours --dry-run;
* KG_TARGET=staging never reaches production.

The last test runs the real alias Cypher, but only against a writable staging
Neo4j named by KG_TEST_NEO4J_URI; it is skipped everywhere else.
"""

import argparse
import json
import os
import sys
import uuid

import pytest

import backfill_head_events as bhe
import backfill_manual_patches as bmp

EXTRACTED = {
    "kind": "node",
    "entity_id": "event:shanshangbaoxun",
    "labels": ["Entity", "Event"],
    "origin": "extracted",
    "props": {
        "entity_id": "event:shanshangbaoxun",
        "canonical_name": "山上寶訓",
        "aliases": ["登山寶訓", "八福"],
        "description": "frozen 2026-07 text",
        "mention_count": 23,
    },
}
MANUAL = {
    "kind": "node",
    "entity_id": "event:shounanzhou",
    "labels": ["Entity", "Event"],
    "origin": "manual",
    "props": {
        "entity_id": "event:shounanzhou",
        "canonical_name": "受難週",
        "aliases": ["受苦週", "Holy Week"],
        "description": "從棕枝主日進城至釘十字架受難安葬的一週敘事",
        "mention_count": 76,
    },
}
EDGE = {"kind": "edge", "pericope_id": "mat:5:0", "entity_id": "event:shanshangbaoxun",
        "entity_name": "山上寶訓", "props": {}}

WRITE_KEYWORDS = ("MERGE", "SET ", "CREATE", "DELETE")


# ---------------------------------------------------------------------------
# merge_aliases
# ---------------------------------------------------------------------------

def test_merge_aliases_is_an_order_preserving_union_without_canonical():
    assert bmp.merge_aliases(["甲", "乙"], ["乙", "丙", "名"], "名") == ["甲", "乙", "丙"]


def test_merge_aliases_handles_missing_lists():
    assert bmp.merge_aliases(None, ["八福"], "山上寶訓") == ["八福"]
    assert bmp.merge_aliases(["八福"], None, "山上寶訓") == ["八福"]


def test_merge_aliases_is_idempotent():
    once = bmp.merge_aliases([], ["登山寶訓", "八福"], "山上寶訓")

    assert bmp.merge_aliases(once, ["登山寶訓", "八福"], "山上寶訓") == once


# ---------------------------------------------------------------------------
# overlay_nodes: offline projection of --apply
# ---------------------------------------------------------------------------

def test_extracted_node_gets_patch_aliases_after_rebuild():
    rebuilt = {"event:shanshangbaoxun": {"canonical_name": "山上寶訓", "aliases": [],
                                         "description": "rebuilt text"}}

    out = bmp.overlay_nodes(rebuilt, [EXTRACTED])

    assert out["event:shanshangbaoxun"]["aliases"] == ["登山寶訓", "八福"]


def test_extracted_node_keeps_its_own_props_and_aliases():
    rebuilt = {"event:shanshangbaoxun": {"canonical_name": "山上寶訓", "aliases": ["山上的教訓"],
                                         "description": "rebuilt text", "mention_count": 1}}

    node = bmp.overlay_nodes(rebuilt, [EXTRACTED])["event:shanshangbaoxun"]

    assert node["aliases"] == ["山上的教訓", "登山寶訓", "八福"]
    assert node["description"] == "rebuilt text"
    assert node["mention_count"] == 1


def test_overlay_does_not_mutate_its_input():
    rebuilt = {"event:shanshangbaoxun": {"canonical_name": "山上寶訓", "aliases": []}}

    bmp.overlay_nodes(rebuilt, [EXTRACTED])

    assert rebuilt == {"event:shanshangbaoxun": {"canonical_name": "山上寶訓", "aliases": []}}


def test_missing_manual_node_is_created_from_frozen_props():
    node = bmp.overlay_nodes({}, [MANUAL])["event:shounanzhou"]

    assert node["canonical_name"] == "受難週"
    assert node["aliases"] == ["受苦週", "Holy Week"]
    assert node["created_from"] == "manual_patch"
    assert node["source"] == "manual_patch"
    assert node["extraction_method"] == "curated"


def test_missing_extracted_node_fails_hard():
    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        bmp.overlay_nodes({}, [EXTRACTED])


# ---------------------------------------------------------------------------
# plan_apply / apply_nodes against a recording fake session
# ---------------------------------------------------------------------------

class _Result(list):
    def single(self):
        return self[0] if self else None


class _FakeGraphSession:
    """Answers the read queries of plan_apply and records every statement.

    ``graph`` maps entity_id → (labels, props); all pericopes exist and no
    MENTIONS edge exists yet (rebuild scenario).
    """

    def __init__(self, graph: dict, alias_update_shortfall: int = 0):
        self.graph = graph
        self.shortfall = alias_update_shortfall
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if query == bmp._NODE_STATUS_CYPHER:
            out = []
            for eid in params["ids"]:
                labels, props = self.graph.get(eid, (None, {}))
                out.append({"eid": eid, "found": labels is not None,
                            "labels": labels, "canonical_name": props.get("canonical_name"),
                            "aliases": props.get("aliases")})
            return _Result(out)
        if "OPTIONAL MATCH (p:Pericope {id: pid})" in query:
            return _Result({"pid": pid, "found": True} for pid in params["ids"])
        if "count(m) > 0 AS found" in query:
            return _Result({"pid": r["pid"], "eid": r["eid"], "found": False}
                           for r in params["rows"])
        if query == bmp._MERGE_NODE_ALIASES_CYPHER:
            return _Result([{"updated": len(params["rows"]) - self.shortfall}])
        if "MERGE (e:Entity:" in query:
            return _Result([{"merged": len(params["rows"])}])
        raise AssertionError(f"unexpected query: {query}")

    def writes(self) -> list[str]:
        return [q for q, _ in self.calls if any(k in q for k in WRITE_KEYWORDS)]


def test_plan_apply_fails_on_missing_extracted_id_before_any_write():
    session = _FakeGraphSession(graph={})

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        bmp.plan_apply(session, [EXTRACTED, MANUAL], [EDGE])

    assert session.writes() == []


def test_plan_apply_fails_when_node_exists_under_another_label():
    session = _FakeGraphSession(graph={
        "event:shanshangbaoxun": (["Theme"], {"canonical_name": "山上寶訓", "aliases": []})})

    with pytest.raises(SystemExit, match="label"):
        bmp.plan_apply(session, [EXTRACTED], [EDGE])


def test_plan_apply_reports_current_state_of_existing_nodes():
    session = _FakeGraphSession(graph={
        "event:shanshangbaoxun": (["Event"], {"canonical_name": "山上寶訓", "aliases": []})})

    plan = bmp.plan_apply(session, [EXTRACTED, MANUAL], [EDGE])

    assert [n["entity_id"] for n in plan["nodes_to_create"]] == ["event:shounanzhou"]
    assert plan["current"] == {"event:shanshangbaoxun": {"canonical_name": "山上寶訓", "aliases": []}}


def test_apply_nodes_merges_aliases_on_every_row():
    session = _FakeGraphSession(graph={})

    bmp.apply_nodes(session, [EXTRACTED, MANUAL])

    alias_calls = [p for q, p in session.calls if q == bmp._MERGE_NODE_ALIASES_CYPHER]
    assert len(alias_calls) == 1
    rows = {r["entity_id"]: r["aliases"] for r in alias_calls[0]["rows"]}
    assert rows == {"event:shanshangbaoxun": ["登山寶訓", "八福"],
                    "event:shounanzhou": ["受苦週", "Holy Week"]}
    # The alias merge must not be gated on node creation, and must use MATCH
    # so it can never create a node. It must append to the node's own
    # aliases (not replace them) and drop the canonical name. Only the
    # staging test at the bottom executes it; these pin its shape offline.
    cypher = " ".join(bmp._MERGE_NODE_ALIASES_CYPHER.split())
    assert "ON CREATE" not in cypher
    assert "MERGE" not in cypher
    assert "MATCH (e:Entity {entity_id: row.entity_id})" in cypher
    assert "SET e.aliases = apoc.coll.toSet(" in cypher
    assert "coalesce(e.aliases, []) + row.aliases" in cypher
    assert "WHERE x <> coalesce(e.canonical_name, '')" in cypher


def test_apply_nodes_only_merges_manual_rows_into_existence():
    session = _FakeGraphSession(graph={})

    bmp.apply_nodes(session, [EXTRACTED, MANUAL])

    create_calls = [p for q, p in session.calls if "MERGE (e:Entity:" in q]
    created = [r["entity_id"] for p in create_calls for r in p["rows"]]
    assert created == ["event:shounanzhou"]


def test_apply_nodes_fails_when_alias_merge_misses_a_node():
    session = _FakeGraphSession(graph={}, alias_update_shortfall=1)

    with pytest.raises(SystemExit, match="alias"):
        bmp.apply_nodes(session, [EXTRACTED, MANUAL])


# ---------------------------------------------------------------------------
# PG sync
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params=None):
        self.conn.executed.append((sql, params))
        if sql.lstrip().startswith("SELECT"):
            ids = params[0]
            self._rows = [(eid, *self.conn.rows[eid]) for eid in ids if eid in self.conn.rows]

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows: dict):
        self.rows = rows  # entity_id → (canonical_name, aliases)
        self.executed: list[tuple[str, tuple]] = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_pg_sync_updates_only_aliases_for_extracted_rows():
    conn = _FakeConn(rows={"event:shanshangbaoxun": ("山上寶訓", [])})

    bmp.sync_pg(conn, [EXTRACTED])

    writes = [(sql, p) for sql, p in conn.executed if not sql.lstrip().startswith("SELECT")]
    assert len(writes) == 1
    sql, params = writes[0]
    assert "UPDATE entities SET aliases" in sql
    assert "description" not in sql and "ON CONFLICT" not in sql
    assert json.loads(params[0]) == ["登山寶訓", "八福"]
    assert params[1] == "event:shanshangbaoxun"
    assert conn.committed


def test_pg_sync_fails_and_rolls_back_when_extracted_row_is_missing():
    conn = _FakeConn(rows={})

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        bmp.sync_pg(conn, [EXTRACTED, MANUAL])

    assert conn.rolled_back and not conn.committed
    assert all(sql.lstrip().startswith("SELECT") for sql, _ in conn.executed)


def test_pg_sync_still_upserts_manual_rows():
    conn = _FakeConn(rows={})

    bmp.sync_pg(conn, [MANUAL])

    sql, params = conn.executed[-1]
    assert "INSERT INTO entities" in sql and "ON CONFLICT" in sql
    assert params[0] == "event:shounanzhou"


# ---------------------------------------------------------------------------
# Qdrant sync
# ---------------------------------------------------------------------------

class _Point:
    def __init__(self, pid, payload):
        self.id = pid
        self.payload = payload


class _FakeQdrant:
    def __init__(self, payloads: dict):
        from embed_entities import _entity_uuid
        self._points = {_entity_uuid(eid): _Point(_entity_uuid(eid), p)
                        for eid, p in payloads.items()}
        self.set_calls: list[dict] = []

    def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
        return [self._points[i] for i in ids if i in self._points]

    def set_payload(self, collection_name, payload, points, wait=True):
        self.set_calls.append({"payload": payload, "points": list(points)})

    def close(self):
        pass


def test_qdrant_sync_sets_only_aliases_for_extracted_rows():
    # Live payloads still hold the legacy JSON-string form ("[]").
    client = _FakeQdrant({"event:shanshangbaoxun": {
        "entity_id": "event:shanshangbaoxun", "canonical_name": "山上寶訓",
        "aliases": "[]", "description": "rebuilt text"}})

    bmp.sync_qdrant_aliases(client, [EXTRACTED, MANUAL])

    from embed_entities import _entity_uuid
    assert client.set_calls == [{"payload": {"aliases": ["登山寶訓", "八福"]},
                                 "points": [_entity_uuid("event:shanshangbaoxun")]}]


def test_qdrant_sync_fails_before_writing_when_point_is_missing():
    client = _FakeQdrant({})

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        bmp.sync_qdrant_aliases(client, [EXTRACTED])

    assert client.set_calls == []


# ---------------------------------------------------------------------------
# --export honours --dry-run
# ---------------------------------------------------------------------------

class _ExportSession:
    def run(self, query: str, **params):
        if query == bmp._EXPORT_EDGES_CYPHER:
            return _Result([{"pericope_id": "mat:5:0", "pericope_label": "Pericope",
                             "entity_id": "event:shanshangbaoxun", "entity_name": "山上寶訓",
                             "props": {}}])
        if query == bmp._EXPORT_NODES_CYPHER:
            return _Result([{"entity_id": "event:shanshangbaoxun",
                             "labels": ["Entity", "Event"], "props": EXTRACTED["props"]}])
        raise AssertionError(f"unexpected query: {query}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _ExportDriver:
    def session(self):
        return _ExportSession()

    def close(self):
        pass


@pytest.fixture
def entities_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "entities.jsonl"
    path.write_text(json.dumps({"entity_id": "event:shanshangbaoxun"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(bmp, "ENTITIES_JSONL", path)
    return path


def test_export_dry_run_writes_nothing(tmp_path, entities_jsonl):
    out = tmp_path / "patches.jsonl"

    counts = bmp.export_patches(_ExportSession(), out, dry_run=True)

    assert counts == (1, 1)
    assert not out.exists()


def test_export_cli_passes_dry_run_through(tmp_path, entities_jsonl, monkeypatch):
    out = tmp_path / "patches.jsonl"
    monkeypatch.setattr(bmp, "get_neo4j", lambda: _ExportDriver())
    monkeypatch.setattr(sys, "argv", ["backfill_manual_patches.py", "--export",
                                      "--dry-run", "--patch-file", str(out)])

    assert bmp.main() == 0
    assert not out.exists()


def test_export_without_dry_run_still_writes(tmp_path, entities_jsonl):
    out = tmp_path / "patches.jsonl"

    bmp.export_patches(_ExportSession(), out)

    kinds = [json.loads(line)["kind"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["meta", "node", "edge"]


# ---------------------------------------------------------------------------
# run_apply: PG/Qdrant preflight before any write, store aliases in the backup
# ---------------------------------------------------------------------------

class _ApplySession(_FakeGraphSession):
    """Also answers the backup, edge-write and smoke-test statements."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query: str, **params):
        if "m IS NOT NULL AS existed" in query:
            self.calls.append((query, params))
            return _Result({"pericope_id": r["pid"], "entity_id": r["eid"],
                            "existed": False, "props_before": None} for r in params["rows"])
        if "MERGE (p)-[m:MENTIONS]->(e)" in query:
            self.calls.append((query, params))
            return _Result([{"written": len(params["rows"])}])
        if "count(r) AS left" in query:
            self.calls.append((query, params))
            return _Result([{"left": 0}])
        return super().run(query, **params)


class _ApplyDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session

    def close(self):
        pass


LIVE_GRAPH = {"event:shanshangbaoxun": (["Event"], {"canonical_name": "山上寶訓", "aliases": []})}


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Fake PG/Qdrant holding the extracted row; manual 受難週 absent everywhere."""
    patch_file = tmp_path / "patches.jsonl"
    patch_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                  for r in (EXTRACTED, MANUAL, EDGE)), encoding="utf-8")
    backups = tmp_path / "backups"
    monkeypatch.setattr(bmp, "BACKUP_DIR", backups)

    class Stores:
        session = _ApplySession(graph=dict(LIVE_GRAPH))
        conn = _FakeConn(rows={"event:shanshangbaoxun": ("山上寶訓", [])})
        qdrant = _FakeQdrant({"event:shanshangbaoxun": {
            "entity_id": "event:shanshangbaoxun", "canonical_name": "山上寶訓", "aliases": "[]"}})
        reembedded: list[list[str]] = []

        def __init__(self):
            self.patch_file = patch_file
            self.backups = backups

        def run(self, **flags):
            args = argparse.Namespace(**{"dry_run": False, "skip_pg": False,
                                         "skip_qdrant": False, **flags})
            bmp.run_apply(_ApplyDriver(self.session), self.patch_file, args)

        def untouched(self) -> bool:
            return (self.session.writes() == [] and not self.conn.committed
                    and self.qdrant.set_calls == [] and self.reembedded == []
                    and not self.backups.exists())

    st = Stores()
    monkeypatch.setattr(bmp, "get_pg", lambda: st.conn)
    monkeypatch.setattr(bmp, "get_qdrant", lambda: st.qdrant)
    monkeypatch.setattr(bmp, "reembed_qdrant", lambda ids: st.reembedded.append(list(ids)))
    return st


def test_missing_pg_row_stops_apply_before_any_store_is_written(stores):
    stores.conn.rows = {}

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        stores.run()

    assert stores.untouched()


def test_missing_qdrant_point_stops_apply_before_any_store_is_written(stores):
    # Before the preflight, Neo4j and PG were written and the manual points
    # re-embedded before sync_qdrant_aliases noticed the missing point.
    stores.qdrant = _FakeQdrant({})

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        stores.run()

    assert stores.untouched()


def test_dry_run_reports_a_missing_store_row_too(stores):
    stores.conn.rows = {}

    with pytest.raises(SystemExit, match="event:shanshangbaoxun"):
        stores.run(dry_run=True)

    assert stores.untouched()


def test_skipped_stores_are_not_preflighted(stores, monkeypatch):
    def _no_store():
        raise AssertionError("a skipped store was contacted")
    monkeypatch.setattr(bmp, "get_pg", _no_store)
    monkeypatch.setattr(bmp, "get_qdrant", _no_store)

    stores.run(skip_pg=True, skip_qdrant=True)

    assert stores.session.writes()


def test_apply_backs_up_every_stores_aliases_before_writing(stores):
    stores.run()

    (backup,) = stores.backups.iterdir()
    rows = {r["entity_id"]: r for r in map(json.loads, backup.read_text(encoding="utf-8").splitlines())
            if r["kind"] == "node"}
    assert rows["event:shanshangbaoxun"]["aliases_before"] == []
    assert rows["event:shanshangbaoxun"]["pg"] == {"existed": True, "aliases_before": []}
    # The raw payload value, legacy JSON string included, so a restore is exact.
    assert rows["event:shanshangbaoxun"]["qdrant"] == {"existed": True, "aliases_before": "[]"}
    assert rows["event:shounanzhou"]["pg"] == {"existed": False, "aliases_before": None}
    assert rows["event:shounanzhou"]["qdrant"] == {"existed": False, "aliases_before": None}
    # ...and the writes still happen afterwards.
    assert stores.conn.committed
    assert stores.reembedded == [["event:shounanzhou"]]
    assert stores.qdrant.set_calls


def test_backup_marks_skipped_stores(stores):
    stores.run(skip_pg=True, skip_qdrant=True)

    (backup,) = stores.backups.iterdir()
    node = next(r for r in map(json.loads, backup.read_text(encoding="utf-8").splitlines())
                if r["kind"] == "node")
    assert node["pg"] is None and node["qdrant"] is None


# ---------------------------------------------------------------------------
# Store targets
# ---------------------------------------------------------------------------

def test_qdrant_endpoint_is_shared_with_10_4():
    # One QDRANT_PORT-over-QDRANT_HTTP_PORT rule for both curated replays.
    assert bmp.get_qdrant is bhe.get_qdrant


def _no_connection():
    raise AssertionError("connected before the target guard ran")


def test_main_refuses_a_staging_run_that_reaches_production(monkeypatch):
    for name, value in {"KG_TARGET": "staging", "NEO4J_URI": "bolt://localhost:7688",
                        "POSTGRES_DB": "bible_rag_staging",
                        "QDRANT_ENTITY_COLLECTION": "bible_entities"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(bmp, "get_neo4j", _no_connection)
    monkeypatch.setattr(sys, "argv", ["backfill_manual_patches.py", "--apply", "--dry-run"])

    with pytest.raises(SystemExit, match="QDRANT_ENTITY_COLLECTION"):
        bmp.main()


@pytest.mark.parametrize("argv", [["--apply"], ["--apply", "--skip-pg", "--skip-qdrant"],
                                  ["--export", "--dry-run"]])
def test_main_guards_every_store_in_every_mode(monkeypatch, argv):
    import kg_target
    seen = []

    def _record(*stores):
        seen.append(stores)
        raise SystemExit("stop after the guard")
    monkeypatch.setattr(kg_target, "assert_target", _record)
    monkeypatch.setattr(bmp, "get_neo4j", _no_connection)
    monkeypatch.setattr(sys, "argv", ["backfill_manual_patches.py", *argv])

    with pytest.raises(SystemExit, match="stop after the guard"):
        bmp.main()

    assert seen == [("neo4j", "postgres", "qdrant")]


# ---------------------------------------------------------------------------
# Opt-in: the real alias Cypher on a writable staging Neo4j
# ---------------------------------------------------------------------------

STAGING_NEO4J = os.getenv("KG_TEST_NEO4J_URI")


@pytest.fixture
def staging_session(monkeypatch):
    """Session on KG_TEST_NEO4J_URI; its fixture nodes are deleted afterwards.

    The URI goes through kg_target first, so a production URI fails the test
    instead of writing there. Nodes use a per-run entity_id prefix and touch
    nothing else in the graph.
    """
    import kg_target
    from neo4j import GraphDatabase

    monkeypatch.setenv("KG_TARGET", "staging")
    monkeypatch.setenv("NEO4J_URI", STAGING_NEO4J)
    kg_target.assert_target("neo4j")

    prefix = f"kgtest{uuid.uuid4().hex[:8]}:"
    driver = GraphDatabase.driver(STAGING_NEO4J, auth=(
        os.getenv("KG_TEST_NEO4J_USER", "neo4j"),
        os.getenv("KG_TEST_NEO4J_PASSWORD", "neo4j_password")))
    try:
        with driver.session() as session:
            yield session, prefix
            session.run("MATCH (e:Entity) WHERE e.entity_id STARTS WITH $p DETACH DELETE e",
                        p=prefix).consume()
    finally:
        driver.close()


@pytest.mark.skipif(not STAGING_NEO4J, reason="set KG_TEST_NEO4J_URI to a writable staging Neo4j")
def test_alias_cypher_matches_its_python_twin_on_staging(staging_session):
    session, prefix = staging_session
    graph = {
        f"{prefix}kept": {"canonical_name": "山上寶訓", "aliases": ["山上的教訓", "八福"]},
        f"{prefix}empty": {"canonical_name": "保羅敘述歸主的經過", "aliases": []},
        f"{prefix}null": {"canonical_name": "掃羅歸主", "aliases": None},
    }
    session.run("UNWIND $rows AS row CREATE (e:Entity:Event) "
                "SET e.entity_id = row.id, e.canonical_name = row.name, e.aliases = row.aliases",
                rows=[{"id": eid, "name": p["canonical_name"], "aliases": p["aliases"]}
                      for eid, p in graph.items()]).consume()
    nodes = [
        {**EXTRACTED, "entity_id": f"{prefix}kept",
         "props": {"aliases": ["登山寶訓", "八福", "山上寶訓"]}},
        {**EXTRACTED, "entity_id": f"{prefix}empty", "props": {"aliases": ["保羅歸主"]}},
        {**EXTRACTED, "entity_id": f"{prefix}null", "props": {"aliases": ["保羅歸主"]}},
        {**MANUAL, "entity_id": f"{prefix}manual",
         "props": {**MANUAL["props"], "entity_id": f"{prefix}manual"}},
    ]

    for _ in range(2):  # a replay must be idempotent
        bmp.apply_nodes(session, nodes)

    stored = {r["id"]: dict(r) for r in session.run(
        "MATCH (e:Entity) WHERE e.entity_id STARTS WITH $p "
        "RETURN e.entity_id AS id, e.canonical_name AS canonical_name, e.aliases AS aliases, "
        "       e.source AS source, e.extraction_method AS extraction_method, "
        "       e.created_from AS created_from", p=prefix)}
    expected = bmp.overlay_nodes(graph, nodes)
    for eid, props in expected.items():
        for key in ("canonical_name", "aliases", "source", "extraction_method", "created_from"):
            assert stored[eid][key] == props.get(key), (eid, key)
    assert stored[f"{prefix}kept"]["aliases"] == ["山上的教訓", "八福", "登山寶訓"]
