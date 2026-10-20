"""Arms G and T-rows of the ordered-chain arithmetic stage-0 (prereg §4; K0-3, K0-6). CPU only.

From the seeds only (never the question type) the engine takes a window of chain rows and writes
derived lines; T-rows is G's kept rows without the lines. Dynasty rows are the prod row text (the
backend engine's ``row_text`` on the r4 layer, primary synchronism included); Genesis rows come from
gen_layer.json as 「X：N歲生Y；生Y後又活M年；共活T歲」 with Y the chain son only (missing fields left
out; the flood-anchored row also says when its son was born after the flood).

- Dynasty, two same-kingdom seeds X before Y: the reigns X..Y summed end to end, the hand-overs
  between them, and for an adjacent father and son the father's age at the son's birth. Every seed:
  its k-th successor (k=1..3) and, where that successor has a primary synchronism, the other
  kingdom's king he acceded under.
- Genesis, ancestor X and descendant Y: X's age at Y's birth, X's lifespan, and Y at X's death (or
  who died first; the taken one: taken at his age). Every chapter-11 seed but the flood-anchored one:
  its birth in years after the flood.

Windows: two seeds X-1..Y+1; one dynasty seed X-1..X+4; Genesis inside the seeds' chapter, from the
flood-anchored row in chapter 11. Over the cap the successor lines go first (largest k first, later
seed first), then the window's outer rows (later first); the core rows (X..Y, X..X+3, anchor..seed)
are never dropped. ``check_lines`` recomputes every derived line from the gold layers (ref_v2,
gen_layer), checks every Genesis row's begetting field (the layer's age, one son: the next row of the
chapter, else the first son listed) and bounds every stated Genesis age by that person's lifespan;
``check_card`` holds the K0-6 invariants. Nothing here calls an LLM or writes a file.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

import x_common as X
from engine import DERIVED_HEADER  # experiment A's A/engine.py, unchanged (the backend engine's header too)

SUCC_K = (1, 2, 3)
TAKEN_ID = "G05.06"                 # SPEC id of the one taken at gen.5.24 (no death, no 「已去世」)
DEFAULT_CLASSES = ("Y", "A")        # an arithmetic key without classes: years or ages
Line = dict[str, Any]


# ---------------------------------------------------------------- rendering

def line_text(head: str, payload: str) -> str:
    """A derived line; a line written whole (no 「head：」) has an empty head."""
    return f"{head}：{payload}" if head else payload


def render(row_texts: list[str], lines) -> str:
    """Rows one per line, then A's header and the derived lines (experiment A's layout)."""
    out = list(row_texts)
    if lines:
        out += [DERIVED_HEADER] + [line_text(h, p) for h, p in lines]
    return "\n".join(out)


def _line(kind: str, head: str, payload: str, value, unit: str, seeds, k: int | None = None) -> Line:
    return {"kind": kind, "head": head, "payload": payload, "value": value, "unit": unit, "seeds": list(seeds),
            "k": k}


def _whole(r) -> bool:
    return r is not None and r >= 1 and float(r).is_integer()


# ---------------------------------------------------------------- dynasty (r4 view, prod row text)

def _bare(V, x) -> str:
    """A king's name, with A's 「（F的兒子）」 when another king of his kingdom bears it."""
    n = V.nodes[x]
    return n["name"] + (f"（{n['father']}的兒子）" if n["father"] and X.backend().engine.homonym(V, x) else "")


def dyn_pair_lines(V, x: str, y: str) -> list[Line]:
    """Sum of reigns, hand-overs and (adjacent son edge) the father's age, for X before Y."""
    eng = X.backend().engine
    i, j = V.idx(x), V.idx(y)
    seg, dx, dy = V.chain[V.nodes[x]["kingdom"]][i:j + 1], eng.desc(V, x), eng.desc(V, y)
    out, reigns = [], [V.nodes[z]["reign"] for z in seg]
    if all(_whole(r) for r in reigns):
        n = int(sum(reigns))
        out.append(_line("sum", f"{dx}到{dy}（含首尾，共{len(seg)}位）在位年數首尾相接合計", f"{n}年", n, "Y", (x, y)))
    out.append(_line("handover", "", f"{dx}到{dy}之間王位交接{j - i}次", j - i, "C", (x, y)))
    a, r, b = V.nodes[x]["age"], V.nodes[x]["reign"], V.nodes[y]["age"]
    if j - i == 1 and V.edge_type.get((x, y)) == "son" and a is not None and b is not None and _whole(r):
        n = a + int(r) - b
        out.append(_line("father_age", f"{dx}生{dy}時", f"{a}歲＋{int(r)}年−{b}歲＝{n}歲", n, "A", (x, y)))
    return out


