"""
Faithfulness metrics adapted to this task (2026-09-10 audit).

Two metrics share one statement decomposition per sample:

  faithfulness         zh-TW NLI judge that sees the user question, treats the
                       ``[i] 書卷 第N章`` header as part of the context, and does
                       not count question premises / headings / requested
                       synthesis as fabrication. Main reading.
  faithfulness_strict  RAGAS 0.4.3 default NLI prompt on the same (header-
                       bearing) context and the same zh decomposition.
                       Conservative gate. (The 2026-09-10 audit's "hdr"
                       condition used RAGAS's English decomposition; the gate
                       threshold is re-derived from results_quick/
                       faith_metric_validation.json, not from the audit.)

Every statement/verdict/reason pair is kept in ``verdict_log`` so a run can
be audited without re-judging. RAGAS overrides the judge temperature per
call (``BaseRagasLLM.get_temperature`` -> 0.01 for n=1), so both metrics are
effectively greedy regardless of the factory setting.
"""

from __future__ import annotations

import asyncio
import hashlib
import typing as t
from dataclasses import dataclass, field

import numpy as np

from ragas.metrics._faithfulness import (
    Faithfulness,
    NLIStatementInput,
    NLIStatementOutput,
    NLIStatementPrompt,
    StatementFaithfulnessAnswer,
    StatementGeneratorInput,
    StatementGeneratorOutput,
    StatementGeneratorPrompt,
)
from ragas.prompt import PydanticPrompt

if t.TYPE_CHECKING:
    from langchain_core.callbacks import Callbacks

CacheKey = tuple[str, str]
LogKey = tuple[str, str, str]

QUESTION_PREFIX = "【使用者問題】"
CONTEXT_PREFIX = "【經文段落】"
ZH_METRIC_NAME = "faithfulness"
STRICT_METRIC_NAME = "faithfulness_strict"


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

class ZhStatementGeneratorPrompt(StatementGeneratorPrompt):
    instruction = (
        "給定一個問題與其回答，把回答中的每個句子拆成一或多個可以獨立驗證的陳述。規則：\n"
        "1. 陳述中的代名詞（他、她、他們、其）改寫成明確的人物或事物；\n"
        "2. 引號「」內的經文原句逐字保留，不改寫其中的「我、你、你們」；\n"
        "3. 每個陳述保留原句所附的出處括號（書卷、章、節）；\n"
        "4. 標題與引導句（例如「耶穌的解釋：」）併入其後的內容，不單獨成為一條陳述；\n"
        "5. 不新增回答中沒有的內容。\n"
        "以 JSON 格式輸出。"
    )
    examples = [
        (
            StatementGeneratorInput(
                question="根據約翰福音20:29，耶穌對多馬說什麼樣的人有福？",
                answer=(
                    "根據約翰福音第20章第29節，耶穌對多馬說：「你因看見了我才信；那沒有看見就信的有福了。」\n\n"
                    "**耶穌的意思：** 他稱許那些沒有親眼看見卻相信的人（約翰福音 20:29）。"
                ),
            ),
            StatementGeneratorOutput(
                statements=[
                    "根據約翰福音第20章第29節，耶穌對多馬說：「你因看見了我才信；那沒有看見就信的有福了。」",
                    "耶穌稱許那些沒有親眼看見卻相信的人（約翰福音 20:29）。",
                ]
            ),
        )
    ]


