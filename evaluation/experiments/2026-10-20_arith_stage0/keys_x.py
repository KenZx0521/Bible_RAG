"""Answer keys of the ordered-chain arithmetic stage-0 (prereg §5): experiment A's rules, copied and changed here.

Answer line: score_a.answer_text, but a list marker is dropped only when whitespace follows it (「41.」 and
「41.5年」 are kept). Number keys (S5, S6, GEN): ``final_value`` is prereg §5's rule ``final`` —
  0. NFKC, Markdown and whitespace removed (cards_common.norm); text in 「」『』“” removed when an accepted
     value remains outside the quotes (執行紀錄); bracketed text removed; verse citations removed, a
     cross-chapter list such as 「15:25-16:8」 or 「15:25、16:8」 whole (a number written with its unit is
     kept); ordinals 「第N…」 removed, except that an ordinal key (F3) reads 「第N年」 as N years; the total
     words become a marker (共同, 共活, 一共活, 總共活 are not total words); when the last conclusion word
     (所以, 因此, 因而, 故而, 於是, 可知, 總之, 綜上, 最終, 故) comes after the last 「=」 and an accepted value
     follows it, steps 1–4 read only the text after it (執行紀錄);
  1. an equals sign: the first accepted value after the last 「=」 (or a bare number within 2 characters);
     when the right side is a sum or a difference (+, 加, -, −, 減), the value just before the first 「=」;
  2. else the last total word whose next number is an accepted value: that value; a total word whose next
     number is a count, a bare number or another unit is skipped;
  3. else a line holding one number: that number;
  4. else the first 「;」 segment holding an accepted value: its last accepted value before the first cue
     word (因為, 其中, 分別, 計算方式, 計算過程, 共活, 總壽數, 享壽, 壽數, 活了) that follows the segment's
     first accepted value (執行紀錄).
Accepted values: the key's first class present in the line (``classes`` in priority order: S5 年; S6, F1,
F5 歲, then 年 when the line has no 歲; F3 年). A number with any other unit is never taken. Exact match
only: a range or an alternative (「40到41年」「40或41年」) or 多／餘／左右 gives no value and the trap
``hedge``. ``distractor`` names the precomputed wrong values an answer matched (description only).
``score_any`` (sensitivity, 執行紀錄): 1 when the score is 1 or the line writes the gold as an accepted
value (a bare number only when it is the line's one number) that is not inexact or hedged (``gold_written``).
Name keys (SYNC): one keys_a.item_ctx per key, each with that key's kingdom and only that key; trap
exemption = every name of the chain kings (seed to target, plus the synchronised king) and the key's
accept list (confirm_A.md §6.1 ``chain``). Both keys hit with no trap = 1; ``score_z`` is the Z key alone;
``score_any`` is the score itself (SYNC keeps the strict rule only: it is described, never judged).
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from typing import NamedTuple

import x_common as X
from keys_a import CITE, item_ctx, king_lexicon, score_line
from score_a import ANS, MD

cc = X.cc

# ---------------------------------------------------------------- answer line
LIST_X = re.compile(r"^(?:[-+•·]|[0-9]{1,2}[.、)]|\([0-9]{1,2}\))(?=\s)")


def answer_text_x(content: str | None) -> str | None:
    """score_a.answer_text with list markers stripped only when whitespace follows them."""
    text = MD.sub("", unicodedata.normalize("NFKC", content or ""))
    ms = list(ANS.finditer(text))
    if not ms:
        return None
    lines = []
    for ln in text[ms[-1].end():].splitlines():
        s = cc.norm(LIST_X.sub("", ln.strip()))
        if s:
            lines.append(s)
        elif lines:
            break
    return ";".join(lines) or None


# ---------------------------------------------------------------- numbers and units
CN = "零〇一二兩三四五六七八九十百千"
NUM = rf"[0-9]+(?:\.[0-9]+)?|[{CN}]+"
UNITS = {"個月": "M", "年": "Y", "載": "Y", "歲": "A", "月": "M", "日": "D", "天": "D",
         "次": "C", "代": "C", "任": "C", "位": "C", "王": "C", "人": "C", "名": "C", "個": "C", "章": "R", "節": "R"}
_UNIT_ALT = "|".join(sorted(UNITS, key=len, reverse=True))
TOK = re.compile(rf"(?<![{CN}0-9.])({NUM})(多|餘)?(?:({_UNIT_ALT})(半)?(多|餘)?(?:(?:又|零)?({NUM})個?月)?)?")
LONE = set("一十百千兩零〇")   # one-character numerals that mostly form words (一生, 百姓, 兩者) without a unit
INEXACT_AFTER = re.compile(r"多|餘|左右")
ALT = re.compile(r"^,?(?:或者|或是|還是|或|至|到|~|〜|-|–|—|/),?$")
APPROX = re.compile(r"(?:大約|大概|差不多|約)$")

_CITE_LIST = "(?:[-~–,、][0-9]+)*"   # keys_a.CITE's verse list; a number with a unit leaves it
if CITE.pattern.count(_CITE_LIST) != 1:
    raise SystemExit("keys_a.CITE changed: its verse-list part is not found once")
CITE_X = re.compile(CITE.pattern.replace(_CITE_LIST, rf"(?:[-~–,、][0-9]+(?![0-9]*(?:{_UNIT_ALT})))*"))
# 「15:25-16:8」「15:25、16:8」: CITE stops at the second chapter, leaving its verse as a bare number
CITE_CHAIN = re.compile(rf"[0-9]+:[0-9]+(?:[-~–,、](?:[0-9]+:)?[0-9]+(?![0-9]*(?:{_UNIT_ALT})))*")
QUOTE = re.compile(r"「[^「」]*」|『[^『』]*』|“[^“”]*”")
CONCL = re.compile(r"所以|因此|因而|故而|於是|可知|總之|綜上|最終|故(?![事意])")
CUE = re.compile(r"因為|其中|分別|計算方式|計算過程|共活|總壽數|享壽|壽數|活了")
SUM_OPS = ("+", "加", "-", "−", "減")
ORD = re.compile(rf"第({NUM})(個)?({_UNIT_ALT})?")
TOTAL = re.compile(r"(?:一共|總共|合共)(?![同活])|共計|合計|總計|累計|加起來|加總|總和|相加|合起來|總數|共(?![同活])")
MARK, CUT = "§", "¦"


class Tok(NamedTuple):
    start: int
    end: int
    value: Fraction
    cls: str | None      # Y A M D C R; None = bare
    inexact: bool


def cn2int_x(s: str) -> int | None:
    """cards_common.cn2int plus 千 (一千零五十六, 一千六百五十六, 兩千)."""
    if "千" not in s:
        return cc.cn2int(s)
    head, _, tail = s.partition("千")
    if "千" in tail:
        return None
    h = 1 if head in ("", "一") else cc.cn2int(head)
    t = 0 if tail == "" else cc.cn2int(tail.lstrip("零〇"))
    return None if h is None or t is None else h * 1000 + t


def num_value(s: str) -> Fraction | None:
    if s[0].isdigit():
        return Fraction(s.replace(",", ""))
    v = cn2int_x(s)
    return None if v is None else Fraction(v)


def clean(line: str, key: dict | None = None) -> str:
    """Step 0: normalised, brackets, citations and ordinals removed, total words marked."""
    ordinal = bool((key or {}).get("ordinal"))

    def ordinal_sub(m: re.Match) -> str:
        return m.group(1) + "年" if ordinal and m.group(3) == "年" else CUT

    s = cc.strip_parens(cc.norm(line))
    s = CITE_X.sub(CUT, CITE_CHAIN.sub(CUT, s))
    s = ORD.sub(ordinal_sub, s)
    return TOTAL.sub(MARK, s)


def tokens(s: str) -> list[Tok]:
    out = []
    for m in TOK.finditer(s):
        raw, more1, unit, half, more2, mon = m.groups()
        if unit is None and more1 is None and len(raw) == 1 and raw in LONE:
            continue
        v = num_value(raw)
        if v is None:
            continue
        cls = UNITS[unit] if unit else None
        if half:
            v += Fraction(1, 2)
        if mon and cls == "Y":
            mv = num_value(mon)
            v += (mv or 0) / 12
        inexact = bool(more1 or more2 or INEXACT_AFTER.match(s, m.end()))
        out.append(Tok(m.start(), m.end(), v, cls, inexact))
    return out


def accepted(toks: list[Tok], classes: list[str]) -> set[str]:
    """The key's first class with a value in the line (年 counts for an age key only without 歲)."""
    for c in classes:
        if any(t.cls == c for t in toks):
            return {c}
    return set(classes)