def dyn_succ_lines(V, x: str) -> list[Line]:
    """X's k-th successors (k=1..3), each with the other kingdom's king at his accession."""
    eng, reg = X.backend().engine, X.backend().regnal
    out = []
    for k in SUCC_K:
        y = V.succ(x, k)
        if y is None:
            break
        ny, payload, nz = V.nodes[y]["name"], _bare(V, y), None
        sync = reg.acc_sync(V, y)
        if sync:
            z, year, _verse = sync[0]
            nz = V.nodes[z]["name"]
            payload += f"；{ny}登基時對方國在位：{_bare(V, z)}（{ny}於{nz}第{year}年登基）"
        head = f"{eng.desc(V, x)}之後第{k}位{eng.KNAME[V.nodes[x]['kingdom']]}王"
        out.append(_line("succ", head, payload, {"Y": ny, "Z": nz}, "N", (x,), k))
    return out


def dyn_window(V, seeds: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(seeds in chain order, window rows, core rows) on the seeds' chain."""
    if not 1 <= len(seeds) <= 2 or len(set(seeds)) != len(seeds) or any(s not in V.nodes or V.idx(s) is None
                                                                          for s in seeds):
        raise ValueError(f"dynasty seeds must be one or two distinct chain kings: {seeds}")
    if len({V.nodes[s]["kingdom"] for s in seeds}) != 1:
        raise ValueError(f"dynasty seeds of two kingdoms: {seeds}")
    xs = sorted(seeds, key=V.idx)
    chain, i, j = V.chain[V.nodes[xs[0]]["kingdom"]], V.idx(xs[0]), V.idx(xs[-1])
    lo, hi, core_hi = (i - 1, j + 1, j) if len(xs) == 2 else (i - 1, i + 4, i + 3)
    return xs, chain[max(lo, 0):hi + 1], chain[i:core_hi + 1]


def dyn_parts(V, seeds: list[str]) -> tuple[list[str], list[str], dict[str, str], list[Line]]:
    xs, window, core = dyn_window(V, seeds)
    lines = (dyn_pair_lines(V, *xs) if len(xs) == 2 else []) + [ln for x in xs for ln in dyn_succ_lines(V, x)]
    return window, core, {y: X.backend().engine.row_text(V, y) for y in window}, lines


# ---------------------------------------------------------------- Genesis (gen_layer.json)

def _nodes(gen: dict) -> dict[str, dict]:
    return {n["id"]: n for n in gen["nodes"]}


def _f(node: dict, field: str):
    v = node["fields"].get(field)
    return v[0] if v else None


def gen_chain(gen: dict, chapter: int) -> list[str]:
    return [n["id"] for n in sorted((n for n in gen["nodes"] if n["chapter"] == chapter), key=lambda n: n["order"])]


def gen_anchor(gen: dict, chapter: int) -> str | None:
    """The chapter's flood-anchored row (its son born flood_offset years after the flood)."""
    return next((x for x in gen_chain(gen, chapter) if _nodes(gen)[x].get("flood_offset")), None)


def taken(node: dict) -> bool:
    return bool(node.get("taken")) or node["id"] == TAKEN_ID


def gen_lifespan(gen: dict, x: str) -> int | None:
    """Stated lifespan, else the layer's derived one (chapter 11: beget + remain)."""
    t = _f(_nodes(gen)[x], "total")
    return t if t is not None else gen.get("derived", {}).get("total", {}).get(x)


def son_name(gen: dict, x: str) -> str | None:
    """The chain son: the son of x's in-chapter edge, else the first son the layer lists."""
    nodes = _nodes(gen)
    for e in gen.get("edges", []):
        if e[0] == x and e[1] in nodes:
            return nodes[e[1]]["name"]
    return (nodes[x].get("sons") or [None])[0]


def gen_row(gen: dict, x: str) -> str:
    """「X：N歲生Y；生Y後又活M年；共活T歲」 (prereg §4): Y is the chain son only (son_name), also when the
    verse names several sons."""
    n, son = _nodes(gen)[x], son_name(gen, x)
    b, r, t = _f(n, "beget"), _f(n, "remain"), _f(n, "total")
    parts = [f"{b}歲生{son or '子'}"] if b is not None else []
    if n.get("flood_offset") and son:
        parts.append(f"{son}生於洪水後{n['flood_offset'][0]}年")
    parts += ([f"生{son or '子'}後又活{r}年"] if r is not None else []) + ([f"共活{t}歲"] if t is not None else [])
    return f"{n['name']}：" + "；".join(parts)


def _death_line(gen: dict, x: str, y: str, n: int, t: int) -> Line | None:
    nodes, ty = _nodes(gen), gen_lifespan(gen, y)
    nx, ny, m = nodes[x]["name"], nodes[y]["name"], t - n
    if taken(nodes[x]):
        return _line("taken", "", f"{nx}在{t}歲時被取去", t, "A", (x,))
    if m <= 0:
        return _line("died_before_birth", "", f"{nx}在{ny}出生前{-m}年去世", -m, "Y", (x, y))
    if ty is None:
        return None
    if m < ty:
        return _line("death_age", f"{nx}去世時{ny}的年齡", f"{m}歲", m, "A", (x, y))
    verb = "已被取去" if taken(nodes[y]) else "已去世"
    return _line("died_first", "", f"{ny}在{nx}去世前{m - ty}年{verb}", m - ty, "Y", (x, y))


def gen_pair_lines(gen: dict, x: str, y: str) -> list[Line]:
    """X's age at Y's birth (only when X was alive: never an age over X's lifespan), X's lifespan, Y at X's death."""
    nodes, chain = _nodes(gen), gen_chain(gen, _nodes(gen)[x]["chapter"])
    begets = [_f(nodes[z], "beget") for z in chain[chain.index(x):chain.index(y)]]
    if None in begets:
        return []
    n, t, out = sum(begets), gen_lifespan(gen, x), []
    if t is None or n <= t:
        out.append(_line("born_age", f"{nodes[y]['name']}出生時{nodes[x]['name']}的年齡", f"{n}歲", n, "A", (x, y)))
    if t is not None:
        out.append(_line("total", f"{nodes[x]['name']}的總壽數", f"{t}歲", t, "A", (x,)))
        out += [d for d in (_death_line(gen, x, y, n, t),) if d]
    return out


def gen_flood_line(gen: dict, x: str) -> Line | None:
    """「X在洪水之後N年出生」 for a seed after the flood-anchored row of its chapter."""
    nodes = _nodes(gen)
    chain, a = gen_chain(gen, nodes[x]["chapter"]), gen_anchor(gen, nodes[x]["chapter"])
    if a is None or chain.index(x) <= chain.index(a):
        return None
    begets = [_f(nodes[z], "beget") for z in chain[chain.index(a) + 1:chain.index(x)]]
    if None in begets:
        return None
    n = nodes[a]["flood_offset"][0] + sum(begets)
    return _line("flood", "", f"{nodes[x]['name']}在洪水之後{n}年出生", n, "Y", (x,))


def gen_window(gen: dict, seeds: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(seeds in chain order, window rows, core rows) inside the seeds' chapter."""
    nodes = _nodes(gen)
    if not 1 <= len(seeds) <= 2 or len(set(seeds)) != len(seeds) or any(s not in nodes for s in seeds):
        raise ValueError(f"Genesis seeds must be one or two distinct layer rows: {seeds}")
    if len({nodes[s]["chapter"] for s in seeds}) != 1:
        raise ValueError(f"Genesis seeds of two chapters: {seeds}")
    chain = gen_chain(gen, nodes[seeds[0]]["chapter"])
    xs = sorted(seeds, key=chain.index)
    i, j, a = chain.index(xs[0]), chain.index(xs[-1]), gen_anchor(gen, nodes[seeds[0]]["chapter"])
    lo = core_lo = i
    if a is not None and chain.index(a) <= i:
        lo = core_lo = chain.index(a)
    return xs, chain[max(min(lo, i - 1), 0):j + 2], chain[core_lo:j + 1]


def gen_parts(gen: dict, seeds: list[str]) -> tuple[list[str], list[str], dict[str, str], list[Line]]:
    xs, window, core = gen_window(gen, seeds)
    lines = (gen_pair_lines(gen, *xs) if len(xs) == 2 else []) + [fl for x in xs if (fl := gen_flood_line(gen, x))]
    return window, core, {y: gen_row(gen, y) for y in window}, lines


# ---------------------------------------------------------------- the card

def fit(texts: dict[str, str], window: list[str], core: list[str], lines: list[Line], cap: int):
    """Drop successor lines (largest k, then later), then outer rows (later first), until the G block fits."""
    rows, kept = list(window), list(lines)

    def size() -> int:
        return len(render([texts[y] for y in rows], [(ln["head"], ln["payload"]) for ln in kept]))
    while size() > cap:
        succ = [i for i, ln in enumerate(kept) if ln["kind"] == "succ"]
        outer = [i for i, y in enumerate(rows) if y not in core]
        if succ:
            kept.pop(max(succ, key=lambda i: (kept[i]["k"], i)))
        elif outer:
            rows.pop(outer[-1])
        else:
            break
    return rows, kept, len(window) - len(rows), len(lines) - len(kept)


def covered(item: dict, lines: list[Line]) -> bool:
    """Some derived line holds the gold: the value in a unit the key accepts, or both king names."""
    gold = item.get("gold")
    if isinstance(gold, dict):
        want = {"Y": gold.get("Y"), "Z": gold.get("Z")}
        return any(ln["kind"] == "succ" and ln["value"] == want for ln in lines)
    classes = next((k.get("classes") for k in item.get("keys", []) if k.get("type") == "arith"), None)
    return gold is not None and any(ln["unit"] in (classes or DEFAULT_CLASSES) and ln["value"] == gold
                                    and str(gold) in ln["payload"] for ln in lines)


def card(item: dict, *, r4=None, gen: dict | None = None, cap: int = X.CAP_CHARS) -> dict:
    """G (rows + derived lines) and T-rows (the same kept rows) for one item's seeds."""
    if item["family"] == "GEN":
        window, core, texts, lines = gen_parts(gen if gen is not None else X.read_json(X.GEN_LAYER), item["seeds"])
    else:
        window, core, texts, lines = dyn_parts(r4 if r4 is not None else X.r4_view(), item["seeds"])
    rows, kept, dropped_rows, dropped_lines = fit(texts, window, core, lines, cap)
    pairs = [[ln["head"], ln["payload"]] for ln in kept]
    g, t = render([texts[y] for y in rows], pairs), render([texts[y] for y in rows], [])
    return {"rows": rows, "lines": pairs, "g_block": g, "t_block": t, "covered": covered(item, kept),
            "dropped_rows": dropped_rows, "dropped_lines": dropped_lines, "chars_g": len(g), "chars_t": len(t),
            "protected_rows": core, "window": window, "over_cap": len(g) > cap,
            "tags": [{k: ln[k] for k in ("kind", "seeds", "k", "value", "unit")} for ln in kept]}


def check_card(item: dict, c: dict, cap: int = X.CAP_CHARS) -> list[str]:
    """K0-6 problems of one card (empty = ok): block sizes, core rows kept, T-rows = G's rows, covered."""
    out = []
    if c["chars_g"] != len(c["g_block"]) or c["chars_t"] != len(c["t_block"]):
        out.append("chars_g/chars_t are not the block lengths")
    out += [f"{a} block {len(c[b])} chars > {cap}" for a, b in (("G", "g_block"), ("T-rows", "t_block"))
            if len(c[b]) > cap]
    out += [f"core row {y} dropped" for y in c["protected_rows"] if y not in c["rows"]]
    if len(c["t_block"].split("\n") if c["t_block"] else []) != len(c["rows"]):
        out.append("T-rows does not hold the kept rows")
    if c["g_block"] != (c["t_block"] + (f"\n{render([], c['lines'])}" if c["lines"] else "")):
        out.append("G block is not T-rows' rows plus the derived lines")
    if len(c["tags"]) != len(c["lines"]):
        out.append("lines and tags differ in number")
    elif c["covered"] != covered(item, [dict(t, payload=p) for t, (_h, p) in zip(c["tags"], c["lines"])]):
        out.append("covered flag does not match the lines")
    return out


# ---------------------------------------------------------------- K0-3: lines against the gold layers

def check_lines(item: dict, c: dict, gen: dict | None = None, *, ref=None, r4=None) -> list[str]:
    """Problems of the card's derived lines recomputed from the gold layers (empty = ok)."""
    if len(c["lines"]) != len(c["tags"]):
        return ["lines and tags differ in number"]
    if item["family"] == "GEN":
        return _check_gen(item, c, gen if gen is not None else X.read_json(X.GEN_LAYER))
    return _check_dyn(item, c, ref if ref is not None else X.ref_v2_view(), r4 if r4 is not None else X.r4_view())


KING = r"(?:以色列|猶大)王[^：；（）]+?(?:（[^（）]+?的兒子）)?"
NAME = r"[^：；（）]+?(?:（[^（）]+?的兒子）)?"
PLAIN = r"[^：；（）]+?"
KING_PARTS = re.compile(r"(?P<kd>以色列|猶大)王(?P<name>[^（）]+?)(?:（(?P<f>[^（）]+?)的兒子）)?")
NAME_PARTS = re.compile(r"(?P<kd>)(?P<name>[^（）]+?)(?:（(?P<f>[^（）]+?)的兒子）)?")
DYN_RE = {
    "sum": re.compile(rf"(?P<x>{KING})到(?P<y>{KING})（含首尾，共(?P<n>[0-9]+)位）在位年數首尾相接合計：(?P<v>[0-9]+)年"),
    "handover": re.compile(rf"(?P<x>{KING})到(?P<y>{KING})之間王位交接(?P<v>[0-9]+)次"),
    "father_age": re.compile(rf"(?P<x>{KING})生(?P<y>{KING})時：(?P<a>[0-9]+)歲＋(?P<r>[0-9]+)年−(?P<b>[0-9]+)歲"
                             rf"＝(?P<v>[0-9]+)歲"),
    "succ": re.compile(rf"(?P<x>{KING})之後第(?P<k>[0-9]+)位(?P<kd>以色列|猶大)王：(?P<y>{NAME})"
                       rf"(?:；(?P<y2>{PLAIN})登基時對方國在位：(?P<z>{NAME})（(?P<y3>{PLAIN})於(?P<z2>{PLAIN})"
                       rf"第(?P<n>[0-9]+)年登基）)?"),
}


def ref_id(V4, VR, x: str) -> str | None:
    """The reference king at r4 king x's chain position (names checked)."""
    if x not in V4.nodes:
        return None
    kd, i = V4.nodes[x]["kingdom"], V4.idx(x)
    if i is None or i >= len(VR.chain.get(kd, ())):
        return None
    rid = VR.chain[kd][i]
    return rid if V4.nodes[x]["name"] in VR.names(rid) else None


def _is(VR, rid: str | None, text: str | None, kingdom: bool = True) -> bool:
    """text names reference king rid (「猶大王N」 or bare 「N」, an optional 「（F的兒子）」 his father)."""
    m = (KING_PARTS if kingdom else NAME_PARTS).fullmatch(text or "")
    if m is None or rid is None or m["name"] not in VR.names(rid):
        return False
    n, pred = VR.nodes[rid], VR.succ(rid, -1)
    if kingdom and X.backend().engine.KNAME[n["kingdom"]] != m["kd"]:
        return False
    fathers = {n["father"]} | (set(VR.names(pred)) if pred and VR.edge_type.get((pred, rid)) == "son" else set())
    return m["f"] is None or m["f"] in fathers


def _ref_sync(VR, rid: str) -> tuple[str, int] | None:
    return next(((o, y) for (n, o, y, _v, p) in VR.syncs if n == rid and p), None)


def _span(VR, x: str, y: str) -> list[str] | None:
    kd = VR.nodes[x]["kingdom"]
    if VR.nodes[y]["kingdom"] != kd or VR.idx(x) is None or VR.idx(y) is None or VR.idx(y) <= VR.idx(x):
        return None
    return VR.chain[kd][VR.idx(x):VR.idx(y) + 1]


def _chk_sum(VR, ids, m, tag) -> list[str]:
    seg = _span(VR, *ids)
    if seg is None or not (_is(VR, ids[0], m["x"]) and _is(VR, ids[1], m["y"])):
        return ["the kings are not the seeds, in chain order"]
    reigns = [VR.nodes[z]["reign"] for z in seg]
    if not all(_whole(r) for r in reigns):
        return ["a part-year reign in the interval"]
    return ([f"count {m['n']} != {len(seg)}"] if int(m["n"]) != len(seg) else []) + \
           ([f"sum {m['v']} != {int(sum(reigns))}"] if int(m["v"]) != sum(reigns) else [])


def _chk_handover(VR, ids, m, tag) -> list[str]:
    seg = _span(VR, *ids)
    if seg is None or not (_is(VR, ids[0], m["x"]) and _is(VR, ids[1], m["y"])):
        return ["the kings are not the seeds, in chain order"]
    return [f"hand-overs {m['v']} != {len(seg) - 1}"] if int(m["v"]) != len(seg) - 1 else []


def _chk_father_age(VR, ids, m, tag) -> list[str]:
    x, y = ids
    seg, named = _span(VR, x, y), _is(VR, x, m["x"]) and _is(VR, y, m["y"])
    if seg is None or len(seg) != 2 or VR.edge_type.get((x, y)) != "son" or not named:
        return ["not an adjacent father and son"]
    a, r, b = VR.nodes[x]["age"], VR.nodes[x]["reign"], VR.nodes[y]["age"]
    if None in (a, r, b):
        return ["an age or reign is missing in the reference"]
    got = tuple(int(m[g]) for g in ("a", "r", "b", "v"))
    out = [] if got == (a, r, b, a + r - b) else [f"{got} != {(a, r, b, a + r - b)}"]
    return out + ([] if 0 < got[3] <= a + r else [f"age {got[3]} outside 0..{a + r}"])


def _chk_succ(VR, ids, m, tag) -> list[str]:
    x, k = ids[0], int(m["k"])
    y = VR.succ(x, k)
    if k != tag["k"] or not _is(VR, x, m["x"]) or m["kd"] != X.backend().engine.KNAME[VR.nodes[x]["kingdom"]]:
        return ["the seed, k or kingdom is not the tag's"]
    if y is None or not _is(VR, y, m["y"], kingdom=False):
        return [f"successor {k} is not {m['y']}"]
    sync = _ref_sync(VR, y)
    if sync is None:
        return [] if m["z"] is None else ["a synchronism the reference does not have"]
    if m["z"] is None:
        return ["the primary synchronism is missing"]
    ok = (_is(VR, y, m["y2"], False) and _is(VR, y, m["y3"], False) and _is(VR, sync[0], m["z"], False)
          and _is(VR, sync[0], m["z2"], False) and int(m["n"]) == sync[1])
    return [] if ok else [f"synchronism is not {VR.nodes[sync[0]]['name']} year {sync[1]}"]


DYN_CHECKS = {"sum": _chk_sum, "handover": _chk_handover, "father_age": _chk_father_age, "succ": _chk_succ}


def _expected_dyn(VR, rs: list[str]) -> Counter:
    """(kind, ref seeds, k) of every line the seeds call for, from the reference layer."""
    want: Counter = Counter()
    if len(rs) == 2 and (seg := _span(VR, *sorted(rs, key=VR.idx))):
        x, y = seg[0], seg[-1]
        want[("handover", (x, y), None)] += 1
        if all(_whole(VR.nodes[z]["reign"]) for z in seg):
            want[("sum", (x, y), None)] += 1
        ages = (VR.nodes[x]["age"], VR.nodes[y]["age"])
        if len(seg) == 2 and VR.edge_type.get((x, y)) == "son" and None not in ages:
            want[("father_age", (x, y), None)] += 1
    for s in rs:
        for k in SUCC_K:
            if VR.succ(s, k) is None:
                break
            want[("succ", (s,), k)] += 1
    return want


def _complete(want: Counter, have: Counter, dropped: int, droppable: str) -> list[str]:
    out = [f"line not called for by the seeds: {key[0]} {key[1]}" for key in have - want]
    miss = want - have
    out += [f"missing line: {key[0]} {key[1]}" for key in miss if key[0] != droppable]
    n_succ = sum(v for key, v in miss.items() if key[0] == droppable)
    return out + ([f"{n_succ} {droppable} lines missing, {dropped} dropped"] if n_succ != dropped else [])


def _check_dyn(item: dict, c: dict, VR, V4) -> list[str]:
    rs = [ref_id(V4, VR, s) for s in item["seeds"]]
    if None in rs:
        return [f"seeds {item['seeds']} are not on the reference chains"]
    sr = item.get("seeds_ref")
    out = [] if not sr or rs == list(sr) else [f"seeds_ref {sr} != {rs}"]
    have: Counter = Counter()
    for i, ((h, p), tag) in enumerate(zip(c["lines"], c["tags"])):
        ids = [ref_id(V4, VR, s) for s in tag["seeds"]]
        m = DYN_RE[tag["kind"]].fullmatch(line_text(h, p)) if tag["kind"] in DYN_RE else None
        if m is None or None in ids:
            out.append(f"line {i}: not a {tag['kind']} line of the seeds")
            continue
        out += [f"line {i} ({tag['kind']}): {e}" for e in DYN_CHECKS[tag["kind"]](VR, ids, m, tag)]
        have[(tag["kind"], tuple(ids), tag["k"])] += 1
    return out + _complete(_expected_dyn(VR, rs), have, c["dropped_lines"], "succ")


# ---------------------------------------------------------------- Genesis lines, recomputed in years

GEN_RE = {
    "born_age": re.compile(r"(?P<y>.+?)出生時(?P<x>.+?)的年齡：(?P<v>[0-9]+)歲"),
    "total": re.compile(r"(?P<x>.+?)的總壽數：(?P<v>[0-9]+)歲"),
    "taken": re.compile(r"(?P<x>.+?)在(?P<v>[0-9]+)歲時被取去"),
    "death_age": re.compile(r"(?P<x>.+?)去世時(?P<y>.+?)的年齡：(?P<v>[0-9]+)歲"),
    "died_first": re.compile(r"(?P<y>.+?)在(?P<x>.+?)去世前(?P<v>[0-9]+)年(?P<verb>已去世|已被取去)"),
    "died_before_birth": re.compile(r"(?P<x>.+?)在(?P<y>.+?)出生前(?P<v>[0-9]+)年去世"),
    "flood": re.compile(r"(?P<x>.+?)在洪水之後(?P<v>[0-9]+)年出生"),
}
AGE_CLAIMS = (re.compile(r"^(?P<who>[^：；]+)：(?P<v>[0-9]+)歲生"),            # row: X：N歲生Y
              re.compile(r"^(?P<who>[^：；]+)：.*共活(?P<v>[0-9]+)歲"),         # row: …；共活T歲
              re.compile(r"時(?P<who>[^時：；]+?)的年齡：(?P<v>[0-9]+)歲$"),
              re.compile(r"^(?P<who>.+?)的總壽數：(?P<v>[0-9]+)歲$"),
              re.compile(r"^(?P<who>.+?)在(?P<v>[0-9]+)歲時被取去$"))


def gen_facts(gen: dict) -> tuple[dict, list[str]]:
    """({id: (name, chapter, born, lifespan)}, problems): born counts years from the chapter's first row,
    in chapter 11 from the flood (through the anchor's offset); lifespans as stated, else beget + remain."""
    nodes, facts, out = _nodes(gen), {}, []
    for ch in sorted({n["chapter"] for n in nodes.values()}):
        chain, born, acc = gen_chain(gen, ch), {}, 0
        for x in chain:
            born[x], b = acc, _f(nodes[x], "beget")
            acc = None if acc is None or b is None else acc + b
        a = gen_anchor(gen, ch)
        if a is not None and chain.index(a) + 1 < len(chain) and born[chain[chain.index(a) + 1]] is not None:
            shift = nodes[a]["flood_offset"][0] - born[chain[chain.index(a) + 1]]
            born = {x: None if v is None else v + shift for x, v in born.items()}
        for x in chain:
            b, r, t = (_f(nodes[x], f) for f in ("beget", "remain", "total"))
            life = t if t is not None else (b + r if None not in (b, r) else None)
            d = gen.get("derived", {}).get("total", {}).get(x)
            if d is not None and d != life:
                out.append(f"derived lifespan of {x} {d} != {life}")
            facts[x] = (nodes[x]["name"], ch, born[x], life)
    return facts, out


def _gen_expect(gen: dict, facts: dict, xs: list[str]) -> Counter:
    """(kind, seeds) of every line the seeds call for, from the recomputed years."""
    nodes, want = _nodes(gen), Counter()
    if len(xs) == 2 and None not in (facts[xs[0]][2], facts[xs[1]][2]):
        (x, y), (_n, _c, bx, tx), (_m, _d, by, ty) = xs, facts[xs[0]], facts[xs[1]]
        if tx is None or by - bx <= tx:
            want[("born_age", (x, y))] += 1
        if tx is not None:
            want[("total", (x,))] += 1
            m = bx + tx - by
            kind = ("taken" if taken(nodes[x]) else "died_before_birth" if m <= 0 else None if ty is None
                    else "death_age" if m < ty else "died_first")
            if kind:
                want[(kind, (x,) if kind == "taken" else (x, y))] += 1
    for x in xs:
        a = gen_anchor(gen, facts[x][1])
        chain = gen_chain(gen, facts[x][1])
        if a is not None and chain.index(x) > chain.index(a):
            want[("flood", (x,))] += 1
    return want


def _gen_value(gen: dict, facts: dict, kind: str, ids: list[str], m) -> int | None:
    """The line's value recomputed from the years (None: the line does not hold for these seeds)."""
    nodes, (x, *rest) = _nodes(gen), ids
    _n, _c, bx, tx = facts[x]
    if kind == "total":
        return tx
    if kind == "taken":
        return tx if taken(nodes[x]) else None
    if kind == "flood":
        a, chain = gen_anchor(gen, facts[x][1]), gen_chain(gen, facts[x][1])
        return bx if a is not None and chain.index(x) > chain.index(a) else None
    by, ty = facts[rest[0]][2], facts[rest[0]][3]
    if kind == "born_age":
        return by - bx
    mm = bx + tx - by
    if kind == "death_age":
        return mm if 0 < mm < ty else None
    if kind == "died_before_birth":
        return -mm if mm <= 0 else None
    want_verb = "已被取去" if taken(nodes[rest[0]]) else "已去世"
    return mm - ty if mm >= ty and m["verb"] == want_verb else None


def _gen_line_problems(gen: dict, facts: dict, i: int, text: str, tag: dict) -> list[str]:
    m = GEN_RE[tag["kind"]].fullmatch(text) if tag["kind"] in GEN_RE else None
    ids = tag["seeds"]
    if m is None or any(x not in facts for x in ids):
        return [f"line {i}: not a {tag['kind']} line of the seeds"]
    names = {g: facts[ids[0] if g == "x" else ids[-1]][0] for g in ("x", "y") if g in m.groupdict()}
    if any(m[g] != nm for g, nm in names.items()) or (len(ids) == 2 and facts[ids[0]][1] != facts[ids[1]][1]):
        return [f"line {i} ({tag['kind']}): the names are not the seeds'"]
    try:
        want = _gen_value(gen, facts, tag["kind"], ids, m)
    except TypeError:
        want = None
    return [] if want is not None and int(m["v"]) == want else [f"line {i} ({tag['kind']}): {m['v']} != {want}"]


def _age_claims(block: str, facts: dict) -> list[str]:
    """Every 「someone N歲」 in the block (rows and lines) is at most that person's lifespan."""
    life = {nm: t for nm, _c, _b, t in facts.values()}
    out = []
    for text in block.split("\n"):
        for pat in AGE_CLAIMS:
            for m in pat.finditer(text):
                who, v = m["who"], int(m["v"])
                if who not in life:
                    out.append(f"age claim of an unknown person: {who}")
                elif life[who] is not None and v > life[who]:
                    out.append(f"{who} {v} 歲 over the lifespan {life[who]}")
    return out


BEGET_ROW = re.compile(r"(?P<x>[^：；]+)：(?P<b>[0-9]+)歲生(?P<s>[^；]+)")


def _row_son(gen: dict, x: str) -> str:
    """The son a row names (prereg §4 「X：N歲生Y」): the next row of the chapter when the layer links them,
    else the first son the layer lists, else 「子」."""
    nodes = _nodes(gen)
    chain = gen_chain(gen, nodes[x]["chapter"])
    nxt = chain[chain.index(x) + 1] if chain.index(x) + 1 < len(chain) else None
    if nxt is not None and [x, nxt] in [e[:2] for e in gen.get("edges", [])]:
        return nodes[nxt]["name"]
    return (nodes[x].get("sons") or ["子"])[0]


def _row_problems(gen: dict, c: dict) -> list[str]:
    """Every kept row's begetting field: the layer's age and one son (_row_son); none when the layer has none."""
    nodes, out = _nodes(gen), []
    for y, text in zip(c["rows"], c["t_block"].split("\n") if c["t_block"] else []):
        if y not in nodes:
            out.append(f"row {y}: not a layer row")
            continue
        b, m = _f(nodes[y], "beget"), BEGET_ROW.match(text)
        if b is None:
            out += [f"row {y}: a begetting the layer does not have"] if m else []
        elif m is None or (m["x"], int(m["b"]), m["s"]) != (nodes[y]["name"], b, _row_son(gen, y)):
            out.append(f"row {y}: the begetting field is not the layer's age and chain son")
    return out


def _check_gen(item: dict, c: dict, gen: dict) -> list[str]:
    facts, out = gen_facts(gen)
    have: Counter = Counter()
    for i, ((h, p), tag) in enumerate(zip(c["lines"], c["tags"])):
        out += _gen_line_problems(gen, facts, i, line_text(h, p), tag)
        have[(tag["kind"], tuple(tag["seeds"]))] += 1
    try:
        xs = gen_window(gen, item["seeds"])[0]
    except ValueError as e:
        return out + [str(e)]
    want = _gen_expect(gen, facts, xs)
    out += [f"line not called for by the seeds: {k}" for k in have - want]
    out += [f"missing line: {k}" for k in want - have]
    return out + _row_problems(gen, c) + _age_claims(c["g_block"], facts)
