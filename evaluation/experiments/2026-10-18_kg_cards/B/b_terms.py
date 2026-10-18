"""Question templates, kinship-term answer/trap tables and the substring-safe matcher (appendix B).

Matching (prereg §1 normalisation, cards_common.norm): names of the item's gold chain are deleted
from the answer line first (so 「父親甲的兄弟」 reads 「父親的兄弟」); then every accept, trap and
neutral string is matched longest first and each hit is masked before shorter strings are tried
(「曾祖父」 is consumed before 「祖父」 can hit, 「叔父的兒子」 before 「叔父」). Traps are checked on the
line with bracketed text removed (cards_common.strip_parens).
"""
from __future__ import annotations

import re

from b_lib import cc

LIN_Q = "根據經文，{a}的{word}是誰？"
PAIR_Q = "根據經文，{b}是{a}的什麼人？"
LIN_WORDS = {"LIN2": "祖父", "LIN3": "曾祖父", "LIN4": "高祖父"}
_LIN_RE = re.compile(r"根據經文，(.+)的(高祖父|曾祖父|祖父)是誰？")
_PAIR_RE = re.compile(r"根據經文，(.+?)是(.+)的什麼人？")
_K_OF = {"祖父": 2, "曾祖父": 3, "高祖父": 4}

_SEQ = {
    3: (["曾祖父", "曾祖", "祖父的父親", "父親的祖父", "第三代祖先", "第3代祖先", "三世祖"],
        ["高祖父", "高祖", "天祖", "祖父", "父親", "曾祖母", "祖母", "曾曾祖父", "曾曾祖", "四世祖", "五世祖"]),
    4: (["高祖父", "高祖", "曾祖父的父親", "祖父的祖父", "父親的曾祖父", "第四代祖先", "第4代祖先",
         "曾曾祖父", "曾曾祖", "四世祖"],
        ["曾祖父", "曾祖", "天祖", "祖父", "高祖母", "曾祖母", "曾曾曾祖父", "三世祖", "五世祖"]),
    5: (["天祖", "天祖父", "高祖父的父親", "高祖的父親", "曾祖父的祖父", "祖父的曾祖父", "父親的高祖父",
         "第五代祖先", "第5代祖先", "曾曾曾祖父", "五世祖"],
        ["高祖父", "高祖", "曾祖父", "曾祖", "烈祖", "祖父", "高祖母", "曾曾曾曾祖父", "三世祖", "四世祖"]),
}
TERMS = {
    "UNC": (["伯父", "叔父", "伯叔", "叔伯", "叔叔", "伯伯", "父親的兄弟", "父親的弟兄", "父親的哥哥",
             "父親的弟弟", "父親的兄長", "父親兄弟", "父親弟兄"],
            ["祖父", "父親", "堂兄弟", "堂兄", "堂弟", "叔伯兄弟", "伯叔兄弟", "舅舅", "舅父"]),
    "COU": (["堂兄弟", "堂兄", "堂弟", "堂親", "堂哥", "堂弟兄", "叔伯兄弟", "伯叔兄弟", "伯父的兒子",
             "叔父的兒子", "伯叔的兒子", "父親兄弟的兒子", "父親的兄弟的兒子", "父親弟兄的兒子",
             "父親的弟兄的兒子"],
            ["親兄弟", "叔父", "伯父", "伯叔", "叔叔", "伯伯", "表兄弟", "表兄", "表弟", "表親"]),
    "MGF": (["外祖父", "外公", "母親的父親", "媽媽的父親"],
            ["祖父", "父親", "岳父", "舅舅", "舅父", "外祖母", "外婆"]),
    "PGM": (["祖母", "奶奶", "阿嬤", "父親的母親"],
            ["外祖母", "外婆", "母親", "曾祖母", "祖父"]),
    "FIL_M": (["岳父", "岳丈", "丈人", "妻子的父親", "妻的父親", "太太的父親", "配偶的父親", "妃嬪的父親", "妾的父親"],
              ["公公", "父親", "祖父", "外祖父"]),
    "FIL_F": (["公公", "家翁", "丈夫的父親", "夫的父親", "配偶的父親"],
              ["岳父", "岳丈", "丈人", "父親", "祖父"]),
    "DIL": (["媳婦", "兒媳", "兒媳婦", "兒子的妻子", "兒子的妻", "兒子的太太", "兒婦", "兒女的配偶", "兒子的妃嬪",
             "兒子的妾"],
            ["妻子", "女兒", "孫女", "孫媳", "孫媳婦", "女婿"]),
    "DIL_F": (["女婿", "女兒的丈夫", "女兒的夫婿", "女兒的配偶", "兒女的配偶"],
              ["媳婦", "兒媳", "兒子", "丈夫", "孫女婿", "外孫"]),
}