def hedged(i: int, toks: list[Tok], s: str) -> bool:
    t = toks[i]
    for j in (i - 1, i + 1):
        if not 0 <= j < len(toks):
            continue
        u = toks[j]
        gap = s[u.end:t.start] if j < i else s[t.end:u.start]
        if ALT.match(gap) and (u.cls == t.cls or u.cls is None or t.cls is None) and u.value != t.value:
            return True
    return False


def _out(v: Fraction | None) -> int | float | None:
    if v is None:
        return None
    return int(v) if v.denominator == 1 else float(v)


def _pick(i: int, toks: list[Tok], s: str, how: str, extra: list[str]) -> tuple[int | float | None, list[str]]:
    t = toks[i]
    if t.inexact:
        return None, [how, "inexact"] + extra
    if hedged(i, toks, s):
        return None, [how, "hedge"] + extra
    if APPROX.search(s[max(0, t.start - 3):t.start]):
        extra = extra + ["approx"]
    return _out(t.value), [how] + extra


def unquoted(line: str, key: dict) -> str:
    """Step 0: text in 「」『』“” removed when an accepted value remains outside the quotes (else the line)."""
    acc = accepted(tokens(clean(line, key)), key["classes"])
    unq = QUOTE.sub("", cc.norm(line))
    return unq if any(t.cls in acc for t in tokens(clean(unq, key))) else line


