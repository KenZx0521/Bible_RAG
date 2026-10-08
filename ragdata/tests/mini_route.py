"""The mini route registry (``query_aliases.yaml``) and what K4 must make of the mini layers.

The mini kg0 has five names (鹽海 typed Place), three printed divine patterns (神 is never
printed, so it has no term) and no ‧ name; the mini events layer has six triggers. With the
two aliases below and the 84 book forms that is 100 terms, one of them (主) unroutable.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ALIAS_ROWS = (
    {"id": "qa.001", "surface": "死海", "target": "鹽海", "source": "現代名",
     "note": "PDF 作鹽海"},
    {"id": "qa.002", "surface": "該撒利亞", "target": "凱撒利亞", "source": "CUNP",
     "note": "RCUV 作凱撒利亞"},
)
QUESTION_EXCLUSIONS = ({"surface": "何提", "context": "如何提", "why": "問句"},)
COUNTS = {"name": 5, "dotless": 0, "divine": 3, "alias": 2, "event": 6, "book": 84}


def query_aliases(**changes) -> dict:
    return {"schema": "ragdata.query_aliases.v1", "aliases": [dict(r) for r in ALIAS_ROWS],
            "question_exclusions": [dict(r) for r in QUESTION_EXCLUSIONS], **changes}


def write_query_aliases(directory: Path, doc: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "query_aliases.yaml"
    path.write_text(yaml.safe_dump(doc or query_aliases(), allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path
