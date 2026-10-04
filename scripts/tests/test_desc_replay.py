"""Step 7 description cache: append on generate, --replay, determinism.

Plan docs/records/2026-10-04_kg_data_layer_fix_plan.md §3.1 / §3.4 / §3.5.1 /
EV-08: descriptions only existed in live Neo4j, so a rebuild lost them. Every
generated description is now appended to a content-addressed cache
(entity_id + titles_sha, with model / temperature / prompt_version / commit)
and `--replay` restores them without the LLM, refusing (stale) when the
entity's input titles changed. In the rebuild chain replay is a gate: its
stale/missing lists go to a JSON report and `--fail-on-stale` exits 1.

A FakeGraph stands in for the Neo4j driver; it answers the module's own
Cypher constants so the tests exercise the real control flow.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

import pytest

from scripts.relation_extraction import desc_generator as dg


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeGraph:
    """In-memory driver: entity_id -> {type, canonical_name, titles, description}.

    `titles` are stored already in query order — the Cypher ordering itself is
    checked separately against the query text.
    """

    def __init__(self, entities: dict[str, dict]):
        self.entities = entities
        self.write_calls: list[list[dict]] = []
        self.uri = None

    def session(self):
        return FakeSession(self)

    def close(self):
        pass

    def descriptions(self) -> dict[str, str]:
        return {eid: e["description"] for eid, e in self.entities.items()}


class FakeSession:
    def __init__(self, graph: FakeGraph):
        self.graph = graph

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, eid: str) -> dict:
        e = self.graph.entities[eid]
        return {
            "entity_id": eid,
            "canonical_name": e["canonical_name"],
            "aliases": [],
            "type": e["type"],
            "labels": ["Entity", e["type"]],
            "description": e["description"],
            "titles": list(e["titles"]),
        }

    def run(self, query, **params):
        if query == dg._UPDATE_DESC_CYPHER:
            rows = [dict(r) for r in params["rows"]]
            self.graph.write_calls.append(rows)
            for r in rows:
                self.graph.entities[r["entity_id"]]["description"] = r["description"]
            return []
        if query == dg._FETCH_BY_IDS_CYPHER:
            ids = [i for i in params["entity_ids"] if i in self.graph.entities]
            return [self._row(i) for i in sorted(ids)]
        if query == dg._FETCH_NEED_DESC_CYPHER:
            types = set(params["target_types"])
            ids = [i for i, e in self.graph.entities.items()
                   if not e["description"] and e["type"] in types]
            return [self._row(i) for i in sorted(ids)]
        raise AssertionError(f"unexpected query: {query[:80]}")


def _entity(name, type_="Person", titles=("創造天地",), description=""):
    return {"canonical_name": name, "type": type_,
            "titles": list(titles), "description": description}


def _write_cache(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def _read_cache(path):
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _entry(eid, desc, titles, flag="ok", generated_at="2026-10-04T10:00:00+08:00"):
    return dg.make_cache_entry(
        entity_id=eid, description=desc, model="m", temperature=0.2,
        prompt_version="p", titles=titles, quality_flag=flag,
        git_commit="c0ffee", generated_at=generated_at,
    )


@pytest.fixture
def no_llm(monkeypatch):
    """Replay must never reach the LLM."""
    def boom(*a, **k):
        raise AssertionError("LLM called during replay")
    monkeypatch.setattr(dg, "_generate_description", boom)
    monkeypatch.setattr(dg.httpx, "Client", boom)


@pytest.fixture
def prod_target(monkeypatch):
    """KG_TARGET unset: the legacy behaviour, whatever the developer's shell has."""
    monkeypatch.delenv("KG_TARGET", raising=False)


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """Keep main()'s default replay report out of the real output/frozen/."""
    path = tmp_path / "reports"
    monkeypatch.setattr(dg, "DEFAULT_REPORT_DIR", path)
    return path


# ---------------------------------------------------------------------------
# Determinism and unchanged content
# ---------------------------------------------------------------------------

