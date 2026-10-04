import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, collections, re
ROOT=BIBLE_RAG_ROOT + "/output"
texts={}; verses=collections.defaultdict(list)
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    r=json.loads(l); t=r["text"]; b=t[t.find("：")+1:]
    texts[r["id"]]=b
    if r["type"]=="verse": verses[r["id"].split(":v:")[0]].append(b)
def body(sid):
    if sid in texts: return texts[sid]
    return " ".join(verses[sid])
allbody=" ".join(v for k,v in texts.items() if ":v:" in k)
def ctx(name):
    L=collections.Counter(); R=collections.Counter()
    i=allbody.find(name)
    while i>=0:
        L[allbody[i-1]]+=1; R[allbody[i+len(name)] if i+len(name)<len(allbody) else '$']+=1
        i=allbody.find(name,i+1)
    return L,R
for n in ["馬利亞","以利亞","迦勒","利亞","以利"]:
    L,R=ctx(n); print(n,sum(L.values()),"L",L.most_common(8),"R",R.most_common(10))

mal_P=["isa:8:0#", "jhn:4:0#verse", "jer:23:1#verse", "isa:36:0#verse", "2ch:18:0#verse", "2ki:18:1#verse", "2ki:17:0#verse", "2ki:23:0#verse", "2ki:5:0#verse", "1ki:22:0#verse", "1ki:21:0#verse", "1ki:18:0#verse", "rom:16:0#", "act:15:0#", "act:12:1#", "act:9:3#", "act:8:1#", "act:8:0#", "act:1:2#", "act:1:1#", "jhn:20:1#", "jhn:19:1#", "jhn:12:0#", "jhn:11:4#", "jhn:11:2#", "jhn:11:1#", "jhn:11:0#", "jhn:8:5#", "luk:24:0#", "luk:17:1#", "luk:10:5#", "luk:10:4#", "luk:9:10#", "luk:2:3#", "luk:2:2#", "luk:2:1#", "luk:2:0#", "luk:1:4#", "luk:1:3#", "luk:1:2#", "mrk:16:1#", "mrk:16:0#", "mrk:15:5#", "mrk:15:4#", "mrk:6:0#", "mat:28:0#", "mat:27:7#", "mat:27:6#", "mat:13:9#", "mat:10:1#", "mat:2:0#", "mat:1:1#", "mat:1:0#", "mic:1:1#", "mic:1:0#", "oba:1:4#", "amo:8:1#", "amo:6:0#", "amo:4:0#", "amo:3:2#", "hos:13:0#", "hos:10:0#", "hos:8:0#", "hos:7:0#", "ezk:23:0#", "ezk:16:4#", "ezk:16:3#", "jer:41:0#", "jer:31:0#", "isa:10:1#", "isa:9:3#", "1ki:13:1#", "1ki:16:3#", "1ki:16:4#", "1ki:20:0#", "1ki:20:1#", "1ki:20:2#", "1ki:22:1#", "1ki:22:3#", "2ki:1:0#", "2ki:2:2#", "2ki:3:0#", "2ki:6:1#", "2ki:6:2#", "2ki:7:0#", "2ki:7:1#", "2ki:10:0#", "2ki:10:2#", "2ki:10:3#", "2ki:10:5#", "2ki:13:0#", "2ki:13:1#", "2ki:14:0#", "2ki:14:2#", "2ki:15:1#", "2ki:15:2#", "2ki:15:3#", "2ki:15:4#", "2ki:15:5#", "2ki:17:1#", "2ki:18:0#", "2ki:21:0#", "1ch:6:0#", "2ch:22:0#", "2ch:25:1#", "2ch:25:2#", "2ch:28:1#", "2ch:28:2#", "ezr:4:1#", "neh:4:0#", "isa:7:0#"]
mal_C=["jhn:4:0:2#", "jhn:4:0:1#", "jhn:4:0:0#", "jer:23:1:0#", "isa:36:0:1#", "1ki:18:0:0#", "1ki:21:0:0#", "1ki:21:0:1#", "1ki:22:0:0#", "2ki:5:0:0#", "2ki:17:0:0#", "2ki:18:1:1#", "2ki:18:1:2#", "2ki:23:0:1#", "2ch:18:0:0#"]
eli_P=["2ki:10:1#", "jer:29:0#verse", "isa:36:0#verse", "neh:13:1#verse", "1ch:11:1#verse", "1ch:23:1#verse", "2ki:18:1#verse", "1ki:18:0#verse", "1ki:21:0#verse", "2sa:23:1#verse", "jos:22:1#verse", "jos:21:0#verse", "num:32:0#verse", "num:26:0#verse", "jas:5:1#", "rom:11:0#", "jhn:1:1#", "luk:9:10#", "luk:9:5#", "luk:9:3#", "luk:9:1#", "luk:4:2#", "luk:3:2#", "luk:1:1#", "mrk:15:4#", "mrk:9:1#", "mrk:8:4#", "mrk:6:2#", "mat:27:6#", "mat:17:0#", "mat:16:2#", "mat:11:1#", "mat:1:0#", "mal:4:0#", "jer:48:2#", "jer:37:1#", "isa:37:0#", "isa:22:1#", "isa:16:0#", "isa:15:0#", "neh:12:5#", "neh:12:3#", "neh:12:1#", "neh:3:1#", "neh:3:0#", "ezr:10:1#", "ezr:10:0#", "ezr:8:4#", "ezr:7:0#", "2ch:21:1#", "1ch:25:0#", "1ch:24:1#", "1ch:24:0#", "1ch:9:5#", "1ch:9:3#", "1ch:8:4#", "1ch:8:2#", "1ch:6:3#", "1ch:6:0#", "1ch:3:2#", "1ch:2:3#", "2ki:23:4#", "2ki:19:0#", "2ki:10:3#", "exo:6:2#", "exo:28:0#", "lev:10:0#", "lev:10:1#", "num:3:0#", "num:3:2#", "num:4:0#", "num:16:1#", "num:19:0#", "num:20:2#", "num:25:0#", "num:27:0#", "num:27:1#", "num:31:0#", "num:31:1#", "num:31:2#", "num:34:1#", "deu:10:0#", "jos:14:0#", "jos:17:0#", "jos:19:6#", "jos:24:1#", "jdg:20:1#", "1sa:7:0#", "1ki:11:1#", "1ki:17:0#", "1ki:17:1#", "1ki:18:1#", "1ki:19:0#", "1ki:19:1#", "2ki:1:0#", "2ki:1:1#", "2ki:2:0#", "2ki:2:1#", "2ki:3:0#", "2ki:9:3#"]
eli_C=["jer:29:0:0#", "isa:36:0:1#", "isa:36:0:0#", "neh:13:1:2#", "neh:13:1:0#", "1ch:23:1:1#", "1ch:23:1:0#", "1ch:11:1:0#", "2ki:18:1:2#", "2ki:18:1:1#", "2ki:18:1:0#", "num:26:0:0#", "num:26:0:3#", "num:32:0:0#", "num:32:0:1#", "num:32:0:2#", "jos:21:0:0#", "jos:22:1:0#", "jos:22:1:2#", "2sa:23:1:0#", "1ki:18:0:0#", "1ki:18:0:1#", "1ki:18:0:2#", "1ki:21:0:1#", "1ki:21:0:2#"]
def clean_mal(b):
    i=b.find("馬利亞")
    while i>=0:
        if i==0 or b[i-1]!="撒": return True
        i=b.find("馬利亞",i+1)
    return False
def clean_eli(b):
    i=b.find("以利亞")
    while i>=0:
        n=b[i+3] if i+3<len(b) else "$"
        if n not in "撒實敬薩巴他": return True
        i=b.find("以利亞",i+1)
    return False
for nm,P,C,f in [("馬利亞",mal_P,mal_C,clean_mal),("以利亞",eli_P,eli_C,clean_eli)]:
    for lbl,lst in [("P",P),("C",C)]:
        bad=[s for s in lst if not f(body(s.split("#")[0]))]
        print(nm,lbl,len(lst),"contaminated",len(bad))
    # also show sample of clean in 2ki for maliya
print([s for s in mal_P if clean_mal(body(s.split('#')[0]))])
