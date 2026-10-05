"""xref_rank / xref_probe: the offline replica of the backend's cross-reference
ranking and the 模擬等於實測 tool built on it (W1 1B-T1).

The replica must order exactly like backend/database/neo4j_db.py (C1 Cypher:
seed_support, curated, votes, then apoc.util.md5([id])) and weigh exactly like
cross_ref_retriever._edge_weight; compare must refuse any drift and the
sentinel rows the plan names. The graph reads go through a fake driver that
records the access mode: predict --target and fingerprint must never open a
write session.
deploy-guard (1B-T4) reads the container through a fake runner: no docker call.
expect (1B-T3) replays Steps 5 and 9 on a tiny Step 0 output and TSK file;
fingerprint reads the same table back through the fake driver. allow turns
that expect file and a fake prod profile into 1B's allowlist fragment: exact
YAML that diff_kg loads, covering 1B's sections and never mention_count.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j import READ_ACCESS

from bible_chunking.curated_xrefs import EDGE_FINGERPRINT_CYPHER, edge_fingerprint
from scripts.tools import diff_kg as dk
from scripts.tools import xref_probe as xp
from scripts.tools import xref_projection as xproj
from scripts.tools import xref_rank as xr

ROOT = Path(__file__).resolve().parents[2]


def edge(a, b, source="tsk", curated=None, votes=None) -> dict:
    return {"a": a, "b": b, "source": source, "curated": curated, "votes": votes}


# ---------------------------------------------------------------- xref_rank

def test_md5_key_matches_apoc():
    # RETURN apoc.util.md5(['heb:1:0']) on prod
    assert xr.md5_key("heb:1:0") == "184ea6ea28b8bb542975b89fb9131104"


def test_one_hop_orders_seed_support_curated_votes_md5():
    index = xr.XrefIndex.from_edges([
        edge("s1", "t:1:0", votes=1), edge("s2", "t:1:0", votes=2),       # two seeds cite it
        edge("s1", "c:1:0", source="markdown"),                           # curated, votes 0
        edge("e:1:0", "s1", source="supplementary", votes=4),            # curated, reverse direction
        edge("s1", "x:1:0", votes=9), edge("x:1:0", "s1", votes=3),       # votes = max over edges
        edge("s1", "y:1:0", votes=5), edge("s1", "z:1:0", votes=5),       # tie on votes 5:
        edge("s2", "w:1:0", votes=5),                                     # md5 z 6c40 < y 6d65 < w 74ed
        edge("s1", "s2", votes=100),                                      # the target is a seed
        edge("s1", "s1", source="markdown"),                              # self loop
    ])
    rows = xr.one_hop(index, ["s1", "s2"], limit=10)
    assert rows == [
        ("t:1:0", 1, False, 0.60), ("e:1:0", 1, True, 0.75), ("c:1:0", 1, True, 0.75),
        ("x:1:0", 1, False, 0.60), ("z:1:0", 1, False, 0.60), ("y:1:0", 1, False, 0.60),
        ("w:1:0", 1, False, 0.60),
    ]
    assert xr.one_hop(index, ["s1", "s2"], limit=3) == rows[:3]
    assert xr.legacy(index, "s2", limit=10) == [               # one seed: votes, then md5
        ("s1", 1, False, 0.60), ("w:1:0", 1, False, 0.60), ("t:1:0", 1, False, 0.60)]


def test_transitional_coalesce_uses_source_when_flag_missing():
    assert xr.is_curated(None, "supplementary") and xr.is_curated(None, "markdown")
    assert not xr.is_curated(None, "tsk") and not xr.is_curated(None, None)
    assert not xr.is_curated(False, "markdown")        # the flag overrides the source
    assert xr.is_curated(True, "tsk")
    index = xr.XrefIndex.from_edges([
        edge("s", "a:1:0", source="supplementary"),
        edge("s", "b:1:0", source="markdown", curated=False, votes=50),
        edge("s", "c:1:0", source="tsk", curated=True, votes=7),
    ])
    assert xr.one_hop(index, ["s"], 10) == [
        ("c:1:0", 1, True, 0.75), ("a:1:0", 1, True, 0.75), ("b:1:0", 1, False, 0.60)]


def test_tsk_votes_1268_is_not_curated():
    index = xr.XrefIndex.from_edges([
        edge("s", "a:1:0", votes=1268),                 # pre-C1 code read votes >= 999 as curated
        edge("s", "b:1:0", source="markdown"),
        edge("s", "c:1:0", votes=12),
    ])
    assert xr.one_hop(index, ["s"], 10) == [
        ("b:1:0", 1, True, 0.75), ("a:1:0", 1, False, 0.60), ("c:1:0", 1, False, 0.60)]
    assert xr.edge_weight(1, False) == 0.60 and xr.edge_weight(7, True) == 0.30


FALLBACK_EDGES = [
    edge("s:1:0", "a:1:0", source="markdown"),
    edge("s:1:0", "c:1:0", votes=5),
    edge("a:1:0", "c:1:0", votes=1),                    # c is one-hop: never a fallback row
    edge("a:1:0", "b:1:0", curated=True, votes=7),
    edge("a:1:0", "e:1:0", votes=3),
    edge("c:1:0", "d:1:0", source="supplementary"),     # s-c is TSK, so d is not all-curated
    edge("a:1:0", "f:1:0", source="markdown"), edge("c:1:0", "f:1:0", votes=2),
    edge("c:1:0", "g:1:0", source="markdown"), edge("a:1:0", "g:1:0", votes=1),
    edge("b:1:0", "h:1:0", source="markdown"),          # distance 3, all curated
    edge("h:1:0", "i:1:0", votes=1),                    # distance 4
    edge("i:1:0", "j:1:0", votes=1),                    # distance 5: beyond the 4-hop cap
]


def test_fallback_runs_only_below_limit_and_marks_all_curated_shortest_path():
    index = xr.XrefIndex.from_edges(FALLBACK_EDGES)
    one = [("a:1:0", 1, True, 0.75), ("c:1:0", 1, False, 0.60)]
    two = [("b:1:0", 2, True, 0.55), ("f:1:0", 2, True, 0.55),             # md5 3e99 < 6b52
           ("d:1:0", 2, False, 0.50), ("e:1:0", 2, False, 0.50), ("g:1:0", 2, False, 0.50)]
    assert xr.multi_hop(index, ["s:1:0"], max_hops=2, limit=10) == one + two
    assert xr.multi_hop(index, ["s:1:0"], max_hops=2, limit=2) == one       # one-hop filled limit
    assert xr.multi_hop(index, ["s:1:0"], max_hops=2, limit=4) == one + two[:2]
    assert xr.multi_hop(index, ["s:1:0"], max_hops=1, limit=10) == one
    assert xr.multi_hop(index, ["s:1:0"], max_hops=9, limit=10) == one + two + [
        ("h:1:0", 3, True, 0.40), ("i:1:0", 4, False, 0.30)]
    assert xr.multi_hop(index, [], max_hops=2, limit=10) == []


# ---------------------------------------------------------------- seeds

def write_jsonl(path, rows) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def question(qid, route, top5) -> dict:
    return {"qid": qid, "route_nograph": route, "nograph_top5": [f"{pid}|標題|semantic" for pid in top5]}


def test_seeds_from_questions_table(tmp_path):
    pids = ["gen:1:0", "gen:1:1", "exo:1:0", "exo:2:0", "exo:3:0", "lev:1:0"]
    write_jsonl(tmp_path / "pericopes.jsonl", [{"id": pid} for pid in reversed(pids)])
    table = [question("Q_R1", "R1", ["gen:1:0"]),
             question("Q_R3", "R3", ["jhn:3:16"] + pids),          # chunk id dropped, 6 pericopes -> 5
             question("Q_R6", "R6", ["jhn:3:16", "jhn:3:17"]),     # nothing left: dropped
             question("Q_FB", "fallback", ["gen:1:0"]),
             question("Q_R5", "R5", ["lev:1:0", "gen:1:0"])]
    (tmp_path / "q.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "seeds.json"
    assert xp.main(["seeds", "--pericopes", str(tmp_path / "pericopes.jsonl"),
                    "--questions", str(tmp_path / "q.json"), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc == {
        "version": 1,
        "questions_sha256": hashlib.sha256((tmp_path / "q.json").read_bytes()).hexdigest(),
        "singles": sorted(pids),
        "sets": {"Q_R3": pids[:5], "Q_R5": ["lev:1:0", "gen:1:0"]},
    }


# ---------------------------------------------------------------- predict

SENTINEL_EDGES = [edge("jer:29:0", "isa:55:0", source="supplementary", curated=False, votes=40),
                  edge("rom:8:1", "eph:1:1", votes=12), edge("jer:1:1", "rom:8:1", votes=3),
                  edge("isa:55:0", "psa:23:0", source="markdown")]


def write_seeds(path, singles, sets) -> None:
    path.write_text(json.dumps({"version": 1, "questions_sha256": "0" * 64,
                                "singles": singles, "sets": sets}), encoding="utf-8")


def test_predict_from_edges_file(tmp_path):
    write_jsonl(tmp_path / "edges.jsonl", SENTINEL_EDGES)
    write_seeds(tmp_path / "seeds.json", ["isa:55:0", "jer:29:0"], {"Q1": ["jer:29:0", "rom:8:1"]})
    out = tmp_path / "pred.json"
    assert xp.main(["predict", "--seeds", str(tmp_path / "seeds.json"),
                    "--edges", str(tmp_path / "edges.jsonl"), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["version"] == 1 and doc["params"] == {"max_hops": 2, "limit": 10}
    assert doc["edges_from"]["edges"] == 4
    rows = doc["rows"]
    assert sorted(rows) == ["legacy:isa:55:0", "legacy:jer:29:0", "q:Q1", "single:isa:55:0", "single:jer:29:0"]
    assert rows["legacy:isa:55:0"] == [["psa:23:0", 1, True, 0.75], ["jer:29:0", 1, False, 0.6]]
    # the curated=False flag beats source=supplementary, so the 2-hop path is not all curated
    assert rows["single:jer:29:0"] == [["isa:55:0", 1, False, 0.6], ["psa:23:0", 2, False, 0.5]]
    assert rows["q:Q1"] == [["isa:55:0", 1, False, 0.6], ["eph:1:1", 1, False, 0.6],
                            ["jer:1:1", 1, False, 0.6], ["psa:23:0", 2, False, 0.5]]


class FakeDriver:
    """Answers each known query (cypher -> rows); records every session's kwargs."""

    def __init__(self, answers: dict[str, list[dict]]):
        self.answers, self.sessions, self.closed = answers, [], False

    def session(self, **kwargs):
        self.sessions.append(kwargs)
        driver = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute_read(self, fn):
                def run(cypher, **params):
                    assert cypher in driver.answers, cypher
                    return [SimpleNamespace(data=lambda r=r: dict(r)) for r in driver.answers[cypher]]
                return fn(SimpleNamespace(run=run))

            def run(self, *a, **k):
                raise AssertionError("a READ action must read through execute_read")

            def execute_write(self, fn):
                raise AssertionError("a READ action must never write")
        return Session()

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def patch_target(monkeypatch, driver) -> list[str]:
    """resolve_target / open_neo4j answer with `driver`; returns the resolved names."""
    resolved = []
    monkeypatch.setattr(xp, "resolve_target", lambda name: resolved.append(name) or
                        SimpleNamespace(name=name, neo4j_uri="bolt://localhost:7688"))
    monkeypatch.setattr(xp, "open_neo4j", lambda target: driver)
    return resolved


