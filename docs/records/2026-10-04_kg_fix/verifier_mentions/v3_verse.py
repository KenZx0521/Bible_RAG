import pickle, collections
OUT="/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/verifier_mentions"
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
c=collections.Counter(); vo=[]
for (lbl,aid,eid),ms in pairs.items():
    if lbl!="Pericope": continue
    g=set(m[2] for m in ms)
    if g=={"verse"}:
        c[eid.split(":")[0]]+=1; vo.append((aid,eid))
print(sum(c.values()), c)
import json; json.dump(vo,open(f"{OUT}/verse_only_pairs.json","w"))
