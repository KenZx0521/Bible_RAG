"""Answer keys of experiment A: key hits and the same-kingdom trap (prereg §2 指標, appendix A.5).

item_ctx(item, VR) once per item, then score_line(ctx, line). Names: greedy longest match over the
reference layer's names and aliases plus the item's name keys (亞撒 is not found inside 亞撒利雅).
A name right after 「<other kingdom>王(X的兒子)」 is that kingdom's king: no hit, no trap. A gold name
another same-kingdom king also bears does not hit when that king's father is attached
(「F的兒子name」「name(F的兒子)」「name，父F」, not after 不是／並非). Numbers: the value written with
its unit (年, 歲, 日) and not after 第, citations removed. Terms: a substring, unless a reject
pattern matches. Trap: paren-stripped line minus the father phrases of the gold and seed kings.
"""
from __future__ import annotations

import re

from a_common import cc

OTHER = {"I": "猶大", "J": "以色列"}
NUM_RUN = "[零〇一二兩三四五六七八九十百]+|[0-9]+"
CITE = re.compile(r"[0-9]+:[0-9]+(?:[-~–,、][0-9]+)*|第?(?:[零〇一二兩三四五六七八九十百]+|[0-9]+)章"
                  r"(?:(?:[零〇一二兩三四五六七八九十百]+|[0-9]+)(?:[-~–至到](?:[零〇一二兩三四五六七八九十百]+|[0-9]+))?節)?")
NOT = "(?<!不是)(?<!並非)"


def king_lexicon(VR) -> set[str]:
    return {nm for x in VR.nodes for nm in VR.names(x)}


def spans(text: str, lexicon: set[str]) -> list[tuple[int, str]]:
    by_len = sorted(lexicon, key=len, reverse=True)
    out, i = [], 0
    while i < len(text):
        hit = next((n for n in by_len if text.startswith(n, i)), None)
        if hit:
            out.append((i, hit))
            i += len(hit)
        else:
            i += 1
    return out


def tokens(text: str, lexicon: set[str]) -> list[str]:
    return [n for _i, n in spans(text, lexicon)]


def alt(names) -> str:
    return "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))


def father_phrases(VR, ids) -> list:
    out = []
    for y in dict.fromkeys(ids):
        f = VR.nodes[y]["father"]
        if f:
            nm, F = alt(VR.names(y)), re.escape(f)
            out.append((re.compile(rf"{F}(?:的兒子|之子)(?=(?:{nm}))"), ""))
            out.append((re.compile(rf"({nm})[,，、]?(?:父親?|其父)(?:是|為|名叫)?{F}"), r"\1"))
    return out


def wrong_fathers(VR, item) -> list:
    """Patterns attaching another same-kingdom bearer's father to a gold name (耶羅波安: 尼八)."""
    out = []
    for y in item["gold"]:
        g = VR.nodes[y]
        for z, n in VR.nodes.items():
            if z != y and n["kingdom"] == g["kingdom"] and g["name"] in VR.names(z) and n["father"] \
                    and n["father"] != g["father"]:
                G, F = re.escape(g["name"]), re.escape(n["father"])
                out.append(re.compile(rf"{NOT}{F}(?:的兒子|之子){G}|{G}[(（]{F}(?:的兒子|之子)|"
                                      rf"{G}[(（,，、]?(?:父親?|其父)(?:是|為|名叫)?{F}"))
    return out


def item_ctx(item: dict, VR, base: set[str] | None = None) -> dict:
    lex = (base or king_lexicon(VR)) | {a for k in item["keys"] if k["type"] == "name" for a in k["accept"]}
    same = {nm for x, n in VR.nodes.items() if n["kingdom"] == item["kingdom"] for nm in VR.names(x)}
    other = OTHER[item["kingdom"]]
    return {"item": item, "lex": lex, "traps": same - set(item["exempt"]),
            "foreign": re.compile(rf"{other}(?:國)?的?王(?:[一-鿿‧]{{1,4}}(?:的兒子|之子))?$"),
            "fathers": father_phrases(VR, item["gold"] + item["seeds"]), "wrong_father": wrong_fathers(VR, item)}


def own_spans(ctx: dict, text: str) -> list[tuple[int, str]]:
    """Name occurrences not marked as the other kingdom's king."""
    return [(i, n) for i, n in spans(text, ctx["lex"]) if not ctx["foreign"].search(text[:i])]


def number_hit(key: dict, text: str) -> bool:
    pat = rf"(?<![零〇一二兩三四五六七八九十百0-9第])({NUM_RUN})(?:個)?(?:{key['unit']})"
    vals = {int(m) if m.isdigit() else cc.cn2int(m) for m in re.findall(pat, CITE.sub("", text))}
    return key["value"] in vals


def key_hit(ctx: dict, key: dict, text: str) -> bool:
    if key["type"] == "name":
        names = {n for _i, n in own_spans(ctx, text)}
        return any(a in names for a in key["accept"]) and not any(p.search(text) for p in ctx["wrong_father"])
    if key["type"] == "number":
        return number_hit(key, text)
    return any(a in text for a in key["accept"]) and not any(re.search(r, text) for r in key.get("reject", []))


def trap_names(ctx: dict, line: str) -> list[str]:
    s = cc.strip_parens(line)
    for pat, rep in ctx["fathers"]:
        s = pat.sub(rep, s)
    return sorted({n for _i, n in own_spans(ctx, s) if n in ctx["traps"]})


def score_line(ctx: dict, line: str | None) -> dict:
    """key_score of one answer line; None line = format failure (0)."""
    if line is None:
        return {"score": 0.0, "format_fail": True, "trap": [], "hits": []}
    hits = [key_hit(ctx, k, line) for k in ctx["item"]["keys"]]
    trap = trap_names(ctx, line)
    return {"score": 0.0 if trap else sum(hits) / len(hits), "format_fail": False, "trap": trap, "hits": hits}


def covered(ctx: dict, key: dict, payloads: list[str]) -> bool:
    return any(key_hit(ctx, key, p) for p in payloads)
