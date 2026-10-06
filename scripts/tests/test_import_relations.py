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

The input is Step 6.05's output, never Step 6's raw relations.jsonl: 6.1 read
whatever file it was given, so a stacked or hand-edited file (two rows of one
key, a row with no source) went into the graph as it was (§6 #11). The file
must now hash to its 6.05 report's output.sha256, hold the report's rows, carry
the report's pp_version on every row, give every row head_id, relation,
tail_id and source, and hold each key once; otherwise the run exits 2 before
it connects.

Nor is the file stacked on an old layer: 6.1 imported into whatever graph it
reached, so a re-run on a built graph kept every edge the new file no longer
has (§6 #11). Step 5 rebuilds the graph without a single Entity-Entity edge
besides MENTIONS and CROSS_REFERENCES, so finding one means 6.1 (or 10.3) has
already run there: the import stops (exit 1) before any write. Only --replace,
from a staging shell (kg_target.require_staging), deletes that layer, inside
the transaction that writes the file; the standard chain never passes it.

The fake driver records auto-commit statements (session.run) separately from
statements run inside session.execute_read and session.execute_write, modelled
on test_import_constraints.py. It holds a set of entity_ids for the endpoint
read and a count of the semantic-layer edges already in the graph, and a write
transaction commits only if its work returns. Files are written by
_db_env_helpers.write_relations_clean, with a matching report. Every test runs
in a shell without KG_TARGET unless it takes the staging_target fixture.
"""

import json
import re
import sys

import pytest

import import_relations_neo4j
# staging_target is a pytest fixture: importing it is what makes it available here.
from _db_env_helpers import PP_VERSION, staging_target, write_relations_clean  # noqa: F401
from relation_extraction import relation_postprocess as pp

KEY = ("head_id", "relation", "tail_id")
REQUIRED = ("head_id", "relation", "tail_id", "source")
MERGE_WITHOUT_MAPS = re.compile(
    r"apoc\.merge\.relationship\(\s*h,\s*row\.relation,\s*\{\},\s*\{\},\s*t,\s*\{\}\s*\)")
# The semantic layer: every Entity-Entity edge but MENTIONS and CROSS_REFERENCES.
LAYER = re.compile(r"MATCH \(:Entity\)-\[r\]->\(:Entity\)\s+"
                   r"WHERE NOT type\(r\) IN \['MENTIONS', 'CROSS_REFERENCES'\]\s")


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
        if "rows" in params:
            return _Result([{"written": self._driver.written(params["rows"])}])
        return _Result([{"edges": self._driver.layer}])   # the layer's count, or its delete


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
    written: rows of one write statement -> the edge count it reports.
    layer: the semantic-layer edges already in the graph (Step 5 leaves 0)."""

    def __init__(self, entities: set[str] | None = None, written=len, layer: int = 0):
        self.entities, self.written, self.layer = entities, written, layer
        self.autocommit: list[tuple[str, dict]] = []
        self.reads: list[tuple[str, dict]] = []
        self.in_tx: list[tuple[str, dict]] = []
        self.connections = self.transactions = self.committed = self.rolled_back = 0

    def connect(self, *args, **kwargs) -> "_FakeDriver":
        """Stands in for GraphDatabase.driver: counts the connections main() opens."""
        self.connections += 1
        return self

    def has(self, entity_id: str) -> bool:
        return self.entities is None or entity_id in self.entities

    def session(self, **kwargs):
        return _Session(self)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _shell_without_target(monkeypatch):
    """The standard chain's shell; the staging_target fixture, set up after
    this one, exports a staging shell instead."""
    monkeypatch.delenv("KG_TARGET", raising=False)


def _row(head, relation, tail, **extra) -> dict:
    """A row as 6.05 stamps it (pp_version); tests add source and the rest."""
    return {"head_id": head, "relation": relation, "tail_id": tail,
            "pp_version": PP_VERSION, **extra}


def _main(monkeypatch, argv: list[str], driver: _FakeDriver | None = None,
          code: int = 0) -> _FakeDriver:
    driver = driver or _FakeDriver()
    monkeypatch.setattr(import_relations_neo4j.GraphDatabase, "driver", driver.connect)
    monkeypatch.setattr(sys, "argv", ["import_relations_neo4j.py", *argv])

    assert import_relations_neo4j.main() == code
    return driver


def _import(monkeypatch, tmp_path, rows: list[dict], *flags: str,
            driver: _FakeDriver | None = None, code: int = 0) -> _FakeDriver:
    path = write_relations_clean(tmp_path, rows)
    return _main(monkeypatch, [str(path), *flags], driver=driver, code=code)


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
                   "extraction_phase": 6, "pp_version": PP_VERSION}},
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
    assert [params for _, params in driver.reads if "ids" in params] == [
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


# --- the input contract: 6.05's output, exactly as its report describes it -----

TWO_ROWS = [_row("person:a", "FATHER_OF", "person:b", source="llm"),
            _row("person:b", "SPOUSE_OF", "person:c", source="anchored_rule")]
OTHER_PP = "pp-111111111111"


def _report_path(path):
    return path.with_name("relations_clean.report.json")


def _edit_report(path, **output) -> None:
    report = json.loads(_report_path(path).read_text(encoding="utf-8"))
    report["pp_version"] = output.pop("pp_version", report["pp_version"])
    report["output"].update(output)
    _report_path(path).write_text(json.dumps(report), encoding="utf-8")


def _edit_rows(path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


# case -> (rows written with a matching report, the edit made afterwards, logged)
NOT_AS_REPORTED = {
    "row edited after 6.05": (TWO_ROWS, lambda p: _edit_rows(p, "SPOUSE_OF", "SIBLING_OF"),
                              "output.sha256"),
    "file stacked on itself": (TWO_ROWS, lambda p: p.write_bytes(p.read_bytes() * 2),
                               "output.sha256"),
    "report rows": (TWO_ROWS, lambda p: _edit_report(p, rows=3), "the report says 3"),
    "report pp_version": (TWO_ROWS, lambda p: _edit_report(p, pp_version=OTHER_PP), OTHER_PP),
    "row of another 6.05 run": ([TWO_ROWS[0], {**TWO_ROWS[1], "pp_version": OTHER_PP}],
                                lambda p: None, OTHER_PP),
    "no report": (TWO_ROWS, lambda p: _report_path(p).unlink(), "no 6.05 report"),
    # A null pp_version would let through every row that carries none.
    "report pp_version null": ([{k: v for k, v in row.items() if k != "pp_version"} for row in TWO_ROWS],
                               lambda p: _edit_report(p, pp_version=None), "not a 6.05 report"),
    # true == 1, so only the type tells a boolean from the row count.
    "report rows true": ([TWO_ROWS[0]], lambda p: _edit_report(p, rows=True), "not a 6.05 report"),
}


def test_default_path_is_relations_clean():
    # Whatever 6.05 writes by default is what 6.1 reads by default: its
    # relations_clean.jsonl and the report beside it, never Step 6's raw
    # relations.jsonl (inverse and id-order rule rows included).
    args = import_relations_neo4j._parser().parse_args([])

    assert args.path == pp.DEFAULT_OUT
    assert args.report is None
    assert import_relations_neo4j.sibling_report(args.path) == pp.DEFAULT_REPORT


@pytest.mark.parametrize("case", sorted(NOT_AS_REPORTED))
def test_report_sha_rows_or_pp_version_mismatch_refused_before_connecting(
        case, monkeypatch, tmp_path, caplog):
    rows, edit, logged = NOT_AS_REPORTED[case]
    path = write_relations_clean(tmp_path, rows)
    edit(path)

    driver = _main(monkeypatch, [str(path)], code=2)

    assert driver.connections == 0
    assert logged in caplog.text


def test_report_flag_reads_a_report_kept_elsewhere(monkeypatch, tmp_path):
    path = write_relations_clean(tmp_path / "out", TWO_ROWS)
    moved = _report_path(path).rename(tmp_path / "kept.report.json")

    assert _main(monkeypatch, [str(path)], code=2).connections == 0
    assert _main(monkeypatch, [str(path), "--report", str(moved)]).connections == 1


def test_duplicate_key_refused_before_connecting(monkeypatch, tmp_path, caplog):
    # An undirected pair written both ways is two keys and imports: the
    # --rules none P1 control keeps such pairs, and H11 counts them on the
    # all-mode chain. Two rows of one key would be two writes of one edge, the
    # later one winning, so they are refused (6.05's collapse_by_key leaves one).
    pair = [_row("person:a", "SPOUSE_OF", "person:b", source="llm"),
            _row("person:b", "SPOUSE_OF", "person:a", source="llm")]
    assert _import(monkeypatch, tmp_path / "pair", pair).connections == 1

    stacked = [*pair, _row("person:a", "SPOUSE_OF", "person:b", source="prior")]
    driver = _import(monkeypatch, tmp_path / "stacked", stacked, code=2)

    assert driver.connections == 0
    assert "person:a SPOUSE_OF person:b" in caplog.text


@pytest.mark.parametrize("value", ["absent", None, ""])
@pytest.mark.parametrize("field", REQUIRED)
def test_missing_required_field_refused(field, value, monkeypatch, tmp_path, caplog):
    row = _row("person:a", "FATHER_OF", "person:b", source="llm")
    broken = ({k: v for k, v in row.items() if k != field} if value == "absent"
              else {**row, field: value})
    rows = [_row("person:c", "SON_OF", "person:a", source="llm"), broken]

    driver = _import(monkeypatch, tmp_path, rows, code=2)

    assert driver.connections == 0
    assert f"row 2: no {field}" in caplog.text


# --- the empty-layer guard; --replace is staging-only -------------------------

def _layer_statements(statements: list[tuple[str, dict]], verb: str) -> list[str]:
    """The statements on the semantic layer that contain verb (count(r) or DELETE)."""
    return [q for q, _ in statements if LAYER.search(q) and verb in q]


@pytest.mark.parametrize("layer", [1, 15926], ids=["one_stray_edge", "prod_today"])
def test_non_empty_layer_without_replace_exits_1(layer, monkeypatch, tmp_path, caplog):
    # The graph already holds 15,926 semantic edges (prod and staging today:
    # 6.1 and 10.3 have run there). Importing again would stack this file on
    # them, keeping every edge it no longer has, so the run stops before any
    # write; the standard chain runs 6.1 right after Step 5, never with --replace.
    # One edge left over (a stray 10.3 edge) stops it as well.
    driver = _FakeDriver(layer=layer)

    _import(monkeypatch, tmp_path, TWO_ROWS, driver=driver, code=1)

    assert driver.transactions == 0
    assert _merges(driver.autocommit + driver.in_tx) == []
    assert len(_layer_statements(driver.reads, "count(r)")) == 1
    assert _layer_statements(driver.autocommit + driver.reads + driver.in_tx, "DELETE") == []
    assert f"already holds {layer} semantic edge(s)" in caplog.text
    assert "Step 5 empties the graph" in caplog.text


@pytest.mark.parametrize("target", [None, "prod"])
def test_replace_refused_outside_staging(target, monkeypatch, tmp_path):
    # --replace deletes a whole layer: from a shell that has not sourced
    # staging.env (KG_TARGET unset or prod), it stops before connecting.
    if target:
        monkeypatch.setenv("KG_TARGET", target)
    driver = _FakeDriver(layer=3)

    with pytest.raises(SystemExit) as exc:
        _import(monkeypatch, tmp_path, TWO_ROWS, "--replace", driver=driver)

    assert "KG_TARGET is not staging" in str(exc.value)
    assert driver.connections == 0


def test_replace_deletes_then_writes_in_one_transaction(staging_target, monkeypatch,
                                                        tmp_path, caplog):
    # On staging, --replace deletes the old layer as the first statement of the
    # transaction that writes the file: the layer becomes exactly the file.
    driver = _FakeDriver(layer=7)

    _import(monkeypatch, tmp_path, TWO_ROWS, "--replace", "--batch-size", "1", driver=driver)

    assert (driver.transactions, driver.committed) == (1, 1)
    queries = [q for q, _ in driver.in_tx]
    assert _layer_statements(driver.in_tx, "DELETE r") == queries[:1]
    assert len(_merges(driver.in_tx)) == 2 == len(queries) - 1
    assert _layer_statements(driver.autocommit + driver.reads, "DELETE") == []
    assert "7 edge(s)" in caplog.text

    # A written mismatch rolls the delete back with the writes.
    failing = _FakeDriver(layer=7, written=lambda sent: len(sent) - 1)
    _import(monkeypatch, tmp_path / "fail", TWO_ROWS, "--replace", driver=failing, code=1)

    assert (failing.transactions, failing.committed, failing.rolled_back) == (1, 0, 1)
    assert _layer_statements(failing.in_tx, "DELETE r") == [failing.in_tx[0][0]]


def test_replace_on_an_empty_or_refused_file_connects_nowhere_and_announces_no_delete(
        staging_target, monkeypatch, tmp_path, caplog):
    # An empty 6.05 output exits 0 and a refused one 2, both before connecting:
    # even with --replace the old layer stays, so neither run may log that it
    # will be deleted (the W1 runbook's --replace logs go into the record).
    driver = _FakeDriver(layer=7)
    _import(monkeypatch, tmp_path / "empty", [], "--replace", driver=driver)
    refused = write_relations_clean(tmp_path / "refused", TWO_ROWS)
    _report_path(refused).unlink()
    _main(monkeypatch, [str(refused), "--replace"], driver=driver, code=2)

    assert driver.connections == 0
    assert "Empty relations file" in caplog.text and "no 6.05 report" in caplog.text
    assert "will be deleted" not in caplog.text

    # A file that is imported still announces the delete before connecting.
    _import(monkeypatch, tmp_path / "rows", TWO_ROWS, "--replace", driver=driver)

    assert driver.connections == 1
    assert "will be deleted and rewritten" in caplog.text
