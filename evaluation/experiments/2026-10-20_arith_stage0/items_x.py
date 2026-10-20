"""Items of the ordered-chain arithmetic stage-0 (prereg §3, §5 干擾值, K0-1/K0-2) -> store items.json.

52 CPU template items. One random.Random(20261020) draws, in this order, S5, SYNC, F1 (chapter 11 and
以挪士–挪亞 minimums, then the free picks), F3 and F5; S6 takes the four clean pairs. Every draw takes
the candidates in rng-shuffled order and keeps the first depth-first solution that meets its quotas.
- DYN S5 (14): X..Y of one kingdom, L 3–6, whole-year reigns, no 亞她利雅, no 耶羅波安 end; quotas by
  (kingdom, L), every sum once. gold = Σ reigns.
- S6 (4): J08→J09, J11→J12, J13→J14, J14→J15. gold = a_X + R_X − a_Y.
- SYNC (16): the k-th king Y after X (k 2/3) and the other kingdom's king Z of Y's primary sync; drops a
  target 約蘭(I)/何細亞, a path through 亞她利雅, an answer named 約阿施/約蘭, a 耶羅波安 start; k 8+8,
  each Z at most twice. Two name keys (accept = experiment A's gold_accept on ref_v2).
- GEN F1 (12) X's age at Y's birth (2–4 generations), F3 (4) years after the flood (沙拉..他拉; 2 +
  begets from 亞法撒), F5 (2) Y's age the year X died (X ≥2 up, not 以諾, Y alive, one chapter); no
  famous-number answer, none ≥1000. Homonyms (拉麥, 以諾, 拿鶴): X by its father, Y (and F3's X) by its
  son, never by a name on the path.
Dynasty gold comes from the hand reference v2 (experiment A's View), mapped to r4 ids by chain position;
k0_fields asserts that r4 agrees on every field an item uses. Genesis gold comes from gen_layer.
verify_gold recomputes each gold another way: dynasty from the raw ref_v2 rows, Genesis from the verse
numbers read again from verse_units.jsonl by patriarch name with its own numeral parser. Question text
lives in the store only; base context = the struct pericope of X's accession (A's acc_verse) or begetting
verse. Nothing here calls an LLM.
"""
from __future__ import annotations

import collections
import functools
import json
import random
import re
from pathlib import Path
from typing import Callable

import gen_layer as G
import tcanon as TC
import units_x as U
import x_common as X
from engine import homonym
from items_a import acc_verse, gold_accept, template_basis
from regnal import acc_sync

SCHEMA = "arith.items.v1"
KNAME = {"I": "以色列", "J": "猶大"}
OTHER = {"I": "J", "J": "I"}
CN = {2: "二", 3: "三"}

# prereg §3.1 S5
PART_YEAR = ("I05", "I14", "I15", "J17", "J19")
ATHALIAH = "J07"
JEROBOAM = ("I01", "I13")
S5_QUOTA = {("I", 3): 2, ("I", 4): 2, ("I", 5): 1, ("I", 6): 1,
            ("J", 3): 2, ("J", 4): 2, ("J", 5): 2, ("J", 6): 2}
# §3.2 S6
S6_PAIRS = (("J08", "J09"), ("J11", "J12"), ("J13", "J14"), ("J14", "J15"))
# §3.3 SYNC
SYNC_BAD_TARGETS = ("I09", "I19")            # r4 A14 約蘭(I), A30 何細亞: two syncs naming different kings
SYNC_HOMONYM_ANSWERS = ("約阿施", "約蘭")
SYNC_QUOTA = {2: 8, 3: 8}
SYNC_MAX_PER_ANSWER = 2
# §3.4 GEN
F1_MIN = {"c11": 6, "c5m": 4}
F1_N, F3_N, F5_N = 12, 4, 2
FAMOUS = (969, 930, 365, 777, 950, 600, 500, 1656)
GEN_HOMONYMS = ("拉麥", "以諾", "拿鶴")
ENOCH = "以諾"
# candidate pools after every exclusion (prereg §3)
POOLS = {"S5": {"I3": 8, "I4": 5, "I5": 3, "I6": 2, "J3": 11, "J4": 9, "J5": 7, "J6": 5},
         "SYNC": {"k2": 16, "k3": 13, "answer_kings": 9},
         "F1": {"c11": 18, "c5m": 14, "c5a": 6}, "F3": 7, "F5": {"ch5": 27, "ch11": 7}}
UNIT_FLOOR = {"DYN": 10, "GEN": 7}            # §3.5: at least this many items cross segments

