"""Step 9 (import_tsk_crossrefs) on a Step 5 graph whose curated rows carry flags.

The old MERGE wrote votes only ON CREATE, so a TSK pair that Step 5 had already
written as a curated edge kept no votes and no TSK mark (XREF-4: 856 pairs, 924
after re-anchoring), and the import still looked green. Now votes, verse_pairs
and tsk are SET on every matched pair; ON CREATE only marks a pure TSK edge
(source 'tsk', curated false). The run is gated:

- before any write, also on --dry-run: no CROSS_REFERENCES edge may lack the
  curated or tsk flag. A graph built before 1B (batch-0 staging, crit#5) is
  refused instead of half rewritten;
- then, also on --dry-run, every supplementary anchor on the graph needs a TSK
  verse pair in its own direction, source verse → target verse, unless the
  edge lists it in supp_tsk_exempt_anchors. Reverse-only support is not
  enough (crit#6). The gate is verse-level: at pericope level every
  definition, the 3 XREF-2 ones included, looks supported (deviation #14);
- after the write: matched == rows, count(tsk) == rows, count(tsk and curated)
  == attached_to_curated, no unflagged edge. Then the edge fingerprint.

FakeGraph answers the script's queries with the semantics their Cypher spells
out; the MERGE text itself is pinned by test_merge_cypher_sets_votes_unconditionally,
the gates' read queries by test_read_queries_spell_the_gates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j import READ_ACCESS

import import_tsk_crossrefs as its
from bible_chunking.curated_xrefs import (EDGE_FINGERPRINT_CYPHER, Anchor, aggregate_curated,
                                          edge_fingerprint)

ROOT = Path(__file__).resolve().parents[2]
TSK = ROOT / "output/cross_references_tsk.txt"
QUEUE = ROOT / "output/embedding_queue.jsonl"
SUPP_FIXTURE = ROOT / "scripts/tests/fixtures/xref/supp_expected_anchors.json"
needs_output = pytest.mark.skipif(not (TSK.is_file() and QUEUE.is_file()),
                                  reason="needs output/cross_references_tsk.txt and embedding_queue.jsonl")
needs_tsk = pytest.mark.skipif(not TSK.is_file(), reason="needs output/cross_references_tsk.txt")

VMAP = {("gen", 1, 1): "gen:1:0", ("gen", 1, 2): "gen:1:0", ("gen", 1, 3): "gen:1:1",
        ("exo", 1, 1): "exo:1:0", ("mat", 1, 1): "mat:1:0"}
TSK_LINES = [
    "Gen.1.1\tExod.1.1\t10",
    "Gen.1.2\tExod.1.1\t4",            # same pericope pair: max votes, 2 verse pairs
    "Gen.1.1\tGen.1.3\t2",
    "Gen.1.1\tGen.1.2\t7",             # self loop
    "Gen.1.1\tMatt.1.1\t-3",           # negative votes
    "Matt.1.1\tGen.1.1-Gen.1.3\t5",    # range: one row per touched pericope
    "Rev.1.1\tGen.1.1\t3",             # source verse not in the map
    "Foo.1.1\tGen.1.1\t3",             # unknown book
]
PAIRS = {("gen:1:0", "exo:1:0"): {"votes": 10, "verse_pairs": 2},
         ("gen:1:0", "gen:1:1"): {"votes": 2, "verse_pairs": 1},
         ("mat:1:0", "gen:1:0"): {"votes": 5, "verse_pairs": 1},
         ("mat:1:0", "gen:1:1"): {"votes": 5, "verse_pairs": 1}}
PERICOPES = ("gen:1:0", "gen:1:1", "exo:1:0", "mat:1:0")


def curated(source: str, **lists) -> dict:
    """A Step 5 curated row (aggregate_curated): flagged, no votes, the source's lists."""
    return {"source": source, "curated": True, "tsk": False, "curated_sources": [source], **lists}


