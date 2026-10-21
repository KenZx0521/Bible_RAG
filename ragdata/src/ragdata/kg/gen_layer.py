"""``gen_layer.json``: the Genesis 5 and 11 chains of the GEN card (plan 2026-10-21 §2.1).

A port of the ordered-chain arithmetic stage-0 builder
(``evaluation/experiments/2026-10-20_arith_stage0/gen_layer.py``: ``build``, ``check``) that reads
the text layer's verse units only; nothing here calls an LLM. Numerals go through a verbatim copy
of experiment A's ``cards_common.cn2int`` (``regnal_rules.zh2int`` is another parser: no 〇, no
bare digit runs). Two things differ from the stage-0 script, neither in the bytes on
text@247eafe44b02: the rows come from the stored layer (``LayerData.rows``), and ``text_digest``
is that layer's digest, where stage-0 wrote the constant of text@247eafe44b02.

- Begetting ages: every 「X(活到)(整)N歲，生了Y」 of chapters 5 and 11, in verse order. The rows
  give the two chains (G05.00 … and G11.00 …). A son written as 「一個兒子」 is named by the 起名叫
  of that verse or the next one; a list of sons keeps all of them, the first being the chain son.
- Remaining years: only the 「X生Y之後(，)又活了／又在世／與上帝同行 N 年」 rows of chapters 5 and 11.
- Stated lifespans: 「X共活了N歲」 of a chain patriarch.
- The flood: the last chapter-5 patriarch's age in the first 洪水 verse of chapter 7 that states
  it, and the flood anchor of the chapter-11 head (「洪水以後N年，X…歲生了Y」) as its flood_offset.

The chapter-11 lifespans (beget + remain) are derived, kept under ``derived`` and never in the
rows. Edges run father -> chain son inside one chapter; the chapter-5 end to the chapter-11 head
is a conflict edge, never used. The file is serialized as stage-0 wrote it (``encode``:
insertion order, ``indent=1``, a final newline), so G-GEN can pin its sha256.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

SCHEMA = "arith.gen_layer.v1"
CHAPTERS = (5, 11)                          # the two chains
FLOOD_CHAPTER = 7
EXPECT = {"nodes": 19, "beget": 19, "remain": 17, "total": 11, "total_eq": 9, "son_match": 17, "derived": 8}

NUM = "[零〇一二兩三四五六七八九十百]+"
NAME = r"[^\s，。、；：「」『』（）！？－]{1,5}?"
BEGET = re.compile(rf"(?P<f>{NAME})(?:活到)?(?:整)?(?P<n>{NUM})歲，?生了(?P<s>[^。]*?)[，。]")
REMAIN = re.compile(rf"(?P<f>{NAME})生(?P<s>{NAME})之後，?(?:又活了|又在世|與上帝同行)(?P<n>{NUM})年")
TOTAL = re.compile(rf"(?P<f>{NAME})共活了(?P<n>{NUM})歲")
NAMED = re.compile(rf"起名叫(?P<s>{NAME})[，。：；]")
FLOOD_AGE = re.compile(rf"洪水[^。]*?(?P<f>{NAME})整?(?P<n>{NUM})歲")
ANCHOR = re.compile(rf"洪水以後(?P<n>{NUM})年，?(?P<f>{NAME}){NUM}歲生了")
ONE_SON = "一個兒子"

# experiment A's cards_common (evaluation/experiments/2026-10-18_kg_cards/cards_common.py), verbatim
_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn2int(s: str) -> int | None:
    """一 … 九百九十九 (十二, 四十一, 二十五, 一百零五); None if not a numeral."""
    if not s or any(c not in _CN and c not in "十百" for c in s):
        return None
    if all(c in _CN for c in s):  # bare digits: 三 → 3, 一九 → 19
        return int("".join(str(_CN[c]) for c in s))
    total, cur = 0, 0
    for c in s:
        if c == "百":
            total += (cur or 1) * 100
            cur = 0
        elif c == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = _CN[c]
    return total + cur


def cn(s: str) -> int:
    v = cn2int(s)
    if v is None:
        raise ValueError(f"not a numeral: {s!r}")
    return v


def encode(doc: Mapping[str, Any]) -> bytes:
    """The file as stage-0 wrote it (and gen_names.json): insertion order, indent 1, final newline."""
    return (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def has_chains(units: Sequence[Mapping[str, Any]]) -> bool:
    """Whether the text holds Genesis 5 or 11 at all (the mini text does not)."""
    return any(r["book_id"] == "gen" and r["chapter"] in CHAPTERS for r in units)


def verses(units: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Genesis verse units in canonical order."""
    rows = [r for r in units if r["book_id"] == "gen"]
    return sorted(rows, key=lambda r: (r.get("ord", 0), r["chapter"], r["v_start"]))


