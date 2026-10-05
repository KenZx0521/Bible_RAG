"""import_relations_neo4j (Step 6.1): what an edge carries is its file row.

apoc.merge.relationship's onCreate map wrote the properties only when the edge
was new, so an edge already in the graph kept whatever an earlier import had
written (the four prod SON_OF edges stuck at phase 5, REL-10). Every edge's
properties are now replaced wholesale by its row, and all rows go in one write
transaction, so a failure leaves no partial layer.

Nothing is skipped silently either: MATCH dropped a row whose endpoint was not
in the graph and the run still exited 0 (H16). A missing endpoint now stops
the run before any write, and a statement that writes a different number of
edges than it was sent rows rolls the whole transaction back.

The fake driver records auto-commit statements (session.run) separately from
statements run inside session.execute_read and session.execute_write, modelled
on test_import_constraints.py. It holds a set of entity_ids for the endpoint
read, and a write transaction commits only if its work returns.
"""

import json
import re
import sys

import pytest

import import_relations_neo4j

KEY = ("head_id", "relation", "tail_id")
MERGE_WITHOUT_MAPS = re.compile(
    r"apoc\.merge\.relationship\(\s*h,\s*row\.relation,\s*\{\},\s*\{\},\s*t,\s*\{\}\s*\)")


class _Result:
    """Both shapes the importer reads: single() for a write, iteration for the reads."""

    def __init__(self, records: list[dict]):
        self._records = records

    def single(self):
        return self._records[0] if self._records else None

    def __iter__(self):
        return iter(self._records)


class _Tx:
    def __init__(self, driver: "_FakeDriver", log: list):
        self._driver, self._log = driver, log

    def run(self, query: str, **params):
        self._log.append((query, params))
        if "ids" in params:
            return _Result([{"id": i} for i in params["ids"] if not self._driver.has(i)])
        return _Result([{"written": self._driver.written(params["rows"])}])


class _Session:
    def __init__(self, driver: "_FakeDriver"):
        self._driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query: str, **params):
        self._driver.autocommit.append((query, params))
        if "rows" in params:
            return _Result([{"written": self._driver.written(params["rows"])}])
        return _Result([])

    def execute_read(self, work, *args, **kwargs):
        return work(_Tx(self._driver, self._driver.reads), *args, **kwargs)

    def execute_write(self, work, *args, **kwargs):
        self._driver.transactions += 1
        try:
            result = work(_Tx(self._driver, self._driver.in_tx), *args, **kwargs)
        except Exception:
            self._driver.rolled_back += 1
            raise
        self._driver.committed += 1
        return result


class _FakeDriver:
    """entities: the entity_ids in the graph (None: every id is there).
    written: rows of one write statement -> the edge count it reports."""

    def __init__(self, entities: set[str] | None = None, written=len):
        self.entities, self.written = entities, written
        self.autocommit: list[tuple[str, dict]] = []
        self.reads: list[tuple[str, dict]] = []
        self.in_tx: list[tuple[str, dict]] = []
        self.transactions = self.committed = self.rolled_back = 0

    def has(self, entity_id: str) -> bool:
        return self.entities is None or entity_id in self.entities

    def session(self, **kwargs):
        return _Session(self)

    def close(self):
        pass


def _row(head, relation, tail, **extra) -> dict:
    return {"head_id": head, "relation": relation, "tail_id": tail, **extra}


def _import(monkeypatch, tmp_path, rows: list[dict], *flags: str,
            driver: _FakeDriver | None = None, code: int = 0) -> _FakeDriver:
    path = tmp_path / "relations.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    driver = driver or _FakeDriver()
    monkeypatch.delenv("KG_TARGET", raising=False)
    monkeypatch.setattr(import_relations_neo4j.GraphDatabase, "driver",
                        lambda *args, **kwargs: driver)
    monkeypatch.setattr(sys, "argv", ["import_relations_neo4j.py", str(path), *flags])

    assert import_relations_neo4j.main() == code
    return driver


