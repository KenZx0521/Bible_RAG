"""K0 material of experiment A (prereg §2 K0-1, gold check) for a second checker, store only.

k0_fields_sample.json: 40 fields drawn with random.Random(20261018) from the G-auto layer as the
arms show it (kingdom, father, reign, age, mother, alias, primary synchronism, succession edge);
each carries its provenance verse id and that verse's text. k0_gold_check.json: every item's
keys, gold, basis verses and their text. Verse text is written to the store only.
"""
from __future__ import annotations

import random

from a_common import ITEMS, LAYER_AUTO, LAYER_REF, OUT, SEED, cc, read_json, verse_text
from items_a import new82_rows
from regnal import load_auto, load_ref

SHOWN = ("father", "reign", "age", "mother")
N_FIELDS = 40


def alias_verses(layer: dict) -> dict:
    out = {}
    for rec in layer["log"]:
        if rec[0] == "rename":
            out[(rec[5], rec[2])] = rec[1]
        elif rec[0] == "fn_alias" and rec[2] == "又名" and rec[5]:
            out[(rec[5], rec[4])] = rec[1].split(":")[1].split("#")[0]
    return out


def population(layer: dict, V) -> list[dict]:
    av, pop = alias_verses(layer), []
    for n in layer["nodes"]:
        x = n["id"]
        if x not in V.nodes:
            continue
        pop.append(dict(kind="kingdom", node=x, name=n["name"], value=n["kingdom"], verse=n["evidence"][0]))
        for f in SHOWN:
            if f in n["fields"]:
                val, verse, _src = n["fields"][f]
                pop.append(dict(kind=f, node=x, name=n["name"], value=val, verse=verse))
        for a in dict.fromkeys(n["aliases"]):
            if a != n["name"]:
                pop.append(dict(kind="alias", node=x, name=n["name"], value=a, verse=av.get((x, a))))
    for (x, o, y, v, p) in V.syncs:
        if p:
            pop.append(dict(kind="sync", node=x, name=V.nodes[x]["name"], value=[V.nodes[o]["name"], y], verse=v))
    for e in layer["edges"] + layer["fallback_edges"]:
        if e[0] in V.nodes and e[1] in V.nodes:
            pop.append(dict(kind="edge", node=e[1], name=V.nodes[e[1]]["name"],
                            value=[V.nodes[e[0]]["name"], e[2]], verse=e[3], pred=e[0]))
    return pop


def with_text(f: dict, V) -> dict:
    out = dict(f, verse_text=verse_text(f["verse"]) if f["verse"] else None)
    if f["kind"] == "edge" and not f["verse"]:
        out["note"] = "order_fallback edge: no provenance verse; check adjacency against both kings' first evidence"
        out["evidence"] = {z: [V.nodes[z]["evidence"][0], verse_text(V.nodes[z]["evidence"][0])] for z in (f["pred"], f["node"])}
    return out


def fields_sample() -> dict:
    layer, V = read_json(LAYER_AUTO), load_auto(LAYER_AUTO)
    pop = sorted(population(layer, V), key=lambda f: (f["kind"], f["node"], str(f["value"])))
    pick = random.Random(SEED).sample(pop, N_FIELDS)
    return {"seed": SEED, "population": len(pop), "by_kind": {k: sum(f["kind"] == k for f in pop) for k in
            dict.fromkeys(f["kind"] for f in pop)}, "threshold": "precision ≥ 0.95 (prereg §2 K0-1)",
            "fields": [dict(with_text(f, V), check=None) for f in pick]}


def original_points() -> dict:
    """Original answer (OLD31 usable.json) or key_points (NEW82 questions_v5.json) of each natural item."""
    new = {k: v["key_points"] for k, v in new82_rows().items()}
    import _gd_sets  # on sys.path once new82_rows ran
    old = {q["id"]: q["answer"] for q in read_json(_gd_sets.OLD31_FILE)}
    return {**new, **old}


def gold_check() -> dict:
    VR, items = load_ref(LAYER_REF), read_json(ITEMS)["items"]
    orig = original_points()
    rows = []
    for it in items:
        keys = [dict(k, basis_text={v: verse_text(v) for v in k["basis"]}) for k in it["keys"]]
        rows.append(dict(id=it["id"], kind=it["kind"], question=it["question"], gold=[VR.names(x) for x in it["gold"]],
                         seeds=[VR.names(x) for x in it["seeds"]], path=[VR.nodes[z]["name"] for z in it.get("path") or []],
                         keys=keys, flags=it.get("flags", []), note=it.get("note"),
                         original_answer_or_key_points=orig.get(it["id"]) if it["kind"] == "natural" else None,
                         check=None))
    return {"n": len(rows), "instruction": "check each key against the basis verses; record check=ok|wrong with a note",
            "items": rows}


def main() -> None:
    cc.write_json(OUT / "k0_fields_sample.json", fields_sample())
    cc.write_json(OUT / "k0_gold_check.json", gold_check())
    print("wrote", OUT / "k0_fields_sample.json", OUT / "k0_gold_check.json")


if __name__ == "__main__":
    main()