class ZhNLIPrompt(NLIStatementPrompt):
    instruction = (
        "你的任務是根據給定的經文段落（context），逐條判斷陳述（statements）是否忠於經文。"
        "若陳述能由經文直接支持或合理推得，verdict=1；若陳述加入了經文中沒有的事實、或與經文矛盾，verdict=0。判斷準則：\n"
        "1. 段落標頭（例如「[1] 約翰福音 第3章 - 耶穌與尼哥德慕 (16節)」）是經文的一部分；陳述中的書卷、章、節出處只要與標頭相符即視為有支持。\n"
        "2. 陳述若只是複述「使用者問題」中已給定的前提（例如問題已指明說話者、對象、書卷或經文位置），不視為捏造；"
        "但若經文與該前提矛盾，或陳述把前提套用到經文沒有提供的段落上，verdict=0。\n"
        "3. 標題、引導句、格式性片段（如「耶穌的解釋：」）不是事實宣稱，給 verdict=1；"
        "對「所提供經文是否包含某內容」的說明，要核對經文：描述正確 verdict=1，描述錯誤（經文其實有提到）verdict=0。\n"
        "4. 針對問題所要求的歸納、比較、分階段整理，只要各組成事實均出自經文即 verdict=1；若引入經文沒有的人物、地點、事件、數字，或錯置歸屬（把甲的事說成乙、把父子關係寫反、把說話者與聽者對調），verdict=0。\n"
        "5. 對經文的意譯、白話重述或同義轉換視為有支持；引用經文原句時，句中的「我、你、你們」依經文脈絡理解。\n"
        "請以 JSON 格式輸出。"
    )
    examples = [
        (
            NLIStatementInput(
                context=(
                    f"{QUESTION_PREFIX}根據約翰福音20:29，耶穌對多馬說什麼樣的人有福？\n\n"
                    f"{CONTEXT_PREFIX}\n[1] 約翰福音 第20章 - 耶穌向多馬顯現 (29節)\n"
                    "29. 耶穌對他說：「你因看見了我才信；那沒有看見就信的有福了。」"
                ),
                statements=[
                    "根據約翰福音第20章第29節，耶穌對多馬說話。",
                    "耶穌說那沒有看見就信的人有福了。",
                    "多馬後來到印度傳道。",
                    "這句話是保羅對多馬說的。",
                ],
            ),
            NLIStatementOutput(statements=[
                StatementFaithfulnessAnswer(statement="根據約翰福音第20章第29節，耶穌對多馬說話。", reason="出處與段落標頭相符；「多馬」是使用者問題已給定的對象，且經文記載耶穌對他說話。", verdict=1),
                StatementFaithfulnessAnswer(statement="耶穌說那沒有看見就信的人有福了。", reason="經文明載「那沒有看見就信的有福了」。", verdict=1),
                StatementFaithfulnessAnswer(statement="多馬後來到印度傳道。", reason="經文段落完全沒有提到印度或傳道，屬經文以外的資訊。", verdict=0),
                StatementFaithfulnessAnswer(statement="這句話是保羅對多馬說的。", reason="經文明載說話者是耶穌，陳述錯置歸屬。", verdict=0),
            ]),
        ),
        (
            NLIStatementInput(
                context=(
                    f"{QUESTION_PREFIX}亞拿尼亞和撒非喇犯了什麼罪？結局如何？\n\n"
                    f"{CONTEXT_PREFIX}\n[1] 使徒行傳 第5章 - 亞拿尼亞和撒非喇 (1-11節)\n"
                    "1 有一個人，名叫亞拿尼亞，同他的妻子撒非喇賣了田產， 2 把價銀私自留下幾分，他的妻子也知道，其餘的幾分拿來放在使徒腳前。 "
                    "3 彼得說：「亞拿尼亞！為甚麼撒但充滿了你的心，叫你欺哄聖靈，把田地的價銀私自留下幾分呢？」 "
                    "5 亞拿尼亞聽見這話，就仆倒，斷了氣；聽見的人都甚懼怕。 6 有些少年人起來，把他包裹，抬出去埋葬了。"
                ),
                statements=[
                    "亞拿尼亞和撒非喇私自留下部分賣田產的價銀（使徒行傳 第5章 2節）。",
                    "亞拿尼亞聽見彼得的話就仆倒斷了氣（使徒行傳 第5章 5節）。",
                    "撒非喇被會眾用石頭打死。",
                    "提供的經文段落沒有提到他們埋葬的地點。",
                    "提供的經文段落沒有提到彼得。",
                ],
            ),
            NLIStatementOutput(statements=[
                StatementFaithfulnessAnswer(statement="亞拿尼亞和撒非喇私自留下部分賣田產的價銀（使徒行傳 第5章 2節）。", reason="第2節明載，且出處與標頭相符。", verdict=1),
                StatementFaithfulnessAnswer(statement="亞拿尼亞聽見彼得的話就仆倒斷了氣（使徒行傳 第5章 5節）。", reason="第3節是彼得說話，第5節記載他仆倒斷氣。", verdict=1),
                StatementFaithfulnessAnswer(statement="撒非喇被會眾用石頭打死。", reason="經文沒有記載用石頭打死，屬捏造。", verdict=0),
                StatementFaithfulnessAnswer(statement="提供的經文段落沒有提到他們埋葬的地點。", reason="對所提供經文內容的描述正確：只說抬出去埋葬，未提地點。", verdict=1),
                StatementFaithfulnessAnswer(statement="提供的經文段落沒有提到彼得。", reason="描述錯誤：第3節明載彼得說話。", verdict=0),
            ]),
        ),
    ]


