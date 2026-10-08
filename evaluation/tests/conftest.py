"""Make the evaluation package root importable as `src.*` in tests; shared fixtures."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

_EVAL_ROOT = Path(__file__).resolve().parent.parent
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))

NEW_BUILD = "b20261008_0000abcd"


@pytest.fixture
def write_contracts():
    """Write a build's contracts directory: manifest naming the build + a one-slot verse_index."""
    def write(root: Path, build_id: str = NEW_BUILD) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"schema": "ragdata.contract.verse_index.v1",
                           "slots": [{"slot_key": "jhn.3.16", "unit_key": "jhn.3.16"}]}).encode()
        (root / "verse_index.json").write_bytes(data)
        (root / "manifest.json").write_text(json.dumps(
            {"build_id": build_id,
             "files": {"verse_index.json": hashlib.sha256(data).hexdigest()}}))
        return root
    return write
