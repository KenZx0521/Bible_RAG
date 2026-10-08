"""``ragdata unload BUILD_ID``: removes exactly what ``load`` wrote for one build."""

from __future__ import annotations

import json

import pytest
from qdrant_client import QdrantClient

import mini_loaded
from fake_dbapi import FakeConn
from ragdata import cli
from ragdata.loader import cli as loader_cli
from ragdata.loader import load as loader
from ragdata.loader import unload as unloader
from ragdata.loader.pg import PgDb, PgError
from ragdata.loader.qdrant import QdrantDb
from ragdata.release import assemble as rel

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")
OTHER_DATE = "20261009"


@pytest.fixture()
def loaded(tmp_path):
    return mini_loaded.load(tmp_path)


def _present(loaded, t) -> dict[str, bool]:
    return {"pg_schema": loaded.pg.schema_exists(t.schema),
            "builds_row": loaded.pg.build_row(t.build_id) is not None,
            "qdrant_collection": loaded.qdrant.exists(t.collection),
            "contracts_dir": t.contracts_dir.exists()}


def _unload(loaded, build_id=None):
    return unloader.unload(build_id or loaded.release.build_id, loaded.pg, loaded.qdrant,
                           loaded.contracts)


def _load_another(loaded) -> loader.Targets:
    """The same layers released on another date: a second build in the same databases."""
    other = rel.assemble(loaded.mini.store, loaded.mini.top, OTHER_DATE, loaded.mini.checks)
    loader.load(other, loaded.pg, loaded.qdrant, loaded.contracts)
    return loader.targets(other.build_id, loaded.contracts)


def test_unload_removes_the_four_things_the_build_owns_and_nothing_else(loaded):
    t, kept = loaded.targets, _load_another(loaded)
    report = _unload(loaded)
    assert _present(loaded, t) == dict.fromkeys(unloader.OWNED, False)
    assert _present(loaded, kept) == dict.fromkeys(unloader.OWNED, True)
    assert report["removed"] == list(unloader.OWNED) and report["absent"] == []
    assert (report["pg_schema"], report["qdrant_collection"]) == (t.schema, t.collection)


def test_unloading_again_finds_nothing_and_finishes_an_interrupted_unload(loaded):
    t = loaded.targets
    loaded.pg.schemas.pop(t.schema)
    loaded.pg.builds.pop(t.build_id)
    report = _unload(loaded)
    assert report["removed"] == ["qdrant_collection", "contracts_dir"]
    assert report["absent"] == ["pg_schema", "builds_row"]
    assert _unload(loaded)["removed"] == []


def test_a_serving_build_is_refused_and_kept_whole(loaded):
    loaded.pg.serving_rows["prod"] = loaded.release.build_id
    with pytest.raises(unloader.UnloadError, match="serving"):
        _unload(loaded)
    assert _present(loaded, loaded.targets) == dict.fromkeys(unloader.OWNED, True)


def test_a_build_promoted_after_the_check_is_still_refused_under_the_lock(loaded, monkeypatch):
    loaded.pg.serving_rows["prod"] = loaded.release.build_id
    monkeypatch.setattr(loaded.pg, "serving", lambda: {})
    with pytest.raises(unloader.UnloadError, match="PG rolled back.*serving"):
        _unload(loaded)
    assert _present(loaded, loaded.targets) == dict.fromkeys(unloader.OWNED, True)


@pytest.mark.parametrize("build_id", ["legacy-20261004", "public", "b20261008_xyz",
                                      "bible_embeddings", "b20261008_0123abcd/.."])
def test_only_a_release_build_id_can_be_unloaded(loaded, build_id):
    with pytest.raises(unloader.UnloadError, match="build id"):
        _unload(loaded, build_id)
    assert _present(loaded, loaded.targets) == dict.fromkeys(unloader.OWNED, True)


@pytest.mark.parametrize("column, value", [("pg_schema", "public"),
                                           ("qdrant_collection", "bible_embeddings"),
                                           ("contracts_dir", "/elsewhere")])
def test_a_builds_row_naming_other_targets_stops_the_unload(loaded, column, value):
    loaded.pg.builds[loaded.release.build_id][column] = value
    with pytest.raises(unloader.UnloadError, match=column):
        _unload(loaded)
    assert _present(loaded, loaded.targets) == dict.fromkeys(unloader.OWNED, True)


def test_a_failure_outside_pg_leaves_pg_as_it_was(loaded, monkeypatch):
    def down(name):
        raise OSError("qdrant down")
    monkeypatch.setattr(loaded.qdrant, "delete", down)
    with pytest.raises(OSError, match="qdrant down"):
        _unload(loaded)
    present = _present(loaded, loaded.targets)
    assert present["pg_schema"] and present["builds_row"] and present["qdrant_collection"]


# ------------------------------------------------------------------ the PG side


def _pg(serving=(), tables=True):
    def answer(statement, params):
        if "to_regclass" in statement:
            return [(tables,)]
        if '"serving"' in statement:
            return [(env,) for env in serving]
        return []
    return FakeConn(answer)


def test_drop_build_refuses_a_serving_build_before_it_drops_anything():
    conn = _pg(serving=("prod",))
    with pytest.raises(PgError, match="serving"):
        PgDb(conn).drop_build("bb20261008_0123abcd", "b20261008_0123abcd", lambda: None)
    assert not any("DROP" in s or "DELETE" in s for s in conn.statements())
    assert conn.log[-1] == ("rollback",)


def test_drop_build_drops_schema_and_row_in_one_transaction_then_runs_during():
    conn, seen = _pg(), []
    PgDb(conn).drop_build("bb20261008_0123abcd", "b20261008_0123abcd",
                          lambda: seen.append(conn.log.count(("commit",))))
    statements = conn.statements()
    assert any("FOR UPDATE" in s for s in statements)
    assert 'DROP SCHEMA IF EXISTS "bb20261008_0123abcd" CASCADE' in statements
    assert any(s.startswith('DELETE FROM "rag_meta"."builds"') for s in statements)
    assert conn.log.count(("commit",)) == seen[0] + 1 and conn.log[-1] == ("commit",)


def test_drop_build_without_rag_meta_drops_only_the_schema():
    conn = _pg(tables=False)
    PgDb(conn).drop_build("bb20261008_0123abcd", "b20261008_0123abcd", lambda: None)
    assert [s for s in conn.statements() if "to_regclass" not in s] == [
        'DROP SCHEMA IF EXISTS "bb20261008_0123abcd" CASCADE']


def test_qdrant_delete_removes_one_collection():
    db = QdrantDb(QdrantClient(location=":memory:"))
    for name in ("passages__b1", "passages__b2"):
        db.create(name, 4)
    db.delete("passages__b1")
    assert not db.exists("passages__b1") and db.exists("passages__b2")


# ------------------------------------------------------------------ the command


def test_the_command_reports_what_it_removed(loaded, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(loader_cli, "connect", lambda env: (loaded.pg, loaded.qdrant))
    loaded.pg.close = loaded.qdrant.close = lambda: None
    argv = ["unload", loaded.release.build_id, "--contracts", str(loaded.contracts),
            "--env-file", str(tmp_path / "none")]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["removed"] == list(unloader.OWNED)
    loaded.pg.serving_rows["staging"] = "b20261008_0123abcd"
    assert cli.main(["unload", "b20261008_0123abcd", "--contracts", str(loaded.contracts),
                     "--env-file", str(tmp_path / "none")]) == 2
    assert "serving" in capsys.readouterr().err
