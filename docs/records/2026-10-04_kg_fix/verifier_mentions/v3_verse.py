import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import pickle, collections
OUT=KGFIX_SP + "/kgfix/verifier_mentions"
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
c=collections.Counter(); vo=[]
for (lbl,aid,eid),ms in pairs.items():
    if lbl!="Pericope": continue
    g=set(m[2] for m in ms)
    if g=={"verse"}:
        c[eid.split(":")[0]]+=1; vo.append((aid,eid))
print(sum(c.values()), c)
import json; json.dump(vo,open(f"{OUT}/verse_only_pairs.json","w"))
