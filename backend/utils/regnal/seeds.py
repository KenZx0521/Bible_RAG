"""The chronology card's seeds, the starting kings: rules first, the gemma seed call as fallback.

``rule_seeds`` (2026-10-19) reads them from the question by program and gives layer node ids
directly, or abstains with a reason. Only then does the seed call run: experiment A's
seeds_a.py, verbatim but its imports and the overlong-line skip (MAX_LINE_CHARS). gemma reads
the question and the retrieved passages once and names the starting kings as 「國別｜王名」
lines (≤2); ``parse_seeds`` turns them into (kingdom, name) pairs that ``engine.resolve``
maps to layer nodes.

The rules, on the NFKC question:

1. names: ``trigger.find_names`` (chain names with the lexicon's blockers, longest first).
2. father markers: F in 「F(王)的兒子X」「F(王)之子X」「X(F(王)的兒子)」「X(父親(是)F)」「X,父(親)F」,
   X a chain name (二世 may follow it), is no seed; it only splits X's homonyms (2ki.9.2's
   約沙法的兒子耶戶 is Jehu alone).
3. anchor: before the earliest cue (``trigger.first_cue``; an S1c match holding a king's name,
   亞撒第三年巴沙篡位, is narrative) only, and never a name in a bracket. S1b takes the two
   ends of 「從/由/自 X … 到/至 Y」, or the only two names before the cue; the other types the
   name nearest the cue. A name after the cue (an answer candidate) is never a seed.
4. abstain: no name before the cue; a seed followed by 的兒子／之子／的女兒／的妻子／… (the seed
   is a relative); 這位／那位／此王／該王 … between the anchor and the cue (the seed is
   described); S1b with not exactly two kings; a father written for a unique name that is not
   the layer's (希勒家的兒子以利亞敬 is not the king).
5. kingdom: 「猶大(國)(的)王X」「以色列(國)(的)王X」 binds X (a hard condition); else the
   question's one kingdom word, when only one of 猶大／以色列 occurs, splits homonyms.
6. homonyms: 「X二世」 the later one; the candidate whose layer father the marker or the
   written father names; a written father naming none of them picks the one fatherless
   candidate only when it ends in a name the lexicon or the chain knows (尼八的兒子耶羅波安);
   else abstain. A written father that names no one is none: a kingdom, or, ending in no known
   name, a pronoun or title (他的兒子, 那位王的兒子).

Only chain nodes (kingdom I or J) are candidates, never a king off the chains (kingdom U).
The rules were written after reading experiment A's 62 questions: their agreement with the
gold seeds there is in-sample (``test_regnal_seeds``). A code review the same day (2026-10-19)
added the pronoun and title fathers, the S1c match holding a name, the bracket's names, 「F王的兒子」,
「(父親(是)F)」 and the relatives written with 之 or other kin words: the 62 questions and the
500-question GT (v1, v2) give the same ids and reasons before and after, on layers 932d2242
and a scratch layer with the Solomon fix.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from ragcommon.regnal import KINGDOMS

from utils.regnal.layer import RegnalLayer
from utils.regnal.trigger import REFERRING as _REFERRING
from utils.regnal.trigger import Mention, cue_kinds, find_names, first_cue

# experiment A's cards_common.strip_parens (bracketed text, innermost first)
_PARENS = re.compile(r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")


def strip_parens(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, _PARENS.sub("", s)
    return s


SEED_SYSTEM = """你是資訊抽取工具，只負責找出問題裏的王。
規則：
1. 只找問題直接點名、或用事蹟描述的以色列王或猶大王，作為推算的起點；可以讀經文段落來辨認是哪一位王
2. 不要回答問題，不要推算問題要問的答案
3. 只輸出指定格式的行，不要輸出任何其他文字"""

SEED_USER = """以下是經文段落：

{context}

---

問題：{question}

