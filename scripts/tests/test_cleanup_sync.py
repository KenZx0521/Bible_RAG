"""cleanup_noise_entities: staging never skips the PG/Qdrant sync silently.

The fakes keep state: all three stores start with one generic Event
(event:rizi, 日子) and with group:yehehua typed Group. A write either lands or
raises, so a failed run leaves the partial state a real one would. Qdrant
raises for any collection but bible_entities_v2, so every test also checks
that the sync follows QDRANT_ENTITY_COLLECTION.

Split from test_db_env.py (see test_db_env_contract.py). As there,
cleanup_noise_entities is imported at collection time, so its import-time
load_dotenv() never runs inside a monkeypatched test.
"""

import itertools
import sys
from types import SimpleNamespace

import psycopg2
import pytest
import qdrant_client
from qdrant_client import models

import cleanup_noise_entities
# staging_target is a pytest fixture: importing it is what makes it available here.
from _db_env_helpers import _FakeQdrant, staging_target  # noqa: F401

RIZI, YEHEHUA = "event:rizi", "group:yehehua"
RIZI_POINT = cleanup_noise_entities.entity_uuid(RIZI)
YEHEHUA_POINT = cleanup_noise_entities.entity_uuid(YEHEHUA)
SYNC_ACTIONS = ["generic-events", "yehehua"]
STORE_NAME = {"postgres": "Postgres", "qdrant": "Qdrant"}


def _rows(rows):
    return SimpleNamespace(single=lambda: rows[0] if rows else None, data=lambda: rows)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass

    commit = rollback = close


class _FakeNeo4j(_Context):
    """Driver, session and result in one; records Cypher."""

    def __init__(self):
        self.cypher = []
        self.events = [{"entity_id": RIZI, "name": "日子", "mc": 1, "props": {}, "rels": []}]
        self.labels = ["Entity", "Group"]

    def session(self):
        return self

    def run(self, cypher, **params):
        self.cypher.append(cypher)
        if "DETACH DELETE" in cypher:
            kept = [e for e in self.events if e["entity_id"] not in params["ids"]]
            deleted, self.events = len(self.events) - len(kept), kept
            return _rows([{"deleted": deleted}])
        if "SET e:Person" in cypher:
            self.labels = ["Entity", "Person"]
        if "IN $stop" in cypher:
            return _rows([dict(e) for e in self.events])
        return _rows([{"labels": list(self.labels)}])


class _FakePostgres(_Context):
    """Connection and cursor in one; DELETE/UPDATE raise while fail_writes is set."""

    def __init__(self):
        self.fail_writes = False
        self.tables = {"entities", "entity_mentions"}
        self.entities = {RIZI: ("Event", "日子"), YEHEHUA: ("Group", "耶和華")}
        self.rows, self.rowcount = [], 0

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        if self.fail_writes and sql.startswith(("DELETE", "UPDATE")):
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.rowcount = 0
        if "to_regclass" in sql:
            self.rows = [(params[0] if params[0] in self.tables else None,)]
        elif sql.startswith("SELECT entity_id FROM entities"):
            self.rows = [(eid,) for eid, (kind, name) in self.entities.items()
                         if kind == "Event" and name in params[0]]
        elif sql.startswith("DELETE FROM entities"):
            self.rowcount = sum(self.entities.pop(eid, None) is not None for eid in params[0])
        elif sql.startswith("UPDATE entities SET type = 'Person'") and YEHEHUA in self.entities:
            self.entities[YEHEHUA], self.rowcount = ("Person", "耶和華"), 1

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


def _selects(point_id, payload, selector) -> bool:
    if not isinstance(selector, models.Filter):
        return point_id in selector
    for cond in selector.must:
        if isinstance(cond, models.HasIdCondition):
            allowed, value = cond.has_id, point_id
        else:
            allowed = cond.match.any if isinstance(cond.match, models.MatchAny) else [cond.match.value]
            value = payload.get(cond.key)
        if value not in allowed:
            return False
    return True


