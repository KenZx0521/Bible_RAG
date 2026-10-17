"""QD experiment stages (experiments/2026-10-18_graph_qd/qd_stage.py) with a fake container.

A stage resumes by key, redoes a decomposition whose fallback came from an Ollama exception
(plan.md §4 K), keeps a model fallback, refuses a decompose meta naming another model,
cuts a half-written last line, and gives up after its rounds.
"""

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_graph_qd"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

if not Path("/mnt/ollama-data/bible_rag_store").is_dir():
    pytest.skip("store not mounted (qd_common pins store files)", allow_module_level=True)

import qd_common as Q  # noqa: E402
import qd_stage as S  # noqa: E402

META = {"type": "meta", "mode": "decompose", "build_id": Q.gd.BUILD_ID, "pg_schema": "x",
        "llm": Q.LLM_LABEL, "llm_provider": "ollama", "llm_max_tokens": Q.LLM_MAX_TOKENS,
        "decomposer_temperature": 0.0, "prompt_file_sha256": Q.PROMPT_SHA256}


def dec(key, fallback=False, error=None, sq="子查詢"):
    return {"type": "dec", "key": key, "subquery": sq, "fallback": fallback,
            "attempts": [{"error": error, "raw": "", "parsed": sq}]}


class Fake:
    """Answers each call from a queue of per-key outcomes; records the keys it was sent."""

    def __init__(self, outcomes, meta=META):
        self.outcomes, self.meta, self.calls = outcomes, meta, []

    def __call__(self, payload, err):
        keys = [it["key"] for it in payload["items"]]
        self.calls.append(keys)
        return [self.meta] + [self.outcomes[k].pop(0) for k in keys]


def items(*keys):
    return [{"key": k, "question": "問", "pids": ["ps:a.1.1"]} for k in keys]


def test_ensure_resumes_by_key(tmp_path):
    fake = Fake({"a": [dec("a")], "b": [dec("b")]})
    S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a"))
    got = S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a", "b"))
    assert fake.calls == [["a"], ["b"]] and set(got) == {"a", "b"}


def test_an_ollama_failure_fallback_is_redone(tmp_path):
    fake = Fake({"a": [dec("a", True, "ReadTimeout()"), dec("a", sq="好")]})
    got = S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a"))
    assert fake.calls == [["a"], ["a"]] and got["a"]["subquery"] == "好"


def test_a_model_fallback_is_kept(tmp_path):
    fake = Fake({"a": [dec("a", True, None, sq="原題")]})
    got = S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a"))
    assert got["a"]["fallback"] is True and fake.calls == [["a"]]


def test_a_meta_naming_another_model_stops_the_stage(tmp_path):
    fake = Fake({"a": [dec("a")]}, meta={**META, "llm": "Ollama (gemma4:e4b)"})
    with pytest.raises(Q.gd.GdError):
        S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a"))


def test_a_chunk_without_meta_is_retried_next_round(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "FAILED_CHUNK_PAUSE", 0)
    calls = []

    def flaky(payload, err):
        calls.append(1)
        if len(calls) == 1:
            return [{"type": "exit", "returncode": 1}]
        return [META, dec("a")]
    got = S.Stage(tmp_path, "dec", "decompose", flaky).ensure(items("a"))
    assert len(calls) == 2 and set(got) == {"a"}


def test_gives_up_after_its_rounds(tmp_path):
    fake = Fake({"a": [{"type": "error", "key": "a", "error": "x"}] * S.MAX_ROUNDS})
    with pytest.raises(Q.QdError, match="still missing"):
        S.Stage(tmp_path, "dec", "decompose", fake).ensure(items("a"))


def test_duplicate_keys_are_refused(tmp_path):
    with pytest.raises(Q.QdError, match="duplicate"):
        S.Stage(tmp_path, "dec", "decompose", Fake({})).ensure(items("a", "a"))


def test_a_half_written_last_line_is_cut(tmp_path):
    path = tmp_path / "dec.jsonl"
    path.write_text(json.dumps(META) + "\n" + json.dumps(dec("a")) + "\n" + '{"type": "dec", "ke',
                    encoding="utf-8")
    st = S.Stage(tmp_path, "dec", "decompose", Fake({}))
    assert path.read_text(encoding="utf-8").endswith("\n") and set(st.results()) == {"a"}


def test_container_body_holds_the_iterq_helpers_once():
    body = S.container_body()
    assert Q.H.PLACEHOLDER not in body and body.count("async def decompose(") == 1
    assert "BASE_USER_T" in body and 'item.get("user_template")' in body
