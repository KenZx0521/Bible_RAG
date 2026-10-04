"""Pieces shared by the DB env tests, split from test_db_env.py.

test_db_env_contract.py, test_staging_write_guards.py and test_cleanup_sync.py
import from here. staging_target is a pytest fixture: a test module gets it by
importing it.
"""

import pytest

import kg_target


class _Stop(Exception):
    """Raised by a fake client once its constructor arguments are captured."""


class _FakeQdrant:
    def get_collections(self):
        return None


STAGING_TARGET = {
    "KG_TARGET": "staging",
    "NEO4J_URI": "bolt://localhost:7688",
    "POSTGRES_DB": "bible_rag_staging",
    "QDRANT_ENTITY_COLLECTION": "bible_entities_v2",
}


@pytest.fixture
def staging_target(monkeypatch, tmp_path):
    for key, value in STAGING_TARGET.items():
        monkeypatch.setenv(key, value)
    # kg_target also treats the repo .env's values as production; keep the
    # outcome independent of which collection .env has been promoted to.
    monkeypatch.setattr(kg_target, "DOTENV_PATH", tmp_path / "no.env")
