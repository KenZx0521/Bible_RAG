"""S5: id resolution through a frozen id table, under 1C-style NER normalization.

Simulates what 1C's normalize_surface does to the CURRENT NER rows (no CKIP
rerun): normalized span -> find_canonical_name -> pinyin provisional id.
Then compares two resolvers:
  naive  : provisional id as-is (what NER would emit after 1C)
  frozen : (type, normalize(canonical)) looked up in the run-of-record id table
           (live_state/20261004/entities.jsonl); twin keys resolve to the clean id;
           a key not in the table keeps the provisional id.
Reports renames (old id gone), new homophone merges, and twin merges.
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
from ro import OUT, jsonl, dump
from s1_whitespace import norm, mint
from entity_extraction.entity_dict import find_canonical_name

live = {}
for r in jsonl(OUT / "frozen/live_state/20261004/entities.jsonl"):
    live[r["entity_id"]] = ([l for l in r["labels"] if l != "Entity"][0], r["canonical_name"])
# frozen table: key -> ids ; twin keys resolve to the id whose stored name is already normalized
table = defaultdict(list)
for eid, (t, c) in live.items():
    table[(t, norm(c))].append(eid)
def frozen_id(t, c):
    ids = table.get((t, norm(c)))
    if not ids:
        return None
    clean = [i for i in ids if live[i][1] == norm(live[i][1]) and not any(ch.isspace() for ch in i)]
    return clean[0] if len(clean) == 1 else (ids[0] if len(ids) == 1 else None)
twin_keys = sum(1 for v in table.values() if len(v) > 1)

ner_types = {}
for r in jsonl(OUT / "ner_entities.jsonl"):
    ner_types[r["entity_id"]] = (r["type"], r["canonical_name"])
rows = 0
naive_ids, frozen_ids = defaultdict(set), defaultdict(set)   # resolved id -> set of normalized canonicals
moved_naive, moved_frozen = Counter(), Counter()
old_ids_seen = set()
for m in jsonl(OUT / "ner_mentions.jsonl"):
    eid = m["entity_id"]
    t, c_old = ner_types[eid]
    span = norm(m["text_span"])
    c = find_canonical_name(span, t)
    prov = mint(t, c)
    fz = frozen_id(t, c) or prov
    rows += 1
    old_ids_seen.add(eid)
    naive_ids[prov].add(norm(c)); frozen_ids[fz].add(norm(c))
    if prov != eid:
        moved_naive["changed_id"] += 1
    if fz != eid:
        moved_frozen["changed_id"] += 1
# entities after each resolver
def summary(ids_map, label):
    multi = {i: sorted(v) for i, v in ids_map.items() if len(v) > 1}
    # homophone groups that were NOT already merged in live (live id has those surfaces as one canonical)
    new_multi = {}
    for i, v in multi.items():
        frozen_names = {norm(live[x][1]) for x in live if x == i}
        new_multi[i] = v
    gone = sorted(old_ids_seen - set(ids_map))
    return {"resolver": label, "entities": len(ids_map), "ids_with_2plus_canonicals": len(multi),
            "old_ner_ids_gone": len(gone), "gone_with_whitespace": sum(1 for g in gone if any(ch.isspace() for ch in g)),
            "gone_sample": gone[:20], "multi_sample": dict(list(multi.items())[:20])}
res = {"ner_rows": rows, "twin_keys_in_table": twin_keys,
       "naive": summary(naive_ids, "naive"), "frozen": summary(frozen_ids, "frozen"),
       "rows_changed_id": {"naive": moved_naive["changed_id"], "frozen": moved_frozen["changed_id"]}}
# baseline: ids that already carry 2+ canonicals in the current NER half (by span canonical)
cur = defaultdict(set)
for m in jsonl(OUT / "ner_mentions.jsonl"):
    t, _ = ner_types[m["entity_id"]]
    cur[m["entity_id"]].add(norm(find_canonical_name(norm(m["text_span"]), t)))
res["current_ids_with_2plus_canonicals"] = sum(1 for v in cur.values() if len(v) > 1)
print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if "sample" not in kk}) for k, v in res.items()}, ensure_ascii=False, indent=1))
dump("s5_id_resolution.json", res)

# ---- row move categories
cat_n, cat_f = Counter(), Counter()
ex = defaultdict(list)
ws = lambda i: any(ch.isspace() for ch in i)
for m in jsonl(OUT / "ner_mentions.jsonl"):
    O = m["entity_id"]; t, _ = ner_types[O]
    c = find_canonical_name(norm(m["text_span"]), t)
    P = mint(t, c); F = frozen_id(t, c) or P
    for lab, X, cat in (("naive", P, cat_n), ("frozen", F, cat_f)):
        if X == O:
            continue
        if ws(O) and not ws(X):
            k = "ws->clean_existing" if X in live else "ws->new_id"
        elif not ws(O) and ws(X):
            k = "clean->ws_frozen(split homophone)"
        elif X in live:
            k = "clean->other_existing(split)"
        else:
            k = "clean->new_id"
        cat[k] += 1
        if len(ex[lab + k]) < 6:
            ex[lab + k].append((O, X, m["text_span"]))
print("naive:", dict(cat_n)); print("frozen:", dict(cat_f))
for k, v in ex.items(): print(" ", k, v)
