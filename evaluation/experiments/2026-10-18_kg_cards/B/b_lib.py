"""Experiment B loaders (prereg.md §3): probe_C1/c1lib.py ported, every path on the store archive.

Read-only, CPU, stdlib. TIPNR (gold source, store only) is read from FP's K archive; nothing
derived from it may be written outside store reports/kg_cards_20261018/B/.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import cards_common as cc  # noqa: E402

STORE = cc.STORE
TEXT = cc.TEXT_LAYER
STRUCT = STORE / "layers/struct/struct@d8d432b4df15"
KS = cc.KS
P3 = KS / "propose_P3/out"
P6 = KS / "propose_P6"
C1 = KS / "probe_C1"
POWER_DIR = KS / "verify_C1_power_cost"
MH_TRIPLES = cc.MH / "multihop/triples.jsonl"
OUT = cc.OUT_ROOT / "B"
BOOKS_JSON = HERE.parents[3] / "packages/ragcommon/data/books.json"
SEED = 20261018

GOLD_FIXES = OUT / "gold_fixes.json"
_SUFFIX = re.compile(r"\((\?|a|d|f)\)")
_FEMALE_V0 = ("woman", "women", "girl", "queen", "daughter", "wife", "mother", "sister", "prophetess")
_FEMALE = re.compile(r"\b(?:woman|women|girl|queen|daughter|wife|mother|sister|prophetess|concubine|widow)\b")
_FIRST_PHRASE = re.compile(r" living|[,;]")


def cid(x: str) -> str:
    return _SUFFIX.sub("", x).strip()


def jl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- struct / text
@lru_cache(None)
def struct() -> dict:
    u2p, u2ps, order = {}, {}, {}
    p2u = collections.defaultdict(list)
    for i, r in enumerate(jl(STRUCT / "verse_index.jsonl")):
        u2p[r["unit_key"]] = r["pericope_id"]
        u2ps[r["unit_key"]] = r["passage_id"]
        order[r["unit_key"]] = i
        p2u[r["pericope_id"]].append(r["unit_key"])
    per = {r["pericope_id"]: r for r in jl(STRUCT / "pericopes.jsonl")}
    ps2u = collections.defaultdict(list)
    for u, ps in u2ps.items():
        ps2u[ps].append(u)
    chunks, u2ck = {}, collections.defaultdict(list)
    for r in jl(STRUCT / "chunks.jsonl"):
        chunks[r["chunk_id"]] = r
        for x in r["unit_refs"]:
            u2ck[x["unit_key"]].append(r["chunk_id"])
    return dict(u2p=u2p, u2ps=u2ps, order=order, p2u=dict(p2u), per=per, ps2u=dict(ps2u),
                chunks=chunks, u2ck=dict(u2ck))


@lru_cache(None)
def passages() -> dict:
    return {r["passage_id"]: r for r in jl(STRUCT / "passages.jsonl")}


def unit_of_verse(u: str) -> str:
    s = struct()
    cks = s["u2ck"].get(u)
    return cks[0] if cks else s["u2ps"][u]


def verses_of_unit(rid: str) -> list[str]:
    s = struct()
    if rid.startswith("ck:"):
        return [x["unit_key"] for x in s["chunks"][rid]["unit_refs"]]
    return s["ps2u"].get(rid, [])


def verses_of_units(rids) -> list[str]:
    vs = {v for r in rids for v in verses_of_unit(r)}
    return sorted(vs, key=struct()["order"].get)


@lru_cache(None)
def verse_text() -> dict:
    return {r["unit_key"]: r["text"] for r in jl(TEXT / "verse_units.jsonl")}


@lru_cache(None)
def books() -> dict:
    """book_id -> (full name, short name); short = first PDF abbreviation, else first colloquial."""
    out = {}
    for b in load_json(BOOKS_JSON)["books"]:
        short = (b.get("pdf_abbreviations") or b.get("colloquial_abbreviations") or [b["name"]])[0]
        out[b["book_id"]] = (b["name"], short)
    return out


def verse_ref(unit_key: str) -> str:
    """'1ch.1.20' -> '代上 1:20' (merged units keep their label: 'eph.6.2-3' -> '弗 6:2-3')."""
    b, c, v = unit_key.split(".", 2)
    return f"{books()[b][1]} {c}:{v}"


# ---------------------------------------------------------------- prod-format context sources
_VERSE_BLOCK = re.compile(r"\*\*[1-9][0-9]*(?:-[1-9][0-9]*)?\*\* ")


def _groups(content: str) -> list[list[str]]:
    """backend/database/content.py _groups (keep in sync)."""
    groups, pending = [], []
    for block in content.split("\n\n"):
        pending.append(block)
        if _VERSE_BLOCK.match(block):
            groups.append(pending)
            pending = []
    if pending:
        raise ValueError(f"passage content has blocks after the last verse: {pending[:1]}")
    return groups


def _refkey(r: dict) -> tuple:
    return (r.get("unit_key"), r.get("from"), r.get("to"))


def chunk_content(passage: dict, chunk_refs: list[dict]) -> str:
    """backend/database/content.py chunk_content (keep in sync)."""
    groups = _groups(passage["content"])
    held = [_refkey(r) for r in passage["unit_refs"]]
    wanted = [_refkey(r) for r in chunk_refs]
    if len(groups) != len(held):
        raise ValueError(f"{passage['passage_id']}: {len(groups)} blocks for {len(held)} pieces")
    starts = [i for i in range(len(held)) if held[i:i + len(wanted)] == wanted]
    if not starts:
        raise ValueError(f"chunk pieces {wanted[:2]} are not a run of {passage['passage_id']}")
    return "\n\n".join(b for g in groups[starts[0]:starts[0] + len(wanted)] for b in g)


def source(rid: str) -> dict:
    """A ps:/ck: unit as prod postgres._passage/_chunk fields used by build_context_blocks."""
    s = struct()
    ck = s["chunks"].get(rid) if rid.startswith("ck:") else None
    p = passages()[ck["passage_id"] if ck else rid]
    book_id, chapter = p["chapter_key"].split(".")
    src = {"id": rid, "book_name": books()[book_id][0], "chapter_num": int(chapter),
           "title": p.get("title") or "", "verse_range": p["verse_range"], "content": p["content"]}
    if ck:
        src.update(verse_range=ck["verse_range"], content=chunk_content(p, ck["unit_refs"]))
    return src


# ---------------------------------------------------------------- frame (verify_C1_power_cost/pool.py)
CHAP = {"gen": [4, 5, 10, 11, 25, 35, 36, 46], "exo": [6], "num": [3, 26], "rut": [4],
        "1ch": list(range(1, 10)), "ezr": [7], "neh": [11, 12], "mat": [1], "luk": [3]}


@lru_cache(None)
def frame() -> frozenset:
    s = struct()
    title = {r[0] for r in load_json(P6 / "title_frame_out.json")["rows"]}
    text = {r[0] for r in load_json(P6 / "text_frame_out.json")["eligible_list"]}
    chap = set()
    for pid, r in s["per"].items():
        b, c, _ = r["start_slot"].split(".")
        if b in CHAP and int(c) in CHAP[b]:
            chap.add(pid)
    return frozenset(title | text | chap)


# ---------------------------------------------------------------- kin triples (G edge source)
@lru_cache(None)
def triples_by_unit() -> dict:
    by = collections.defaultdict(list)
    for t in jl(MH_TRIPLES):
        if t["head"] != t["tail"]:
            by[t["unit_key"]].append(t)
    return dict(by)


# ---------------------------------------------------------------- TIPNR (store only)
@lru_cache(None)
def tipnr() -> dict:
    tip = {cid(r["uid"]): r for r in load_json(P3 / "tipnr.json")}
    parents, sibs, partners = (collections.defaultdict(set) for _ in range(3))
    for i, r in tip.items():
        for p in r["parents"]:
            parents[i].add(cid(p))
        for o in r["offspring"]:
            parents[cid(o)].add(i)
        for x in r["siblings"]:
            sibs[i].add(cid(x)); sibs[cid(x)].add(i)
        for x in r["partners"]:
            partners[i].add(cid(x)); partners[cid(x)].add(i)
    return dict(tip=tip, parents=dict(parents), sibs=dict(sibs), partners=dict(partners),
                gender={i: "F" if _female(r["desc"]) else "M" for i, r in tip.items()},
                gender_v0={i: "F" if r["desc"].lower().startswith(_FEMALE_V0) else "M" for i, r in tip.items()})


def _female(desc: str) -> bool:
    """A female noun in the description's first phrase ("<name>'s wife living …"); v0 only read its
    first word and took 8 women for men."""
    return bool(_FEMALE.search(_FIRST_PHRASE.split(desc.lower(), 1)[0]))


@lru_cache(None)
def gold_fixes() -> dict:
    """store B/gold_fixes.json (TIPNR ids, store only): wrong or unsupported gold edges
    {rel, x, y, scope: '*' | pericope} and label corrections {unit, surface, to: id | null}."""
    d = load_json(GOLD_FIXES) if GOLD_FIXES.exists() else {}
    edges = {(e["rel"], e["x"], e["y"], e["scope"]) for e in d.get("edges", [])}
    relabel = {(x["unit"], x["surface"]): x["to"] for x in d.get("labels", [])}
    return dict(edges=edges, relabel=relabel, n_edges=len(edges), n_labels=len(relabel))


def bad_edge(rel: str, x: str, y: str, pericope: str) -> bool:
    """rel 'parent' (x parent of y) or 'partner' (either order); scope '*' or the pericope."""
    E = gold_fixes()["edges"]
    pairs = [(x, y)] if rel == "parent" else [(x, y), (y, x)]
    return any((rel, a, b, sc) in E for a, b in pairs for sc in ("*", pericope))


@lru_cache(None)
def labels(fixed: bool = True) -> dict:
    """probe_C1 align3 labels {unit: {surface: individual}}; fixed applies gold_fixes relabels
    (to null drops the label)."""
    lab = load_json(C1 / "labels3.json")
    if not fixed:
        return lab
    out = {u: dict(m) for u, m in lab.items()}
    for (u, c), to in gold_fixes()["relabel"].items():
        out.setdefault(u, {}).pop(c, None)
        if to:
            out[u][c] = to
    return out


def is_person(i: str) -> bool:
    return tipnr()["tip"].get(i, {}).get("cat", "").startswith("PERSON")


@lru_cache(None)
def items_eval() -> tuple:
    return tuple(load_json(C1 / "items_eval.json"))
