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

Split from test_db_env.py, together with test_staging_write_guards.py (the
KG_TARGET=staging write guards) and test_cleanup_sync.py (the
cleanup_noise_entities PG/Qdrant sync); shared pieces are in _db_env_helpers.py.
"""

import importlib.util
import sys
from pathlib import Path

import dotenv
import psycopg2
import pytest
import qdrant_client

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
from _db_env_helpers import _FakeQdrant, _Stop
from scripts.relation_extraction import extract_relations
from scripts.relation_extraction.config import Neo4jConfig

SCRIPTS = Path(__file__).resolve().parents[1]


def _capturing(store: dict, *, stop: bool = False, result=None):
    def factory(*args, **kwargs):
        store["args"], store["kwargs"] = args, kwargs
        if stop:
            raise _Stop
        return result
    return factory


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
