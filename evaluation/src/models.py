"""
Pydantic data models for the evaluation pipeline.
"""

from __future__ import annotations
from pydantic import BaseModel, Field


class GroundTruthItem(BaseModel):
    question_id: str
    question: str
    question_type: str
    book_name: str
    reference: str = ""
    expected_answer_points: list[str] = []
    reference_answer: str = ""


class ParsedReference(BaseModel):
    """A single parsed Bible reference unit."""
    book_name: str
    book_id: str
    chapters: list[int] = []          # e.g. [3] or [6,7,8,9]
    verse_start: int | None = None    # e.g. 16
    verse_end: int | None = None      # e.g. 18
    is_whole_book: bool = False


class SourceInfo(BaseModel):
    id: str
    book: str
    chapter: int | None = None
    title: str = ""
    verse_range: str = ""
    score: float | None = None


class EvalSample(BaseModel):
    question_id: str
    question: str
    question_type: str
    rag_answer: str = ""
    contexts: list[str] = []
    sources: list[SourceInfo] = []
    ground_truth: GroundTruthItem
    reference_answer: str = ""


class MetricResult(BaseModel):
    name: str
    value: float
    category: str  # retrieval | reference_based | llm_judge | context | semantic


class Rationale(BaseModel):
    """LLM judge rationale explanations for evaluation."""
    faithfulness: str = ""   # 回答對檢索內容的忠實度解釋
    relevance: str = ""      # 回答與問題的相關性解釋
    overall: str = ""        # 整體評價解釋
    context: str = ""        # 上下文品質解釋


class EvalReport(BaseModel):
    question_id: str
    question_type: str
    metrics: list[MetricResult] = []
    rationale: Rationale | None = None


class AggregatedReport(BaseModel):
    overall: dict[str, float] = Field(default_factory=dict)
    by_type: dict[str, dict[str, float]] = Field(default_factory=dict)
    samples: list[EvalReport] = []
