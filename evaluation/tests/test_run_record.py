"""run_meta.json v2 (2026-10-28 P0): what a collection was, recorded beside its checkpoint.

git, docker and Ollama are faked through src.run_record._run (subprocess) and
_get_json (HTTP); no test reaches them (conftest refuses both by default).
"""

import hashlib
import json
import subprocess
from datetime import datetime

import pytest

from src import provenance as pv
from src import run_record as rr

BUILD = "b20261008_0000abcd"
FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}}
SECRET_VALUES = ("sk-ant-secret", "hunter2", "neo-pw", "gpg-key-value", "sk-openai",
                 "t0k3n", "rag-pass", "rag-key", "rag-salt", "db-url-pw")
ENV = [
    "ANTHROPIC_API_KEY=sk-ant-secret", "POSTGRES_PASSWORD=hunter2", "NEO4J_PASSWORD=neo-pw",
    "GPG_KEY=gpg-key-value", "OPENAI_API_KEY=sk-openai", "PATH=/usr/bin",
    "LLM_PROVIDER=ollama", "OLLAMA_MODEL=gemma4:26b", "CLAUDE_MODEL=claude-x",
    "LLM_TEMPERATURE=0.1", "LLM_MAX_TOKENS=4096", "STRICT_BUILD_CHECK=true",
    "RAG_RANK_FUSION_ALPHA=0.3", "RAG_USE_GRAPH=true", "RAG_ENTITY_QUERY_TOP_K=8",
    "RAG_ENV=prod", "RAG_SERVICE_TOKEN=t0k3n", "RAG_DB_PASS=rag-pass", "RAG_API_KEY=rag-key",
    "RAG_SECRET_SALT=rag-salt", "RAG_DATABASE_URL=postgresql://bible:db-url-pw@db:5432/x",
]
INSPECT = [{"Config": {"Image": "bible_rag-backend:r5", "Env": ENV},
            "Image": "sha256:img", "State": {"StartedAt": "2026-10-21T08:00:00Z"}}]
TAGS = {"models": [{"name": "gemma3:latest", "model": "gemma3:latest", "digest": "d0", "size": 1},
                   {"name": "gemma4:26b", "model": "gemma4:26b", "digest": "d1", "size": 2}]}


PS_PROD = ["docker", "ps", "--filter", "publish=8000", "--format", "{{.Names}}"]


@pytest.fixture(autouse=True)
def _prod_url(monkeypatch):
    """BACKEND_URL is prod's and EVAL_BACKEND_CONTAINER unset, whatever the local .env says."""
    monkeypatch.setattr(rr.settings, "backend_url", "http://localhost:8000")
    monkeypatch.setattr(rr.settings, "eval_backend_container", "")


def _fake_run(monkeypatch, outputs: dict, calls: list | None = None):
    """_run answering by command head ("docker ps", "docker" for inspect, "git rev-parse",
    "git status"); docker ps names prod's container unless told otherwise."""
    outputs = {"docker ps": "bible_rag_backend\n", **outputs}

    def run(cmd, timeout):
        if calls is not None:
            calls.append((cmd, timeout))
        if cmd[0] == "docker":
            head = "docker ps" if cmd[1] == "ps" else "docker"
        else:
            head = f"git {next(a for a in cmd if a in ('rev-parse', 'status'))}"
        out = outputs[head]
        if isinstance(out, BaseException):
            raise out
        return out
    monkeypatch.setattr(rr, "_run", run)


def _fake_tags(monkeypatch, tags=TAGS, seen: list | None = None):
    def get(url, timeout):
        if seen is not None:
            seen.append(url)
        if isinstance(tags, BaseException):
            raise tags
        return tags
    monkeypatch.setattr(rr, "_get_json", get)


# --- backend_runtime: allowlisted env, never a secret ------------------------------------

def test_backend_runtime_records_image_start_and_the_allowlisted_env(monkeypatch):
    calls = []
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT)}, calls)

    runtime = rr.backend_runtime()

    assert (runtime["container"], runtime["container_from"]) == ("bible_rag_backend", "BACKEND_URL")
    assert (runtime["image"], runtime["image_id"], runtime["started_at"]) == (
        "bible_rag-backend:r5", "sha256:img", "2026-10-21T08:00:00Z")
    assert runtime["env"] == {
        "LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma4:26b", "CLAUDE_MODEL": "claude-x",
        "LLM_TEMPERATURE": "0.1", "LLM_MAX_TOKENS": "4096", "STRICT_BUILD_CHECK": "true",
        "RAG_RANK_FUSION_ALPHA": "0.3", "RAG_USE_GRAPH": "true", "RAG_ENTITY_QUERY_TOP_K": "8",
        "RAG_ENV": "prod", "RAG_DATABASE_URL": "postgresql://***@db:5432/x"}
    assert calls == [(PS_PROD, 5.0),
                     (["docker", "inspect", "--type", "container", "bible_rag_backend"], 5.0)]