def test_predict_target_reads_in_read_sessions(tmp_path, monkeypatch):
    driver = FakeDriver({xp.EDGES_CYPHER: SENTINEL_EDGES})
    resolved = patch_target(monkeypatch, driver)
    write_seeds(tmp_path / "seeds.json", ["jer:29:0"], {})
    out = tmp_path / "pred.json"
    assert xp.main(["predict", "--seeds", str(tmp_path / "seeds.json"),
                    "--target", "staging", "--out", str(out)]) == 0
    assert resolved == ["staging"] and driver.closed
    assert driver.sessions and all(s.get("default_access_mode") == READ_ACCESS for s in driver.sessions)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["edges_from"]["target"] == "staging"
    assert doc["rows"]["single:jer:29:0"][0] == ["isa:55:0", 1, False, 0.6]


def test_predict_target_refused_exits_1_without_output(tmp_path, monkeypatch):
    def refuse(name):
        raise ValueError("--target prod refused: shell NEO4J_URI differs")
    monkeypatch.setattr(xp, "resolve_target", refuse)
    write_seeds(tmp_path / "seeds.json", ["jer:29:0"], {})
    out = tmp_path / "pred.json"
    assert xp.main(["predict", "--seeds", str(tmp_path / "seeds.json"),
                    "--target", "prod", "--out", str(out)]) == 1
    assert not out.exists()