Q_S5 = "依列王紀的記載，{x}到{y}（含首尾）的在位年數首尾相接，一共幾年？"
Q_S6 = "{x}生他的兒子{y}時是幾歲？（依列王紀記載的登基年歲與在位年數，首尾相接計算）"
Q_SYNC = "{x}之後的第{k}位{kd}王是誰？他登基時，在位的{okd}王是誰？"
Q_F1 = "依創世記的記載，{x}幾歲時，{y}出生？"
Q_F3 = "依創世記的記載，照創世記11章10節的算法（{son}生於洪水之後{n}年），{x}在洪水之後多少年出生？請答年數。"
Q_F5 = "依創世記的記載，{x}去世那年，{y}幾歲？"


# ---------------------------------------------------------------- numerals and question numbers
_DIG = "零一二三四五六七八九"
_CNV = re.compile(r"(?:(?P<h>[一二兩三四五六七八九])百)?零?(?:(?P<t>[一二兩三四五六七八九])?(?P<ten>十))?"
                  r"(?P<u>[一二兩三四五六七八九])?")
UNITS = {"Y": "年|載", "A": "歲", "M": "個月", "D": "日|天", "C": "位|次|代|任"}
NUM_TOK = r"\d{1,3}(?:,\d{3})+|\d+|[零〇一二兩三四五六七八九十百千]+"


def cn_value(s: str) -> int | None:
    """Positional reading of a Chinese numeral below 1000 (verify_gold's own parser)."""
    m = _CNV.fullmatch(s or "")
    if not s or not m:
        return None
    d = lambda c: 2 if c == "兩" else _DIG.index(c)  # noqa: E731
    tens = (d(m["t"]) if m["t"] else 1) if m["ten"] else 0
    return (d(m["h"]) * 100 if m["h"] else 0) + tens * 10 + (d(m["u"]) if m["u"] else 0)