SUPP_ANCHOR = "gen 1:1-2>exo 1:1"   # forward: Gen.1.1→Exod.1.1 (10), Gen.1.2→Exod.1.1 (4)
SUPP_EDGE = curated("supplementary", supp_anchors=[SUPP_ANCHOR])

# Step 5 output: one curated pair TSK also has, one it does not.
STEP5_EDGES = (("gen:1:0", "exo:1:0", SUPP_EDGE),
               ("exo:1:0", "gen:1:0", curated("markdown")))


# ---------------------------------------------------------------- fake driver

class _Record(dict):
    def data(self) -> dict:
        return dict(self)


class _Result:
    def __init__(self, records: list[dict], created: int = 0):
        self._records = [_Record(r) for r in records]
        self._summary = SimpleNamespace(counters=SimpleNamespace(relationships_created=created))

    def __iter__(self):
        return iter(self._records)

    def single(self):
        assert len(self._records) == 1
        return self._records[0]

    def consume(self):
        return self._summary


class FakeGraph:
    """The driver and the store: records every session's kwargs and every query
    as (session access mode, transaction kind, cypher)."""

    def __init__(self, pericopes=PERICOPES, edges=STEP5_EDGES):
        self.pericopes = set(pericopes)
        self.edges = {(a, b): dict(props) for a, b, props in edges}
        self.sessions: list[dict] = []
        self.calls: list[tuple] = []
        self.closed = False

    def session(self, **kwargs):
        self.sessions.append(kwargs)
        return _Session(self, kwargs.get("default_access_mode"))

    def close(self) -> None:
        self.closed = True

    def merges(self) -> int:
        return sum(cypher == its._MERGE_CYPHER for *_, cypher in self.calls)

    def answer(self, cypher: str, params: dict) -> _Result:
        if cypher == its._MERGE_CYPHER:
            return self._merge(params["rows"])
        if cypher == its._COUNTS_CYPHER:
            return _Result([self._counts()])
        if cypher == its._CURATED_PAIRS_CYPHER:
            return _Result([{"a": a, "b": b} for (a, b), p in self.edges.items()
                            if p.get("curated") is True])
        if cypher == EDGE_FINGERPRINT_CYPHER:
            return _Result(self.fingerprint_rows())
        if cypher == its._SUPP_ANCHORS_CYPHER:
            return _Result([{"a": a, "b": b, "anchors": p["supp_anchors"],
                             "exempt": p.get("supp_tsk_exempt_anchors", [])}
                            for (a, b), p in self.edges.items() if "supp_anchors" in p])
        raise AssertionError(f"unexpected query: {cypher}")

    def fingerprint_rows(self) -> list[dict]:
        return [{"a": a, "b": b, **{k: p.get(k) for k in ("votes", "verse_pairs", "curated", "tsk")}}
                for (a, b), p in self.edges.items()]

    def _merge(self, rows: list[dict]) -> _Result:
        matched = created = 0
        for row in rows:
            pair = (row["from_id"], row["to_id"])
            if not set(pair) <= self.pericopes:
                continue
            if pair not in self.edges:
                self.edges[pair] = {"source": "tsk", "curated": False}
                created += 1
            self.edges[pair].update(votes=row["votes"], verse_pairs=row["verse_pairs"], tsk=True)
            matched += 1
        return _Result([{"matched": matched}], created)

    def _counts(self) -> dict:
        props = list(self.edges.values())
        return {"total": len(props),
                "curated": sum(p.get("curated") is True for p in props),
                "unflagged": sum(p.get("curated") is None or p.get("tsk") is None for p in props),
                "tsk": sum(p.get("tsk") is True for p in props),
                "tsk_curated": sum(p.get("tsk") is True and p.get("curated") is True for p in props)}