# ---------------------------------------------------------------- compare

def sentinel_rows() -> dict:
    rows: dict[str, list] = {"q:Q1": [["gen:1:0", 1, True, 0.75]]}
    for kind in ("single", "legacy"):
        for x, y in xp.SENTINEL_PAIRS:
            rows.setdefault(f"{kind}:{x}", []).append([y, 1, False, 0.6])
            rows.setdefault(f"{kind}:{y}", []).append([x, 1, False, 0.6])
    return rows


def full(rows, **over) -> dict:
    return {"version": 1, "params": {"max_hops": 2, "limit": 10}, "edges_from": {}, "rows": rows, **over}


def run_compare(tmp_path, pred, measured) -> int:
    (tmp_path / "p.json").write_text(json.dumps(pred), encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps(measured), encoding="utf-8")
    return xp.main(["compare", "--pred", str(tmp_path / "p.json"), "--measured", str(tmp_path / "m.json")])


def test_compare_exact_and_sentinels(tmp_path, capsys):
    rows = sentinel_rows()
    assert len(rows) == 1 + 2 * 5                       # the 5 seeds the plan names, single and legacy
    assert run_compare(tmp_path, full(rows), full(rows)) == 0
    assert run_compare(tmp_path, full(rows), rows) == 0                     # bare key -> rows map
    assert "sentinels 12/12" in capsys.readouterr().out

    changed = json.loads(json.dumps(rows))
    changed["q:Q1"][0][3] = 0.55
    assert run_compare(tmp_path, full(rows), changed) == 1
    assert "q:Q1" in capsys.readouterr().out

    typed = json.loads(json.dumps(rows))
    typed["q:Q1"][0][2] = 1                              # 1 == True in Python, not in JSON
    assert run_compare(tmp_path, full(rows), typed) == 1

    missing = json.loads(json.dumps(rows))
    missing["legacy:eph:1:1"] = [["gen:1:0", 1, False, 0.6]]
    assert run_compare(tmp_path, full(missing), missing) == 1
    assert "legacy:eph:1:1" in capsys.readouterr().out

    curated = json.loads(json.dumps(rows))
    curated["single:jer:29:0"] = [["isa:55:0", 1, True, 0.75]]   # the pre-C1 999-sentinel row
    assert run_compare(tmp_path, full(curated), curated) == 1
    curated["single:jer:29:0"] = [["isa:55:0", 1, True, 0.6]]    # right weight, wrong flag
    assert run_compare(tmp_path, full(curated), curated) == 1