def test_no_secret_reaches_run_meta(monkeypatch, tmp_path):
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT), "git rev-parse": "abc\n", "git status": ""})
    _fake_tags(monkeypatch)
    record = rr.start_record(mode="graph", graph_strategies=["event_registry"], n_questions=1,
                             inputs=rr.CollectionInputs(argv=("run_eval.py", "--graph")))

    pv.write_run_meta(tmp_path, pv.Provenance(BUILD, FINGERPRINT), record)

    text = (tmp_path / pv.RUN_META).read_text(encoding="utf-8")
    for leaked in (*SECRET_VALUES, "ANTHROPIC_API_KEY", "POSTGRES_PASSWORD", "OPENAI_API_KEY",
                   "NEO4J_PASSWORD", "GPG_KEY", "RAG_SERVICE_TOKEN", "RAG_DB_PASS", "RAG_API_KEY",
                   "RAG_SECRET_SALT"):
        assert leaked not in text, leaked


@pytest.mark.parametrize("name, kept", [
    ("RAG_GRAPH_STRATEGIES", True), ("RAG_X_PASSPHRASE", False), ("RAG_TOKENIZER", False),
    ("RAG_KEYWORD_PIN", False), ("LLM_MAX_TOKENS", True), ("ANTHROPIC_API_KEY", False),
    ("OLLAMA_BASE_URL", False), ("PATH", False)])
def test_the_allowlist_and_the_rag_prefix_rule(name, kept):
    assert (name in rr.safe_env([f"{name}=v"])) is kept


def test_the_container_is_the_one_publishing_the_backend_url_port(monkeypatch):
    """A staging run once recorded prod's image: the name was fixed, not BACKEND_URL's."""
    calls = []
    _fake_run(monkeypatch, {"docker ps": "bible_rag_backend_stg\n", "docker": json.dumps(INSPECT)},
              calls)
    monkeypatch.setattr(rr.settings, "backend_url", "http://localhost:8002")

    runtime = rr.backend_runtime()

    assert (runtime["container"], runtime["container_from"]) == ("bible_rag_backend_stg", "BACKEND_URL")
    assert [c for c, _ in calls] == [
        ["docker", "ps", "--filter", "publish=8002", "--format", "{{.Names}}"],
        ["docker", "inspect", "--type", "container", "bible_rag_backend_stg"]]


def test_the_container_name_comes_from_the_setting_when_set(monkeypatch):
    calls = []
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT)}, calls)
    monkeypatch.setattr(rr.settings, "eval_backend_container", "rb_backend")

    runtime = rr.backend_runtime()

    assert (runtime["container"], runtime["container_from"]) == ("rb_backend", "EVAL_BACKEND_CONTAINER")
    assert [c for c, _ in calls] == [["docker", "inspect", "--type", "container", "rb_backend"]]


@pytest.mark.parametrize("ps_out", ["", "bible_rag_backend\nother_backend\n"], ids=["none", "two"])
def test_no_single_container_on_the_port_is_an_error_entry(monkeypatch, ps_out):
    calls = []
    _fake_run(monkeypatch, {"docker ps": ps_out, "docker": json.dumps(INSPECT)}, calls)

    runtime = rr.backend_runtime()

    assert runtime["container"] is None and "publish port 8000" in runtime["error"]
    assert [c for c, _ in calls] == [PS_PROD]


def test_a_backend_url_off_this_host_is_an_error_entry_without_docker(monkeypatch):
    calls = []
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT)}, calls)
    monkeypatch.setattr(rr.settings, "backend_url", "http://10.0.0.5:8000")

    runtime = rr.backend_runtime()

    assert runtime["container"] is None and "EVAL_BACKEND_CONTAINER" in runtime["error"]
    assert calls == []