def test_titles_sha_is_sha256_of_ordered_title_list():
    a = dg.titles_sha(["創造天地", "伊甸園"])
    assert re.fullmatch(r"[0-9a-f]{64}", a)
    assert a == dg.titles_sha(["創造天地", "伊甸園"])
    assert a != dg.titles_sha(["伊甸園", "創造天地"])  # order is part of the prompt
    assert a != dg.titles_sha(["創造天地"])
    assert dg.titles_sha([]) == dg.titles_sha(None)


@pytest.mark.parametrize("query", ["_FETCH_NEED_DESC_CYPHER", "_FETCH_BY_IDS_CYPHER"])
def test_title_collection_is_ordered_before_collect(query):
    # Without ORDER BY, collect() follows store order, so which 6 titles reach
    # the prompt depended on import history (plan §3.4).
    cypher = getattr(dg, query)
    assert re.search(
        r"AS title\s+ORDER BY title\s+WITH e, \[t IN collect\(DISTINCT title\)",
        cypher,
    ), cypher
    assert "ORDER BY e.entity_id" in cypher


def test_generation_and_replay_share_one_title_computation():
    strip = lambda q: q.split("RETURN")[0].split("OPTIONAL MATCH", 1)[1]  # noqa: E731
    assert strip(dg._FETCH_NEED_DESC_CYPHER) == strip(dg._FETCH_BY_IDS_CYPHER)


def test_user_prompt_is_byte_identical_to_original():
    target = {"canonical_name": "亞伯拉罕", "type": "Person",
              "titles": ["神呼召亞伯蘭", "", "亞伯拉罕獻以撒"]}
    canonical, type_zh, titles = target["canonical_name"], target["type"], target["titles"]
    original = (
        f"實體名稱: {canonical}\n"
        f"類型: {type_zh}\n"
        f"出現於以下聖經段落:\n"
        + "\n".join(f"- {t}" for t in titles if t)
        + "\n\n請用 60 字以內、純客觀的描述總結這個實體在聖經中的角色或位置。"
    )
    assert dg._build_user_prompt(target) == original


@pytest.mark.parametrize("content, expected", [
    ('{"description": "以色列人的先祖"}', ("以色列人的先祖", "ok")),
    ('```json\n{"description": " 先知 "}\n```', ("先知", "ok")),
    ("先知,在\n撒瑪利亞說預言", ("先知,在 撒瑪利亞說預言", "raw_text")),
    ('{"description": ', ('{"description":', "raw_text")),
])
def test_parse_reply_keeps_content_and_flags_fallback(content, expected):
    assert dg._parse_reply(content) == expected


def test_prompt_version_tracks_prompt_text():
    assert re.fullmatch(r"desc-[0-9a-f]{12}", dg.PROMPT_VERSION)
    assert dg.PROMPT_VERSION == dg._prompt_version(dg.SYSTEM_PROMPT, dg._USER_PROMPT_TEMPLATE)
    assert dg.PROMPT_VERSION != dg._prompt_version(dg.SYSTEM_PROMPT + " ", dg._USER_PROMPT_TEMPLATE)


# ---------------------------------------------------------------------------
# Generate: append to cache
# ---------------------------------------------------------------------------

def _gen_args(tmp_path, *extra):
    return dg._build_parser().parse_args(
        ["--cache", str(tmp_path / "frozen" / "descriptions.jsonl"),
         "--model", "gemma-test", *extra])


