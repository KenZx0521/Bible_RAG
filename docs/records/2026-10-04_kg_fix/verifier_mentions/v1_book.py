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
texts={}
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    r=json.loads(l); texts[r["id"]]=(r["type"],r["text"])
def body_off(t):
    i=t.find("：")
    return i+1
# pair -> list of (region, span, src_type)
pairs=collections.defaultdict(list)
order=[]
for l in open(f"{ROOT}/entity_mentions.jsonl"):
    r=json.loads(l)
    sid=r["source_id"]; st=r["source_type"]
    if sid not in texts: continue  # grounded pericope ids (no prefix)?
    if r.get("start_pos") is None: continue
    typ,t=texts[sid]
    bn=books[sid.split(":")[0]]
    s=r["start_pos"]
    reg="book" if s<len(bn) else ("title" if s<body_off(t) else "body")
    if st=="verse":
        anchor=("Pericope",sid.split(":v:")[0],"verse")
    elif st=="chunk":
        anchor=("Chunk",sid,"chunk")
    else:
        anchor=("Pericope",sid,"pericope")
    key=(anchor[0],anchor[1],r["entity_id"])
    pairs[key].append((reg,r["text_span"],anchor[2],s,sid))
pickle.dump(dict(pairs),open(f"{OUT}/pairs.pkl","wb"))
# body text of anchors
def anchor_body(lbl,aid):
    if lbl=="Chunk" or aid in texts:
        t=texts[aid][1]; return t[body_off(t):]
    return None
stats=collections.Counter()
ambig=[]
for (lbl,aid,eid),ms in pairs.items():
    gran=set(m[2] for m in ms)
    nonverse=[m for m in ms if m[2]!="verse"]
    first = nonverse[0] if nonverse else ms[0]
    if first[0]!="book": continue
    regs=set(m[0] for m in (nonverse if nonverse else ms))
    src = "nv" if nonverse else "verseonly"
    cls = "book_only" if regs=={"book"} else ("book+title" if regs=={"book","title"} else "has_body")
    # adversarial: does span (any) appear in body?
    body = anchor_body(lbl,aid)
    if body is None:
        # verse-only anchor in chunked pericope: concatenate verse bodies
        vb=[texts[m[4]][1] for m in ms]
        body=""
        for k,(tp,t) in texts.items():
            pass
    spans=set(m[1] for m in ms)
    inbody = body is not None and any(sp in body for sp in spans)
    stats[(lbl,src,cls,inbody)]+=1
    if cls!="has_body" and inbody: ambig.append((lbl,aid,eid,spans))
for k,v in sorted(stats.items()): print(k,v)
print("ambig sample", ambig[:30])
json.dump(ambig,open(f"{OUT}/ambig.json","w"),ensure_ascii=False)
