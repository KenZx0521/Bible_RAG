"""Offline simulation of 1C (NER: title+body only, whitespace strip, book-abbrev stoplist)
and 1D (E/O/T whitespace twins, R8 junk, 5 named EV-09 events) on the staging graph.
Inputs read-only: graph_staging.pkl (READ queries on 7688), output/*.jsonl, output/frozen/descriptions.jsonl.
Approximation (inference): an edge survives 1C iff one of its JSONL occurrence rows has its
span inside text[book_end:] (title+body). Dictionary hits are found at every occurrence, so
this is exact for them; CKIP-only spans may or may not be re-tagged in the body."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import sys, os, re, json, pickle, hashlib, collections
sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts"); sys.path.insert(0, BIBLE_RAG_ROOT)
from pypinyin import lazy_pinyin
from bible_chunking.config import CROSS_REF_ABBREV
from export_event_registry import curated_event_ids
from kg_validate.checks_r import _is_junk_name
R = BIBLE_RAG_ROOT; D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); kg, edges, ents = g["kg"], g["edges"], g["ents"]
label = {e["eid"]: e["label"] for e in ents}; name = {e["eid"]: e["name"] for e in ents}
PPG = {"Person", "Place", "Group"}

texts = {}
for l in open(f"{R}/output/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l); texts[r["id"]] = r["text"]
BOOK_RE = re.compile(r"^\S+ 第\d+章 ")
def key_of(m):
    sid = m["source_id"]
    if m.get("source_type") == "chunk": return ("Chunk", sid)
    return ("Pericope", sid.split(":v:")[0])

survive = collections.defaultdict(bool); seen = set()
for l in open(f"{R}/output/entity_mentions.jsonl", encoding="utf-8"):
    m = json.loads(l)
    if m.get("start_pos") is None or label.get(m["entity_id"]) not in PPG and m["entity_id"] in label: continue
    k = (*key_of(m), m["entity_id"]); seen.add(k)
    t = texts[m["source_id"]]; be = BOOK_RE.match(t).end()
    if (m["text_span"] or "").strip() and (m["text_span"].strip() in t[be:]):
        survive[k] = True

# --- 1C ---------------------------------------------------------------
abbrev = set(CROSS_REF_ABBREV)
def strip_target(eid):
    nm = name[eid]; s = nm.strip(); lab = label[eid]
    twins = [e for e in name if label[e] == lab and name[e] == s and e != eid]
    return twins[0] if twins else f"{lab.lower()}:{''.join(lazy_pinyin(s))}", bool(twins)
ws_ppg = {e for e in name if label[e] in PPG and name[e] != (name[e] or "").strip()}
remap = {}; twin_hit = 0
for e in ws_ppg:
    t, hit = strip_target(e); remap[e] = t; twin_hit += hit
abbrev_ents = sorted(e for e in name if label[e] in PPG and (name[e] or "").strip() in abbrev and name[e].strip() not in {"但"})
print("1C whitespace P/P/G:", len(ws_ppg), "with same-label clean twin:", twin_hit)
print("1C book-abbrev P/P/G entities:", len(abbrev_ents), [(e, name[e]) for e in abbrev_ents])

def is_curated(ed): return ed["source"] in ("manual_patch", "head_event_backfill")
before = [(ed["lab"], ed["sid"], ed["eid"], ed["title"], ed["source"], ed["start_pos"]) for ed in edges]
after1c, dropped = [], collections.Counter()
no_jsonl = 0
for (lab, sid, eid, title, src, sp) in before:
    if label.get(eid) in PPG and src not in ("manual_patch", "head_event_backfill"):
        k = (lab, sid, eid)
        if k not in seen: no_jsonl += 1
        elif not survive[k]: dropped["book_region_only"] += 1; continue
        if eid in abbrev_ents: dropped["book_abbrev_entity"] += 1; continue
        eid = remap.get(eid, eid)
    after1c.append((lab, sid, eid, title, src, sp))
after1c = list({(a[0], a[1], a[2]): a for a in after1c}.values())  # MERGE collapses twin duplicates
print("1C P/P/G live edges without JSONL occurrence rows:", no_jsonl)
print("1C MENTIONS:", len(before), "->", len(after1c), dict(dropped))

def anchors(rows):
    out = collections.defaultdict(set)
    for (lab, sid, eid, *_ ) in rows:
        out[eid].add(kg.chunk_parent.get(sid, sid) if lab == "Chunk" else sid)
    return out
a0, a1 = anchors(before), anchors(after1c)
for e in ("person:make", "person:matai", "person:lujia", "person:yuehan", "place:aiji"):
    print(f"  {e} {name.get(e)} pericope-anchors {len(a0.get(e, ()))} -> {len(a1.get(e, ()))}")
gone = sorted(e for e in a0 if label.get(e) in PPG and e not in a1 and e not in remap)
print("1C P/P/G entities left with no MENTIONS (node disappears):", len(gone), [name[e] for e in gone][:40])
touched = sorted(e for e in set(a0) | set(a1) if label.get(e) in PPG and a0.get(e) != a1.get(e))
print("1C P/P/G entities whose anchor set changes:", len(touched))

# --- description stale/missing (titles_cypher rule: distinct non-empty titles, code-point order, first 6)
def titles(rows):
    out = collections.defaultdict(set)
    for (lab, sid, eid, title, *_ ) in rows:
        if title: out[eid].add(title)
    return {e: sorted(t)[:6] for e, t in out.items()}
def tsha(t): return hashlib.sha256(json.dumps(list(t or []), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
cache = collections.defaultdict(set)
for l in open(f"{R}/output/frozen/descriptions.jsonl", encoding="utf-8"):
    r = json.loads(l); cache[r["entity_id"]].add(r["titles_sha"])
def classify(rows, nodes):
    t = titles(rows); st, mi = [], []
    for e, shas in cache.items():
        if e not in nodes: mi.append(e)
        elif tsha(t.get(e, [])) not in shas: st.append(e)
    return st, mi
nodes0 = set(name)
st0, mi0 = classify(before, nodes0)
print("replay vs BEFORE (self-check, expect 0/0):", len(st0), len(mi0))
nodes1 = (nodes0 - set(gone) - set(abbrev_ents) - set(remap)) | set(remap.values())
st1, mi1 = classify(after1c, nodes1)
print("replay after 1C: stale", len(st1), collections.Counter(label.get(e) for e in st1), "missing", len(mi1))

# --- 1D ---------------------------------------------------------------
EOT = {"Event", "Object", "Theme"}
allow = {"這是基督嗎？"}
junk = {e for e in name if label[e] in EOT and (name[e] or "").strip() not in allow and _is_junk_name(name[e])}
ws_eot = {e for e in name if label[e] in EOT and name[e] != (name[e] or "").strip()}
remap_d = {}
for e in ws_eot:
    t, hit = strip_target(e)
    if hit: remap_d[e] = t
junk_del = junk - set(remap_d)
named_ev09 = {e for e in name if label[e] == "Event" and name[e] in {"瑪拉", "瑪撒", "米利巴", "耶和華曉諭", "曉諭摩西"}}
curated = set(curated_event_ids())
print("1D R8 junk:", collections.Counter(label[e] for e in junk), "| E/O/T whitespace:", len(ws_eot), "twin-merged:", len(remap_d),
      "| EV-09 named events found:", sorted(name[e] for e in named_ev09))
print("1D curated registry ids touched by deletions/merges:", sorted((junk_del | named_ev09 | set(remap_d)) & curated))
delete = junk_del | named_ev09
after1d = []
for (lab, sid, eid, title, src, sp) in after1c:
    if eid in delete: continue
    after1d.append((lab, sid, remap_d.get(eid, eid), title, src, sp))
after1d = list({(a[0], a[1], a[2]): a for a in after1d}.values())
ev_keys = lambda rows: {(r[0], r[1], r[2]) for r in rows if label.get(r[2]) == "Event"}
k0, k1, k2 = ev_keys(before), ev_keys(after1c), ev_keys(after1d)
print("H10 Event MENTIONS: before", len(k0), "after 1C", len(k1), "(identical:", k0 == k1, ") after 1D", len(k2))
reg_keys = lambda ks: {k for k in ks if k[2] in curated}
print("H10 restricted to curated (registry) events unchanged after 1D:", reg_keys(k0) == reg_keys(k2), len(reg_keys(k0)))
nodes2 = (nodes1 - delete - set(remap_d))
st2, mi2 = classify(after1d, nodes2)
print("replay after 1C+1D: stale", len(st2), collections.Counter(label.get(e) for e in st2), "missing", len(mi2), collections.Counter(label.get(e) for e in mi2))
json.dump({"stale_1c": st1, "missing_1c": mi1, "stale_1c1d": st2, "missing_1c1d": mi2, "touched_1c": touched, "gone_1c": gone},
          open(f"{D}/sim1c1d_desc.json", "w"), ensure_ascii=False, indent=1)
pickle.dump({"after1c": after1c, "after1d": after1d, "remap": remap, "remap_d": remap_d, "delete": delete}, open(f"{D}/sim1c1d.pkl", "wb"))
