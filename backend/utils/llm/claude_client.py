"""Claude (Anthropic) LLM client."""

import anthropic

from .base import LLMClient


class ClaudeClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return f"Claude ({self._model})"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        # Anthropic API uses a separate system parameter
        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                chat_messages.append(msg)

        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        resp = await self._client.messages.create(**kwargs)
        return resp.content[0].text

    async def health_check(self) -> bool:
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
            return bool(resp.content)
        except Exception:
            return False
