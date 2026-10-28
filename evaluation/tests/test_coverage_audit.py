"""answer_coverage audit (2026-10-28 P0): per-point verdicts kept, no silent 'missing' fill.

A reply that leaves a point without a legal verdict (no index, index out of range, a
verdict outside covered/partial/missing) or cannot be parsed is asked once more; still
incomplete, the question's coverage is invalid and the judge's raw reply is kept. A
complete, legal reply scores exactly as before. The judge LLM is stubbed.
"""

import asyncio
import itertools
import json

import pytest

from src.metrics import coverage_eval as ce
from src.models import EvalSample, GroundTruthItem

POINTS = ["神創造天地", "地是空虛混沌", "神說要有光"]
SCORE = {"covered": 1.0, "partial": 0.5, "missing": 0.0}


def _sample(points=POINTS, answer="起初神創造天地。", qid="Q1"):
    gt = GroundTruthItem(question_id=qid, question="創世記第一章說什麼？", question_type="T",
                         book_name="創世記", expected_answer_points=list(points))
    return EvalSample(question_id=qid, question=gt.question, question_type="T",
                      ground_truth=gt, rag_answer=answer)


def _reply(verdicts, start=1, **extra):
    items = [{"index": i, "verdict": v, "reason": f"r{i}"} for i, v in enumerate(verdicts, start)]
    return json.dumps({"verdicts": items, **extra}, ensure_ascii=False)


def _judge(monkeypatch, *replies):
    """judge_completion answering ``replies`` in turn (an exception is raised); records calls."""
    calls = []

    async def judge(prompt, **kwargs):
        calls.append(prompt)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(ce, "judge_completion", judge)
    return calls


def _run(sample):
    metrics, details = ce.compute_coverage([sample])
    return metrics[sample.question_id][0], details[sample.question_id]


# --- complete, legal replies: same score as before, one call --------------------------------

def _old_score(verdicts):
    """The pre-2026-10-28 formula on a complete reply."""
    return round(sum(SCORE[v] for v in verdicts) / len(verdicts), 4)


@pytest.mark.parametrize("verdicts", list(itertools.product(SCORE, repeat=3)))
def test_a_complete_reply_scores_exactly_as_before(monkeypatch, verdicts):
    calls = _judge(monkeypatch, _reply(verdicts))

    metric, detail = _run(_sample())

    assert metric.valid and metric.value == _old_score(verdicts)
    assert len(calls) == 1 and detail.attempts == 1 and detail.error is None


def test_points_are_kept_with_verdict_and_reason(monkeypatch):
    _judge(monkeypatch, _reply(["covered", "partial", "missing"]))

    _, detail = _run(_sample())

    assert detail.rationale_fields()["coverage_points"] == [
        {"index": 1, "point": POINTS[0], "verdict": "covered", "reason": "r1"},
        {"index": 2, "point": POINTS[1], "verdict": "partial", "reason": "r2"},
        {"index": 3, "point": POINTS[2], "verdict": "missing", "reason": "r3"}]
    assert detail.raw is None        # a valid score keeps no raw reply


def test_index_order_is_honoured(monkeypatch):
    reply = json.dumps({"verdicts": [{"index": 3, "verdict": "missing"},
                                     {"index": 1, "verdict": "covered"},
                                     {"index": 2, "verdict": "partial"}]})
    _judge(monkeypatch, reply)

    metric, detail = _run(_sample())

    assert metric.value == 0.5
    assert [p["verdict"] for p in detail.points] == ["covered", "partial", "missing"]


def test_an_extra_out_of_range_item_does_not_spoil_a_complete_reply(monkeypatch):
    calls = _judge(monkeypatch, _reply(["covered", "covered", "partial", "covered"]))

    metric, _ = _run(_sample())

    assert metric.valid and metric.value == round(2.5 / 3, 4) and len(calls) == 1


def test_a_salvaged_complete_reply_scores_as_before(monkeypatch):
    """Broken JSON (an unescaped quote in a reason) still yields every verdict positionally."""
    broken = ('{"verdicts": [{"index": 1, "verdict": "covered", "reason": "他說"好""}, '
              '{"index": 2, "verdict": "partial", "reason": "x"}, '
              '{"index": 3, "verdict": "missing", "reason": "y"}]}')
    calls = _judge(monkeypatch, broken)

    metric, detail = _run(_sample())

    assert metric.valid and metric.value == 0.5 and len(calls) == 1
    assert [p["verdict"] for p in detail.points] == ["covered", "partial", "missing"]


