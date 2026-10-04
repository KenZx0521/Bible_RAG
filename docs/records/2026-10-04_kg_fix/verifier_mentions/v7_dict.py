import json,sys
sys.path.insert(0,"/home/kenzx0521/Bible_RAG/scripts")
from entity_extraction.entity_dict import PERSON_DICT,PLACE_DICT,GROUP_DICT
body=[]
for l in open("/home/kenzx0521/Bible_RAG/output/embedding_queue.jsonl"):
    r=json.loads(l)
    if r["type"]=="verse": t=r["text"]; body.append(t[t.find("：")+1:])
B="\n".join(body)
zero=[]
for nm,D in [("Person",PERSON_DICT),("Place",PLACE_DICT),("Group",GROUP_DICT)]:
    for c,als in D.items():
        for a in als|{c}:
            if a not in B: zero.append((nm,c,a))
print(len(zero))
for z in zero: print(z)
for v in ["撒馬利亞","尼哥德慕","凱撒利亞","泰爾","塞魯士","伯‧善","巴旦‧亞蘭","底格里斯","西門‧彼得"]: print(v,B.count(v))
