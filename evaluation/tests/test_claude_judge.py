"""Claude judge requests for models that take only default sampling (Haiku 5.5).

Claude 4.7+ models reject `temperature` with a 400 and open replies with a
`thinking` block when adaptive thinking is on (the Haiku 5.5 default).
"""

import asyncio
from types import SimpleNamespace

import anthropic
import pytest

from src.config import settings
from src.llm import judge_client
from src.llm.langchain_factory import create_langchain_llm
from src.metrics.ragas_eval import _wrap_judge_llm


def _fake_client(content: list, stop_reason: str = "end_turn"):
    """An AsyncAnthropic stand-in recording the create() kwargs."""
    sent: dict = {}
    resp = SimpleNamespace(content=content, stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    async def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(status_code=200, parse=lambda: resp)

    messages = SimpleNamespace(with_raw_response=SimpleNamespace(create=create))
    return sent, (lambda **_: SimpleNamespace(messages=messages))


@pytest.fixture
def claude_judge(monkeypatch):
    monkeypatch.setattr(settings, "eval_llm_provider", "claude")
    monkeypatch.setattr(settings, "eval_claude_model", "claude-haiku-5-5")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")


def test_claude_request_omits_temperature_and_reads_text_after_thinking(claude_judge, monkeypatch):
    sent, client = _fake_client([SimpleNamespace(type="thinking", thinking="", signature="s"),
                                 SimpleNamespace(type="text", text=' {"verdict": 1} ')])
    monkeypatch.setattr(anthropic, "AsyncAnthropic", client)

    out = asyncio.run(judge_client.judge_completion("p", max_tokens=64, temperature=0.0))

    assert out == '{"verdict": 1}'
    assert "temperature" not in sent
    assert sent["model"] == "claude-haiku-5-5"


def test_claude_reply_without_text_raises_with_stop_reason(claude_judge, monkeypatch):
    _, client = _fake_client([SimpleNamespace(type="thinking", thinking="", signature="s")],
                             stop_reason="max_tokens")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", client)

    with pytest.raises(RuntimeError, match="max_tokens"):
        asyncio.run(judge_client.judge_completion("p", max_tokens=64))


def test_langchain_claude_model_sends_no_temperature(claude_judge):
    llm = create_langchain_llm()

    assert llm.temperature is None


@pytest.mark.parametrize(("provider", "bypass"), [("claude", True), ("ollama", False)])
def test_ragas_wrapper_skips_temperature_override_only_for_claude(monkeypatch, provider, bypass):
    from ragas.run_config import RunConfig

    monkeypatch.setattr(settings, "eval_llm_provider", provider)

    wrapper = _wrap_judge_llm(SimpleNamespace(temperature=None), RunConfig())

    assert wrapper.bypass_temperature is bypass
