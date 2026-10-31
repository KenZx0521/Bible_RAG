"""The vLLM client: the request it sends (thinking on, Ollama's budget) and what it reads back."""

import asyncio
import json

import httpx
import pytest

from utils.llm import factory, vllm_client
from utils.llm.vllm_client import VLLMClient

MODEL = "google/gemma-4-E4B-it"


def _serve(monkeypatch, handler):
    """Route the client's httpx calls to ``handler``; returns the requests it saw."""
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(record), **kwargs)

    monkeypatch.setattr(vllm_client.httpx, "AsyncClient", Client)
    return seen


def _completion(content):
    return httpx.Response(200, json={"choices": [{"message": {
        "role": "assistant", "content": content, "reasoning": "thought"}}]})


def test_chat_asks_for_thinking_and_returns_only_the_answer(monkeypatch):
    seen = _serve(monkeypatch, lambda r: _completion("摩西的岳父是葉忒羅。"))
    messages = [{"role": "user", "content": "摩西的岳父是誰？"}]

    answer = asyncio.run(VLLMClient("http://vllm:8000/", MODEL).chat(
        messages, temperature=0.2, max_tokens=300))

    assert answer == "摩西的岳父是葉忒羅。"
    assert str(seen[0].url) == "http://vllm:8000/v1/chat/completions"
    assert json.loads(seen[0].content) == {
        "model": MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 300,
        "chat_template_kwargs": {"enable_thinking": True}}


def test_a_thought_that_used_up_max_tokens_answers_empty(monkeypatch):
    _serve(monkeypatch, lambda r: _completion(None))

    assert asyncio.run(VLLMClient("http://vllm:8000", MODEL).chat([])) == ""


def test_an_http_error_is_raised(monkeypatch):
    _serve(monkeypatch, lambda r: httpx.Response(400, json={"error": "too long"}))

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(VLLMClient("http://vllm:8000", MODEL).chat([]))


@pytest.mark.parametrize("handler, healthy", [
    (lambda r: httpx.Response(200, json={"data": [{"id": MODEL}]}), True),
    (lambda r: httpx.Response(200, json={"data": [{"id": "google/gemma-4-31B-it"}]}), False),
    (lambda r: httpx.Response(503), False),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), False),
], ids=["served", "other_model", "unavailable", "down"])
def test_health_is_the_model_being_served(monkeypatch, handler, healthy):
    seen = _serve(monkeypatch, handler)

    assert asyncio.run(VLLMClient("http://vllm:8000", MODEL).health_check()) is healthy
    assert str(seen[0].url) == "http://vllm:8000/v1/models"


def test_the_factory_builds_the_vllm_client_from_settings(monkeypatch):
    from config import settings

    monkeypatch.setattr(factory, "_instance", None)
    monkeypatch.setattr(settings, "llm_provider", "vLLM")
    monkeypatch.setattr(settings, "vllm_base_url", "http://vllm:8000")
    monkeypatch.setattr(settings, "vllm_model", MODEL)

    client = factory.get_llm_client()

    assert isinstance(client, VLLMClient) and client.provider_name == f"vLLM ({MODEL})"
    monkeypatch.setattr(factory, "_instance", None)
