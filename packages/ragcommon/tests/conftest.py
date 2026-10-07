"""Put packages/ on sys.path so the suite also runs without PYTHONPATH=packages."""

import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))
