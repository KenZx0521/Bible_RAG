"""Reconstruct live-equivalent MENTIONS edges for NER (Person/Place/Group) mentions
from output/entity_mentions.jsonl and classify each edge by evidence region.

Edge key = (label, node_id, entity_id), mirroring import_neo4j.py:256-311
(verse -> parent Pericope; chunk -> Chunk; else Pericope).

Evidence per mention:
  book   : position inside leading book name
  header : inside ' 第N章 title (..節)：'
  body   : verse text
Because CKIP-NER positions come from text.find() (ner_extractor.py:235 — first
occurrence only), we ALSO test whether the span string occurs anywhere in the
body region ("body_any").  An edge is "real-evidence" if any mapped mention has
body_any.  Classes: body / header_only / book_only / book+header_only.
"""
import json, re, collections, pickle
ROOT = "/home/kenzx0521/Bible_RAG/output"
OUT = "/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/mentions"

books = {}
for l in open(f"{ROOT}/books.jsonl", encoding="utf-8"):
    l = l.strip()
    if l:
        b = json.loads(l); books[b["id"]] = b["name"]
HDR_PC = re.compile(r"^(\S+) 第\d+章 .*?\([\d\-]+節\)：")
HDR_V = re.compile(r"^(\S+) 第\d+章 .*? 第[\d\-]+節：")
texts = {}
for l in open(f"{ROOT}/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l)
    t = r["text"]
    m = (HDR_V if r["type"] == "verse" else HDR_PC).match(t)
    assert m, r["id"]
    bl = len(books[r["id"].split(":")[0]])
    texts[r["id"]] = (r["type"], t, bl, m.end())

ents = {}
for l in open(f"{ROOT}/entities.jsonl", encoding="utf-8"):
    e = json.loads(l); ents[e["entity_id"]] = e

edges = collections.defaultdict(lambda: {"regs": collections.Counter(), "body_any": False,
                                          "spans": collections.Counter(), "first": None,
                                          "nonverse": False, "verse": False})
for l in open(f"{ROOT}/entity_mentions.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("start_pos") is None:
        continue  # grounded Event/Object/Theme (no positions by design)
    sid, st = r["source_id"], r["source_type"]
    typ, t, bl, he = texts[sid]
    if st == "verse" or ":v:" in sid:
        key = ("Pericope", sid.split(":v:")[0], r["entity_id"])
    elif st == "chunk":
        key = ("Chunk", sid, r["entity_id"])
    else:
        key = ("Pericope", sid, r["entity_id"])
    s = r["start_pos"]
    reg = "book" if s < bl else ("header" if s < he else "body")
    d = edges[key]
    d["regs"][reg] += 1
    d["spans"][r["text_span"]] += 1
    if r["text_span"] in t[he:]:
        d["body_any"] = True
    if st == "verse":
        d["verse"] = True
    else:
        d["nonverse"] = True
        if d["first"] is None:
            d["first"] = (s, r["text_span"], reg)

def klass(d):
    if d["body_any"]:
        return "body"
    r = set(d["regs"])
    if r == {"book"}:
        return "book_only"
    if r == {"header"}:
        return "header_only"
    return "book+header_only"

summary = collections.Counter()
for k, d in edges.items():
    origin = "nonverse" if d["nonverse"] else "verse_only"
    summary[(k[0], origin, klass(d))] += 1
for k, v in sorted(summary.items()):
    print(k, v)
print("total edges", len(edges))
pickle.dump({k: {**v, "regs": dict(v["regs"]), "spans": dict(v["spans"])} for k, v in edges.items()},
            open(f"{OUT}/edges.pkl", "wb"))
