"""Token-level kinship rules: what stands between two neighbouring name tokens in one verse.

Ported from the PDF-only prototype (store reports/kg_restore_20261102/kg_plan_v2/pdf_only/kin2.py,
its ``k0``). Each rule yields ``Hit`` rows over token indices; a hit never joins two tokens of the
same name.

The fix of 2026-11-02 (the prototype's SPOUSE_OF 0.864): a name after 娶 or 的妻子 may be a relative
of the wife (亞倫娶了亞米拿達的女兒, 猶大的妻子書亞的女兒), not the wife. ``_wife_after_relatives``
walks such a chain to the wife it names; a wife the verse does not name gives no edge.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Iterator, NamedTuple

from ragdata.kg.graph_schema import PARENT, SIBLING, SPOUSE
from ragdata.kg.kin_tokens import Verse

NUM = "〇零一二三四五六七八九十百千兩"
LIST_SEP = frozenset({"、", "和", "與", "及", "以及", "並", "，和", "，並", "、和", "，還有"})
COMMA_SEP = frozenset({"，和", "，並", "，還有"})
APPOS_SUFFIX = ("王－", "王", "元帥", "人")
NONPERSON_SUFFIX = ("女子", "地", "城", "族", "支派", "的女子", "全家")
NOT_BEGETTER_BEFORE = frozenset({"給", "從", "為"})
# X的妻子Y的女兒: Y is the wife's relative (the regex text is shared with the encoded rules)
OF_A_RELATIVE = rf"的(?:[{NUM}]+個)?(?:女兒|孫女|外孫女|妹子|妹妹|姊妹|姊姊|姐姐|長女|次女)"
_OF_A_RELATIVE = re.compile("^" + OF_A_RELATIVE)
# X娶Y兒子Z的女兒W / X娶了Y的女兒，Z的妹妹，W: a link from a relative to the next name
_RELATIVE_LINK = re.compile(r"^(?:的)?(?:兒子|孫子|女兒|孫女|妹妹|妹子|姊姊|姊妹)[，、]?$")
_UNNAMED_RELATIVE = re.compile(rf"^(?:的)?(?:[{NUM}]+個)?(?:兒子|孫子|女兒|孫女|妹妹|妹子|姊姊|姊妹)")

_BEGOT = re.compile(rf"^(?:活到[^，。；]{{1,14}}?歲，|[{NUM}]+歲(?:的時候)?，?)?(?:又|也|就|便|還)?生(?:了)?$")
_FROM_MOTHER_1 = re.compile(r"^從$")
_FROM_MOTHER_2 = re.compile(r"^(?:氏)?(?:又|也)?生(?:了)?$")
_GAVE_HIM = re.compile(r"^(?:給|為)他(?:又|也|就)?生(?:了)?$")
_GIVE_1 = re.compile(r"^(?:給|為)$")
_GIVE_2 = re.compile(r"^(?:又|也|就)?生(?:了)?$")
_CONCEIVE = re.compile(r"^(?:就|又|也|便)?懷孕，?(?:就|又)?生(?:了)?$")
_CHILD_NOUN = re.compile(rf"^的(?:[{NUM}]+個)?(?:長子|次子|三子|四子|五子|六子|七子|兒子們|兒子|女兒們|女兒|長女|次女|小兒子|大兒子|獨生女|眾子)(?:是|有|名叫|叫|就是)?$")
_IS = re.compile(r"^(?:，)?(?:是|乃是|就是)$")
_AFTER_IS_CHILD = re.compile(r"^的(?:兒子|女兒)")
_PARENT_NOUN = re.compile(r"^的(父親|母親)(?:是|名叫|叫|就是)?$")
_SPOUSE_NOUN = re.compile(r"^的(?:妻子|妻|丈夫|妾)(?:是|名叫|叫|就是)?$")
_MARRY = re.compile(r"^(?:就|便|又|也|後來)?娶(?:了)?$")
_DAUGHTER_OF = re.compile(r"^的女兒$")
# 瑪拿西的長子基列之父瑪吉: 基列 only describes 瑪吉, who is the son
_DESCRIBES_THE_NEXT = re.compile(r"^(?:之父|的父親|的父|之母|的母親)$")
_SIB_NOUN = re.compile(r"^的(?:哥哥|弟弟|兄弟|弟兄|姊姊|姐姐|妹妹|姊妹)(?:是|名叫|叫)?$")
_NAMED_CHILD = re.compile(r"^(?:[^。；「」：:的]{0,16}?，)?(?:又|也|就|便)?(?:懷孕，?)?(?:日期滿了，?)?(?:就|又)?生了(?:一個|個)?(?:兒子|女兒)，[^。；「」]{0,24}?起名叫$")


class Hit(NamedTuple):
    head: int
    rel: str
    tail: int
    role: str          # F, M or P for PARENT_OF, "-" otherwise
    pattern: str


def resolve(verse: Verse, index: int) -> int | None:
    """The person a token stands for: past 赫人 and 王 apposition; None for a place or tribe."""
    tokens = verse.tokens
    j = index
    while j < len(tokens):
        after = verse.after(j)
        suffix = next((s for s in APPOS_SUFFIX if after.startswith(s)), None)
        if suffix is not None:
            if j + 1 < len(tokens) and tokens[j + 1].start == tokens[j].end + len(suffix):
                j += 1
                continue
            return j if suffix.startswith("王") else None
        return None if after.startswith(NONPERSON_SUFFIX) else j
    return None


def list_after(verse: Verse, index: int, allow_comma: bool = False) -> list[int]:
    """The tokens of the name list that starts at ``index``."""
    first = resolve(verse, index)
    if first is None:
        return []
    out, k = [first], first
    while k + 1 < len(verse.tokens):
        gap = verse.gap(k, k + 1)
        if gap not in LIST_SEP or (gap in COMMA_SEP and not allow_comma):
            break
        if verse.after(k + 1)[:2].startswith(("生", "的")) or resolve(verse, k + 1) != k + 1:
            break
        out.append(k + 1)
        k += 1
    return out


def _begot(v: Verse, i: int) -> Iterator[Hit]:
    if _BEGOT.match(v.gap(i, i + 1)) and v.preceding_char(i) not in NOT_BEGETTER_BEFORE:
        for child in list_after(v, i + 1):
            yield Hit(i, PARENT, child, "P", "begot")


def _from_mother(v: Verse, i: int) -> Iterator[Hit]:
    if i + 2 < len(v.tokens) and _FROM_MOTHER_1.match(v.gap(i, i + 1)) \
            and _FROM_MOTHER_2.match(v.gap(i + 1, i + 2)):
        for child in list_after(v, i + 2):
            yield Hit(i, PARENT, child, "F", "from_mother")
            yield Hit(i + 1, PARENT, child, "M", "from_mother")


def _gave_birth(v: Verse, i: int) -> Iterator[Hit]:
    gap = v.gap(i, i + 1)
    if _GAVE_HIM.match(gap):
        for child in list_after(v, i + 1):
            yield Hit(i, PARENT, child, "M", "gave_birth_to_him")
    if _GIVE_1.match(gap) and i + 2 < len(v.tokens) and _GIVE_2.match(v.gap(i + 1, i + 2)):
        for child in list_after(v, i + 2):
            yield Hit(i, PARENT, child, "M", "gave_birth_to_X")
            yield Hit(i + 1, PARENT, child, "F", "gave_birth_to_X")
    if _CONCEIVE.match(gap):
        yield Hit(i, PARENT, i + 1, "M", "conceive")


def _child_noun(v: Verse, i: int) -> Iterator[Hit]:
    gap = v.gap(i, i + 1)
    if not _CHILD_NOUN.match(gap):
        return
    person = resolve(v, i + 1)
    if gap.endswith("是") and person is not None and v.after(person).startswith("的"):
        return
    if person is not None and person + 1 < len(v.tokens) and _DESCRIBES_THE_NEXT.match(v.gap(person, person + 1)):
        yield Hit(i, PARENT, person + 1, "P", "child_noun")
        return
    for child in list_after(v, i + 1, gap.endswith(("是", "有"))):
        yield Hit(i, PARENT, child, "P", "child_noun")


def _child_of(v: Verse, i: int) -> Iterator[Hit]:
    gap, after = v.gap(i, i + 1), v.after(i + 1)
    if _IS.match(gap) and _AFTER_IS_CHILD.match(after):
        yield Hit(i + 1, PARENT, i, "P", "is_child_of")
    if gap in ("是從", "從") and after.startswith("生的"):
        yield Hit(i + 1, PARENT, i, "M", "born_from")


def _parent_noun(v: Verse, i: int) -> Iterator[Hit]:
    found = _PARENT_NOUN.match(v.gap(i, i + 1))
    if found:
        parent = resolve(v, i + 1)
        if parent is not None:
            yield Hit(parent, PARENT, i, "F" if found.group(1) == "父親" else "M", "parent_noun")


def _spouse_noun(v: Verse, i: int) -> Iterator[Hit]:
    if _SPOUSE_NOUN.match(v.gap(i, i + 1)):
        wife = resolve(v, i + 1)
        if wife is not None and not _OF_A_RELATIVE.match(v.after(wife)):
            yield Hit(i, SPOUSE, wife, "-", "spouse_noun")


def _wife_after_relatives(v: Verse, index: int) -> int | None:
    """The wife after 娶: through 大衛兒子耶利摩的女兒瑪哈拉 to 瑪哈拉; None if she is not named."""
    j = resolve(v, index)
    if j is None:
        return None
    while j + 1 < len(v.tokens) and _RELATIVE_LINK.match(v.gap(j, j + 1)):
        j += 1
    return None if _UNNAMED_RELATIVE.match(v.after(j)) else j


def _marry(v: Verse, i: int) -> Iterator[Hit]:
    if not _MARRY.match(v.gap(i, i + 1)):
        return
    if i + 2 < len(v.tokens) and _DAUGHTER_OF.match(v.gap(i + 1, i + 2)):
        yield Hit(i, SPOUSE, i + 2, "-", "marry_daughter")
        yield Hit(i + 1, PARENT, i + 2, "P", "marry_daughter")
        return
    wife = _wife_after_relatives(v, i + 1)
    if wife is not None:
        yield Hit(i, SPOUSE, wife, "-", "marry")


def _give_as_wife(v: Verse, i: int) -> Iterator[Hit]:
    if v.gap(i, i + 1) == "給" and v.after(i + 1).startswith("為妻"):
        yield Hit(i + 1, SPOUSE, i, "-", "give_as_wife")


def _sibling_noun(v: Verse, i: int) -> Iterator[Hit]:
    if _SIB_NOUN.match(v.gap(i, i + 1)):
        yield Hit(i, SIBLING, i + 1, "-", "sibling_noun")


def _named_child(v: Verse, i: int) -> Iterator[Hit]:
    if _NAMED_CHILD.match(v.gap(i, i + 1)):
        yield Hit(i, PARENT, i + 1, "P", "named_child")


RULES: tuple[Callable[[Verse, int], Iterable[Hit]], ...] = (
    _begot, _from_mother, _gave_birth, _child_noun, _child_of, _parent_noun, _spouse_noun, _marry,
    _give_as_wife, _sibling_noun, _named_child)


def token_hits(verse: Verse) -> list[Hit]:
    """Every token rule over every pair of neighbouring tokens."""
    names = [t.norm_key for t in verse.tokens]
    return [hit for i in range(len(names) - 1) for rule in RULES for hit in rule(verse, i)
            if names[hit.head] != names[hit.tail]]
