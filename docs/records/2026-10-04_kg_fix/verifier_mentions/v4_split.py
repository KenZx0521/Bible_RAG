import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import pickle, collections
OUT=KGFIX_SP + "/kgfix/verifier_mentions"
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
c1=collections.Counter(); c2=collections.Counter()
for (lbl,aid,eid),ms in pairs.items():
    nv=[m for m in ms if m[2]!="verse"]
    if not nv or nv[0][0]!="book": continue
    r1=set(m[0] for m in nv); r2=set(m[0] for m in ms)
    f=lambda r:"body" if "body" in r else ("book+title" if "title" in r else "book")
    c1[f(r1)]+=1; c2[f(r2)]+=1
print("nonverse only",c1); print("pooled with verse",c2)
