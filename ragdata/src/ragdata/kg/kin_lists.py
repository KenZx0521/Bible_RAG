"""Kinship sentences that run across verses: ordinal lists (長子 A，次子 B), a list's summary (這都是
X 的兒子) and a child named in the next verse. Ported from the prototype's N1, N2 and N4 passes
(kin2.py). A ``Link`` joins token ``head`` of unit ``head_unit`` to token ``tail`` of ``tail_unit``
and is recorded at ``unit``.
"""

from __future__ import annotations

import re
from typing import Iterator, NamedTuple

from ragdata.kg.kin_tokens import Corpus, Verse

_ORD = re.compile(r"^(?:[，、；。]?)(?:其次是|其次|次子|次|三子|四子|五子|六子|七子|八子|九子|第二|第三|第四|第五|第六|第七|第八|老二|老三)(?:是|名叫|叫)?$")
_ORD_START = re.compile(r"^(?:次子|三子|四子|五子|六子|七子|八子|九子|其次|第二|第三)(?:是|名叫|叫)?$")
_HEAD_ORD = re.compile(r"^(?:的)?(?:長子|頭生的)(?:是|名叫|叫)?$|^生長子$|^(?:又|也|就|便)?生了?長子$|^的兒子(?:是|：)?長子(?:是|名叫|叫)?$")
_ORD_SEPARATORS = frozenset({"、", "，", "，又生", "，又生了", "；又生", "和"})
_END_OF_VERSE = frozenset({"，", "、", "；", "。", ""})
_LIST_TITLE = re.compile(r"(?:所生的兒子記在下面|得了幾個兒子|生了幾個兒子|所生的兒子如下)[：，]")
_ORDINAL_BEFORE = re.compile(r"(?:長子|次子|三子|四子|五子|六子|七子|八子|九子|十子)(?:是)?$")
_NAMED_NEXT = re.compile(r"^(?:就)?給(?:他|她)起名叫$")
_BORE_AT_END = re.compile(r"生了?(?:一個|個)?(?:兒子|女兒)[，]?$")
_SUMMARY = re.compile(r"(?:這都是|這些都是|這些是|這[都些]?[一二三四五六七八九十兩]+(?:個)?人(?:都)?是|這[一二三四五六七八九十兩]+(?:個)?人都是|以上都是)$")
_SUMMARY_OF = re.compile(r"^的(?:兒子|眾子|女兒|兒女)")
_LIST_SEPARATORS = frozenset({"、", "，", "和", "與", "，和", "、和", "及", "；"})
_TITLE_WINDOW = 4       # the title's verse and the next three
_SUMMARY_HOPS = 3       # verses a summary reaches back


class Link(NamedTuple):
    unit: str
    head_unit: str
    head: int
    tail_unit: str
    tail: int
    role: str
    pattern: str


def _next_ordinal_verse(c: Corpus, verse: Verse) -> Verse | None:
    """The next verse of the chapter, if it goes on with an ordinal."""
    position = c.position[verse.unit_key] + 1
    if position >= len(c.verses):
        return None
    after = c.verses[position]
    if not c.same_chapter(after, verse) or not after.tokens:
        return None
    return after if _ORD_START.match(after.before(0)) else None


def _ordinal_run(c: Corpus, verse: Verse, head: int) -> Iterator[Link]:
    """長子 A，次子 B: the children after the first, in this verse and on into the next ones."""
    at, cur = verse, head + 1
    while True:
        if cur + 1 < len(at.tokens):
            gap = at.gap(cur, cur + 1)
            if not (_ORD.match(gap) or gap in _ORD_SEPARATORS):
                return
            yield Link(at.unit_key, verse.unit_key, head, at.unit_key, cur + 1, "P", "n2_ord")
            cur += 1
        else:
            following = None if at.after(cur).strip() not in _END_OF_VERSE \
                else _next_ordinal_verse(c, at)
            if following is None:
                return
            yield Link(following.unit_key, verse.unit_key, head, following.unit_key, 0, "P",
                       "n2_ord_xv")
            at, cur = following, 0


