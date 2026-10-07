"""G-IMPORT (design §8): build modules import no database driver, no ``scripts.*`` and none of
the legacy tools that run inside the backend venv."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ragdata

ROOT = Path(ragdata.__file__).resolve().parent
FORBIDDEN = ("psycopg", "neo4j", "qdrant_client", "scripts", "ragdata.legacy", "utils")
BUILD_PACKAGES = ("stages", "kg")


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def _build_modules() -> list[Path]:
    return sorted(p for package in BUILD_PACKAGES for p in (ROOT / package).rglob("*.py"))


@pytest.mark.parametrize("path", _build_modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_build_modules_import_nothing_forbidden(path):
    bad = {m for m in _imports(path)
           if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)}
    assert not bad, f"{path.relative_to(ROOT)} imports {sorted(bad)}"


def test_the_scan_sees_the_kg_modules():
    names = {p.name for p in _build_modules()}
    assert {"k0.py", "k1_events.py", "k4_route.py"} <= names