class _FakeQdrantStore(_Context, _FakeQdrant):
    """One entity collection; an id-list set_payload on a missing point fails
    like the server's 404, a Filter selector skips it."""

    def __init__(self):
        self.fail_writes = False
        self.collections = {"bible_entities_v2"}
        self.points = {
            RIZI_POINT: {"entity_id": RIZI, "type": "Event", "canonical_name": "日子"},
            YEHEHUA_POINT: {"entity_id": YEHEHUA, "type": "Group", "canonical_name": "耶和華"},
        }
        self.writes = []

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def _select(self, collection_name, selector):
        if collection_name not in self.collections:
            raise ValueError(f"Collection `{collection_name}` doesn't exist")
        return [pid for pid, payload in self.points.items() if _selects(pid, payload, selector)]

    def _write(self, kind, collection_name):
        if self.fail_writes:
            raise ConnectionError("qdrant went away")
        self.writes.append((kind, collection_name))

    def scroll(self, collection_name, scroll_filter, offset=None, **kwargs):
        selected = self._select(collection_name, scroll_filter)
        return [SimpleNamespace(id=pid, payload=self.points[pid]) for pid in selected], None

    def delete(self, collection_name, points_selector, wait=True):
        self._write("delete", collection_name)
        for pid in self._select(collection_name, points_selector):
            del self.points[pid]

    def set_payload(self, collection_name, payload, points, wait=True):
        self._write("set_payload", collection_name)
        missing = [] if isinstance(points, models.Filter) else set(points) - set(self.points)
        if missing:
            raise ValueError(f"No point with id {sorted(missing)[0]} found")
        for pid in self._select(collection_name, points):
            self.points[pid] = {**self.points[pid], **payload}


_CONNECT = {"postgres": (psycopg2, "connect"), "qdrant": (qdrant_client, "QdrantClient")}


def _connect(monkeypatch, store, factory):
    monkeypatch.setattr(*_CONNECT[store], factory)


def _unreachable(*args, **kwargs):
    raise psycopg2.OperationalError("could not connect to server: Connection refused")


