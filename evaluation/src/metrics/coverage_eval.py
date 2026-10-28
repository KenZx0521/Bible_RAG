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

Audit (2026-10-28): every point's verdict and reason is kept (``coverage_points`` in
the result's rationale). A reply that leaves any point without a legal verdict (no
index, an index that is not a whole number or out of range, a verdict outside the
three above) or cannot be parsed at all is asked once more, with a note saying what
was wrong; if it is still incomplete the question's coverage is invalid
(``incomplete_verdicts`` / ``unparseable``) and the raw reply is kept, instead of the
missing points being scored 'missing'. A judge call that raises is invalid at once
(``judge_error``). A complete, legal reply scores as before; one scored despite
defects (a repeated index, an extra item, verdicts read from broken JSON) keeps its
raw reply and the defects (``coverage_problems``, ``coverage_salvaged``).

``_parse_verdicts`` is the pre-2026-10-28 reader (missing points filled 'missing'),
kept unchanged for the archived re-judge scripts; the pipeline reads with
``_read_verdicts``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

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
# An index token for the salvage path (its value is checked like a JSON index).
_INDEX_RE = re.compile(r'"index"\s*:\s*"?([^,}\]\s"]*)"?', re.I)
_WHOLE_NUMBER = re.compile(r"\d+", re.ASCII)

# Judge calls per question: the first, and one retry for an incomplete/unparseable reply.
_MAX_ATTEMPTS = 2
_RAW_LIMIT = 8000

# Concurrency: Ollama serializes inference, so a single in-flight request.
# Other providers tolerate parallel judge calls.
_OLLAMA_WORKERS = 1
_OTHER_WORKERS = 8

# Appended to the prompt when asking again, so a greedy (temperature 0) judge does not
# simply repeat the reply it gave.
_RETRY_NOTE = ("\n\n（上一次的回覆{problem}。請重新輸出完整 JSON：verdicts 剛好 {n} 項，"
               "index 從 1 到 {n} 各出現一次，verdict 只能是 covered、partial 或 missing。）")

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


@dataclass(frozen=True)
class ParsedVerdicts:
    """A judge reply read point by point: ``verdicts[i]`` is None when point i+1 got no legal one."""
    verdicts: tuple[str | None, ...]
    reasons: tuple[str, ...]
    problems: tuple[str, ...] = ()     # what was wrong with the reply, for the audit trail
    salvaged: bool = False             # invalid JSON, its items read by pattern

    @property
    def missing_points(self) -> list[int]:
        return [i for i, v in enumerate(self.verdicts, 1) if v is None]

    @property
    def complete(self) -> bool:
        return not self.missing_points