def test_generate_appends_one_cache_entry_per_description(tmp_path, monkeypatch):
    graph = FakeGraph({
        "person:a": _entity("甲", titles=["甲的故事", "甲之死"]),
        "person:b": _entity("乙", titles=[]),             # no context -> skipped
        "person:c": _entity("丙", titles=["丙"]),          # refusal -> skipped
        "place:d": _entity("丁", "Place", titles=["丁城"]),
    })
    replies = {"甲": ("猶大王", "ok"), "丙": ("請提供更多資訊", "ok"),
               "丁": ("迦南的城", "raw_text")}
    monkeypatch.setattr(dg, "_generate_description",
                        lambda http, model, target, *a: replies[target["canonical_name"]])
    monkeypatch.setattr(dg, "git_commit", lambda: "abc123-dirty")
    args = _gen_args(tmp_path)

    dg.run_generate(graph, None, args)

    entries = _read_cache(args.cache)
    assert [e["entity_id"] for e in entries] == ["person:a", "place:d"]
    for e in entries:
        assert list(e) == list(dg.CACHE_FIELDS)
        assert e["model"] == "gemma-test"
        assert e["prompt_version"] == dg.PROMPT_VERSION
        # Plan §3.1: the cache records temperature and commit next to model
        # and prompt_version, so a hit says exactly what produced the text.
        assert e["temperature"] == dg.TEMPERATURE == 0.2
        assert e["git_commit"] == "abc123-dirty"
        datetime.fromisoformat(e["generated_at"])
    assert entries[0]["titles_sha"] == dg.titles_sha(["甲的故事", "甲之死"])
    assert entries[0]["description"] == "猶大王"
    assert entries[0]["quality_flag"] == "ok"
    assert entries[1]["quality_flag"] == "raw_text"
    assert graph.descriptions()["person:a"] == "猶大王"
    assert graph.descriptions()["person:c"] == ""


def test_generate_appends_to_existing_cache(tmp_path, monkeypatch):
    args = _gen_args(tmp_path)
    _write_cache(args.cache, [_entry("person:old", "舊", ["x"])])
    graph = FakeGraph({"person:a": _entity("甲")})
    monkeypatch.setattr(dg, "_generate_description", lambda *a: ("猶大王", "ok"))

    dg.run_generate(graph, None, args)

    assert [e["entity_id"] for e in _read_cache(args.cache)] == ["person:old", "person:a"]


def test_generate_dry_run_writes_neither_graph_nor_cache(tmp_path, monkeypatch):
    graph = FakeGraph({"person:a": _entity("甲")})
    monkeypatch.setattr(dg, "_generate_description", lambda *a: ("猶大王", "ok"))
    args = _gen_args(tmp_path, "--dry-run")

    dg.run_generate(graph, None, args)

    assert not args.cache.exists()
    assert graph.write_calls == []


class _FakeHttp:
    def __init__(self):
        self.sent = []

    def post(self, path, json):
        self.sent.append(json)
        reply = {"message": {"content": '{"description": "猶大王"}'}}
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: reply})()


def test_request_temperature_is_the_recorded_one():
    """The cache's temperature field must be the value actually sent."""
    http = _FakeHttp()

    dg._generate_description(http, "m", {"canonical_name": "甲", "type": "Person",
                                         "titles": ["甲的故事"]}, 8192, 2048)

    assert http.sent[0]["options"]["temperature"] == dg.TEMPERATURE


_HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize("head, diff_rc, expected", [
    ("ok", 1, _HEAD_SHA + "-dirty"),   # `git diff --quiet` exits 1: tracked files differ
    ("ok", 0, _HEAD_SHA),              # exits 0: the tree is HEAD
    ("fails", 0, None),                # rev-parse fails: not a git checkout
    ("no git", 0, None),               # git is not installed
])
def test_git_commit_names_head_and_marks_a_dirty_tree(monkeypatch, head, diff_rc, expected):
    """git's answers are faked, so both states are checked whatever the checkout is."""
    def fake_run(cmd, **kwargs):
        if head == "no git":
            raise FileNotFoundError("git")
        if cmd[1] == "rev-parse":
            rc, out = (0, _HEAD_SHA + "\n") if head == "ok" else (128, "")
        else:
            rc, out = diff_rc, ""
        return dg.subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

    monkeypatch.setattr(dg.subprocess, "run", fake_run)

    assert dg.git_commit() == expected


