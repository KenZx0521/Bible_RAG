import pickle, json
OUT="/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/verifier_mentions"
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
