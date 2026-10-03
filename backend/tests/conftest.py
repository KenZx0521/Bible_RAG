import sys
from pathlib import Path

# Backend modules import each other as top-level packages (`from config import
# settings`, `from utils...`), the same way uvicorn runs them from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