def int2cn(n: int) -> str:
    """1..999 in the text layer's style (十三, 一百零五, 九百一十二)."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    s = _DIG[h] + "百" if h else ""
    if t:
        s += ("" if t == 1 and not h else _DIG[t]) + "十"
    elif h and u:
        s += "零"
    return s + (_DIG[u] if u else "")


def _num(tok: str) -> int | None:
    return int(tok.replace(",", "")) if tok[0].isdigit() else X.cc.cn2int(tok)


def numbers_in_text(text: str) -> list[int]:
    """Every number of a text, in order (Arabic with thousands separators, Chinese numerals)."""
    return [v for v in (_num(m.group()) for m in re.finditer(NUM_TOK, text)) if v is not None]


def answer_class_numbers(text: str, classes: list[str]) -> list[tuple[int, str]]:
    """(value, unit) of every number written with a unit of the answer classes (prereg §3.5)."""
    units = "|".join(UNITS[c] for c in classes)
    pat = re.compile(rf"({NUM_TOK})(?:多|餘)?(?:個)?({units})")
    return [(_num(m.group(1)), m.group(2)) for m in pat.finditer(text) if _num(m.group(1)) is not None]


# ---------------------------------------------------------------- draws and distractors
def draw(cands: list, rng: random.Random, quota: dict, stratum: Callable, distinct: Callable | None = None,
         cap: Callable | None = None, cap_n: int | None = None) -> list:
    """Candidates in rng-shuffled order; the first depth-first pick meeting the quotas (per stratum),
    each distinct() value once and at most cap_n per cap() group. ValueError when none exists."""
    order = list(cands)
    rng.shuffle(order)
    keys = [stratum(c) for c in order]
    left = [collections.Counter(keys[i:]) for i in range(len(order) + 1)]
    groups = [collections.Counter(cap(c) for c in order[i:]) if cap else None for i in range(len(order) + 1)]
    need, used, seen, picked = collections.Counter(quota), collections.Counter(), set(), []

    def feasible(i: int) -> bool:
        if any(left[i][s] < n for s, n in need.items() if n > 0):
            return False
        return not cap or sum(min(cap_n - used[g], n) for g, n in groups[i].items()) >= sum(need.values())

    def dfs(i: int) -> bool:
        if not +need:
            return True
        if not feasible(i):
            return False
        c, s = order[i], keys[i]
        if need[s] > 0 and (distinct is None or distinct(c) not in seen) and (not cap or used[cap(c)] < cap_n):
            picked.append(c)
            need[s] -= 1
            seen.add(distinct(c) if distinct else None)
            used[cap(c) if cap else None] += 1
            if dfs(i + 1):
                return True
            picked.pop()
            need[s] += 1
            seen.discard(distinct(c) if distinct else None)
            used[cap(c) if cap else None] -= 1
        return dfs(i + 1)
    if not dfs(0):
        raise ValueError(f"no draw meets {dict(quota)}")
    return picked


def distractor_list(gold: int, pairs: list[tuple[int, str]]) -> list[dict]:
    """First kind per value; never the gold, never ≤ 0 (prereg §5 干擾值)."""
    out, seen = [], {gold}
    for v, kind in pairs:
        if v > 0 and v not in seen:
            seen.add(v)
            out.append({"value": v, "kind": kind})
    return out


# ---------------------------------------------------------------- dynasty
@functools.lru_cache(maxsize=1)
def id_map() -> dict[str, str]:
    """ref_v2 id -> r4 id by chain position; the names must agree."""
    VR, V4 = X.ref_v2_view(), X.r4_view()
    m = {}
    for kd in KNAME:
        if len(VR.chain[kd]) != len(V4.chain[kd]):
            raise SystemExit(f"chain {kd}: ref_v2 {len(VR.chain[kd])} kings, r4 {len(V4.chain[kd])}")
        for a, b in zip(VR.chain[kd], V4.chain[kd]):
            if VR.nodes[a]["name"] != V4.nodes[b]["name"]:
                raise SystemExit(f"{a}/{b}: {VR.nodes[a]['name']} is not {V4.nodes[b]['name']}")
            m[a] = b
    return m


def king(VR, x: str) -> str:
    return f"{KNAME[VR.nodes[x]['kingdom']]}王{VR.nodes[x]['name']}"


def s5_candidates(VR, log: dict) -> list[dict]:
    whole, out = [], []
    for kd in KNAME:
        ch = VR.chain[kd]
        for L in range(3, 7):
            for i in range(len(ch) - L + 1):
                path = ch[i:i + L]
                if not set(path) & set(PART_YEAR):
                    whole.append(dict(kingdom=kd, L=L, path=path))
    no_q = [c for c in whole if ATHALIAH not in c["path"]]
    out = [c for c in no_q if c["path"][0] not in JEROBOAM and c["path"][-1] not in JEROBOAM]
    for c in out:
        rs = [VR.nodes[z]["reign"] for z in c["path"]]
        if any(float(r) != int(r) for r in rs):
            raise SystemExit(f"S5 {c['path']}: a reign that is not whole years")
        c["gold"] = sum(int(r) for r in rs)
    log["S5"] = {"whole_year": len(whole), "no_athaliah": len(no_q), "no_jeroboam_end": len(out)}
    return out


def sync_candidates(VR, log: dict) -> list[dict]:
    allc = []
    for kd in KNAME:
        for x in VR.chain[kd]:
            for k in (2, 3):
                y = VR.succ(x, k)
                prim = acc_sync(VR, y) if y else []
                if prim:
                    z, year, verse = prim[0]
                    allc.append(dict(kingdom=kd, k=k, x=x, y=y, z=z, year=year, sync_verse=verse,
                                     path=[VR.succ(x, i) for i in range(k + 1)]))
    c1 = [c for c in allc if c["y"] not in SYNC_BAD_TARGETS]
    c2 = [c for c in c1 if ATHALIAH not in c["path"]]
    c3 = [c for c in c2 if not {VR.nodes[c["y"]]["name"], VR.nodes[c["z"]]["name"]} & set(SYNC_HOMONYM_ANSWERS)]
    c4 = [c for c in c3 if c["x"] not in JEROBOAM]
    log["SYNC"] = {"all": len(allc), "no_bad_target": len(c1), "no_athaliah": len(c2), "no_homonym_answer": len(c3),
                   "no_jeroboam_start": len(c4)}
    return c4


def ref_flags(VR, V4, ids: list[str]) -> list[str]:
    """Same-kingdom homonyms among the kings an item names: ref-only (an alias r4 rejected) or both."""
    m, out = id_map(), []
    for x in dict.fromkeys(ids):
        if homonym(V4, m[x]):
            out.append(f"{VR.nodes[x]['name']} ({x}) has a same-kingdom homonym in r4 and ref_v2")
        elif homonym(VR, x):
            out.append(f"ref_v2 lists another same-kingdom king under {VR.nodes[x]['name']} ({x}); r4 does not, "
                       "so it is named without a father")
    return out


def dyn_item(VR, c: dict, qtype: str, family: str) -> dict:
    """Fields shared by S5, S6 and SYNC items (path in ref ids)."""
    m, V4 = id_map(), X.r4_view()
    p = c["path"]
    seeds_ref = [p[0]] if family == "SYNC" else [p[0], p[-1]]
    v = acc_verse(VR, p[0])
    pid = X.ac.verse_passage()[v]
    touched, nested = U.node_units(p, VR.chain)
    return dict(family=family, qtype=qtype, kingdom=c["kingdom"], chapter=None,
                seeds=[m[s] for s in seeds_ref], seeds_ref=seeds_ref,
                seed_names=[[VR.nodes[s]["kingdom"], VR.nodes[s]["name"]] for s in seeds_ref],
                seed_display=[king(VR, s) for s in seeds_ref], path=[m[z] for z in p], path_ref=list(p),
                L=c.get("L"), k=c.get("k"), units_touched=touched, nested=nested,
                sources=[X.ac.passage_source(pid)], context_from=pid,
                flags=ref_flags(VR, V4, seeds_ref + ([c["y"], c["z"]] if family == "SYNC" else [])))


def arith_key(value: int, classes: list[str], basis: list[str], ordinal: bool = False) -> dict:
    return {"type": "arith", "value": value, "classes": classes, "ordinal": ordinal,
            "basis": [v for v in dict.fromkeys(basis) if v]}


def s5_item(VR, c: dict) -> dict:
    p, rs = c["path"], [int(VR.nodes[z]["reign"]) for z in c["path"]]
    g, n = c["gold"], len(p)
    it = dyn_item(VR, c, "S5", "DYN")
    basis = [VR.nodes[z]["prov"].get("reign") for z in p]
    pairs = [(r, "component") for r in rs] + [(g - rs[0], "drop_first"), (g - rs[-1], "drop_last"),
                                              (g - (n - 1), "handover"), (g - n, "nonacc"),
                                              (g - 1, "off_by_one"), (g + 1, "off_by_one")]
    return dict(it, question=Q_S5.format(x=king(VR, p[0]), y=king(VR, p[-1])), gold=g,
                keys=[arith_key(g, ["Y"], basis)], distractors=distractor_list(g, pairs), tc_basis=basis)


def s6_item(VR, x: str, y: str) -> dict:
    nx, ny = VR.nodes[x], VR.nodes[y]
    if VR.edge_type.get((x, y)) != "son":
        raise SystemExit(f"S6 {x}->{y} is not a son edge")
    g = nx["age"] + int(nx["reign"]) - ny["age"]
    it = dyn_item(VR, dict(kingdom=nx["kingdom"], path=[x, y]), "S6", "S6")
    basis = [nx["prov"].get("age"), nx["prov"].get("reign"), ny["prov"].get("age")]
    pairs = [(nx["age"] + int(nx["reign"]), "father_death_age"), (ny["age"], "son_acc_age"),
             (g - 1, "off_by_one"), (g + 1, "off_by_one")]
    return dict(it, question=Q_S6.format(x=king(VR, x), y=king(VR, y)), gold=g,
                keys=[arith_key(g, ["A", "Y"], basis)], distractors=distractor_list(g, pairs), tc_basis=basis)


def name_key(VR, role: str, z: str, basis: list[str], exempt: list[str]) -> dict:
    return {"type": "name", "role": role, "kingdom": VR.nodes[z]["kingdom"], "gold_ref": z, "gold_id": id_map()[z],
            "accept": gold_accept(VR, z), "exempt": exempt, "basis": [v for v in dict.fromkeys(basis) if v]}


def sync_item(VR, c: dict) -> dict:
    x, y, z, k, kd = c["x"], c["y"], c["z"], c["k"], c["kingdom"]
    it = dyn_item(VR, c, f"SYNC{k}", "SYNC")
    exempt = sorted({nm for w in c["path"] + [z] for nm in VR.names(w)} | set(gold_accept(VR, y))
                    | set(gold_accept(VR, z)))
    yb = template_basis(VR, dict(stratum="S1", seed=x, path=c["path"], answer=y))
    keys = [name_key(VR, "Y", y, yb, exempt), name_key(VR, "Z", z, [c["sync_verse"]], exempt)]
    q = Q_SYNC.format(x=king(VR, x), k=CN[k], kd=KNAME[kd], okd=KNAME[OTHER[kd]])
    return dict(it, question=q, gold={"Y": VR.nodes[y]["name"], "Z": VR.nodes[z]["name"]}, keys=keys,
                distractors=[], z=id_map()[z], z_ref=z, sync=[c["year"], c["sync_verse"]], exempt=exempt,
                tc_basis=[acc_verse(VR, w) for w in c["path"]])


# ---------------------------------------------------------------- Genesis
def beget(gen: dict, nid: str) -> tuple[int, str]:
    return tuple(G.node(gen, nid)["fields"]["beget"])


def gen_display(gen: dict, nid: str, role: str) -> str:
    """The patriarch's name; a homonym by its father (role X) or its chain son (role Y)."""
    n = G.node(gen, nid)
    if n["name"] not in GEN_HOMONYMS:
        return n["name"]
    ch = G.chain(gen, n["chapter"])
    i = ch.index(nid)
    if role == "X":
        return f"{G.node(gen, ch[i - 1])['name']}的兒子{n['name']}"
    return f"{G.node(gen, ch[i + 1])['name']}的父親{n['name']}"


