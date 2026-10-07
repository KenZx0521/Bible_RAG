import sys
from pathlib import Path

# Backend modules import each other as top-level packages (`from config import
# settings`, `from utils...`), the same way uvicorn runs them from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# ragcommon lives in packages/; the image puts it on PYTHONPATH, a bare
# `pytest backend/tests` does not.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))
