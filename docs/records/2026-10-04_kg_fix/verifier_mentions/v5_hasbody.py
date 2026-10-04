import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import pickle, json
OUT=KGFIX_SP + "/kgfix/verifier_mentions"
pairs=pickle.load(open(f"{OUT}/pairs.pkl","rb"))
amb=set()
import ast
hb=[]
for (lbl,aid,eid),ms in pairs.items():
    nv=[m for m in ms if m[2]!="verse"]
    if lbl!="Pericope" or not nv or nv[0][0]!="book": continue
    if any(m[0]=="body" for m in nv): hb.append(aid+"|"+eid)
print(len(hb))
json.dump(hb,open(f"{OUT}/hasbody_keys.json","w"),ensure_ascii=False)
