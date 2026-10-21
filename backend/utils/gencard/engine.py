"""Stage-0's Genesis card engine, copied verbatim (prereg §5.1): the card text is byte-equal by construction.

Source: evaluation/experiments/2026-10-20_arith_stage0/engine_x.py (committed in 2cf514c, never edited).
Copied unchanged, in the source's order: the constants TAKEN_ID, DEFAULT_CLASSES and Line, and the functions
line_text, render, _line, _nodes, _f, gen_chain, gen_anchor, taken, gen_lifespan, son_name, gen_row,
_death_line, gen_pair_lines, gen_flood_line, gen_window, gen_parts, fit and covered. DERIVED_HEADER is
experiment A's (evaluation/experiments/2026-10-18_kg_cards/A/engine.py, the backend engine's header too),
CAP_CHARS stage-0's x_common.CAP_CHARS (900). Nothing else of engine_x (the dynasty functions, card,
check_*) is here: ``card.py`` builds the Genesis card with these functions exactly as engine_x.card's
Genesis branch does. ``test_gen_confirm_gencard`` compares every copied source segment with engine_x's
and the card text with engine_x.card on all 64 same-chapter pairs. Standard library only.
"""
from __future__ import annotations

from typing import Any

DERIVED_HEADER = "依上列資料推算："      # A/engine.py DERIVED_HEADER, unchanged
CAP_CHARS = 900                          # stage-0 x_common.CAP_CHARS
TAKEN_ID = "G05.06"                 # SPEC id of the one taken at gen.5.24 (no death, no 「已去世」)
DEFAULT_CLASSES = ("Y", "A")        # an arithmetic key without classes: years or ages
Line = dict[str, Any]


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
