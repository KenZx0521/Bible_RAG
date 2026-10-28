"""The judge models the APIs said they served (meta.judge_served_models).

judge_completion counts what each provider's reply names; RAGAS calls go through
LangChain and are counted by a callback reading the reply's response_metadata. A reply
that names no model is not counted. No network is reached.
"""

import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from src.config import settings
from src.llm import judge_client
from src.llm.served_models import ServedModelCallback, ServedModels, served_models


@pytest.fixture(autouse=True)
def _fresh_counts():
    served_models.reset()
    yield
    served_models.reset()


def test_counts_accumulate_and_reset():
    counts = ServedModels()
    counts.add("a")
    counts.add("a")
    counts.add(None)
    counts.add("")
    counts.add("b")

    assert counts.snapshot() == {"a": 2, "b": 1}
    counts.reset()
    assert counts.snapshot() == {}


def test_a_claude_reply_counts_the_model_it_names(monkeypatch):
    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                           model="claude-haiku-5-5-20261001")

    async def create(**kwargs):
        return SimpleNamespace(status_code=200, parse=lambda: resp)

    messages = SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=messages))
    monkeypatch.setattr(settings, "eval_llm_provider", "claude")

    asyncio.run(judge_client.judge_completion("p"))

    assert served_models.snapshot() == {"claude-haiku-5-5-20261001": 1}


def test_an_ollama_reply_counts_the_model_it_names(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            return httpx.Response(200, json={"model": "gemma4:26b", "response": "ok"},
                                  request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "eval_llm_provider", "ollama")

    assert asyncio.run(judge_client.judge_completion("p")) == "ok"
    assert served_models.snapshot() == {"gemma4:26b": 1}


def test_a_reply_naming_no_model_is_not_counted(monkeypatch):
    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    async def create(**kwargs):
        return SimpleNamespace(status_code=200, parse=lambda: resp)

    messages = SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=messages))
    monkeypatch.setattr(settings, "eval_llm_provider", "claude")

    asyncio.run(judge_client.judge_completion("p"))

    assert served_models.snapshot() == {}


@pytest.mark.parametrize("meta, llm_output, counted", [
    ({"model_name": "claude-haiku-5-5-20261001"}, None, {"claude-haiku-5-5-20261001": 1}),
    ({"model": "gemma4:26b"}, None, {"gemma4:26b": 1}),
    ({}, {"model_name": "gpt-x"}, {"gpt-x": 1}),
    ({}, None, {}),
], ids=["anthropic", "ollama", "llm_output", "nothing"])
def test_the_langchain_callback_reads_what_the_reply_names(meta, llm_output, counted):
    result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x",
                                                                       response_metadata=meta))]],
                       llm_output=llm_output)

    ServedModelCallback().on_llm_end(result)

    assert served_models.snapshot() == counted