def test_compare_params_and_key_sets(tmp_path):
    rows = sentinel_rows()
    assert run_compare(tmp_path, full(rows), full(rows, params={"max_hops": 2, "limit": 30})) == 1
    fewer = {k: v for k, v in rows.items() if k != "q:Q1"}
    assert run_compare(tmp_path, full(rows), fewer) == 1


# ---------------------------------------------------------------- deploy-guard

REPO_BACKEND = Path(xp.__file__).resolve().parents[2] / "backend"
NEO4J_DB, RETRIEVER, PROBE = "database/neo4j_db.py", "utils/retrieval/cross_ref_retriever.py", "probes/xref_measure.py"
PRE_1B = {  # the 087ab0d lines plan §2.2 says must be gone from the container before the data load
    NEO4J_DB: b'        "     max(coalesce(r.votes, 999)) AS votes "\n',
    RETRIEVER: b"_CURATED_VOTES = 999\n",
}


class FakeDocker:
    """subprocess.run stand-in for `docker exec <container> cat <path>`; records every command."""

    def __init__(self, files: dict[str, bytes], fail: bytes | None = None):
        self.files, self.fail, self.calls = files, fail, []

    def __call__(self, cmd, check, capture_output):
        self.calls.append(cmd)
        assert cmd[:2] == ["docker", "exec"] and cmd[3] == "cat" and check is False and capture_output
        if self.fail is not None:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=self.fail)
        rel = cmd[4].removeprefix("/app/backend/")
        if rel not in self.files:
            return SimpleNamespace(returncode=1, stdout=b"",
                                   stderr=f"cat: {cmd[4]}: No such file or directory\n".encode())
        return SimpleNamespace(returncode=0, stdout=self.files[rel], stderr=b"")


def checkout_files() -> dict[str, bytes]:
    return {rel: (REPO_BACKEND / rel).read_bytes() for rel in (NEO4J_DB, RETRIEVER, PROBE)}


def run_guard(monkeypatch, docker, *argv) -> int:
    monkeypatch.setattr(xp, "run_command", docker)
    return xp.main(["deploy-guard", *argv])


def test_deploy_guard_accepts_current_checkout(monkeypatch, capsys):
    files = checkout_files()
    docker = FakeDocker(files)
    assert run_guard(monkeypatch, docker) == 0
    assert docker.calls == [["docker", "exec", "bible_rag_backend", "cat", f"/app/backend/{rel}"]
                            for rel in (NEO4J_DB, RETRIEVER, PROBE)]
    out = capsys.readouterr().out
    assert "deployed backend reads r.curated" in out
    for data in files.values():
        assert hashlib.sha256(data).hexdigest() in out

    docker = FakeDocker(files)
    assert run_guard(monkeypatch, docker, "--container", "bible_rag_backend_staging") == 0
    assert {cmd[2] for cmd in docker.calls} == {"bible_rag_backend_staging"}


def test_deploy_guard_rejects_sentinel_code(monkeypatch, capsys, tmp_path):
    files = {**checkout_files(), NEO4J_DB: PRE_1B[NEO4J_DB]}
    assert run_guard(monkeypatch, FakeDocker(files)) == 1
    out = capsys.readouterr().out
    assert "coalesce(r.votes, 999) present" in out and "lacks r.curated" in out
    assert "deployed backend reads r.curated" not in out

    # the code checks stand on their own: a checkout holding the same pre-1B files still fails
    files = {**checkout_files(), **PRE_1B}
    for rel, data in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    shas, problems = xp.deploy_guard("bible_rag_backend", FakeDocker(files), backend=tmp_path)
    assert shas == {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}
    assert problems == [f"coalesce(r.votes, 999) present in {NEO4J_DB}",
                        f"_CURATED_VOTES present in {RETRIEVER}",
                        f"{NEO4J_DB} lacks r.curated"]