def term_key(typ: str, k: int | None = None, a_gender: str | None = None,
             mid_gender: str | None = None) -> str:
    """SEQ by k; FIL by a's gender (岳父／公公); DIL by the middle child's gender (媳婦／女婿)."""
    if typ == "SEQ":
        return f"SEQ{k}"
    if typ == "FIL":
        return "FIL_F" if a_gender == "F" else "FIL_M"
    if typ == "DIL":
        return "DIL_F" if mid_gender == "F" else "DIL"
    return typ


def term_table(key: str) -> tuple[list[str], list[str]]:
    return _SEQ[int(key[3:])] if key.startswith("SEQ") else TERMS[key]


def question(typ: str, a: str, b: str) -> str:
    if typ in LIN_WORDS:
        return LIN_Q.format(a=a, word=LIN_WORDS[typ])
    return PAIR_Q.format(a=a, b=b)


def parse_question(q: str) -> dict:
    """What the card program reads from the question text: lineal (k) or pair mode. Names come
    from the seed stage, never from here."""
    m = _LIN_RE.fullmatch(q)
    if m:
        return dict(mode="lin", k=_K_OF[m.group(2)])
    if _PAIR_RE.fullmatch(q):
        return dict(mode="pair", k=None)
    raise ValueError(f"not a B template question: {q}")


# ---------------------------------------------------------------- matcher
_MASK = "\u25a1"
_DOTS = re.compile("[\u2027\u00b7\u30fb\u2022\u2219\u22c5]")


def nrm(s: str) -> str:
    """cards_common.norm plus name-dot variants removed (甲\u2027乙 = 甲\u00b7乙 = 甲乙)."""
    return _DOTS.sub("", cc.norm(s))


def _hits(text: str, accept, trap, neutral=()) -> tuple[set, set]:
    """Longest-first scan; returns (accept hits, trap hits); neutral strings are consumed silently."""
    kinds = {}
    for s in neutral:
        kinds.setdefault(nrm(s), "n")
    for s in trap:
        kinds[nrm(s)] = "t"
    for s in accept:
        kinds[nrm(s)] = "a"
    acc, trp = set(), set()
    for s in sorted((s for s in kinds if s), key=lambda s: (-len(s), s)):
        if s in text:
            (acc if kinds[s] == "a" else trp if kinds[s] == "t" else set()).add(s)
            text = text.replace(s, _MASK)
    return acc, trp


def _drop_names(text: str, names) -> str:
    for n in sorted({nrm(x) for x in names if x}, key=len, reverse=True):
        text = text.replace(n, "")
    return text


def judge(line: str | None, key: dict) -> dict:
    """line: cards_common.answer_line output (normalised) or None. key: item answer key."""
    if line is None:
        return dict(ok=0, why="format")
    line = nrm(line)
    if key["kind"] == "name":
        acc, _ = _hits(line, key["accept"], key["trap"], key["neutral"])
        _, trp = _hits(cc.strip_parens(line), key["accept"], key["trap"], key["neutral"])
    else:
        acc, _ = _hits(_drop_names(line, key["names"]), key["accept"], key["trap"])
        _, trp = _hits(_drop_names(cc.strip_parens(line), key["names"]), key["accept"], key["trap"])
    ok = int(bool(acc) and not trp)
    return dict(ok=ok, why="ok" if ok else ("trap" if trp else "miss"), acc=sorted(acc), trap=sorted(trp))


_CLAUSE = re.compile(r"[,，;；。、]|因為|即")


def first_clause(line: str) -> str:
    return _CLAUSE.split(line, 1)[0]


def judge_variants(line: str | None, key: dict) -> dict:
    """Descriptive only (not the prereg metric): ok with traps read on the first clause of the
    answer line, and whether the accept hit exists only inside brackets."""
    if line is None:
        return dict(ok_first_clause=0, accept_only_in_parens=False)
    line = nrm(line)
    names = key.get("names", ())
    prep = (lambda t: t) if key["kind"] == "name" else (lambda t: _drop_names(t, names))
    neutral = key.get("neutral", ())
    acc, _ = _hits(prep(line), key["accept"], key["trap"], neutral)
    acc_np, _ = _hits(prep(cc.strip_parens(line)), key["accept"], key["trap"], neutral)
    _, trp = _hits(prep(first_clause(cc.strip_parens(line))), key["accept"], key["trap"], neutral)
    return dict(ok_first_clause=int(bool(acc) and not trp), accept_only_in_parens=bool(acc) and not acc_np)
