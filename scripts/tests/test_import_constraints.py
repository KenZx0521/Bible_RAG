"""import_neo4j: global :Entity(entity_id) uniqueness (ID-7/H1), and writes
that fail where they happen.

Per-subtype constraints (Person/Event/...) cannot stop the same entity_id from
existing under two type labels, and `MERGE (e:Entity:Event {entity_id: ...})`
silently creates such a twin. The global constraint turns that into an error.

The real driver reports a statement's failure lazily (session.run only waits
for the RUN reply; a PULL/commit failure surfaces on the next run, or is
swallowed by Session.close() after the last one), so the fakes below can fail
on consume() as well as on run(). That error only helps if every write is
consumed: otherwise a twin rejected by the constraint above blames the next
row, or, as the last row of a batch, vanishes and the import looks green.
"""

import sys

import pytest

import import_neo4j

ENTITY_CONSTRAINT = (
    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE"
)


class _Result:
    def __init__(self, error: Exception | None):
        self._error = error

    def consume(self):
        if self._error is not None:
            raise self._error


class _RecordingSession:
    def __init__(self, driver: "_RecordingDriver"):
        self._driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Like neo4j.Session.close(): an unconsumed failure is dropped here.
        return False

    def run(self, query: str, **params):
        self._driver.statements.append(query)
        if self._driver.fail:
            raise RuntimeError("constraint creation refused")
        lazy = any(f"(n:{label})" in query for label in self._driver.lazy_fail)
        return _Result(RuntimeError(f"deferred failure: {query}") if lazy else None)


class _RecordingDriver:
    def __init__(self, fail: bool = False, lazy_fail: tuple[str, ...] = ()):
        self.statements: list[str] = []
        self.fail = fail
        self.lazy_fail = lazy_fail

    def session(self):
        return _RecordingSession(self)


def test_global_entity_constraint_is_created():
    driver = _RecordingDriver()

    import_neo4j.create_constraints(driver)

    assert ENTITY_CONSTRAINT in driver.statements


