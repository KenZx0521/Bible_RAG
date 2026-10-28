"""The judge models the providers said they served, counted per run.

A configured model name is what was asked for; the API's reply names what answered
(e.g. a dated snapshot, or a fallback model). judge_completion counts the model each
reply names; RAGAS calls go through LangChain and are counted by
:class:`ServedModelCallback` from the reply's response_metadata / llm_output. A reply
that names no model is not counted: nothing is guessed. evaluation_results.json
meta.judge_served_models is the snapshot (absent when nothing was counted).
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class ServedModels:
    """Thread-safe {model name: replies} counter."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._counts = Counter()

    def add(self, model: str | None) -> None:
        if not model:
            return
        with self._lock:
            self._counts[str(model)] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))


served_models = ServedModels()


def _named(meta: Any) -> str | None:
    if not isinstance(meta, dict):
        return None
    return meta.get("model_name") or meta.get("model")


def models_in_llm_result(response: Any) -> list[str]:
    """Model names a LangChain LLMResult carries: per generation, else once from llm_output."""
    names = [name
             for generations in getattr(response, "generations", None) or []
             for generation in generations
             if (name := _named(getattr(getattr(generation, "message", None), "response_metadata", None)))]
    if names:
        return names
    name = _named(getattr(response, "llm_output", None))
    return [name] if name else []


class ServedModelCallback(BaseCallbackHandler):
    """Counts the served model of every LangChain reply into ``served_models``."""

    run_inline = True     # in the event loop, not a worker thread

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        for name in models_in_llm_result(response):
            served_models.add(name)
