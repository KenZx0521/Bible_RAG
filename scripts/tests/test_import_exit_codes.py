"""Step 3 / Step 5 importers must fail the rebuild chain when they cannot connect.

docs/build_database.md stops the chain on any non-zero exit; an importer that
prints "Connection failed" and returns 0 lets the chain run on into steps that
then act on an empty or stale database.
"""

import sys

import pytest

import import_neo4j
import import_postgres


def _boom():
    raise ConnectionError("database down")


@pytest.mark.parametrize("module, connect", [
    (import_neo4j, "get_neo4j_driver"),
    (import_postgres, "get_db_connection"),
])
def test_connection_failure_exits_non_zero(monkeypatch, tmp_path, module, connect):
    monkeypatch.delenv("KG_TARGET", raising=False)
    monkeypatch.setattr(module, connect, _boom)
    monkeypatch.setattr(sys, "argv", [module.__name__, "--output-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        module.main()

    assert exc.value.code == 1
