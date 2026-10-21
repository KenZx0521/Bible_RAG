"""The GEN rule's worst case within the request's 500 characters (plan 2026-10-21 A2 (6)).

Once the GEN card is on, utils.gencard's rule reads every question the regnal trigger does not take.
Every CJK literal of its code (each run of CJK characters, and each character alone) follows a chain
name and is followed by one separator, or by itself, repeated to 500 characters (QueryRequest.question's
max_length) and a character no cue ends on; each chain name, alone and in a marker phrase, is repeated
the same way; and every prefix of a question that takes the card is followed by a run of separators.
``trigger`` and ``card`` together must stay under LIMIT_S on gen_fakes' layer and, when the store is
mounted, on the confirmation set's layer (its names read from it at run time); SIGALRM turns a hang
into a failure.
"""

from __future__ import annotations

import re
import signal
import time
from pathlib import Path

import pytest

import gen_fakes
from utils import gen_card
from utils.gencard import card, trigger

LIMIT_S = 0.1           # the slowest case takes well under 1 ms
MAX_CHARS = 500         # models.request.QueryRequest.question
FILLS = ("，", "、", ",", " ", "的", "了", "又", "(")
PKG = Path(gen_card.__file__).with_name("gencard")
CODE = "".join(p.read_text(encoding="utf-8").split('"""', 2)[2] for p in sorted(PKG.glob("*.py")))
RUNS = re.findall(r"[一-鿿]+", CODE)
LITERALS = sorted(set(RUNS) | set("".join(RUNS)))
STORE = Path("/mnt/ollama-data/bible_rag_store/reports")
STORE_FILES = (STORE / "arith_stage0_20261020/gen_layer.json", STORE / "gen_confirm_20261020/gen_names.json")


@pytest.fixture(scope="module", params=["fakes", "store"])
def layer(request):
    if request.param == "fakes":
        return gen_card.parse_files(*gen_fakes.files())
    if not all(p.is_file() for p in STORE_FILES):
        pytest.skip("the confirmation set's GEN files are not in the store")
    return gen_card.parse_files(*(p.read_bytes() for p in STORE_FILES))


def _example(L) -> str:
    """A question that takes the card: the head of chapter 5's age at the birth of his grandson."""
    head, _son, grandson = L.chains[5][:3]
    return f"{L.name[head]}幾歲時{L.name[grandson]}出生"


def _alarm(_sig, _frame):
    raise TimeoutError


def _took(L, q: str) -> float:
    """Seconds trigger and card take on ``q``; inf past 2 s (SIGALRM)."""
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(2)
    try:
        t = time.perf_counter()
        trigger(q, L)
        card(q, L)
        return time.perf_counter() - t
    except TimeoutError:
        return float("inf")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _cases(L):
    first = L.name[L.order[0]]
    for lit in LITERALS:
        for fill in (*FILLS, lit):
            yield (first + lit + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"
    for n in L.name.values():
        for unit in (n, f"{n}的兒子", f"({n}的父親)"):
            yield (unit * MAX_CHARS)[:MAX_CHARS]
    ex = _example(L)
    for k in range(1, len(ex) + 1):
        for fill in FILLS:
            yield (ex[:k] + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"


def test_the_example_takes_the_card(layer):
    fired = trigger(_example(layer), layer).fired      # bound: unbound, a failure prints question and layer
    assert fired


def test_the_literals_are_read_from_the_code():
    assert {"出生", "去世", "幾歲", "的父親", "又", "活"} <= set(LITERALS) and len(LITERALS) > 200


def test_no_rule_step_backtracks_on_a_repeated_separator_or_literal(layer):
    slow = [(i, t) for i, q in enumerate(_cases(layer)) if (t := _took(layer, q)) > LIMIT_S]
    assert not slow, slow[:5]
