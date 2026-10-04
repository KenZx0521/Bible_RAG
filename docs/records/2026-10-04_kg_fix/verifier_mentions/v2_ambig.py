import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, re, collections, pickle
ROOT=BIBLE_RAG_ROOT + "/output"
OUT=KGFIX_SP + "/kgfix/verifier_mentions"
books={}
for l in open(f"{ROOT}/books.jsonl"):
    if l.strip():
        b=json.loads(l); books[b["id"]]=b["name"]
texts={}; verses=collections.defaultdict(list)
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    r=json.loads(l); texts[r["id"]]=(r["type"],r["text"])
    if r["type"]=="verse": verses[r["id"].split(":v:")[0]].append(r["text"])
bo=lambda t:t.find("：")+1
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
out=collections.Counter(); rows=[]
for (lbl,aid,eid),ms in pairs.items():
    nonverse=[m for m in ms if m[2]!="verse"]
    use = nonverse if nonverse else ms
    if use[0][0]!="book": continue
    regs=set(m[0] for m in use)
    if "body" in regs: continue
    if lbl=="Chunk" or aid in texts:
        body=texts[aid][1][bo(texts[aid][1]):]
    else:
        body="".join(v[bo(v):] for v in verses[aid])
    spans=set(m[1] for m in ms)
    hits=[]
    for sp in spans:
        i=body.find(sp)
        while i>=0:
            hits.append(body[max(0,i-4):i+len(sp)+4]); i=body.find(sp,i+1)
    out[(lbl,"verseonly" if not nonverse else "nv", bool(hits))]+=1
    if hits: rows.append((lbl,aid,eid,sorted(spans),hits[:3]))
for k,v in sorted(out.items()): print(k,v)
for r in rows: print(r)
