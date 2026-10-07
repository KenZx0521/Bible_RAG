"""G-IMPORT (design §8): build modules import no database driver, no ``scripts.*``, none of
the legacy tools that run inside the backend venv and not the loader; outside the loader's
two database adapters no ragdata module imports a driver at all."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ragdata

ROOT = Path(ragdata.__file__).resolve().parent
DRIVERS = ("psycopg", "psycopg2", "neo4j", "qdrant_client")
FORBIDDEN = (*DRIVERS, "scripts", "ragdata.legacy", "ragdata.loader", "utils")
BUILD_PACKAGES = ("stages", "kg")
DRIVER_MODULES = {"loader/pg.py", "loader/qdrant.py"}    # the only modules that may import one


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def _hits(names: set[str], forbidden: tuple[str, ...]) -> set[str]:
    return {m for m in names if any(m == f or m.startswith(f + ".") for f in forbidden)}


def _build_modules() -> list[Path]:
    return sorted(p for package in BUILD_PACKAGES for p in (ROOT / package).rglob("*.py"))


@pytest.mark.parametrize("path", _build_modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_build_modules_import_nothing_forbidden(path):
    bad = _hits(_imports(path), FORBIDDEN)
    assert not bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}"


def test_only_the_loader_adapters_import_a_database_driver():
    importers = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
                 if _hits(_imports(p), DRIVERS)}
    assert importers == DRIVER_MODULES


def test_the_scan_catches_a_driver_import(tmp_path):
    module = tmp_path / "m.py"
    module.write_text("import psycopg2.extras\nfrom qdrant_client import models\n",
                      encoding="utf-8")
    assert _hits(_imports(module), DRIVERS) == {"psycopg2.extras", "qdrant_client"}


def test_the_scan_sees_the_kg_modules():
    names = {p.name for p in _build_modules()}
    assert {"k0.py", "k1_events.py", "k4_route.py"} <= names
