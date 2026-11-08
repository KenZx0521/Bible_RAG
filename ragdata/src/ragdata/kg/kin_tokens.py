"""The verses and name tokens the kinship rules read.

Input: the text layer's verse units and body name spans, and kg0's divine rule for 耶穌, the one
person the PDF never underlines. A token is one body span or one merge group. Nothing outside
the PDF comes in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

BODY = "body"
DIVINE_RULE = "divine_rule"
JESUS = "耶穌"


class Token(NamedTuple):
    start: int
    end: int
    surface: str
    norm_key: str


@dataclass(frozen=True)
class Verse:
    unit_key: str
    book_id: str
    chapter: int
    text: str
    tokens: tuple[Token, ...]

    def gap(self, first: int, second: int) -> str:
        """The text between two tokens."""
        return self.text[self.tokens[first].end:self.tokens[second].start]

    def after(self, index: int) -> str:
        return self.text[self.tokens[index].end:]

    def before(self, index: int) -> str:
        return self.text[:self.tokens[index].start]

    def preceding_char(self, index: int) -> str:
        start = self.tokens[index].start
        return self.text[max(0, start - 1):start]


@dataclass(frozen=True)
class Corpus:
    verses: tuple[Verse, ...]             # in PDF order
    position: Mapping[str, int]           # unit_key -> index in ``verses``

    def verse(self, unit_key: str) -> Verse:
        return self.verses[self.position[unit_key]]

    def same_chapter(self, first: Verse, second: Verse) -> bool:
        return (first.book_id, first.chapter) == (second.book_id, second.chapter)


def merged_group(rows: Sequence[Mapping[str, Any]]) -> Token:
    """One token for the spans of a merge group (鹽＋海 → 鹽海)."""
    ordered = sorted(rows, key=lambda row: row["start"])
    surface = "".join(row["surface"] for row in ordered)
    return Token(ordered[0]["start"], ordered[-1]["end"], surface, surface)


def body_tokens(name_spans: Iterable[Mapping[str, Any]]) -> dict[str, list[Token]]:
    """One token per body span or merge group, by verse unit (not sorted)."""
    by_unit: dict[str, list[Token]] = defaultdict(list)
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in name_spans:
        if row["region"] != BODY:
            continue
        if row["merge_group"]:
            groups[(row["container_id"], row["merge_group"])].append(row)
        else:
            by_unit[row["container_id"]].append(
                Token(row["start"], row["end"], row["surface"], row["norm_key"]))
    for (unit, _), rows in groups.items():
        by_unit[unit].append(merged_group(rows))
    return by_unit


def _with_jesus(by_unit: dict[str, list[Token]], extra_spans: Iterable[Mapping[str, Any]]) -> None:
    for row in extra_spans:
        if row["region"] == BODY and row["source"] == DIVINE_RULE and row["surface"] == JESUS:
            by_unit[row["container_id"]].append(Token(row["start"], row["end"], JESUS, JESUS))


def corpus(verse_units: Iterable[Mapping[str, Any]], name_spans: Iterable[Mapping[str, Any]],
           extra_spans: Iterable[Mapping[str, Any]]) -> Corpus:
    by_unit = body_tokens(name_spans)
    _with_jesus(by_unit, extra_spans)
    verses = tuple(Verse(row["unit_key"], row["book_id"], row["chapter"], row["text"],
                         tuple(sorted(by_unit.get(row["unit_key"], ()))))
                   for row in verse_units)
    return Corpus(verses, MappingProxyType({v.unit_key: i for i, v in enumerate(verses)}))