@pytest.mark.parametrize("rel", [NEO4J_DB, RETRIEVER, PROBE])
def test_deploy_guard_rejects_image_from_other_checkout(rel, monkeypatch, capsys):
    files = checkout_files()
    files[rel] += b"\n"                                  # the new text plus one byte
    assert run_guard(monkeypatch, FakeDocker(files)) == 1
    out = capsys.readouterr().out
    assert f"{rel}: sha256" in out and "image not built from this checkout" in out
    assert "exit 1: 1 problems" in out


def test_deploy_guard_rejects_missing_probe_module(monkeypatch, capsys):
    files = {rel: data for rel, data in checkout_files().items() if rel != PROBE}
    assert run_guard(monkeypatch, FakeDocker(files)) == 1
    out = capsys.readouterr().out
    assert "missing probes/xref_measure.py" in out and "exit 1: 1 problems" in out


def test_deploy_guard_docker_failure(monkeypatch, capsys):
    docker = FakeDocker({}, fail=b"Error response from daemon: No such container: nope\n")
    assert run_guard(monkeypatch, docker, "--container", "nope") == 1
    out = capsys.readouterr().out
    assert out.count("docker exec failed") == 3 and "No such container" in out
    assert "missing" not in out and "deployed backend reads r.curated" not in out

    def no_docker(cmd, check, capture_output):
        raise FileNotFoundError(2, "No such file or directory", "docker")
    assert run_guard(monkeypatch, no_docker) == 1        # docker itself absent: still never 0


# ---------------------------------------------------------------- expect / fingerprint

QUEUE_VERSES = ["gen:1:0:v:1-2", "gen:2:0:v:1", "gen:2:0:v:2", "gen:2:0:v:3", "exo:3:0:v:1",
                "exo:3:0:v:2", "isa:7:1:v:14", "mat:1:1:v:22", "mat:1:1:v:23", "mat:2:0:v:1"]


def curated_row(start, end, source) -> dict:
    props = {"source": source, "curated": True, "tsk": False, "curated_sources": [source]}
    return {"start": start, "end": end, "type": "CROSS_REFERENCES", "properties": props}


STEP5_ROWS = [{"start": "gen:1", "end": "gen:1:0", "type": "CONTAINS", "properties": {}},
              curated_row("mat:1:1", "isa:7:1", "markdown"),           # TSK attaches
              curated_row("gen:2:0", "gen:1:0", "supplementary"),      # TSK attaches
              curated_row("mat:2:0", "exo:3:0", "markdown")]           # TSK holds only the reverse pair
TSK_LINES = ["Matt.1.23\tIsa.7.14\t50", "Matt.1.22\tIsa.7.14\t10",   # one pair: max votes, 2 verse pairs
             "Gen.2.1\tGen.1.1-Gen.1.2\t5",                            # a range inside one pericope
             "Gen.1.1\tExod.3.1\t7",                                    # pure TSK
             "Exod.3.2\tMatt.2.1\t3",                                   # pure TSK, a curated edge reversed
             "Gen.1.1\tGen.1.2\t9", "Gen.1.2\tExod.3.1\t-2"]           # self loop, negative votes: dropped
PROJECTED = [  # (a, b, source, curated, tsk, votes, verse_pairs) after Step 5 and Step 9, by hand
    ("exo:3:0", "mat:2:0", "tsk", False, True, 3, 1),
    ("gen:1:0", "exo:3:0", "tsk", False, True, 7, 1),
    ("gen:2:0", "gen:1:0", "supplementary", True, True, 5, 1),
    ("mat:1:1", "isa:7:1", "markdown", True, True, 50, 2),
    ("mat:2:0", "exo:3:0", "markdown", True, False, None, None),
]
PROVENANCE_ROWS = [{"source": "markdown", "curated": True, "tsk": True, "n": 1},
                   {"source": "markdown", "curated": True, "tsk": False, "n": 1},
                   {"source": "supplementary", "curated": True, "tsk": True, "n": 1},
                   {"source": "tsk", "curated": False, "tsk": True, "n": 2}]


def live_rows(projected=PROJECTED) -> list[dict]:
    """The rows EDGE_FINGERPRINT_CYPHER returns for a graph holding `projected`."""
    return [{"a": a, "b": b, "votes": v, "verse_pairs": vp, "curated": c, "tsk": t}
            for a, b, _s, c, t, v, vp in projected]


def write_step0(tmp_path, rows=STEP5_ROWS) -> Path:
    out = tmp_path / "step0"
    out.mkdir(exist_ok=True)
    write_jsonl(out / "embedding_queue.jsonl", [{"id": "gen:1:0", "type": "pericope"}] +
                [{"id": vid, "type": "verse", "text": "經文"} for vid in QUEUE_VERSES])
    write_jsonl(out / "neo4j_relationships.jsonl", rows)
    (tmp_path / "tsk.txt").write_text("From Verse\tTo Verse\tVotes\t#\n" + "\n".join(TSK_LINES) + "\n",
                                      encoding="utf-8")
    return out


