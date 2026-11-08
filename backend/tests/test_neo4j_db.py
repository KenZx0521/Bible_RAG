"""database.neo4j_db: closed Cypher templates, and what happens when Neo4j does not answer.

Every failure reaches the caller as ``Skipped``: the graph side goes without it, a request never
fails. A connection or authentication error skips Neo4j for 30 s; one timeout skips only the
question, because the reranker blocks the event loop and a timeout does not mean Neo4j is down.
"""

import asyncio
import re

import pytest

from database import cypher, neo4j_db
from database.neo4j_db import (AuthError, ConnectionAcquisitionTimeoutError, DriverError, Neo4jError,
                               ServiceUnavailable)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        async def rows():
            for row in self._rows:
                yield row
        return rows()


class _Session:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, params):
        self.driver.ran.append((query, params))
        step = self.driver.script.pop(0) if self.driver.script else [{"x": 1}]
        if isinstance(step, Exception):
            raise step
        if step == "hang":
            await asyncio.sleep(60)
        return _Result(step)


class _Driver:
    def __init__(self, *script):
        self.script = list(script)
        self.ran = []
        self.modes = []

    def session(self, default_access_mode=None):
        self.modes.append(default_access_mode)
        return _Session(self)


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(neo4j_db, "_now", lambda: now[0])
    return now


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(neo4j_db, "QUERY_S", 0.01)


def _driver(monkeypatch, *script) -> _Driver:
    driver = _Driver(*script)
    monkeypatch.setattr(neo4j_db, "get_driver", lambda: driver)
    return driver


def _read(name="build_info", **params):
    return asyncio.run(neo4j_db.read(name, **{"b": "b1", **params}))


def _reason(name="build_info") -> str:
    with pytest.raises(neo4j_db.Skipped) as caught:
        _read(name)
    return caught.value.reason


# --- the templates ------------------------------------------------------------------------------

def test_only_a_template_name_is_accepted(monkeypatch):
    driver = _driver(monkeypatch)
    with pytest.raises(ValueError, match="MATCH"):
        _read("MATCH (n) RETURN n")
    assert driver.ran == []


def test_a_template_over_a_build_needs_its_build_id(monkeypatch):
    driver = _driver(monkeypatch)
    with pytest.raises(ValueError, match="build"):
        asyncio.run(neo4j_db.read("build_info"))
    assert driver.ran == []


def test_a_read_runs_the_template_read_only_with_the_params(monkeypatch):
    driver = _driver(monkeypatch, [{"info": {"complete": True}}])

    rows = _read("build_info", b="b7")

    assert rows == [{"info": {"complete": True}}]
    assert driver.ran == [(cypher.TEMPLATES["build_info"], {"b": "b7"})]
    assert driver.modes == [neo4j_db.READ_ACCESS]


def _lint(query: str) -> list[str]:
    """What is wrong with a template: every rule of ``database.cypher``, in any case and any spelling."""
    out = []
    if re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|FOREACH)\b", query, re.I):
        out.append("writes")
    if re.search(r"LOAD\s+CSV", query, re.I):
        out.append("reads a file")
    if re.search(r"-\[[^\]]*\*", query):
        out.append("bare var-length")
    if re.search(r"\)[+*]", query) or re.search(r"\)\{\d*,\}", query):
        out.append("unbounded quantified path")
    if any(not 1 <= int(low) <= int(high) <= 5 for low, high in re.findall(r"\)\{(\d+),(\d+)\}", query)):
        out.append("quantified path over five hops")
    if re.search(r"ANY\s+SHORTEST|shortestPath|allShortestPaths", query, re.I):
        out.append("a shortest path that is not ALL SHORTEST")
    if re.search(r"\b(elementId|id)\(", query, re.I) or "apoc." in query.lower():
        out.append("unstable node id or a plugin")
    for found in re.finditer(r"\bLIMIT\b", query, re.I):
        clause = query[:found.start()].rsplit("}", 1)[-1]
        if not re.search(r"\bORDER\s+BY\b", clause, re.I):
            out.append("LIMIT without ORDER BY in its clause")
    return out + _unconfined(query)


def _unconfined(query: str) -> list[str]:
    """A MATCH must name the build or start from a variable something before it bound."""
    out = []
    pieces = re.split(r"(?=\b(?:OPTIONAL\s+)?MATCH\b)", query, flags=re.I)
    seen = pieces[0]
    for piece in pieces[1:]:
        clause = re.split(r"\b(?:WHERE|WITH|RETURN|UNWIND|CALL)\b", piece, maxsplit=1, flags=re.I)[0]
        confined = "build_id:$b" in clause.replace(" ", "") or any(
            re.search(rf"\b{name}\b", seen) for name in re.findall(r"\((\w+)[:)\s]", clause))
        if not confined and "dbms.components" not in query:
            out.append(f"MATCH outside the build: {clause.strip()[:60]}")
        seen += piece
    return out


@pytest.mark.parametrize("name", sorted(cypher.TEMPLATES))
def test_every_template_keeps_the_rules(name):
    assert _lint(cypher.TEMPLATES[name]) == [], name


