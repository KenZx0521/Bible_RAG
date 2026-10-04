"""Batch-1C offline simulation: quantify the MENTIONS / entity / description /
relation changes of the 1C NER fix against the staging rebuild (== live).

Inputs (read-only): output/*.jsonl, output/frozen/descriptions.jsonl,
graph_staging.json (READ dump of staging), rows_*.jsonl / ents_*.jsonl (ner_sim.py).
Usage: python analyze.py [ctx|pos]   -> prints report, writes result_<geo>.json
"""
import json, sys, collections
sys.path.insert(0, ".")
from edgelib import *
from ner_sim_geo import is_geo_context
TAG = sys.argv[1] if len(sys.argv) > 1 else "ctx"   # suffix of rows_1c_<TAG>.jsonl
GEO = TAG
C = collections.Counter
out = {}

texts = load_texts(); books = load_books(); titles = load_titles()
chunk_parent = {json.loads(l)["id"]: json.loads(l)["parent_id"] for l in open(f"{ROOT}/chunks.jsonl")}
g = json.load(open("graph_staging.json"))
stg_types = {e["eid"]: e["el"] for e in g["entities"]}
stg_mc = {e["eid"]: e["mc"] for e in g["entities"]}
stg_name = {e["eid"]: e["name"] for e in g["entities"]}

def read(p): return [json.loads(l) for l in open(p)]
old_ents = {d["entity_id"]: d for d in map(json.loads, open(f"{ROOT}/entities.jsonl"))}
old_rows = [r for r in read(f"{ROOT}/entity_mentions.jsonl") if old_ents[r["entity_id"]]["type"] in PPG]
cur_rows = read("rows_current.jsonl"); new_rows = read(f"rows_1c_{GEO}.jsonl")
cur_ents = {d["entity_id"]: d for d in read("ents_current.jsonl")}
new_ents = {d["entity_id"]: d for d in read(f"ents_1c_{GEO}.jsonl")}

# ---- A. harness validation: rows_current == output/ner_mentions.jsonl (content multiset)
key = lambda d: (d["entity_id"], d["source_id"], d["source_type"], d["text_span"], d.get("start_pos"), d.get("end_pos"))
base = C(key(d) for d in read(f"{ROOT}/ner_mentions.jsonl")); sim = C(key(d) for d in cur_rows)
out["A_harness"] = {"ner_mentions_rows": sum(base.values()), "replay_rows": sum(sim.values()),
                    "only_file": sum((base - sim).values()), "only_replay": sum((sim - base).values())}

# ---- B. edge sets
def dan10_2(rows, E):
    keep = {r["source_id"].split(":v:")[0] for r in rows if r["entity_id"] == "place:dan"
            and is_geo_context(r.get("context", ""))}
    return OrderedDict((k, v) for k, v in E.items() if not (k[2] == "place:dan" and k[1] not in keep))
from collections import OrderedDict
E_stg = {(m["sl"], m["sid"], m["eid"]): m for m in g["mentions"] if m["el"] in PPG and not m["curated"]}
# context is needed for 10.2 on the current-dict half; recompute it like NERExtractor._get_context
def ctx_of(r):
    t = texts[r["source_id"]]["text"]; s, e = r["start_pos"], r["end_pos"]
    a, b = max(0, s - 30), min(len(t), e + 30)
    return ("..." if a > 0 else "") + t[a:b] + ("..." if b < len(t) else "")
for r in cur_rows:
    if r["entity_id"] == "place:dan": r["context"] = ctx_of(r)
E_cur = dan10_2(cur_rows, edges_first_wins(cur_rows))
E_new = edges_first_wins(new_rows)
out["B_edges"] = {"staging_ppg_ner": len(E_stg), "current_dict_plus_10_2": len(E_cur), "batch1c": len(E_new)}

def diff(a, b):
    return {"removed": len(set(a) - set(b)), "added": len(set(b) - set(a)), "kept": len(set(a) & set(b))}
out["B_drift_staging_to_current"] = diff(E_stg, E_cur)
drift_ents = C(k[2] for k in set(E_stg) ^ set(E_cur))
out["B_drift_entities"] = dict(drift_ents.most_common(10))
out["B_1c_current_to_new"] = diff(E_cur, E_new)
out["B_total_staging_to_new"] = diff(E_stg, E_new)

# ---- C. classify current edges missing in 1C
reg = lambda r: ("book" if r["start_pos"] < texts[r["source_id"]]["title_start"] else
                 "title" if r["start_pos"] < texts[r["source_id"]]["body_start"] else "body")