class _Session:
    def __init__(self, graph: FakeGraph, mode):
        self.graph, self.mode = graph, mode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _tx(self, kind: str):
        def run(cypher, **params):
            if kind == "read" and cypher == its._MERGE_CYPHER:
                raise AssertionError("the server rejects a write in a READ transaction")
            self.graph.calls.append((self.mode, kind, cypher))
            return self.graph.answer(cypher, params)
        return SimpleNamespace(run=run)

    def execute_read(self, fn, *args):
        return fn(self._tx("read"), *args)

    def execute_write(self, fn, *args):
        return fn(self._tx("write"), *args)


def _write_tsk(path: Path, lines=TSK_LINES) -> Path:
    path.write_text("From Verse\tTo Verse\tVotes\n" + "".join(f"{l}\n" for l in lines),
                    encoding="utf-8")
    return path


def _main(graph: FakeGraph, monkeypatch, tmp_path, *flags: str) -> int:
    monkeypatch.delenv("KG_TARGET", raising=False)
    monkeypatch.setattr(its, "get_driver", lambda: graph)
    monkeypatch.setattr(its, "build_verse_map", lambda path: dict(VMAP))
    return its.main([str(_write_tsk(tmp_path / "cross_references.txt")), *flags])


# ---------------------------------------------------------------- Cypher

def test_merge_cypher_sets_votes_unconditionally():
    text = " ".join(its._MERGE_CYPHER.split())
    clauses = re.search(r"ON CREATE SET (.+?) SET (.+?) RETURN", text)
    assert clauses, text

    def assigned(clause):
        return dict((k, v.strip()) for k, v in re.findall(r"r\.(\w+) = ([^,]+)", clause))

    assert assigned(clauses[1]) == {"source": "'tsk'", "curated": "false"}
    assert assigned(clauses[2]) == {"votes": "row.votes", "verse_pairs": "row.verse_pairs",
                                    "tsk": "true"}
    assert "ON MATCH" not in text


def test_read_queries_spell_the_gates():
    # FakeGraph answers these by identity and counts in Python, so only their text says
    # what the graph is asked; unflagged is crit#5's precondition and a post-write gate
    counts = " ".join(its._COUNTS_CYPHER.split())
    assert counts.startswith("MATCH ()-[r:CROSS_REFERENCES]->() RETURN "), counts
    assert {alias: expr for expr, alias in re.findall(r"count\((.+?)\) AS (\w+)", counts)} == {
        "total": "r",
        "curated": "CASE WHEN r.curated = true THEN 1 END",
        "unflagged": "CASE WHEN r.curated IS NULL OR r.tsk IS NULL THEN 1 END",
        "tsk": "CASE WHEN r.tsk = true THEN 1 END",
        "tsk_curated": "CASE WHEN r.tsk = true AND r.curated = true THEN 1 END"}
    assert " ".join(its._CURATED_PAIRS_CYPHER.split()) == (
        "MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope) WHERE r.curated = true "
        "RETURN a.id AS a, b.id AS b")


# ---------------------------------------------------------------- aggregate_tsk

def test_aggregate_tsk_semantics(tmp_path):
    pairs, stats = its.aggregate_tsk(_write_tsk(tmp_path / "tsk.txt"), VMAP)

    assert pairs == PAIRS
    assert (stats["lines"], stats["negative_votes_dropped"], stats["self_loops_dropped"],
            stats["from_unmapped"], stats["from_unparsed"]) == (8, 1, 1, 1, 1)


@needs_output
def test_real_tsk_aggregates_to_250358_pairs():
    pairs, stats = its.aggregate_tsk(TSK, its.build_verse_map(QUEUE))

    assert len(pairs) == 250_358
    assert {pair: v["votes"] for pair, v in pairs.items() if v["votes"] >= 999} == {
        ("jer:29:0", "isa:55:0"): 1130, ("rom:8:1", "eph:1:1"): 1268,
        ("rom:8:1", "jer:1:1"): 1143}
    assert (stats["lines"], stats["negative_votes_dropped"], stats["self_loops_dropped"]) == (
        344_799, 1_166, 9_811)


# ---------------------------------------------------------------- precondition (crit#5)