@pytest.mark.parametrize("query", [
    "MATCH p = (a {build_id:$b}) ((u)-[:R]-(v))+ (c) RETURN p",
    "MATCH p = (a {build_id:$b}) ((u)-[:R]-(v))* (c) RETURN p",
    "MATCH p = (a {build_id:$b}) ((u)-[:R]-(v)){1,} (c) RETURN p",
    "MATCH p = (a {build_id:$b}) ((u)-[:R]-(v)){1,6} (c) RETURN p",
    "MATCH (a {build_id:$b})-[:R*]->(c) RETURN c",
    "match (a {build_id:$b}) create (c) return c",
    "match (a {build_id:$b}) detach delete a",
    "match (a {build_id:$b}) return a limit 3",
    "MATCH (a {build_id:$b}) RETURN a LIMIT 3",
    "LOAD CSV FROM 'file:///x' AS line MATCH (a {build_id:$b}) RETURN a",
    "MATCH (a {build_id:$b}) MATCH (c:Person) RETURN a, c",
    "CALL () { MATCH (a {build_id:$b}) RETURN a ORDER BY a.id } MATCH (a) RETURN a LIMIT 3",
    "match p = any shortest (a {build_id:$b}) ((u)-[:R]-(v)){1,5} (c) return p",
    "MATCH (a {build_id:$b}) RETURN id(a)",
    "MATCH (a {build_id:$b}) RETURN elementId(a)",
    "MATCH (a {build_id:$b}) CALL apoc.path.expand(a) YIELD path RETURN path",
])
def test_the_rules_catch_a_template_that_breaks_them(query):
    assert _lint(query) != []


def test_paths_are_all_shortest_and_at_most_five_hops():
    query = cypher.TEMPLATES["kin_path"]
    assert "ALL SHORTEST" in query and "){1,5}" in query


@pytest.mark.parametrize("name", sorted(set(cypher.TEMPLATES) - {"server_version"}))
def test_every_template_is_confined_to_one_build(name):
    assert "build_id:$b" in cypher.TEMPLATES[name].replace(" ", "")


# --- when Neo4j does not answer -----------------------------------------------------------------

@pytest.mark.parametrize("error, reason", [
    (ServiceUnavailable("refused"), neo4j_db.UNAVAILABLE),
    (AuthError("wrong password"), neo4j_db.AUTH),
])
def test_a_connection_or_auth_error_skips_neo4j_for_30_s_then_it_is_tried_again(
        monkeypatch, clock, error, reason):
    driver = _driver(monkeypatch, error, [{"x": 1}])

    assert _reason() == reason
    assert _reason() == neo4j_db.SKIPPING
    clock[0] += neo4j_db.SKIP_S - 1
    assert _reason() == neo4j_db.SKIPPING
    assert len(driver.ran) == 1

    clock[0] += 1
    assert _read() == [{"x": 1}]
    assert len(driver.ran) == 2


def test_one_timeout_skips_only_that_question(monkeypatch, clock, fast):
    driver = _driver(monkeypatch, "hang", [{"x": 1}])

    assert _reason() == neo4j_db.TIMEOUT
    assert _read() == [{"x": 1}]
    assert len(driver.ran) == 2


def test_two_timeouts_in_a_row_skip_neo4j_for_30_s(monkeypatch, clock, fast):
    driver = _driver(monkeypatch, "hang", "hang", [{"x": 1}])

    assert _reason() == neo4j_db.TIMEOUT
    assert _reason() == neo4j_db.TIMEOUT
    assert _reason() == neo4j_db.SKIPPING
    assert len(driver.ran) == 2

    clock[0] += neo4j_db.SKIP_S
    assert _read() == [{"x": 1}]


def test_an_answer_between_two_timeouts_resets_the_count(monkeypatch, clock, fast):
    driver = _driver(monkeypatch, "hang", [{"x": 1}], "hang", [{"x": 2}])

    assert _reason() == neo4j_db.TIMEOUT
    assert _read() == [{"x": 1}]
    assert _reason() == neo4j_db.TIMEOUT
    assert _read() == [{"x": 2}]
    assert len(driver.ran) == 4


def test_a_full_pool_counts_as_a_timeout(monkeypatch, clock):
    _driver(monkeypatch, ConnectionAcquisitionTimeoutError("pool"), [{"x": 1}])

    assert _reason() == neo4j_db.TIMEOUT
    assert _read() == [{"x": 1}]


@pytest.mark.parametrize("error", [Neo4jError("bad"), DriverError("broken")])
def test_any_other_driver_error_skips_the_question_and_neo4j_stays_on(monkeypatch, clock, error):
    driver = _driver(monkeypatch, error, [{"x": 1}])

    assert _reason() == neo4j_db.ERROR
    assert _read() == [{"x": 1}]
    assert len(driver.ran) == 2


def test_nothing_configured_is_a_skip_and_no_driver(monkeypatch, clock):
    monkeypatch.setattr(neo4j_db.settings, "neo4j_uri", "")
    monkeypatch.setattr(neo4j_db, "_driver", None)
    assert _reason() == neo4j_db.NOT_CONFIGURED


def test_a_skip_never_carries_the_message_of_the_error(monkeypatch, clock):
    _driver(monkeypatch, AuthError("bolt://neo4j:s3cret@host"))
    with pytest.raises(neo4j_db.Skipped) as caught:
        _read()
    assert "s3cret" not in str(caught.value)


def test_the_driver_is_short_and_retries_nothing():
    assert (neo4j_db.POOL_SIZE, neo4j_db.CONNECT_S, neo4j_db.ACQUIRE_S, neo4j_db.QUERY_S) == (8, 0.3, 0.4, 0.8)