def test_load_cache_rejects_lines_without_provenance(tmp_path):
    cache = tmp_path / "descriptions.jsonl"
    entry = _entry("person:a", "猶大王", ["甲的故事"])
    del entry["temperature"]
    _write_cache(cache, [entry])

    with pytest.raises(SystemExit, match="temperature"):
        dg.load_cache(cache)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _replay_graph():
    return FakeGraph({
        "person:a": _entity("甲", titles=["甲的故事"]),
        "place:b": _entity("乙", "Place", titles=["乙城", "乙山"]),
        "event:c": _entity("丙", "Event", titles=["丙事"], description="抽取時的描述"),
    })


def _replay_cache(tmp_path):
    path = tmp_path / "descriptions.jsonl"
    _write_cache(path, [
        _entry("person:a", "猶大王", ["甲的故事"]),
        _entry("place:b", "迦南的城", ["乙城", "乙山"]),
        _entry("event:c", "live 上的描述", ["丙事"], flag="unreviewed"),
    ])
    return path


def test_replay_restores_descriptions_without_llm(tmp_path, no_llm):
    graph = _replay_graph()

    summary = dg.replay(graph, _replay_cache(tmp_path), dry_run=False, write_batch=2)

    assert graph.descriptions() == {
        "person:a": "猶大王", "place:b": "迦南的城", "event:c": "live 上的描述"}
    assert sorted(summary["written"]) == ["event:c", "person:a", "place:b"]
    assert summary["stale"] == [] and summary["missing"] == []
    assert summary["overwritten"] == ["event:c"]
    assert all(len(batch) <= 2 for batch in graph.write_calls)


def test_replay_is_idempotent(tmp_path, no_llm):
    graph = _replay_graph()
    cache = _replay_cache(tmp_path)

    dg.replay(graph, cache, dry_run=False, write_batch=50)
    after_first = graph.descriptions()
    calls_after_first = len(graph.write_calls)
    second = dg.replay(graph, cache, dry_run=False, write_batch=50)

    assert graph.descriptions() == after_first
    assert second["written"] == []
    assert sorted(second["unchanged"]) == ["event:c", "person:a", "place:b"]
    assert len(graph.write_calls) == calls_after_first


def test_replay_marks_stale_when_titles_changed(tmp_path, no_llm):
    graph = _replay_graph()
    graph.entities["place:b"]["titles"] = ["乙城"]   # MENTIONS changed upstream

    summary = dg.replay(graph, _replay_cache(tmp_path), dry_run=False, write_batch=50)

    assert summary["stale"] == ["place:b"]
    assert graph.descriptions()["place:b"] == ""
    assert sorted(summary["written"]) == ["event:c", "person:a"]


def test_replay_uses_entry_matching_current_titles(tmp_path, no_llm):
    graph = FakeGraph({"person:a": _entity("甲", titles=["甲的故事"])})
    cache = tmp_path / "descriptions.jsonl"
    _write_cache(cache, [
        _entry("person:a", "舊版", ["甲的故事"]),
        _entry("person:a", "新輸入的描述", ["甲的故事", "甲之死"]),
        _entry("person:a", "同輸入的較新描述", ["甲的故事"]),
    ])

    summary = dg.replay(graph, cache, dry_run=False, write_batch=50)

    assert summary["written"] == ["person:a"]
    assert graph.descriptions()["person:a"] == "同輸入的較新描述"


def test_replay_reports_entities_missing_from_graph(tmp_path, no_llm):
    graph = FakeGraph({"person:a": _entity("甲", titles=["甲的故事"])})
    cache = tmp_path / "descriptions.jsonl"
    _write_cache(cache, [_entry("person:a", "猶大王", ["甲的故事"]),
                         _entry("person:gone", "已刪除", ["x"])])

    summary = dg.replay(graph, cache, dry_run=False, write_batch=50)

    assert summary["missing"] == ["person:gone"]
    assert summary["written"] == ["person:a"]


