"""scripts/ tests run with the scripts venv (see run.sh).

Scripts import each other as top-level modules (`from backfill_head_events
import ...`) and the repo root packages (`bible_chunking`, `scripts.*`), so
both directories go on sys.path, mirroring how the scripts are executed.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
for path in (str(ROOT), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