def run_expect(tmp_path, *extra, rows=STEP5_ROWS) -> int:
    out = write_step0(tmp_path, rows)
    return xp.main(["expect", "--output-dir", str(out), "--tsk", str(tmp_path / "tsk.txt"),
                    "--out", str(tmp_path / "xref.json"), *extra])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_expect_applies_set_semantics(tmp_path):
    edges = tmp_path / "edges.jsonl"
    assert run_expect(tmp_path, "--edges-out", str(edges)) == 0
    step0 = tmp_path / "step0"
    assert json.loads((tmp_path / "xref.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "inputs": {"relationships_sha256": sha256(step0 / "neo4j_relationships.jsonl"),
                   "embedding_queue_sha256": sha256(step0 / "embedding_queue.jsonl"),
                   "tsk_sha256": sha256(tmp_path / "tsk.txt")},
        "counts": {"curated_rows": 3, "attached": 2, "curated_without_tsk": 1, "pure_tsk": 2,
                   "total": 5, "votes_edges": 4},
        "xref_provenance": {"source=markdown curated=True tsk=False": 1,
                            "source=markdown curated=True tsk=True": 1,
                            "source=supplementary curated=True tsk=True": 1,
                            "source=tsk curated=False tsk=True": 2},
        "xrefs_by_source": {"markdown": 2, "supplementary": 1, "tsk": 2},
        "fingerprint": edge_fingerprint(live_rows()),
    }
    assert [json.loads(line) for line in edges.read_text(encoding="utf-8").splitlines()] == [
        {"a": a, "b": b, "source": s, "curated": c, "votes": v} for a, b, s, c, _t, v, _vp in PROJECTED]

    # the edge file is predict --edges input
    write_seeds(tmp_path / "seeds.json", ["mat:2:0"], {})
    assert xp.main(["predict", "--seeds", str(tmp_path / "seeds.json"), "--edges", str(edges),
                    "--out", str(tmp_path / "pred.json")]) == 0
    rows = json.loads((tmp_path / "pred.json").read_text(encoding="utf-8"))["rows"]
    assert rows["legacy:mat:2:0"] == [["exo:3:0", 1, True, 0.75]]      # curated wins over the TSK reverse


def test_expect_refuses_what_the_pipeline_refuses(tmp_path, capsys):
    duplicate = STEP5_ROWS + [curated_row("mat:1:1", "isa:7:1", "supplementary")] * 2   # 3 rows, 1 pair
    assert run_expect(tmp_path, rows=duplicate) == 1                    # import_neo4j refuses it
    err = capsys.readouterr().err
    assert "1 duplicate pairs (import_neo4j refuses them): mat:1:1→isa:7:1" in err and "unset" not in err
    pre_1b = STEP5_ROWS + [{"start": "isa:7:1", "end": "mat:1:1", "type": "CROSS_REFERENCES",
                            "properties": {"source": "markdown", "verse_start": 14}}]
    assert run_expect(tmp_path, rows=pre_1b) == 1                       # Step 9's precondition refuses it
    assert "1 rows with curated or tsk unset (Step 9's precondition refuses them): isa:7:1→mat:1:1" \
        in capsys.readouterr().err
    assert not (tmp_path / "xref.json").exists()


def live_driver(projected=PROJECTED, provenance=PROVENANCE_ROWS) -> FakeDriver:
    return FakeDriver({EDGE_FINGERPRINT_CYPHER: list(reversed(live_rows(projected))),
                       xproj.PROVENANCE_CYPHER: provenance})


def test_fingerprint_matches_expect_on_fake_driver(tmp_path, monkeypatch, capsys):
    assert run_expect(tmp_path) == 0
    capsys.readouterr()
    resolved = patch_target(monkeypatch, live_driver())
    assert xp.main(["fingerprint", "--target", "staging", "--expect", str(tmp_path / "xref.json")]) == 0
    out = capsys.readouterr().out
    assert resolved == ["staging"]
    assert f"fingerprint {edge_fingerprint(live_rows())} (staging" in out
    assert "  source=tsk curated=False tsk=True: 2" in out and "exit 0" in out
    assert xp.main(["fingerprint", "--target", "staging"]) == 0         # no --expect: report only


