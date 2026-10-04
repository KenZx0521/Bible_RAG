"""FINAL variant: stale/missing descriptions with cause + whitespace carry-over check.
Writes expected_stale_FINAL.json (draft of config/desc_expected_stale_batch1c)."""
import json, sys, collections
sys.path.insert(0, ".")
from edgelib import *
from pypinyin import lazy_pinyin
titles = load_titles(); texts = load_texts()
g = json.load(open("graph_staging.json"))
st = {e["eid"]: e["el"] for e in g["entities"]}; nm = {e["eid"]: e["name"] for e in g["entities"]}
other = [(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if not (m["el"] in PPG and not m["curated"])]
E0 = {(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if m["el"] in PPG and not m["curated"]}
rows = [json.loads(l) for l in open("rows_1c_pos_cfull.jsonl")]
E1 = set(edges_first_wins(rows)); ids1 = {r["entity_id"] for r in rows}
T0, T1 = titles_of(other + list(E0), titles), titles_of(other + list(E1), titles)
cache = collections.defaultdict(dict)
for l in open(f"{ROOT}/frozen/descriptions.jsonl"):
    d = json.loads(l); cache[d["entity_id"]][d["titles_sha"]] = d
rows_cur = collections.defaultdict(list)
for l in open("rows_current.jsonl"):
    r = json.loads(l); rows_cur[edge_key(r)].append(r)
reg = lambda r: "book" if r["start_pos"] < texts[r["source_id"]]["title_start"] else "other"
nonppg = set(st) - {e for e, t in st.items() if t in PPG}
out = {"stale": [], "missing": []}; cause_c = collections.Counter()
for eid in sorted(cache):
    if st.get(eid) not in PPG: continue
    if eid not in ids1:
        n = nm[eid]
        if n != n.strip():
            succ = f"{st[eid].lower()}:" + "".join(lazy_pinyin(n.strip()))
            carry = succ in ids1 and succ not in cache and titles_sha(T1.get(succ, [])) in cache[eid]
            cause = "whitespace_merge"
            out["missing"].append({"entity_id": eid, "canonical_name": n, "cause": cause, "successor": succ if succ in ids1 else None,
                                   "carry_over_possible": carry})
        else:
            cause = "dictionary_drift" if eid == "person:liuer" else "book_abbreviation" if len(n) <= 2 and eid in ("person:linqian", "person:wangxia", "place:e", "place:fu", "place:ha", "place:la", "place:you", "place:yue") else "book_region_only"
            out["missing"].append({"entity_id": eid, "canonical_name": n, "cause": cause, "successor": None, "carry_over_possible": False})
        cause_c[("missing", cause)] += 1
        continue
    sha1 = titles_sha(T1.get(eid, []))
    if sha1 in cache[eid]: continue
    rem = [k for k in E0 - E1 if k[2] == eid]; add = [k for k in E1 - E0 if k[2] == eid]
    if eid in ("person:yeteluo", "person:yisao", "person:saoluo"): cause = "dictionary_drift"
    elif add and all(any((k[0], k[1], o) in E0 for o in [o for o in st if nm.get(o, "").strip() == nm[eid] and o != eid]) for k in add) and not rem: cause = "whitespace_merge"
    elif rem and not add and all(all(reg(r) == "book" for r in rows_cur.get(k, [{"start_pos": 0, "source_id": k[1]}])) for k in rem): cause = "book_region"
    elif rem and all(all(reg(r) == "book" for r in rows_cur.get(k, [])) for k in rem) if rem else False: cause = "book_region+whitespace_merge"
    else: cause = "ckip_position_or_other"
    cause_c[("stale", cause)] += 1
    out["stale"].append({"entity_id": eid, "canonical_name": nm[eid], "cause": cause,
                         "old_titles": T0.get(eid, []), "new_titles": T1.get(eid, []), "current_titles_sha": sha1})
print(dict(cause_c))
print("whitespace missing with exact carry-over:", sum(1 for m in out["missing"] if m.get("carry_over_possible")))
for s in out["stale"]:
    if s["cause"] not in ("book_region",): print("  ", s["entity_id"], s["canonical_name"], s["cause"], s["old_titles"][:3], "->", s["new_titles"][:3])
json.dump(out, open("expected_stale_FINAL.json", "w"), ensure_ascii=False, indent=1)
