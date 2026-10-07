"""loader.pg over a scripted connection: one transaction, rollback and the own-schema drop;
loader.promote; loader.config."""

from __future__ import annotations

import psycopg2
import pytest

from fake_dbapi import FakeConn, FakeDbError
from ragdata.loader import config, pg as pgmod, promote as promoter
from ragdata.loader.pg import PgDb, PgError
from ragdata.loader.plan import CopyStep, PgPlan
from ragdata.loader.tables import table

PLAN = PgPlan("bb20261008_0123abcd", ('CREATE TABLE "bb20261008_0123abcd"."books" (…)',),
              (CopyStep("books", 'COPY "bb20261008_0123abcd"."books" FROM STDIN', "x\n", 1),),
              ('ANALYZE "bb20261008_0123abcd"."books"',))
BUILD = {"build_id": "b20261008_0123abcd", "release_sha": "r", "manifest_sha": "m",
         "pg_schema": PLAN.schema, "qdrant_collection": "c", "contracts_dir": "d",
         "kg_enabled": False, "points": 1, "manifest": {}}


def _answers(count=1, schema_exists=False):
    def answer(statement, params):
        if statement.startswith("SELECT count(*)"):
            return [(count,)]
        if "pg_namespace" in statement:
            return [(1,)] if schema_exists else []
        return []
    return answer


def _kinds(conn):
    return [entry[0] for entry in conn.log]


def test_apply_writes_everything_in_one_transaction_then_commits():
    conn, seen = FakeConn(_answers()), []
    PgDb(conn).apply(PLAN, BUILD, lambda: seen.append(_kinds(conn).count("commit")))
    statements = conn.statements()
    assert statements[0] == 'CREATE SCHEMA "bb20261008_0123abcd"'
    assert statements[1].startswith("CREATE TABLE") and statements[2].startswith("COPY")
    assert any(s.startswith('CREATE SCHEMA IF NOT EXISTS "rag_meta"') for s in statements)
    assert statements[-1].startswith('INSERT INTO "rag_meta"."builds"')
    assert seen == [0] and _kinds(conn)[-1] == "commit" and conn.autocommit is False
    assert not any("DROP" in s for s in statements)


def test_a_short_copy_rolls_back_and_drops_the_schema_it_created():
    conn = FakeConn(_answers(count=0, schema_exists=True))
    with pytest.raises(PgError, match="COPY wrote 0 rows, expected 1"):
        PgDb(conn).apply(PLAN, BUILD, lambda: None)
    assert "rollback" in _kinds(conn)
    assert conn.statements()[-1] == 'DROP SCHEMA "bb20261008_0123abcd" CASCADE'


def test_a_failure_in_during_rolls_back_without_a_drop_once_the_schema_is_gone():
    conn = FakeConn(_answers())

    def during():
        raise RuntimeError("qdrant down")
    with pytest.raises(RuntimeError, match="qdrant down"):
        PgDb(conn).apply(PLAN, BUILD, during)
    assert "commit" not in _kinds(conn)[:-1] and "rollback" in _kinds(conn)
    assert not any("DROP" in s for s in conn.statements())


def test_a_schema_that_already_exists_is_never_dropped():
    conn = FakeConn(_answers(schema_exists=True), fail="CREATE SCHEMA")
    with pytest.raises(FakeDbError):
        PgDb(conn).apply(PLAN, BUILD, lambda: None)
    assert not any("DROP" in s for s in conn.statements())


def test_reads_go_through_their_own_short_transactions():
    def answer(statement, params):
        if "to_regclass" in statement:
            return [(True,)]
        if '"serving"' in statement:
            return [("staging", "b1")]
        if '"builds"' in statement:
            return [("b1", "r", "m", "s", "c", "d", False, 3, {}, False)]
        if "pg_constraint" in statement:
            return [("books", "pk_books", "p")]
        return [("gen", 1)]
    db = PgDb(FakeConn(answer))
    assert db.serving() == {"staging": "b1"}
    assert db.build_row("b1")["points"] == 3 and db.build_row("b1")["synthetic"] is False
    assert db.constraints("s") == {("books", "pk_books", "p")}
    books = table("books")
    db._conn.answer = lambda s, p: [tuple(range(len(books.columns)))]
    assert db.fetch("s", books)[0]["book_id"] == 0
    db.close()