def build_nli_context(question: str, contexts: list[str]) -> str:
    """Question-aware NLI context: the judge must know what the question already gave."""
    return f"{QUESTION_PREFIX}{question}\n\n{CONTEXT_PREFIX}\n" + "\n\n".join(contexts)


# --------------------------------------------------------------------------
# Shared state: one decomposition per (question, answer); full verdict audit log
# --------------------------------------------------------------------------

def _cache_key(row: dict) -> CacheKey:
    """Decomposition depends on question + answer only."""
    return (row["user_input"], row["response"])


def log_key(question: str, answer: str, contexts: list[str]) -> LogKey:
    """Verdicts depend on the context too; identical Q/A rows with different contexts stay apart."""
    digest = hashlib.sha1("\n\n".join(contexts).encode("utf-8")).hexdigest()
    return (question, answer, digest)


def _log_key(row: dict) -> LogKey:
    return log_key(row["user_input"], row["response"], list(row["retrieved_contexts"]))


def _future_failed(fut: asyncio.Future) -> bool:
    return fut.cancelled() or (fut.done() and fut.exception() is not None)


class StatementCache:
    """
    Dedupes concurrent statement generation for the same row: both metrics
    await one future. The await is shielded so a consumer cancelled by RAGAS's
    per-job timeout cannot cancel a producer its sibling is still waiting on;
    when the cancelled consumer was the LAST waiter the producer is cancelled
    too, so an orphaned call does not keep occupying a serialized judge
    (Ollama, max_workers=1) and cascade timeouts into the following rows.
    """

    def __init__(self) -> None:
        self._futures: dict[CacheKey, asyncio.Future] = {}
        # waiter counts keyed by the future itself, so a reset()/replacement
        # can never alias a stale waiter onto a fresh producer
        self._waiters: dict[asyncio.Future, int] = {}

    def reset(self) -> None:
        self._futures = {}
        self._waiters = {}

    def size(self) -> int:
        return len(self._futures)

    def _on_done(self, key: CacheKey, fut: asyncio.Future) -> None:
        # Retrieve the exception (silences "Task exception was never retrieved")
        # and evict a failed producer eagerly.
        failed = fut.cancelled() or fut.exception() is not None
        if failed and self._futures.get(key) is fut:
            self._futures.pop(key, None)

    async def get_or_create(self, key: CacheKey, factory: t.Callable[[], t.Awaitable[t.Any]]) -> t.Any:
        fut = self._futures.get(key)
        if fut is None or _future_failed(fut):
            fut = asyncio.ensure_future(factory())
            fut.add_done_callback(lambda f, k=key: self._on_done(k, f))
            self._futures[key] = fut
        self._waiters[fut] = self._waiters.get(fut, 0) + 1
        try:
            return await asyncio.shield(fut)
        finally:
            remaining = self._waiters.get(fut, 1) - 1
            if remaining > 0:
                self._waiters[fut] = remaining
            else:
                self._waiters.pop(fut, None)
                if not fut.done():
                    fut.cancel()  # last waiter left (timeout): free the judge
                    if self._futures.get(key) is fut:
                        self._futures.pop(key, None)