def f1_candidates(gen: dict, log: dict) -> list[dict]:
    out, seen = [], 0
    for ch in G.CHAPTERS:
        ids = G.chain(gen, ch)
        for i, x in enumerate(ids):
            for j in range(i + 2, min(i + 5, len(ids))):
                seen += 1
                y, g = ids[j], G.age_at_birth(gen, x, ids[j])
                if G.node(gen, x)["name"] == ENOCH and g >= G.total(gen, x):
                    continue
                if g in FAMOUS or g >= 1000:
                    continue
                pool = "c11" if ch == 11 else ("c5a" if i < 2 else "c5m")
                out.append(dict(qtype="F1", chapter=ch, pool=pool, path=ids[i:j + 1], gold=g))
    log["F1"] = {"pairs_2_4": seen, "kept": len(out)}
    return out


def f3_candidates(gen: dict, log: dict) -> list[dict]:
    ids = G.chain(gen, 11)
    off = G.node(gen, ids[0])["flood_offset"][0]
    out = [dict(qtype="F3", chapter=11, pool="c11", path=ids[:j + 1],
                gold=off + sum(beget(gen, z)[0] for z in ids[1:j])) for j in range(2, len(ids))]
    out = [c for c in out if c["gold"] not in FAMOUS and c["gold"] < 1000]
    log["F3"] = {"kept": len(out)}
    return out