def test_missing_rag_meta_means_nothing_serves_and_nothing_is_registered():
    db = PgDb(FakeConn(lambda s, p: [(False,)] if "to_regclass" in s else []))
    assert db.serving() == {} and db.build_row("b1") is None
    assert db.schema_exists("b1") is False


def test_connect_reports_a_refused_connection(monkeypatch):
    def refuse(**kwargs):
        raise psycopg2.OperationalError("no route")
    monkeypatch.setattr(pgmod.psycopg2, "connect", refuse)
    settings = config.PgSettings("h", 1, "d", "u", "secret")
    with pytest.raises(PgError, match="no route") as caught:
        PgDb.connect(settings)
    assert "secret" not in str(caught.value) and "secret" not in repr(settings)


def test_connect_hands_the_settings_to_psycopg2(monkeypatch):
    seen = {}
    monkeypatch.setattr(pgmod.psycopg2, "connect", lambda **kw: seen.update(kw) or FakeConn())
    PgDb.connect(config.PgSettings("h", 5432, "bible_rag", "bible", "pw"))
    assert seen == {"host": "h", "port": 5432, "dbname": "bible_rag", "user": "bible",
                    "password": "pw"}


# ------------------------------------------------------------------ promote

DIGEST = "sha256:" + "a" * 64


def _registered(previous=None):
    def answer(statement, params):
        if '"builds"' in statement:
            return [(1,)] if params[0] == "b1" else []
        if "FOR UPDATE" in statement:
            return [previous] if previous else []
        return []
    return answer


def test_promote_replaces_the_env_row_in_one_transaction():
    conn = FakeConn(_registered(("b0", "sha256:" + "b" * 64)))
    before = promoter.promote(PgDb(conn), "staging", "b1", DIGEST)
    assert before == promoter.Serving("staging", "b0", "sha256:" + "b" * 64)
    insert = next(s for s in conn.statements() if s.startswith("INSERT"))
    assert "ON CONFLICT" in insert and conn.log[-1] == ("commit",)
    assert promoter.promote(PgDb(FakeConn(_registered())), "prod", "b1", DIGEST) is None


@pytest.mark.parametrize("env, build, digest, match", [
    ("test", "b1", DIGEST, "env"), ("prod", "b1", "sha256:xyz", "digest"),
    ("prod", "b2", DIGEST, "not in rag_meta.builds"),
])
def test_promote_refuses_what_cannot_be_served(env, build, digest, match):
    conn = FakeConn(_registered())
    with pytest.raises(promoter.PromoteError, match=match):
        promoter.promote(PgDb(conn), env, build, digest)
    assert not any(s.startswith("INSERT") for s in conn.statements())


# ------------------------------------------------------------------ config


def test_env_files_and_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# c\nexport POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_DB='db'\n"
                   "POSTGRES_USER=u\nPOSTGRES_PASSWORD=\"p w\"\nQDRANT_HOST=q\n"
                   "QDRANT_HTTP_PORT=6333\nQDRANT_GRPC_PORT=6334\nnoise\n", encoding="utf-8")
    values = config.read_env_file(env)
    assert config.pg_settings(values) == config.PgSettings("localhost", 5432, "db", "u", "p w")
    assert config.qdrant_settings(values) == config.QdrantSettings("q", 6333, 6334)
    with pytest.raises(config.ConfigError, match="POSTGRES_HOST"):
        config.pg_settings({})
    with pytest.raises(config.ConfigError, match="not a port"):
        config.qdrant_settings({**values, "QDRANT_GRPC_PORT": "x"})
    with pytest.raises(config.ConfigError, match="unreadable"):
        config.read_env_file(tmp_path / "missing")