@pytest.fixture
def cleanup_stores(monkeypatch, tmp_path):
    """Fake Neo4j/PG/Qdrant behind cleanup_noise_entities; backups go to tmp_path."""
    stores = {"neo4j": _FakeNeo4j(), "postgres": _FakePostgres(), "qdrant": _FakeQdrantStore()}
    monkeypatch.setenv("QDRANT_ENTITY_COLLECTION", "bible_entities_v2")
    monkeypatch.setattr(cleanup_noise_entities, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(cleanup_noise_entities, "get_neo4j", lambda: stores["neo4j"])
    for store in _CONNECT:
        _connect(monkeypatch, store, lambda *a, store=store, **k: stores[store])
    return stores


def _cleanup(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["cleanup_noise_entities.py", *args])
    return cleanup_noise_entities.main()


def _synced(stores, action):
    """Per store: has the action's change landed there?"""
    neo4j, pg, qdrant = stores["neo4j"], stores["postgres"], stores["qdrant"]
    if action == "generic-events":
        return {"neo4j": not neo4j.events, "postgres": RIZI not in pg.entities,
                "qdrant": RIZI_POINT not in qdrant.points}
    return {"neo4j": "Person" in neo4j.labels, "postgres": pg.entities[YEHEHUA][0] == "Person",
            "qdrant": qdrant.points[YEHEHUA_POINT]["type"] == "Person"}


ALL_SYNCED = {"neo4j": True, "postgres": True, "qdrant": True}


@pytest.mark.parametrize("breakage, message", [
    ("postgres down", "Postgres"),
    ("qdrant down", "Qdrant"),
    ("no entities table", "entities"),
    ("no entity_mentions table", "entity_mentions"),
    ("no entity collection", "bible_entities_v2"),
])
def test_cleanup_staging_stops_before_neo4j_when_a_sync_store_cannot_take_it(
        breakage, message, cleanup_stores, staging_target, monkeypatch):
    """Answering is not enough: a missing table or collection fails the sync the same way."""
    if breakage.endswith("down"):
        _connect(monkeypatch, breakage.split()[0], _unreachable)
    elif breakage.endswith("table"):
        cleanup_stores["postgres"].tables.discard(breakage.split()[1])
    else:
        cleanup_stores["qdrant"].collections.clear()

    with pytest.raises(SystemExit) as exc:
        _cleanup(monkeypatch, "--actions", "generic-events,yehehua")

    assert message in str(exc.value)
    assert cleanup_stores["neo4j"].cypher == []


# Connections after the preflight's (call 1): generic-events reads the ids PG
# and Qdrant still hold (call 2), then syncs (call 3); yehehua only syncs.
MID_RUN_CONNECTIONS = [("generic-events", 2), ("generic-events", 3), ("yehehua", 2)]


@pytest.mark.parametrize("store", ["postgres", "qdrant"])
@pytest.mark.parametrize("action, nth", MID_RUN_CONNECTIONS)
def test_cleanup_staging_fails_hard_when_a_store_drops_mid_run(
        action, nth, store, cleanup_stores, staging_target, monkeypatch):
    """The preflight passed; a connection lost later must still stop the run."""
    calls = itertools.count(1)

    def connect(*args, **kwargs):
        if next(calls) == nth:
            raise ConnectionError(f"{store} went away")
        return cleanup_stores[store]
    _connect(monkeypatch, store, connect)

    with pytest.raises(SystemExit) as exc:
        _cleanup(monkeypatch, "--actions", action)

    assert STORE_NAME[store] in str(exc.value)
    assert next(calls) == nth + 1   # the failing connection was the last one tried


@pytest.mark.parametrize("failing", ["postgres", "qdrant"])
@pytest.mark.parametrize("action", SYNC_ACTIONS)
def test_cleanup_staging_rerun_finishes_an_interrupted_sync(
        action, failing, cleanup_stores, staging_target, monkeypatch):
    """A failed sync write stops the run. Neo4j is written first, so the rerun
    finds it clean; the sync must happen anyway."""
    cleanup_stores[failing].fail_writes = True
    with pytest.raises(SystemExit, match=STORE_NAME[failing]):
        _cleanup(monkeypatch, "--actions", action)
    interrupted = _synced(cleanup_stores, action)
    assert interrupted["neo4j"] and not interrupted[failing]

    cleanup_stores[failing].fail_writes = False
    assert _cleanup(monkeypatch, "--actions", action) == 0

    assert _synced(cleanup_stores, action) == ALL_SYNCED


@pytest.mark.parametrize("holder", ["postgres", "qdrant"])
def test_cleanup_staging_deletes_a_generic_event_only_one_store_still_holds(
        holder, cleanup_stores, staging_target, monkeypatch):
    cleanup_stores["neo4j"].events = []
    if holder == "postgres":
        del cleanup_stores["qdrant"].points[RIZI_POINT]
    else:
        del cleanup_stores["postgres"].entities[RIZI]

    assert _cleanup(monkeypatch, "--actions", "generic-events") == 0
    assert _synced(cleanup_stores, "generic-events") == ALL_SYNCED


def test_cleanup_staging_relabel_treats_a_point_qdrant_lacks_as_done(
        cleanup_stores, staging_target, monkeypatch):
    """An id-list set_payload would 404; syncing a target id must be a no-op instead."""
    del cleanup_stores["qdrant"].points[YEHEHUA_POINT]

    assert _cleanup(monkeypatch, "--actions", "yehehua") == 0

    assert cleanup_stores["postgres"].entities[YEHEHUA][0] == "Person"
    assert YEHEHUA_POINT not in cleanup_stores["qdrant"].points


@pytest.mark.parametrize("action, skipped", [("generic-events", "Nothing matched"),
                                             ("yehehua", "Already relabeled — skip")])
def test_cleanup_prod_still_decides_the_sync_from_neo4j_alone(
        action, skipped, cleanup_stores, monkeypatch, capsys):
    monkeypatch.delenv("KG_TARGET", raising=False)
    cleanup_stores["neo4j"].events, cleanup_stores["neo4j"].labels = [], ["Entity", "Person"]
    connected = []
    for store in _CONNECT:
        _connect(monkeypatch, store, lambda *a, store=store, **k: connected.append(store))

    assert _cleanup(monkeypatch, "--actions", action) == 0

    assert skipped in capsys.readouterr().out
    assert connected == []


def test_cleanup_staging_dry_run_needs_no_sync_store(cleanup_stores, staging_target, monkeypatch):
    """A dry run writes nothing, so it must stay usable while PG is down."""
    _connect(monkeypatch, "postgres", _unreachable)

    # Not dan: it reads output/entity_mentions.jsonl, and it never syncs anyway.
    assert _cleanup(monkeypatch, "--dry-run", "--actions", "generic-events,yehehua") == 0
    assert _synced(cleanup_stores, "generic-events") == {k: False for k in ALL_SYNCED}


def test_cleanup_prod_still_warns_and_carries_on_without_postgres(cleanup_stores, monkeypatch, capsys):
    monkeypatch.delenv("KG_TARGET", raising=False)
    _connect(monkeypatch, "postgres", _unreachable)

    assert _cleanup(monkeypatch, "--actions", "yehehua") == 0

    assert "⚠ Postgres unavailable" in capsys.readouterr().out
    assert any("SET e:Person" in c for c in cleanup_stores["neo4j"].cypher)
    assert cleanup_stores["qdrant"].writes == [("set_payload", "bible_entities_v2")]