def _index(value) -> int | None:
    """A judge's 1-based index as an int; None unless it is a whole number (a bool is not)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None     # inf and nan are not integers
    if isinstance(value, str) and _WHOLE_NUMBER.fullmatch(value.strip()):
        return int(value.strip())
    return None


def _json_verdicts(items: list, n_points: int) -> ParsedVerdicts:
    """Index-aware reading of a verdicts list; a defective item fills no point."""
    verdicts: list[str | None] = [None] * n_points
    reasons = [""] * n_points
    problems: list[str] = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"item {i}: not an object")
            continue
        if "index" not in item:
            problems.append(f"item {i}: no index")
            continue
        index = _index(item["index"])
        verdict = str(item.get("verdict", "")).strip().lower()
        if index is None:
            problems.append(f"item {i}: index {item['index']!r} is not a whole number")
        elif not 1 <= index <= n_points:
            problems.append(f"item {i}: index {index} out of range 1..{n_points}")
        elif verdict not in _VERDICT_SCORE:
            problems.append(f"item {i}: verdict {item.get('verdict')!r} is not covered/partial/missing")
        else:
            if verdicts[index - 1] is not None:
                problems.append(f"index {index} given twice (the last kept)")
            verdicts[index - 1], reasons[index - 1] = verdict, str(item.get("reason", "") or "")
    return ParsedVerdicts(tuple(verdicts), tuple(reasons), tuple(problems))


def _salvage_items(cleaned: str) -> tuple[list[dict], list[str]]:
    """{index, verdict} pairs read item by item ('{' to '{') from invalid JSON, and what was not read.

    Both tokens precede a free-text reason in the prompt's item shape, so an unescaped
    quote inside a reason does not reach them. An item without exactly one index and one
    legal verdict fills no point (a verdict is never placed by position).
    """
    items, unread = [], []
    for segment in cleaned.split("{"):
        indexes = _INDEX_RE.findall(segment)
        verdicts = [v.lower() for v in _VERDICT_RE.findall(segment)]
        if len(indexes) == 1 and len(verdicts) == 1:
            items.append({"index": indexes[0], "verdict": verdicts[0]})
        elif indexes or verdicts:
            unread.append(f"an item with {len(indexes)} index and {len(verdicts)} legal verdict "
                          f"token(s) is not read")
    return items, unread


def _salvaged(cleaned: str, n_points: int) -> ParsedVerdicts | None:
    """Verdicts read from invalid JSON by pattern, or None when it holds no legal verdict at all."""
    if not _VERDICT_RE.search(cleaned):
        return None
    items, unread = _salvage_items(cleaned)
    parsed = _json_verdicts(items, n_points)
    problems = (f"invalid JSON: {len(items)} index/verdict pair(s) read by pattern",
                *unread, *parsed.problems)
    return ParsedVerdicts(parsed.verdicts, ("",) * n_points, problems, salvaged=True)


def _read_verdicts(text: str, n_points: int) -> ParsedVerdicts | None:
    """
    Read a judge JSON response point by point, or None when nothing can be read.

    Primary path parses strict JSON and honours each verdict's 1-based index.
    When the model emits invalid JSON (commonly an unescaped quote inside a
    Chinese reason string), fall back to reading each item's index and verdict
    tokens by pattern (_salvaged). Either way a verdict needs its own index, and
    points left without a legal verdict stay None (never 'missing').
    """
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()

    match = re.search(r"\{.*\}", cleaned, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        items = data.get("verdicts") if isinstance(data, dict) else None
        if isinstance(items, list) and items:
            return _json_verdicts(items, n_points)
    return _salvaged(cleaned, n_points)


def _parse_verdicts(text: str, n_points: int) -> list[str] | None:
    """
    The pre-2026-10-28 reader, unchanged: a verdict list with every point the reply
    leaves out filled 'missing', or None on failure.

    Kept only so the archived re-judge scripts (store reports/analysis_20261010/verify/)
    reproduce the old scores; the pipeline reads with _read_verdicts.

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


@dataclass(frozen=True)
class CoverageOutcome:
    """One question's coverage and how it was reached (saved in the result's rationale)."""
    question_id: str
    result: MetricResult
    points: tuple[dict, ...] = ()      # {index, point, verdict, reason}
    error: str | None = None           # why ``result`` is invalid
    raw: str | None = None             # the judge's last reply, kept when invalid or scored with problems
    attempts: int = 0                  # judge calls made (0: not judged)
    problems: tuple[str, ...] = ()     # what was wrong with the last reply (scored or not)
    salvaged: bool = False             # the last reply was invalid JSON, read by pattern
    retry: dict | None = None          # {why, same_reply} when the judge was asked twice

    def rationale_fields(self) -> dict:
        return {"coverage_points": [dict(p) for p in self.points], "coverage_error": self.error,
                "coverage_raw": self.raw, "coverage_attempts": self.attempts,
                "coverage_problems": list(self.problems), "coverage_salvaged": self.salvaged,
                "coverage_retry": None if self.retry is None else dict(self.retry)}


@dataclass(frozen=True)
class _Asked:
    """What asking the judge (once, or twice) gave: the last reply, read."""
    parsed: ParsedVerdicts | None
    raw: str | None
    attempts: int
    error: str | None = None
    retry: dict | None = None


