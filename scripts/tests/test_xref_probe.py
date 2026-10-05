"""xref_rank / xref_probe: the offline replica of the backend's cross-reference
ranking and the 模擬等於實測 tool built on it (W1 1B-T1).

The replica must order exactly like backend/database/neo4j_db.py (C1 Cypher:
seed_support, curated, votes, then apoc.util.md5([id])) and weigh exactly like
cross_ref_retriever._edge_weight; compare must refuse any drift and the
sentinel rows the plan names. The graph reads go through a fake driver that
records the access mode: predict --target must never open a write session.
deploy-guard (1B-T4) reads the container through a fake runner: no docker call.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j import READ_ACCESS

from scripts.tools import xref_probe as xp
from scripts.tools import xref_rank as xr


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
    """Answers the edge query; records every session's kwargs."""

    def __init__(self, rows):
        self.rows, self.sessions, self.closed = rows, [], False

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
                    assert cypher == xp.EDGES_CYPHER
                    return [SimpleNamespace(data=lambda r=r: dict(r)) for r in driver.rows]
                return fn(SimpleNamespace(run=run))

            def run(self, *a, **k):
                raise AssertionError("predict must read through execute_read")

            def execute_write(self, fn):
                raise AssertionError("predict must never write")
        return Session()

    def verify_connectivity(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_predict_target_reads_in_read_sessions(tmp_path, monkeypatch):
    driver = FakeDriver(SENTINEL_EDGES)
    resolved = []
    monkeypatch.setattr(xp, "resolve_target", lambda name: resolved.append(name) or
                        SimpleNamespace(name=name, neo4j_uri="bolt://localhost:7688"))
    monkeypatch.setattr(xp, "open_neo4j", lambda target: driver)
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


@pytest.mark.parametrize("action", ["seeds", "predict", "compare", "deploy-guard"])
def test_top_level_help_lists_every_flag(action, capsys):
    with pytest.raises(SystemExit):
        xp.main(["--help"])
    text = capsys.readouterr().out
    assert action in text
    for flag in ("--pericopes", "--questions", "--out", "--seeds", "--target", "--edges",
                 "--pred", "--measured", "--container"):
        assert flag in text