請列出這個問題點名或描述的王（推算的起點，不是問題要問的答案），最多 2 位，每位一行，格式：
國別｜王名
國別只寫「猶大」或「以色列」；王名用經文中的寫法。"""

MAX_SEEDS = 2
# backend only: a 「國別｜王名」 line is short; longer lines (a model stuck in a whitespace loop)
# are skipped before _LINE, whose backtracking grows polynomially with the line's length.
# Every recorded seed line of experiment A is far below this (test_regnal_parity).
MAX_LINE_CHARS = 64
_SEP = "｜|:："
_LABEL = re.compile(r"(?:國別|王名|名字|國家)\s*[:：]")
_ROW = re.compile(r"^\|(.*)\|$")
_LINE = re.compile(rf"^[\s\-*•·>#\d.、)）]*(?P<k>[^{_SEP}\n]{{1,12}}?)\s*[{_SEP}]\s*(?P<n>[^{_SEP}\n]{{1,20}}?)\s*[{_SEP}]?\s*$")
_NAME = re.compile(r"[一-鿿‧]{1,6}")


def seed_user(context: str, question: str) -> str:
    return SEED_USER.format(context=context, question=question)


def _kingdom(s: str) -> str | None:
    if "猶大" in s:
        return "J"
    if "以色列" in s:
        return "I"
    return None


def _name(s: str) -> str | None:
    s = strip_parens(unicodedata.normalize("NFKC", s))
    s = re.sub(r"[*_`#\s]", "", s)
    s = re.sub(r"^(?:猶大|以色列)(?:國)?王?", "", s)
    s = re.sub(r"王$", "", s)
    m = _NAME.fullmatch(s)
    return m.group(0) if m else None


def clean_line(raw: str) -> str:
    """NFKC; drop 國別：/王名： labels and the outer pipes of a Markdown table row."""
    s = _LABEL.sub("", unicodedata.normalize("NFKC", raw).strip())
    m = _ROW.match(s.strip())
    return m.group(1).strip() if m else s.strip()


def parse_seeds(text: str) -> list[tuple[str, str]]:
    """Up to two distinct (kingdom, name) from 「國別｜王名」 lines (｜ | ： : accepted, also
    「國別：猶大｜王名：希西家」 and table rows 「| 猶大 | 希西家 |」); a line without 猶大 or 以色列 in
    its first field, or without a 1–6 character name, is skipped."""
    out = []
    for raw in (text or "").splitlines():
        line = clean_line(raw)
        if len(line) > MAX_LINE_CHARS:
            continue
        m = _LINE.match(line)
        if not m:
            continue
        kd, nm = _kingdom(m.group("k")), _name(m.group("n"))
        if kd and nm and (kd, nm) not in out:
            out.append((kd, nm))
        if len(out) == MAX_SEEDS:
            break
    return out


# --- rule seeds (on the NFKC question: （） are () there, ， is ,) ---------------------------------

_KD_WORD = {"猶大": "J", "以色列": "I"}
_KD_PREFIX = re.compile(r"(猶大|以色列)國?的?王$")
_CJK = "[一-鿿‧]"
_SON = r"王?(?:的兒子|之子)"                     # 「F的兒子」「F王的兒子」「F之子」
_FATHER_OF = re.compile(_SON)
_FATHER_LABEL = re.compile(r"[,、]?(?:父親?|其父)(?:是|為|名叫)?$")
# the bracket right after a name (二世 between), and a father written in it:
# 「(F的兒子)」「(F王的兒子)」「(父親是F)」
_ANNOTATION = re.compile(r"(?:二世)?\(([^()]*)\)")
_FATHER_IN = re.compile(rf"({_CJK}{{1,8}}?){_SON}|(?:父親?|其父)(?:是|為|名叫)?({_CJK}{{1,8}}?)王?")
_FATHER_BEFORE = re.compile(rf"({_CJK}{{1,4}}?){_SON}$")
# a written "father" that names no one: a kingdom (以色列王的兒子), or, ending in no known name,
# a pronoun or a title (他, 那位, 這個; 王 is already dropped)
_KINGDOM = re.compile(r"(?:猶大|以色列)國?")
_NO_ONE = re.compile(r"[他她其祂位個們人]$")
_RELATIVE = re.compile(r"(?:的|之)(?:兒子|女兒|孫子|曾孫|長子|次子|子孫|後裔|妻子|妻|王后|太后|父親|母親|祖父|祖母"
                       r"|兄弟|弟弟|哥哥|姊妹|姐妹)|之(?:子|女|父|母)")
_BRACKETED = re.compile(r"\([^()]*\)")
_OPENERS, _CLOSERS = "(【[", ")】]"
_SPAN = re.compile(r"(?:從|由|自)(?P<a>[^,;。?!到至]{1,16}?)(?:到|至)(?P<b>[^,;。?!]{1,16})")


class RuleSeeds(NamedTuple):
    ids: tuple[str, ...]      # chain node ids (kingdom I or J) in anchor order, ≤ MAX_SEEDS; () = abstain
    reason: str | None        # why the rules abstained


def _annotation(q: str, m: Mention) -> re.Match | None:
    """The bracket written right after a name (「X(…)」「X二世(…)」), group 1 its text."""
    return _ANNOTATION.match(q, m.end)


def _markers(q: str, found: tuple[Mention, ...]) -> dict[Mention, Mention]:
    """Father marker -> the chain name it fathers: 「F(王)的兒子X」, 「X(F(王)的兒子)」,
    「X(父親(是)F)」, 「X,父親F」."""
    at_start, at_end = {m.start: m for m in found}, {m.end: m for m in found}
    out = {}
    for f in found:
        of = _FATHER_OF.match(q, f.end)
        if of and of.end() in at_start:
            out[f] = at_start[of.end()]
            continue
        label = _FATHER_LABEL.search(q[:f.start])
        if label and label.start() in at_end:
            out[f] = at_end[label.start()]
    for x in found:
        note = _annotation(q, x)
        father = note and _FATHER_IN.fullmatch(note.group(1))
        if father:
            g = 1 if father.group(1) else 2
            end = note.start(1) + father.end(g)
            out.update({f: x for f in found if f.end == end and note.start(1) <= f.start})
    return out


def _known(word: str, known: frozenset[str]) -> bool:
    """The word ends in a name of two or more characters the lexicon or the chain knows (尼八,
    亞比亞他; 王亞哈謝 ends in 亞哈謝)."""
    return any(word[i:] in known for i in range(len(word) - 1))


def _names_someone(father: str | None, known: frozenset[str]) -> str | None:
    """The written father, or None when it names no one: a kingdom, or a word ending in no known
    name that is one character or ends in a pronoun or title (他, 阿施和他, 那位). Another word
    (祭司) is kept: it still contradicts a unique king's layer father."""
    if not father or _KINGDOM.fullmatch(father):
        return None
    if _known(father, known):
        return father
    return None if len(father) < 2 or _NO_ONE.search(father) else father


