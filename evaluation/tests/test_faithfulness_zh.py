"""
Faithfulness judge fixes (2026-09-10 audit):
  - NLI context carries the user question (question-premise entities are not hallucinations)
  - zh-TW NLI/statement prompts subclass the RAGAS 0.4.3 prompts
  - the strict and zh metrics share one statement decomposition per sample
  - a consumer cancelled by RAGAS's per-job timeout cannot poison the shared decomposition
  - every statement/verdict/reason is retained for auditing
"""

import asyncio

import pytest

from src.metrics.faithfulness_zh import (
    FaithfulnessStrict,
    FaithfulnessZh,
    StatementCache,
    ZhNLIPrompt,
    ZhStatementGeneratorPrompt,
    build_faithfulness_rationale,
    build_nli_context,
    log_key,
    verdict_log,
)


def test_nli_context_prefixes_question_and_joins_blocks():
    ctx = build_nli_context("根據約翰福音3:16?", ["[1] 約翰福音 第3章\n16. 上帝愛世人", "[2] x\ny"])
    assert ctx.startswith("【使用者問題】根據約翰福音3:16?\n\n【經文段落】\n")
    assert "[1] 約翰福音 第3章\n16. 上帝愛世人\n\n[2] x\ny" in ctx


def test_metric_names_are_distinct_and_stable():
    assert FaithfulnessZh().name == "faithfulness"
    assert FaithfulnessStrict().name == "faithfulness_strict"


def test_zh_prompts_subclass_ragas_prompts():
    from ragas.metrics._faithfulness import NLIStatementPrompt, StatementGeneratorPrompt
    assert isinstance(ZhNLIPrompt(), NLIStatementPrompt)
    assert isinstance(ZhStatementGeneratorPrompt(), StatementGeneratorPrompt)
    ex_in, ex_out = ZhNLIPrompt().examples[0]
    assert "【使用者問題】" in ex_in.context
    assert any(a.verdict == 0 for a in ex_out.statements) and any(a.verdict == 1 for a in ex_out.statements)


def test_zh_nli_examples_teach_wrong_meta_claim_is_unfaithful():
    """A false 'the passage does not mention X' must be a negative example, not only a positive one."""
    _, ex_out = ZhNLIPrompt().examples[1]
    meta = [a for a in ex_out.statements if a.statement.startswith("提供的經文段落沒有提到")]
    assert {a.verdict for a in meta} == {0, 1}


def test_zh_metric_uses_zh_prompts_and_strict_uses_ragas_default_nli():
    from ragas.metrics._faithfulness import NLIStatementPrompt
    zh, strict = FaithfulnessZh(), FaithfulnessStrict()
    assert isinstance(zh.nli_statements_prompt, ZhNLIPrompt)
    assert type(strict.nli_statements_prompt) is NLIStatementPrompt
    # both decompose with the zh statement prompt (shared decomposition, two judging standards)
    assert isinstance(zh.statement_generator_prompt, ZhStatementGeneratorPrompt)
    assert isinstance(strict.statement_generator_prompt, ZhStatementGeneratorPrompt)


def test_log_key_separates_identical_qa_with_different_contexts():
    assert log_key("q", "a", ["c1"]) != log_key("q", "a", ["c2"])
    assert log_key("q", "a", ["c1"]) == log_key("q", "a", ["c1"])


def test_statement_cache_dedupes_concurrent_requests():
    cache = StatementCache()
    calls = 0

    async def make():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return ["s1", "s2"]

    async def run():
        return await asyncio.gather(cache.get_or_create("k", make), cache.get_or_create("k", make))

    a, b = asyncio.run(run())
    assert a == b == ["s1", "s2"]
    assert calls == 1


def test_statement_cache_survives_consumer_cancellation_when_sibling_waits():
    """RAGAS per-job timeout cancels one consumer; the sibling already waiting still gets the shared result."""
    cache = StatementCache()
    calls = 0

    async def make():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return ["s"]

    async def run():
        first = asyncio.ensure_future(cache.get_or_create("k", make))
        second = asyncio.ensure_future(cache.get_or_create("k", make))
        await asyncio.sleep(0.01)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await second

    assert asyncio.run(run()) == ["s"]
    assert calls == 1


def test_statement_cache_cancels_orphaned_producer_when_last_waiter_leaves():
    """Sole consumer timed out -> the producer is cancelled too (frees a serialized judge) and a later caller regenerates."""
    cache = StatementCache()
    calls = 0
    producer_cancelled = False

    async def make():
        nonlocal calls, producer_cancelled
        calls += 1
        try:
            await asyncio.sleep(0.5)
            return ["s"]
        except asyncio.CancelledError:
            producer_cancelled = True
            raise

    async def run():
        first = asyncio.ensure_future(cache.get_or_create("k", make))
        await asyncio.sleep(0.01)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.sleep(0.01)
        assert producer_cancelled and cache.size() == 0
        return await cache.get_or_create("k", make)

    assert asyncio.run(run()) == ["s"]
    assert calls == 2


