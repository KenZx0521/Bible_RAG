"""The backend's committed test build is what make_mini_build.py writes from today's mini release.

The backend suite reads ``backend/tests/fixtures/mini_build`` and cannot rebuild it (no
ragdata there), so a contract change in ragdata would leave it stale without a failure.
Regenerate with the command in make_mini_build.py.
"""

import importlib.util
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_backend_mini_build_is_current(tmp_path):
    spec = importlib.util.spec_from_file_location("make_mini_build", FIXTURES / "make_mini_build.py")
    make = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make)

    make.write(tmp_path / "work", tmp_path / "out")

    fresh, committed = _files(tmp_path / "out"), _files(FIXTURES / "mini_build")
    assert sorted(fresh) == sorted(committed)
    assert [name for name in fresh if fresh[name] != committed[name]] == []