def _unflagged_graph() -> FakeGraph:
    """Five edges as a pre-1B Step 5 or an earlier Step 9 left them: no flags."""
    return FakeGraph(edges=(
        ("gen:1:0", "exo:1:0", {"source": "markdown"}),
        ("exo:1:0", "gen:1:0", {"source": "supplementary"}),
        ("gen:1:0", "gen:1:1", {"source": "tsk", "votes": 2, "verse_pairs": 1}),
        ("mat:1:0", "gen:1:0", {"source": "tsk", "votes": 5, "verse_pairs": 1}),
        ("mat:1:0", "gen:1:1", {"source": "tsk", "votes": 5, "verse_pairs": 1, "curated": False}),
    ))


@pytest.mark.parametrize("flags", [(), ("--dry-run",)])
def test_precondition_unflagged_graph_exits_1_before_any_write(flags, monkeypatch, tmp_path, capsys):
    graph = _unflagged_graph()
    before = {pair: dict(p) for pair, p in graph.edges.items()}

    assert _main(graph, monkeypatch, tmp_path, *flags) == 1

    assert graph.merges() == 0 and graph.edges == before
    assert all(s.get("default_access_mode") == READ_ACCESS for s in graph.sessions)
    err = capsys.readouterr().err
    assert "5 of 5 CROSS_REFERENCES edges have curated or tsk unset" in err
    assert "are curated" not in err      # Step 5 did load them, only without flags
    assert graph.closed


@pytest.mark.parametrize("flags", [(), ("--dry-run",)])
@pytest.mark.parametrize("edges", [(), (("gen:1:0", "gen:1:1", {"source": "tsk", "curated": False,
                                                              "tsk": True}),)],
                         ids=["empty", "tsk-only"])
def test_precondition_no_curated_edge_exits_1_before_any_write(edges, flags, monkeypatch, tmp_path,
                                                               capsys):
    # Step 5 skips a missing neo4j_relationships.jsonl without failing. Step 9 would
    # then create only pure TSK edges, and every count gate passes (attached 0).
    graph = FakeGraph(edges=edges)
    before = {pair: dict(p) for pair, p in graph.edges.items()}

    assert _main(graph, monkeypatch, tmp_path, *flags) == 1

    assert graph.merges() == 0 and graph.edges == before
    assert all(s.get("default_access_mode") == READ_ACCESS for s in graph.sessions)
    err = capsys.readouterr().err
    assert f"0 of {len(edges)} CROSS_REFERENCES edges are curated" in err
    # rerunning Step 5 alone skips the missing file again: Step 0 has to restore it
    assert "restore output/neo4j_relationships.jsonl (Step 0" in err
    assert "rerun Step 5 first" not in err
    assert graph.closed


# ---------------------------------------------------------------- write + gates

def test_count_gates_pass_exit_0(monkeypatch, tmp_path, capsys):
    graph = FakeGraph()

    assert _main(graph, monkeypatch, tmp_path) == 0

    out = capsys.readouterr().out
    assert "created 3, attached_to_curated 1, matched 4" in out
    assert graph.edges[("gen:1:0", "exo:1:0")] == {   # curated edge: TSK evidence attached
        **SUPP_EDGE, "tsk": True, "votes": 10, "verse_pairs": 2}
    assert graph.edges[("exo:1:0", "gen:1:0")] == curated("markdown")
    assert graph.edges[("mat:1:0", "gen:1:1")] == {
        "source": "tsk", "curated": False, "tsk": True, "votes": 5, "verse_pairs": 1}
    assert f"fingerprint: {edge_fingerprint(graph.fingerprint_rows())}" in out
    # Every read, before and after the write, is a READ session; only the MERGE writes.
    for mode, kind, cypher in graph.calls:
        assert (kind == "write") == (cypher == its._MERGE_CYPHER)
        assert kind == "write" or mode == READ_ACCESS


