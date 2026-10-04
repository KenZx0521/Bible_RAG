"""S2: junk E/O/T, stoplist/place-name Events, Event∩dict-P/P/G names; protection check.

Proposed rule set for compile_entities (all on normalize_surface(name)):
  _is_junk_title: starts with （ ( ＊ * (but '(無標題)' is not junk), contains a
  digit [0-9０-９], ends with 。，！？；」：, or len < 2. allow: 這是基督嗎？
  stoplist Event: GENERIC_EVENT_STOPLIST (24) + EV-09 (瑪拉 瑪撒 米利巴 耶和華曉諭 曉諭摩西)
  dict gate (plan 1D gate): Event whose normalized name is a P/P/G dict canonical or alias.
Counts are reported on JSONL (output/entities.jsonl) and on the live export.
"""
import sys, re, json
from collections import Counter, defaultdict
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
sys.path.insert(0, "/home/kenzx0521/Bible_RAG")
from ro import OUT, ROOT, jsonl, dump, neo4j, read
from s1_whitespace import norm, load
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS

EV09_EXTRA = ["瑪拉", "瑪撒", "米利巴", "耶和華曉諭", "曉諭摩西"]
JUNK_ALLOW = {"這是基督嗎？"}
_XREF = re.compile(r"^[（(＊*]")
_DIGIT = re.compile(r"[0-9０-９]")
_FRAG_END = re.compile(r"[。，！？；」：]$")


def is_junk_title(name: str) -> str | None:
    n = norm(name)
    if n in JUNK_ALLOW or n == "(無標題)":
        return None
    if len(n) < 2:
        return "too_short"
    if _XREF.search(n):
        return "xref_remnant"
    if _DIGIT.search(n):
        return "digit"
    if _FRAG_END.search(n):
        return "fragment_end"
    return None


def dict_names():
    out = {}
    for typ, d in (("Person", PERSON_DICT), ("Place", PLACE_DICT), ("Group", GROUP_DICT)):
        for k, v in d.items():
            for n in set(v) | {k}:
                out.setdefault(n, set()).add(typ)
    return out


def protected_ids():
    reg = json.load(open(ROOT / "backend/data/event_registry.json"))
    ids = {e["id"] for e in reg["events"]} | {d["id"] for d in reg.get("dropped", [])}
    ids |= set(ALIAS_INJECTIONS) | {e["entity_id"] for e in NEW_EVENTS}
    for r in jsonl(ROOT / "config/curated/manual_graph_patches.jsonl"):
        if r.get("kind") in ("node", "edge") and r.get("entity_id"):
            ids.add(r["entity_id"])
    for r in jsonl(OUT / "frozen/live_state/20261004/curated_mentions.jsonl"):
        ids.add(r["entity_id"])
    ids |= {"place:dan", "group:yehehua"}
    return ids, {e["id"] for e in reg["events"]}


def classify(ents, dn):
    stop = set(GENERIC_EVENT_STOPLIST) | set(EV09_EXTRA)
    res = {}
    for eid, e in ents.items():
        if e["type"] not in ("Event", "Object", "Theme"):
            continue
        j = is_junk_title(e["name"])
        n = norm(e["name"])
        if j:
            res[eid] = ("junk:" + j, e["type"], e["name"])
        elif e["type"] == "Event" and n in set(GENERIC_EVENT_STOPLIST):
            res[eid] = ("stop:generic24", e["type"], e["name"])
        elif e["type"] == "Event" and n in set(EV09_EXTRA):
            res[eid] = ("stop:ev09", e["type"], e["name"])
        elif e["type"] == "Event" and n in dn:
            res[eid] = ("dictname:" + "/".join(sorted(dn[n])), e["type"], e["name"])
    return res


if __name__ == "__main__":
    dn = dict_names()
    prot, reg_ids = protected_ids()
    out = {"protected_ids": len(prot), "registry_ids": len(reg_ids)}
    live = load(OUT / "frozen/live_state/20261004/entities.jsonl", live=True)
    js = load(OUT / "entities.jsonl")
    titles = {r["title"] for r in jsonl(OUT / "pericopes.jsonl")}
    # mentions per entity (JSONL) and relations.jsonl endpoints
    mc = Counter(m["entity_id"] for m in jsonl(OUT / "entity_mentions.jsonl"))
    rel = Counter()
    for r in jsonl(OUT / "relations.jsonl"):
        rel[r["head_id"]] += 1; rel[r["tail_id"]] += 1
    for lab, ents in (("live", live), ("jsonl", js)):
        c = classify(ents, dn)
        by = Counter((v[0].split(":")[0] + ":" + (v[0].split(":")[1] if v[0].startswith("junk") else v[0].split(":")[1]), v[1]) for v in c.values())
        out[lab] = {
            "by_rule_type": {f"{k[0]}|{k[1]}": n for k, n in sorted(by.items())},
            "junk_by_type": dict(Counter(v[1] for v in c.values() if v[0].startswith("junk"))),
            "stop_events": sum(1 for v in c.values() if v[0].startswith("stop")),
            "dictname_events": sum(1 for v in c.values() if v[0].startswith("dictname")),
            "protected_hit": sorted(e for e in c if e in prot),
            "registry_hit": sorted(e for e in c if e in reg_ids),
            "list": {e: v for e, v in sorted(c.items())},
        }
        if lab == "jsonl":
            out[lab]["mentions_jsonl"] = {k: sum(mc[e] for e, v in c.items() if v[0].startswith(k)) for k in ("junk", "stop", "dictname")}
            out[lab]["relations_jsonl_edges"] = {k: sum(rel[e] for e, v in c.items() if v[0].startswith(k)) for k in ("junk", "stop", "dictname")}
            out[lab]["dictname_title_derived"] = sum(1 for e, v in c.items() if v[0].startswith("dictname") and norm(v[2]) in titles)
        print(lab, json.dumps({k: v for k, v in out[lab].items() if k != "list"}, ensure_ascii=False))
    # live MENTIONS / relation counts for the live candidate set
    cands = sorted(out["live"]["list"])
    drv = neo4j("prod")
    rows = read(drv, """
      UNWIND $ids AS eid MATCH (e:Entity {entity_id: eid})
      OPTIONAL MATCH (e)-[r]-()
      RETURN eid, sum(CASE WHEN type(r)='MENTIONS' THEN 1 ELSE 0 END) AS men,
             sum(CASE WHEN r IS NOT NULL AND type(r)<>'MENTIONS' THEN 1 ELSE 0 END) AS rels,
             sum(CASE WHEN r IS NOT NULL AND type(r)<>'MENTIONS' AND r.extraction_phase=5 AND r.notes STARTS WITH 'cooccurrence' THEN 1 ELSE 0 END) AS cooc
    """, ids=cands)
    drv.close()
    agg = defaultdict(Counter)
    for r in rows:
        k = out["live"]["list"][r["eid"]][0].split(":")[0]
        t = out["live"]["list"][r["eid"]][1]
        agg[f"{k}|{t}"]["n"] += 1; agg[f"{k}|{t}"]["mentions"] += r["men"]; agg[f"{k}|{t}"]["rels"] += r["rels"]
    out["live_edges"] = {k: dict(v) for k, v in agg.items()}
    print("live edges:", json.dumps(out["live_edges"], ensure_ascii=False))
    dump("s2_junk_stop.json", out)
