"""The Genesis age card's rule seeds (prereg §5.2): the ten steps, in order, each abstention with its reason.

``decide(question, L)`` reads the question once (``trigger.read``) and runs the steps of §5.2 in order:

1. NFKC (``trigger.read``).
2. another book named (``L.other_books``: 路加, 歷代志/代上, 馬太, 希伯來書, 猶大書) -> abstain.
3. the chain names (``trigger.scan`` and ``trigger.counted``: longest first with the blockers; 支派/族
   dropped; 閃 and 他拉 only with another chapter-11 name).
4. a Cain-line name -> abstain; an Abram-family name -> abstain, unless a marker phrase the layer agrees
   with marks a chain name the layer also gives another father as a son (拿鶴's chain marker).
5. the structural pair: every (A, B) of found ids, same chapter, B at least 2 generations below A, every
   other found name A's chain father or B's chain son; the other names are the identifiers (「不在路徑上的辨識詞」),
   so a pair must hold every name a marker phrase or a kinship word marks (「以挪士的父親塞特」 marks 塞特,
   whose marker is on the path); exactly one -> the seeds (A, B), else abstain.
6. a marker phrase stating a father and son the layer does not -> abstain.
7. cues: an age word or a year count, and exactly one event family (birth, written 出生 or 生了;
   death; 洪水 is a family of its own the rule never takes), or with no event the F1 form 「X比Y大
   (幾|多少)歲」. Shape F5 for death, or for birth followed by 「(又|還)活了?(多少|幾)年」; F1 otherwise.
   A death with 「(又|還)活」 asks Y's years after X's death, a death with a span word (相隔 …) the gap of
   two deaths: neither is on the card, so both abstain.
8. roles: every birth cue's born (the nearest name before 出生, after 生了) is B; every death cue's
   dying (the nearest name before) is A; the F1 form's X is A and Y is B; and a 生了 cue's begetter
   (a chain name before it in its clause) is B's chain father, which step 5 never lets through: so
   「他拉生了拿鶴」 (Terah's son) abstains, as the prereg says this step does; and a kinship word with no
   name after it (「X的兒子幾歲」) asks someone the question does not name: abstain.
9. scope = the pool's shape: F1 needs d <= 4 and A alive at B's birth (his age then below his
   lifespan); F5 needs A not taken and B alive at A's death (0 < A's lifespan - his age at B's birth
   < B's lifespan).
10. a yes/no or who-comparison word -> abstain.

Interpretations (every one in the report): a step with several cues of its family holds for each of
them (從X出生到Y出生 abstains at step 8); the role of a marker phrase is the marked name's; the begetter
of step 8 (the prereg's rule names only the born and the dying); the marked names of step 5; the other
quantities of step 7 and the unnamed kin of step 8 (abstentions only: a wrong seed costs far more than an
abstention, §5.6). Rule 7's born person is as written: 「Y是在X幾歲時出生的」 abstains (a P1 question).
No fallback: an abstention means no card. Standard library only.
"""
from __future__ import annotations

from .names import Layer
from .trigger import CLAUSE_ENDS, Mention, Reading, Trigger, nearest_after, nearest_before, read

OK = "ok"
OTHER_BOOK = "點名別的書"
CAIN_LINE = "該隱一線的人名"
ABRAM_FAMILY = "亞伯蘭家族的人名"
NO_PAIR = "沒有結構對"
MARKED_OFF = "辨識詞標的不是種子"
MANY_PAIRS = "結構對不只一對"
MARKER = "辨識詞與層矛盾"
NO_AGE_CUE = "沒有年歲線索"
NO_EVENT_CUE = "沒有事件線索"
MANY_FAMILIES = "事件族不只一個"
FLOOD = "洪水線索"
DEATH_LIVED_ON = "問去世之後又活的年數"
DEATH_SPAN = "問兩人去世相隔的年數"
BORN_NOT_B = "出生者不是後代"
DYING_NOT_A = "去世者不是先祖"
BEGETTER = "生育者不是後代的父親"
OLDER_NOT_AB = "比較的兩人不是先祖與後代"
UNNAMED_KIN = "問的是沒有寫名字的親屬"
F1_FAR = "超出題池形狀：相隔超過四代"
F1_GONE = "超出題池形狀：後代出生時先祖已不在世"
F5_TAKEN = "超出題池形狀：先祖被取去"
F5_GONE = "超出題池形狀：先祖去世時後代不在世"
YES_NO = "是非題或誰比較"
REASONS = {2: (OTHER_BOOK,), 4: (CAIN_LINE, ABRAM_FAMILY), 5: (NO_PAIR, MARKED_OFF, MANY_PAIRS), 6: (MARKER,),
           7: (NO_AGE_CUE, NO_EVENT_CUE, MANY_FAMILIES, FLOOD, DEATH_LIVED_ON, DEATH_SPAN),
           8: (BORN_NOT_B, DYING_NOT_A, BEGETTER, OLDER_NOT_AB, UNNAMED_KIN),
           9: (F1_FAR, F1_GONE, F5_TAKEN, F5_GONE), 10: (YES_NO,)}
