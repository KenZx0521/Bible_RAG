"""The chronology card's engine: experiment A's engine.py (arm G-auto), verbatim but its imports.

From the resolved seeds only (never the question type) the engine reads the chain rows of
seed ±3 and the rows walked back by born_under, and writes derivation lines: k-th successor
(k=±1..±3), n-th usurper after the seed (within +3), king at the seed's birth, and the reigns
between two same-kingdom seeds. No contemporaries, no king_at_other_year. Rows and lines share
one ≤900-char budget; rows farthest from the seeds go first. A card with no derivation line is
no card (the caller answers without one).
"""
from __future__ import annotations

from ragcommon.regnal import KINGDOM_NAMES as KNAME
from ragcommon.regnal import acc_sync, born_under, fmt_reign

CAP_CHARS = 900
EDGE_LABEL = {"son": "子繼父", "brother": "兄弟繼位", "usurp": "篡位", "queen_usurp": "篡位",
              "installed": "被立為王", "restored": "被立為王", "people": "百姓立為王", "seat": "接續王位",
              "order_fallback": "不詳"}
DERIVED_HEADER = "依上列資料推算："
FAILED = ("UNKNOWN_REIGN", "BEFORE_CHAIN")


def homonym(V, x) -> bool:
    n = V.nodes[x]
    return any(y != x and m["kingdom"] == n["kingdom"] and n["name"] in V.names(y) for y, m in V.nodes.items())


def desc(V, x) -> str:
    n = V.nodes[x]
    s = f"{KNAME.get(n['kingdom'], '?')}王{n['name']}"
    return s + (f"（{n['father']}的兒子）" if n["father"] and homonym(V, x) else "")


def attrs(V, y) -> str:
    n = V.nodes[y]
    parts = ([f"父{n['father']}"] if n["father"] else []) + \
            ([f"在位{fmt_reign(n['reign'])}"] if n["reign"] is not None else []) + \
            ([f"登基{n['age']}歲"] if n["age"] is not None else [])
    return f"（{'，'.join(parts)}）" if parts else ""


def row_text(V, x) -> str:
    n = V.nodes[x]
    head = desc(V, x)
    others = V.names(x)[1:]
    if others:
        head += f"（又稱{'、'.join(others)}）"
    parts = ([f"父{n['father']}"] if n["father"] else []) + \
            ([f"在位{fmt_reign(n['reign'])}"] if n["reign"] is not None else []) + \
            ([f"登基{n['age']}歲"] if n["age"] is not None else []) + \
            ([f"母{n['mother']}"] if n["mother"] else [])
    pred = V.succ(x, -1)
    if pred:
        parts.append(f"繼位：{EDGE_LABEL.get(V.edge_type.get((pred, x)), '不詳')}")
    for o, y, _v in acc_sync(V, x):
        parts.append(f"於{desc(V, o)}第{y}年登基")
    return head + "：" + "；".join(parts)


def derive(V, seeds: list[str]) -> tuple[list[str], list[tuple[str, str]], list[list]]:
    """(rows read, in read order; derivation lines as (head, payload); line tags [rel, seed, k])."""
    read, lines, tags = [], [], []

    def touch(y):
        if y is not None and y not in read:
            read.append(y)
    for x in seeds:
        touch(x)
    for x in seeds:
        kd = KNAME[V.nodes[x]["kingdom"]]
        for k in (-3, -2, -1, 1, 2, 3):
            y = V.succ(x, k)
            if y is None:
                continue
            for j in range(1, abs(k) + 1):
                touch(V.succ(x, j if k > 0 else -j))
            lines.append((f"{desc(V, x)}之{'後' if k > 0 else '前'}第{abs(k)}位{kd}王", V.nodes[y]["name"] + attrs(V, y)))
            tags.append(["succ", x, k])
        cnt = 0
        for k in range(1, 4):
            a, b = V.succ(x, k - 1), V.succ(x, k)
            if b is None:
                break
            if V.edge_type.get((a, b)) == "usurp":
                cnt += 1
                lines.append((f"{desc(V, x)}之後第{cnt}個篡位者", V.nodes[b]["name"] + attrs(V, b)))
                tags.append(["usurper", x, cnt])
        bu, walked = born_under(V, x)
        for y in walked:
            touch(y)
        if bu and bu[0] not in FAILED:
            lines.append((f"{desc(V, x)}出生時在位的{kd}王（依登基{V.nodes[x]['age']}歲往回累加前任在位年數）",
                          V.nodes[bu[0]]["name"]))
            tags.append(["born", x, None])
    if len(seeds) >= 2:
        a, b = seeds[0], seeds[1]
        if V.nodes[a]["kingdom"] == V.nodes[b]["kingdom"] and V.idx(a) is not None and V.idx(b) is not None:
            lines.append((f"{desc(V, a)}到{desc(V, b)}相隔", f"{abs(V.idx(b) - V.idx(a))}代王位"))
            tags.append(["gap", a, b])
    return read, lines, tags


