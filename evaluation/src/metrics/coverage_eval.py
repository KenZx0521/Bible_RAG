"""
Answer Coverage metric — recall over expected_answer_points.

Measures whether the RAG answer addresses each required answer point listed in
ground_truth.json. Unlike RAGAS answer_correctness (an F1 that punishes every
answer statement absent from the terse reference_answer), coverage is pure
recall: extra correct content is never penalized. It pairs with faithfulness,
which catches hallucination.

Per expected point the judge LLM returns one of:
  covered  -> 1.0   answer clearly states the point
  partial  -> 0.5   answer touches the point but incompletely
  missing  -> 0.0   answer does not address the point

answer_coverage = mean(point scores)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult
from ..llm import judge_completion

console = Console()
logger = logging.getLogger(__name__)

_VERDICT_SCORE = {"covered": 1.0, "partial": 0.5, "missing": 0.0}

# Matches a verdict token. Used by the salvage path: the verdict value is a
# fixed vocabulary and is emitted before the free-text reason, so it survives
# even when an unescaped quote inside a reason corrupts the surrounding JSON.
_VERDICT_RE = re.compile(r'"verdict"\s*:\s*"(covered|partial|missing)"', re.I)

# Concurrency: Ollama serializes inference, so a single in-flight request.
# Other providers tolerate parallel judge calls.
_OLLAMA_WORKERS = 1
_OTHER_WORKERS = 8

# Placeholders are substituted via str.replace so the literal JSON braces in
# the template need no escaping.
_PROMPT_TEMPLATE = """你是聖經問答評估專家。以下給你一個問題、一組「應涵蓋的重點」，以及一份 RAG 系統的回答。

請逐一判斷每個重點是否被回答涵蓋，分成三級：
- "covered"：回答清楚表達了這個重點（換句話說、引用不同經文節數都算）。
- "partial"：回答有觸及這個重點，但不完整、含糊、或只覆蓋了一部分。
- "missing"：回答完全沒有處理這個重點。

重要原則：只判斷每個重點「是否出現在回答中」。不要因為回答比重點更詳盡、或包含額外資訊而扣分——回答冗長是允許的。

【問題】
<<QUESTION>>

【應涵蓋的重點】
<<POINTS>>

【RAG 回答】
<<ANSWER>>

請「只」輸出 JSON，不要任何其他文字。verdicts 陣列的長度與順序必須與重點完全對應：
{"verdicts": [{"index": 1, "verdict": "covered", "reason": "簡短理由"}]}"""


def _parse_verdicts(text: str, n_points: int) -> list[str] | None:
    """
    Extract a verdict list from a judge JSON response, or None on failure.

    Primary path parses strict JSON and honours each verdict's 1-based index.
    When the model emits invalid JSON (commonly an unescaped quote inside a
    Chinese reason string), fall back to extracting verdict tokens positionally
    — they precede the free-text reason field, so reason corruption never
    reaches them.
    """
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()

    # Primary: strict JSON, index-aware.
    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        verdicts = data.get("verdicts") if isinstance(data, dict) else None
        if isinstance(verdicts, list) and verdicts:
            parsed: list[str] = ["missing"] * n_points
            for i, item in enumerate(verdicts):
                if not isinstance(item, dict):
                    continue
                try:
                    pos = int(item.get("index", i + 1)) - 1
                except (TypeError, ValueError):
                    pos = i
                verdict = str(item.get("verdict", "")).strip().lower()
                if 0 <= pos < n_points and verdict in _VERDICT_SCORE:
                    parsed[pos] = verdict
            return parsed

    # Fallback: positional verdict extraction, tolerant of broken JSON.
    found = [v.lower() for v in _VERDICT_RE.findall(cleaned)]
    if not found:
        return None
    salvaged: list[str] = ["missing"] * n_points
    for i, verdict in enumerate(found[:n_points]):
        salvaged[i] = verdict
    return salvaged


def _result(value: float, valid: bool) -> MetricResult:
    return MetricResult(
        name="answer_coverage", value=value, category="llm_judge", valid=valid
    )


async def _score_one(
    sample: EvalSample, semaphore: asyncio.Semaphore
) -> tuple[str, MetricResult]:
    """Judge coverage for a single sample."""
    qid = sample.question_id
    points = sample.ground_truth.expected_answer_points

    # No required points -> coverage is undefined; flag invalid so it is
    # excluded from aggregation rather than coerced to 0.
    if not points:
        logger.warning("[Coverage] %s has no expected_answer_points; skipping", qid)
        return qid, _result(0.0, valid=False)

    # Empty answer / refusal -> a genuine 0 (valid: it should drag the mean).
    if not sample.rag_answer or not sample.rag_answer.strip():
        logger.info("[Coverage] %s => 0.000 (empty/refused answer)", qid)
        return qid, _result(0.0, valid=True)

    points_block = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    prompt = (
        _PROMPT_TEMPLATE
        .replace("<<QUESTION>>", sample.question)
        .replace("<<POINTS>>", points_block)
        .replace("<<ANSWER>>", sample.rag_answer)
    )

    async with semaphore:
        try:
            raw = await judge_completion(prompt, max_tokens=8192, temperature=0.0)
        except Exception as e:  # noqa: BLE001 - judge failure must not abort the run
            logger.error("[Coverage] %s judge call failed: %s", qid, e)
            return qid, _result(0.0, valid=False)

    verdicts = _parse_verdicts(raw, len(points))
    if verdicts is None:
        logger.error("[Coverage] %s unparseable judge output: %r", qid, (raw or "")[:200])
        return qid, _result(0.0, valid=False)

    score = sum(_VERDICT_SCORE[v] for v in verdicts) / len(verdicts)
    logger.info(
        "[Coverage] %s => %.3f  %s",
        qid, score, {i + 1: v for i, v in enumerate(verdicts)},
    )
    return qid, _result(round(score, 4), valid=True)


async def _compute_async(samples: list[EvalSample]) -> dict[str, list[MetricResult]]:
    is_ollama = settings.eval_llm_provider.lower() == "ollama"
    workers = _OLLAMA_WORKERS if is_ollama else _OTHER_WORKERS
    semaphore = asyncio.Semaphore(workers)
    pairs = await asyncio.gather(*(_score_one(s, semaphore) for s in samples))
    return {qid: [mr] for qid, mr in pairs}


def compute_coverage_metrics(
    samples: list[EvalSample],
) -> dict[str, list[MetricResult]]:
    """
    Run answer-coverage evaluation on all samples.

    Returns: { question_id: [MetricResult] }
    """
    console.print(
        f"[bold]Running answer-coverage evaluation "
        f"with {settings.eval_llm_provider}...[/bold]"
    )
    if not samples:
        return {}

    results = asyncio.run(_compute_async(samples))
    valid = sum(1 for ms in results.values() for m in ms if m.valid)
    console.print(
        f"[green]Coverage computed for {valid}/{len(results)} samples.[/green]"
    )
    return results
