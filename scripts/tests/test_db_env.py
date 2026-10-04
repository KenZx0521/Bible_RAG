"""DB connection settings honour the staging env vars (plan §3.7 R1).

A staging rebuild points every script at the staging stores purely through
env vars (scripts/tools/staging.env: NEO4J_URI=bolt://localhost:7688,
POSTGRES_DB=bible_rag_staging, QDRANT_ENTITY_COLLECTION=bible_entities_vN).
A script that ignores one of them silently writes the production store
instead, so each connection point is checked by capturing what the client
constructor receives.

The scripts call load_dotenv() at import time. They are imported here at
collection time, as the other test modules do, so .env is read once against
the real environment and never from inside a monkeypatched test.
"""

import importlib.util
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable

import dotenv
import psycopg2
import pytest
import qdrant_client
from qdrant_client import models

import backfill_aliases
import backfill_event_relations
import backfill_verse_mentions
import cleanup_noise_entities
import embed_entities
import import_postgres
import import_qdrant
import import_qdrant_hybrid
import import_relations_neo4j
import import_tsk_crossrefs
import kg_target
from scripts.relation_extraction import extract_relations
from scripts.relation_extraction.config import Neo4jConfig

SCRIPTS = Path(__file__).resolve().parents[1]


class _Stop(Exception):
    """Raised by a fake client once its constructor arguments are captured."""


def _capturing(store: dict, *, stop: bool = False, result=None):
    def factory(*args, **kwargs):
        store["args"], store["kwargs"] = args, kwargs
        if stop:
            raise _Stop
        return result
    return factory


class _FakeQdrant:
    def get_collections(self):
        return None


