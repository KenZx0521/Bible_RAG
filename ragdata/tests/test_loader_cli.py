"""``python -m ragdata load|verify`` with stand-in databases."""

from __future__ import annotations

import json

import pytest
from qdrant_client import QdrantClient

import mini_loaded
import mini_release
from fake_pg import FakePg
from ragdata import cli
from ragdata.loader import cli as loader_cli
from ragdata.loader import pg as pgmod, qdrant as qmod
from ragdata.loader.qdrant import QdrantDb
from ragdata.loader.verify import VerifyInputs

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes")


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    mini = mini_release.build(tmp_path / "mini")
    release = mini_loaded.assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    pg.close = qdrant.close = lambda: None
    monkeypatch.setattr(loader_cli, "connect", lambda env: (pg, qdrant))
    real = loader_cli.VerifyInputs
    monkeypatch.setattr(loader_cli, "VerifyInputs", lambda **kw: real(
        **{**kw, "encoder": mini_release.encoder()}))
    path = mini.root / "releases" / f"{release.build_id}.json"
    common = ["--store", str(mini.store), "--contracts", str(tmp_path / "contracts"),
              "--env-file", str(tmp_path / "none")]
    return {"mini": mini, "release": release, "path": path, "common": common, "pg": pg}


def test_load_then_verify(setup, capsys, tmp_path):
    argv = ["load", str(setup["path"]), "--slot", "inactive", *setup["common"]]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["build_id"] == setup["release"].build_id and out["points"] == 22
    report = tmp_path / "proj.json"
    code = cli.main(["verify", str(setup["path"]), *setup["common"], "--gt",
                     str(setup["mini"].gt), "--freeze", str(setup["mini"].freeze),
                     "--sample", "4", "--report", str(report)])
    assert code == 0, capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["pass"] is True
    assert cli.main(argv) == 2
    assert "refusing" in capsys.readouterr().err


def test_verify_before_load_is_a_failed_gate(setup, capsys):
    code = cli.main(["verify", str(setup["path"]), *setup["common"], "--gt",
                     str(setup["mini"].gt), "--freeze", str(setup["mini"].freeze)])
    assert code == 1 and json.loads(capsys.readouterr().out)["pass"] is False


def test_load_accepts_only_the_inactive_slot(setup, capsys):
    with pytest.raises(SystemExit):
        cli.main(["load", str(setup["path"]), "--slot", "prod"])
    assert "invalid choice" in capsys.readouterr().err


def test_the_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("POSTGRES_HOST=file\nPOSTGRES_DB=db\nOTHER=x\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_HOST", "environ")
    found = loader_cli.environment(env)
    assert found["POSTGRES_HOST"] == "environ" and found["POSTGRES_DB"] == "db"
    monkeypatch.delenv("POSTGRES_HOST")
    assert "POSTGRES_HOST" not in loader_cli.environment(tmp_path / "missing")


def test_connect_closes_pg_when_qdrant_cannot_be_reached(monkeypatch):
    closed = []

    class Pg:
        @classmethod
        def connect(cls, settings):
            return cls()

        def close(self):
            closed.append(True)

    def refuse(settings):
        raise OSError("qdrant refused")
    monkeypatch.setattr(pgmod, "PgDb", Pg)
    monkeypatch.setattr(qmod.QdrantDb, "connect", classmethod(lambda cls, s: refuse(s)))
    env = {"POSTGRES_HOST": "h", "POSTGRES_PORT": "1", "POSTGRES_DB": "d", "POSTGRES_USER": "u",
           "QDRANT_HOST": "q", "QDRANT_HTTP_PORT": "2", "QDRANT_GRPC_PORT": "3"}
    with pytest.raises(OSError, match="qdrant refused"):
        loader_cli.connect(env)
    assert closed == [True]


def test_missing_settings_are_bad_input(setup, capsys, monkeypatch):
    monkeypatch.setattr(loader_cli, "connect", lambda env: loader_cli.config.pg_settings(env))
    for key in loader_cli.config.PG_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert cli.main(["load", str(setup["path"]), "--slot", "inactive", *setup["common"]]) == 2
    assert "missing settings" in capsys.readouterr().err


def test_verify_inputs_default_to_the_repository_gt():
    inputs = VerifyInputs()
    assert inputs.gt.name == "ground_truth.v2.json" and inputs.sample == 200