# --- incomplete or unparseable: one retry, then invalid with the raw reply ------------------

@pytest.mark.parametrize("bad", [
    _reply(["covered", "covered"]),                                         # point 3 absent
    json.dumps({"verdicts": [{"verdict": "covered"}, {"index": 2, "verdict": "covered"},
                             {"index": 3, "verdict": "covered"}]}),         # no index
    _reply(["covered", "covered", "covered"], start=2),                     # 2..4: 1 absent, 4 out of range
    _reply(["covered", "yes", "covered"]),                                  # illegal verdict
    json.dumps({"verdicts": [{"index": "one", "verdict": "covered"}, {"index": 2, "verdict": "covered"},
                             {"index": 3, "verdict": "covered"}]}),         # index not a number
], ids=["point_absent", "no_index", "out_of_range", "illegal_verdict", "index_not_int"])
def test_an_incomplete_reply_is_retried_once_then_scored(monkeypatch, bad):
    calls = _judge(monkeypatch, bad, _reply(["covered", "partial", "covered"]))

    metric, detail = _run(_sample())

    assert len(calls) == 2 and calls[1].startswith(calls[0])     # the retry adds what was wrong
    assert metric.valid and metric.value == round(2.5 / 3, 4)
    assert detail.attempts == 2 and detail.error is None


def test_incomplete_twice_is_invalid_with_reason_points_and_raw(monkeypatch):
    bad = _reply(["covered", "covered"])
    _judge(monkeypatch, bad, bad)

    metric, detail = _run(_sample())

    assert not metric.valid
    fields = detail.rationale_fields()
    assert fields["coverage_error"].startswith("incomplete_verdicts")
    assert "3" in fields["coverage_error"]                  # names the point left without one
    assert fields["coverage_raw"] == bad and fields["coverage_attempts"] == 2
    assert [p["verdict"] for p in fields["coverage_points"]] == ["covered", "covered", None]


def test_unparseable_twice_is_invalid_and_the_raw_reply_is_truncated(monkeypatch):
    junk = "我無法判斷。" * 3000
    _judge(monkeypatch, junk, junk)

    metric, detail = _run(_sample())

    assert not metric.valid and detail.error == "unparseable" and detail.attempts == 2
    assert detail.raw == junk[:8000]
    assert [p["verdict"] for p in detail.points] == [None, None, None]


def test_a_judge_exception_is_invalid_without_retry_and_keeps_the_message(monkeypatch):
    calls = _judge(monkeypatch, RuntimeError("Claude judge returned no text (stop_reason=max_tokens)"))

    metric, detail = _run(_sample())

    assert not metric.valid and len(calls) == 1 and detail.attempts == 1
    assert detail.error.startswith("judge_error: RuntimeError: Claude judge returned no text")


def test_an_exception_on_the_retry_keeps_the_first_reply(monkeypatch):
    bad = _reply(["covered"])
    _judge(monkeypatch, bad, TimeoutError("read timed out"))

    metric, detail = _run(_sample())

    assert not metric.valid and detail.attempts == 2
    assert detail.error.startswith("judge_error: TimeoutError") and detail.raw == bad


# --- not judged ----------------------------------------------------------------------------

def test_an_empty_answer_is_a_valid_zero_without_a_judge_call(monkeypatch):
    calls = _judge(monkeypatch, AssertionError("no judge for an empty answer"))

    metric, detail = _run(_sample(answer="  "))

    assert metric.valid and metric.value == 0.0 and calls == []
    assert (detail.attempts, detail.error, detail.points) == (0, None, ())


def test_no_expected_points_is_invalid_and_says_so(monkeypatch):
    _judge(monkeypatch, AssertionError("no judge without points"))

    metric, detail = _run(_sample(points=[]))

    assert not metric.valid and detail.error == "no_expected_points"


# --- shapes other callers rely on ----------------------------------------------------------

