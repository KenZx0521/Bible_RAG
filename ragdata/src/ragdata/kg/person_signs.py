"""What the kinship rows say of each name token, for ``person_identity`` to compare: its relatives' names,
a title or gentile, its sex, and which token of its verse it cannot be.

Sex is read only from a word right next to the name: 雅各之妻拉結的兒子是約瑟 holds 之妻, and 約瑟 is no wife. A
name some row writes as a woman's is a mother wherever it is a parent, unless that token is written as
a man (瑪迦, 亞比雅 are both).

A king's title comes four ways: printed before the name, from the regnal table for a verse holding the
name once and for a son of the father it names, or a father of the king it names (``Kings``), and, for a
name two kingdoms' kings share,
from the father or son the row names (以色列王約哈斯的兒子約阿施; 約阿施的兒子猶大王亞瑪謝). 稱呼馬可的約翰 is a sign
of its own (``q:``): such a token is someone else than a 約翰 without it.

Two tokens of a name in one verse are two people when a row makes one a father and the next a son of
someone else, written as a list of men and not as a chain: 亞撒利雅的兒子約珥；…耶哈利勒的兒子亞撒利雅 (the
father first), and 亞勒腓的兒子雅各、奮銳黨的西門，和雅各的兒子猶大 (the son first, only list marks between).
約拿單 in 掃羅的兒子約拿單…掃羅的孫子、約拿單的兒子米非波設 and 示非 in 示非的兒子細撒。示非是亞龍的兒子 stay one.
"""

from __future__ import annotations

import re
from collections import defaultdict
from types import MappingProxyType
from typing import Mapping, NamedTuple, Sequence

from ragdata.kg.kin_extract import KinRow
from ragdata.kg.kin_rules import NUM, PARENT, SPOUSE
from ragdata.kg.kin_tokens import Corpus

Mention = tuple[str, int]        # (unit_key, token index)

_FEMALE_END = re.compile(r"(?:女兒|長女|次女|獨生女|的妻|的妾|之妻|妻子|妹子|妹妹|姊姊|姐姐|母親)[，、－：]?(?:名叫)?$")
_MALE_END = re.compile(r"(?:兒子|長子|次子|三子|四子|五子|六子|七子|八子|九子|之子|哥哥|弟弟)[，、－：]?(?:是|有|叫|名叫|就是)?$")
# 雅代的兒子是利健、約坦、以法: every name of a list of sons, the row's gap opening with the word
_SONS_START = re.compile(rf"^的(?:[{NUM}]+個)?(?:兒子|長子|次子|三子|四子|五子|六子|七子|八子|九子|小兒子|大兒子)(?:是|有|名叫|叫|就是)?")
_WIFE = re.compile(r"妻|妾|娶")
_HUSBAND = "丈夫"
_IS_A_SON_OF = "的兒子"
_IS_A_DAUGHTER_OF = "的女兒"
_IS_CHILD_OF = "is_child_of"
_NAMER = "n4_namer"             # the one who named a child can be its mother
_LIST_END = ("、", "，", "和", "與", "及")
_STOPS = re.compile(r"[。；：]")
_GRANDCHILD_END = re.compile(r"(?:孫子|孫女|曾孫|玄孫)[、，]$")
_OWN_TITLE = ("ti:",)
_CALLED = re.compile(r"稱呼([^，。；、]{1,6})的$")


class Kings(NamedTuple):
    """What the identity reads of the regnal table."""
    homonyms: frozenset[str] = frozenset()                       # names of kings in two kingdoms
    titles: Mapping[tuple[str, str], str] = MappingProxyType({})  # (name, a verse it reads him from) -> 猶大王
    sons: Mapping[tuple[str, str], str] = MappingProxyType({})    # (name, his father's name) -> 猶大王
    fathers: Mapping[tuple[str, str], str] = MappingProxyType({})  # (a king, his son who was king) -> 猶大王


class Signs(NamedTuple):
    surface: dict[Mention, str]
    strong: dict[Mention, set[str]]          # ch: sp: si: ma: gent: ti: q:, each with a name
    fathers: dict[Mention, set[str]]
    mothers: dict[Mention, set[str]]
    children: dict[Mention, set[Mention]]
    women: frozenset[Mention]
    men: frozenset[Mention]
    female: frozenset[str]                   # names some row writes as a woman's
    apart: dict[Mention, set[Mention]]


