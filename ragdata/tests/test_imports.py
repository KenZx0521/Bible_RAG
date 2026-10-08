"""Every ragdata module can be the first one imported: no import cycle between packages.

A cycle hides in a full test run, because collection imports modules in file
order and an earlier one loads the cycle from its harmless end. Each module is
therefore imported in a child interpreter with no ragdata module loaded before it.
"""

from __future__ import annotations

import os
import pkgutil
import subprocess
import sys

import ragdata

# Imports each named module with every ragdata module unloaded first; exits 1 listing failures.
FIRST_IMPORT = """
import importlib, sys
failed = []
for name in sys.argv[1:]:
    for loaded in [m for m in sys.modules if m.split(".")[0] == "ragdata"]:
        del sys.modules[loaded]
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed.append(f"{name}: {type(exc).__name__}: {exc}")
sys.exit("\\n".join(failed) or None)
"""


def _modules() -> list[str]:
    found = pkgutil.walk_packages(ragdata.__path__, "ragdata.")
    return sorted(m.name for m in found if m.name.rsplit(".", 1)[-1] != "__main__")


def _first_import(names: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    return subprocess.run([sys.executable, "-c", FIRST_IMPORT, *names], env=env,
                          capture_output=True, text=True, timeout=300)


def test_every_module_imports_first_in_a_fresh_interpreter():
    names = _modules()
    assert {"ragdata.gates.runner", "ragdata.gates.struct",
            "ragdata.stages.s05_struct.build", "ragdata.cli"} <= set(names)
    done = _first_import(names)
    assert done.returncode == 0, done.stderr


def test_the_child_reports_a_module_that_fails_to_import():
    done = _first_import(["ragdata.no_such_module"])
    assert done.returncode == 1
    assert "ragdata.no_such_module: ModuleNotFoundError" in done.stderr
