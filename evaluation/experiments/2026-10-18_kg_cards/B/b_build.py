"""Item records for B: question, frozen key, prod-format context (R5 units), gold chain and its
layout in the edge table (twin_struct.py contiguous rule). Records hold TIPNR-derived fields and
go to store B/ only."""
from __future__ import annotations

import collections
import random

import b_card as Cd
import b_gold as Gd
import b_items as I
import b_lib as L
from b_lib import cc

N_GOLD_CHECK = 20


def gold_edge_candidates(g: dict, ids: list[str], sig: list[str]) -> list[list[tuple]]:
    """Per gold hop, the surface keys (head, rel, tail) that would state it in the edge table."""
    out = []
    for x, y, rel in zip(ids, ids[1:], sig):
        sx, sy = Gd.surfaces(g, x), Gd.surfaces(g, y)
        if rel in ("U", "Um"):
            keys = [(h, "PARENT_OF", t) for h in sy for t in sx]
        elif rel in ("D", "Dm"):
            keys = [(h, "PARENT_OF", t) for h in sx for t in sy]
        else:
            keys = [k for h in sx for t in sy for k in ((h, "SPOUSE_OF", t), (t, "SPOUSE_OF", h))]
        out.append(keys)
    return out


def layout(rows: list[tuple], cands: list[list[tuple]]) -> dict:
    """twin_struct.py classes on the gold chain: contiguous / monotone / scattered / unlocated."""
    E = {}
    for i, (k, _) in enumerate(rows):
        E.setdefault(k, i)
    pos = [next((E[k] for k in keys if k in E), None) for keys in cands]
    if any(p is None for p in pos):
        cls = "unlocated"
    elif sorted(pos) == list(range(min(pos), min(pos) + len(pos))):
        cls = "contiguous"
    elif pos == sorted(pos) or pos == sorted(pos, reverse=True):
        cls = "monotone"
    else:
        cls = "scattered"
    return dict(cls=cls, pos=pos, dispersed=cls in ("monotone", "scattered"))


def context_names(verses: list[str]) -> set[str]:
    """Every name the context verses carry: label surfaces (any category) and MH triple ends."""
    lab, tb = L.labels(True), L.triples_by_unit()
    names = {c for u in verses for c in lab.get(u, {})}
    return names | {t[k] for u in verses for t in tb.get(u, []) for k in ("head", "tail")}


def with_superstrings(key: dict, names: set[str]) -> dict:
    """LIN keys: names that contain an accept or trap name (甲乙 in 甲乙丙) become neutral, so the
    longest-first matcher consumes them before the shorter key name can hit."""
    if key["kind"] != "name":
        return key
    keyed = set(key["accept"]) | set(key["trap"])
    extra = sorted(n for n in names if n not in keyed and n not in key["neutral"] and any(k in n for k in keyed))
    return dict(key, neutral=list(key["neutral"]) + extra) if extra else key


def record(r: dict, key: dict, iid: str, stratum: str, source: str = "dev", base_uid: str | None = None) -> dict:
    g = Gd.gold_graph(r["pericope"])
    units = list(r["R5"]["units"])
    verses = L.verses_of_units(units)
    sources = [L.source(u) for u in units]
    rows = Cd.edge_rows(verses, L.triples_by_unit())
    key = with_superstrings(key, context_names(verses))
    return dict(id=iid, source=source, stratum=stratum, type=r["type"], pericope=r["pericope"],
                question=key["question"], key=key, sig=list(r["sig"]), ids=list(r["ids"]),
                surfaces=list(r["surfaces"]), hop_verses=Gd.hop_verses(g, r["ids"]),
                a_gender=Gd.gender(r["ids"][0]), units=units, verses=verses,
                context=cc.build_context(sources), n_edges=len(rows),
                layout=layout(rows, gold_edge_candidates(g, r["ids"], r["sig"])),
                replaced=base_uid is not None and base_uid != I.item_uid(r))


def base_draw() -> tuple[list, list[str], dict]:
    """Dev pericopes -> draw on the v0 pool -> run order (one rng, seed 20261018, in this order):
    the K0-checked base 48 (store v0_k0checked/items.json)."""
    rng = random.Random(L.SEED)
    dev, pmeta = I.dev_pericopes(rng)
    picks, dmeta = I.draw(I.base_candidates(dev), rng, set())
    perm = rng.sample(range(len(picks)), len(picks))
    ordered = [picks[j] for j in sorted(range(len(picks)), key=lambda j: perm[j])]
    return ordered, dev, dict(dev_pericopes=dev, **pmeta, **dmeta)


def build(excluded: set) -> tuple[list[dict], dict]:
    """Base 48, then each slot failing the fixed gold (I.check_item) or listed in excluded is
    replaced (I.replace); the other slots keep their item and id."""
    ordered, dev, meta = base_draw()
    checked, bad = [], {}
    for i, (s, r, _) in enumerate(ordered):
        key, why = I.check_item(r, Gd.gold_graph(r["pericope"]))
        why = "+".join(x for x in (why, "gold_exclusions" if I.item_uid(r) in excluded else "") if x)
        if why:
            bad[i] = why
        checked.append((s, r, key))
    pool, base_pool = I.candidates(dev), I.base_candidates(dev)
    final, log = I.replace(checked, pool, bad, excluded)
    base_uids = [I.item_uid(r) for _, r, _ in ordered]
    items = [record(r, key, f"b{n:02d}", s, base_uid=base_uids[n - 1]) for n, (s, r, key) in enumerate(final, 1)]
    meta.update(n_items=len(items), excluded=sorted(excluded), base_uids=base_uids, replacements=log,
                per_pericope_final=dict(sorted(collections.Counter(it["pericope"] for it in items).items())),
                per_stratum_final={s: sum(it["stratum"] == s for it in items) for s in I.BASE_QUOTA},
                pool_sizes={s: [len(base_pool.get(s, [])), len(pool.get(s, []))] for s in I.BASE_QUOTA})
    return items, meta


def gold_check_ids(items: list[dict]) -> list[str]:
    return sorted(random.Random(L.SEED).sample(sorted(it["id"] for it in items), N_GOLD_CHECK))


def supplement_rows(dev: list[str]):
    """K0 card supplement: items of the frame's other item pericopes, shuffled with seed 20261018."""
    devs, fr = set(dev), L.frame()
    rows = [r for r in L.items_eval() if r["pericope"] in fr and r["pericope"] not in devs
            and r["type"] in I.TYPES]
    rows.sort(key=lambda r: (r["pericope"], r["type"], r["surfaces"], r["ids"]))
    random.Random(L.SEED).shuffle(rows)
    for r in rows:
        key, _ = I.check_item(r, Gd.gold_graph(r["pericope"]))
        if key is not None:
            yield r, key
