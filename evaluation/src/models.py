"""
Pydantic data models for the evaluation pipeline.

Every field is declared: these models ignore undeclared keys (pydantic's default
extra='ignore'), which once dropped GT ``family`` silently, so a field the results must
keep is added here and covered by a round-trip test (tests/test_eval_results_audit.py).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GroundTruthItem(BaseModel):
    question_id: str
    question: str
    question_type: str
    book_name: str
    reference: str = ""
    expected_answer_points: list[str] = []
    reference_answer: str = ""
    # Diagnostic family label (500-question GT expansion). Empty for the
    # legacy 100 questions, which the GT doc designates "legacy_head".
    family: str = ""


class ParsedReference(BaseModel):
    """A single parsed Bible reference unit."""
    book_name: str
    book_id: str
    chapters: list[int] = []          # e.g. [3] or [6,7,8,9]
    verse_start: int | None = None    # e.g. 16
    verse_end: int | None = None      # e.g. 18
    # True → verse range runs from verse_start to the END of chapters[0]
    # (emitted for cross-chapter ranges like "1:17-2:10"; verse_end is None).
    to_chapter_end: bool = False
    is_whole_book: bool = False


class SourceInfo(BaseModel):
    id: str
    book: str
    chapter: int | None = None
    title: str = ""
    verse_range: str = ""
    score: float | None = None
    # Retrieval strategy that surfaced the source (verse_direct / semantic / ...).
    # Diagnostics only; legacy fetches are resolved from book/chapter/verse_range.
    strategy: str | None = None
    # The exact context block the generator saw (header + text), when the
    # backend was asked for it (include_context). None on legacy checkpoints.
    context: str | None = None
    # New builds (R1 API): the record kind and the first/last verse keys the
    # passage spans (ragcommon.ids grammar). None on legacy sources.
    kind: str | None = None
    start_key: str | None = None
    end_key: str | None = None


class EvalSample(BaseModel):
    question_id: str
    question: str
    question_type: str
    rag_answer: str = ""
    contexts: list[str] = []
    sources: list[SourceInfo] = []
    # Where `contexts` came from: backend (generator blocks returned by the API),
    # rebuilt (generator-format blocks rebuilt from PostgreSQL), or
    # legacy_headerless (pre-2026-09 checkpoint text, no headers).
    context_source: str = ""
    ground_truth: GroundTruthItem
    reference_answer: str = ""
    route_used: str = ""
    strategies_used: list[str] = []
    strategy_errors: dict[str, str] = {}
    # The backend's IntentInfo for the question ({type, entities, verse_refs,
    # rejected_refs}) and the arm it was collected under (graph / no_graph /
    # semantic / default); None for checkpoints collected before 2026-10-28.
    intent: dict[str, Any] | None = None
    mode: str | None = None


class MetricResult(BaseModel):
    name: str
    value: float
    category: str  # retrieval | llm_judge | semantic
    valid: bool = True  # False when the metric could not be computed (e.g. RAGAS timeout)


class Rationale(BaseModel):
    """LLM judge rationale explanations for evaluation."""
    faithfulness: str = ""   # zh 判準:「k/n statements supported」+ 只列 verdict=0 的陳述
    relevance: str = ""      # 回答與問題的相關性解釋
    overall: str = ""        # 整體評價解釋
    context: str = ""        # 上下文品質解釋
    faithfulness_strict: str = ""  # RAGAS 預設判準的忠實度解釋
    # Full audit trail: one entry per statement with both metrics' verdicts
    # {statement, verdict, reason, strict_verdict, strict_reason}
    faithfulness_statements: list[dict] = []
    # answer_coverage audit (metrics/coverage_eval.py): one entry per expected point
    # {index, point, verdict, reason} (verdict None = the judge gave none); why the
    # score is invalid (no_expected_points / unparseable / incomplete_verdicts: ... /
    # judge_error: ... / internal_error: ...), the judge's last raw reply when invalid
    # or scored with problems (<= 8000 chars), how many judge calls were made (0 = not
    # judged: no points or an empty answer), what was wrong with the last reply even
    # when it was scored (a repeated index, an extra item, ...), whether it was invalid
    # JSON read by pattern, and why the judge was asked again {why, same_reply}.
    coverage_points: list[dict] = []
    coverage_error: str | None = None
    coverage_raw: str | None = None
    coverage_attempts: int = 0
    coverage_problems: list[str] = []
    coverage_salvaged: bool = False
    coverage_retry: dict[str, Any] | None = None
    # Why a RAGAS metric is invalid for this question: {"ragas_<metric>": message};
    # {"ragas": message} when the whole RAGAS run failed.
    errors: dict[str, str] = {}


class EvalReport(BaseModel):
    question_id: str
    question_type: str
    family: str = ""
    metrics: list[MetricResult] = []
    rationale: Rationale | None = None
    route_used: str = ""
    strategies_used: list[str] = []
    strategy_errors: dict[str, str] = {}
    intent: dict[str, Any] | None = None    # as EvalSample
    mode: str | None = None


class AggregatedReport(BaseModel):
    overall: dict[str, float] = Field(default_factory=dict)
    by_type: dict[str, dict[str, float]] = Field(default_factory=dict)
    by_family: dict[str, dict[str, float]] = Field(default_factory=dict)
    # Run provenance: judge model, ragas version, timestamp, k, n_samples; the build
    # and GT; invalid_counts / invalid_ids, eval_run, run_meta, judge_served_models.
    meta: dict = Field(default_factory=dict)
    samples: list[EvalReport] = []
