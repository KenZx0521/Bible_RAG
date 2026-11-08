"""Which questions ask about kinship, of whom, and which way a walk should go for them.

The cues are read on the question with its names and books blanked out: 亞伯拉罕 holds 伯, 撒母耳 holds 母,
and neither asks about an uncle or a mother. A kinship word counts only right after a name, with at most a
title or a count between: X 的父親, X 王的父親, X 有幾個兒子, X 和 Y 的母親. So 天父, 信心之父, 浪子的父親 and
摩西的休書…論休妻 ask nothing. A word that only names the next person (亞伯拉罕的兒子以撒) asks nothing either:
以撒的妻子, in 亞伯拉罕的兒子以撒的妻子是誰, is what is asked, and of 以撒. Nor does one a question goes on from
without asking anything (亞伯拉罕的子孫會多如天上的星，是什麼意思).

A pronoun asks nothing: a question that describes the one it asks about (那位祭司…他的外祖父是誰) means that person
by 他, and no name it writes. On 113 complex questions the cards a pronoun or a far 同名 gave were of the wrong people.

曾 counts only in 曾祖, 曾孫 (曾經 is no great-grandfather), and 弟子 is no younger brother. Beyond the kinship
words: 關係 when two names, or 他們, are in its own clause (``takes``), and 同名 or 幾個叫 X right beside the name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from ragcommon.routing import MASK, Hit, RoutingLexicon

SIBLING, SPOUSE = "SIBLING_OF", "SPOUSE_OF"
SPOUSE_FIRST, CHILD_FIRST = "spouse", "child"


@dataclass(frozen=True)
class Cue:
    up: int = 0                    # generations upward; 0: not asked
    down: int = 0                  # generations downward
    side: tuple[str, ...] = ()     # the one-hop kinds asked for
    near: bool = False             # one or two hops in any direction
    same_name: bool = False
    relation: bool = False         # 關係, which only speaks about two people
    in_law: str = ""               # near, by way of a spouse (岳母) or of a child's spouse (媳婦)

    @property
    def only_relation(self) -> bool:
        """關係 and no kinship word: all it can ask for is the path between two people."""
        return self.relation and not (self.up or self.down or self.side or self.near or self.same_name)


# the longest first: 曾祖 before 祖, 祖先 before 祖
_WORDS: tuple[tuple[str, Cue], ...] = (
    *((w, Cue(up=n)) for w, n in (("祖先", 3), ("曾外祖", 3), ("曾祖", 3), ("外祖", 2), ("祖", 2), ("父", 1), ("母", 1))),
    *((w, Cue(down=n)) for w, n in (("後代", 3), ("後裔", 3), ("子孫", 3), ("曾外孫", 3), ("曾孫", 3), ("外孫", 2), ("孫", 2),
                                    ("兒子", 1), ("女兒", 1), ("兒女", 1), ("子女", 1), ("孩子", 1), ("長子", 1), ("次子", 1), ("眾子", 1))),
    *((w, Cue(side=(SIBLING,))) for w in "兄弟哥姊姐妹"),
    *((w, Cue(side=(SPOUSE,))) for w in ("妻", "妾", "丈夫")),
    *((w, Cue(near=True, in_law=SPOUSE_FIRST)) for w in "岳婆"),
    ("媳", Cue(near=True, in_law=CHILD_FIRST)), ("女婿", Cue(near=True, in_law=CHILD_FIRST)),
    ("婿", Cue(near=True, in_law=CHILD_FIRST)),
    *((w, Cue(near=True)) for w in (*"叔伯舅姑姨侄甥", "親屬", "親戚", "家譜", "血緣")),
)
_NOT_KIN = ("弟子",)
_NAME = re.compile(rf"{MASK}+")
_LINK = re.compile(r"(?:王|先知|祭司)?(?:的|之|(?:共)?有)?(?:[一二三四五六七八九十兩幾多少]+[個位名]?)?")
_NOUN_REST = re.compile(r"[親子父母弟兄妹姊們婦夫女先叔伯舅姑姨侄甥婿孫祖裔代]*")
_AND = re.compile(r"[和與及、]")
_NAMES_THE_NEXT = re.compile(rf"(?:，|、|－|名叫|叫)?{MASK}")
_ASKING = re.compile(r"誰|哪|幾|多少|什麼|甚麼|何|嗎|呢|？|\?|名叫|叫")
_ASKING_WITHIN = 8
_ENDS = "。！ "
_JOINED_BEFORE = re.compile(rf"({MASK}+)[和與及、跟同]$")
_TWO_NAMES = re.compile(rf"{MASK}[和與及、跟同]{MASK}")
_SAME_NAME = re.compile(rf"{MASK}(?:有|的)?同名|同名的{MASK}+(?![{MASK}王])|幾[個位](?:名)?叫{MASK}")
_PLURAL = ("他們", "她們")
RELATION = "關係"
_CLAUSE_OF_RELATION = re.compile(rf"[^，。；！？,;!?]*{RELATION}[^，。；！？,;!?]*")


def word_at(text: str, at: int) -> Cue | None:
    """The cue of a kinship word starting at ``at``."""
    if text.startswith(_NOT_KIN, at):
        return None
    return next((cue for word, cue in _WORDS if text.startswith(word, at)), None)


def _word_length(text: str, at: int) -> int:
    return next(len(word) for word, _ in _WORDS if text.startswith(word, at))


def _joined(cues: Iterable[Cue]) -> Cue:
    """Everything the cues ask for."""
    out = Cue()
    for cue in cues:
        side = tuple(kind for kind in (SIBLING, SPOUSE) if kind in out.side or kind in cue.side)
        out = replace(out, up=max(out.up, cue.up), down=max(out.down, cue.down), side=side, near=out.near or cue.near,
                      in_law=out.in_law or cue.in_law)
    return out


def _words_after(text: str, at: int) -> tuple[Cue | None, int]:
    """What the words after a name ask for (父親和兒子: two), and where they end."""
    at = _LINK.match(text, at).end()
    found: list[Cue] = []
    while (cue := word_at(text, at)) is not None:
        found.append(cue)
        at = _NOUN_REST.match(text, at + _word_length(text, at)).end()
        joined = _AND.match(text, at)
        if not joined or word_at(text, joined.end()) is None:
            break
        at = joined.end()
    return (_joined(found) if found else None), at


def _names_ending_with(text: str, name: re.Match[str]) -> list[int]:
    """Where the name ends, and the names joined to it: 雅各和以掃的母親 asks of both."""
    ends, start = [name.end()], name.start()
    while (before := _JOINED_BEFORE.search(text, 0, start)) is not None:
        ends.append(before.end(1))
        start = before.start(1)
    return ends


def _asks(text: str, end: int) -> bool:
    """A question word soon after the kinship word, or nothing at all after it (雅各的家譜)."""
    return end >= len(text.rstrip(_ENDS)) or bool(_ASKING.search(text, end, end + _ASKING_WITHIN))


@dataclass(frozen=True)
class Reading:
    """A masked question, read."""

    cue: Cue | None = None                        # everything it asks; None: no kinship
    of_name: Mapping[int, Cue] | None = None      # the offset a masked name ends at -> what is asked of it

    def of(self, end: int | None) -> Cue | None:
        """What is asked of the name ending at ``end`` (None: an intent entity the question does not write)."""
        return (self.of_name or {}).get(end) if end is not None else None


def _asks_relation(text: str) -> bool:
    return any(_TWO_NAMES.search(clause) or any(p in clause for p in _PLURAL)
               for clause in _CLAUSE_OF_RELATION.findall(text))


def reading(text: str) -> Reading:
    of_name: dict[int, Cue] = {}
    for name in _NAME.finditer(text):
        cue, end = _words_after(text, name.end())
        if cue is None or not _asks(text, end) or _NAMES_THE_NEXT.match(text, end):
            continue
        for name_end in _names_ending_with(text, name):
            of_name[name_end] = _joined((of_name.get(name_end, Cue()), cue))
    same_name = bool(_SAME_NAME.search(text))
    relation = _asks_relation(text)
    if not (of_name or same_name or relation):
        return Reading()
    return Reading(replace(_joined(of_name.values()), same_name=same_name, relation=relation), of_name)


def read(text: str) -> Cue | None:
    """The cue of a masked question; None when it asks about no kinship."""
    return reading(text).cue


def masked(question: str, hits: Iterable[Hit], lexicon: RoutingLexicon) -> str:
    """The question with its books and its names (the lexicon's ``hits``) blanked out."""
    text = lexicon.mask_books(question)
    for hit in hits:
        text = text[:hit.start] + MASK * (hit.end - hit.start) + text[hit.end:]
    return text


def takes(cue: Cue, ends: int) -> bool:
    """Whether the cue speaks about ``ends`` named people: 關係 alone needs two."""
    return ends >= 2 if cue.only_relation else True