def test_fingerprint_expect_mismatch_exits_1(tmp_path, monkeypatch, capsys):
    assert run_expect(tmp_path) == 0
    expect = ["fingerprint", "--target", "staging", "--expect", str(tmp_path / "xref.json")]
    votes = [PROJECTED[0][:5] + (4, 1)] + PROJECTED[1:]                 # one TSK vote differs
    patch_target(monkeypatch, live_driver(projected=votes))
    assert xp.main(expect) == 1
    out = capsys.readouterr().out
    assert "fingerprint differs" in out and "exit 1: 1 problems" in out

    pre_1b = PROVENANCE_ROWS[1:] + [{"source": "markdown", "curated": None, "tsk": None, "n": 1}]
    patch_target(monkeypatch, live_driver(provenance=pre_1b))
    assert xp.main(expect) == 1
    out = capsys.readouterr().out
    assert "source=markdown curated=- tsk=-: 1, expected 0" in out
    assert "source=markdown curated=True tsk=True: 0, expected 1" in out
    assert "fingerprint differs" not in out and "exit 1: 2 problems" in out


# ---------------------------------------------------------------- allow

# a pre-1B prod for the fixture's expect file: no curated/tsk flags, no supplementary
# source, a TSK count past 1,000, other sections that 1B leaves alone, and a K10-like
# mention_count residual that is 1A's (residuals_allow.yaml), never 1B's
PROD_PROFILE = {
    "labels": [{"key": "Pericope", "n": 7}],
    "relationships": [{"key": "CONTAINS", "n": 3}, {"key": "CROSS_REFERENCES", "n": 249_506}],
    "ee_edges": [{"type": "SON_OF", "phase": 2, "source": None, "n": 1}],
    "mentions": [],
    "xrefs": [{"source": "markdown", "n": 2}, {"source": "tsk", "n": 249_504}],
    "xref_provenance": [{"source": "markdown", "curated": None, "tsk": None, "n": 2},
                        {"source": "tsk", "curated": None, "tsk": None, "n": 249_504}],
    "entities": [{"entity_id": "person:yeteluo", "description": "", "aliases": [], "mention_count": 3}],
}


def profile_answers() -> dict[str, list[dict]]:
    return {dk.PROFILE_QUERIES[section]: rows for section, rows in PROD_PROFILE.items()}


def run_allow(tmp_path, monkeypatch, *extra) -> tuple[int, list[str]]:
    assert run_expect(tmp_path) == 0
    resolved = patch_target(monkeypatch, FakeDriver(profile_answers()))
    argv = ["allow", "--expect", str(tmp_path / "xref.json"), "--out", str(tmp_path / "allow.yaml"), *extra]
    return xp.main(argv), resolved


def test_allow_writes_the_1b_fragment_as_exact_yaml(tmp_path, monkeypatch, capsys):
    code, resolved = run_allow(tmp_path, monkeypatch)
    assert code == 0 and resolved == ["prod"]
    expect, fp = tmp_path / "xref.json", edge_fingerprint(live_rows())

    def entry(section, key, delta, what):
        return (f'  - section: {section}\n    key: "{key}"\n    delta: {delta}\n'
                f'    reason: "1B {what}：期望檔（fingerprint {fp[:12]}）減 prod"\n')
    rel, src, prov = ("Step 5／9 重建的 CROSS_REFERENCES 總數", "各 source 的 CROSS_REFERENCES 數",
                      "Step 5／9 寫入的 source、curated、tsk 組合")
    assert (tmp_path / "allow.yaml").read_text(encoding="utf-8") == (
        "# 1B fragment of the merged W1 allowlist, written by xref_probe.py allow: regenerate it, never edit it.\n"
        "# delta = expect file - prod (diff_kg's b - a): one exact entry per differing key of\n"
        "# relationships CROSS_REFERENCES, xrefs and xref_provenance. No mention_count entries:\n"
        "# the merged allowlist takes those from 1A's residuals_allow.yaml only.\n"
        f"# expect file sha256 {sha256(expect)}, fingerprint {fp}\n"
        "# prod bolt://localhost:7688\n"
        "version: 1\n"
        "allow:\n"
        + entry("relationships", "CROSS_REFERENCES", -249501, rel)
        + entry("xrefs", "source=supplementary", 1, src)
        + entry("xrefs", "source=tsk", -249502, src)
        + entry("xref_provenance", "source=markdown curated=- tsk=-", -2, prov)
        + entry("xref_provenance", "source=markdown curated=True tsk=False", 1, prov)
        + entry("xref_provenance", "source=markdown curated=True tsk=True", 1, prov)
        + entry("xref_provenance", "source=supplementary curated=True tsk=True", 1, prov)
        + entry("xref_provenance", "source=tsk curated=- tsk=-", -249504, prov)
        + entry("xref_provenance", "source=tsk curated=False tsk=True", 2, prov))
    out = capsys.readouterr().out
    assert "  xrefs source=tsk: -249,502" in out and "allow: 9 entries" in out
    # the bytes depend on the expect file's content, not on how its path is spelt
    monkeypatch.chdir(tmp_path)
    assert xp.main(["allow", "--expect", "./xref.json", "--out", "again.yaml"]) == 0
    assert (tmp_path / "again.yaml").read_bytes() == (tmp_path / "allow.yaml").read_bytes()


