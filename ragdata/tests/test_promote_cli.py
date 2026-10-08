"""``python -m ragdata promote``: argument rules (prod needs --yes-prod) and the JSON it prints."""

from __future__ import annotations

import json

import pytest

from fake_dbapi import FakeConn
from ragdata import cli
from ragdata.loader import cli as loader_cli
from ragdata.loader.pg import PgDb

D0, D1 = ("sha256:" + c * 64 for c in "ab")


@pytest.fixture()
def opened(monkeypatch, tmp_path):
    """Stand-in PG whose staging/prod row is b0 and whose history holds only that promote."""
    seen = []

    def answer(statement, params):
        if 'FROM "rag_meta"."builds"' in statement:
            return [(1,)] if params[0] in ("b0", "b1") else []
        if 'FROM "rag_meta"."serving_history"' in statement:
            return [(1, "b0", D0)]
        if 'FROM "rag_meta"."serving"' in statement:
            return [("b0", D0)]
        return []

    def connect(env):
        seen.append(dict(env))
        return PgDb(FakeConn(answer))

    monkeypatch.setattr(loader_cli, "connect_pg", connect)
    return seen, ["--env-file", str(tmp_path / "none")]


def test_promote_staging_prints_the_new_pair_and_the_one_before(opened, capsys):
    seen, common = opened

    code = cli.main(["promote", "--env", "staging", "--build", "b1", "--image", D1, *common])

    assert code == 0 and len(seen) == 1
    assert json.loads(capsys.readouterr().out) == {
        "env": "staging", "serving": {"build_id": "b1", "backend_image_digest": D1},
        "before": {"build_id": "b0", "backend_image_digest": D0}}


def test_rollback_prints_what_was_undone_and_what_serves_now(opened, capsys):
    _, common = opened

    assert cli.main(["promote", "--rollback", "--env", "staging", *common]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["undone"] == {"build_id": "b0", "backend_image_digest": D0}
    assert out["serving"] is None


@pytest.mark.parametrize("argv, match", [
    (["--env", "prod", "--build", "b1", "--image", D1], "--yes-prod"),
    (["--env", "prod", "--rollback"], "--yes-prod"),
    (["--env", "staging", "--build", "b1"], "--image"),
    (["--env", "staging", "--image", D1], "--build"),
    (["--env", "staging", "--rollback", "--build", "b1"], "--rollback"),
])
def test_bad_arguments_are_refused_before_connecting(opened, capsys, argv, match):
    seen, common = opened

    assert cli.main(["promote", *argv, *common]) == 2
    assert match in capsys.readouterr().err and seen == []


def test_prod_with_yes_prod_goes_ahead(opened, capsys):
    seen, common = opened

    argv = ["promote", "--env", "prod", "--yes-prod", "--build", "b1", "--image", D1, *common]
    assert cli.main(argv) == 0 and len(seen) == 1
    assert json.loads(capsys.readouterr().out)["env"] == "prod"


def test_a_promote_the_database_refuses_is_bad_input(opened, capsys):
    _, common = opened

    assert cli.main(["promote", "--env", "staging", "--build", "b9", "--image", D1, *common]) == 2
    assert "b9 is not in rag_meta.builds" in capsys.readouterr().err


def test_connect_pg_reads_only_the_postgres_settings(monkeypatch):
    from ragdata.loader import pg as pgmod
    monkeypatch.setattr(pgmod.PgDb, "connect", classmethod(lambda cls, settings: settings))
    env = {"POSTGRES_HOST": "h", "POSTGRES_PORT": "1", "POSTGRES_DB": "d", "POSTGRES_USER": "u"}

    assert repr(loader_cli.connect_pg(env)) == "PgSettings(u@h:1/d)"