def final_value(line: str, key: dict) -> tuple[int | float | None, list[str]]:
    """The answer's asserted value (prereg §5 rule final) and how it was found (flags[0]; ``conclusion``
    added when only the text after the last conclusion word was read)."""
    s = clean(unquoted(line, key), key)
    toks = tokens(s)
    acc = accepted(toks, key["classes"])
    cs = list(CONCL.finditer(s))
    if cs and ("=" not in s or cs[-1].start() > s.rindex("=")):
        tail = s[cs[-1].end():]
        tt = tokens(tail)
        if any(t.cls in acc for t in tt):            # the clause after the last 所以／因此／故 holds the answer
            v, fl = _final(tail, tt, acc)
            return v, fl + ["conclusion"]
    return _final(s, toks, acc)


def _final(s: str, toks: list[Tok], acc: set[str]) -> tuple[int | float | None, list[str]]:
    """Steps 1–4 on a cleaned text, its tokens and the line's accepted classes."""

    def ok(t: Tok) -> bool:
        return t.cls in acc

    def near_bare(t: Tok, at: int) -> bool:
        return t.cls is None and 0 <= t.start - at <= 2

    # 1. an equation
    if "=" in s:
        j = s.rindex("=")
        after = [k for k, t in enumerate(toks) if t.start > j]
        is_sum = bool(after) and s[toks[after[0]].end:toks[after[0]].end + 1] in SUM_OPS
        if is_sum:
            first = s.index("=")
            cand = [k for k, t in enumerate(toks) if t.end <= first and (ok(t) or (t.cls is None and first - t.end <= 2))]
            cand, how = cand[-1:], "eq_left"
        else:
            cand, how = [k for k in after if ok(toks[k]) or near_bare(toks[k], j + 1)][:1], "eq"
        if cand:
            return _pick(cand[0], toks, s, how, [])
    # 2. the last total word whose next number is accepted (a bare number is not: §5 step 2)
    for m in reversed(list(re.finditer(MARK, s))):
        nxt = [k for k, t in enumerate(toks) if t.start >= m.end()][:1]
        if nxt and ok(toks[nxt[0]]):
            return _pick(nxt[0], toks, s, "marker", [])
    # 3. a line holding one number
    if len(toks) == 1:
        if ok(toks[0]) or toks[0].cls is None:
            return _pick(0, toks, s, "single", [])
        return None, ["no_value"]
    # 4. the first segment holding an accepted value, its last one before a cue word after the first one
    off = 0
    for seg in s.split(";"):
        ks = [k for k, t in enumerate(toks) if off <= t.start < off + len(seg) and ok(t)]
        cue = CUE.search(s, toks[ks[0]].end, off + len(seg)) if ks else None
        if cue:                                      # 因為／其中／分別… after the answer: support, not answer
            ks = [k for k in ks if toks[k].start < cue.start()]
        off += len(seg) + 1
        if ks:
            return _pick(ks[-1], toks, s, "segment", ["multi"] if len({toks[k].value for k in ks}) > 1 else [])
    return None, ["no_value"]