MAX_F1_D = 4


def structural_pairs(L: Layer, ids: tuple[str, ...]) -> list[tuple[str, str]]:
    """Step 5: every (A, B) with B >= 2 generations below A and every other id A's father or B's son."""
    out = []
    for a in ids:
        for b in ids:
            d = L.distance(a, b)
            if d is not None and d >= 2 and set(ids) - {a, b} <= {L.father(a), L.son(b)}:
                out.append((a, b))
    return out


def agrees(L: Layer, father: str, son: str) -> bool:
    """The layer states father -> son (an edge, or the conflict edge across the chapters)."""
    return (father, son) in L.parents


def _abram_excused(L: Layer, r: Reading) -> bool:
    return any(L.name[c.marked] in L.son_namesakes and agrees(L, c.father, c.son) for c in r.claims)


def shape(r: Reading) -> tuple[str | None, str]:
    """Step 7: (F1 or F5, OK), or (None, why)."""
    if not r.age_cue:
        return None, NO_AGE_CUE
    fams = {"birth" if c.family == "beget" else c.family for c in r.events}
    if len(fams) > 1:
        return None, MANY_FAMILIES
    if fams == {"flood"}:
        return None, FLOOD
    if fams == {"death"}:
        return (None, DEATH_LIVED_ON) if r.lived_on else (None, DEATH_SPAN) if r.span else ("F5", OK)
    if fams == {"birth"}:
        first = min(c.start for c in r.events)
        return ("F5" if any(s > first for s in r.lived_on) else "F1"), OK
    return ("F1", OK) if r.older else (None, NO_EVENT_CUE)


def begetter(r: Reading, at: int) -> Mention | None:
    """The chain mention before position ``at`` in the same clause (a 生了 cue's subject), or None."""
    m = nearest_before(r.mentions, at)
    return m if m is not None and not any(ch in CLAUSE_ENDS for ch in r.q[m.end:at]) else None


def roles(L: Layer, r: Reading, a: str, b: str) -> str | None:
    """Step 8: why a cue's person is not the seed its role needs, or None."""
    for c in r.events:
        who = nearest_after(r.mentions, c.end) if c.family == "beget" else nearest_before(r.mentions, c.start)
        if c.family in ("birth", "beget") and (who is None or who.id != b):
            return BORN_NOT_B
        if c.family == "death" and (who is None or who.id != a):
            return DYING_NOT_A
        if c.family == "beget" and (f := begetter(r, c.start)) is not None and f.id != L.father(b):
            return BEGETTER
    if any(o != (a, b) for o in r.older):
        return OLDER_NOT_AB
    return UNNAMED_KIN if r.kin_unnamed else None


def scope(L: Layer, a: str, b: str, form: str) -> str | None:
    """Step 9: why the pair is outside the pool's shape for this form, or None."""
    n, t, tb = L.age_at_birth(a, b), L.lifespan[a], L.lifespan[b]
    if form == "F1":
        if L.distance(a, b) > MAX_F1_D:
            return F1_FAR
        return F1_GONE if n is None or (t is not None and n >= t) else None
    if a in L.taken:
        return F5_TAKEN
    return None if None not in (n, t, tb) and 0 < t - n < tb else F5_GONE


def _no(step: int, why: str) -> Trigger:
    return Trigger(False, None, why, step, None)


def decide(question: str, L: Layer) -> Trigger:
    """Prereg §5.2's ten steps, in order (see the module docstring)."""
    r = read(question, L)                                                    # 1, 3
    if r.other_book:                                                         # 2
        return _no(2, OTHER_BOOK)
    if r.cain:                                                               # 4
        return _no(4, CAIN_LINE)
    if r.abram and not _abram_excused(L, r):
        return _no(4, ABRAM_FAMILY)
    pairs = structural_pairs(L, r.ids)                                       # 5
    if not pairs:
        return _no(5, NO_PAIR)
    marked = {c.marked for c in r.claims} | set(r.kin_named)
    pairs = [p for p in pairs if marked <= set(p)]
    if len(pairs) != 1:
        return _no(5, MANY_PAIRS if pairs else MARKED_OFF)
    a, b = pairs[0]
    if any(not agrees(L, c.father, c.son) for c in r.claims):                # 6
        return _no(6, MARKER)
    form, why = shape(r)                                                     # 7
    if form is None:
        return _no(7, why)
    if (why := roles(L, r, a, b)) is not None:                               # 8
        return _no(8, why)
    if (why := scope(L, a, b, form)) is not None:                            # 9
        return _no(9, why)
    if r.yes_no:                                                             # 10
        return _no(10, YES_NO)
    return Trigger(True, (a, b), OK, 0, form)


def rule_seeds(question: str, L: Layer) -> tuple[tuple[str, str] | None, str]:
    """(the rule seeds (A, B) in chain order, OK), or (None, why the rule abstained)."""
    t = decide(question, L)
    return t.seeds, t.reason