def _points(points: list[str], parsed: ParsedVerdicts | None) -> tuple[dict, ...]:
    return tuple({"index": i, "point": p,
                  "verdict": parsed.verdicts[i - 1] if parsed else None,
                  "reason": parsed.reasons[i - 1] if parsed else ""}
                 for i, p in enumerate(points, 1))


def _incomplete(parsed: ParsedVerdicts) -> str:
    missing = ", ".join(map(str, parsed.missing_points))
    detail = "; ".join(parsed.problems)
    return f"incomplete_verdicts: point(s) {missing} have no legal verdict" + (f" ({detail})" if detail else "")


def _why_retry(parsed: ParsedVerdicts | None) -> str:
    return "unparseable" if parsed is None else _incomplete(parsed)


def _retry_note(parsed: ParsedVerdicts | None, n_points: int) -> str:
    """What the retry prompt adds: what was wrong with the reply, and the shape wanted."""
    problem = ("不是可解析的 JSON" if parsed is None
               else f"第 {'、'.join(map(str, parsed.missing_points))} 點沒有合法的判定")
    return _RETRY_NOTE.format(problem=problem, n=n_points)


def _clip(raw: str | None) -> str | None:
    return None if raw is None else raw[:_RAW_LIMIT]


def _invalid(qid: str, points: list[str], asked: _Asked, error: str) -> CoverageOutcome:
    parsed = asked.parsed
    return CoverageOutcome(qid, _result(0.0, valid=False), _points(points, parsed), error,
                           _clip(asked.raw), asked.attempts,
                           problems=parsed.problems if parsed else (),
                           salvaged=bool(parsed and parsed.salvaged), retry=asked.retry)


def _prompt(sample: EvalSample, points: list[str]) -> str:
    points_block = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    return (
        _PROMPT_TEMPLATE
        .replace("<<QUESTION>>", sample.question)
        .replace("<<POINTS>>", points_block)
        .replace("<<ANSWER>>", sample.rag_answer)
    )


async def _ask(qid: str, prompt: str, n_points: int, semaphore: asyncio.Semaphore) -> _Asked:
    """Ask; ask once more, saying what was wrong, when the reply is incomplete or unparseable."""
    parsed, raw, retry = None, None, None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with semaphore:
                reply = await judge_completion(prompt, max_tokens=8192, temperature=0.0)
        except Exception as e:  # noqa: BLE001 - judge failure must not abort the run
            logger.error("[Coverage] %s judge call failed: %s", qid, e)
            return _Asked(parsed, raw, attempt, f"judge_error: {type(e).__name__}: {e}", retry)
        if retry is not None:
            retry = {**retry, "same_reply": reply == raw}
        raw, parsed = reply, _read_verdicts(reply, n_points)
        if parsed is not None and parsed.complete:
            return _Asked(parsed, raw, attempt, retry=retry)
        if attempt < _MAX_ATTEMPTS:
            retry = {"why": _why_retry(parsed), "same_reply": None}
            logger.warning("[Coverage] %s judge reply %s; asking again", qid, retry["why"])
            prompt += _retry_note(parsed, n_points)
    return _Asked(parsed, raw, _MAX_ATTEMPTS, retry=retry)