def _father_written(q: str, m: Mention, known: frozenset[str]) -> str | None:
    """The father written next to a name, on the chain or not: in the bracket right after it
    (「X(F的兒子)」「X(父親是F)」), or 「F的兒子X」 right before it (F: the 1–4 characters before
    (王)的兒子, so possibly more than F); None for one that names no one (``_names_someone``)."""
    note = _annotation(q, m)
    father = note and _FATHER_IN.fullmatch(note.group(1))
    if father:
        return _names_someone(father.group(1) or father.group(2), known)
    before = _FATHER_BEFORE.search(q[:m.start])
    return _names_someone(before.group(1), known) if before else None


def _in_brackets(q: str) -> list[bool]:
    """Per character of q: inside a bracket (（） 【】 [], nested or not)."""
    depth, out = 0, []
    for ch in q:
        if ch in _CLOSERS:
            depth = max(0, depth - 1)
        out.append(depth > 0)
        if ch in _OPENERS:
            depth += 1
    return out


def _after(q: str, m: Mention) -> str:
    """The text after a name, its brackets and a 二世 dropped (what a relative word follows)."""
    return strip_parens(q[m.end:]).removeprefix("二世")


def _kingdoms(q: str, m: Mention) -> tuple[str | None, str | None]:
    """(the kingdom a 「猶大王X」 prefix binds, the question's one kingdom word)."""
    prefix = _KD_PREFIX.search(q[max(0, m.start - 8):m.start])
    words = {kd for w, kd in _KD_WORD.items() if w in q}
    return (_KD_WORD[prefix.group(1)] if prefix else None), (next(iter(words)) if len(words) == 1 else None)


