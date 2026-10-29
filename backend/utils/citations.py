"""Deterministic repair of block numbers written as chapter numbers (rewrite 2-C).

The generator sometimes cites passage block ``[N]`` as chapter N: block ``[3] 約翰福音
第14章 (15-21節)`` comes back as 「約翰福音 3:16」. A chapter citation is rewritten to
block N's chapter only when all of these hold:

- it names a book (``書 第N章第V節``, ``書 N:V``; an abbreviation counts for the
  colon form), or is a bare ``[N:V]`` in square brackets (other bare forms are
  left alone);
- (book, N) is no chapter of the passages, of the auxiliary card's evidence, or of
  the question;
- block N is that book (a bare citation: block N's book, unless the last book named
  before it is another), and it holds verse V.

Only the chapter digits change. Every passage is one chapter (design §2.23), so a
legitimate cross-chapter citation never matches.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from ragcommon import books, refs

_SPAN = re.compile(r"^(\d+)(?:-(\d+))?$")
_QUESTION_CHAPTER = re.compile(r"第\s*(\d+)\s*[章篇]|(\d+)\s*[:：]")


@lru_cache(maxsize=1)
def _names() -> tuple[dict[str, str], re.Pattern[str]]:
    """Written form -> book id, and the citation pattern (longest names first)."""
    names = books.default_books().names_longest_first()
    full = "|".join(re.escape(n.text) for n in names if not n.is_abbreviation)
    every = "|".join(re.escape(n.text) for n in names)
    pattern = re.compile(
        rf"(?P<b1>{full})\s*第?\s*(?P<c1>\d+)\s*[章篇](?:\s*第?\s*(?P<v1>\d+)\s*節)?"
        rf"|(?P<b2>{every})\s*(?P<c2>\d+)\s*[:：]\s*(?P<v2>\d+)"
        rf"|[\[［]\s*(?P<c3>\d+)\s*[:：]\s*(?P<v3>\d+)"
        rf"|(?P<bk>{full})")
    return {n.text: n.book_id for n in names}, pattern


def _blocks(sources: list[dict]) -> dict[int, tuple[str, int, tuple[int, int] | None]]:
    """Block number -> (book id, chapter, verse span) of each passage as the generator saw it."""
    out = {}
    for i, src in enumerate(sources, 1):
        if src.get("book_id") is None or src.get("chapter_num") is None:
            continue
        m = _SPAN.match(str(src.get("verse_range") or ""))
        span = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else None
        out[i] = (src["book_id"], int(src["chapter_num"]), span)
    return out


def _question_chapters(question: str) -> set[tuple[str, int]]:
    """Every (book, chapter) the question might name.

    Its references as ragcommon.refs reads them (chapter ranges, 「羅馬書5章」, Chinese
    numerals), plus its books times its 第N章 / N: numbers.
    """
    by_name, pattern = _names()
    named = {by_name[m.group(g)] for m in pattern.finditer(question)
             for g in ("b1", "b2", "bk") if m.group(g)}
    numbers = {int(a or b) for a, b in _QUESTION_CHAPTER.findall(question)}
    found = {(r.book_id, ch) for r in refs.find_refs(question).refs
             for ch in range(r.ch, r.ch_end + 1)}
    return found | {(b, n) for b in named for n in numbers}


def _evidence_chapters(evidence: Iterable[str]) -> set[tuple[str, int]]:
    """(book, chapter) of verse keys such as ``1ki.15.1``."""
    out = set()
    for key in evidence:
        parts = key.split(".")
        if len(parts) >= 2 and parts[1].isdigit():
            out.add((parts[0], int(parts[1])))
    return out


def fix_block_chapters(answer: str, sources: list[dict], question: str = "",
                       evidence: Iterable[str] = ()) -> str:
    """``answer`` with each citation of block N as chapter N given block N's chapter."""
    blocks = _blocks(sources)
    if not answer or not blocks:
        return answer
    by_name, pattern = _names()
    allowed = ({(b, ch) for b, ch, _ in blocks.values()} | _question_chapters(question)
               | _evidence_chapters(evidence))
    edits: list[tuple[int, int, str]] = []
    last: str | None = None
    for m in pattern.finditer(answer):
        if m.group("bk"):
            last = by_name[m.group("bk")]
            continue
        group = "1" if m.group("c1") else "2" if m.group("c2") else "3"
        n, verse = int(m.group("c" + group)), m.group("v" + group)
        named = by_name[m.group("b" + group)] if group != "3" else None
        last = named or last
        block = blocks.get(n)
        if block is None or verse is None:
            continue
        book, chapter, span = block
        if (named or last or book) != book:
            continue
        if (book, n) in allowed or span is None or not span[0] <= int(verse) <= span[1]:
            continue
        edits.append((m.start("c" + group), m.end("c" + group), str(chapter)))
    for start, end, text in reversed(edits):
        answer = answer[:start] + text + answer[end:]
    return answer