class VerdictLog:
    """Per-row statement verdicts for every faithfulness metric that ran."""

    def __init__(self) -> None:
        self._log: dict[t.Hashable, dict[str, list[tuple[str, int, str]]]] = {}

    def reset(self) -> None:
        self._log = {}

    def record(self, metric_name: str, key: t.Hashable, triples: list[tuple[str, int, str]]) -> None:
        self._log.setdefault(key, {})[metric_name] = list(triples)

    def entries(self, key: t.Hashable) -> list[dict]:
        """
        Merge zh and strict verdicts by statement text; zh order leads. Strict
        verdicts that match no zh statement are appended (verdict=None) so the
        strict count always equals what the metric scored.
        """
        per_metric = self._log.get(key)
        if not per_metric:
            return []
        zh = per_metric.get(ZH_METRIC_NAME) or []
        strict = per_metric.get(STRICT_METRIC_NAME) or []
        if not zh:
            return [{"statement": s, "verdict": None, "reason": None, "strict_verdict": v, "strict_reason": r}
                    for s, v, r in strict]
        zh_texts = {s for s, _, _ in zh}
        # text -> strict indices in order, so duplicated statements pair positionally
        strict_index: dict[str, list[int]] = {}
        for j, (s, _, _) in enumerate(strict):
            strict_index.setdefault(s, []).append(j)
        # Positional fallback only when the judge rewrote a statement it could
        # not have matched by text (same count, unmatched text at that index).
        positional_ok = len(strict) == len(zh)
        consumed: set[int] = set()
        out = []
        for i, (stmt, verdict, reason) in enumerate(zh):
            candidates = strict_index.get(stmt) or []
            j = next((c for c in candidates if c not in consumed), None)
            if j is None and positional_ok and strict[i][0] not in zh_texts:
                j = i
            if j is None or j in consumed:
                sv, sr = None, None
            else:
                consumed.add(j)
                sv, sr = strict[j][1], strict[j][2]
            out.append({"statement": stmt, "verdict": verdict, "reason": reason,
                        "strict_verdict": sv, "strict_reason": sr})
        for j, (s, v, r) in enumerate(strict):
            if j not in consumed:
                out.append({"statement": s, "verdict": None, "reason": None,
                            "strict_verdict": v, "strict_reason": r})
        return out


statement_cache = StatementCache()
verdict_log = VerdictLog()


def build_faithfulness_rationale(entries: list[dict], verdict_key: str, reason_key: str) -> str:
    """
    Human-readable rationale for one judge: support count + every failing
    statement with its reason. "" when that judge did not run.
    """
    judged = [e for e in entries if e.get(verdict_key) is not None]
    if not judged:
        return ""
    negatives = [e for e in judged if e.get(verdict_key) == 0]
    head = f"{len(judged) - len(negatives)}/{len(judged)} statements supported"
    if not negatives:
        return head
    return " | ".join([head] + [f"[0] {e['statement']} || {e.get(reason_key) or ''}" for e in negatives])


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

@dataclass
class _SharedDecompositionFaithfulness(Faithfulness):
    """Faithfulness whose statement decomposition is shared across sibling metrics."""

    statement_generator_prompt: PydanticPrompt = field(default_factory=ZhStatementGeneratorPrompt)

    async def _create_statements(self, row: dict, callbacks: "Callbacks") -> StatementGeneratorOutput:
        async def make() -> StatementGeneratorOutput:
            return await Faithfulness._create_statements(self, row, callbacks)
        return await statement_cache.get_or_create(_cache_key(row), make)

    def _nli_context(self, row: dict) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    async def _create_verdicts(self, row: dict, statements: list[str], callbacks: "Callbacks") -> NLIStatementOutput:
        assert self.llm is not None, "llm must be set to compute score"
        return await self.nli_statements_prompt.generate(
            llm=self.llm,
            data=NLIStatementInput(context=self._nli_context(row), statements=statements),
            callbacks=callbacks,
        )

    async def _ascore(self, row: dict, callbacks: "Callbacks") -> float:
        assert self.llm is not None, "LLM is not set"
        statements = (await self._create_statements(row, callbacks)).statements
        if not statements:
            return np.nan
        verdicts = await self._create_verdicts(row, statements, callbacks)
        verdict_log.record(
            self.name, _log_key(row),
            [(a.statement, int(bool(a.verdict)), a.reason) for a in verdicts.statements],
        )
        return self._compute_score(verdicts)


@dataclass
class FaithfulnessZh(_SharedDecompositionFaithfulness):
    name: str = ZH_METRIC_NAME
    nli_statements_prompt: PydanticPrompt = field(default_factory=ZhNLIPrompt)

    def _nli_context(self, row: dict) -> str:
        return build_nli_context(row["user_input"], list(row["retrieved_contexts"]))


@dataclass
class FaithfulnessStrict(_SharedDecompositionFaithfulness):
    name: str = STRICT_METRIC_NAME
    nli_statements_prompt: PydanticPrompt = field(default_factory=NLIStatementPrompt)

    def _nli_context(self, row: dict) -> str:
        return "\n\n".join(row["retrieved_contexts"])
