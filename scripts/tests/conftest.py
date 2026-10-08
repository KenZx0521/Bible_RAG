"""scripts/ tests run with the scripts venv (see run.sh).

The script under test is imported as a top-level module
(`import derive_ragcommon_data`), so scripts/ goes on sys.path, mirroring how
it is executed.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
