"""Scripture references as a question words them.

A question is worded more loosely than the text ragcommon.refs is written for (GT
references, PDF notes): 《約翰福音》3:16, 約翰福音的第3章, 3.16, 3章和5章, 20章十誡. The wording
is put right here, before that parser reads it, because the parser and utils.verse_parser
are pinned (metric_version, the R2 freeze) and the build reads notes with the same parser.
Every character keeps its offset, so spans still index the question.

Each pattern runs on user input inside the event loop, so none may backtrack: adjacent
optional parts never share what they can match.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache

from ragcommon import _reflex as lx
from ragcommon import books, refs
from utils.verse_parser import FoundRefs, _backend_refs

_MISSPELT = {"創世紀": "創世記"}
_NUM = f"[0-9{lx.CN_CHARS}]+"
_DI = r"(?:第\s*)?"
# Words a number counts: 12門徒, 10災, 7封信, 5大講論; not 大衛, 福音, 封印, 種子.
_COUNT_WORDS = "門徒|使徒|支派|災|封(?!印)|大(?!衛|地|意|綱|家|概)|福(?!音|氣)|誡(?!命)|樣(?!式)|種(?!子)|項"
_COUNTED = re.compile(rf"\s*(?:{_COUNT_WORDS})")
# What a reference starts with, in folded text: a number list or range closed by a marker.
_CITED = rf"\s*{_DI}{_NUM}(?:\s*[,\-]\s*{_DI}{_NUM})*\s*(?:章|篇|節|:)"
# What may stand between a full book name and its reference.
_LINK = r"[》」』”\"]*(?:\s*(?:[中裡裏內]?的|之|[中裡裏內]))?"
# After a word such as 的 or 中, 七篇 with no verse after it counts psalms: 詩篇中七篇悔罪詩.
_COUNT_AFTER_LINK = re.compile(rf"\s*[{lx.CN_CHARS}]+\s*[章篇節](?!\s*{_DI}{_NUM}\s*(?:節|:))")
_OF_VERSE = re.compile(rf"(?<=[章篇])的(?!\s*[一兩]\s*節)(?=\s*{_DI}{_NUM}\s*節(?!經文))")
_AND = re.compile(rf"(?<=[章篇節0-9])\s*[和與及跟暨](?!\s*[一兩]\s*[章篇節])(?={_CITED})")
# A number right after 章 that is no verse: the 十 of 20章十誡, the 10 of 20章10誡.
_NOT_A_VERSE = re.compile(rf"(?<=[章篇])(?:[{lx.CN_CHARS}]+(?![{lx.CN_CHARS}]|\s*(?:節|:|-|,|章|篇))"
                          rf"|[0-9]+(?=\s*(?:{_COUNT_WORDS})))")
# A decimal or date after a book: 2.5小時, 1.2版本.
_NOT_A_VERSE_NUMBER = r"(?![0-9]|\s*(?:小時|億|公里|公尺|星|版|章|篇))"


@lru_cache(maxsize=1)
def _full_names() -> str:
    full = [n for n, name in books.default_books().names.items() if not name.is_abbreviation]
    return "|".join(re.escape(n) for n in sorted(full, key=lambda n: (-len(n), n)))


@lru_cache(maxsize=1)
def _dot() -> re.Pattern[str]:
    return re.compile(rf"(?P<head>(?:{_full_names()}){_LINK}\s*{_DI}[0-9]+)"
                      rf"\.(?=[1-9][0-9]*{_NOT_A_VERSE_NUMBER})")


@lru_cache(maxsize=1)
def _book_link() -> re.Pattern[str]:
    return re.compile(rf"(?P<book>{_full_names()})(?P<link>{_LINK})(?={_CITED})")


def _blank(m: re.Match[str]) -> str:
    return " " * len(m.group())


def _unlinked(m: re.Match[str]) -> str:
    worded = m["link"].strip("》」』”\" ")
    if worded and _COUNT_AFTER_LINK.match(m.string, m.end()):
        return m.group()
    return m["book"] + " " * len(m["link"])


def correct_book_names(text: str) -> str:
    """The question with common misspellings of book names put right; offsets do not move."""
    for wrong, right in _MISSPELT.items():
        text = text.replace(wrong, right)
    return text


def _fold(text: str, join_and: bool) -> str:
    """The question in the wording ragcommon.refs reads; every character keeps its offset."""
    folded = correct_book_names(lx.normalize(text))
    folded = _dot().sub(lambda m: f'{m["head"]}:', folded)
    folded = _book_link().sub(_unlinked, folded)
    folded = _OF_VERSE.sub(_blank, folded)
    if join_and:
        folded = _AND.sub(lambda m: "," + " " * (len(m.group()) - 1), folded)
    return _NOT_A_VERSE.sub(_blank, folded)


def _counts_things(match: refs.RefMatch, folded: str) -> bool:
    """True for a single bare chapter number that a counted word follows (馬太福音12門徒)."""
    if len(match.refs) != 1 or not folded[match.end - 1].isdigit():
        return False
    ref = match.refs[0]
    return ref.v_start is None and ref.ch == ref.ch_end and _COUNTED.match(folded, match.end) is not None


def _read(text: str, join_and: bool) -> refs.FindResult:
    folded = _fold(text, join_and)
    found = refs.find_refs(folded)
    return refs.FindResult(
        tuple(replace(m, raw=text[m.start:m.end]) for m in found.matches
              if not _counts_things(m, folded)),
        tuple(replace(r, raw=text[r.start:r.end]) for r in found.rejected))


def read_question(text: str) -> refs.FindResult:
    """The references in a question, spans reported in the question's own words.

    A span joined at 和 is validated as one, so a second reference that does not exist
    (羅馬書8章和17章) would take the first down with it; then the two are read apart.
    """
    found = _read(text, join_and=True)
    if not found.rejected:
        return found
    apart = _read(text, join_and=False)
    return apart if len(apart.refs) > len(found.refs) else found


def find_verse_references(text: str) -> FoundRefs:
    """The references in a question as the backend serves them, and the spans naming no verse."""
    found = read_question(text)
    return FoundRefs(tuple(r for ref in found.refs for r in _backend_refs(ref)), found.rejected)