rows_by_edge = collections.defaultdict(list)
for r in cur_rows: rows_by_edge[edge_key(r)].append(r)
new_by_edge = collections.defaultdict(list)
for r in new_rows: new_by_edge[edge_key(r)].append(r)
ABBR = set(json.load(open("abbrev.json")))
cls_removed = C(); samples = collections.defaultdict(list)
for k in set(E_cur) - set(E_new):
    rs = rows_by_edge[k]; regs = {reg(r) for r in rs}
    ent = cur_ents[k[2]]; name = ent["canonical_name"]
    if name != name.strip():
        c = "whitespace_id_renamed" if (k[0], k[1], None) else ""
        tw = [e for e in new_ents.values() if e["canonical_name"] == name.strip() and e["type"] == ent["type"]]
        c = "whitespace_id->twin_edge_exists" if tw and (k[0], k[1], tw[0]["entity_id"]) in E_new else "whitespace_id->no_edge"
    elif name.strip() in ABBR:
        c = "book_abbreviation"
    elif regs == {"book"}:
        c = "book_region_only"
    elif "book" in regs:
        c = "book_region+ckip_context"
    else:
        c = "ckip_context_change"
    cls_removed[c] += 1
    if len(samples[c]) < 8: samples[c].append(f"{k[1]}->{k[2]}({name}) regs={sorted(regs)}")
out["C_removed_by_reason"] = dict(cls_removed)
out["C_removed_samples"] = dict(samples)
cls_added = C(); samples_a = collections.defaultdict(list)
cur_ids_by_name = collections.defaultdict(set)
for e in cur_ents.values(): cur_ids_by_name[(e["canonical_name"].strip(), e["type"])].add(e["entity_id"])
for k in set(E_new) - set(E_cur):
    ent = new_ents[k[2]]
    olds = cur_ids_by_name[(ent["canonical_name"], ent["type"])] - {k[2]}
    if olds and any((k[0], k[1], o) in E_cur for o in olds):
        c = "moved_from_whitespace_twin"
    elif k[2] == "place:dan":
        c = "dan_rule_difference"
    else:
        c = "ckip_context_change"
    cls_added[c] += 1
    if len(samples_a[c]) < 8: samples_a[c].append(f"{k[1]}->{k[2]}({ent['canonical_name']}) regs={sorted({r['source_region'] for r in new_by_edge[k]})}")
out["C_added_by_reason"] = dict(cls_added)
out["C_added_samples"] = dict(samples_a)

# ---- D. R1 (first position in book name) and relocation
def r1(E):
    return sum(1 for k, r in E.items() if r.get("start_pos") is not None and
               r.get("sp", r.get("start_pos")) < len(books[k[1].split(":")[0]]))
def r1_stg(E):
    return sum(1 for k, m in E.items() if m["sp"] is not None and m["sp"] < len(books[k[1].split(":")[0]]))
out["D_R1"] = {"staging": r1_stg(E_stg), "current_dict": r1(E_cur), "batch1c_absolute_pos": r1(E_new)}
# body-relative coordinates would make R1 count body positions < len(book)
out["D_R1_if_body_relative"] = sum(1 for k, r in E_new.items()
                                   if r["start_pos"] - texts[r["source_id"]]["body_start"] < len(books[k[1].split(":")[0]])
                                   and r["start_pos"] >= texts[r["source_id"]]["body_start"])
reloc = C()
for k in set(E_cur) & set(E_new):
    a = reg(E_cur[k]); b = E_new[k]["source_region"]
    if a == "book": reloc[f"book->{b}"] += 1
out["D_relocated_first_row"] = dict(reloc)
# edge-level region (aggregated): title-only edges
agg = C()
for k, rs in new_by_edge.items():
    agg["body" if any(r["source_region"] == "body" for r in rs) else "title_only"] += 1
out["D_edge_region_aggregated"] = dict(agg)
# first-row region would mislabel edges that have both
mixed_first_title = sum(1 for k, rs in new_by_edge.items()
                        if rs[0]["source_region"] == "title" and any(r["source_region"] == "body" for r in rs))
out["D_edges_first_row_title_but_body_exists"] = mixed_first_title
by_gran = C()
for k, rs in new_by_edge.items():
    if k[0] == "Pericope":
        kinds = {("verse" if ":v:" in r["source_id"] else "pericope") for r in rs}
        by_gran["+".join(sorted(kinds))] += 1
out["D_pericope_edges_by_row_granularity"] = dict(by_gran)

# ---- E. R9 / H4 on rows
def r9(rows, text_of):
    seen = C((r["source_id"], r["entity_id"], r["start_pos"]) for r in rows)
    mism = sum(1 for r in rows if text_of(r)[r["start_pos"]:r["end_pos"]] != r["text_span"])
    return {"duplicate_positions": sum(n - 1 for n in seen.values()), "span_mismatch": mism}
