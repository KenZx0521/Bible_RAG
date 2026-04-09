"""
Synchronous Ollama LLM client for entity extraction scripts.
"""

import logging

import httpx

from .llm_extractor import BaseLLMClient
from .config import EntityExtractLLMConfig

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Synchronous Ollama client using httpx."""

    def __init__(self, config: EntityExtractLLMConfig):
        # BaseLLMClient expects a LLMConfig but we only use rate_limit()
        super().__init__(config)
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model

    def call(self, system_prompt: str, user_prompt: str) -> str:
        self.rate_limit()

        with httpx.Client(timeout=600.0) as client:
            resp = client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": self.config.temperature,
                        "num_predict": self.config.max_tokens,
                        "num_ctx": getattr(self.config, "num_ctx", 8192),
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            tokens_eval = data.get("eval_count", "?")
            tokens_prompt = data.get("prompt_eval_count", "?")
            duration_s = data.get("total_duration", 0) / 1e9
            done_reason = data.get("done_reason", "?")
            logger.info(
                f"Ollama response: prompt_tokens={tokens_prompt}, "
                f"eval_tokens={tokens_eval}, duration={duration_s:.1f}s, "
                f"done_reason={done_reason}, content_len={len(content)}"
            )
            if not content or not content.strip():
                logger.warning(
                    f"Ollama returned empty content! Full response keys: {list(data.keys())}, "
                    f"done={data.get('done')}, done_reason={done_reason}, "
                    f"message={data.get('message')}"
                )
            return content
