"""Offline prototype of compile_entities (K1c) + compile-time curated overlay (Kc) + replay (K7).

Pure JSONL in, in-memory graph out. Two modes:
  fixes=False: reproduce the batch-0 chain (Step 5 -> 10.1 -> 10.2 -> 10.4 -> 10.5 -> 7 replay)
               so it can be compared with staging Neo4j (equivalence).
  fixes=True : the 1D compile (normalize, twin merge, junk/stoplist/dict-name drops,
               overrides, compiled aliases + ambiguity filter, id_migration).
No database access here.
"""
from __future__ import annotations

import json, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
sys.path.insert(0, "/home/kenzx0521/Bible_RAG")
from ro import OUT, ROOT, jsonl
from s1_whitespace import norm, mint
from s2_junk_stop import is_junk_title, dict_names, EV09_EXTRA
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
from backfill_aliases import build_rows
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST, compute_dan_keep_sources
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS
import backfill_manual_patches as bmp
from scripts.relation_extraction import desc_generator as dg

DICTS = {"Person": PERSON_DICT, "Place": PLACE_DICT, "Group": GROUP_DICT}


def load_titles():
    per, ch = {}, {}
    for r in jsonl(OUT / "neo4j_nodes.jsonl"):
        p = r["properties"]
        if "Pericope" in r["labels"]:
            per[p["id"]] = p.get("title")
        elif "Chunk" in r["labels"]:
            ch[p["id"]] = p.get("pericope_title")
    return per, ch


def base_graph():
    nodes = {}
    for r in jsonl(OUT / "entities.jsonl"):
        nodes[r["entity_id"]] = {"type": r["type"], "canonical_name": r.get("canonical_name", ""),
                                 "aliases": list(r.get("aliases") or []),
                                 "description": r.get("description", ""),
                                 "mention_count": r.get("mention_count", 0),
                                 "extraction_method": r.get("extraction_method"),
                                 "origin": "extracted"}
    rows = []   # occurrence rows (label, sid, eid, text_span)
    for m in jsonl(OUT / "entity_mentions.jsonl"):
        st, sid = m.get("source_type", ""), m["source_id"]
        if st == "verse" or ":v:" in sid:
            sid, lab = sid.split(":v:")[0], "Pericope"
        elif st == "chunk":
            lab = "Chunk"
        else:
            lab = "Pericope"
        rows.append((lab, sid, m["entity_id"], m.get("text_span", "")))
    return nodes, rows


def edges_of(rows):
    out = {}
    for lab, sid, eid, span in rows:
        out.setdefault((lab, sid, eid), {})
    return out


# ---------------------------------------------------------------- overlays (chain semantics)

def ov_10_1(nodes, scope_types=None):
    """backfill_aliases: dict aliases by label (before 10.2 relabels yehehua)."""
    for label, d in DICTS.items():
        names = {n["canonical_name"] for n in nodes.values() if n["type"] == label}
        rows, _ = build_rows(label, d, names)
        for row in rows:
            for n in nodes.values():
                if n["type"] == label and n["canonical_name"] == row["match_name"]:
                    n["aliases"] = bmp.merge_aliases(n["aliases"], row["aliases"], n["canonical_name"])


def ov_10_2(nodes, edges, dan=True, generic=True, yehehua=True):
    if dan:
        keep = compute_dan_keep_sources(OUT / "entity_mentions.jsonl")
        for k in [k for k in edges if k[2] == "place:dan" and k[1] not in keep]:
            del edges[k]
        nodes["place:dan"]["mention_count"] = sum(1 for k in edges if k[2] == "place:dan")
    if generic:
        gone = {e for e, n in nodes.items() if n["type"] == "Event" and n["canonical_name"] in set(GENERIC_EVENT_STOPLIST)}
        for e in gone:
            del nodes[e]
        for k in [k for k in edges if k[2] in gone]:
            del edges[k]
    if yehehua and "group:yehehua" in nodes:
        nodes["group:yehehua"]["type"] = "Person"


def ov_10_4(nodes, edges):
    for eid, al in ALIAS_INJECTIONS.items():
        n = nodes[eid]
        n["aliases"] = bmp.merge_aliases(n["aliases"], al, n["canonical_name"])
    for ev in NEW_EVENTS:
        n = nodes.setdefault(ev["entity_id"], {"type": "Event", "origin": "head_event_backfill"})
        n.update({"type": "Event", "canonical_name": ev["canonical_name"], "aliases": list(ev["aliases"]),
                  "description": ev["description"], "mention_count": len(ev["anchors"]),
                  "extraction_method": "curated", "source": "head_event_backfill"})
        for pid in ev["anchors"]:
            edges.setdefault(("Pericope", pid, ev["entity_id"]), {"curated": True, "source": "head_event_backfill"})