def test_compute_coverage_metrics_keeps_its_shape(monkeypatch):
    _judge(monkeypatch, _reply(["covered"] * 3))

    out = ce.compute_coverage_metrics([_sample()])

    assert list(out) == ["Q1"] and out["Q1"][0].name == "answer_coverage" and out["Q1"][0].value == 1.0


def test_score_one_keeps_its_shape_for_the_frozen_probe(monkeypatch):
    """experiments/2026-10-03_event_registry/probe_coverage.py: ``_, m = await _score_one(s, sem)``."""
    _judge(monkeypatch, _reply(["covered", "missing", "missing"]))

    qid, metric = asyncio.run(ce._score_one(_sample(), asyncio.Semaphore(1)))

    assert qid == "Q1" and metric.value == round(1 / 3, 4) and metric.valid


def test_the_judged_log_line_keeps_the_frozen_collectors_shape(monkeypatch, caplog):
    """experiments/2026-10-15_book_anchor/ba_cov.py reads (qid, score, {index: verdict})."""
    _judge(monkeypatch, _reply(["covered", "partial", "missing"]))

    with caplog.at_level("INFO", logger="src.metrics.coverage_eval"):
        _run(_sample())

    rec = next(r for r in caplog.records if r.msg.startswith("[Coverage] %s => "))
    assert rec.args == ("Q1", 0.5, {1: "covered", 2: "partial", 3: "missing"})


# --- review fixes (2026-10-28): defects of a scored reply are kept, salvage honours index ----

TWO = POINTS[:2]


def test_a_clean_reply_records_no_problem_and_no_raw(monkeypatch):
    _judge(monkeypatch, _reply(["covered", "partial", "missing"]))

    _, detail = _run(_sample())

    fields = detail.rationale_fields()
    assert (fields["coverage_problems"], fields["coverage_salvaged"]) == ([], False)
    assert fields["coverage_raw"] is None and fields["coverage_retry"] is None


def test_salvage_pairs_each_verdict_with_its_own_index(monkeypatch):
    """Broken JSON, index 2 first: point 2 gets 'missing', point 1 'covered' (not by position)."""
    broken = ('{"verdicts":[{"index":2,"verdict":"missing","reason":"他說"不"在"},'
              '{"index":1,"verdict":"covered","reason":"ok"}]}')
    _judge(monkeypatch, broken)

    metric, detail = _run(_sample(points=TWO))

    assert metric.valid and metric.value == 0.5
    assert [p["verdict"] for p in detail.points] == ["covered", "missing"]
    fields = detail.rationale_fields()
    assert fields["coverage_salvaged"] is True and fields["coverage_problems"]
    assert fields["coverage_raw"] == broken             # a scored reply with defects keeps its raw text


def test_salvage_reads_a_verdict_first_item_order(monkeypatch):
    broken = ('{"verdicts":[{"verdict":"partial","index":2,"reason":"他說"不"在"},'
              '{"verdict":"covered","index":1,"reason":"ok"}]}')
    _judge(monkeypatch, broken)

    metric, detail = _run(_sample(points=TWO))

    assert metric.valid and [p["verdict"] for p in detail.points] == ["covered", "partial"]


def test_a_repeated_index_is_scored_last_wins_and_the_defect_is_kept(monkeypatch):
    reply = json.dumps({"verdicts": [{"index": 1, "verdict": "covered"}, {"index": 1, "verdict": "missing"},
                                     {"index": 2, "verdict": "covered"}]})
    _judge(monkeypatch, reply)

    metric, detail = _run(_sample(points=TWO))

    assert metric.valid and metric.value == 0.5
    fields = detail.rationale_fields()
    assert any("index 1 given twice" in p for p in fields["coverage_problems"])
    assert fields["coverage_raw"] == reply and fields["coverage_salvaged"] is False


@pytest.mark.parametrize("reply", [
    json.dumps({"verdicts": [{"verdict": "covered", "reason": "a"}, {"verdict": "missing", "reason": "b"}]}),
    '{"verdicts":[{"verdict":"covered","reason":"他說"好""},{"verdict":"missing","reason":"b"}]}',
], ids=["valid_json", "broken_json"])
def test_verdicts_without_index_are_incomplete_whether_or_not_the_json_is_valid(monkeypatch, reply):
    calls = _judge(monkeypatch, reply)

    metric, detail = _run(_sample(points=TWO))

    assert not metric.valid and len(calls) == 2
    assert detail.error.startswith("incomplete_verdicts")
    assert [p["verdict"] for p in detail.points] == [None, None]