def ordinal_runs(c: Corpus) -> Iterator[Link]:
    for verse in c.verses:
        for i in range(len(verse.tokens) - 1):
            if _HEAD_ORD.match(verse.gap(i, i + 1)):
                yield from _ordinal_run(c, verse, i)


def _title_head(verse: Verse, title: re.Match[str]) -> int | None:
    """The last name before the list's title, not one after 在／於／從 (a place)."""
    heads = [i for i, t in enumerate(verse.tokens)
             if t.end <= title.start() and verse.preceding_char(i) not in ("在", "於", "從")]
    return heads[-1] if heads else None


def titled_lists(c: Corpus) -> Iterator[Link]:
    """X…所生的兒子記在下面：長子 A…次子 B… in the title's verse and the next three."""
    for position, verse in enumerate(c.verses):
        title = _LIST_TITLE.search(verse.text)
        head = _title_head(verse, title) if title and verse.tokens else None
        if head is None:
            continue
        for later in c.verses[position:position + _TITLE_WINDOW]:
            if not c.same_chapter(later, verse):
                break
            for i, token in enumerate(later.tokens):
                if later is verse and token.start < title.end():
                    continue
                if _ORDINAL_BEFORE.search(later.text[max(0, token.start - 3):token.start]):
                    yield Link(later.unit_key, verse.unit_key, head, later.unit_key, i, "F",
                               "n2_head")


def named_in_next_verse(c: Corpus) -> Iterator[Link]:
    """X…生了一個兒子，｜給他起名叫 C."""
    for previous, verse in zip(c.verses, c.verses[1:]):
        if verse.tokens and previous.tokens and _NAMED_NEXT.match(verse.before(0)) \
                and _BORE_AT_END.search(previous.text):
            yield Link(verse.unit_key, previous.unit_key, 0, verse.unit_key, 0, "P", "n4_xv")


def _back_through_list(verse: Verse, start: int) -> tuple[list[int], int, bool]:
    """Tokens of the name list ending at ``start``, walking back; where it stopped; and whether a
    token that begins a new clause (的／生) or a non-separator stopped it."""
    tails, j = [], start
    while j >= 0:
        if verse.after(j).startswith(("的", "生")):
            return tails, j, True
        tails.append(j)
        if j == 0:
            return tails, j, False
        if verse.gap(j - 1, j) not in _LIST_SEPARATORS:
            return tails, j, True
        j -= 1
    return tails, j, False


def _earlier_verses(c: Corpus, verse: Verse) -> Iterator[tuple[str, int]]:
    """A summary at the head of a verse takes in whole list verses before it."""
    position = c.position[verse.unit_key]
    for earlier in reversed(c.verses[max(0, position - _SUMMARY_HOPS):position]):
        if not c.same_chapter(earlier, verse) or not earlier.tokens \
                or earlier.after(len(earlier.tokens) - 1).strip() not in _END_OF_VERSE:
            return
        tails, _, stopped = _back_through_list(earlier, len(earlier.tokens) - 1)
        yield from ((earlier.unit_key, t) for t in tails)
        if stopped or earlier.before(0).strip():
            return


def _summary_tails(c: Corpus, verse: Verse, k: int, summary: re.Match[str]) -> list[tuple[str, int]]:
    """The tokens a summary at token ``k`` sums up."""
    if k > 0 and verse.text[verse.tokens[k - 1].end:summary.start()].strip() in ("。", "，", "；", ""):
        tails, stop, _ = _back_through_list(verse, k - 1)
        reach = stop == 0 and not verse.before(0).strip()
        found = [(verse.unit_key, t) for t in tails]
    else:
        found, reach = [], k == 0 and verse.before(k).strip() == summary.group(0)
    return found + list(_earlier_verses(c, verse)) if reach else found


def summaries(c: Corpus) -> Iterator[Link]:
    """A、B、C。這都是 X 的兒子."""
    for verse in c.verses:
        for k in range(len(verse.tokens)):
            summary = _SUMMARY.search(verse.before(k))
            if summary and _SUMMARY_OF.match(verse.after(k)):
                for unit, tail in _summary_tails(c, verse, k, summary):
                    yield Link(verse.unit_key, verse.unit_key, k, unit, tail, "P", "n1_summary")
