"""Kinship sentence patterns over a verse's encoded text (name tokens become ``⟨k⟩``).

Ported from the PDF-only prototype's ``plus`` and n3-n10 families (kin2.py): omitted 的 and
inserted titles, naming sentences, 是 X 的父親, declared lists, marriages, grandchild appositions
and regnal mothers. Family n9 (a pronoun inside one noun phrase) is not ported: pronouns are not
resolved. n3_sp carries the wife-of-a-relative fix of ``kin_rules``.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Iterator

from ragdata.kg.kin_rules import NUM, OF_A_RELATIVE, PARENT, SIBLING, SPOUSE, Hit
from ragdata.kg.kin_tokens import Verse

_N = r"⟨(\d+)⟩"
_L = rf"((?:{_N}(?:、|，|和|與|及|，和|、和)?){{1,12}})"
_ID = re.compile(_N)
_TITLE = "先知|祭司|大祭司|文士|書記|史官|家宰|軍長|元帥|宦官|省長|族長|首領|王|將軍|勇士|使者|女先知|士師"
_CNT = rf"[{NUM}幾]+個"
_NOT_OF_RELATIVE = rf"(?!{OF_A_RELATIVE})"


def encode(verse: Verse) -> str:
    out, position = [], 0
    for k, token in enumerate(verse.tokens):
        out += [verse.text[position:token.start], f"⟨{k}⟩"]
        position = token.end
    out.append(verse.text[position:])
    return "".join(out)


def _ids(text: str) -> list[int]:
    return [int(x) for x in _ID.findall(text)]


_PLUS = (("P1", re.compile(rf"{_N}又?娶了?(?:[^。；]{{0,30}}?){_N}為妻[，,]?她?(?:給他)?生了{_L}")),
         ("P2", re.compile(rf"{_N}又?娶了?{_N}[，,]生了{_L}")),
         ("P3", re.compile(rf"{_N}的(?:長兄|哥哥|弟弟|兄弟|姊姊|妹妹|姊妹|長姊){_N}")),
         ("P4", re.compile(rf"{_N}的?兒子{_N}的(?:女兒|兒子){_N}")),
         ("P5", re.compile(rf"{_N}是(?:作過)?(?:⟨\d+⟩人)?{_N}(?:所)?生的")),
         ("P6", re.compile(rf"他母親名叫{_N}[，,]是[^。；]{{0,6}}?{_N}的女兒")),
         ("P7", re.compile(rf"{_N}是[^。；]{{0,8}}?{_N}的女兒{_N}所生的")))
_ACCESSION = re.compile(rf"{_N}登基")
# 四子亞多尼雅是哈及所生的: the list is the father's, so whoever bore him is his mother (耶弗他是基列所生的 is no list)
_ORDINAL_END = re.compile(r"(?:長子|次子|三子|四子|五子|六子|七子|八子|九子)$")
# fixes of 2026-11-02 (rules the golden list found missing)
_UNNAMED_WIFE_BORE = re.compile(rf"{_N}又?娶了?{_N}的[^。；⟨]{{0,6}}女兒為妻[，,]?她?(?:給他)?生了{_L}")
_BEGOT_IN_A_PLACE = re.compile(rf"{_N}在{_N}(?:地)?(?:又)?生了?{_L}")


def _plus_hits(tag: str, m: re.Match[str], enc: str) -> Iterator[Hit]:
    g, pattern = m.groups(), f"plus_{tag}"
    if tag in ("P1", "P2"):
        for child in _ids(g[2]):
            yield Hit(int(g[0]), PARENT, child, "F", pattern)
            yield Hit(int(g[1]), PARENT, child, "M", pattern)
    elif tag == "P3":
        yield Hit(int(g[0]), SIBLING, int(g[1]), "-", pattern)
    elif tag == "P4":
        yield Hit(int(g[0]), PARENT, int(g[1]), "P", pattern)
        yield Hit(int(g[1]), PARENT, int(g[2]), "P", pattern)
    elif tag == "P5":
        yield Hit(int(g[1]), PARENT, int(g[0]), "M" if _ORDINAL_END.search(enc[:m.start()]) else "P", pattern)
    elif tag == "P6":
        yield Hit(int(g[1]), PARENT, int(g[0]), "P", pattern)
        kings = _ACCESSION.findall(enc[:m.start()])
        if kings:
            yield Hit(int(g[0]), PARENT, int(kings[0]), "M", pattern)
    elif tag == "P7":
        yield Hit(int(g[1]), PARENT, int(g[2]), "P", pattern)
        yield Hit(int(g[2]), PARENT, int(g[0]), "M", pattern)


def plus(enc: str) -> Iterator[Hit]:
    for tag, rx in _PLUS:
        for m in rx.finditer(enc):
            yield from _plus_hits(tag, m, enc)
    for rx, tag in ((_UNNAMED_WIFE_BORE, "plus_P8"), (_BEGOT_IN_A_PLACE, "plus_P9")):
        for m in rx.finditer(enc):
            yield from (Hit(int(m.group(1)), PARENT, child, "F", tag) for child in _ids(m.group(3)))


_N3 = (("n3_node", re.compile(rf"{_N}(?:之子|兒子)(?:－)?{_N}"), "PAR"),
       ("n3_daughter", re.compile(rf"{_N}(?:之女|女兒)(?:－)?{_N}"), "PAR"),
       ("n3_title", re.compile(rf"{_N}的(?:兒子|女兒)(?:－)?(?:{_TITLE})(?:－)?{_N}"), "PAR"),
       ("n3_gentitle", re.compile(rf"{_N}的(?:兒子|女兒)－{_N}"), "PAR"),
       ("n3_pair", re.compile(rf"{_N}與{_N}之子{_N}"), "PAIR"),
       ("n3_fa", re.compile(rf"{_N}(?:父親|之父)(?:－)?{_N}"), "INV"),
       ("n3_mo", re.compile(rf"{_N}(?:母親|之母)(?:－)?{_N}"), "INV"),
       ("n3_sp", re.compile(rf"{_N}(?:妻子|之妻|的妻子?|的丈夫|丈夫)(?:－)?{_N}{_NOT_OF_RELATIVE}"), "SP"),
       ("n3_sib", re.compile(rf"{_N}(?:兄弟|弟弟|哥哥|的妹子(?:是)?|妹子)(?:－)?{_N}"), "SIB"),
       ("n3_sibtitle", re.compile(rf"{_N}的(?:姊姊|妹妹|哥哥|弟弟|兄弟)(?:{_TITLE})(?:－)?{_N}"), "SIB"),
       ("n3_sibcomma", re.compile(rf"{_N}的(?:姊姊|妹妹|哥哥|弟弟|兄弟)[，、](?:{_TITLE})?{_N}(?!的)"), "SIB"),
       ("n3_sibnamed", re.compile(rf"{_N}有(?:一個)?[^⟨。；]{{0,8}}(?:妹子|妹妹|哥哥|弟弟|兄弟|姊姊)[，]?名叫{_N}"), "SIB"),
       ("n3_issib", re.compile(rf"{_N}不?(?:是|乃是|就是|，是){_N}的(?:哥哥|弟弟|兄弟|姊姊|妹妹|妹子|姊妹)"), "SIB"))
_WIFE_BORE = re.compile(rf"{_N}(?:之妻|的妻子?|妻子|的妾)(?:－)?{_N}(?:的兒子是|所生的(?:兒子)?(?:，就是|是)?|又?生了?){_L}")
# 對摩西說：「…你的哥哥亞倫: 你 is the one spoken to, named in this verse
_ADDRESSED_SIBLING = re.compile(rf"(?:對|向)(?:她|他)?(?:兒子)?{_N}(?:發怒)?說：「[^」]*?你的?(?:哥哥|弟弟|兄弟|姊姊|妹妹)(?:⟨\d+⟩人)?{_N}")


def n3(enc: str) -> Iterator[Hit]:
    for tag, rx, kind in _N3:
        for m in rx.finditer(enc):
            g = [int(x) for x in m.groups()]
            if kind == "PAR":
                yield Hit(g[0], PARENT, g[1], "P", tag)
            elif kind == "PAIR":
                yield Hit(g[0], PARENT, g[2], "M", tag)
                yield Hit(g[1], PARENT, g[2], "F", tag)
            elif kind == "INV":
                yield Hit(g[1], PARENT, g[0], "F" if tag == "n3_fa" else "M", tag)
            else:
                yield Hit(g[0], SPOUSE if kind == "SP" else SIBLING, g[1], "-", tag)
    for m in _WIFE_BORE.finditer(enc):
        for child in _ids(m.group(3)):
            yield Hit(int(m.group(1)), PARENT, child, "F", "n3_wife_bore")
            yield Hit(int(m.group(2)), PARENT, child, "M", "n3_wife_bore")
    for m in _ADDRESSED_SIBLING.finditer(enc):
        yield Hit(int(m.group(1)), SIBLING, int(m.group(2)), "-", "n3_address")


_N4 = (("n4_MF", re.compile(rf"{_N}(?:給|為){_N}(?:又|也|就)?生了?(?:一個|個)?(?:兒子|女兒)[；，。]{_N}?(?:就)?給(?:他|她|孩子)?(?:所生的兒子)?起名叫{_N}")),
       ("n4_MthenF", re.compile(rf"{_N}(?:[^。；「」⟨]{{0,14}}?)(?:懷孕)?[，。]?(?:[^。；「」⟨]{{0,8}}?)生了?(?:一個|個)?(?:兒子|子|女兒)[；，。]?{_N}[^。；「」⟨]{{0,4}}給(?:他|她|孩子)起名叫{_N}")),
       ("n4_P", re.compile(rf"{_N}(?:[^。；「」⟨要必將]{{0,18}}?)生了?(?:一個|個)?(?:兒子|子|女兒)[^。；「」⟨]{{0,14}}?起名叫{_N}")),
       ("n4_FgaveM", re.compile(rf"{_N}給{_N}所生的(?:兒子|女兒)起名叫{_N}")),
       ("n4_namer", re.compile(rf"生了?(?:一個|個)?(?:兒子|子|女兒)[；，。]?{_N}(?:就)?給(?:他|她|孩子)起名叫{_N}")),
       ("n4_Pdot", re.compile(rf"{_N}(?:就|又)?懷孕[。，](?:日期滿足|日期滿了)[，。]?生了?(?:一個|個)?(?:兒子|女兒)[，。]給(?:他|她)起名叫{_N}")))


_GIVEN_TO = ("給", "為")


def n4(enc: str) -> Iterator[Hit]:
    for tag, rx in _N4:
        for m in rx.finditer(enc):
            g = m.groups()
            if tag == "n4_MthenF" and enc[max(0, m.start() - 1):m.start()] in _GIVEN_TO:     # 夏甲給亞伯蘭生了
                continue
            if tag == "n4_MF":
                yield Hit(int(g[0]), PARENT, int(g[3]), "M", tag)
                yield Hit(int(g[1]), PARENT, int(g[3]), "F", tag)
            elif tag == "n4_MthenF":
                yield Hit(int(g[0]), PARENT, int(g[2]), "M", tag)
                yield Hit(int(g[1]), PARENT, int(g[2]), "F", tag)
            elif tag == "n4_FgaveM":
                yield Hit(int(g[0]), PARENT, int(g[2]), "F", tag)
                yield Hit(int(g[1]), PARENT, int(g[2]), "M", tag)
            else:
                role = {"n4_P": "P", "n4_namer": "F", "n4_Pdot": "M"}[tag]
                yield Hit(int(g[0]), PARENT, int(g[1]), role, tag)


_N5 = re.compile(rf"{_N}[，]?(?:是|乃是|就是|，是|，就是){_N}(?:(?:和|、){_N})?的(父親|母親|父|母)(?=[，。；、）」]|$)")


def n5(enc: str) -> Iterator[Hit]:
    for m in _N5.finditer(enc):
        role = "F" if m.group(4).startswith("父") else "M"
        yield Hit(int(m.group(1)), PARENT, int(m.group(2)), role, "n5_isparent")
        if m.group(3):
            yield Hit(int(m.group(1)), PARENT, int(m.group(3)), role, "n5_isparent")


_N6 = (("n6_have", re.compile(rf"{_N}(?:共)?(?:有|生了?){_CNT}(?:兒子|女兒)[，：；]?(?:他們的名字是|就是|名字是|名叫|一個名叫|大的名叫){_L}")),
       ("n6_bore", re.compile(rf"{_N}(?:在{_N})?所生的(?:兒子|女兒|是)(?:是|，就是|有|記在下面：)?(?:長子)?{_L}")),
       ("n6_fam", re.compile(rf"{_N}的(?:兒子|女兒)(?:：|，按着家室，?(?:是)?){_L}")),
       ("n6_kids", re.compile(rf"{_N}的兒女(?:是|有|：)?{_L}")),
       ("n6_yuan", re.compile(rf"{_N}的(?:兒子|女兒)記在下面：(?:{_N}的長子是)?{_L}")),
       ("n6_MF", re.compile(rf"{_N}給{_N}(?:所)?生的(?:{_CNT})?(?:兒子|女兒){_L}")),
       ("n6_MFis", re.compile(rf"{_N}給{_N}所生的(?:{_CNT})?(?:兒子|女兒)(?:是|，就是){_L}")),
       ("n6_two", re.compile(rf"{_N}有{_CNT}女兒，大的名叫{_N}，小的名叫{_N}")))
_N6_LIST_GROUP = {"n6_have": 1, "n6_bore": 2, "n6_fam": 1, "n6_kids": 1, "n6_yuan": 2}


def _list_items(enc: str, listed: str) -> list[int]:
    """The list stops at a token followed by 的／生／給: a new clause, not an item."""
    out = []
    for m in _ID.finditer(listed):
        if enc[enc.find(m.group(0)) + len(m.group(0)):][:1] in ("的", "生", "給"):
            break
        out.append(int(m.group(1)))
    return out


def _n6_hits(tag: str, m: re.Match[str], enc: str) -> Iterator[Hit]:
    g = m.groups()
    if tag == "n6_bore" and enc[max(0, m.start() - 1):m.start()] in ("在", "於", "從"):
        return
    if tag in _N6_LIST_GROUP:
        for child in _list_items(enc, g[_N6_LIST_GROUP[tag]]):
            yield Hit(int(g[0]), PARENT, child, "P", tag)
    elif tag in ("n6_MF", "n6_MFis"):
        for child in _list_items(enc, g[2]):
            yield Hit(int(g[0]), PARENT, child, "M", tag)
            yield Hit(int(g[1]), PARENT, child, "F", tag)
    else:
        yield Hit(int(g[0]), PARENT, int(g[1]), "P", tag)
        yield Hit(int(g[0]), PARENT, int(g[2]), "P", tag)


def n6(enc: str) -> Iterator[Hit]:
    for tag, rx in _N6:
        for m in rx.finditer(enc):
            yield from _n6_hits(tag, m, enc)


_N7 = (("n7_isspouse", re.compile(rf"{_N}[，]?(?:是|乃是|就是|，是|，就是){_N}的(?:妻子|妻|妾|丈夫)(?![的⟨]|所|生)")),
       ("n7_namedwife", re.compile(rf"{_N}(?:又|也|後來|就)?娶(?:了)?(?:[一兩二]個?|一)?妻(?:子)?[，：]?(?:一個)?(?:名叫|是){_N}(?:，一個名叫{_N})?")),
       ("n7_havewives", re.compile(rf"{_N}有{_CNT}妻子?[：，]一(?:名|個名叫){_N}[，；]一(?:名|個名叫){_N}")),
       ("n7_bride", re.compile(rf"{_N}(?:嫁給|歸){_N}為妻")))


def n7(enc: str) -> Iterator[Hit]:
    for tag, rx in _N7:
        for m in rx.finditer(enc):
            g = [int(x) for x in m.groups() if x is not None]
            yield from (Hit(g[0], SPOUSE, other, "-", tag) for other in g[1:])


_GENERATION = {"玄孫": 4, "曾孫": 3, "孫子": 2, "孫女": 2, "兒子": 1, "女兒": 1}
_N8 = re.compile(rf"{_N}的(玄孫|曾孫|孫子|孫女)(?:[、，]|，又是)(?:(?:[^⟨。；]{{0,6}})?)(?={_N}的(曾孫|孫子|孫女|兒子|女兒))")
_N8_REVERSED = re.compile(rf"{_N}的(?:兒子|女兒)[、，]{_N}的(?:孫子|孫女)")


def n8(enc: str) -> Iterator[Hit]:
    """G 的孫子、F 的兒子 → G→F; C 是 F 的兒子，G 的孫子 → G→F."""
    for m in _N8.finditer(enc):
        if _GENERATION[m.group(2)] == _GENERATION[m.group(4)] + 1:
            yield Hit(int(m.group(1)), PARENT, int(m.group(3)), "P", "n8_grand")
    for m in _N8_REVERSED.finditer(enc):
        yield Hit(int(m.group(2)), PARENT, int(m.group(1)), "P", "n8_grand_rev")


_N10 = re.compile(rf"{_N}登基[^。]*。他母親名叫{_N}")


def n10(enc: str) -> Iterator[Hit]:
    for m in _N10.finditer(enc):
        yield Hit(int(m.group(2)), PARENT, int(m.group(1)), "M", "n10_regmother")


FAMILIES: tuple[Callable[[str], Iterable[Hit]], ...] = (plus, n3, n4, n5, n6, n7, n8, n10)


def pattern_hits(verse: Verse) -> list[Hit]:
    enc = encode(verse)
    return [hit for family in FAMILIES for hit in family(enc)]
