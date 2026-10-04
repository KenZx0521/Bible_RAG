"""S1: whitespace names, same-type / any-type twins, id collisions after strip.

Inputs (read-only): output/entities.jsonl (JSONL, pre-10.x),
output/frozen/live_state/20261004/entities.jsonl (live export, 9,124),
output/ner_entities.jsonl (current NER half), output/frozen/grounded_entities.jsonl.
"""
import sys, json, unicodedata
from collections import Counter, defaultdict
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from ro import OUT, jsonl, dump
from pypinyin import lazy_pinyin

TYPES = ("Person", "Place", "Group", "Event", "Object", "Theme")


def norm(s: str) -> str:
    # plan's normalize_surface: strip + remove inner ASCII/full-width spaces + zero-width + NFC
    s = unicodedata.normalize("NFC", s or "")
    for ch in (" ", "　", "​", "‌", "‍", "﻿", "\t", "\n"):
        s = s.replace(ch, "")
    return s


def mint(typ: str, name: str) -> str:
    return f"{typ.lower()}:{''.join(lazy_pinyin(name))}"


def load(path, live=False):
    out = {}
    for r in jsonl(path):
        t = r["labels"][1] if live and r["labels"][0] == "Entity" else (r["labels"][0] if live else r["type"])
        if live:
            t = [l for l in r["labels"] if l != "Entity"][0]
        out[r["entity_id"]] = {"type": t, "name": r["canonical_name"], "aliases": r.get("aliases") or [],
                               "method": r.get("extraction_method"), "mc": r.get("mention_count")}
    return out


def analyse(ents, label):
    by_key = defaultdict(list)          # (type, norm name) -> ids
    by_name = defaultdict(list)         # norm name -> ids (any type)
    for eid, e in ents.items():
        by_key[(e["type"], norm(e["name"]))].append(eid)
        by_name[norm(e["name"])].append(eid)
    padded = {eid for eid, e in ents.items() if e["name"] != e["name"].strip()}
    inner = {eid for eid, e in ents.items() if e["name"].strip() != norm(e["name"]) and eid not in padded}
    ws_id = {eid for eid in ents if any(c.isspace() for c in eid)}
    dirty = padded | inner | ws_id
    res = {"label": label, "entities": len(ents), "padded_names": len(padded),
           "inner_space_names": len(inner), "ids_with_space": len(ws_id), "dirty_total": len(dirty),
           "dirty_by_type": dict(Counter(ents[e]["type"] for e in dirty))}
    same, cross, none_, collide = [], [], [], []
    for eid in sorted(dirty):
        e = ents[eid]
        twins = [t for t in by_key[(e["type"], norm(e["name"]))] if t != eid and t not in dirty]
        anyt = [t for t in by_name[norm(e["name"])] if t != eid and t not in dirty]
        if twins:
            same.append((eid, twins[0]))
        elif anyt:
            cross.append((eid, anyt))
        else:
            none_.append(eid)
        if not twins:
            new = mint(e["type"], norm(e["name"]))
            if new in ents and new not in dirty and norm(ents[new]["name"]) != norm(e["name"]):
                collide.append((eid, new, ents[new]["name"]))
    res.update({
        "same_type_twin": len(same), "same_type_twin_by_type": dict(Counter(ents[a]["type"] for a, _ in same)),
        "any_type_twin": len(same) + len(cross),
        "cross_type_only": len(cross), "cross_type_only_by_type": dict(Counter(ents[a]["type"] for a, _ in cross)),
        "no_twin": len(none_), "no_twin_by_type": dict(Counter(ents[a]["type"] for a in none_)),
        "rename_id_collides_with_other_name": len(collide),
        "twin_id_equals_minted": sum(1 for a, b in same if b == mint(ents[a]["type"], norm(ents[a]["name"]))),
    })
    # several dirty ids mapping to the same clean key (dirty-dirty twins)
    dd = Counter((ents[e]["type"], norm(ents[e]["name"])) for e in dirty)
    res["dirty_groups_with_2plus"] = sum(1 for v in dd.values() if v > 1)
    return res, {"same": same, "cross": cross, "none": none_, "collide": collide}


if __name__ == "__main__":
    out = {}
    live = load(OUT / "frozen/live_state/20261004/entities.jsonl", live=True)
    js = load(OUT / "entities.jsonl")
    ner = load(OUT / "ner_entities.jsonl")
    grd = load(OUT / "frozen/grounded_entities.jsonl")
    for lab, ents in (("live", live), ("jsonl", js), ("ner_half", ner), ("grounded_half", grd)):
        r, lists = analyse(ents, lab)
        out[lab] = r
        out[lab + "_lists"] = {k: v[:400] for k, v in lists.items()}
        print(json.dumps(r, ensure_ascii=False))
    # which half do the dirty ids come from (jsonl)
    r, lists = analyse(js, "jsonl")
    src = Counter(("ner" if e in ner else "grounded" if e in grd else "?") for e, *_ in
                  [(x[0],) for x in lists["same"]] + [(x[0],) for x in lists["cross"]] + [(x,) for x in lists["none"]])
    print("jsonl dirty by half:", dict(src))
    out["jsonl_dirty_by_half"] = dict(src)
    dump("s1_whitespace.json", out)
