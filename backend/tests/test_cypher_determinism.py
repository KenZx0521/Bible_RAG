"""Every LIMIT or slice in a graph/entity query must cut a totally ordered list.

`ORDER BY mention_count DESC LIMIT 3`, or a LIMIT with no ORDER BY at all,
returns whichever tied rows the store happens to visit first. Two equivalent
stores (prod and a staging rebuild of the same data) then disagree: W0's
legacy-100 opt-in run changed 19 of 100 questions with no data change
(docs/records/2026-10-05_kg_batch1_w0_results.md). The rule (plan X1,
generalised): every ORDER BY in front of a LIMIT or a slice ends with a stable
hash of the row identity — apoc.util.md5 in Cypher, md5() in SQL — so ties are
broken without a lexical bias towards any book.
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
QUERY_FILES = [
    BACKEND / "database" / "neo4j_db.py",
    BACKEND / "utils" / "retrieval" / "entity_path_retriever.py",
    BACKEND / "database" / "postgres.py",
]
CLAUSES = re.compile(r"\b(MATCH|WITH|RETURN|UNWIND|SELECT|FROM|WHERE)\b")


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _queries() -> list[tuple[str, str]]:
    found = []
    for path in QUERY_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            text = _text(node)
            if text and re.search(r"\bLIMIT\b", text) and re.search(r"\b(MATCH|SELECT)\b", text):
                found.append((f"{path.name}:{node.lineno}", text))
    return found


def _sort_keys(clause: str) -> list[str]:
    """An ORDER BY clause split on its top-level commas."""
    keys, depth, start = [], 0, 0
    for i, ch in enumerate(clause):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            keys.append(clause[start:i])
            start = i + 1
    return keys + [clause[start:]]


QUERIES = _queries()


def test_the_scan_finds_the_known_queries():
    # neo4j_db: 10 queries with a LIMIT; entity_path: 1; postgres: 2
    assert len(QUERIES) >= 13, [where for where, _ in QUERIES]


@pytest.mark.parametrize("where,query", QUERIES, ids=[w for w, _ in QUERIES])
def test_every_limit_cuts_a_hash_tiebroken_order(where, query):
    for limit in re.finditer(r"\bLIMIT\b", query):
        before = query[:limit.start()]
        order = before.rfind("ORDER BY")
        assert order >= 0, f"{where}: LIMIT without ORDER BY"
        clause = before[order:]
        assert not CLAUSES.search(clause), f"{where}: the ORDER BY before LIMIT belongs to another clause"
        last_key = _sort_keys(clause)[-1]
        assert "md5(" in last_key, f"{where}: last sort key {last_key.strip()!r} is not a hash tiebreak"


def test_hub_aware_slice_is_taken_from_an_ordered_collect():
    # entity_query: all_p[0..cap] keeps the first `cap` of collect(DISTINCT p)
    source = (BACKEND / "database" / "neo4j_db.py").read_text(encoding="utf-8")
    query = source[source.index("async def get_pericopes_for_entities_hub_aware"):]
    query = query[:query.index("entity_ids=entity_ids")]
    assert re.search(r"ORDER BY [^\n]*apoc\.util\.md5\([^\n]*\n\s*WITH eid, collect\(DISTINCT p\)", query), query
    assert "all_p[0..cap]" in query