def f5_candidates(gen: dict, log: dict) -> list[dict]:
    out, seen = [], 0
    for ch in G.CHAPTERS:
        ids = G.chain(gen, ch)
        for i, x in enumerate(ids):
            for j in range(i + 2, len(ids)):
                seen += 1
                y = ids[j]
                g = G.total(gen, x) - G.age_at_birth(gen, x, y)
                if G.node(gen, x)["name"] == ENOCH or not 0 < g < G.total(gen, y):
                    continue
                if g not in FAMOUS and g < 1000:
                    out.append(dict(qtype="F5", chapter=ch, pool=f"ch{ch}", path=ids[i:j + 1], gold=g))
    log["F5"] = {"pairs_2_up": seen, "kept": len(out)}
    return out


def gen_basis(gen: dict, c: dict) -> list[str]:
    p, x = c["path"], c["path"][0]
    if c["qtype"] == "F1":
        return [beget(gen, z)[1] for z in p[:-1]]
    if c["qtype"] == "F3":
        return [G.node(gen, x)["flood_offset"][1]] + [beget(gen, z)[1] for z in p[1:-1]]
    f = G.node(gen, x)["fields"]
    life = [f["total"][1]] if "total" in f else [f["beget"][1], f["remain"][1]]
    return life + [beget(gen, z)[1] for z in p[:-1]]


def gen_distractors(gen: dict, c: dict) -> list[dict]:
    p, g, qt = c["path"], c["gold"], c["qtype"]
    ch = G.chain(gen, c["chapter"])
    top = p[1] if qt == "F3" else p[0]                # the first begetting counted
    seed = p[-1] if qt == "F3" else p[0]               # whose lifespan / remaining years
    bs = [beget(gen, z)[0] for z in p[:-1]]
    f = G.node(gen, seed)["fields"]
    life = [(G.total(gen, seed), "lifespan")] + ([(f["remain"][0], "remaining")] if "remain" in f else [])
    nxt = [beget(gen, p[-1])[0]] if "beget" in G.node(gen, p[-1])["fields"] else []
    i = ch.index(top)
    before = [beget(gen, ch[i - 1])[0]] if i > 0 else []
    if qt == "F1":
        pairs = [(b, "edge") for b in bs] + [(g - bs[-1], "short_chain"), (g - bs[0], "short_chain")] + \
                [(g + b, "long_chain") for b in nxt + before] + life
    elif qt == "F3":
        off = G.node(gen, p[0])["flood_offset"][0]
        pairs = [(g - off, "no_anchor"), (g - bs[-1], "short_chain")] + [(g + b, "long_chain") for b in nxt] + \
                [(bs[-1], "edge")] + life
    else:
        tx, s = G.total(gen, p[0]), sum(bs)
        pairs = [(tx, "lifespan"), (s, "birth_age")] + life[1:] + [(tx - (s - bs[-1]), "short_chain")] + \
                [(tx - (s + b), "long_chain") for b in nxt] + [(G.total(gen, p[-1]), "lifespan_y")]
    return distractor_list(g, pairs + [(g - 1, "off_by_one"), (g + 1, "off_by_one")])