def test_subtype_constraints_are_kept():
    driver = _RecordingDriver()

    import_neo4j.create_constraints(driver)

    for label in ("Person", "Place", "Group", "Event", "Object", "Theme"):
        assert (f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE n.entity_id IS UNIQUE") in driver.statements


def test_constraint_failure_is_not_swallowed():
    # A refused constraint (e.g. existing duplicate ids) must stop the import:
    # silently continuing would leave H1 unenforced while the run looks green.
    driver = _RecordingDriver(fail=True)

    with pytest.raises(RuntimeError, match="constraint"):
        import_neo4j.create_constraints(driver)


@pytest.mark.parametrize("label", ["Entity", "Theme"])
def test_deferred_failure_is_raised_for_its_own_label(label):
    # Theme is the last constraint: without consume() its failure would only
    # reach Session.close() and the import would carry on looking green.
    driver = _RecordingDriver(lazy_fail=(label,))

    with pytest.raises(RuntimeError, match=rf":{label}\(entity_id\)"):
        import_neo4j.create_constraints(driver)


def test_deferred_failure_of_the_modern_syntax_falls_back():
    # Only the modern statement fails (older server): the legacy syntax
    # succeeds, so no error and every constraint is still attempted.
    class _ModernFails(_RecordingDriver):
        def session(self):
            return _ModernFailsSession(self)

    class _ModernFailsSession(_RecordingSession):
        def run(self, query, **params):
            self._driver.statements.append(query)
            return _Result(RuntimeError("syntax") if "IF NOT EXISTS" in query else None)

    driver = _ModernFails()

    import_neo4j.create_constraints(driver)

    modern = [q for q in driver.statements if "IF NOT EXISTS" in q]
    legacy = [q for q in driver.statements if "ASSERT" in q]
    assert len(modern) == len(legacy) == 11


def test_main_refuses_staging_on_the_production_graph(monkeypatch):
    # import_neo4j clears the whole graph: KG_TARGET=staging with NEO4J_URI
    # left on (or falling back to) production must stop before connecting.
    monkeypatch.setenv("KG_TARGET", "staging")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")

    def _no_connection():
        raise AssertionError("connected before the target guard ran")
    monkeypatch.setattr(import_neo4j, "get_neo4j_driver", _no_connection)
    monkeypatch.setattr(sys, "argv", ["import_neo4j.py"])

    with pytest.raises(SystemExit, match="NEO4J_URI"):
        import_neo4j.main()


# ------------------------------------------------- writes fail where they happen ---

class _LazyResult:
    def __init__(self, session: "_LazySession", error: Exception | None):
        self._session = session
        self.error = error

    def consume(self):
        self._session.pending = None
        if self.error is not None:
            raise self.error


class _LazySession:
    """neo4j.Session for auto-commit writes: run() returns once RUN is accepted;
    a failure surfaces on consume(), else on the next run() (before that
    statement is sent), else nowhere: close() drops it."""

    def __init__(self, driver: "_LazyDriver"):
        self._driver = driver
        self.pending: _LazyResult | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.pending is not None:
            self._driver.unconsumed += 1    # Session.close() swallows its error
        return False

    def run(self, query: str, **params):
        if self.pending is not None:
            self._driver.unconsumed += 1
            pending, self.pending = self.pending, None
            if pending.error is not None:
                raise pending.error
        self._driver.sent.append(params)
        failing = self._driver.fail_on(len(self._driver.sent) - 1)
        self.pending = _LazyResult(self, RuntimeError(
            f"deferred failure of statement {len(self._driver.sent) - 1}: {params}")
            if failing else None)
        return self.pending


class _LazyDriver:
    def __init__(self, fail_at: int | None = None):
        self.sent: list[dict] = []
        self.unconsumed = 0
        self.fail_on = lambda index: index == fail_at

    def session(self):
        return _LazySession(self)


def _entities(n: int) -> list[dict]:
    return [{"entity_id": f"event:e{i}", "type": "Event", "canonical_name": f"e{i}",
             "description": "", "mention_count": 1, "aliases": []} for i in range(n)]


_WRITERS = {
    "entities": (3, lambda d: import_neo4j._insert_entity_batch(d, _entities(3))),
    "nodes": (3, lambda d: import_neo4j._insert_node_batch(
        d, [{"labels": "Book", "props": {"id": f"b{i}"}} for i in range(3)])),
    "relationships": (3, lambda d: import_neo4j._insert_relationship_batch(
        d, [{"start": f"a{i}", "end": f"b{i}", "type": "CONTAINS", "props": {}}
            for i in range(3)])),
    "clear": (1, import_neo4j.clear_database),
}


@pytest.mark.parametrize("writer", _WRITERS)
def test_every_write_is_consumed_before_the_next(writer):
    count, write = _WRITERS[writer]
    driver = _LazyDriver()

    write(driver)

    assert len(driver.sent) == count and driver.unconsumed == 0


@pytest.mark.parametrize("writer", _WRITERS)
def test_failure_of_the_last_write_is_raised(writer, capsys):
    # The last statement has no next run() to surface its failure, so without
    # consume() Session.close() would drop it and the import would carry on.
    count, write = _WRITERS[writer]
    driver = _LazyDriver(fail_at=count - 1)

    with pytest.raises(RuntimeError, match=f"statement {count - 1}"):
        write(driver)
    assert "Database cleared" not in capsys.readouterr().out


def test_entity_twin_stops_the_batch_at_its_own_row():
    # e.g. :Entity(entity_id) refusing an id already imported under another type.
    driver = _LazyDriver(fail_at=1)

    with pytest.raises(RuntimeError, match="event:e1"):
        import_neo4j._insert_entity_batch(driver, _entities(3))
    assert [p["entity_id"] for p in driver.sent] == ["event:e0", "event:e1"]
    assert driver.unconsumed == 0
