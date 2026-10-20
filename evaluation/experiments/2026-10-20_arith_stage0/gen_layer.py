"""Genesis layer of the ordered-chain arithmetic stage-0 (prereg §2 創世記層) -> store gen_layer.json.

Regex over the text layer's verse_units.jsonl (book_id gen); numerals through cards_common.cn2int.
- Begetting ages: every 「X(活到)(整)N歲，生了Y」 of chapters 5 and 11, in verse order (19). The rows
  give the two chains: G05.00 亞當 … G05.09 挪亞 and G11.00 閃 … G11.08 他拉. A son written as 「一個
  兒子」 is named by the 起名叫 of that verse or the next one; a list of sons (「Y、Z、W」) keeps all
  of them, the first being the chain son.
- Remaining years: only the 「X生Y之後(，)又活了／又在世／與上帝同行 N 年」 rows of chapters 5 and 11
  (17). 挪亞's years after the flood (gen.9.28) count from the flood, not a birth: 挪亞 has beget and
  total only.
- Stated lifespans: 「X共活了N歲」 of a chain patriarch (11: gen.5.5 … 5.31, gen.9.29, gen.11.32).
- The flood: 挪亞's age in the first 洪水 verse of chapter 7 that states it (gen.7.6), and the flood
  anchor of the chapter-11 head 「洪水以後N年，X…歲生了Y」 (gen.11.10), kept on 閃 as flood_offset.
The chapter-11 lifespans (beget + remain) are derived, kept under ``derived`` and never in the rows.
Edges run father -> chain son inside one chapter; 挪亞 -> 閃 is a conflict edge (gen.5.32 against
gen.11.10) and is never used. Years count from 亞當's birth; chapter 11 hangs on the flood anchor
(flood year = 亞當 -> 挪亞 begets + 挪亞's flood age), never on gen.5.32. Nothing here calls an LLM.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import x_common as X

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


def cn(s: str) -> int:
    v = X.cc.cn2int(s)
    if v is None:
        raise ValueError(f"not a numeral: {s!r}")
    return v


def verses(text_dir: Path) -> list[dict]:
    """Genesis verse units in canonical order."""
    rows = [r for r in X.jsonl(Path(text_dir) / "verse_units.jsonl") if r["book_id"] == "gen"]
    return sorted(rows, key=lambda r: (r.get("ord", 0), r["chapter"], r["v_start"]))


def sons_of(match: re.Match, i: int, vs: list[dict]) -> list[str]:
    s = match.group("s").strip()
    if s != ONE_SON:
        return [x for x in s.split("、") if x]
    for r in vs[i:i + 2]:
        m = NAMED.search(r["text"]) if r["chapter"] == vs[i]["chapter"] else None
        if m:
            return [m.group("s")]
    return []


def scan(vs: list[dict]) -> dict:
    """Raw regex hits: beget rows per chapter, remain rows, totals, the flood age and the anchor."""
    out = {"beget": {c: [] for c in CHAPTERS}, "remain": [], "total": [], "flood": None, "anchor": None}
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


def build(text_dir: Path | str = X.TEXT) -> dict:
    """The layer document (schema arith.gen_layer.v1) with its K0-2 checks."""
    raw = scan(verses(Path(text_dir)))
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
    return {"schema": SCHEMA, "text_digest": X.TEXT_DIGEST, "nodes": nodes, "edges": edges,
            "conflict_edges": conflict_edges,
            "flood": {"noah_age": [flood["n"], flood["verse"]] if flood else None},
            "derived": {"total": derived},
            "checks": {"total_eq": [total_eq, len(full)], "son_match": [son_ok, len(raw["remain"])],
                       "noah_no_remain": bool(noah) and "remain" not in noah["fields"],
                       "counts": {"nodes": len(nodes), "beget": len(nodes), "remain": len(raw["remain"]),
                                  "total": n_total, "derived": len(derived)}},
            "problems": problems}


def check(doc: dict, expect: dict = EXPECT) -> list[str]:
    """K0-2 on the layer (empty = ok): beget + remain = total on every full row, every remain son is the
    begetting row's son, 挪亞 has no remain, 閃 carries the flood anchor, and the prereg §2 counts."""
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


def sha256(doc: dict) -> str:
    """sha256 of the file x_common.write_json writes for doc."""
    return X.sha256_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def write(doc: dict, path: Path | str = X.GEN_LAYER) -> Path:
    return X.write_json(path, doc)


def load(path: Path | str = X.GEN_LAYER) -> dict:
    return X.read_json(path)


# ---------------------------------------------------------------- readers
def node(doc: dict, nid: str) -> dict:
    return next(n for n in doc["nodes"] if n["id"] == nid)


def by_name(doc: dict, name: str) -> str | None:
    hits = [n["id"] for n in doc["nodes"] if n["name"] == name]
    return hits[0] if len(hits) == 1 else None


def chain(doc: dict, chapter: int) -> list[str]:
    return [n["id"] for n in sorted(doc["nodes"], key=lambda n: n["order"]) if n["chapter"] == chapter]


def total(doc: dict, nid: str) -> int | None:
    """Stated lifespan, else the derived chapter-11 one (beget + remain)."""
    t = node(doc, nid)["fields"].get("total")
    return t[0] if t else doc["derived"]["total"].get(nid)


def age_at_birth(doc: dict, x: str, y: str) -> int:
    """x's age at the birth of his chain descendant y (begets x .. y's father); same chapter only."""
    ch = chain(doc, node(doc, x)["chapter"])
    i, j = ch.index(x), ch.index(y)
    if j <= i:
        raise ValueError(f"{y} is not a descendant of {x}")
    return sum(node(doc, z)["fields"]["beget"][0] for z in ch[i:j])


def flood_year(doc: dict) -> int:
    noah = chain(doc, CHAPTERS[0])[-1]
    return born_year(doc, noah) + doc["flood"]["noah_age"][0]


def born_year(doc: dict, nid: str) -> int:
    """Years from 亞當's birth; chapter 11 through the flood anchor (gen.11.10), never gen.5.32."""
    n = node(doc, nid)
    ch = chain(doc, n["chapter"])
    if n["chapter"] == CHAPTERS[0]:
        return sum(node(doc, z)["fields"]["beget"][0] for z in ch[:n["order"]])
    head = node(doc, ch[0])
    second = flood_year(doc) + head["flood_offset"][0]     # the head's son, born after the flood
    if n["order"] == 0:
        return second - head["fields"]["beget"][0]
    return second + sum(node(doc, z)["fields"]["beget"][0] for z in ch[1:n["order"]])


def death_year(doc: dict, nid: str) -> int:
    """born_year + lifespan (以諾: the year he was taken)."""
    return born_year(doc, nid) + total(doc, nid)
