"""G-IDLINT (design §3.2): the backend never splits an id on ':' to learn what it is.

Ids are read through ragcommon.ids.parse() or the payload and table fields. Every
`.split(':')`, `.rsplit(':')`, `.partition(':')` or `.rpartition(':')` in backend
code fails this test unless the allow-list names its file and line, with the
reason it is not an id.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SPLITTERS = frozenset({"split", "rsplit", "partition", "rpartition"})
SEPARATORS = frozenset({":", "："})

# (path relative to backend/, the stripped source line) -> why it is not an id
ALLOWED = {
    ("utils/llm/ollama_client.py", 'model_base = self._model.split(":")[0]'):
        "Ollama 模型名稱（gemma3:4b）的 tag，不是 id",
}


def _python_files() -> list[Path]:
    return sorted(p for p in BACKEND.rglob("*.py")
                  if ".venv" not in p.parts and "__pycache__" not in p.parts)


def colon_splits(source: str) -> list[int]:
    """Line numbers of every call splitting on a colon."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in SPLITTERS and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in SEPARATORS):
            lines.append(node.lineno)
    return lines


def violations() -> list[str]:
    found = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(BACKEND).as_posix()
        for line in colon_splits(source):
            text = source.splitlines()[line - 1].strip()
            if (rel, text) not in ALLOWED:
                found.append(f"{rel}:{line}: {text}")
    return found


def test_no_backend_code_splits_ids_on_colons():
    assert violations() == []


def test_every_allowed_line_still_exists_and_has_a_reason():
    for (rel, text), reason in ALLOWED.items():
        source = (BACKEND / rel).read_text(encoding="utf-8")
        assert text in (source.splitlines()[n - 1].strip() for n in colon_splits(source)), rel
        assert reason


def test_the_scan_sees_every_form():
    source = 'a = x.split(":")\nb = y.rsplit(":", 1)\nc = z.partition("：")\nd = w.split(".")\n'

    assert colon_splits(source) == [1, 2, 3]
