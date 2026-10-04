import pickle, collections
OUT="/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/verifier_mentions"
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
c1=collections.Counter(); c2=collections.Counter()
for (lbl,aid,eid),ms in pairs.items():
    nv=[m for m in ms if m[2]!="verse"]
    if not nv or nv[0][0]!="book": continue
    r1=set(m[0] for m in nv); r2=set(m[0] for m in ms)
    f=lambda r:"body" if "body" in r else ("book+title" if "title" in r else "book")
    c1[f(r1)]+=1; c2[f(r2)]+=1
print("nonverse only",c1); print("pooled with verse",c2)
