"""The backend finds packages/ (ragcommon) on its own, not only through PYTHONPATH.

embedder and reranker import ragcommon at module level, so every import of
the backend needs packages/ on sys.path. The image sets PYTHONPATH, but the
documented local start (`cd backend && uv run uvicorn main:app`, README) and
the runbook's backend suite (`PYTHONPATH=$SHIM ... pytest backend/tests`,
docs/staging_promotion.md R0) do not.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PACKAGES = REPO / "packages"


def _env_without_packages() -> dict:
    """os.environ with every packages/ entry dropped from PYTHONPATH (pytest's shim stays)."""
    kept = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
            if p and Path(p).resolve() != PACKAGES]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(kept), "HF_HUB_OFFLINE": "1"}


def _run(args: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=cwd, env=_env_without_packages(),
                          capture_output=True, text=True, timeout=300)


def test_main_imports_from_backend_without_packages_on_pythonpath():
    # uvicorn main:app from backend/: cwd is on sys.path, nothing else is
    result = _run(["-c", "import main, ragcommon.encoder"], BACKEND)

    assert result.returncode == 0, result.stderr


def test_suite_collects_without_packages_on_pythonpath():
    result = _run(["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                   "backend/tests/test_content.py"], REPO)

    assert result.returncode == 0, result.stdout + result.stderr


def _imported_roots(path: Path) -> set[str]:
    import ast
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_backend_imports_neither_scripts_nor_bible_chunking():
    """R1: the image no longer carries scripts/ or bible_chunking/ (design §11.1)."""
    offenders = [p.relative_to(BACKEND).as_posix() for p in BACKEND.rglob("*.py")
                 if ".venv" not in p.parts
                 and _imported_roots(p) & {"scripts", "bible_chunking", "neo4j"}]
    assert offenders == []
