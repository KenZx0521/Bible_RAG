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

2026-10-19, relaxation (qset P1): on the question set's P1 the trigger took 22 of 60 real
phrasings (R_trig 0.367 < 0.70, ``evaluation/experiments/2026-10-19_regnal_qset/qset.md`` §6), all
38 misses a cue miss: the writers counted with 往前數兩任, 往前倒推兩位, 後面第二位, 往下數第三個,
之前兩代, 隔兩任; counted handovers with 傳了幾次, 換了幾次, 換手, 更迭; wrote the usurper as 謀反,
弒君, 殺王, 奪得王位 without 篡; and the birth year as 出生(的)那一年 with 做王, 當王. Each type got
alternatives for these (``_S1A_NEW`` … ``_S4_NEW``, each pattern's group ``new``), and a few for the
same answer asked another way (k = ±1: 的下一任是誰, 繼任者是誰; 是在哪位王在位時出生的). Only P1 and
the development set's three misses were looked at; those three (SUC_01, N_SUC_01, N_KIN_14: a
great-grandson, a described king, a kinship) take no new cue.

The old alternatives are unchanged and first in each pattern, so every question the old rules took
still takes the card; and ``first_cue`` returns the earliest old cue wherever one is left, so such a
question keeps its rule seeds and abstentions (a relaxation cue earlier in a two-cue question moved
the anchor to another king before this). An added alternative counts (``_counts``) only after the
chain name it starts from (two different ones for S1b, the names the rule seeds anchor on), with no
referring phrase in it (那位王以後), and: a k = ±1 or reversed-birth one right after its king (亞撒的
繼任者; not 約西亞年間的大祭司…的下一任); an S1b one when the stretch from the second king to the count
names no other office, thing, reign, kingdom or nation (大祭司更替了幾次, 在位期間, 以色列換了幾次王
between two kings of Judah: the pattern cannot tell another kingdom's throne from the kings' own, so
北國以色列的王位 between two kings of Israel is lost too); an S4 one when no other kingdom or nation
follows its throne word (在位的以色列王是誰, 作亞述王的). Inside the patterns: a counted 位, 任 or 名
needs a king, a who or a throne verb after it (前面第三位書記官 is none), 個 and 代 a throne word or a
who (往上數三代 is an ancestor, 第二個王朝 no king), a bare count (兩任) a who or a throne verb; a who
is not 哪一年 or 是誰的兒子; 傳 and 換 count the throne only with 王位 before or 王 after; the usurper
needs an ordinal after 之後 and then a killing or a seizing of the throne, with no 被, 遭 or 死 in the
rooms (第一位被殺的王, 死於政變的王 are the victims; a nation that 背叛 a kingdom is no usurper); the birth's
room holds no other kingdom, nation, prophet or parent, its throne word no year count after it (作王第
幾年 is a synchronism), and 出生於… asks which king (出生在西拿基立統治的年代嗎 does not).

