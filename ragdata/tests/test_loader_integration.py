"""The loader against a real PostgreSQL: set RAGDATA_TEST_PG_DSN to a throwaway database
whose name starts with ``ragdata_test`` (the test wipes its rag_meta and b* schemas).

    docker run -d --rm --pull never --name ragdata_test_pg -e POSTGRES_PASSWORD=test \\
      -e POSTGRES_USER=test -e POSTGRES_DB=ragdata_test -p 127.0.0.1:55432:5432 \\
      --tmpfs /var/lib/postgresql/data pgvector/pgvector:pg15
    RAGDATA_TEST_PG_DSN=postgresql://test:test@127.0.0.1:55432/ragdata_test pytest …

Qdrant is the in-memory client. Without the variable every test here is skipped.
"""

from __future__ import annotations

import os

import pytest
from qdrant_client import QdrantClient

import mini_loaded
import mini_release
from ragdata.loader import load as loader
from ragdata.loader import promote as promoter
from ragdata.loader.pg import PgDb
from ragdata.loader.qdrant import QdrantDb

DSN = os.environ.get("RAGDATA_TEST_PG_DSN", "")
pytestmark = [pytest.mark.skipif(not DSN, reason="RAGDATA_TEST_PG_DSN not set"),
              pytest.mark.filterwarnings("ignore:Payload indexes")]


@pytest.fixture()
def db():
    import psycopg2
    conn = psycopg2.connect(DSN)
    if not conn.get_dsn_parameters()["dbname"].startswith("ragdata_test"):
        pytest.fail("RAGDATA_TEST_PG_DSN must name a throwaway ragdata_test* database")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT nspname FROM pg_namespace WHERE nspname = 'rag_meta' "
                    "OR nspname ~ '^bb[0-9]{8}_'")
        for (schema,) in cur.fetchall():
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    pg = PgDb(conn)
    yield pg
    pg.close()


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("integration"))


def _load(tmp_path, mini, pg):
    release = mini_loaded.assembled(mini)
    qdrant = QdrantDb(QdrantClient(location=":memory:"))
    report = loader.load(release, pg, qdrant, tmp_path / "contracts")
    loaded = mini_loaded.Loaded(mini, release, pg, qdrant, tmp_path / "contracts", report)
    return loaded


def test_load_and_verify_on_postgres(tmp_path, mini, db):
    loaded = _load(tmp_path, mini, db)
    report = loaded.verify()
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    row = db.build_row(loaded.release.build_id)
    assert row["points"] == 22 and row["manifest"]["build_id"] == loaded.release.build_id
    with pytest.raises(loader.LoadError, match="refusing"):
        loader.load(loaded.release, db, loaded.qdrant, loaded.contracts)


def test_a_failure_before_commit_leaves_no_schema(tmp_path, mini, db, monkeypatch):
    release = mini_loaded.assembled(mini)
    qdrant = QdrantDb(QdrantClient(location=":memory:"))
    monkeypatch.setattr(qdrant, "count", lambda name: 0)
    with pytest.raises(loader.LoadError, match="PG rolled back"):
        loader.load(release, db, qdrant, tmp_path / "contracts")
    t = loader.targets(release.build_id)
    assert not db.schema_exists(t.schema) and db.build_row(release.build_id) is None


def test_promote_and_switch_back(tmp_path, mini, db):
    loaded = _load(tmp_path, mini, db)
    digest = "sha256:" + "c" * 64
    assert promoter.promote(db, "staging", loaded.release.build_id, digest) is None
    assert db.serving() == {"staging": loaded.release.build_id}
    before = promoter.promote(db, "staging", loaded.release.build_id, "sha256:" + "d" * 64)
    assert before == promoter.Serving("staging", loaded.release.build_id, digest)
    with pytest.raises(loader.LoadError, match="serving"):
        loader.load(loaded.release, db, loaded.qdrant, tmp_path / "again")