def ov_10_5(nodes, edges):
    pnodes, pedges = bmp.load_patches(bmp.DEFAULT_PATCH_FILE)
    flat = {e: {**n, "canonical_name": n["canonical_name"], "aliases": n["aliases"]} for e, n in nodes.items()}
    over = bmp.overlay_nodes(flat, pnodes)
    for pn in pnodes:
        eid = pn["entity_id"]
        if eid not in nodes:
            p = over[eid]
            nodes[eid] = {"type": next(l for l in pn["labels"] if l != "Entity"),
                          "canonical_name": p["canonical_name"], "aliases": p["aliases"],
                          "description": p.get("description", ""), "mention_count": p.get("mention_count", 0),
                          "extraction_method": "curated", "origin": "manual", "source": "manual_patch"}
        else:
            nodes[eid]["aliases"] = over[eid]["aliases"]
    for e in pedges:
        if e["entity_id"] in nodes:
            edges.setdefault(("Pericope", e["pericope_id"], e["entity_id"]), {"curated": True, "source": "manual_patch"})


def titles_for(edges, per, ch):
    t = defaultdict(set)
    for lab, sid, eid in edges:
        title = per.get(sid) if lab == "Pericope" else ch.get(sid)
        if title:
            t[eid].add(title)
    return {e: sorted(v)[:6] for e, v in t.items()}


def replay(nodes, edges, per, ch, cache_path=OUT / "frozen/descriptions.jsonl"):
    cache = dg.load_cache(cache_path)
    titles = titles_for(edges, per, ch)
    rep = {"written": [], "unchanged": [], "stale": [], "missing": []}
    for eid in sorted(cache):
        n = nodes.get(eid)
        if n is None:
            rep["missing"].append(eid); continue
        entry = cache[eid].get(dg.titles_sha(titles.get(eid, [])))
        if entry is None:
            rep["stale"].append(eid); continue
        if (n.get("description") or "") == entry["description"]:
            rep["unchanged"].append(eid)
        else:
            n["description"] = entry["description"]; rep["written"].append(eid)
    return rep, titles


def chain(fixes=None):
    """fixes=None -> batch-0 chain projection."""
    nodes, rows = base_graph()
    edges = edges_of(rows)
    ov_10_1(nodes)
    ov_10_2(nodes, edges)
    ov_10_4(nodes, edges)
    ov_10_5(nodes, edges)
    per, ch = load_titles()
    rep, titles = replay(nodes, edges, per, ch)
    return nodes, edges, rep, titles


# ---------------------------------------------------------------- 1D compile (fixes on)

def protected():
    reg = json.load(open(ROOT / "backend/data/event_registry.json"))
    ids = {e["id"] for e in reg["events"]} | {d["id"] for d in reg.get("dropped", [])}
    ids |= set(ALIAS_INJECTIONS) | {e["entity_id"] for e in NEW_EVENTS}
    for r in jsonl(ROOT / "config/curated/manual_graph_patches.jsonl"):
        if r.get("entity_id"):
            ids.add(r["entity_id"])
    ids |= {"place:dan", "group:yehehua"}
    return ids


def curated_alias_pairs():
    """(entity_id, alias) written by 10.4/10.5 — registry triggers live here."""
    pairs = set()
    for eid, al in ALIAS_INJECTIONS.items():
        pairs |= {(eid, a) for a in al}
    for ev in NEW_EVENTS:
        pairs |= {(ev["entity_id"], a) for a in ev["aliases"]}
    for r in jsonl(ROOT / "config/curated/manual_graph_patches.jsonl"):
        if r.get("kind") == "node":
            pairs |= {(r["entity_id"], a) for a in r["props"].get("aliases") or []}
    return pairs


def dict_alias_owners():
    own = defaultdict(set)
    for t, d in DICTS.items():
        for k, v in d.items():
            for a in set(v) | {k}:
                own[a].add((t, k))
    return own