async def _judge_sample(sample: EvalSample, semaphore: asyncio.Semaphore) -> CoverageOutcome:
    """Judge coverage for a single sample."""
    qid = sample.question_id
    points = sample.ground_truth.expected_answer_points

    # No required points -> coverage is undefined; flag invalid so it is
    # excluded from aggregation rather than coerced to 0.
    if not points:
        logger.warning("[Coverage] %s has no expected_answer_points; skipping", qid)
        return CoverageOutcome(qid, _result(0.0, valid=False), error="no_expected_points")

    # Empty answer / refusal -> a genuine 0 (valid: it should drag the mean).
    if not sample.rag_answer or not sample.rag_answer.strip():
        logger.info("[Coverage] %s => 0.000 (empty/refused answer)", qid)
        return CoverageOutcome(qid, _result(0.0, valid=True))

    asked = await _ask(qid, _prompt(sample, points), len(points), semaphore)
    parsed = asked.parsed
    if asked.error is not None:
        return _invalid(qid, points, asked, asked.error)
    if parsed is None:
        logger.error("[Coverage] %s unparseable judge output: %r", qid, (asked.raw or "")[:200])
        return _invalid(qid, points, asked, "unparseable")
    if not parsed.complete:
        logger.error("[Coverage] %s %s", qid, _incomplete(parsed))
        return _invalid(qid, points, asked, _incomplete(parsed))

    if parsed.problems:   # complete despite them (an extra item, a salvaged read): scored as before
        logger.warning("[Coverage] %s reply scored with defects: %s", qid, "; ".join(parsed.problems))
    score = sum(_VERDICT_SCORE[v] for v in parsed.verdicts) / len(parsed.verdicts)
    logger.info(
        "[Coverage] %s => %.3f  %s",
        qid, score, {i + 1: v for i, v in enumerate(parsed.verdicts)},
    )
    return CoverageOutcome(qid, _result(round(score, 4), valid=True), _points(points, parsed),
                           raw=_clip(asked.raw) if parsed.problems else None,
                           attempts=asked.attempts, problems=parsed.problems,
                           salvaged=parsed.salvaged, retry=asked.retry)


async def _judge_one(sample: EvalSample, semaphore: asyncio.Semaphore) -> CoverageOutcome:
    """Judge one sample; an unexpected error voids only this question, never the run."""
    try:
        return await _judge_sample(sample, semaphore)
    except Exception as e:  # noqa: BLE001 - one question's defect must not abort every score
        logger.exception("[Coverage] %s internal error", sample.question_id)
        return CoverageOutcome(sample.question_id, _result(0.0, valid=False),
                               error=f"internal_error: {type(e).__name__}: {e}"[:500])


async def _score_one(
    sample: EvalSample, semaphore: asyncio.Semaphore
) -> tuple[str, MetricResult]:
    """(question_id, coverage) for one sample (the shape experiments/ probes call)."""
    outcome = await _judge_one(sample, semaphore)
    return outcome.question_id, outcome.result


async def _compute_async(samples: list[EvalSample]) -> list[CoverageOutcome]:
    is_ollama = settings.eval_llm_provider.lower() == "ollama"
    workers = _OLLAMA_WORKERS if is_ollama else _OTHER_WORKERS
    semaphore = asyncio.Semaphore(workers)
    return await asyncio.gather(*(_judge_one(s, semaphore) for s in samples))


def compute_coverage(
    samples: list[EvalSample],
) -> tuple[dict[str, list[MetricResult]], dict[str, CoverageOutcome]]:
    """
    Run answer-coverage evaluation on all samples.

    Returns: ({ question_id: [MetricResult] }, { question_id: CoverageOutcome })
    """
    console.print(
        f"[bold]Running answer-coverage evaluation "
        f"with {settings.eval_llm_provider}...[/bold]"
    )
    if not samples:
        return {}, {}

    outcomes = asyncio.run(_compute_async(samples))
    results = {o.question_id: [o.result] for o in outcomes}
    valid = sum(1 for o in outcomes if o.result.valid)
    retried = sum(1 for o in outcomes if o.attempts > 1)
    console.print(
        f"[green]Coverage computed for {valid}/{len(results)} samples "
        f"({retried} asked twice).[/green]"
    )
    return results, {o.question_id: o for o in outcomes}


def compute_coverage_metrics(
    samples: list[EvalSample],
) -> dict[str, list[MetricResult]]:
    """compute_coverage without the per-question detail: { question_id: [MetricResult] }."""
    return compute_coverage(samples)[0]