def sons_of(match: re.Match, i: int, vs: list[Mapping[str, Any]]) -> list[str]:
    s = match.group("s").strip()
    if s != ONE_SON:
        return [x for x in s.split("、") if x]
    for r in vs[i:i + 2]:
        m = NAMED.search(r["text"]) if r["chapter"] == vs[i]["chapter"] else None
        if m:
            return [m.group("s")]
    return []


def scan(vs: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Raw regex hits: beget rows per chapter, remain rows, totals, the flood age and the anchor."""
    out: dict[str, Any] = {"beget": {c: [] for c in CHAPTERS}, "remain": [], "total": [], "flood": None,
                           "anchor": None}
    for i, r in enumerate(vs):
        c, t, vid = r["chapter"], r["text"], r["unit_key"]
        if c in CHAPTERS:
            m = BEGET.search(t)
            if m:
                out["beget"][c].append(dict(name=m.group("f"), n=cn(m.group("n")), verse=vid, sons=sons_of(m, i, vs)))
            for m in REMAIN.finditer(t):
                out["remain"].append(dict(chapter=c, name=m.group("f"), son=m.group("s"), n=cn(m.group("n")),
                                          verse=vid))
            m = ANCHOR.search(t)
            if m and out["anchor"] is None:
                out["anchor"] = dict(name=m.group("f"), n=cn(m.group("n")), verse=vid)
        for m in TOTAL.finditer(t):
            out["total"].append(dict(name=m.group("f"), n=cn(m.group("n")), verse=vid))
        if c == FLOOD_CHAPTER and out["flood"] is None:
            m = FLOOD_AGE.search(t)
            if m:
                out["flood"] = dict(name=m.group("f"), n=cn(m.group("n")), verse=vid)
    return out


def build(units: Sequence[Mapping[str, Any]], text_digest: str) -> dict[str, Any]:
    """The layer document (schema arith.gen_layer.v1) of the text's verse units, with its K0-2 checks."""
    raw = scan(verses(units))
    nodes, by_name, problems = [], {}, []
    for c in CHAPTERS:
        for j, b in enumerate(raw["beget"][c]):
            nid = f"G{c:02d}.{j:02d}"
            if b["name"] in by_name:
                problems.append(f"chain name {b['name']} twice")
            by_name[b["name"]] = nid
            nodes.append(dict(id=nid, name=b["name"], chapter=c, order=j, sons=b["sons"],
                              fields={"beget": [b["n"], b["verse"]]}, flood_offset=None, evidence=[b["verse"]]))
    by_id = {n["id"]: n for n in nodes}
    edges, conflict_edges = [], []
    for c in CHAPTERS:
        ch = [n for n in nodes if n["chapter"] == c]
        for a, b in zip(ch, ch[1:]):
            if a["sons"][:1] == [b["name"]]:
                edges.append([a["id"], b["id"], "son", a["fields"]["beget"][1]])
            else:
                problems.append(f"{a['id']}: chain son {a['sons'][:1]} is not the next row's {b['name']}")
    ch5, ch11 = ([n for n in nodes if n["chapter"] == c] for c in CHAPTERS)
    if ch5 and ch11 and ch5[-1]["sons"][:1] == [ch11[0]["name"]]:
        conflict_edges.append([ch5[-1]["id"], ch11[0]["id"], "son", ch5[-1]["fields"]["beget"][1]])
    son_ok = 0
    for r in raw["remain"]:
        nid = by_name.get(r["name"])
        if nid is None or by_id[nid]["chapter"] != r["chapter"]:
            problems.append(f"remain row {r['verse']} has no chain father")
            continue
        n = by_id[nid]
        if "remain" in n["fields"]:
            problems.append(f"{nid}: two remain rows")
        n["fields"]["remain"] = [r["n"], r["verse"]]
        n["evidence"].append(r["verse"])
        son_ok += n["sons"][:1] == [r["son"]]
    n_total = 0
    for t in raw["total"]:
        nid = by_name.get(t["name"])
        if nid is None:
            continue
        if "total" in by_id[nid]["fields"]:
            problems.append(f"{nid}: two lifespans")
        by_id[nid]["fields"]["total"] = [t["n"], t["verse"]]
        by_id[nid]["evidence"].append(t["verse"])
        n_total += 1
    anchor, flood = raw["anchor"], raw["flood"]
    if anchor and anchor["name"] in by_name:
        by_id[by_name[anchor["name"]]]["flood_offset"] = [anchor["n"], anchor["verse"]]
    noah = ch5[-1] if ch5 else None
    if not flood or not noah or flood["name"] != noah["name"]:
        problems.append("the flood age is not the last chapter-5 patriarch's")
    full = [n for n in nodes if {"beget", "remain", "total"} <= set(n["fields"])]
    total_eq = sum(n["fields"]["beget"][0] + n["fields"]["remain"][0] == n["fields"]["total"][0] for n in full)
    derived = {n["id"]: n["fields"]["beget"][0] + n["fields"]["remain"][0] for n in ch11
               if "remain" in n["fields"] and "total" not in n["fields"]}
    return {"schema": SCHEMA, "text_digest": text_digest, "nodes": nodes, "edges": edges,
            "conflict_edges": conflict_edges,
            "flood": {"noah_age": [flood["n"], flood["verse"]] if flood else None},
            "derived": {"total": derived},
            "checks": {"total_eq": [total_eq, len(full)], "son_match": [son_ok, len(raw["remain"])],
                       "noah_no_remain": bool(noah) and "remain" not in noah["fields"],
                       "counts": {"nodes": len(nodes), "beget": len(nodes), "remain": len(raw["remain"]),
                                  "total": n_total, "derived": len(derived)}},
            "problems": problems}


def check(doc: Mapping[str, Any], expect: Mapping[str, int] = EXPECT) -> list[str]:
    """K0-2 on the layer (empty = ok): beget + remain = total on every full row, every remain son is the
    begetting row's son, the chapter-5 end has no remain, the chapter-11 head carries the flood anchor,
    and the prereg §2 counts. G-GEN does not run it (the sha256 pin fixes the file); the tests do."""
    ck, out = doc["checks"], list(doc.get("problems", []))
    if ck["total_eq"] != [expect["total_eq"]] * 2:
        out.append(f"total_eq {ck['total_eq']} is not {[expect['total_eq']] * 2}")
    if ck["son_match"] != [expect["son_match"]] * 2:
        out.append(f"son_match {ck['son_match']} is not {[expect['son_match']] * 2}")
    if not ck["noah_no_remain"]:
        out.append("noah_no_remain is false")
    for k in ("nodes", "beget", "remain", "total", "derived"):
        if ck["counts"][k] != expect[k]:
            out.append(f"{k}: {ck['counts'][k]} rows, expected {expect[k]}")
    heads = [n for n in doc["nodes"] if n["chapter"] == CHAPTERS[1] and n["order"] == 0]
    if not heads or not heads[0]["flood_offset"] or doc["flood"]["noah_age"] is None:
        out.append("no flood anchor on the chapter-11 head or no flood age")
    if [n["id"] for n in doc["nodes"] if n["flood_offset"]] != [h["id"] for h in heads]:
        out.append("a flood offset off the chapter-11 head")
    return out