def _merges(statements: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [(q, p) for q, p in statements if "apoc.merge.relationship" in q]


def test_cypher_overwrites_all_properties(monkeypatch, tmp_path):
    # An llm row (span longer than the old 512 cut) and an anchored row whose
    # confidence_raw is null: props are the row minus its key, nulls dropped.
    llm = _row("person:a", "FATHER_OF", "person:b", source="llm", confidence_raw=0.85,
               evidence_span="甲" * 600, sources=["llm"], support_pericopes=[],
               extraction_phase=3, direction_verified=False)
    anchored = _row("person:c", "SON_OF", "person:a", source="anchored_rule",
                    confidence_raw=None, verse=12, notes="gei", extraction_phase=6)

    driver = _import(monkeypatch, tmp_path, [llm, anchored])

    merges = _merges(driver.autocommit + driver.in_tx)
    for query, _ in merges:
        assert "SET rel = row.props" in query
        assert MERGE_WITHOUT_MAPS.search(query), query
    sent = [r for _, params in merges for r in params["rows"]]
    assert sent == [
        {"head_id": "person:a", "relation": "FATHER_OF", "tail_id": "person:b",
         "props": {k: v for k, v in llm.items() if k not in KEY}},
        {"head_id": "person:c", "relation": "SON_OF", "tail_id": "person:a",
         "props": {"source": "anchored_rule", "verse": 12, "notes": "gei",
                   "extraction_phase": 6}},
    ]
    assert len(sent[0]["props"]["evidence_span"]) == 600


def test_all_rows_are_written_in_one_transaction(monkeypatch, tmp_path):
    # Two relation types and more rows than one batch: still one transaction,
    # nothing auto-committed, every row sent once in file order.
    rows = [_row(f"person:h{i}", relation, f"person:t{i}", source="llm")
            for i, relation in enumerate(["FATHER_OF", "SON_OF", "FATHER_OF",
                                          "SPOUSE_OF", "SON_OF"])]

    driver = _import(monkeypatch, tmp_path, rows, "--batch-size", "2")

    assert driver.transactions == 1
    assert _merges(driver.autocommit) == []
    assert len(_merges(driver.in_tx)) == 3
    sent = [r for _, params in _merges(driver.in_tx) for r in params["rows"]]
    assert [tuple(r[k] for k in KEY) for r in sent] == [tuple(r[k] for k in KEY) for r in rows]


def test_missing_endpoint_exits_1_before_any_write(monkeypatch, tmp_path, caplog):
    # person:liuer is not in the graph: one read lists every endpoint the file
    # references, the run stops there, and no write transaction is opened.
    rows = [_row("person:a", "FATHER_OF", "person:liuer", source="llm"),
            _row("person:liuer", "SON_OF", "person:a", source="anchored_rule"),
            _row("person:b", "SPOUSE_OF", "person:a", source="llm")]
    driver = _FakeDriver(entities={"person:a", "person:b"})

    _import(monkeypatch, tmp_path, rows, driver=driver, code=1)

    assert driver.transactions == 0
    assert _merges(driver.autocommit + driver.in_tx) == []
    assert [params for _, params in driver.reads] == [
        {"ids": ["person:a", "person:b", "person:liuer"]}]
    assert "person:liuer" in caplog.text
    assert "2 row(s)" in caplog.text


@pytest.mark.parametrize("delta", [-1, 1])
def test_written_count_mismatch_rolls_back_and_exits_1(monkeypatch, tmp_path, caplog, delta):
    # Every endpoint is there, but the second statement reports one edge fewer
    # (an endpoint deleted meanwhile) or one more (a duplicate entity_id): the
    # check runs inside the transaction, so it rolls back and nothing commits.
    rows = [_row(f"person:h{i}", "FATHER_OF", f"person:t{i}", source="llm") for i in range(4)]
    statements = []

    def written(sent):
        statements.append(sent)
        return len(sent) + (delta if len(statements) == 2 else 0)

    driver = _FakeDriver(written=written)

    _import(monkeypatch, tmp_path, rows, "--batch-size", "2", driver=driver, code=1)

    assert (driver.transactions, driver.committed, driver.rolled_back) == (1, 0, 1)
    assert len(statements) == 2
    assert f"wrote {2 + delta} edge(s) for 2 row(s)" in caplog.text
