"""Classify every positioned NER mention in entity_mentions.jsonl by text region.

Regions of an embedding_queue text:
  book   : the leading book name (e.g. 馬可福音)
  header : ' 第N章 {title} (range節)：' or ' 第N章 {title} 第n節：'
  body   : verse text
Also checks whether text[start:end] == text_span (position fidelity).
"""
import json, re, collections, sys
ROOT = "/home/kenzx0521/Bible_RAG/output"
OUT = "/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/mentions"

books = {}
for l in open(f"{ROOT}/books.jsonl", encoding="utf-8"):
    l = l.strip()
    if l:
        b = json.loads(l); books[b["id"]] = b["name"]

texts = {}
for l in open(f"{ROOT}/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l); texts[r["id"]] = (r["type"], r["text"])

HDR_PC = re.compile(r"^(\S+) 第\d+章 .*?\([\d\-]+節\)：")
HDR_V = re.compile(r"^(\S+) 第\d+章 .*? 第\d+節：")

def regions(sid):
    typ, t = texts[sid]
    m = (HDR_V if typ == "verse" else HDR_PC).match(t)
    book = sid.split(":")[0]
    bn = books[book]
    assert t.startswith(bn), (sid, t[:20])
    hdr_end = m.end() if m else None
    return t, len(bn), hdr_end

stats = collections.Counter()
by_entity = collections.defaultdict(collections.Counter)
mismatch = []
rows = []
for l in open(f"{ROOT}/entity_mentions.jsonl", encoding="utf-8"):
    r = json.loads(l)
    sid = r["source_id"]
    if r.get("start_pos") is None:
        stats[("nopos", r["source_type"])] += 1
        continue
    t, blen, hend = regions(sid)
    s, e = r["start_pos"], r["end_pos"]
    if hend is None:
        stats["hdr_parse_fail"] += 1
    if t[s:e] != r["text_span"]:
        mismatch.append(r)
    if s < blen:
        reg = "book"
    elif hend is not None and s < hend:
        reg = "header"
    else:
        reg = "body"
    stats[(reg, r["source_type"])] += 1
    by_entity[r["entity_id"]][reg] += 1
    rows.append({"eid": r["entity_id"], "sid": sid, "st": r["source_type"], "span": r["text_span"],
                 "s": s, "e": e, "reg": reg})

for k, v in sorted(stats.items(), key=str):
    print(k, v)
print("position mismatch", len(mismatch))
json.dump(rows, open(f"{OUT}/positioned_rows.json", "w"), ensure_ascii=False)
top = sorted(by_entity.items(), key=lambda kv: -kv[1]["book"])[:40]
for eid, c in top:
    print(eid, dict(c))
