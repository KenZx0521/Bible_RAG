"""What the question says, for the Genesis age card's rule (prereg §5.2): ``read`` and ``trigger``.

``read(question, L)`` reads the NFKC question (rule 1) once: whether it names another book (rule 2; 代上
not after a word it ends, as in 後代上); the chain names, scanned longest first together with the blockers
and the Cain-line and Abram-family names (rules 3, 4); the marker phrases 「C的父親N」「F的兒子N」 (also 之父,
之子) and their bracket forms 「N(C的父親)」「N(F的兒子)」, white space allowed between the parts (every
spelling mech_g's marker forms accept, and more) (rule 6); a kinship word right after a name
(``KIN_WORDS``: 「X的孫子Y」 names Y, 「X的兒子」 with no name after it leaves the person asked unnamed); the
cues (rule 7) and the yes/no words (rule 10).
The steps themselves, in order and each abstention with its reason, are ``seeds.decide``; ``trigger`` is its
result. The rule has no fallback, so the trigger fires exactly when the rule seeds are found.

Rule 3 as read here (prereg §5.2-3):
- one scan, longest first, a tie to the leftmost: the 19 chain names, the blockers (the routing lexicon's
  names that hold a chain name, 以諾城, the common words of ``names.COMMON_WORDS`` and the guarded names'
  run-togethers), and the rule-4 names (so 挪亞 in 挪亞大幾歲 is the chain name, never the Cain line's 亞大);
- a blocker never swallows a cue: a blocker overlapping a cue word without holding it is skipped
  (希伯來 in 希伯來到世上, 閃過 in 閃過世), and a cue word inside a name taken is no cue; a rule-4 name's
  common word overlapping a chain name is skipped too (it hides 以拿, never 拿鶴);
- a chain name followed by (半)支派 or 族 is the tribe, not the person;
- a guarded name (``L.guarded``: 閃, 他拉) counts only when another chain name of its chapter counts.

A marker phrase reads as one mention of the marked name N (the nearest-name roles of rule 7 see N, not the
marker inside it). Interpretation (the prereg's rule cannot pass its own F3 pin without it): 洪水 is an
event family of its own, which the rule never takes. Standard library only; every pattern is a fixed
word or a bounded one (``test_gen_confirm_gencard`` times a 500-character adversarial question).
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from .names import Layer, nfkc

# ---------------------------------------------------------------- rule 7 and rule 10 words (prereg §5.2)
AGE_WORDS = ("幾歲", "多少歲", "多大", "年紀", "年齡", "歲數", "高齡", "多老", "年歲")
SPAN_WORDS = ("相隔", "相差", "間隔", "相距", "隔了", "差了")    # optional before (多少|幾)年
YEAR_WORDS = ("多少年", "幾年", "多久")
BIRTH_WORDS = ("出生", "誕生", "出世", "降生", "來到世上")       # the born: the nearest name before
BEGET_WORDS = ("生了", "生下", "生出", "得了")                    # the born: the nearest name after
DEATH_WORDS = ("去世", "過世", "離世", "逝世", "辭世", "死", "壽終", "離開人世")   # the dying: nearest before
FLOOD_WORDS = ("洪水",)                                           # F3's family: never taken
OLDER_WORDS = ("大幾歲", "大多少歲")                              # 「X比Y大(幾|多少)歲」
LIVED_ON_WORDS = ("又活", "還活")                                 # 「(又|還)活了?(多少|幾)年」
YES_NO_WORDS = ("是否", "是不是", "有沒有", "嗎", "誰比較", "哪一位")
# a kinship word right after a name: the person it means is the name after it, or nobody named
KIN_WORDS = ("兒子", "父親", "孫子", "曾孫", "玄孫", "後代", "後裔", "子孫", "兒女", "子女", "長子", "次子", "兄弟",
             "弟兄", "哥哥", "弟弟", "妻子", "母親", "祖父", "祖先", "先祖")
# rule 2: a book abbreviation that also ends a common word (後代上, 年代上, 第三代上) is no book after it
BOOK_NOT_AFTER = {"代上": "後世年時朝古近現當前末第幾每各兩數同隔一二三四五六七八九十百千0123456789"}
CUE_LITERALS = tuple(dict.fromkeys(AGE_WORDS + SPAN_WORDS + YEAR_WORDS + BIRTH_WORDS + BEGET_WORDS + DEATH_WORDS
                                   + FLOOD_WORDS + OLDER_WORDS + LIVED_ON_WORDS + YES_NO_WORDS))
RULE7_WORDS = tuple(w for w in CUE_LITERALS if w not in YES_NO_WORDS)

FAMILY = {**{w: "birth" for w in BIRTH_WORDS}, **{w: "beget" for w in BEGET_WORDS},
          **{w: "death" for w in DEATH_WORDS}, **{w: "flood" for w in FLOOD_WORDS}}
_EVENT = re.compile("|".join(map(re.escape, sorted(FAMILY, key=lambda w: (-len(w), w)))))
_LIVED_ON = re.compile(r"(?:又|還)活了?(?:多少|幾)年")
_TRIBE = re.compile(r"半?支派|族")
_KIN = re.compile("的(?:" + "|".join(KIN_WORDS) + ")|之(?:子|父|孫)")
CLAUSE_ENDS = frozenset(",.?!;:。")                                  # NFKC: ，？！；： are ASCII
FATHER_LINKS, SON_LINKS = ("的父親", "之父"), ("的兒子", "之子")
_OPEN, _CLOSE = "(（", ")）"
_KIND_ORDER = {"blocker": 0, "cain": 1, "abram": 2, "chain": 3}


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    text: str
    kind: str                  # chain, blocker, cain or abram


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    id: str                    # the chain person named here (a marker phrase: the marked one)


@dataclass(frozen=True)
class Claim:
    father: str                # a marker phrase's statement: father is son's father (layer ids)
    son: str
    marked: str                # the name the phrase marks


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    family: str                # birth, beget, death or flood


@dataclass(frozen=True)
class Reading:
    q: str                                 # the NFKC question
    other_book: bool
    ids: tuple[str, ...]                   # counted chain names, distinct ids, in order of appearance
    cain: bool
    abram: bool
    claims: tuple[Claim, ...]
    mentions: tuple[Mention, ...]          # in order; marker phrases as one mention
    kin_named: tuple[str, ...]             # 「X的孫子Y」 (no marker phrase): Y, the person the question means
    kin_unnamed: bool                      # 「X的兒子」 with no name after it: the person asked is unnamed
    age_cue: bool
    events: tuple[Cue, ...]
    span: bool                             # a span word (相隔 …), not inside a name
    older: tuple[tuple[str, str], ...]     # 「X比Y大(幾|多少)歲」: (X, Y)
    lived_on: tuple[int, ...]              # starts of 「(又|還)活了?(多少|幾)年」
    yes_no: bool


@dataclass(frozen=True)
class Trigger:
    fired: bool
    seeds: tuple[str, str] | None          # (ancestor, descendant) in chain order
    reason: str                            # seeds.OK, or why the rule abstained
    step: int                              # the §5.2 step that abstained (0 when it fired)
    shape: str | None                      # F1 or F5 when it fired


def _spans(q: str, words: tuple[str, ...]) -> list[tuple[int, int]]:
    """Every occurrence of every word, overlaps included."""
    out = []
    for w in words:
        i = q.find(w)
        while i >= 0:
            out.append((i, i + len(w)))
            i = q.find(w, i + 1)
    return out


def _swallows(s: int, e: int, cues: list[tuple[int, int]]) -> bool:
    """The blocker q[s:e] overlaps a cue word without holding it."""
    return any(a < e and s < b and not (s <= a and b <= e) for a, b in cues)


def _ws(q: str, i: int) -> int:
    """The first position from i that is not white space (mech_g's \\s)."""
    while i < len(q) and q[i].isspace():
        i += 1
    return i


def scan(q: str, L: Layer) -> tuple[Token, ...]:
    """Chain names, blockers and rule-4 names in q: longest first, a tie to the leftmost, none inside
    one already taken, a blocker swallowing a cue skipped (rule 3)."""
    cues = _spans(q, RULE7_WORDS)
    terms = ([(t, "chain") for t in L.id_of] + [(t, "blocker") for t in L.blockers]
             + [(t, "cain") for t in L.cain_line] + [(t, "abram") for t in L.abram_family])
    occ = [(s, s + len(t), t, k) for t, k in terms for s, _e in _spans(q, (t,))]
    occ.sort(key=lambda o: (o[0] - o[1], o[0], _KIND_ORDER[o[3]]))
    names = [(s, e) for s, e, _t, k in occ if k == "chain"]
    taken = bytearray(len(q))
    out = []
    for s, e, t, k in occ:
        if any(taken[s:e]) or (k == "blocker" and _swallows(s, e, cues)):
            continue
        if t in L.rule4_words and any(a < e and s < b for a, b in names):
            continue
        taken[s:e] = b"\x01" * (e - s)
        out.append(Token(s, e, t, k))
    return tuple(sorted(out, key=lambda t: t.start))


def counted(q: str, L: Layer, tokens: tuple[Token, ...]) -> tuple[Token, ...]:
    """The chain-name tokens that count: not a tribe; a guarded name only with a chapter mate."""
    chain = [t for t in tokens if t.kind == "chain" and not _TRIBE.match(q, t.end)]
    names = {t.text for t in chain}

    def mate(t: Token) -> bool:
        ch = L.chapter[L.id_of[t.text]]
        return any(n != t.text and L.chapter[L.id_of[n]] == ch for n in names)
    return tuple(t for t in chain if t.text not in L.guarded or mate(t))


def _bracketed(q: str, a: Token, b: Token, links: tuple[str, ...]) -> int | None:
    """End of 「a(b<link>)」 (white space allowed around and inside the bracket) right after a, else None."""
    o = _ws(q, a.end)
    if o < len(q) and q[o] in _OPEN and _ws(q, o + 1) == b.start:
        j = _ws(q, b.end)
        for link in links:
            close = _ws(q, j + len(link))
            if q.startswith(link, j) and close < len(q) and q[close] in _CLOSE:
                return close + 1
    return None


def markers(q: str, L: Layer, chain: tuple[Token, ...]) -> tuple[tuple[Claim, ...], tuple[Mention, ...]]:
    """The marker phrases (rule 6) and the mentions they make: 「C的父親N」 and 「F的兒子N」 read as
    one mention of N, from C or F to N; 「N(C的父親)」 and 「N(F的兒子)」 as one of N, to the bracket's end."""
    claims, mentions, absorbed = [], [], set()
    ids = [L.id_of[t.text] for t in chain]
    for i, (a, b) in enumerate(zip(chain, chain[1:])):
        if i in absorbed or i + 1 in absorbed:
            continue
        gap, x, y = "".join(q[a.end:b.start].split()), ids[i], ids[i + 1]
        if gap in FATHER_LINKS or gap in SON_LINKS:
            claims.append(Claim(y, x, y) if gap in FATHER_LINKS else Claim(x, y, y))
            mentions.append(Mention(a.start, b.end, y))
        elif (end := _bracketed(q, a, b, FATHER_LINKS)) is not None:
            claims.append(Claim(x, y, x))
            mentions.append(Mention(a.start, end, x))
        elif (end := _bracketed(q, a, b, SON_LINKS)) is not None:
            claims.append(Claim(y, x, x))
            mentions.append(Mention(a.start, end, x))
        else:
            continue
        absorbed |= {i, i + 1}
    mentions += [Mention(t.start, t.end, ids[i]) for i, t in enumerate(chain) if i not in absorbed]
    return tuple(claims), tuple(sorted(mentions, key=lambda m: m.start))


def _inside(s: int, e: int, tokens: tuple[Token, ...]) -> bool:
    return any(t.start <= s and e <= t.end for t in tokens)


def kin(q: str, mentions: tuple[Mention, ...]) -> tuple[tuple[str, ...], bool]:
    """A kinship word right after a mention (``KIN_WORDS``, 之子, 之父, 之孫; a marker phrase is one mention, so
    its own link is never read here): (the ids named right after one, whether one names nobody)."""
    starts = {m.start: m for m in mentions}
    named, unnamed = [], False
    for m in mentions:
        if (k := _KIN.match(q, _ws(q, m.end))) is not None:
            n = starts.get(_ws(q, k.end()))
            unnamed = unnamed or n is None
            named += [n.id] if n is not None else []
    return tuple(named), unnamed


def _book_named(q: str, books: tuple[str, ...]) -> bool:
    """Rule 2: some book named, a ``BOOK_NOT_AFTER`` abbreviation only where no word ends in it."""
    return any(i == 0 or q[i - 1] not in BOOK_NOT_AFTER.get(b, "") for b in books for i, _e in _spans(q, (b,)))


def _older(q: str, mentions: tuple[Mention, ...]) -> tuple[tuple[str, str], ...]:
    """「X比Y大(幾|多少)歲」 with X and Y mentions written right against 比 and 大."""
    by_end = {m.end: m for m in mentions}
    out = []
    for s, _e in _spans(q, OLDER_WORDS):
        y = by_end.get(s)
        x = by_end.get(y.start - 1) if y is not None and y.start > 0 and q[y.start - 1] == "比" else None
        if x is not None:
            out.append((x.id, y.id))
    return tuple(out)


def read(question: str, L: Layer) -> Reading:
    q = nfkc(question)
    tokens = scan(q, L)
    chain = counted(q, L, tokens)
    claims, mentions = markers(q, L, chain)
    events = tuple(Cue(m.start(), m.end(), FAMILY[m.group(0)]) for m in _EVENT.finditer(q)
                   if not _inside(m.start(), m.end(), tokens))
    age = [s for s in _spans(q, AGE_WORDS + YEAR_WORDS) if not _inside(*s, tokens)]
    kin_named, kin_unnamed = kin(q, mentions)
    return Reading(q=q, other_book=_book_named(q, L.other_books),
                   ids=tuple(dict.fromkeys(L.id_of[t.text] for t in chain)),
                   cain=any(t.kind == "cain" for t in tokens), abram=any(t.kind == "abram" for t in tokens),
                   claims=claims, mentions=mentions, kin_named=kin_named, kin_unnamed=kin_unnamed,
                   age_cue=bool(age), events=events,
                   span=any(not _inside(*s, tokens) for s in _spans(q, SPAN_WORDS)),
                   older=_older(q, mentions), lived_on=tuple(m.start() for m in _LIVED_ON.finditer(q)),
                   yes_no=any(w in q for w in YES_NO_WORDS))


def nearest_before(mentions: tuple[Mention, ...], at: int) -> Mention | None:
    ends = [m.end for m in mentions]
    i = bisect.bisect_right(ends, at)
    return mentions[i - 1] if i else None


def nearest_after(mentions: tuple[Mention, ...], at: int) -> Mention | None:
    starts = [m.start for m in mentions]
    i = bisect.bisect_left(starts, at)
    return mentions[i] if i < len(mentions) else None


def trigger(question: str, L: Layer) -> Trigger:
    """The ten steps of prereg §5.2 on the question (``seeds.decide``): fired with the rule seeds, or why not."""
    from .seeds import decide            # seeds.py reads the question with this module, as backend seeds.py does
    return decide(question, L)