# ---------------------------------------------------------------- name keys (SYNC)
def _gold_ref(item: dict, key: dict, VR) -> str:
    """The reference-layer id of a name key: Y = seed + k, Z = Y's primary sync (checked against the
    key's gold_ref when the item builder wrote one)."""
    y = VR.succ(item["seeds_ref"][0], item["k"])
    zs = [o for (n, o, _yr, _v, prim) in VR.syncs if n == y and prim]
    if key["role"] == "Z" and len(zs) != 1:
        raise ValueError(f"{item['id']}: {y} has {len(zs)} primary syncs")
    g = y if key["role"] == "Y" else zs[0]
    if key.get("gold_ref", g) != g:
        raise ValueError(f"{item['id']}: key {key['role']} gold_ref {key['gold_ref']} is not {g}")
    return g


def ctxs_x(item: dict, VR=None, base: set[str] | None = None) -> dict[str, dict]:
    """{role: keys_a ctx}: one item_ctx per name key, that key's kingdom, chain exemption. ValueError when
    the item disagrees with the reference layer (path, gold ids, accept, a written exempt list)."""
    VR = VR or X.ref_v2_view()
    base = base if base is not None else king_lexicon(VR)
    keys = [k for k in item["keys"] if k["type"] == "name"]
    x0, k = item["seeds_ref"][0], item["k"]
    path = [VR.succ(x0, i) for i in range(k + 1)]
    if None in path or len(path) != len(item["path"]) or item.get("path_ref", path) != path:
        raise ValueError(f"{item['id']}: reference path {path} does not match the item path")
    refs = {key["role"]: _gold_ref(item, key, VR) for key in keys}
    chain = list(dict.fromkeys(path + list(refs.values())))
    names = {nm for x in chain for nm in VR.names(x)}
    out = {}
    for key in keys:
        g = refs[key["role"]]
        if VR.nodes[g]["name"] not in key["accept"] or VR.nodes[g]["kingdom"] != key["kingdom"]:
            raise ValueError(f"{item['id']}: key {key['role']} does not name {g} of kingdom {key['kingdom']}")
        exempt = sorted(names | set(key["accept"]))
        if "exempt" in key and sorted(key["exempt"]) != exempt:
            raise ValueError(f"{item['id']}: key {key['role']} exempt list is not the chain rule's")
        src = {"id": item["id"], "keys": [key], "kingdom": key["kingdom"], "gold": [g], "seeds": [x0],
               "exempt": exempt}
        out[key["role"]] = item_ctx(src, VR, base)
    return out


# ---------------------------------------------------------------- one answer line
def _arith_key(item: dict) -> dict:
    keys = [k for k in item["keys"] if k["type"] == "arith"]
    if len(keys) != 1 or len(item["keys"]) != 1:
        raise ValueError(f"{item['id']}: a number item has exactly one arith key")
    return keys[0]


def gold_written(line: str | None, key: dict) -> bool:
    """score_any's lenient test: the gold written as an accepted value (a bare number only when it is the
    line's one number), not inexact and not hedged; quotes and conclusion words are not used."""
    if line is None:
        return False
    s = clean(line, key)
    toks = tokens(s)
    acc = accepted(toks, key["classes"])
    return any(t.value == key["value"] and (t.cls in acc or (t.cls is None and len(toks) == 1))
               and not t.inexact and not hedged(i, toks, s) for i, t in enumerate(toks))


def distractor_of(item: dict, value) -> list[str] | None:
    kinds = sorted({d["kind"] for d in item.get("distractors") or [] if d["value"] == value})
    return kinds or None


def score_line_x(item: dict, line: str | None, ctxs: dict | None = None) -> dict:
    """The score of one answer line; None line = format failure (0)."""
    is_name = any(k["type"] == "name" for k in item["keys"])
    if line is None:
        out = {"score": 0, "score_any": 0, "format_fail": True, "trap": [], "value": None, "flags": [],
               "distractor": None, "hits": []}
        return dict(out, score_z=0) if is_name else out
    if is_name:
        ctxs = ctxs or ctxs_x(item)
        rs = {k["role"]: score_line(ctxs[k["role"]], line) for k in item["keys"]}
        hits = [rs[k["role"]]["hits"][0] for k in item["keys"]]
        trap = sorted({n for r in rs.values() for n in r["trap"]})
        z = rs["Z"]
        score = int(all(hits) and not trap)
        return {"score": score, "score_any": score, "format_fail": False, "trap": trap, "value": None,
                "flags": [], "distractor": None, "hits": hits, "score_z": int(z["hits"][0] and not z["trap"])}
    key = _arith_key(item)
    v, flags = final_value(line, key)
    trap = ["hedge"] if {"hedge", "inexact"} & set(flags) else []
    hit = not trap and v is not None and v == key["value"]
    return {"score": int(hit), "score_any": int(hit or gold_written(line, key)), "format_fail": False,
            "trap": trap, "value": v, "flags": flags,
            "distractor": None if hit or v is None else distractor_of(item, v), "hits": [hit]}


