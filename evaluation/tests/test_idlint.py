"""G-IDLINT (design §3.2): evaluation never derives an id's meaning by splitting it on ':'.

Ids are read through ragcommon.ids.parse, the payload's fields or table columns.
A ':' split that is not about an id goes in ALLOWED, keyed by file and the exact
source line, with the reason it is not an id.
"""

import os
import re
from pathlib import Path

import pytest

EVAL_ROOT = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()   # this file's samples below are the scanner's fixtures
COLON_SPLIT = re.compile(r"""\.(?:r?split|r?partition|count)\(\s*(?P<q>['"]):(?P=q)""")
_SKIP_DIRS = {".venv", "__pycache__"}

# (path relative to evaluation/, stripped source line) -> why it is not an id.
ALLOWED: dict[tuple[str, str], str] = {}


def _sources():
    for root, dirs, files in os.walk(EVAL_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith("results")]
        for name in files:
            path = Path(root) / name
            if name.endswith(".py") and path.resolve() != _SELF:
                yield path.relative_to(EVAL_ROOT).as_posix(), path.read_text(encoding="utf-8")


def test_no_id_is_split_on_colon():
    violations = [
        f"{rel}:{n}: {line.strip()}"
        for rel, text in _sources()
        for n, line in enumerate(text.splitlines(), start=1)
        if COLON_SPLIT.search(line) and (rel, line.strip()) not in ALLOWED
    ]

    assert violations == []


def test_every_allowlisted_split_still_exists_and_says_why():
    texts = dict(_sources())
    stale = [key for key, reason in ALLOWED.items()
             if not reason.strip() or key[1] not in {ln.strip() for ln in texts.get(key[0], "").splitlines()}]

    assert stale == []


@pytest.mark.parametrize("line, flagged", [
    ('parts = source_id.split(":")', True),
    ("book, rest = rid.split(':', 1)", True),
    ('head, _, tail = rid.rpartition(":")', True),
    ('n = rid.count(":")', True),
    ('items = text.split(",")', False),
    ('a, b = key.split("::")', False),
    ('parsed = ids.parse(rid)', False),
])
def test_the_scan_recognises_colon_splits(line, flagged):
    assert bool(COLON_SPLIT.search(line)) is flagged
