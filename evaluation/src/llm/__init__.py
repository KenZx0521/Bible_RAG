"""
Evaluation LLM abstraction layer.
Provides judge_completion() for LLM-as-Judge and create_langchain_llm() for RAGAS.
"""

from .judge_client import judge_completion
from .langchain_factory import create_langchain_llm

__all__ = ["judge_completion", "create_langchain_llm"]
