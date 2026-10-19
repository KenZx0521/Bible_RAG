"""Which questions get the chronology card: the confirmed question types only.

A question takes the card when it names a king on the regnal chain (a name or alias of the
layer) and asks one of the confirmed types (``confirm_A.md`` §2.1):

- S1a the k-th king before or after a king (之後／之前的第 k 位, 往前數第 k 位, 接續…作王的是誰,
  繼位的是誰);
- S1b how many times the throne changed hands between two kings (交接, 相隔…代);
- S1c the n-th usurper after a king (第 n 個…篡);
- S4 the king reigning when a king was born (出生時／出生的時候／出生那年 … 在位／作…王).

The rules were fixed on the type definitions and the 30 development questions (stage 0)
alone (commit 1efcc85). One change came after the blind set was read (2026-10-19, plan
執行紀錄): its six misses were all S1a with punctuation between 之後 and 第 k 位, or 往前數
第 k 位, so the S1a cue now allows punctuation and 往前／往後數; the blind set's recall
under the changed rule is in-sample. A code review then found event questions taking the
card (繼位時幾歲, 篡位後做了什麼), so every cue now asks for the confirmed answer: an
ordinal, or who took the throne, or who reigned at a birth. Broad words (年間, 在位時, 先後順序, a reign length)
are no cue: a question about the events of a reign is not a chronology question, and the
card was never measured there. Matching is on the NFKC question text and reads nothing else.

2026-10-19, blockers: a chain name inside a longer name off the chain was read as the king
(押沙龍 as 沙龍, 以利亞撒 as 亞撒, 亞哈隨魯 as 亞哈, 以拉他 as 以拉), so with a cue such a
question took the card. ``find_names`` now takes the chain names together with the blockers
(the routing lexicon's person and place names that hold a chain name and are none,
``layer.with_lexicon``; not its events, 所羅門獻殿 does name the king), longest first, and
drops a blocker's place; a name followed by 支派／族 is the tribe, not the king. It narrows
only: on the 500-question GT (v1 and v2) the questions naming a chain king go 21 → 19 on
layer 932d2242 and none takes the card, before or after; the blind and development sets fire
as before (32/32, 27/30). Its known cost: a real king whose name runs into a character that
makes a blocker (以拉 + 大約 reads as 以拉大, 28 blockers there, many a king's name and one
character) is hidden too, so such a question loses the card or the rules abstain. The
startup log prints the blockers and ``test_regnal_seeds`` pins them per layer. The rule seeds
(``seeds.rule_seeds``) read the names with the same function.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_NUM = "[一二三四五六七八九十兩0-9]+"
_KTH = rf"(?:往(?:前|後)數)?(?:的)?第{_NUM}(?:位|任|代)"
_WHO = r"(?:是|為)?(?:誰|哪)"
CUES = {
    # an ordinal position, or asking who took the throne (not the events around it)
    "S1a": re.compile(rf"(?:之|以)(?:後|前)[，,、\s]*{_KTH}|往(?:前|後)數(?:的)?第{_NUM}(?:位|任|代)"
                      rf"|接續.{{0,6}}?作王的(?:人)?{_WHO}|繼位(?:的|者)(?:人)?{_WHO}"),
    "S1b": re.compile(r"交接|相隔.{0,3}?代"),
    # the n-th usurper (an ordinal before 篡, with room for 背叛、殺王 between, as the type's own
    # definition words it), not what a usurper did
    "S1c": re.compile(rf"第{_NUM}(?:個|位|次)?.{{0,12}}?篡"),
    # who reigned at a king's birth, not the events of it
    "S4": re.compile(rf"出生(?:的)?(?:時|那年).{{0,12}}?(?:在位|作.{{0,3}}?王|王{_WHO})"),
}


# 瑪拿西支派, 瑪拿西半支派: the tribe, not the king
_TRIBE = re.compile(r"半?支派|族")


@dataclass(frozen=True)
class Trigger:
    fired: bool
    kings: tuple[str, ...]     # chain names found in the question, in order of appearance
    cues: tuple[str, ...]      # the types whose cue matched


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    name: str                  # a chain name or alias, as the layer spells it


def find_names(question: str, names: tuple[str, ...], blockers: tuple[str, ...] = ()) -> tuple[Mention, ...]:
    """Chain names in the (NFKC) question, in order of appearance: chain names and blockers
    together, longest first, none inside one already taken; a blocker's place and a name
    followed by 支派／族 are dropped."""
    chain = set(names)
    taken: list[Mention] = []
    for name in sorted(chain | set(blockers), key=lambda n: (-len(n), n)):
        for m in re.finditer(re.escape(name), question):
            if not any(m.start() < t.end and t.start < m.end() for t in taken):
                taken.append(Mention(m.start(), m.end(), name))
    return tuple(t for t in sorted(taken, key=lambda t: t.start)
                 if t.name in chain and not _TRIBE.match(question, t.end))


# a match of these holding a king's name is narrative, not the cue: S1c's room before 篡 also
# takes a regnal year (亞撒第三年巴沙篡位). In the others a held name is the anchor (接續X作王)
# or an answer candidate after the cue's start (X出生時，Y在位嗎).
_NARRATIVE_ROOM = ("S1c",)


def first_cue(question: str, found: tuple[Mention, ...] = ()) -> tuple[str, int] | None:
    """(type, start) of the earliest cue in the (NFKC) question, skipping an S1c match that
    overlaps one of ``found``; None without one. Every start is tried, so a skipped match hides
    no later one; with ``found`` empty this is the earliest ``search`` of each cue."""
    for i in range(len(question)):
        for kind, p in CUES.items():
            m = p.match(question, i)
            if m and not (kind in _NARRATIVE_ROOM
                          and any(n.start < m.end() and m.start() < n.end for n in found)):
                return kind, i
    return None


def trigger(question: str, names: tuple[str, ...], blockers: tuple[str, ...] = ()) -> Trigger:
    q = unicodedata.normalize("NFKC", question)
    kings = tuple(m.name for m in find_names(q, names, blockers))
    cues = tuple(t for t, p in CUES.items() if p.search(q))
    return Trigger(bool(kings) and bool(cues), kings, cues)