def test_replay_dry_run_classifies_but_does_not_write(tmp_path, no_llm):
    graph = _replay_graph()

    summary = dg.replay(graph, _replay_cache(tmp_path), dry_run=True, write_batch=50)

    assert sorted(summary["written"]) == ["event:c", "person:a", "place:b"]
    assert graph.write_calls == []
    assert graph.descriptions()["person:a"] == ""


def test_replay_without_cache_file_fails(tmp_path, no_llm):
    with pytest.raises(SystemExit):
        dg.replay(_replay_graph(), tmp_path / "absent.jsonl", dry_run=True, write_batch=50)


# ---------------------------------------------------------------------------
# CLI: --replay end to end, staging via env
# ---------------------------------------------------------------------------

def test_main_replay_targets_neo4j_from_env(tmp_path, monkeypatch, no_llm, prod_target,
                                           report_dir):
    graph = _replay_graph()
    seen = {}

    def fake_driver(uri, auth):
        seen["uri"], seen["auth"] = uri, auth
        return graph

    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7688")
    monkeypatch.setenv("NEO4J_USER", "staging_user")
    monkeypatch.setenv("NEO4J_PASSWORD", "staging_pw")
    monkeypatch.setattr(dg.GraphDatabase, "driver", fake_driver)

    rc = dg.main(["--replay", "--cache", str(_replay_cache(tmp_path))])

    assert rc == 0
    assert seen == {"uri": "bolt://localhost:7688", "auth": ("staging_user", "staging_pw")}
    assert graph.descriptions()["person:a"] == "猶大王"


def test_main_cache_path_from_env(tmp_path, monkeypatch, no_llm):
    cache = _replay_cache(tmp_path)
    monkeypatch.setenv("DESC_CACHE_PATH", str(cache))
    args = dg._build_parser().parse_args(["--replay"])
    assert args.cache == cache


# ---------------------------------------------------------------------------
# Replay as a pipeline gate: JSON report, --fail-on-stale
# ---------------------------------------------------------------------------

def _stale_and_missing_cache(tmp_path):
    """place:b's titles changed (stale) and person:gone left the graph (missing)."""
    path = tmp_path / "descriptions.jsonl"
    _write_cache(path, [
        _entry("person:a", "猶大王", ["甲的故事"]),
        _entry("place:b", "迦南的城", ["乙城"]),
        _entry("person:gone", "已刪除", ["x"]),
    ])
    return path


def _main_on(graph, monkeypatch, *argv):
    monkeypatch.setattr(dg.GraphDatabase, "driver", lambda uri, auth: graph)
    return dg.main(["--replay", *argv])


def test_replay_writes_a_json_report_of_stale_and_missing(tmp_path, no_llm):
    graph = _replay_graph()
    cache = _stale_and_missing_cache(tmp_path)
    report = tmp_path / "out" / "report.json"

    dg.replay(graph, cache, dry_run=False, write_batch=50,
              report_path=report, neo4j_uri="bolt://localhost:7688")

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["neo4j_uri"] == "bolt://localhost:7688"
    assert data["cache"] == str(cache)
    assert data["cache_sha256"] == hashlib.sha256(cache.read_bytes()).hexdigest()
    assert data["dry_run"] is False
    assert data["counts"] == {"cached": 3, "written": 1, "overwritten": 0,
                              "unchanged": 0, "stale": 1, "missing": 1}
    assert data["missing"] == ["person:gone"]
    assert data["written"] == ["person:a"]
    # Enough to diagnose a stale entity without rerunning: what the graph has
    # now versus which inputs the cache knows.
    assert data["stale"] == [{
        "entity_id": "place:b", "canonical_name": "乙",
        "current_titles": ["乙城", "乙山"],
        "current_titles_sha": dg.titles_sha(["乙城", "乙山"]),
        "cached_titles_sha": [dg.titles_sha(["乙城"])],
    }]


