"""R1 (reviewer, independent): whitespace twins from the LIVE export, not the JSONL chain.

Independent re-implementation (no planner code imported):
  * dirty = canonical_name != NFC(strip-all-whitespace(name)) OR id contains whitespace
  * same-type twin = another entity of the same type label whose cleaned name equals,
    and whose own name/id are clean
  * after merge with the 'keep' id policy: count ids still carrying whitespace
  * occurrence overlap: does a dirty twin's mention row sit on the SAME occurrence as a
    clean-twin row (same source_id, |start diff|<=1)?  -> double count in mention_count / PG rows
Reads: output/frozen/live_state/20261004/entities.jsonl, output/entity_mentions.jsonl,
       output/entities.jsonl (mention_count). No DB.
"""
import json, re, unicodedata, sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("/home/kenzx0521/Bible_RAG/output")
WS = re.compile(r"[\s　​‌‍﻿]")


def clean(s):
    return WS.sub("", unicodedata.normalize("NFC", s or ""))


def jl(p):
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


live = {}
for r in jl(OUT / "frozen/live_state/20261004/entities.jsonl"):
    t = [l for l in r["labels"] if l != "Entity"]
    live[r["entity_id"]] = (t[0], r["canonical_name"])

dirty = {e for e, (t, n) in live.items() if n != clean(n) or WS.search(e)}
by_key = defaultdict(list)
for e, (t, n) in live.items():
    by_key[(t, clean(n))].append(e)

merge, keep_ws, no_clean, multi_clean = {}, [], [], []
for e in sorted(dirty):
    t, n = live[e]
    peers = [p for p in by_key[(t, clean(n))] if p != e and p not in dirty]
    if len(peers) == 1:
        merge[e] = peers[0]
    elif len(peers) > 1:
        multi_clean.append((e, peers))
    else:
        if WS.search(e):
            keep_ws.append(e)
        no_clean.append(e)

res = {
    "live_entities": len(live),
    "dirty_total": len(dirty),
    "dirty_name": sum(1 for e in dirty if live[e][1] != clean(live[e][1])),
    "dirty_by_type": dict(Counter(live[e][0] for e in dirty)),
    "same_type_twin_merge": len(merge),
    "merge_by_type": dict(Counter(live[e][0] for e in merge)),
    "dirty_groups_with_multiple_clean_peers": len(multi_clean),
    "no_clean_twin": len(no_clean),
    "ids_with_ws_kept_after_merge": len(keep_ws),
    "kept_ws_by_type": dict(Counter(live[e][0] for e in keep_ws)),
}

# occurrence overlap between dirty twin rows and survivor rows
rows = defaultdict(list)
for m in jl(OUT / "entity_mentions.jsonl"):
    if m["entity_id"] in merge or m["entity_id"] in set(merge.values()):
        rows[m["entity_id"]].append((m["source_id"], m.get("start_pos"), m.get("text_span")))
same_occ, total_dirty_rows = 0, 0
samples = []
for d, s in merge.items():
    surv = defaultdict(set)
    for sid, sp, _ in rows[s]:
        surv[sid].add(sp)
    for sid, sp, span in rows[d]:
        total_dirty_rows += 1
        if sp is None:
            continue
        if any(x is not None and abs(x - sp) <= 1 for x in surv.get(sid, ())):
            same_occ += 1
            if len(samples) < 8:
                samples.append(f"{sid}@{sp} {span!r} {d}->{s}")
res["dirty_twin_rows"] = total_dirty_rows
res["dirty_rows_on_same_occurrence_as_survivor"] = same_occ
res["same_occurrence_samples"] = samples

# protected ids involved?
reg = json.load(open("/home/kenzx0521/Bible_RAG/backend/data/event_registry.json"))
reg_ids = {e["id"] for e in reg["events"]}
res["registry_ids_in_merge"] = sorted((set(merge) | set(merge.values())) & reg_ids)
json.dump({**res, "merge": merge, "keep_ws": keep_ws}, open(Path(__file__).with_suffix(".json"), "w"),
          ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