@pytest.fixture
def staging_env(monkeypatch):
    env = {
        "NEO4J_URI": "bolt://staging-host:7688",
        "NEO4J_USER": "stage_user",
        "NEO4J_PASSWORD": "stage_pw",
        "POSTGRES_HOST": "pg-host",
        "POSTGRES_PORT": "15432",
        "POSTGRES_DB": "bible_rag_staging",
        "POSTGRES_USER": "pg_user",
        "POSTGRES_PASSWORD": "pg_pw",
        "QDRANT_HOST": "qdrant-host",
        "QDRANT_PORT": "16333",
        "QDRANT_HTTP_PORT": "26333",
    }
    monkeypatch.delenv("KG_TARGET", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


# --- Qdrant -----------------------------------------------------------------

def _qdrant_kwargs_import_qdrant(monkeypatch):
    store = {}
    monkeypatch.setattr(import_qdrant, "QdrantClient", _capturing(store))
    import_qdrant.get_qdrant_client()
    return store["kwargs"]


def _qdrant_kwargs_import_qdrant_hybrid(monkeypatch):
    store = {}
    monkeypatch.setattr(import_qdrant_hybrid, "QdrantClient", _capturing(store))
    import_qdrant_hybrid.get_qdrant_client()
    return store["kwargs"]


def _qdrant_kwargs_cleanup_noise_entities(monkeypatch):
    store = {}
    monkeypatch.setattr(qdrant_client, "QdrantClient", _capturing(store, result=_FakeQdrant()))
    assert cleanup_noise_entities.get_qdrant() is not None
    return store["kwargs"]


def _qdrant_kwargs_embed_entities(monkeypatch):
    store = {}
    monkeypatch.setattr(embed_entities, "QdrantClient", _capturing(store, stop=True))
    monkeypatch.setattr(sys, "argv", ["embed_entities.py"])
    with pytest.raises(_Stop):
        embed_entities.main()
    return store["kwargs"]


QDRANT_CONNECTORS = {
    "import_qdrant": _qdrant_kwargs_import_qdrant,
    "import_qdrant_hybrid": _qdrant_kwargs_import_qdrant_hybrid,
    "cleanup_noise_entities": _qdrant_kwargs_cleanup_noise_entities,
    "embed_entities": _qdrant_kwargs_embed_entities,
}


@pytest.mark.parametrize("script", sorted(QDRANT_CONNECTORS))
def test_qdrant_port_wins_over_http_port(script, staging_env, monkeypatch):
    kwargs = QDRANT_CONNECTORS[script](monkeypatch)

    assert kwargs["host"] == "qdrant-host"
    assert int(kwargs["port"]) == 16333


@pytest.mark.parametrize("script", sorted(QDRANT_CONNECTORS))
def test_qdrant_http_port_still_honoured_without_qdrant_port(script, staging_env, monkeypatch):
    """.env and docker-compose.yml only define QDRANT_HTTP_PORT."""
    monkeypatch.delenv("QDRANT_PORT")

    kwargs = QDRANT_CONNECTORS[script](monkeypatch)

    assert int(kwargs["port"]) == 26333


def _fresh_import(name, monkeypatch):
    """Execute scripts/<name>.py again as a separate module object.

    Collection names are read at import time. Reloading the shared module would
    re-run load_dotenv() and leave .env values in os.environ for later tests;
    a private copy with load_dotenv stubbed out reads only the patched env.
    """
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    spec = importlib.util.spec_from_file_location(f"_fresh_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_passage_collection_follows_backend_setting(monkeypatch):
    """Same env name as backend/config.py qdrant_collection."""
    monkeypatch.setenv("QDRANT_COLLECTION", "bible_embeddings_staging")

    assert _fresh_import("import_qdrant", monkeypatch).COLLECTION_NAME == "bible_embeddings_staging"


def test_hybrid_collection_follows_env(monkeypatch):
    monkeypatch.setenv("QDRANT_HYBRID_COLLECTION", "bible_embeddings_hybrid_staging")

    module = _fresh_import("import_qdrant_hybrid", monkeypatch)

    assert module.COLLECTION_NAME == "bible_embeddings_hybrid_staging"


def test_entity_collection_follows_env(monkeypatch):
    """backfill_head_events/backfill_manual_patches re-embed via this constant."""
    monkeypatch.setenv("QDRANT_ENTITY_COLLECTION", "bible_entities_v2")

    assert _fresh_import("embed_entities", monkeypatch).COLLECTION_NAME == "bible_entities_v2"


# --- Neo4j ------------------------------------------------------------------

def _neo4j_get_driver(module, func_name):
    def connect(monkeypatch):
        store = {}
        monkeypatch.setattr(module.GraphDatabase, "driver", _capturing(store))
        getattr(module, func_name)()
        return store
    return connect


def _neo4j_relation_extraction(monkeypatch):
    cfg = Neo4jConfig.from_env()
    return {"args": (cfg.uri,), "kwargs": {"auth": (cfg.user, cfg.password)}}


NEO4J_CONNECTORS = {
    "backfill_aliases": _neo4j_get_driver(backfill_aliases, "get_driver"),
    "backfill_event_relations": _neo4j_get_driver(backfill_event_relations, "get_driver"),
    "backfill_verse_mentions": _neo4j_get_driver(backfill_verse_mentions, "get_driver"),
    "import_tsk_crossrefs": _neo4j_get_driver(import_tsk_crossrefs, "get_driver"),
    "cleanup_noise_entities": _neo4j_get_driver(cleanup_noise_entities, "get_neo4j"),
    "relation_extraction.config": _neo4j_relation_extraction,
}


@pytest.mark.parametrize("script", sorted(NEO4J_CONNECTORS))
def test_neo4j_settings_follow_env(script, staging_env, monkeypatch):
    store = NEO4J_CONNECTORS[script](monkeypatch)

    assert store["args"][0] == "bolt://staging-host:7688"
    assert store["kwargs"]["auth"] == ("stage_user", "stage_pw")


def test_import_relations_neo4j_follows_env(staging_env, monkeypatch, tmp_path):
    rel = tmp_path / "relations.jsonl"
    rel.write_text('{"relation": "FATHER_OF"}\n', encoding="utf-8")
    store = {}
    monkeypatch.setattr(import_relations_neo4j.GraphDatabase, "driver", _capturing(store, stop=True))
    monkeypatch.setattr(sys, "argv", ["import_relations_neo4j.py", str(rel)])

    with pytest.raises(_Stop):
        import_relations_neo4j.main()

    assert store["args"][0] == "bolt://staging-host:7688"
    assert store["kwargs"]["auth"] == ("stage_user", "stage_pw")


def test_embed_entities_neo4j_follows_env(staging_env, monkeypatch):
    store = {}
    monkeypatch.setattr(embed_entities, "QdrantClient", _capturing({}, result=_FakeQdrant()))
    monkeypatch.setattr(embed_entities, "_ensure_collection", lambda client, recreate: None)
    monkeypatch.setattr(embed_entities.GraphDatabase, "driver", _capturing(store, stop=True))
    monkeypatch.setattr(sys, "argv", ["embed_entities.py"])

    with pytest.raises(_Stop):
        embed_entities.main()

    assert store["args"][0] == "bolt://staging-host:7688"
    assert store["kwargs"]["auth"] == ("stage_user", "stage_pw")


# --- PostgreSQL ---------------------------------------------------------------

def _pg_import_postgres(monkeypatch):
    store = {}
    monkeypatch.setattr(import_postgres.psycopg2, "connect", _capturing(store))
    import_postgres.get_db_connection()
    return store["kwargs"]


def _pg_cleanup(monkeypatch):
    store = {}
    monkeypatch.setattr(psycopg2, "connect", _capturing(store, result=object()))
    assert cleanup_noise_entities.get_postgres() is not None
    return store["kwargs"]


def _pg_extract_relations(monkeypatch):
    store = {}
    monkeypatch.setattr(extract_relations.psycopg2, "connect", _capturing(store))
    extract_relations._build_pg_connection()
    return store["kwargs"]


PG_CONNECTORS = {
    "import_postgres": _pg_import_postgres,
    "cleanup_noise_entities": _pg_cleanup,
    "relation_extraction.extract_relations": _pg_extract_relations,
}


@pytest.mark.parametrize("script", sorted(PG_CONNECTORS))
def test_postgres_settings_follow_env(script, staging_env, monkeypatch):
    kwargs = PG_CONNECTORS[script](monkeypatch)

    assert kwargs["host"] == "pg-host"
    assert int(kwargs["port"]) == 15432
    assert kwargs.get("dbname", kwargs.get("database")) == "bible_rag_staging"
    assert kwargs["user"] == "pg_user"
    assert kwargs["password"] == "pg_pw"


@pytest.mark.parametrize("script", sorted(PG_CONNECTORS))
def test_postgres_fallbacks_match_compose(script, monkeypatch):
    """Without .env the fallbacks must be docker-compose.yml's, not postgres/'' (which
    made cleanup_noise_entities skip its PG sync silently)."""
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    kwargs = PG_CONNECTORS[script](monkeypatch)

    assert kwargs["host"] == "localhost"
    assert int(kwargs["port"]) == 5432
    assert kwargs.get("dbname", kwargs.get("database")) == "bible_rag"
    assert kwargs["user"] == "bible"
    assert kwargs["password"] == "bible_password"


# --- KG_TARGET=staging: every write script refuses before it connects ---------
#
# Each writer's connection points are replaced by a recorder that stops the run
# at the first call. A refused run must reach none of them; a run with isolated
# staging settings (or without KG_TARGET) must reach one, which shows the
# recorders sit where the script really connects.

STAGING_TARGET = {
    "KG_TARGET": "staging",
    "NEO4J_URI": "bolt://localhost:7688",
    "POSTGRES_DB": "bible_rag_staging",
    "QDRANT_ENTITY_COLLECTION": "bible_entities_v2",
}
PRODUCTION_SETTING = {  # store -> (variable, production value)
    "neo4j": ("NEO4J_URI", "bolt://localhost:7687"),
    "postgres": ("POSTGRES_DB", "bible_rag"),
    "qdrant": ("QDRANT_ENTITY_COLLECTION", "bible_entities"),
}


@dataclass(frozen=True)
class Writer:
    module: ModuleType
    stores: tuple[str, ...]
    connections: tuple[tuple[object, str], ...]   # (owner, attribute) the script connects through
    argv: Callable[[Path], list[str]] = lambda tmp: []  # creates the inputs main() needs
    stubs: tuple[tuple[object, str, object], ...] = ()


def _file(path: Path, text: str = "") -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def _output_dir_with(files: dict[str, str]) -> Callable[[Path], list[str]]:
    def argv(tmp: Path) -> list[str]:
        for name, text in files.items():
            _file(tmp / name, text)
        return ["--output-dir", str(tmp)]
    return argv


_CLEANUP_CONNECTIONS = tuple((cleanup_noise_entities, name)
                             for name in ("get_neo4j", "get_qdrant", "get_postgres"))

WRITERS = {
    "import_postgres": Writer(
        import_postgres, ("postgres",), ((import_postgres, "get_db_connection"),),
        argv=lambda tmp: ["--output-dir", str(tmp)]),
    "embed_entities": Writer(
        embed_entities, ("neo4j", "qdrant"),
        ((embed_entities, "QdrantClient"), (embed_entities.GraphDatabase, "driver"))),
    "import_tsk_crossrefs": Writer(
        import_tsk_crossrefs, ("neo4j",), ((import_tsk_crossrefs, "get_driver"),),
        argv=lambda tmp: [_file(tmp / "cross_references.txt", "From\tTo\tVotes\n")],
        stubs=((import_tsk_crossrefs, "build_verse_map", lambda path: {}),)),
    "import_relations_neo4j": Writer(
        import_relations_neo4j, ("neo4j",), ((import_relations_neo4j.GraphDatabase, "driver"),),
        argv=lambda tmp: [_file(tmp / "relations.jsonl", '{"relation": "FATHER_OF"}\n')]),
    "backfill_aliases": Writer(
        backfill_aliases, ("neo4j",), ((backfill_aliases, "get_driver"),)),
    "backfill_event_relations": Writer(
        backfill_event_relations, ("neo4j",), ((backfill_event_relations, "get_driver"),),
        argv=lambda tmp: ["--input", _file(tmp / "relations_unclassified.jsonl")]),
    "backfill_verse_mentions": Writer(
        backfill_verse_mentions, ("neo4j",), ((backfill_verse_mentions, "get_driver"),),
        argv=_output_dir_with({"entity_mentions.jsonl": '{"source_type": "verse", '
                               '"source_id": "gen_1:v:1", "entity_id": "person:x"}\n'})),
    # Only the dan action stays inside Neo4j; the others also sync PG and Qdrant.
    "cleanup_noise_entities[dan]": Writer(
        cleanup_noise_entities, ("neo4j",), _CLEANUP_CONNECTIONS,
        argv=lambda tmp: ["--actions", "dan"]),
    "cleanup_noise_entities[all]": Writer(
        cleanup_noise_entities, ("neo4j", "postgres", "qdrant"), _CLEANUP_CONNECTIONS),
}

# Step 4/4.1 write the passage collections, which staging shares with production.
PASSAGE_WRITERS = {
    "import_qdrant": Writer(
        import_qdrant, (), ((import_qdrant, "get_qdrant_client"), (import_qdrant, "QdrantClient")),
        argv=_output_dir_with({"embeddings.jsonl": ""})),
    "import_qdrant_hybrid": Writer(
        import_qdrant_hybrid, (),
        ((import_qdrant_hybrid, "get_qdrant_client"), (import_qdrant_hybrid, "QdrantClient")),
        argv=_output_dir_with({"embeddings.jsonl": "", "sparse_vectors.jsonl": ""})),
}


def _run_main(writer: Writer, monkeypatch, tmp_path, reached: list) -> None:
    def recorder(name):
        def connect(*args, **kwargs):
            reached.append(name)
            raise _Stop
        return connect

    for owner, attr in writer.connections:
        monkeypatch.setattr(owner, attr, recorder(attr))
    for owner, attr, value in writer.stubs:
        monkeypatch.setattr(owner, attr, value)
    monkeypatch.setattr(sys, "argv", [f"{writer.module.__name__}.py", *writer.argv(tmp_path)])
    try:
        writer.module.main()
    except (_Stop, SystemExit) as exc:  # importers exit 1 on a failed connection
        if isinstance(exc, SystemExit) and (exc.code != 1 or not reached):
            raise


@pytest.fixture
def staging_target(monkeypatch, tmp_path):
    for key, value in STAGING_TARGET.items():
        monkeypatch.setenv(key, value)
    # kg_target also treats the repo .env's values as production; keep the
    # outcome independent of which collection .env has been promoted to.
    monkeypatch.setattr(kg_target, "DOTENV_PATH", tmp_path / "no.env")


GUARD_CASES = [(name, store) for name, writer in WRITERS.items() for store in writer.stores]


@pytest.mark.parametrize("name, store", GUARD_CASES)
def test_staging_refuses_a_missing_setting_before_connecting(name, store, staging_target,
                                                             monkeypatch, tmp_path):
    variable, _ = PRODUCTION_SETTING[store]
    monkeypatch.delenv(variable)
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert "KG_TARGET=staging refused" in str(exc.value)
    assert variable in str(exc.value)
    assert reached == []


@pytest.mark.parametrize("name, store", GUARD_CASES)
def test_staging_refuses_a_production_setting_before_connecting(name, store, staging_target,
                                                                monkeypatch, tmp_path):
    variable, production = PRODUCTION_SETTING[store]
    monkeypatch.setenv(variable, production)
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert f"{variable}={production}" in str(exc.value)
    assert reached == []


def test_a_neo4j_only_run_does_not_need_the_sync_settings(staging_target, monkeypatch, tmp_path):
    for variable, _ in (PRODUCTION_SETTING["postgres"], PRODUCTION_SETTING["qdrant"]):
        monkeypatch.delenv(variable)
    reached = []

    _run_main(WRITERS["cleanup_noise_entities[dan]"], monkeypatch, tmp_path, reached)

    assert reached == ["get_neo4j"]


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_isolated_staging_settings_reach_the_connection(name, staging_target, monkeypatch, tmp_path):
    reached = []

    _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert len(reached) == 1


@pytest.mark.parametrize("name", sorted({**WRITERS, **PASSAGE_WRITERS}))
def test_unset_target_connects_as_before(name, monkeypatch, tmp_path):
    monkeypatch.delenv("KG_TARGET", raising=False)
    reached = []

    _run_main({**WRITERS, **PASSAGE_WRITERS}[name], monkeypatch, tmp_path, reached)

    assert len(reached) == 1


@pytest.mark.parametrize("name", sorted(PASSAGE_WRITERS))
def test_passage_collection_writers_refuse_any_staging_run(name, staging_target, monkeypatch, tmp_path):
    """No setting makes them safe: bible_embeddings* has no staging copy."""
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(PASSAGE_WRITERS[name], monkeypatch, tmp_path, reached)

    assert "KG_TARGET=staging refused" in str(exc.value)
    assert reached == []


# --- cleanup_noise_entities: staging never skips the PG/Qdrant sync silently ---
#
# The fakes keep state: all three stores start with one generic Event
# (event:rizi, 日子) and with group:yehehua typed Group. A write either lands or
# raises, so a failed run leaves the partial state a real one would. Qdrant
# raises for any collection but bible_entities_v2, so every test also checks
# that the sync follows QDRANT_ENTITY_COLLECTION.

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