def test_statement_cache_evicts_failed_producer_and_retries():
    cache = StatementCache()
    calls = 0

    async def make():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("judge down")
        return ["ok"]

    async def run():
        with pytest.raises(RuntimeError):
            await cache.get_or_create("k", make)
        return await cache.get_or_create("k", make)

    assert asyncio.run(run()) == ["ok"]
    assert calls == 2


def test_statement_cache_reset_forgets_entries():
    cache = StatementCache()

    async def make():
        return ["x"]

    asyncio.run(cache.get_or_create("k", make))
    cache.reset()
    assert cache.size() == 0


def test_verdict_log_merges_zh_and_strict_by_statement():
    verdict_log.reset()
    verdict_log.record("faithfulness", ("q", "a"), [("s1", 1, "ok"), ("s2", 0, "no")])
    verdict_log.record("faithfulness_strict", ("q", "a"), [("s1", 1, "ok!"), ("s2", 1, "fine")])
    entries = verdict_log.entries(("q", "a"))
    assert entries == [
        {"statement": "s1", "verdict": 1, "reason": "ok", "strict_verdict": 1, "strict_reason": "ok!"},
        {"statement": "s2", "verdict": 0, "reason": "no", "strict_verdict": 1, "strict_reason": "fine"},
    ]


def test_verdict_log_positional_fallback_only_for_rewritten_text():
    verdict_log.reset()
    verdict_log.record("faithfulness", "k", [("s1", 1, "a"), ("s2", 0, "b")])
    # strict rewrote s2 -> "s2'" at the same index: matched positionally
    verdict_log.record("faithfulness_strict", "k", [("s1", 1, "a!"), ("s2'", 0, "b!")])
    e = verdict_log.entries("k")
    assert (e[1]["strict_verdict"], e[1]["strict_reason"]) == (0, "b!")
    # strict returned s1 twice: the duplicate must not be attributed to s2
    verdict_log.record("faithfulness_strict", "k", [("s1", 1, "a!"), ("s1", 1, "dup")])
    e = verdict_log.entries("k")
    assert (e[1]["strict_verdict"], e[1]["strict_reason"]) == (None, None)


def test_verdict_log_appends_unmatched_strict_verdicts():
    """A strict verdict the merge cannot attribute is kept, so the strict count equals what was scored."""
    verdict_log.reset()
    verdict_log.record("faithfulness", "k", [("s1", 1, "a"), ("s2", 1, "b")])
    verdict_log.record("faithfulness_strict", "k", [("s1", 1, "a!"), ("x", 0, "no x"), ("y", 0, "no y")])
    e = verdict_log.entries("k")
    assert [(d["statement"], d["verdict"], d["strict_verdict"]) for d in e] == [
        ("s1", 1, 1), ("s2", 1, None), ("x", None, 0), ("y", None, 0)]
    assert build_faithfulness_rationale(e, "strict_verdict", "strict_reason") == (
        "1/3 statements supported | [0] x || no x | [0] y || no y")
    assert build_faithfulness_rationale(e, "verdict", "reason") == "2/2 statements supported"


def test_verdict_log_strict_only():
    verdict_log.reset()
    verdict_log.record("faithfulness_strict", "k", [("s1", 0, "no")])
    assert verdict_log.entries("k") == [
        {"statement": "s1", "verdict": None, "reason": None, "strict_verdict": 0, "strict_reason": "no"}]


def test_verdict_log_unknown_key_is_empty():
    verdict_log.reset()
    assert verdict_log.entries(("nope", "x")) == []


def test_rationale_counts_support_and_lists_only_failures():
    entries = [
        {"statement": "s1", "verdict": 1, "reason": "ok", "strict_verdict": 0, "strict_reason": "no header"},
        {"statement": "s2", "verdict": 0, "reason": "wrong person", "strict_verdict": 0, "strict_reason": "wrong person"},
        {"statement": "s3", "verdict": 1, "reason": "fine", "strict_verdict": 1, "strict_reason": "fine"},
    ]
    assert build_faithfulness_rationale(entries, "verdict", "reason") == (
        "2/3 statements supported | [0] s2 || wrong person"
    )
    assert build_faithfulness_rationale(entries, "strict_verdict", "strict_reason") == (
        "1/3 statements supported | [0] s1 || no header | [0] s2 || wrong person"
    )


def test_rationale_is_empty_when_that_judge_did_not_run():
    entries = [{"statement": "s1", "verdict": 1, "reason": "ok", "strict_verdict": None, "strict_reason": None}]
    assert build_faithfulness_rationale(entries, "strict_verdict", "strict_reason") == ""
    assert build_faithfulness_rationale(entries, "verdict", "reason") == "1/1 statements supported"
    assert build_faithfulness_rationale([], "verdict", "reason") == ""