def test_second_run_creates_nothing_and_keeps_the_fingerprint(monkeypatch, tmp_path, capsys):
    graph = FakeGraph()
    assert _main(graph, monkeypatch, tmp_path) == 0
    first = capsys.readouterr().out.split("fingerprint: ")[1]

    assert _main(graph, monkeypatch, tmp_path) == 0

    out = capsys.readouterr().out
    assert "created 0, attached_to_curated 1, matched 4" in out
    assert out.split("fingerprint: ")[1] == first


@pytest.mark.parametrize("pericopes, extra, failed", [
    # a TSK pericope is not a node: its rows match nothing
    (("gen:1:0", "gen:1:1", "exo:1:0"), (), ["matched rows: 2, expected 4",
                                              "edges with tsk = true: 2, expected 4"]),
    # an older TSK edge the current rows do not contain
    (PERICOPES, (("gen:1:1", "exo:1:0", {"source": "tsk", "curated": False, "tsk": True}),),
     ["edges with tsk = true: 5, expected 4"]),
    # a curated edge already marked tsk that TSK no longer supports
    (PERICOPES, (("gen:1:1", "mat:1:0", {**curated("markdown"), "tsk": True}),),
     ["edges with tsk = true: 5, expected 4", "edges with tsk and curated: 2, expected 1"]),
])
def test_count_gate_mismatch_exits_1(pericopes, extra, failed, monkeypatch, tmp_path, capsys):
    graph = FakeGraph(pericopes, STEP5_EDGES + extra)

    assert _main(graph, monkeypatch, tmp_path) == 1

    captured = capsys.readouterr()
    assert [line.strip() for line in captured.err.splitlines()[1:]] == failed
    assert "fingerprint" not in captured.out


class _MissedOnCreateGraph(FakeGraph):
    """A MERGE whose ON CREATE did not run: the edges it creates have no curated flag."""

    def _merge(self, rows: list[dict]) -> _Result:
        before = set(self.edges)
        result = super()._merge(rows)
        for pair in set(self.edges) - before:
            del self.edges[pair]["curated"]
        return result


def test_post_write_gate_fails_on_an_edge_left_unflagged(monkeypatch, tmp_path, capsys):
    # every other count holds (matched 4, tsk 4, tsk and curated 1): only this gate sees it
    graph = _MissedOnCreateGraph()

    assert _main(graph, monkeypatch, tmp_path) == 1

    captured = capsys.readouterr()
    assert [line.strip() for line in captured.err.splitlines()[1:]] == [
        "edges with curated or tsk unset: 3, expected 0"]
    assert "fingerprint" not in captured.out


def test_dry_run_writes_nothing_and_uses_read_sessions(monkeypatch, tmp_path, capsys):
    graph = FakeGraph()
    before = {pair: dict(p) for pair, p in graph.edges.items()}

    assert _main(graph, monkeypatch, tmp_path, "--dry-run") == 0

    assert graph.merges() == 0 and graph.edges == before
    assert graph.sessions and all(s.get("default_access_mode") == READ_ACCESS
                                  for s in graph.sessions)
    assert {kind for _, kind, _ in graph.calls} == {"read"}
    out = capsys.readouterr().out
    assert "attached_to_curated 1" in out and "[dry-run] nothing written" in out
    assert "supplementary anchors: 1 on 1 edges, tsk_exempt 0" in out


# ---------------------------------------------------------------- support gate (XREF-1/2)

INDEX_LINES = [
    "Gen.1.1\tExod.1.1\t3",
    "Gen.1.1\tExod.1.1\t9",              # the same verse pair again: max votes
    "Gen.1.1\tExod.1.2\t-1",             # negative votes
    "Gen.1.1\tExod.1.3\t0",
    "Gen.1.1\tGen.1.2\t7",               # one pericope: still a verse pair
    "Rev.1.1\tPs.1.1-Ps.1.200\t2",       # same chapter: 1-61 (MAX_RANGE_VERSES past 1)
    "Rev.1.1\tExod.2.5-Exod.3.4\t4",     # cross chapter: the two endpoints only
    "Foo.1.1\tGen.1.1\t5",               # unknown book
]


