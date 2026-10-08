"""Bible RAG evaluation.

ragcommon (ids, books, refs, versification) lives in the repo's packages/ and
is not installed into this venv (design D-20: no relock), so its root goes on
sys.path here, before any ``src`` module imports it.
"""

import sys
from pathlib import Path

_PACKAGES = Path(__file__).resolve().parents[2] / "packages"
if str(_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_PACKAGES))