def _mentions(r: KinRow) -> tuple[Mention, Mention]:
    return (r.head_unit, r.head_index), (r.tail_unit, r.tail_index)


def _same_verse_in_order(r: KinRow) -> bool:
    return r.head_unit == r.tail_unit and r.head_index < r.tail_index


def _sexes_of_a_row(r: KinRow, c: Corpus) -> tuple[list[Mention], list[Mention]]:
    """(women, men) the row writes."""
    head, tail = _mentions(r)
    if r.rel == PARENT and r.role == "M":
        return [head], []
    women, men = [], [head] if r.rel == PARENT and r.role == "F" and r.pattern != _NAMER else []
    text = c.verse(r.head_unit).text
    if r.pattern == _IS_CHILD_OF:
        after = text[r.head_end:]
        return ([tail] if after.startswith(_IS_A_DAUGHTER_OF) else [],
                [tail] if after.startswith(_IS_A_SON_OF) else [])
    if not _same_verse_in_order(r):
        return women, men
    gap = text[r.head_end:r.tail_start]
    if r.rel == SPOUSE:
        if _WIFE.search(gap):
            return [tail], [head]
        return ([head], [tail]) if _HUSBAND in gap else ([], [])
    if _FEMALE_END.search(gap):
        women.append(tail)
    elif _MALE_END.search(gap) or _SONS_START.match(gap):
        men.append(tail)
    return women, men


def sexes(rows: Sequence[KinRow], c: Corpus) -> tuple[frozenset[Mention], frozenset[Mention]]:
    women: set[Mention] = set()
    men: set[Mention] = set()
    for r in rows:
        found_women, found_men = _sexes_of_a_row(r, c)
        women.update(found_women)
        men.update(found_men)
    return frozenset(women), frozenset(men)


def _token_titles(c: Corpus, mention: Mention, strong: dict[Mention, set[str]]) -> None:
    unit, index = mention
    if index == 0:
        return
    verse = c.verse(unit)
    gap, previous = verse.gap(index - 1, index), verse.tokens[index - 1].norm_key
    if gap == "人":
        strong[mention].add(f"gent:{previous}")
    if gap in ("王", "王－"):
        strong[mention].add(f"ti:{previous}王")
    called = _CALLED.search(verse.before(index))
    if called:
        strong[mention].add(f"q:{called.group(1)}")


def _titles_of(signs: set[str]) -> set[str]:
    return {s for s in signs if s.startswith(_OWN_TITLE)}


def _regnal_table_titles(rows: Sequence[KinRow], surface: Mapping[Mention, str], strong: dict[Mention, set[str]],
                         kings: Kings) -> None:
    """A verse's king, when the verse has that name on one token with a row; a son of the father it names."""
    count: dict[tuple[str, str], int] = defaultdict(int)
    for (unit, _), name in surface.items():
        count[(name, unit)] += 1
    for mention, name in surface.items():
        title = kings.titles.get((name, mention[0]))
        if title and count[(name, mention[0])] == 1:
            strong[mention].add(f"ti:{title}")
    for r in rows:
        if r.rel != PARENT:
            continue
        son, father = kings.sons.get((r.tail, r.head)), kings.fathers.get((r.head, r.tail))
        if son:
            strong[(r.tail_unit, r.tail_index)].add(f"ti:{son}")
        if father:
            strong[(r.head_unit, r.head_index)].add(f"ti:{father}")


def _inherited_titles(rows: Sequence[KinRow], strong: dict[Mention, set[str]],
                      homonyms: frozenset[str]) -> None:
    """A shared king's kingdom, from the father or the son the row names beside him."""
    printed = {mention: _titles_of(signs) for mention, signs in strong.items()}
    for r in rows:
        if r.rel != PARENT or r.role == "M":
            continue
        head, tail = _mentions(r)
        if r.tail in homonyms:
            strong[tail] |= printed.get(head, set())
        if r.head in homonyms:
            strong[head] |= printed.get(tail, set())