def test_dry_run_replay_report_is_marked_dry_run(tmp_path, no_llm):
    report = tmp_path / "report.json"

    dg.replay(_replay_graph(), _replay_cache(tmp_path), dry_run=True, write_batch=50,
              report_path=report)

    assert json.loads(report.read_text(encoding="utf-8"))["dry_run"] is True


@pytest.mark.parametrize("flag, expected_rc", [([], 0), (["--fail-on-stale"], 1)])
def test_fail_on_stale_turns_stale_or_missing_into_exit_1(
        tmp_path, monkeypatch, no_llm, prod_target, flag, expected_rc):
    graph = _replay_graph()
    report = tmp_path / "report.json"

    rc = _main_on(graph, monkeypatch, "--cache", str(_stale_and_missing_cache(tmp_path)),
                  "--report", str(report), *flag)

    assert rc == expected_rc
    assert report.exists()
    # The rows that do match are still written: replay is idempotent, and the
    # report plus exit code are what stop the chain.
    assert graph.descriptions()["person:a"] == "猶大王"


@pytest.mark.parametrize("entries", [
    [("person:a", "猶大王", ["甲的故事"]), ("person:gone", "已刪除", ["x"])],   # missing only
    [("place:b", "迦南的城", ["乙城"])],                                       # stale only
])
def test_fail_on_stale_counts_missing_and_stale_alike(
        tmp_path, monkeypatch, no_llm, prod_target, report_dir, entries):
    cache = tmp_path / "descriptions.jsonl"
    _write_cache(cache, [_entry(*e) for e in entries])

    assert _main_on(_replay_graph(), monkeypatch, "--cache", str(cache), "--fail-on-stale") == 1


def test_fail_on_stale_passes_a_clean_replay(tmp_path, monkeypatch, no_llm, prod_target,
                                             report_dir):
    rc = _main_on(_replay_graph(), monkeypatch, "--cache", str(_replay_cache(tmp_path)),
                  "--fail-on-stale")
    assert rc == 0


def test_default_report_goes_under_output_frozen(tmp_path, monkeypatch, no_llm, prod_target,
                                                 report_dir):
    _main_on(_replay_graph(), monkeypatch, "--cache", str(_replay_cache(tmp_path)))

    reports = list(report_dir.glob("replay_*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["counts"]["written"] == 3


def test_default_report_dir_is_under_output_frozen():
    assert dg.DEFAULT_REPORT_DIR.parent == dg._REPO_ROOT / "output" / "frozen"


@pytest.mark.parametrize("argv", [["--fail-on-stale"], ["--report", "r.json"]])
def test_replay_only_flags_are_rejected_in_generate_mode(argv):
    with pytest.raises(SystemExit) as exc:
        dg.main(argv)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# kg_target: a staging run must never write the production graph
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [["--replay"], []])
@pytest.mark.parametrize("uri", [None, "bolt://localhost:7687", "bolt://localhost"])
def test_staging_target_refuses_production_neo4j_before_connecting(
        tmp_path, monkeypatch, no_llm, report_dir, mode, uri):
    monkeypatch.setenv("KG_TARGET", "staging")
    if uri is None:
        monkeypatch.delenv("NEO4J_URI", raising=False)
    else:
        monkeypatch.setenv("NEO4J_URI", uri)
    monkeypatch.setattr(dg.GraphDatabase, "driver",
                        lambda *a, **k: pytest.fail("connected despite KG_TARGET=staging"))

    with pytest.raises(SystemExit, match="NEO4J_URI"):
        dg.main([*mode, "--cache", str(_replay_cache(tmp_path))])


def test_staging_target_with_staging_neo4j_proceeds(tmp_path, monkeypatch, no_llm, report_dir):
    monkeypatch.setenv("KG_TARGET", "staging")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7688")
    graph = _replay_graph()

    rc = _main_on(graph, monkeypatch, "--cache", str(_replay_cache(tmp_path)))

    assert rc == 0
    assert graph.descriptions()["person:a"] == "猶大王"
