"""PDF-only kinship extraction: every rule over every verse, as ``KinRow`` facts.

A row names both tokens by verse and index and carries their character offsets, so every fact
points at the PDF text it was read from. No pronoun is resolved, and nothing but the text layer
and kg0's divine rule is read (``kin_tokens``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from ragdata.kg.kin_lists import Link, named_in_next_verse, ordinal_runs, summaries, titled_lists
from ragdata.kg.kin_patterns import pattern_hits
from ragdata.kg.kin_rules import LIST_SEP, PARENT, Hit, token_hits
from ragdata.kg.kin_tokens import Corpus, Verse

_FAMILY = re.compile(r"^(n\d+|plus)")
_NOT_A_PERSON_AFTER = ("女子", "的女子", "人", "地", "城", "族", "支派", "全家", "山", "河", "谷", "家")
# 和猶大、便雅憫全家 / 和摩押婦人: the list has run on into a people
_PEOPLE_AHEAD = re.compile(r"^(?:婦人|、?[^，。；]{0,8}全家)")
_LIST_RULES = ("child_noun", "begot")


@dataclass(frozen=True)
class KinRow:
    unit: str
    head_unit: str
    head_index: int
    head: str
    rel: str
    tail_unit: str
    tail_index: int
    tail: str
    role: str
    pattern: str
    head_start: int
    head_end: int
    tail_start: int
    tail_end: int

    @property
    def family(self) -> str:
        found = _FAMILY.match(self.pattern)
        return found.group(1) if found else "k0"


def _row(c: Corpus, link: Link, rel: str) -> KinRow | None:
    head_verse, tail_verse = c.verse(link.head_unit), c.verse(link.tail_unit)
    head, tail = head_verse.tokens[link.head], tail_verse.tokens[link.tail]
    if head.norm_key == tail.norm_key:
        return None
    if _FAMILY.match(link.pattern) and (head_verse.after(link.head).startswith(_NOT_A_PERSON_AFTER)
                                        or tail_verse.after(link.tail).startswith(_NOT_A_PERSON_AFTER)):
        return None
    return KinRow(link.unit, link.head_unit, link.head, head.norm_key, rel, link.tail_unit,
                  link.tail, tail.norm_key, link.role, link.pattern, head.start, head.end,
                  tail.start, tail.end)


def _runs_into_a_people(verse: Verse, hit: Hit) -> bool:
    """所羅門的兒子羅波安和猶大、便雅憫全家: a list that runs on into a people is not children."""
    return hit.pattern in _LIST_RULES and hit.tail > hit.head + 1 \
        and verse.gap(hit.tail - 1, hit.tail) in LIST_SEP \
        and bool(_PEOPLE_AHEAD.match(verse.after(hit.tail)))


def _verse_links(verse: Verse) -> Iterable[tuple[Link, str]]:
    if len(verse.tokens) < 2:
        return
    unit = verse.unit_key
    for hit in token_hits(verse):
        if not _runs_into_a_people(verse, hit):
            yield Link(unit, unit, hit.head, unit, hit.tail, hit.role, hit.pattern), hit.rel
    for hit in pattern_hits(verse):
        yield Link(unit, unit, hit.head, unit, hit.tail, hit.role, hit.pattern), hit.rel


def _drop_summaries_of_descendants(rows: Sequence[KinRow]) -> list[KinRow]:
    """A list member with another father: 這都是 X 的兒子 names descendants, not X's children."""
    fathers: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        if row.rel == PARENT and not row.pattern.startswith("n1") and row.role != "M":
            fathers.setdefault((row.tail_unit, row.tail_index), set()).add(row.head)
    bad = {(r.unit, r.head_index) for r in rows if r.pattern == "n1_summary"
           and fathers.get((r.tail_unit, r.tail_index))
           and r.head not in fathers[(r.tail_unit, r.tail_index)]}
    return [r for r in rows if not (r.pattern == "n1_summary" and (r.unit, r.head_index) in bad)]


def extract(c: Corpus) -> tuple[KinRow, ...]:
    """Every kinship fact the rules read, one row per token pair and pattern."""
    found: list[tuple[Link, str]] = [pair for verse in c.verses for pair in _verse_links(verse)]
    for links in (ordinal_runs(c), titled_lists(c), named_in_next_verse(c), summaries(c)):
        found += [(link, PARENT) for link in links]
    rows: dict[tuple, KinRow] = {}
    for link, rel in found:
        row = _row(c, link, rel)
        if row is not None:
            rows.setdefault((row.head_unit, row.head_index, rel, row.tail_unit, row.tail_index,
                             row.pattern), row)
    return tuple(_drop_summaries_of_descendants(list(rows.values())))