def gen_item(gen: dict, c: dict) -> dict:
    p, qt = c["path"], c["qtype"]
    seeds = [p[-1]] if qt == "F3" else [p[0], p[-1]]
    roles = ["Y"] if qt == "F3" else ["X", "Y"]
    shown = [gen_display(gen, s, r) for s, r in zip(seeds, roles)]
    head = G.chain(gen, 11)[:2]
    if qt == "F1":
        q = Q_F1.format(x=shown[0], y=shown[1])
    elif qt == "F3":
        q = Q_F3.format(son=G.node(gen, head[1])["name"], n=int2cn(G.node(gen, head[0])["flood_offset"][0]),
                        x=shown[0])
    else:
        q = Q_F5.format(x=shown[0], y=shown[1])
    v = beget(gen, seeds[0])[1]
    pid = X.ac.verse_passage()[v]
    touched, nested = U.edge_units(p, {ch: G.chain(gen, ch) for ch in G.CHAPTERS})
    names = [G.node(gen, z)["name"] for z in p]
    return dict(family="GEN", qtype=qt, question=q, kingdom=None, chapter=c["chapter"], pool=c["pool"],
                seeds=seeds, seeds_ref=None, seed_names=[[None, G.node(gen, s)["name"]] for s in seeds],
                seed_display=shown, path=list(p), path_ref=None, path_names=names, L=None, k=None,
                d=len(p) - 1, gold=c["gold"],
                keys=[arith_key(c["gold"], ["Y"] if qt == "F3" else ["A", "Y"], gen_basis(gen, c), qt == "F3")],
                distractors=gen_distractors(gen, c), units_touched=touched, nested=nested,
                flood_offset=G.node(gen, head[0])["flood_offset"][0] if qt == "F3" else None,
                sources=[X.ac.passage_source(pid)], context_from=pid,
                flags=[f"homonym shown as {s}" for s in shown if s not in names])


# ---------------------------------------------------------------- K0-1 and independent gold
def k0_fields(item: dict) -> list[str]:
    """K0-1: r4 agrees with ref_v2 on every field the dynasty item uses (empty = ok)."""
    VR, V4, m = X.ref_v2_view(), X.r4_view(), id_map()
    p, out = item["path_ref"], []
    if item["path"] != [m[z] for z in p] or item["seeds"] != [m[z] for z in item["seeds_ref"]]:
        out.append("r4 ids are not the mapped ref ids")
    for z in p + ([item["z_ref"]] if item.get("z_ref") else []):
        if VR.nodes[z]["name"] != V4.nodes[m[z]]["name"] or VR.nodes[z]["kingdom"] != V4.nodes[m[z]]["kingdom"]:
            out.append(f"{z}: name or kingdom")
    for a, b in zip(p, p[1:]):
        if VR.succ(a) != b or V4.succ(m[a]) != m[b]:
            out.append(f"{a}->{b}: not adjacent in both")
        if VR.edge_type.get((a, b)) != V4.edge_type.get((m[a], m[b])):
            out.append(f"{a}->{b}: edge type")
    fields = {"S5": [(z, "reign") for z in p], "S6": [(p[0], "age"), (p[0], "reign"), (p[1], "age")]}
    for z, f in fields.get(item["qtype"], []):
        a, b = VR.nodes[z][f], V4.nodes[m[z]][f]
        if a is None or b is None or float(a) != float(b):
            out.append(f"{z}.{f}: ref {a} r4 {b}")
    if item["family"] == "SYNC":
        r = [(m[o], yr) for o, yr, _v in acc_sync(VR, p[-1])]
        s = [(o, yr) for o, yr, _v in acc_sync(V4, m[p[-1]])]
        if r != s or not r or r[0][0] != item["z"]:
            out.append(f"{p[-1]}: primary sync ref {r} r4 {s}")
    return out


@functools.lru_cache(maxsize=1)
def _ref_rows() -> dict:
    return {r["id"]: r for r in X.read_json(X.REF_V2)}


def _verify_dyn(item: dict) -> tuple[object, list[str]]:
    rows, p, out = _ref_rows(), item["path_ref"], []
    for a, b in zip(p, p[1:]):
        if not rows[b]["pred"] or rows[b]["pred"][0] != a:
            out.append(f"{b}: pred is not {a}")
    if item["seeds_ref"] != ([p[0]] if item["family"] == "SYNC" else [p[0], p[-1]]):
        out.append(f"seeds {item['seeds_ref']} are not the path ends")
    if item["qtype"] == "S5":
        return sum(rows[z]["reign"][1] for z in p), out
    if item["qtype"] == "S6":
        x, y = p
        if rows[y]["pred"][1] != "son":
            out.append(f"{y}: not a son edge")
        return rows[x]["age"][0] + rows[x]["reign"][1] - rows[y]["age"][0], out
    cur = item["seeds_ref"][0]
    for _ in range(item["k"]):
        nxt = [i for i, r in rows.items() if r["pred"] and r["pred"][0] == cur and r["kingdom"] == rows[cur]["kingdom"]]
        if len(nxt) != 1:
            return None, out + [f"{cur}: {len(nxt)} successors"]
        cur = nxt[0]
    prim = [s for s in rows[cur]["sync"] if s[3] == "primary"]
    if cur != p[-1] or len(prim) != 1 or prim[0][0] != item["z_ref"]:
        out.append(f"walk ends at {cur} with primary syncs {prim}")
    return ({"Y": rows[cur]["name"], "Z": rows[prim[0][0]]["name"]} if prim else None), out