def chain_order(V, rows: list[str], seeds: list[str]) -> list[str]:
    kd_rank = {}
    for x in seeds + rows:
        kd_rank.setdefault(V.nodes[x]["kingdom"], len(kd_rank))
    return sorted(rows, key=lambda y: (kd_rank[V.nodes[y]["kingdom"]], V.idx(y) if V.idx(y) is not None else 999))


def distance(V, y, seeds) -> float:
    ds = [abs(V.idx(y) - V.idx(s)) for s in seeds
          if V.nodes[s]["kingdom"] == V.nodes[y]["kingdom"] and V.idx(y) is not None and V.idx(s) is not None]
    return min(ds) if ds else float("inf")


def render(V, rows: list[str], lines: list[tuple[str, str]]) -> str:
    out = [row_text(V, y) for y in rows]
    if lines:
        out += [DERIVED_HEADER] + [f"{h}：{p}" for h, p in lines]
    return "\n".join(out)


def fit(V, rows, lines, seeds, cap=CAP_CHARS):
    """Drop the row farthest from the seeds (ties: later row) until rows + lines fit the cap."""
    rows, lines, dropped = list(rows), list(lines), []
    while len(render(V, rows, lines)) > cap and len(rows) > len(seeds):
        far = max(range(len(rows)), key=lambda i: (distance(V, rows[i], seeds) if rows[i] not in seeds else -1, i))
        dropped.append(rows.pop(far))
    while len(render(V, rows, lines)) > cap and lines:
        lines.pop()
    return rows, lines, dropped


def cards(V, seeds: list[str]) -> dict:
    """G (rows + lines) and T-rows (same kept rows) blocks for one layer; G None = abstain."""
    read, lines, tags = derive(V, seeds)
    rows = chain_order(V, read, seeds)
    g_rows, g_lines, dropped = fit(V, rows, lines, seeds)
    t_rows = g_rows if lines else fit(V, rows, [], seeds)[0]
    return {"rows": t_rows, "rows_read": rows, "rows_dropped": dropped, "lines": g_lines,
            "g_block": render(V, g_rows, g_lines) if g_lines else None,
            "t_block": render(V, t_rows, []) if t_rows else "",
            "payloads": [p for _h, p in g_lines], "tags": tags[:len(g_lines)]}


def resolve(V, kd: str | None, name: str, question: str) -> str | None:
    """Seed (kingdom, name) -> node id; same-kingdom homonyms are split only by the question's
    「F的兒子name」 or 「name（F的兒子）」."""
    cands = [x for x, n in V.nodes.items()
             if n["kingdom"] in V.chain and (kd is None or n["kingdom"] == kd) and name in V.names(x)]
    if len(cands) > 1:
        named = [x for x in cands if V.nodes[x]["father"] and (
            f"{V.nodes[x]['father']}的兒子{name}" in question or f"{name}（{V.nodes[x]['father']}的兒子）" in question)]
        if not named and f"{name}（" in question:
            named = [x for x in cands if not V.nodes[x]["father"]]
        cands = named
    return cands[0] if len(cands) == 1 else None
