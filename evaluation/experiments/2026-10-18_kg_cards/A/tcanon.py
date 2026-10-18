"""T-canon arm (prereg §2): canonical window of 1–2 Kings regnal-formula verses, no layer, no graph.

Formula verses = 1ki/2ki verses matching probe_C5 supply.py's skeleton regex, in canonical order.
Centre = the seed's accession verse found by string search on the seed (kingdom, name) from
stage 1, first hit in canonical order over tiers 「name(在X)登基作K」, 「name(在X)登基」 not followed
by the other kingdom, 「name(在X)作K王+年數」, 「name(在X)作王+年數」, 「K王name」, name; the name must
fill a whole PDF proper-name span of the text layer (name_spans.jsonl), so 羅波安 is not found in
耶羅波安. Each tier is tried first with the question's 「（F的兒子）」 father (the verse must hold
「F的兒子name」) when the question gives one. Two seeds: start from the span of both centres if it fits.
Tiers are tried in order; within a tier the first canonical hit wins. The window grows one verse
at a time, after and before in turn; a side whose next verse would push the block past 900 chars
(or that has no verse left) is skipped, and growth stops when neither side fits. Each verse is
labelled 王上/王下 c:v; the window's 又名/就是 footnotes (text layer footnotes.jsonl) follow their verse.
"""
from __future__ import annotations

import functools
import re

from a_common import CAP_CHARS, KNAME, TEXT, footnotes, jsonl, short_ref, verse_units
from layer_re import P_FN_ALIAS

FORMULA = re.compile(r'登基|作.{0,8}王.{0,2}[一二三四五六七八九十]+|接續|母親名叫|列祖同睡|篡')  # supply.py skel_re


@functools.cache
def formula_verses() -> tuple[tuple[str, str], ...]:
    rows = [r for r in verse_units().values() if r["book_id"] in ("1ki", "2ki") and FORMULA.search(r["text"])]
    return tuple((r["unit_key"], r["text"]) for r in sorted(rows, key=lambda r: r["ord"]))


@functools.cache
def name_spans() -> dict:
    out: dict[str, set] = {}
    for r in jsonl(TEXT / "name_spans.jsonl"):
        out.setdefault(r["container_id"], set()).add((r["start"], r["end"]))
    return out


def tiers(kd: str | None, name: str):
    k = KNAME.get(kd) if kd else "(?:猶大|以色列)"
    other = f"(?!作(?:了)?{KNAME['I' if kd == 'J' else 'J']})" if kd else ""
    n, at, num = f"(?P<x>{re.escape(name)})", "(?:在[一-鿿‧]{2,5}?)?", "(?:共)?[一二三四五六七八九十]"
    yield re.compile(rf"{n}{at}登基作(?:了)?{k}")
    yield re.compile(rf"{n}{at}登基{other}")
    yield re.compile(rf"{n}{at}作(?:了)?{k}(?:眾人的)?王{num}")
    yield re.compile(rf"{n}{at}作(?:了)?王{num}")
    if kd:
        yield re.compile(rf"{KNAME[kd]}王{n}")
    yield re.compile(n)


def hit(pat, key: str, text: str) -> bool:
    spans = name_spans().get(key, set())
    return any((m.start("x"), m.end("x")) in spans for m in pat.finditer(text))


def father_of(question: str, name: str) -> str | None:
    m = re.search(re.escape(name) + r"（([一-鿿‧]{1,4})的兒子）", question)
    return m.group(1) if m else None


def find_center(kd: str | None, name: str, question: str) -> int | None:
    vs, father = formula_verses(), father_of(question, name)
    for need_father in ((True, False) if father else (False,)):
        for pat in tiers(kd, name):
            for i, (key, t) in enumerate(vs):
                if hit(pat, key, t) and (not need_father or f"{father}的兒子{name}" in t):
                    return i
    return None


def verse_lines(i: int) -> list[str]:
    key, text = formula_verses()[i]
    out = [f"{short_ref(key)} {text}"]
    for fn in footnotes().get(key, []):
        if P_FN_ALIAS.match(fn["text"].strip()):
            out.append(f"{short_ref(key)} 註：{fn['text'].strip()}")
    return out


def render(lo: int, hi: int) -> str:
    return "\n".join(ln for i in range(lo, hi + 1) for ln in verse_lines(i))


def window(centers: list[int], cap: int = CAP_CHARS) -> tuple[int, int] | None:
    if not centers:
        return None
    lo, hi = min(centers), max(centers)
    if len(render(lo, hi)) > cap:
        lo = hi = centers[0]
    n, after = len(formula_verses()), True
    while True:
        for side_after in (after, not after):
            nlo, nhi = (lo, hi + 1) if side_after else (lo - 1, hi)
            if nlo >= 0 and nhi < n and len(render(nlo, nhi)) <= cap:
                lo, hi, after = nlo, nhi, not side_after
                break
        else:
            return lo, hi


def tcanon(seeds: list[tuple[str | None, str]], question: str) -> dict:
    centers = [c for c in (find_center(kd, nm, question) for kd, nm in seeds) if c is not None]
    win = window(centers)
    if win is None:
        return {"block": "", "centers": [], "window": None, "verses": []}
    vs = formula_verses()
    return {"block": render(*win), "centers": [vs[c][0] for c in centers],
            "window": [vs[win[0]][0], vs[win[1]][0]], "n_verses": win[1] - win[0] + 1,
            "verses": [vs[i][0] for i in range(win[0], win[1] + 1)]}