def test_verse_pair_index_semantics(tmp_path):
    index = its.build_verse_pair_index(_write_tsk(tmp_path / "tsk.txt", INDEX_LINES))

    gen1_1, rev1_1 = ("gen", 1, 1), ("rev", 1, 1)
    assert index == {(gen1_1, ("exo", 1, 1)): 9, (gen1_1, ("exo", 1, 3)): 0,
                     (gen1_1, ("gen", 1, 2)): 7,
                     **{(rev1_1, ("psa", 1, n)): 2 for n in range(1, 62)},
                     (rev1_1, ("exo", 2, 5)): 4, (rev1_1, ("exo", 3, 4)): 4}


# heb 1:5 → psa 2:7 both ways; psa 118:22 → mat 21:42 only, i.e. reverse of 'mat>psa'.
INDEX = {(("heb", 1, 5), ("psa", 2, 7)): 12, (("psa", 2, 7), ("heb", 1, 5)): 4,
         (("psa", 118, 22), ("mat", 21, 42)): 6}
REVERSE_ONLY = "mat 21:42>psa 118:22"
UNSUPPORTED = "rev 20:4>isa 65:17"


def supp_row(anchors: list[str], exempt: list[str] = ()) -> dict:
    """A row of the support query: one edge's anchors and its exempt anchors."""
    return {"a": "x:1:0", "b": "y:1:0", "anchors": anchors, "exempt": list(exempt)}


def test_supported_forward():
    # one of the source verses has the pair: enough
    assert its.anchor_votes("heb 1:3-5>psa 2:7", INDEX) == (12, 4)
    assert its.unsupported_anchors([supp_row(["heb 1:3-5>psa 2:7"])], INDEX) == []


def test_reverse_only_fails_without_exemption():
    rows = [supp_row(["heb 1:5>psa 2:7", REVERSE_ONLY])]

    assert its.anchor_votes(REVERSE_ONLY, INDEX) == (None, 6)
    assert its.unsupported_anchors(rows, INDEX) == [
        f"x:1:0→y:1:0 {REVERSE_ONLY!r}: forward votes none, reverse votes 6 (reverse only)"]


def test_reverse_only_passes_with_exemption():
    rows = [supp_row(["heb 1:5>psa 2:7", REVERSE_ONLY], exempt=[REVERSE_ONLY])]

    assert its.unsupported_anchors(rows, INDEX) == []


def test_unsupported_but_exempt_passes():
    assert its.unsupported_anchors([supp_row([UNSUPPORTED], exempt=[UNSUPPORTED])], INDEX) == []
    # the exemption names one anchor, not the edge
    assert its.unsupported_anchors([supp_row([UNSUPPORTED, REVERSE_ONLY], exempt=[REVERSE_ONLY])],
                                   INDEX) == [
        f"x:1:0→y:1:0 {UNSUPPORTED!r}: forward votes none, reverse votes none"]


def test_unparsable_anchor_fails_instead_of_crashing():
    # Step 5 only writes anchors it parsed; a hand-edited graph need not hold them
    rows = [supp_row(["heb 1:5", "heb 1:5>psa 2:7"])]

    assert its.unsupported_anchors(rows, INDEX) == [
        "x:1:0→y:1:0 'heb 1:5': expected 'source>target'"]


def test_support_query_reads_the_lists_step5_writes():
    anchor = Anchor("gen:1:0", "exo:1:0", SUPP_ANCHOR, "quote", "d", tsk_exempt="a reason")
    props = aggregate_curated([], [anchor])[0]["properties"]

    for key in ("supp_anchors", "supp_tsk_exempt_anchors"):
        assert key in props and f"r.{key}" in its._SUPP_ANCHORS_CYPHER