# ---------------------------------------------------------------- K0-4 on real items: G lines copied verbatim
DEATH = ("death_age", "taken", "died_before_birth", "died_first")
PAIR = ("born_age", "total", DEATH)
COPIES = {"S5": (("sum",), ("sum", "handover"), ("handover", "sum")), "S6": (("father_age",),), "F1": (PAIR,),
          "F3": (("flood",),), "F5": (("death_age",), PAIR)}


def _line_of(card: dict, kind, seeds: list[str], k: int | None = None) -> str | None:
    kinds = kind if isinstance(kind, tuple) else (kind,)
    for (head, payload), tag in zip(card["lines"], card["tags"]):
        if tag["kind"] in kinds and set(tag["seeds"]) <= set(seeds) and (k is None or tag["k"] == k):
            return f"{head}：{payload}" if head else payload
    return None


def copy_cases(item: dict, card: dict, ctxs: dict | None = None) -> list[dict]:
    """K0-4: the item's own G derived lines copied verbatim into the answer line (prereg §4 sets per
    question type; SYNC also the two writings of §6-4). want = 1, except F5's three lines (§5 step 4: 0)."""
    out = []
    if item["family"] == "SYNC":
        kn = X.ac.KNAME
        y, z, kd = item["gold"]["Y"], item["gold"]["Z"], item["kingdom"]
        okd = "J" if kd == "I" else "I"
        texts = {"succ_line": [_line_of(card, "succ", item["seeds"], item["k"])],
                 "y_then_z": [f"{y}；{kn[okd]}王{z}"],
                 "acceded_in": [f"{kn[kd]}王{y}於{kn[okd]}王{z}第{item['sync'][0]}年登基"]}
        ctxs = ctxs or ctxs_x(item)
        for case, lines in texts.items():
            r = score_line_x(item, answer_text_x("答案：" + "\n".join(lines)), ctxs) if None not in lines else None
            out.append({"case": case, "want": 1, "got": None if r is None else r["score"]})
        return out
    for kinds in COPIES[item["qtype"]]:
        lines = [_line_of(card, k, item["seeds"]) for k in kinds]
        case = "+".join(k if isinstance(k, str) else "death" for k in kinds)
        want = 0 if item["qtype"] == "F5" and len(kinds) > 1 else 1
        if None in lines:
            out.append({"case": case, "want": want, "got": None, "value": None})
            continue
        r = score_line_x(item, answer_text_x("答案：" + "\n".join(lines)))
        out.append({"case": case, "want": want, "got": r["score"], "value": r["value"]})
    return out


# ---------------------------------------------------------------- K0-4 F3 echo cases (appendix)
F3_ECHO = (("anchor_first_segment", "甲生於洪水後2年;丁在洪水之後37年出生"),
           ("anchor_same_segment", "甲生於洪水後2年,丁在洪水之後37年出生"),
           ("anchor_after_answer", "丁在洪水之後37年出生,甲生於洪水後2年"),
           ("anchor_after_answer_because", "丁在洪水之後37年出生,因為甲生於洪水後2年"),
           ("anchor_in_brackets", "丁在洪水之後37年出生(甲生於洪水後2年)"),
           ("anchor_in_sum", "2+30+5=37年"),
           ("anchor_total_word", "洪水後2年加35年,共37年"))


def f3_echo_table(value: int = 37) -> list[dict]:
    """K0-4: answer lines that also write the flood anchor's 2 years (made-up names), scored by §5."""
    item = {"id": "F3_echo", "keys": [{"type": "arith", "value": value, "classes": ["Y"], "ordinal": True}]}
    out = []
    for case, line in F3_ECHO:
        r = score_line_x(item, line)
        out.append({"case": case, "line": line, "value": r["value"], "flags": r["flags"], "score": r["score"]})
    return out