This draft was chosen over two others (a minimal one, one written from the types' grammar) on a
held-out probe set written from the type definitions alone, without P1 or any draft (72 positives,
72 near-misses naming chain kings), then reviewed from four sides (equivalence, backtracking, false
fires, code), which found the anchor move, the hidden referring phrase and the guards above. As it
stands: P1 58 of 60 (rule seeds 18 → 49, the nine others abstain, none wrong; near-misses 0 of 15
before and after), the held-out set 49 of 72 (the old rules 27; none with a wrong rule seed) and 0
of its 72 near-misses; GT v1 and v2 fire 0, the development set 27/30 and the blind set 32/32 as
before. P1 and the reviews' questions are in-sample; P2 is the measure of how far it carries.

Its known costs: a composite that names a position and asks something of it takes the card
(往前數兩任的王在位多久, 約西亞之後的四位王是誰), as 之後第二位王 … 多久 did before; a king of Israel's
birth asked with 猶大王 takes it (亞哈出生的那一年，誰在位當猶大王), the born line being of his own
kingdom; the old alternatives keep what they took (希西家出生那年亞述王是誰, 希西家出生的時候亞哈斯作王第
幾年, 以後第二位先知). No added
alternative repeats a part that can match empty or that is open-ended: an early draft's
王位(…|[,，、 ]*)* backtracked exponentially on 王位 and a run of commas (24 took 0.9 s); separators are
now ``{0,3}`` and every room bounded, the numerals' run follows a fixed word, and
``test_regnal_trigger_time`` runs every literal of this file, and every prefix of an example of each
alternative, followed by a repeated separator to the request's 500 characters.
``evaluation/tests/test_regnal_qset.py`` pins every alternative, old and added, to an example holding
a literal of the question writers' banned list (``banned_q.CUE_LITERALS``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass

_NUM = "[一二三四五六七八九十兩0-9]+"
_KTH = rf"(?:往(?:前|後)數)?(?:的)?第{_NUM}(?:位|任|代)"
_WHO = r"(?:是|為)?(?:誰|哪)"

# --- the 2026-10-19 relaxation; every piece below serves only the added alternatives -------------
_ROOM = r"[^?？。!！;；]"                          # a character inside one clause (NFKC: ？ is ?)
_SEP = r"[,，、\s]{0,3}"                           # bounded: no repeat in the added alternatives is open
# who, not where, which year or whose (哪裡, 哪一年, 是誰的兒子)
_WHO_KING = r"(?:是|為)?(?:誰(?!的|殺|害|篡|弒|立|膏|廢|擄|生)|哪(?:一)?(?:位|個|任|名))"
_KD = r"(?:(?:猶大|以色列|南國|北國)(?:國)?(?:的)?)"
_KING = r"(?:王(?![朝后宮室冠妃府])|君王|國王|君主)"     # not 王朝, 王后
_THRONE_VERB = r"(?:坐|作|做|當|登基|繼位|接位|即位)"
_ASK_KING = rf"(?:的)?{_KD}?{_KING}?{_SEP}{_WHO_KING}"        # (的猶大王)是誰
_KING_NEXT = rf"(?:(?:的)?{_KD}?{_KING}{_SEP}{_WHO_KING}|(?:的)?{_THRONE_VERB})"
# what may follow a counted 位/任/名: a king, a who, a throne verb or the clause's end (後面第二位是誰;
# not 前面第三位書記官, 往前數兩位先知)
_KING_FOLLOWS = rf"(?={_SEP}(?:(?:的)?{_KD}?{_KING}|{_WHO_KING}|(?:的)?{_THRONE_VERB}|叫|[?,，、。]|$))"
# the direction a count runs from the named king; 往上 and 往回 run toward the earlier kings
_DIR = r"(?:(?:之|以)(?:後|前)|死後|(?:後|前)面|往(?:前|後|下|上|回)|向(?:前|後))"
_STEP = r"(?:再|接下來|接著)?(?:往(?:前|後|下|上|回))?(?:再)?"
_COUNT = r"(?:(?:倒)?(?:數|推|算)(?:下去|回去|過去)?|(?:經)?過)(?:了)?"
# 代 is a generation and 個 is anything, so they need a throne word or a who after them too
_CL_ORD = rf"(?:(?:位|任|名){_KING_FOLLOWS}|代(?={_SEP}{_KING_NEXT})|個(?={_SEP}{_KING_NEXT}|{_SEP}{_WHO_KING}))"
_CL_COUNTED = rf"(?:(?:位|任){_KING_FOLLOWS}|代(?={_SEP}{_KING_NEXT}))"
# a bare count (兩任, 兩代) without a counting verb: a who or a throne verb must follow
_CL_BARE = rf"(?:(?:任|位)(?={_SEP}(?:{_ASK_KING}|(?:的)?{_THRONE_VERB}))|代(?={_SEP}{_KING_NEXT}))"
_S1A_NEW = (
    rf"{_DIR}{_SEP}{_STEP}(?:{_COUNT})?(?:的)?第{_NUM}{_CL_ORD}"           # 之後再往下數第三個王, 後面第二位
    rf"|{_DIR}{_SEP}{_STEP}{_COUNT}{_NUM}{_CL_COUNTED}"                    # 往前數兩任, 往前倒推兩位
    rf"|{_DIR}{_SEP}(?:再)?隔(?:了)?{_NUM}{_CL_COUNTED}"                   # 之後，隔兩任
    rf"|{_DIR}{_SEP}{_STEP}(?:的)?{_NUM}{_CL_BARE}"                        # 之前兩代坐猶大王位, 之後的兩任王是誰
    # k = ±1, of the king named right before it (group ``adj``, _ADJACENT)
    rf"|(?P<adj>(?<![最落])(?:下|上|前|後)一(?:任|位|個){_ASK_KING}"          # 的下一任是誰 (not 最後一位)
    rf"|(?:下下|上上)(?:一)?(?:任|位|個){_ASK_KING}"                           # 的上上任是誰
    rf"|(?:繼任|接任|接位|繼承)(?:王位)?(?:的|者|人)(?:人|王)?{_WHO_KING}"  # 的繼任者是誰
    rf"|(?:接著|接下來|緊接著){_THRONE_VERB}(?:上)?(?:了)?(?:王位|王|國王)?(?:的)?(?:人|王)?{_WHO_KING})"
)
# the throne changing hands, counted; 傳 and 換 count anything, so 王位 before or 王 after (a bare
# 傳了幾次 at the clause's end was tried and dropped: 亞哈和約沙法之間，結盟傳了幾次)
_HANDS = r"(?:換手|更迭|更替|交替|輪替|交棒)"
_TALLY = r"(?:幾|多少)次"
_S1B_NEW = (
    rf"{_HANDS}(?:了|過)?{_TALLY}"                                          # 換手了幾次, 更迭了幾次
    rf"|王位(?:[,，、\s]|一共|總共|共|前後|中間|先後|總計|合計){{0,12}}"
    rf"(?:傳|換|更換|轉移|傳遞|傳承|易手|轉手|易主|移交)(?:了|過)?{_TALLY}"      # 王位一共傳了幾次
    rf"|(?:傳|換|更換)(?:了|過)?{_TALLY}(?:的)?(?:王位|{_KING})"                # 換了幾次王
    rf"|{_TALLY}(?:的)?(?:王位)?(?:{_HANDS}|易手|轉手|換王|傳承|交接)"          # 經歷了幾次更迭
)
# an ordinal after 之後 (the count runs from the named king), then the throne taken by killing or
# conspiracy: 背叛 and 叛變 alone are no core (a nation's revolt is none); no 被, 遭 or 死 in the rooms
# (第一位被殺的王, 死於政變的王 are the victims)
_USURP = (r"(?:篡|弒|謀反|政變|殺(?:王|君)|殺(?:掉|害|死)?(?:了)?(?:前任|在位|當時)?(?:國王|君王|君主)"
          r"|奪(?:得|取)?(?:了)?(?:王位|國位|政權)|奪位|奪權)")
_AFTER = r"(?:(?:之|以)後|往後|往下|接下來|算起|起算)"
_UROOM = r"[^?？。!！;；被遭死]"
_S1C_NEW = (
    rf"{_AFTER}{_UROOM}{{0,20}}?第{_NUM}(?:個|位|名){_UROOM}{{0,8}}?{_USURP}"     # 之後，第二個靠謀反
    rf"|{_AFTER}{_UROOM}{{0,12}}?{_USURP}{_UROOM}{{0,16}}?(?:的人|者|的王|之人)"
    rf"(?:裡面|裏面|當中|之中|中)?{_SEP}(?:的)?第{_NUM}(?:個|位|名)"              # 奪位的人裡面，第二個
)
# who reigned at the birth: no other kingdom, nation, prophet or parent in the room (希西家出生那一年
# 亞述王是誰; the born line is the king's own kingdom's), nor after the throne word (_OTHER_REALM),
# no year count after it (作王第幾年 is a synchronism)
_NATIONS = r"亞述|巴比倫|迦勒底|埃及|亞蘭|摩押|以東|亞捫|波斯|推羅|西頓|非利士"
_REALMS = rf"以色列|北國|撒馬利亞|{_NATIONS}"
_BORN = r"(?:出生|誕生|出世|降生)"
_BORN_AT = r"(?:的)?(?:時|那(?:一)?年|這(?:一)?年|當年|之時|之年|那(?:一)?天|那時|的年份)"
_BROOM = rf"(?:(?!{_REALMS}|先知|祭司|父|母){_ROOM})"
_REIGNING = r"(?:在位|[作做當坐]王|執政|統治|掌權|當政)"
_ON_THRONE = (rf"(?:在位|[作做當坐](?:著)?{_BROOM}{{0,3}}?王|王{_WHO_KING}|掌權|執政|統治|當政)"
              rf"(?!{_ROOM}{{0,2}}?(?:第|幾|多少|多久))")
_DURING = r"(?:時候|時|期間|年間|時期|年代|任內|那年)"
_S4_NEW = (
    rf"{_BORN}{_BORN_AT}{_BROOM}{{0,14}}?{_ON_THRONE}"                       # 出生那一年，是誰在做王
    # asking which king (出生在西拿基立統治的年代嗎 names the reign it asks about)
    rf"|{_BORN}(?:於|在){_BROOM}{{0,3}}?(?:誰|哪(?:一)?(?:位|個|任)){_BROOM}{{0,6}}?{_REIGNING}(?:的)?{_DURING}"  # 出生於哪一位王在位期間
    # the king named right before it is the one born (group ``adj``): 希西家是在哪位王在位時出生的
    rf"|(?P<adj4>(?:是)?(?:在)?(?:誰|哪(?:一)?(?:位|個|任){_BROOM}{{0,6}}?){_REIGNING}(?:的)?{_DURING}?(?:所)?{_BORN})"
)

CUES = {
    # an ordinal position, or asking who took the throne (not the events around it)
    "S1a": re.compile(rf"(?:之|以)(?:後|前)[，,、\s]*{_KTH}|往(?:前|後)數(?:的)?第{_NUM}(?:位|任|代)"
                      rf"|接續.{{0,6}}?作王的(?:人)?{_WHO}|繼位(?:的|者)(?:人)?{_WHO}"
                      rf"|(?P<new>{_S1A_NEW})"),
    "S1b": re.compile(rf"交接|相隔.{{0,3}}?代|(?P<new>{_S1B_NEW})"),
    # the n-th usurper (an ordinal before 篡, with room for 背叛、殺王 between, as the type's own
    # definition words it), not what a usurper did
    "S1c": re.compile(rf"第{_NUM}(?:個|位|次)?.{{0,12}}?篡|(?P<new>{_S1C_NEW})"),
    # who reigned at a king's birth, not the events of it
    "S4": re.compile(rf"出生(?:的)?(?:時|那年).{{0,12}}?(?:在位|作.{{0,3}}?王|王{_WHO})|(?P<new>{_S4_NEW})"),
}
# a match of a relaxation alternative (group ``new``) counts only after the chain name it starts
# from: this many different ones before it (S1b: its two ends)
_NEW_NEEDS = {"S1a": 1, "S1b": 2, "S1c": 1, "S4": 1}
# ... with no referring phrase in it (拿答之後的那位王以後，第二個謀反的人: the rule seeds look for one
# only between the anchor and the cue's start, with the same words)
REFERRING = re.compile(r"這位|那位|此王|該王|這王|那王|這個王|那個王")
# ... a k = ±1 or reversed-birth one only right after its king (亞撒的繼任者; not 約西亞年間的大祭司
# 希勒家，他的下一任)
_ADJACENT = re.compile(r"(?:二世)?(?:王)?(?:的|之|死後[,，]?)?")
# ... an S1b one only when what changed hands, between the last of them and the count (bracketed
# notes aside), is no other office, thing, reign, kingdom or nation: 從約坦到希西家，大祭司更替了幾次;
# 約坦和亞哈斯在位期間，以色列的王位更迭了幾次 asks the contemporaries, 從亞撒到約沙法，以色列換了幾次王
# another kingdom's throne, which the pattern cannot tell from the kings' own (北國以色列的王位 between
# two kings of Israel is lost with it)
_NOT_THE_THRONE = re.compile(
    rf"祭司|先知|首都|都城|京城|國都|將軍|元帥|首領|聖殿|約櫃|城|妻|妃|后|軍|戰|土地|領土|疆|界|邊|宗主|主權"
    rf"|在位|年間|期間|時期|時間|那些年|猶大|南國|南北|耶路撒冷|{_REALMS}")
# ... and an S4 one only when no other kingdom or nation follows its throne word in the clause
# (希西家出生那一年，作亞述王的是誰; 約坦出生那一年，在位的以色列王是誰)
_OTHER_REALM = re.compile(rf"{_ROOM}{{0,8}}?(?:{_REALMS})")
_BRACKET = re.compile(r"\([^()]*\)")


def _unbracketed(q: str, start: int, end: int) -> str:
    """q[start:end] without the characters inside brackets (a note: 約哈斯（不是以色列的）)."""
    inside = {i for b in _BRACKET.finditer(q) for i in range(b.start(), b.end())}
    return "".join(ch for i, ch in enumerate(q[start:end], start) if i not in inside)


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


def _counts(kind: str, m: re.Match, found: tuple[Mention, ...]) -> bool:
    """A cue match counts: always for the committed alternatives; for a relaxation one (group
    ``new``) only after ``_NEW_NEEDS[kind]`` different chain names and under the guards above."""
    if m.group("new") is None:
        return True
    q = m.string
    before = [n for n in found if n.end <= m.start()]
    if len({n.name for n in before}) < _NEW_NEEDS[kind] or REFERRING.search(m.group(0)):
        return False
    if (m.group("adj") if kind == "S1a" else m.group("adj4") if kind == "S4" else None) is not None:
        if not _ADJACENT.fullmatch(q, before[-1].end, m.start()):
            return False
    if kind == "S1b":
        return not _NOT_THE_THRONE.search(_unbracketed(q, before[-1].end, m.start()))
    if kind == "S4":
        return not _OTHER_REALM.match(q, m.end())
    return True


def _matches(question: str, found: tuple[Mention, ...]) -> Iterator[tuple[str, re.Match]]:
    """(type, match) of every cue match that counts, by start, every start tried."""
    for i in range(len(question)):
        for kind, p in CUES.items():
            m = p.match(question, i)
            if m and _counts(kind, m, found):
                yield kind, m


def cue_kinds(question: str, found: tuple[Mention, ...] = ()) -> set[str]:
    """The types with a cue match that counts in the (NFKC) question, a narrative one included."""
    return {kind for kind, _m in _matches(question, found)}


def first_cue(question: str, found: tuple[Mention, ...] = ()) -> tuple[str, int] | None:
    """(type, start) of the earliest cue in the (NFKC) question, skipping an S1c match that
    overlaps one of ``found``; None without one. Every start is tried, so a skipped match hides
    no later one. A committed alternative's cue wins wherever one is left, so a question the old
    rules took keeps its anchor; only without one does the earliest relaxation cue count (it needs a
    name of ``found`` before it). With ``found`` empty this is the earliest ``search`` of each cue's
    committed alternatives."""
    relaxed = None
    for kind, m in _matches(question, found):
        if kind in _NARRATIVE_ROOM and any(n.start < m.end() and m.start() < n.end for n in found):
            continue
        if m.group("new") is None:
            return kind, m.start()
        if relaxed is None:
            relaxed = kind, m.start()
    return relaxed


def trigger(question: str, names: tuple[str, ...], blockers: tuple[str, ...] = ()) -> Trigger:
    q = unicodedata.normalize("NFKC", question)
    found = find_names(q, names, blockers)
    kings = tuple(m.name for m in found)
    hit = cue_kinds(q, found)
    cues = tuple(t for t in CUES if t in hit)
    return Trigger(bool(kings) and bool(cues), kings, cues)
