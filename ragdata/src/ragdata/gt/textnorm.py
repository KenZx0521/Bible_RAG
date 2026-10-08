"""Text helpers shared by the GT v2 build and G-GT.

Matching against the service text is done on Han characters only (``norm``):
GT answers punctuate freely, and the name separator ``‧``, dashes and digits are
not part of a quotation's wording. A clause is a maximal run between the
punctuation marks of ``CLAUSE_BREAKS`` (the audit's g03 splitter); a quote
clause is a clause inside 「」 or 『』 at any nesting depth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff]")
CLAUSE_BREAKS = "，。；：！？、「」『』（）()…—\\-\\s,.;:!?\"'“”‘’〔〕\\[\\]《》〈〉"
CLAUSE_RE = re.compile(f"[^{CLAUSE_BREAKS}]+")
QUOTE_PAIRS = {"「": "」", "『": "』"}
QUOTE_CLOSERS = frozenset(QUOTE_PAIRS.values())


class QuoteError(ValueError):
    """Quote marks that do not pair up."""


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


def norm(text: str) -> str:
    """The Han characters of ``text``, in order."""
    return "".join(HAN_RE.findall(text))


def clause_spans(text: str) -> tuple[Span, ...]:
    return tuple(Span(m.start(), m.end(), m.group()) for m in CLAUSE_RE.finditer(text))


def _quote_depths(text: str) -> list[int]:
    """Quote nesting depth of every character (marks themselves count as outside)."""
    stack: list[str] = []
    depths = []
    for i, ch in enumerate(text):
        if ch in QUOTE_PAIRS:
            depths.append(0)
            stack.append(QUOTE_PAIRS[ch])
        elif ch in QUOTE_CLOSERS:
            if not stack or stack.pop() != ch:
                raise QuoteError(f"unmatched {ch!r} at {i}: {text!r}")
            depths.append(0)
        else:
            depths.append(len(stack))
    if stack:
        raise QuoteError(f"unclosed quote: {text!r}")
    return depths


def quote_clause_spans(text: str) -> tuple[Span, ...]:
    """The clauses that lie inside quote marks."""
    depths = _quote_depths(text)
    return tuple(s for s in clause_spans(text) if depths[s.start] > 0)