def _is_mother(r: KinRow, head: Mention, women: frozenset[Mention], men: frozenset[Mention],
               female: frozenset[str]) -> bool:
    return r.role == "M" or head in women or (r.head in female and head not in men)


def _is_list_of_men(c: Corpus, first: Mention, second: Mention) -> bool:
    """Only list marks between two tokens, in one verse or two running on: ``first``, a son; ``second``, a father."""
    verse, later = c.verse(first[0]), c.verse(second[0])
    start, end = verse.tokens[first[1]].end, later.tokens[second[1]].start
    between = verse.text[start:end] if first[0] == second[0] else verse.text[start:] + later.text[:end]
    return between.endswith(_LIST_END) and not _STOPS.search(between) and not _GRANDCHILD_END.search(between)


def _two_people(c: Corpus, first: Mention, second: Mention, fathers: set[Mention], sons: set[Mention]) -> bool:
    """Tokens of one name, ``first`` before ``second``; neighbours are a chain (X的兒子Y；Y的兒子Z)."""
    same_verse = first[0] == second[0]
    if (same_verse and second[1] == first[1] + 1) or (
            not same_verse and second[1] == 0 and first[1] == len(c.verse(first[0]).tokens) - 1):
        return False
    if same_verse and first in fathers and second in sons:
        return True
    return first in sons and second in fathers and _is_list_of_men(c, first, second)


def _apart(rows: Sequence[KinRow], surface: Mapping[Mention, str], c: Corpus) -> dict[Mention, set[Mention]]:
    fathers: set[Mention] = set()      # the head of a row whose tail comes after it
    sons: set[Mention] = set()         # the tail of a row whose head comes before it
    for r in rows:
        if r.rel == PARENT and _same_verse_in_order(r):
            head, tail = _mentions(r)
            fathers.add(head)
            sons.add(tail)
    by_name_in_verse: dict[tuple[str, str], list[Mention]] = defaultdict(list)
    for mention, name in surface.items():
        by_name_in_verse[(mention[0], name)].append(mention)
    apart: dict[Mention, set[Mention]] = defaultdict(set)
    for (unit, name), tokens in by_name_in_verse.items():
        at = c.position[unit] + 1
        following = by_name_in_verse.get((c.verses[at].unit_key, name), []) if at < len(c.verses) else []
        ordered = sorted(tokens, key=lambda m: m[1])
        for i, first in enumerate(ordered):
            for second in (*ordered[i + 1:], *sorted(following, key=lambda m: m[1])):
                if _two_people(c, first, second, fathers, sons):
                    apart[first].add(second)
                    apart[second].add(first)
    return apart


def signs_of(rows: Sequence[KinRow], c: Corpus, kings: Kings = Kings()) -> Signs:
    surface: dict[Mention, str] = {}
    strong: dict[Mention, set[str]] = defaultdict(set)
    fathers: dict[Mention, set[str]] = defaultdict(set)
    mothers: dict[Mention, set[str]] = defaultdict(set)
    children: dict[Mention, set[Mention]] = defaultdict(set)
    women, men = sexes(rows, c)
    female = frozenset(r.head if m == (r.head_unit, r.head_index) else r.tail for r in rows
                       for m in _mentions(r) if m in women)
    for r in rows:
        head, tail = _mentions(r)
        surface[head], surface[tail] = r.head, r.tail
        if r.rel == PARENT:
            children[head].add(tail)
            if _is_mother(r, head, women, men, female):
                strong[tail].add(f"ma:{r.head}")
                if r.role == "M" or head in women:
                    mothers[tail].add(r.head)
            else:
                fathers[tail].add(r.head)
            strong[head].add(f"ch:{r.tail}")
        else:
            prefix = "sp:" if r.rel == SPOUSE else "si:"
            strong[head].add(f"{prefix}{r.tail}")
            strong[tail].add(f"{prefix}{r.head}")
    for mention in list(surface):
        _token_titles(c, mention, strong)
    _regnal_table_titles(rows, surface, strong, kings)
    _inherited_titles(rows, strong, kings.homonyms)
    return Signs(surface, strong, fathers, mothers, children, women, men, female, _apart(rows, surface, c))