@functools.lru_cache(maxsize=1)
def _gen_text() -> dict[int, list[tuple[str, str]]]:
    rows = [r for r in X.jsonl(X.TEXT / "verse_units.jsonl") if r["book_id"] == "gen" and r["chapter"] in G.CHAPTERS]
    out: dict[int, list] = {c: [] for c in G.CHAPTERS}
    for r in sorted(rows, key=lambda r: r["ord"]):
        out[r["chapter"]].append((r["unit_key"], r["text"]))
    return out


def _one(ch: int, pat: str) -> tuple[int | None, str | None]:
    """The single verse of chapter ch matching pat; its numeral (group 1) by cn_value."""
    hits = [(cn_value(m.group(1)), vid) for vid, t in _gen_text()[ch] for m in re.finditer(pat, t)]
    return hits[0] if len(hits) == 1 else (None, None)


def _verify_gen(item: dict) -> tuple[object, list[str]]:
    names, ch, qt, out = item["path_names"], item["chapter"], item["qtype"], []
    num, nb = r"([零〇一二兩三四五六七八九十百]+)", r"(?<![一-鿿])"
    found = [_one(ch, rf"{nb}{re.escape(f)}(?:活到)?整?{num}歲") for f in names[:-1]]
    if any(v is None for v, _vid in found):
        return None, [f"begetting verse not found once for {names[:-1]}"]
    bs, basis = [v for v, _vid in found], [vid for _v, vid in found]
    text = _gen_text()[ch]
    keys = [vid for vid, _t in text]
    for (_v, vid), son in zip(found, names[1:]):
        i = keys.index(vid)
        if son not in "".join(t for _k, t in text[i:i + 2]):   # the son is named there or in the next verse
            out.append(f"{vid} does not name {son}")
    if qt == "F1":
        g = sum(bs)
    elif qt == "F3":
        off, vid = _one(ch, rf"洪水以後{num}年")
        g, basis = (off + sum(bs[1:]), [vid] + basis[1:]) if off is not None else (None, basis)
    else:
        t, vid = _one(ch, rf"{nb}{re.escape(names[0])}共活了{num}歲")
        if t is None:
            r, rvid = _one(ch, rf"{nb}{re.escape(names[0])}生{re.escape(names[1])}之後，?(?:又活了|又在世|與上帝同行){num}年")
            t, life = (bs[0] + r, [basis[0], rvid]) if r is not None else (None, [])
        else:
            life = [vid]
        g, basis = (t - sum(bs) if t is not None else None), life + basis
    if g is not None and list(dict.fromkeys(basis)) != item["keys"][0]["basis"]:
        out.append(f"basis verses {basis} differ from the key's")
    return g, out


def verify_gold(item: dict) -> list[str]:
    """Independent recomputation of the item's gold (empty = agrees): dynasty from the raw ref_v2 rows,
    Genesis from the verse numbers read again from the text layer (K0-1 gold, K0-2 雙路核對)."""
    g, out = (_verify_gen if item["family"] == "GEN" else _verify_dyn)(item)
    if g != item["gold"]:
        out.append(f"recomputed gold {g} is not the item's {item['gold']}")
    for k in item["keys"]:
        if k["type"] == "arith" and k["value"] != item["gold"]:
            out.append("key value is not the gold")
        if k["type"] == "name" and item["gold"][k["role"]] not in k["accept"]:
            out.append(f"key {k['role']} does not accept the gold name")
    return out


# ---------------------------------------------------------------- build
def tcanon_fields(it: dict) -> dict:
    if it["family"] == "GEN":
        return {"tcanon_complete": None, "tcanon_missing": None}
    tc = TC.tcanon([tuple(s) for s in it["seed_names"]], it["question"])
    missing = [v for v in it["tc_basis"] if v not in set(tc["verses"])]
    return {"tcanon_complete": not missing, "tcanon_missing": missing}


def pool_sizes(s5, sync, f1, f3, f5) -> dict:
    s = collections.Counter(f"{c['kingdom']}{c['L']}" for c in s5)
    return {"S5": {k: s[k] for k in POOLS["S5"]},
            "SYNC": {"k2": sum(c["k"] == 2 for c in sync), "k3": sum(c["k"] == 3 for c in sync),
                     "answer_kings": len({c["z"] for c in sync})},
            "F1": {k: sum(c["pool"] == k for c in f1) for k in POOLS["F1"]}, "F3": len(f3),
            "F5": {k: sum(c["pool"] == k for c in f5) for k in POOLS["F5"]}}