@pytest.mark.parametrize("failure", [
    FileNotFoundError("docker"),
    subprocess.TimeoutExpired(["docker"], 5.0),
    RuntimeError("docker inspect exited 1: Error: No such container: bible_rag_backend"),
], ids=["no_docker", "timeout", "no_container"])
def test_an_unreachable_docker_is_an_error_entry_not_a_failure(monkeypatch, failure):
    _fake_run(monkeypatch, {"docker": failure})

    runtime = rr.backend_runtime()

    assert set(runtime) == {"container", "error"} and runtime["error"]


def test_odd_docker_output_is_an_error_entry(monkeypatch):
    _fake_run(monkeypatch, {"docker": "[]"})

    assert "error" in rr.backend_runtime()


# --- generator ---------------------------------------------------------------------------

def test_an_ollama_generator_records_the_model_digest_and_size(monkeypatch):
    seen = []
    _fake_tags(monkeypatch, seen=seen)
    monkeypatch.setattr(rr.settings, "ollama_base_url", "http://ollama:11434")

    gen = rr.generator_info({"env": {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma4:26b"}})

    assert gen == {"provider": "ollama", "model": "gemma4:26b", "digest": "d1", "size": 2}
    assert seen == ["http://ollama:11434/api/tags"]


def test_an_untagged_ollama_model_is_its_latest_tag(monkeypatch):
    _fake_tags(monkeypatch)

    gen = rr.generator_info({"env": {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma3"}})

    assert gen["digest"] == "d0"


@pytest.mark.parametrize("runtime, tags", [
    ({"env": {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "nope:1b"}}, TAGS),
    ({"env": {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma4:26b"}}, OSError("refused")),
    ({"env": {"LLM_PROVIDER": "ollama"}}, TAGS),
    ({"error": "docker: not found"}, TAGS),
    ({"env": {}}, TAGS),
], ids=["model_not_served", "ollama_down", "no_model_var", "runtime_unknown", "no_provider"])
def test_a_generator_that_cannot_be_identified_is_an_error_entry(monkeypatch, runtime, tags):
    _fake_tags(monkeypatch, tags)

    assert "error" in rr.generator_info(runtime)


def test_an_api_generator_is_named_without_asking_ollama(monkeypatch):
    _fake_tags(monkeypatch, AssertionError("ollama must not be asked"))

    gen = rr.generator_info({"env": {"LLM_PROVIDER": "claude", "CLAUDE_MODEL": "claude-x"}})

    assert gen == {"provider": "claude", "model": "claude-x"}


# --- eval_code ---------------------------------------------------------------------------

def test_eval_code_records_head_and_dirty_evaluation_paths(monkeypatch):
    calls = []
    status = (" M evaluation/src/collector.py\n?? evaluation/results_graph/\n"
              "?? evaluation/new_tool.py\n")
    _fake_run(monkeypatch, {"git rev-parse": "c40cabf\n", "git status": status}, calls)

    code = rr.eval_code_state()

    assert code == {"git_head": "c40cabf", "git_dirty": True, "n_dirty_paths": 3,
                    "dirty_paths": ["evaluation/src/collector.py", "evaluation/results_graph/",
                                    "evaluation/new_tool.py"]}
    assert all(timeout == 5.0 for _, timeout in calls)


def test_untracked_result_directories_alone_do_not_make_the_code_dirty(monkeypatch):
    _fake_run(monkeypatch, {"git rev-parse": "c40cabf\n",
                            "git status": "?? evaluation/results_graph/\n?? evaluation/results_x/\n"})

    code = rr.eval_code_state()

    assert code["git_dirty"] is False and len(code["dirty_paths"]) == 2


def test_dirty_paths_are_capped_at_fifty(monkeypatch):
    status = "".join(f" M evaluation/f{i}.py\n" for i in range(60))
    _fake_run(monkeypatch, {"git rev-parse": "h\n", "git status": status})

    code = rr.eval_code_state()

    assert len(code["dirty_paths"]) == 50 and code["n_dirty_paths"] == 60


def test_git_that_fails_is_an_error_entry(monkeypatch):
    _fake_run(monkeypatch, {"git rev-parse": FileNotFoundError("git"), "git status": ""})

    assert set(rr.eval_code_state()) == {"error"}


# --- health, mode, the record ------------------------------------------------------------

def test_health_summary_keeps_the_handshake_not_build_or_encoder():
    health = {"status": "ok", "services": {"qdrant": True}, "build_id": BUILD,
              "encoder": FINGERPRINT,
              "handshake": {"build_id": BUILD, "ok": True, "strict": True, "mismatches": []}}

    assert rr.health_summary(health) == {"status": "ok", "services": {"qdrant": True},
                                         "ok": True, "strict": True, "mismatches": []}
    assert rr.health_summary(None) is None


@pytest.mark.parametrize("use_graph, semantic, mode", [
    (True, False, "graph"), (False, False, "no_graph"), (None, False, "default"),
    (None, True, "semantic")])
def test_collection_mode_follows_the_cli_flags(use_graph, semantic, mode):
    assert rr.collection_mode(use_graph, semantic) == mode


def _iso_with_tz(text):
    return datetime.fromisoformat(text).tzinfo is not None


def test_start_record_then_finish_record(monkeypatch, tmp_path):
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT), "git rev-parse": "h\n", "git status": ""})
    _fake_tags(monkeypatch)
    monkeypatch.setattr(rr.settings, "top_k", 5)
    ids = tmp_path / "ids.txt"
    ids.write_text("VERSE_LOOKUP_001\n", encoding="utf-8")
    inputs = rr.CollectionInputs(argv=("run_eval.py", "--graph"), ids_file=ids,
                                 health={"status": "ok", "handshake": {"ok": True}})

    record = rr.start_record(mode="graph", graph_strategies=None, n_questions=3, inputs=inputs)
    done = rr.finish_record(record, n_collected=3, n_request_failures=1)

    col = record["collection"]
    assert record["run_meta_version"] == 2
    assert _iso_with_tz(col["started_at"]) and col["finished_at"] is None
    assert {k: col[k] for k in ("mode", "argv", "top_k", "graph_strategies_requested", "ids_file",
                                "ids_file_sha256", "n_questions", "resumed")} == {
        "mode": "graph", "argv": ["run_eval.py", "--graph"], "top_k": 5,
        "graph_strategies_requested": None, "ids_file": str(ids),
        "ids_file_sha256": hashlib.sha256(ids.read_bytes()).hexdigest(), "n_questions": 3,
        "resumed": []}
    assert record["eval_code"]["git_head"] == "h"
    assert record["backend_runtime"]["image"] == "bible_rag-backend:r5"
    assert record["generator"]["digest"] == "d1"
    assert record["backend_health"]["ok"] is True
    assert _iso_with_tz(done["collection"]["finished_at"])
    assert (done["collection"]["n_collected"], done["collection"]["n_request_failures"]) == (3, 1)
    assert record["collection"]["finished_at"] is None      # finish_record copies


def test_a_record_without_any_probe_still_starts():
    """conftest refuses git, docker and HTTP: every probe is an error entry, nothing raises."""
    record = rr.start_record(mode="semantic", graph_strategies=[], n_questions=0,
                             inputs=rr.CollectionInputs())

    assert "error" in record["eval_code"] and "error" in record["backend_runtime"]
    assert "error" in record["generator"] and record["backend_health"] is None
    assert record["collection"]["ids_file"] is None


# --- run_meta.json v2 on disk -------------------------------------------------------------

def test_run_meta_v2_round_trips_and_keeps_the_build(monkeypatch, tmp_path):
    record = rr.start_record(mode="graph", graph_strategies=None, n_questions=1,
                             inputs=rr.CollectionInputs())

    pv.write_run_meta(tmp_path, pv.Provenance(BUILD, FINGERPRINT), record)

    data = json.loads((tmp_path / pv.RUN_META).read_text(encoding="utf-8"))
    assert (data["data_build_id"], data["encoder_fingerprint"]) == (BUILD, FINGERPRINT)
    assert pv.read_run_meta(tmp_path).meta() == {"data_build_id": BUILD,
                                                 "encoder_fingerprint": FINGERPRINT}
    sections = pv.read_run_record(tmp_path)
    assert sections["run_meta_version"] == 2
    assert sections["collection"] == record["collection"]
    assert list(tmp_path.iterdir()) == [tmp_path / pv.RUN_META]     # no .tmp left


def test_a_record_cannot_relabel_the_build(tmp_path):
    pv.write_run_meta(tmp_path, pv.Provenance(BUILD), {"data_build_id": "legacy-20261004",
                                                       "collection": {"mode": "graph"}})

    assert pv.read_run_meta(tmp_path).data_build_id == BUILD


def test_an_old_run_meta_reads_with_every_new_section_null(tmp_path):
    (tmp_path / pv.RUN_META).write_text(json.dumps(
        {"data_build_id": BUILD, "encoder_fingerprint": None}))

    assert pv.read_run_meta(tmp_path).data_build_id == BUILD
    assert pv.read_run_record(tmp_path) == {k: None for k in pv.RUN_META_SECTIONS}


def test_a_checkpoint_without_run_meta_has_no_record(tmp_path):
    assert pv.read_run_record(tmp_path) is None


# --- review fixes (2026-10-28) ------------------------------------------------------------

OLLAMA_RUNTIME = {"env": {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "gemma4:26b"}}


@pytest.mark.parametrize("tags", [[], None, "oops", {"models": "x"}, {"models": [None, "x"]},
                                  {"models": [{"name": ["gemma4:26b"]}]}],
                         ids=["list", "null", "string", "models_not_a_list", "entries_not_objects",
                              "unhashable_name"])
def test_an_odd_api_tags_body_is_an_error_entry_not_a_crash(monkeypatch, tags):
    _fake_tags(monkeypatch, tags)

    gen = rr.generator_info(OLLAMA_RUNTIME)

    assert gen["provider"] == "ollama" and "error" in gen


def test_a_probe_that_raises_unexpectedly_is_an_error_entry(monkeypatch):
    _fake_run(monkeypatch, {"docker": json.dumps(INSPECT), "git rev-parse": "h\n", "git status": ""})

    def boom(runtime):
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(rr, "generator_info", boom)

    record = rr.start_record(mode="graph", graph_strategies=None, n_questions=1,
                             inputs=rr.CollectionInputs())

    assert record["generator"] == {"error": "AttributeError: 'list' object has no attribute 'get'"}
    assert record["backend_runtime"]["image"] == "bible_rag-backend:r5"


@pytest.mark.parametrize("name", ["RAG_Api_Key", "rag_secret", "RAG_Neo4j_Password", "Rag_Db_Pass",
                                  "rag_service_token"])
def test_secret_markers_match_whatever_the_case(name):
    """The backend's pydantic settings read env names case-insensitively, so a secret may be spelled so."""
    assert rr.safe_env([f"{name}=s3cr3t-value"]) == {}


def test_allowlisted_names_match_whatever_the_case():
    assert rr.safe_env(["llm_provider=ollama", "Ollama_Model=gemma4:26b"]) == {
        "Ollama_Model": "gemma4:26b", "llm_provider": "ollama"}


@pytest.mark.parametrize("name", ["RAG_NEO4J_AUTH", "RAG_CREDENTIALS", "RAG_DB_PWD", "RAG_DB_DSN",
                                  "RAG_PRIVATE_X", "RAG_TLS_CERT"])
def test_more_secret_shaped_names_are_dropped(name):
    assert rr.safe_env([f"{name}=neo4j/hunter2"]) == {}


@pytest.mark.parametrize("value, masked", [
    ("postgresql://bible:ab/cd@postgres/db", "postgresql://***@postgres/db"),
    ("postgresql://bible:a@ss@postgres/db", "postgresql://***@postgres/db"),
    ("redis://:pw@redis:6379/0", "redis://***@redis:6379/0"),
    ("http://ollama:11434", "http://ollama:11434"),
])
def test_url_credentials_are_masked_whatever_they_contain(value, masked):
    assert rr.safe_env([f"RAG_SOME_URL={value}"]) == {"RAG_SOME_URL": masked}


@pytest.mark.parametrize("value", [
    "sk-ant-api03-abcdef", "sk_live_123", "ghp_abcdef123", "github_pat_11AAA", "AKIAIOSFODNN7EXAMPLE",
    "AIzaSyD-abc", "xoxb-123-456", "hf_abcdefgh",
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZg==",
])
def test_secret_shaped_values_are_masked(value):
    assert rr.safe_env([f"RAG_EXTRA={value}"]) == {"RAG_EXTRA": "***"}


@pytest.mark.parametrize("value", [
    "true", "0.3", "8", "prod", "event_registry,cross_ref_expand,entity_query", "gemma4:26b-a4b-it-q8_0",
    "claude-sonnet-4-5-20250929", "b20261021_dfa1e3e3", "/mnt/ollama-data/bible_rag_store/b2026",
    '["event_registry"]',
])
def test_ordinary_values_are_kept(value):
    assert rr.safe_env([f"RAG_EXTRA={value}"]) == {"RAG_EXTRA": value}
