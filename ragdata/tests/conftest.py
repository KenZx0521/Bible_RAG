"""Put ragdata/src and packages/ on sys.path so the suite runs without PYTHONPATH."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for path in (REPO / "ragdata" / "src", REPO / "packages", Path(__file__).resolve().parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