tx = lambda r: texts[r["source_id"]]["text"]
out["E_R9"] = {"current": r9(cur_rows, tx), "batch1c": r9(new_rows, tx), "live_ner_half": r9(old_rows, tx)}
ws = lambda E: sum(1 for e in E.values() if e["type"] in PPG and e["canonical_name"] != e["canonical_name"].strip())
out["E_H4_ppg_whitespace_names"] = {"staging": sum(1 for e in g["entities"] if e["el"] in PPG and e["name"] != e["name"].strip()),
                                    "current": ws(cur_ents), "batch1c": ws(new_ents)}

# ---- F. entities
stg_ppg = {e for e, t in stg_types.items() if t in PPG}
new_ppg = set(new_ents)
gone = stg_ppg - new_ppg; born = new_ppg - stg_ppg
def why_gone(eid):
    n = stg_name[eid]
    if n != n.strip(): return "whitespace_name"
    if n.strip() in ABBR: return "book_abbreviation"
    if eid not in cur_ents: return "dictionary_drift(流珥)"
    rs = [r for r in cur_rows if r["entity_id"] == eid]
    if rs and all(reg(r) == "book" for r in rs): return "book_region_only"
    if eid == "person:yeteluo": return "?"
    return "ckip_context_change"
cur_rows_by_ent = collections.defaultdict(list)
for r in cur_rows: cur_rows_by_ent[r["entity_id"]].append(r)
def why_gone_fast(eid):
    n = stg_name[eid]
    if n != n.strip(): return "whitespace_name"
    if n.strip() in ABBR: return "book_abbreviation"
    if eid not in cur_ents: return "dictionary_drift"
    rs = cur_rows_by_ent[eid]
    if rs and all(reg(r) == "book" for r in rs): return "book_region_only"
    return "ckip_context_change"
gone_cls = collections.defaultdict(list)
for eid in sorted(gone): gone_cls[why_gone_fast(eid)].append(f"{eid}({stg_name[eid]},mc={stg_mc[eid]})")
out["F_entities"] = {"staging_ppg": len(stg_ppg), "batch1c_ppg": len(new_ppg), "gone": len(gone), "new": len(born)}
out["F_gone_by_reason"] = {k: {"n": len(v), "ids": v[:40]} for k, v in gone_cls.items()}
out["F_new_ids"] = [f"{e}({new_ents[e]['canonical_name']},mc={new_ents[e]['mention_count']})" for e in sorted(born)][:60]
# mention_count deltas (node property = occurrence rows)
deltas = []
for eid in stg_ppg & new_ppg:
    a, b = stg_mc[eid] or 0, new_ents[eid]["mention_count"]
    if a != b: deltas.append((b - a, eid, stg_name[eid], a, b))
deltas.sort()
out["F_mc_changed_entities"] = len(deltas)
out["F_mc_top_decrease"] = [f"{n}({e}) {a}->{b}" for d, e, n, a, b in deltas[:25]]
out["F_mc_top_increase"] = [f"{n}({e}) {a}->{b}" for d, e, n, a, b in deltas[-12:][::-1]]
edge_cnt = lambda E, eid: sum(1 for k in E if k[2] == eid)
probe = {}
for eid in ("person:make", "person:mataí", "person:matai", "person:lujia", "place:aiji", "person:yuehan", "place:dan",
            "person:yeteluo", "person:danyili", "person:yisaiya", "person:mixia", "person:shimu"):
    if eid in stg_types or eid in new_ents:
        probe[eid] = {"edges_staging": edge_cnt(E_stg, eid), "edges_1c": edge_cnt(E_new, eid),
                      "mc_staging": stg_mc.get(eid), "mc_1c": new_ents.get(eid, {}).get("mention_count")}
out["F_probes"] = probe
# entities affected = any edge or mc change
aff = {k[2] for k in set(E_stg) ^ set(E_new)} | {d[1] for d in deltas} | gone | born
out["F_entities_affected"] = len(aff)
book_named = [f"{e}({n})" for e, n in ((e, new_ents[e]["canonical_name"]) for e in new_ents)
              if any(n == b or n == b.rstrip("記書") or (len(n) >= 2 and b.startswith(n) and n in ("民數", "雅歌", "列王", "歷代", "使徒", "福音")) for b in books.values())]
out["F_book_named_entities_after"] = book_named

