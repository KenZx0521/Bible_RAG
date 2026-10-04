"""Impact of MENTIONS fix on Step-6 relation outputs (read-only).
bad pericope-level pairs = book-prefix-only + substring-contaminated (14 names, lower bound)
                          + place:dan non-geo (cleanup_noise_entities gate)."""
import json, pickle, collections, sys, re
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
ROOT = "/home/kenzx0521/Bible_RAG/output"
E = pickle.load(open("edges.pkl", "rb"))
contam = set(pickle.load(open("contam_edges.pkl", "rb")))
def klass(d):
    if d["body_any"]: return "body"
    r = set(d["regs"])
    return "book_only" if r == {"book"} else ("header_only" if r == {"header"} else "book+header_only")
bad = {}
for k, d in E.items():
    if k[0] != "Pericope": continue
    kl = klass(d)
    if kl in ("book_only", "book+header_only"): bad[(k[1], k[2])] = "book"
    elif k in contam: bad[(k[1], k[2])] = "substr"
# dan gate (replicates cleanup_noise_entities._is_geo_context)
# verbatim copy of cleanup_noise_entities.py:43-46,106-136 (module imports neo4j)
PUNCT = set("，。；：、「」？！ \n\t^$（）－")
GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}
LIST_OK_PREV = {"和", "與", "同"} | PUNCT
def _is_geo_context(ctx):
    if "別是巴" in ctx: return True
    i = ctx.find("但")
    while i >= 0:
        p = ctx[i - 1] if i > 0 else "^"; n = ctx[i + 1] if i + 1 < len(ctx) else "$"
        if p in GEO_PREV and n != "以": return True
        if p in NAMING_PREV and (n in PUNCT or n == "$"): return True
        if p in LIST_OK_PREV and n == "、": return True
        if p == "、" and (n in PUNCT or n == "$"): return True
        i = ctx.find("但", i + 1)
    return False
keep = set()
for l in open(f"{ROOT}/entity_mentions.jsonl", encoding="utf-8"):
    if '"place:dan"' not in l: continue
    rec = json.loads(l)
    if rec.get("entity_id") == "place:dan" and _is_geo_context(rec.get("context", "")):
        keep.add(rec["source_id"].split(":v:")[0])
dan_all = {k[1] for k in E if k[0] == "Pericope" and k[2] == "place:dan"}
for p in dan_all - keep: bad[(p, "place:dan")] = "dan"
print("bad pericope pairs", collections.Counter(bad.values()), "dan keep", len(keep), "dan all", len(dan_all))
def hit(rec):
    p = rec.get("source_pericope_id") or ""
    return bad.get((p, rec["head_id"])) or bad.get((p, rec["tail_id"]))
for fn in ("relations.jsonl", "relations_unclassified.jsonl"):
    c = collections.Counter(); byrel = collections.Counter(); nos = 0
    for l in open(f"{ROOT}/{fn}", encoding="utf-8"):
        r = json.loads(l)
        if not r.get("source_pericope_id"): nos += 1; continue
        h = hit(r)
        c[h or "ok"] += 1
        if h: byrel[(r.get("relation") or (r.get("head_type")+"-"+r.get("tail_type")), h)] += 1
    print(fn, "no_source_pid", nos, dict(c)); print("  top", byrel.most_common(12))