@pytest.mark.parametrize("cls", [FaithfulnessZh, FaithfulnessStrict])
def test_metrics_share_one_decomposition_and_log_verdicts(cls, monkeypatch):
    """Both metrics run on one row: statements generated once, verdicts logged per metric."""
    from src.metrics import faithfulness_zh as mod
    from ragas.metrics._faithfulness import (
        NLIStatementOutput, NLIStatementPrompt, StatementFaithfulnessAnswer, StatementGeneratorOutput,
    )

    mod.statement_cache.reset()
    verdict_log.reset()
    gen_calls = {"n": 0}

    async def fake_statements(self, *, llm, data, callbacks=None):
        gen_calls["n"] += 1
        return StatementGeneratorOutput(statements=["耶穌愛世人", "保羅到了羅馬"])

    async def fake_nli(self, *, llm, data, callbacks=None):
        assert data.statements == ["耶穌愛世人", "保羅到了羅馬"]
        return NLIStatementOutput(statements=[
            StatementFaithfulnessAnswer(statement="耶穌愛世人", reason="經文明載", verdict=1),
            StatementFaithfulnessAnswer(statement="保羅到了羅馬", reason="未提及", verdict=0),
        ])

    monkeypatch.setattr(ZhStatementGeneratorPrompt, "generate", fake_statements)
    monkeypatch.setattr(ZhNLIPrompt, "generate", fake_nli)
    monkeypatch.setattr(NLIStatementPrompt, "generate", fake_nli)

    zh, strict = FaithfulnessZh(), FaithfulnessStrict()
    zh.llm = strict.llm = object()  # assert-only in _ascore
    row = {"user_input": "q", "response": "a", "retrieved_contexts": ["[1] c"]}

    async def run():
        return await asyncio.gather(zh._ascore(row, None), strict._ascore(row, None))

    s_zh, s_strict = asyncio.run(run())
    assert s_zh == 0.5 and s_strict == 0.5
    assert gen_calls["n"] == 1
    entries = verdict_log.entries(log_key("q", "a", ["[1] c"]))
    assert [e["statement"] for e in entries] == ["耶穌愛世人", "保羅到了羅馬"]
    assert entries[1]["verdict"] == 0 and entries[1]["strict_verdict"] == 0


def test_zh_nli_context_includes_question_strict_does_not(monkeypatch):
    from src.metrics import faithfulness_zh as mod
    from ragas.metrics._faithfulness import NLIStatementOutput, NLIStatementPrompt, StatementFaithfulnessAnswer

    seen = {}

    async def fake_nli(self, *, llm, data, callbacks=None):
        seen[type(self).__name__] = data.context
        return NLIStatementOutput(statements=[StatementFaithfulnessAnswer(statement="s", reason="r", verdict=1)])

    monkeypatch.setattr(ZhNLIPrompt, "generate", fake_nli)
    monkeypatch.setattr(NLIStatementPrompt, "generate", fake_nli)
    zh, strict = FaithfulnessZh(), FaithfulnessStrict()
    zh.llm = strict.llm = object()
    row = {"user_input": "問題?", "response": "a", "retrieved_contexts": ["[1] c", "[2] d"]}
    asyncio.run(zh._create_verdicts(row, ["s"], None))
    asyncio.run(strict._create_verdicts(row, ["s"], None))
    assert seen["ZhNLIPrompt"].startswith("【使用者問題】問題?")
    assert seen["NLIStatementPrompt"] == "[1] c\n\n[2] d"
    mod.statement_cache.reset()


def test_verdict_log_pairs_duplicate_statement_texts_positionally():
    verdict_log.reset()
    verdict_log.record("faithfulness", "k", [("dup", 1, "a"), ("dup", 0, "b")])
    verdict_log.record("faithfulness_strict", "k", [("dup", 1, "a!"), ("dup", 0, "b!")])
    e = verdict_log.entries("k")
    assert [(d["verdict"], d["strict_verdict"], d["strict_reason"]) for d in e] == [(1, 1, "a!"), (0, 0, "b!")]
    assert len(e) == 2


def test_statement_cache_reset_mid_flight_does_not_touch_fresh_future():
    """A stale waiter finishing after reset() must not evict or mis-count the fresh producer."""
    cache = StatementCache()

    async def slow():
        await asyncio.sleep(0.05)
        return ["old"]

    async def fresh():
        await asyncio.sleep(0.05)
        return ["new"]

    async def run():
        stale = asyncio.ensure_future(cache.get_or_create("k", slow))
        await asyncio.sleep(0.01)
        cache.reset()
        b = asyncio.ensure_future(cache.get_or_create("k", fresh))
        c = asyncio.ensure_future(cache.get_or_create("k", fresh))
        await asyncio.sleep(0.01)
        stale.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stale
        b.cancel()
        with pytest.raises(asyncio.CancelledError):
            await b
        return await c  # still one waiter on the fresh future: must resolve, not be cancelled

    assert asyncio.run(run()) == ["new"]
