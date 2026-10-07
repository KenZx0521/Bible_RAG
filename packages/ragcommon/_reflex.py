"""Lexer for Chinese scripture references: folding, Chinese numerals, tokens.

``normalize`` maps every variant separator to one ASCII form and keeps the
string length, so token offsets index the caller's original text too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

NUM, COLON, DASH, CHAP, VERSE, DI, SUFFIX, COMMA, SEMI = (
    "NUM", "COLON", "DASH", "CHAP", "VERSE", "DI", "SUFFIX", "COMMA", "SEMI",
)
BOOK, AMBIGUOUS = "BOOK", "AMBIGUOUS"

_FOLD = str.maketrans({
    **{chr(0xFF10 + d): str(d) for d in range(10)},
    **dict.fromkeys("：‧·・･︰∶﹕", ":"),
    **dict.fromkeys("－–—―‒−﹣~～〜至到", "-"),
    **dict.fromkeys("，、﹐､", ","),
    **dict.fromkeys("；﹔", ";"),
    "ａ": "a", "ｂ": "b", "ｃ": "c", "　": " ",
})
_SIMPLE = {":": COLON, "-": DASH, ",": COMMA, ";": SEMI,
           "章": CHAP, "篇": CHAP, "節": VERSE, "第": DI}
_DIGITS = "0123456789"
_CN_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_CHARS = "".join(_CN_DIGIT) + "十百"


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    value: object = None   # int (None for a malformed Chinese numeral), marker char, or book name
    arabic: bool = True


def normalize(text: str) -> str:
    """Fold full-width digits and separator variants; length-preserving."""
    return text.translate(_FOLD)


def _nonzero_digit(text: str) -> int | None:
    value = _CN_DIGIT.get(text) if len(text) == 1 else None
    return value or None


def cn_value(text: str) -> int | None:
    """Value of a Chinese numeral up to 999 (十三, 二十, 一百零五, 一百十九); None if malformed."""
    total, rest = 0, text
    if "百" in rest:
        head, _, rest = rest.partition("百")
        hundreds = _nonzero_digit(head)
        if hundreds is None:
            return None
        total = hundreds * 100
        if rest[:1] in ("零", "〇"):
            unit = _nonzero_digit(rest[1:])
            return None if unit is None else total + unit
    if "十" in rest:
        head, _, rest = rest.partition("十")
        tens = 1 if head == "" else _nonzero_digit(head)
        if tens is None:
            return None
        total += tens * 10
    if rest:
        unit = _nonzero_digit(rest)
        if unit is None:
            return None
        total += unit
    return total or None


def _run_end(text: str, pos: int, chars: str) -> int:
    end = pos
    while end < len(text) and text[end] in chars:
        end += 1
    return end


def _suffix_ok(text: str, pos: int, tokens: list[Token]) -> bool:
    prev = tokens[-1] if tokens else None
    following = text[pos + 1:pos + 2]
    return (prev is not None and prev.kind == NUM and prev.end == pos
            and not (following.isascii() and following.isalpha()))


def _token_at(text: str, pos: int, tokens: list[Token]) -> Token | None:
    ch = text[pos]
    if ch in _DIGITS:
        end = _run_end(text, pos, _DIGITS)
        return Token(NUM, pos, end, int(text[pos:end]))
    if ch in CN_CHARS:
        end = _run_end(text, pos, CN_CHARS)
        return Token(NUM, pos, end, cn_value(text[pos:end]), arabic=False)
    if ch in _SIMPLE:
        return Token(_SIMPLE[ch], pos, pos + 1, ch)
    if ch in "abc" and _suffix_ok(text, pos, tokens):
        return Token(SUFFIX, pos, pos + 1, ch)
    return None


def tokenize(text: str, pos: int = 0,
             match_book: Callable[[str, int], Token | None] | None = None,
             ) -> tuple[tuple[Token, ...], int]:
    """Tokenize ``text`` (already normalized) from ``pos``.

    Stops at the first character that cannot belong to a reference and returns
    the tokens plus that stop position. Book names become tokens only when a
    ``match_book`` callback is given.
    """
    tokens: list[Token] = []
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        token = match_book(text, pos) if match_book else None
        token = token or _token_at(text, pos, tokens)
        if token is None:
            break
        tokens.append(token)
        pos = token.end
    return tuple(tokens), pos