def compile_1d(id_policy="keep", dictname_scope=("Event", "Object", "Theme"), alias_type="extraction",
               ambiguity=True):
    prot = protected()
    nodes, rows = base_graph()
    mig = []                      # id_migration rows
    dn = dict_names()
    stats = Counter()
    # 1. normalize names
    for eid, n in nodes.items():
        n["raw_name"] = n["canonical_name"]
        n["extraction_type"] = n["type"]
        nn = norm(n["canonical_name"])
        if nn != n["canonical_name"]:
            stats["normalized_names"] += 1
            n["canonical_name"] = nn
    # 2. twin merge / rename
    groups = defaultdict(list)
    for eid, n in nodes.items():
        groups[(n["type"], n["canonical_name"])].append(eid)
    remap = {}
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        clean = [i for i in ids if not any(c.isspace() for c in i) and nodes[i]["raw_name"] == nodes[i]["canonical_name"]]
        if len(clean) != 1:
            stats["ambiguous_twin_groups"] += 1
            continue
        surv = clean[0]
        for i in ids:
            if i == surv:
                continue
            remap[i] = surv
            mig.append({"old_id": i, "new_id": surv, "op": "merge", "rule": "normalized_twin", "type": key[0]})
    for i, s in remap.items():
        a, b = nodes[s], nodes.pop(i)
        a["mention_count"] = (a.get("mention_count") or 0) + (b.get("mention_count") or 0)
        a["aliases"] = bmp.merge_aliases(a["aliases"], b["aliases"], a["canonical_name"])
    if id_policy == "rename":
        taken = set(nodes)
        for eid in sorted(e for e in nodes if any(c.isspace() for c in e)):
            n = nodes[eid]
            new = mint(n["type"], n["canonical_name"])
            if new in taken:
                new = f"{n['type'].lower()}:{n['canonical_name']}"
                stats["rename_collision_han_id"] += 1
            remap[eid] = new; taken.add(new)
            nodes[new] = nodes.pop(eid)
            mig.append({"old_id": eid, "new_id": new, "op": "rename", "rule": "normalized_id", "type": n["type"]})
    rows = [(l, s, remap.get(e, e), sp) for l, s, e, sp in rows]
    # 3. rule drops on E/O/T
    drop = {}
    for eid, n in nodes.items():
        if n["type"] not in ("Event", "Object", "Theme") or eid in prot:
            continue
        j = is_junk_title(n["canonical_name"])
        if j:
            drop[eid] = "junk:" + j
        elif n["type"] == "Event" and n["canonical_name"] in set(GENERIC_EVENT_STOPLIST):
            drop[eid] = "stop:generic24"
        elif n["type"] == "Event" and n["canonical_name"] in set(EV09_EXTRA):
            drop[eid] = "stop:ev09"
        elif n["type"] in dictname_scope and n["canonical_name"] in dn:
            drop[eid] = "dictname"
    # protected that WOULD have been hit
    stats["protected_would_hit"] = sum(1 for eid in prot if eid in nodes and nodes[eid]["type"] in ("Event", "Object", "Theme")
                                       and (is_junk_title(nodes[eid]["canonical_name"]) or nodes[eid]["canonical_name"] in dn))
    for eid, rule in sorted(drop.items()):
        mig.append({"old_id": eid, "new_id": None, "op": "drop", "rule": rule, "type": nodes[eid]["type"]})
        del nodes[eid]
    rows = [r for r in rows if r[2] not in drop]
    edges = edges_of(rows)
    # 4. Kc overlay (moved from 10.x) — aliases from dict (10.1 logic) by extraction type
    if alias_type == "extraction":
        for label, d in DICTS.items():
            names = {n["canonical_name"] for n in nodes.values() if n["extraction_type"] == label}
            rws, _ = build_rows(label, d, names)
            for row in rws:
                for n in nodes.values():
                    if n["extraction_type"] == label and n["canonical_name"] == row["match_name"]:
                        n["aliases"] = bmp.merge_aliases(n["aliases"], row["aliases"], n["canonical_name"])
    ov_10_2(nodes, edges, dan=True, generic=False, yehehua=True)   # yehehua == entity_overrides.yaml
    ov_10_4(nodes, edges)
    ov_10_5(nodes, edges)
    # 5. ambiguity filter (curated aliases exempt)
    cur = curated_alias_pairs()
    downer = dict_alias_owners()
    if ambiguity:
        owners, canon = defaultdict(set), defaultdict(set)
        for e, n in nodes.items():
            canon[n["canonical_name"]].add(e)
            for a in n["aliases"]:
                owners[a].add(e)
        for e, n in nodes.items():
            keep, amb = [], []
            for a in n["aliases"]:
                if (e, a) in cur:
                    keep.append(a); continue
                if len(owners[a]) > 1 or (canon.get(a, set()) - {e}) or len(downer.get(a, ())) > 1:
                    amb.append(a)
                else:
                    keep.append(a)
            if amb:
                n["ambiguous_aliases"] = amb
                n["aliases"] = keep
    return nodes, edges, rows, mig, drop, stats