def draws(rng: random.Random, s5, sync, f1, f3, f5) -> dict:
    pick_s5 = draw(s5, rng, S5_QUOTA, lambda c: (c["kingdom"], c["L"]), distinct=lambda c: c["gold"])
    pick_sy = draw(sync, rng, SYNC_QUOTA, lambda c: c["k"], cap=lambda c: c["z"], cap_n=SYNC_MAX_PER_ANSWER)
    first = draw([c for c in f1 if c["pool"] in F1_MIN], rng, F1_MIN, lambda c: c["pool"])
    rest = draw([c for c in f1 if c not in first], rng, {"any": F1_N - len(first)}, lambda c: "any")
    pick_f3 = draw(f3, rng, {"F3": F3_N}, lambda c: "F3")
    pick_f5 = draw(f5, rng, {"F5": F5_N}, lambda c: "F5")
    return {"S5": pick_s5, "SYNC": pick_sy, "F1": first + rest, "F3": pick_f3, "F5": pick_f5}


def number(items: list[dict], prefix_of: Callable) -> list[dict]:
    seen: collections.Counter = collections.Counter()
    out = []
    for it in items:
        p = prefix_of(it)
        seen[p] += 1
        out.append({"id": f"{p}_{seen[p]:02d}", **it})
    return out


def checks(items: list[dict], pools: dict) -> dict:
    out = {"pools": [] if pools == POOLS else [f"pools {pools} are not prereg §3's {POOLS}"],
           "pins": [f"{p.name}: sha256 differs" for p, want in ((X.REF_V2, X.REF_V2_SHA256),
                                                                 (X.R4_LAYER, X.R4_LAYER_SHA256))
                    if X.sha256_file(p) != want],
           "k0_1": [f"{it['id']}: {p}" for it in items if it["family"] != "GEN" for p in k0_fields(it)],
           "gold": [f"{it['id']}: {p}" for it in items for p in verify_gold(it)],
           "questions": [], "units": []}
    for it in items:
        if it["family"] == "SYNC":
            continue
        found = answer_class_numbers(it["question"], it["keys"][0]["classes"])
        if found != ([(it["flood_offset"], "年")] if it["qtype"] == "F3" else []) or \
                it["gold"] in numbers_in_text(it["question"]):
            out["questions"].append(f"{it['id']}: answer-class numbers {found}")
    for fam, floor in UNIT_FLOOR.items():
        n = sum(not it["nested"] for it in items if it["family"] == fam)
        if n < floor:
            out["units"].append(f"{fam}: {n} items cross segments, prereg §3.5 expects ≥{floor}")
    return out


def build_items(seed: int = X.SEED, gen: dict | None = None) -> dict:
    """The 52 items (prereg §3) with their pools and checks; deterministic for a seed."""
    VR, gen, log = X.ref_v2_view(), gen or G.build(), {}
    cand = dict(S5=s5_candidates(VR, log), SYNC=sync_candidates(VR, log), F1=f1_candidates(gen, log),
                F3=f3_candidates(gen, log), F5=f5_candidates(gen, log))
    picks = draws(random.Random(seed), *cand.values())
    order = lambda kd, z: (kd, VR.idx(z))  # noqa: E731
    s5 = [s5_item(VR, c) for c in sorted(picks["S5"], key=lambda c: (order(c["kingdom"], c["path"][0]), c["L"]))]
    s6 = [s6_item(VR, x, y) for x, y in S6_PAIRS]
    sy = [sync_item(VR, c) for c in sorted(picks["SYNC"], key=lambda c: (c["k"], order(c["kingdom"], c["x"])))]
    gn = [gen_item(gen, c) for qt in ("F1", "F3", "F5")
          for c in sorted(picks[qt], key=lambda c: (c["chapter"], c["path"][0], len(c["path"])))]
    items = number(s5 + s6 + sy + gn, lambda it: it["qtype"])
    items = [dict(it, **tcanon_fields(it)) for it in items]
    pools = pool_sizes(*cand.values())
    return {"schema": SCHEMA, "seed": seed, "n_items": len(items), "items": items, "pools": pools,
            "pool_log": log, "checks": checks(items, pools),
            "inputs": {"ref_v2_sha256": X.sha256_file(X.REF_V2), "r4_sha256": X.sha256_file(X.R4_LAYER),
                       "text_digest": X.TEXT_DIGEST, "gen_layer_sha256": G.sha256(gen)}}


def items_sha256(doc: dict) -> str:
    """sha256 of the file x_common.write_json writes for doc."""
    return X.sha256_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")


def write(doc: dict, path: Path | str = X.ITEMS) -> Path:
    bad = {k: v for k, v in doc["checks"].items() if v}
    if bad:
        raise SystemExit(f"items not written, checks failed: {bad}")
    return X.write_json(path, doc)


def load(path: Path | str = X.ITEMS) -> dict:
    return X.read_json(path)