def _unsupported_graph() -> FakeGraph:
    """STEP5_EDGES plus a supplementary anchor TSK has only in reverse
    (Matt.1.1→Gen.1.1-Gen.1.3) and one it has in neither direction."""
    return FakeGraph(edges=STEP5_EDGES + (
        ("gen:1:1", "mat:1:0", curated("supplementary", supp_anchors=["gen 1:3>mat 1:1"])),
        ("exo:1:0", "gen:1:1", curated("supplementary", supp_anchors=["exo 1:1>gen 1:3"])),
    ))


UNSUPPORTED_LINES = [
    "exo:1:0→gen:1:1 'exo 1:1>gen 1:3': forward votes none, reverse votes none",
    "gen:1:1→mat:1:0 'gen 1:3>mat 1:1': forward votes none, reverse votes 5 (reverse only)",
]


def test_unsupported_exits_1_with_no_write(monkeypatch, tmp_path, capsys):
    graph = _unsupported_graph()
    before = {pair: dict(p) for pair, p in graph.edges.items()}

    assert _main(graph, monkeypatch, tmp_path) == 1

    assert graph.merges() == 0 and graph.edges == before
    err = capsys.readouterr().err.splitlines()
    assert "same-direction TSK support" in err[0] and "nothing written" in err[0]
    assert [line.strip() for line in err[1:]] == UNSUPPORTED_LINES
    assert graph.closed


def test_dry_run_still_runs_the_gate(monkeypatch, tmp_path, capsys):
    graph = _unsupported_graph()

    assert _main(graph, monkeypatch, tmp_path, "--dry-run") == 1

    assert graph.merges() == 0
    assert all(s.get("default_access_mode") == READ_ACCESS for s in graph.sessions)
    assert its._SUPP_ANCHORS_CYPHER in [cypher for *_, cypher in graph.calls]
    captured = capsys.readouterr()
    assert [line.strip() for line in captured.err.splitlines()[1:]] == UNSUPPORTED_LINES
    assert "[dry-run] nothing written" not in captured.out


@needs_tsk
def test_real_supplementary_anchors_are_forward_supported():
    index = its.build_verse_pair_index(TSK)
    fixture = json.loads(SUPP_FIXTURE.read_text(encoding="utf-8"))

    assert len(fixture) == 162
    rows = [{"a": a, "b": b, "anchors": [text], "exempt": []} for text, a, b in fixture]
    assert its.unsupported_anchors(rows, index) == []
    assert its.anchor_votes("rev 19:16>dan 2:47", index) == (8, 3)
    # the gate catches the 3 XREF-2 anchors that 1B-C5a/C5b removed or re-anchored
    removed = (("rev 19:1>psa 118:1", "rev:19:0", "psa:118:0"),
               ("rev 19:11-16>dan 7:13-14", "rev:19:2", "dan:7:1"),
               ("rev 20:4>isa 65:17", "rev:20:0", "isa:65:1"))   # in pair order
    rows = [{"a": a, "b": b, "anchors": [text], "exempt": []} for text, a, b in removed]
    assert its.unsupported_anchors(rows, index) == [
        f"{a}→{b} {text!r}: forward votes none, reverse votes none" for text, a, b in removed]


# ---------------------------------------------------------------- edge_fingerprint

FP_ROWS = [
    {"a": "rom:8:1", "b": "jer:1:1", "votes": 1143, "verse_pairs": 2, "curated": False, "tsk": True},
    {"a": "mat:4:0", "b": "deu:6:1", "votes": None, "verse_pairs": None, "curated": True,
     "tsk": False},
]


def test_edge_fingerprint_order_independent_and_sensitive_to_flags():
    # sim_w1_1b.py:171 over these two edges
    known = "67089fb4673348aa5b8226ee0e214f6f2f19f601b823ff2db78db77f2159da6c"
    assert edge_fingerprint(FP_ROWS) == known
    assert edge_fingerprint(reversed(FP_ROWS)) == known
    for key, value in (("tsk", True), ("curated", False), ("votes", 0), ("verse_pairs", 1)):
        assert edge_fingerprint([FP_ROWS[0], {**FP_ROWS[1], key: value}]) != known