# ---- G. Event MENTIONS untouched
ev = [(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if m["el"] == "Event"]
out["G_event_mentions"] = {"staging": len(ev), "touched_by_1c": sum(1 for k in set(E_stg) ^ set(E_new) if stg_types.get(k[2]) == "Event" or new_ents.get(k[2], {}).get("type") == "Event")}

# ---- H. descriptions: titles before/after
other = [(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if not (m["el"] in PPG and not m["curated"])]
T_before = titles_of(other + list(E_stg), titles)
T_after = titles_of(other + list(E_new), titles)
cache = collections.defaultdict(dict)
for l in open(f"{ROOT}/frozen/descriptions.jsonl"):
    d = json.loads(l); cache[d["entity_id"]][d["titles_sha"]] = d
after_ids = (set(stg_types) - stg_ppg) | new_ppg
stale, missing, ok = [], [], 0
for eid, shas in cache.items():
    if eid not in after_ids: missing.append(eid); continue
    if titles_sha(T_after.get(eid, [])) in shas: ok += 1
    else: stale.append(eid)
assert all(titles_sha(T_before.get(e, [])) in s for e, s in cache.items())
st_types = C(stg_types.get(e) for e in stale); mi_types = C(stg_types.get(e) for e in missing)
out["H_desc"] = {"cached": len(cache), "replayable": ok, "stale": len(stale), "missing": len(missing),
                 "stale_by_type": dict(st_types), "missing_by_type": dict(mi_types)}
out["H_stale_samples"] = [f"{e}({stg_name[e]})" for e in stale[:30]]
out["H_missing"] = [f"{e}({stg_name[e]})" for e in missing]
json.dump({"stale": stale, "missing": missing}, open(f"expected_stale_{GEO}.json", "w"), ensure_ascii=False, indent=1)

# ---- I. relations.jsonl
rels = read(f"{ROOT}/relations.jsonl")
ids_after = after_ids
ws_map = {}
for e in stg_ppg:
    n = stg_name[e]
    if n != n.strip():
        tw = [x for x in new_ents.values() if x["canonical_name"] == n.strip() and x["type"] == stg_types[e]]
        if tw: ws_map[e] = tw[0]["entity_id"]
dangling = [r for r in rels if r["head_id"] not in ids_after or r["tail_id"] not in ids_after]
remap_ok = [r for r in dangling if ws_map.get(r["head_id"], r["head_id"]) in ids_after and ws_map.get(r["tail_id"], r["tail_id"]) in ids_after]
out["I_relations"] = {"total": len(rels), "endpoint_vanishes": len(dangling),
                      "fixable_by_whitespace_id_migration": len(remap_ok),
                      "by_phase": dict(C(r["extraction_phase"] for r in dangling)),
                      "samples": [f"{r['head_id']}-{r['relation']}->{r['tail_id']}" for r in dangling if r not in remap_ok][:12]}
def support(E_ppg):
    s = set()
    for (lab, sid, eid) in list(E_ppg) + other:
        s.add((chunk_parent.get(sid, sid) if lab == "Chunk" else sid, eid))
    return s
S0, S1 = support(E_stg), support(E_new)
def supported(r, S):
    pid = r.get("source_pericope_id")
    h = ws_map.get(r["head_id"], r["head_id"]); t = ws_map.get(r["tail_id"], r["tail_id"])
    return (pid, h) in S and (pid, t) in S
gated = [r for r in rels if r.get("source_pericope_id") and r["extraction_phase"] != 3]
lost = [r for r in gated if supported(r, S0) and not supported(r, S1)]
gain = [r for r in gated if not supported(r, S0) and supported(r, S1)]
out["I_provenance_support"] = {"with_source_pericope": len(gated), "supported_before": sum(supported(r, S0) for r in gated),
                               "supported_after": sum(supported(r, S1) for r in gated), "lost": len(lost), "gained": len(gain),
                               "lost_by_phase": dict(C(r["extraction_phase"] for r in lost)),
                               "lost_samples": [f"{r['head_canonical']}-{r['relation']}->{r['tail_canonical']}@{r['source_pericope_id']}" for r in lost[:12]]}

# ---- J. PG entity_mentions rows (occurrence rows) and dan
out["J_rows"] = {"live_ner_rows": len(old_rows), "current_rows": len(cur_rows), "batch1c_rows": len(new_rows),
                 "batch1c_title_rows": sum(r["source_region"] == "title" for r in new_rows)}
out["J_dan"] = {"staging_edges": edge_cnt(E_stg, "place:dan"), "batch1c_edges": edge_cnt(E_new, "place:dan"),
                "same_set": {k for k in E_stg if k[2] == "place:dan"} == {k for k in E_new if k[2] == "place:dan"},
                "rows_1c": sum(r["entity_id"] == "place:dan" for r in new_rows)}
json.dump(out, open(f"result_{GEO}.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