def test_allow_fragment_loads_in_diff_kg_and_covers_exactly_the_1b_differences(tmp_path, monkeypatch):
    assert run_allow(tmp_path, monkeypatch)[0] == 0
    allow = dk.load_allowlist(tmp_path / "allow.yaml")
    assert {e["section"] for e in allow} == {"relationships", "xrefs", "xref_provenance"}
    # what R2's diff_kg sees: staging = prod with the xref layer the expect file predicts,
    # plus the mention_count residual
    prod = dk.read_profile(FakeDriver(profile_answers()))
    expect = json.loads((tmp_path / "xref.json").read_text(encoding="utf-8"))
    yeteluo = {**prod["entities"]["person:yeteluo"], "mention_count": 30}
    staging = {**prod, "relationships": {**prod["relationships"], "CROSS_REFERENCES": expect["counts"]["total"]},
               "xrefs": {f"source={s}": n for s, n in expect["xrefs_by_source"].items()},
               "xref_provenance": expect["xref_provenance"], "entities": {"person:yeteluo": yeteluo}}
    diffs = [d for section in dk.COUNT_SECTIONS for d in dk.diff_counts(section, prod[section], staging[section])]
    diffs += dk.diff_entities(prod["entities"], staging["entities"])
    classified, unused = dk.classify(diffs, allow)
    assert unused == []
    assert [(d["section"], d["key"]) for d in classified if d["allowed_by"] is None] == \
        [("mention_count", "person:yeteluo")]                           # 1A's residuals_allow.yaml


def test_allow_reads_prod_only_and_writes_nothing_when_it_cannot(tmp_path, monkeypatch):
    assert run_expect(tmp_path) == 0
    argv = ["allow", "--expect", str(tmp_path / "xref.json"), "--out", str(tmp_path / "allow.yaml")]
    resolved = patch_target(monkeypatch, FakeDriver(profile_answers()))  # a regression must not reach .env
    with pytest.raises(SystemExit) as exc:
        xp.main(argv + ["--target", "staging"])                         # the a side is diff_kg's --a prod
    assert exc.value.code == 2 and resolved == []                       # a usage error, before any target

    def refuse(name):
        raise ValueError("--target prod refused: shell NEO4J_URI differs")
    monkeypatch.setattr(xp, "resolve_target", refuse)
    assert xp.main(argv) == 1
    (tmp_path / "v2.json").write_text(json.dumps({"version": 2}), encoding="utf-8")
    patch_target(monkeypatch, FakeDriver(profile_answers()))
    assert xp.main(["allow", "--expect", str(tmp_path / "v2.json"), "--out", str(tmp_path / "allow.yaml")]) == 1
    assert not (tmp_path / "allow.yaml").exists()


@pytest.mark.parametrize("action", ["predict", "fingerprint", "allow"])
def test_read_actions_open_read_sessions_only(action, tmp_path, monkeypatch):
    assert run_expect(tmp_path) == 0                                    # allow's input (expect is offline)
    # import_tsk_crossrefs load_dotenv()s .env into os.environ on import: a READ
    # action must not import it, or the prod URI would look like a shell override
    monkeypatch.setitem(sys.modules, "import_tsk_crossrefs", None)
    driver = FakeDriver({xp.EDGES_CYPHER: SENTINEL_EDGES, EDGE_FINGERPRINT_CYPHER: live_rows(),
                         xproj.PROVENANCE_CYPHER: PROVENANCE_ROWS, **profile_answers()})
    patch_target(monkeypatch, driver)
    write_seeds(tmp_path / "seeds.json", ["jer:29:0"], {})
    argv = {"predict": ["predict", "--seeds", str(tmp_path / "seeds.json"), "--out", str(tmp_path / "p.json")],
            "fingerprint": ["fingerprint"],
            "allow": ["allow", "--expect", str(tmp_path / "xref.json"), "--out", str(tmp_path / "a.yaml")]}[action]
    assert xp.main(argv + ["--target", "prod"]) == 0
    assert driver.closed and driver.sessions
    assert all(s == {"default_access_mode": READ_ACCESS} for s in driver.sessions)


def test_importing_the_tool_does_not_import_step9():
    code = "import sys; from scripts.tools import xref_probe; assert 'import_tsk_crossrefs' not in sys.modules"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("action", ["seeds", "predict", "compare", "deploy-guard", "expect", "fingerprint",
                                    "allow"])
def test_top_level_help_lists_every_flag(action, capsys):
    with pytest.raises(SystemExit):
        xp.main(["--help"])
    text = capsys.readouterr().out
    assert action in text
    for flag in ("--pericopes", "--questions", "--out", "--seeds", "--target", "--edges",
                 "--pred", "--measured", "--container", "--output-dir", "--tsk", "--edges-out", "--expect"):
        assert flag in text