@pytest.mark.parametrize("index", ["1e999", "Infinity", "-Infinity", "NaN", "1.9", "true", '"²"'])
def test_an_index_that_is_not_a_whole_number_fills_no_point_and_never_raises(index):
    text = '{"verdicts":[{"index":%s,"verdict":"covered"},{"index":2,"verdict":"covered"}]}' % index

    parsed = ce._read_verdicts(text, 2)

    assert parsed.verdicts == (None, "covered") and not parsed.complete
    assert any("not a whole number" in p for p in parsed.problems)


@pytest.mark.parametrize("index", ["1", '"1"', "1.0"])
def test_a_whole_number_index_is_read(index):
    text = '{"verdicts":[{"index":%s,"verdict":"covered"},{"index":2,"verdict":"missing"}]}' % index

    assert ce._read_verdicts(text, 2).verdicts == ("covered", "missing")


def test_an_unexpected_error_for_one_question_spoils_only_that_question(monkeypatch):
    _judge(monkeypatch, _reply(["covered"] * 3))
    real = ce._read_verdicts

    def read(text, n):
        if n == 2:
            raise OverflowError("cannot convert float infinity to integer")
        return real(text, n)

    monkeypatch.setattr(ce, "_read_verdicts", read)

    metrics, details = ce.compute_coverage([_sample(qid="Q1"), _sample(points=TWO, qid="Q2")])

    assert metrics["Q1"][0].valid and metrics["Q1"][0].value == 1.0
    assert not metrics["Q2"][0].valid
    assert details["Q2"].error.startswith("internal_error: OverflowError")


def test_the_retry_tells_the_judge_what_was_wrong_and_records_it(monkeypatch):
    first = _reply(["covered", "covered"])
    calls = _judge(monkeypatch, first, _reply(["covered", "partial", "covered"]))

    metric, detail = _run(_sample())

    assert metric.valid and len(calls) == 2
    assert calls[1] != calls[0] and calls[1].startswith(calls[0])
    assert "3" in calls[1][len(calls[0]):]               # names the point left without a verdict
    retry = detail.rationale_fields()["coverage_retry"]
    assert retry["why"].startswith("incomplete_verdicts") and retry["same_reply"] is False


def test_a_retry_that_returns_the_same_reply_says_so(monkeypatch):
    bad = _reply(["covered"])
    _judge(monkeypatch, bad, bad)

    _, detail = _run(_sample())

    assert detail.rationale_fields()["coverage_retry"] == {
        "why": ce._why_retry(ce._read_verdicts(bad, 3)), "same_reply": True}


def test_an_unparseable_reply_retry_asks_for_json(monkeypatch):
    calls = _judge(monkeypatch, "我無法判斷。", _reply(["covered"] * 3))

    _, detail = _run(_sample())

    assert "JSON" in calls[1][len(calls[0]):]
    assert detail.rationale_fields()["coverage_retry"] == {"why": "unparseable", "same_reply": False}


# --- _parse_verdicts keeps its pre-2026-10-28 shape for the archived re-judge scripts --------

@pytest.mark.parametrize("text, n, expected", [
    ('{"verdicts":[{"index":1,"verdict":"covered"},{"index":2,"verdict":"partial"}]}', 2,
     ["covered", "partial"]),
    ('{"verdicts":[{"index":1,"verdict":"covered"}]}', 3, ["covered", "missing", "missing"]),
    ('{"verdicts":[{"verdict":"partial"},{"verdict":"covered"}]}', 2, ["partial", "covered"]),
    ('{"verdicts":[{"index":2,"verdict":"missing","reason":"他說"不"在"},'
     '{"index":1,"verdict":"covered"}]}', 2, ["missing", "covered"]),
    ("我無法判斷。", 2, None),
], ids=["complete", "short_filled_missing", "no_index_by_position", "salvage_by_position", "unparseable"])
def test_legacy_parse_verdicts_returns_the_old_list(text, n, expected):
    """store reports/analysis_20261010/verify/*: sum(_VERDICT_SCORE[x] for x in v) / len(v)."""
    assert ce._parse_verdicts(text, n) == expected