def _node(V, q: str, m: Mention, father: str | None, known: frozenset[str]) -> tuple[str | None, str | None]:
    """The chain node a named king is, or (None, why); ``father``: a chain-name marker's."""
    strict, soft = _kingdoms(q, m)
    cands = [x for kd in KINGDOMS for x in V.chain.get(kd, ())
             if (strict is None or kd == strict) and m.name in V.names(x)]
    if len(cands) > 1 and strict is None and soft:
        cands = [x for x in cands if V.nodes[x]["kingdom"] == soft] or cands
    if not cands:
        return None, "no node"
    written = _father_written(q, m, known)
    if len(cands) == 1:
        layer_father, given = V.nodes[cands[0]]["father"], written or father
        if given and layer_father and not given.endswith(layer_father):
            return None, "father contradicts the layer"
        return cands[0], None
    if q.startswith("二世", m.end) and len({V.nodes[x]["kingdom"] for x in cands}) == 1:
        return max(cands, key=V.idx), None
    # a father naming none of them picks the fatherless one only when it is a known name
    for given, trusted in ((father, True), (written, bool(written) and _known(written, known))):
        if given:
            named = [x for x in cands if V.nodes[x]["father"] and given.endswith(V.nodes[x]["father"])]
            if not named and trusted:
                named = [x for x in cands if not V.nodes[x]["father"]]
            if len(named) == 1:
                return named[0], None
    return None, "homonym"


def _span(q: str, before: list[Mention]) -> list[Mention] | None:
    """S1b's two kings: the ends of 「從 X … 到 Y」 when written, else the only two names before
    the cue; None when that is not two."""
    for s in _SPAN.finditer(q):
        a = [m for m in before if s.start("a") <= m.start < s.end("a")]
        b = [m for m in before if s.start("b") <= m.start < s.end("b")]
        if len(a) == 1 and b and a[0].name != b[0].name:
            return [a[0], b[0]]
    firsts: dict[str, Mention] = {}
    for m in before:
        firsts.setdefault(m.name, m)
    return list(firsts.values()) if len(firsts) == 2 else None


def rule_seeds(layer: RegnalLayer, question: str) -> RuleSeeds:
    """The question's starting kings as chain node ids, or () and why the rules abstain (the
    caller then falls back to the gemma seed call)."""
    q = unicodedata.normalize("NFKC", question)
    found = find_names(q, layer.names, layer.blockers)
    if not found:
        return RuleSeeds((), "no chain name")
    markers = _markers(q, found)
    fathers = {x: f.name for f, x in markers.items()}
    cue = first_cue(q, found)
    if cue is None:
        return RuleSeeds((), "every cue holds a name" if cue_kinds(q, found) else "no cue")
    kind, at = cue
    bracketed = _in_brackets(q)
    before = [m for m in found if m not in markers and m.end <= at and not bracketed[m.start]]
    if not before:
        return RuleSeeds((), "no anchor before the cue")
    picked = _span(q, before) if kind == "S1b" else [before[-1]]
    if picked is None:
        return RuleSeeds((), "S1b: not exactly two kings")
    if any(_RELATIVE.match(_after(q, m)) for m in picked):
        return RuleSeeds((), "the anchor's relative")
    if _REFERRING.search(_BRACKETED.sub("", q[picked[-1].end:at])):
        return RuleSeeds((), "a referring phrase")
    known = layer.lexicon_names | frozenset(layer.names)
    ids: list[str] = []
    for m in picked:
        # a father written anywhere for the same name counts (the first mention may carry it)
        father = fathers.get(m) or next((f for x, f in fathers.items() if x.name == m.name), None)
        x, why = _node(layer.view, q, m, father, known)
        if x is None:
            return RuleSeeds((), f"{why}: {m.name}")
        if x not in ids:
            ids.append(x)
    return RuleSeeds(tuple(ids[:MAX_SEEDS]), None)
