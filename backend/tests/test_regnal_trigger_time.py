"""The trigger's worst case within the request's 500 characters: no cue pattern backtracks.

An early draft of the 2026-10-19 relaxation repeated a part that could match empty
(王位(…|[,，、\\s]*)*): 王位 and a run of commas backtracked exponentially (24 commas took 0.9 s,
30 would take minutes). Here every CJK literal of trigger.py's code (each run of CJK characters,
and each character alone, since 往(?:前|後) holds no literal 往前) follows a chain name and is
followed by one separator, or by itself, repeated to 500 characters (QueryRequest.question's
max_length) and a character no cue ends on. A lookahead reached only after several tokens
(之後兩任 then a run of commas) is not reached that way, so every prefix of an example of each
cue alternative is run the same way too. ``trigger`` and ``first_cue`` must stay under LIMIT_S,
and SIGALRM turns a hang into a failure.
"""

from __future__ import annotations

import re
import signal
import time
from pathlib import Path

import pytest

from utils.regnal import trigger as T

LIMIT_S = 0.1           # the slowest case takes about 3 ms
MAX_CHARS = 500         # models.request.QueryRequest.question
NAMES = ("耶羅波安", "亞哈", "約蘭", "暗利", "約坦", "亞撒")
FILLS = ("，", "、", ",", " ", "的", "了", "再")
CODE = Path(T.__file__).read_text(encoding="utf-8").split('"""', 2)[2]
RUNS = re.findall(r"[\u4e00-\u9fff]+", CODE)
# one question per cue alternative, old and added (each takes the card on NAMES)
EXAMPLES = ("亞哈之後的第四位王是誰", "亞哈往前數第三位王是誰", "接續亞哈作王的是誰", "亞哈死後繼位的是誰",
            "亞哈之後再往下數第三個王是誰", "亞哈往前倒推兩位是誰", "亞哈之後，隔兩任的王是誰", "亞哈之後兩任王是誰",
            "亞哈之前兩代坐以色列王位的是誰", "亞哈的下一任是誰", "亞哈的上上任是誰", "亞哈的繼任者是誰",
            "亞哈死後，接著作王的是誰", "從暗利到亞哈王位交接幾次", "暗利和亞哈相隔幾代", "從暗利到亞哈，中間換手了幾次",
            "從暗利到亞哈，王位一共傳了幾次", "從暗利到亞哈，換了幾次王", "從暗利到亞哈經歷了幾次更迭",
            "亞哈之後第二個篡位的是誰", "亞哈之後，第四個靠謀反登基的是誰", "亞哈以後，殺王奪位的人裡面，第二個是誰",
            "約坦出生時在位的王是誰", "約坦出生那一年，誰在做王", "約坦出生於哪一位王在位期間", "約坦是在哪位王在位時出生的")
LITERALS = sorted(set(RUNS) | set("".join(RUNS)))


def _alarm(_sig, _frame):
    raise TimeoutError


def _took(q: str) -> float:
    """Seconds trigger and first_cue take on ``q``; inf past 2 s (SIGALRM)."""
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(2)
    try:
        t = time.perf_counter()
        T.trigger(q, NAMES)
        T.first_cue(q, T.find_names(q, NAMES))
        return time.perf_counter() - t
    except TimeoutError:
        return float("inf")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _cases():
    for lit in LITERALS:
        for fill in (*FILLS, lit):
            yield (NAMES[1] + lit + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"
    for ex in EXAMPLES:
        for k in range(1, len(ex) + 1):
            for fill in FILLS:
                yield (ex[:k] + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"


def test_every_example_takes_the_card():
    assert [ex for ex in EXAMPLES if not T.trigger(ex, NAMES).fired] == []


def test_the_literals_are_read_from_the_code():
    assert {"王位", "出生", "謀反", "交接", "往", "前"} <= set(LITERALS) and len(LITERALS) > 300


def test_no_cue_backtracks_on_a_repeated_separator_or_literal():
    slow = [(q[:12], t) for q in _cases() if (t := _took(q)) > LIMIT_S]
    assert not slow, slow[:5]


@pytest.mark.parametrize("fill", ["，", " "])
def test_the_early_drafts_case_is_fast(fill):
    assert _took("從亞哈到約蘭王位" + fill * 480 + "x") < LIMIT_S
