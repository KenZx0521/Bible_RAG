import json, collections
ROOT = "/home/kenzx0521/Bible_RAG/output"
def ekey(r):
    sid, st = r["source_id"], r.get("source_type")
    if st == "verse" or ":v:" in sid: return ("Pericope", sid.split(":v:")[0], r["entity_id"])
    if st == "chunk": return ("Chunk", sid, r["entity_id"])
    return ("Pericope", sid, r["entity_id"])
def rows(path):
    for l in open(path): yield json.loads(l)
def edges_of(path):
    E = collections.OrderedDict(); allrows = collections.defaultdict(list)
    for r in rows(path):
        k = ekey(r)
        allrows[k].append(r)
        if k not in E: E[k] = r
    return E, allrows
def staging_ppg():
    g = json.load(open("graphs.json"))["staging"]
    return {(m["lab"], m["sid"], m["eid"]): m for m in g["mentions"] if m["etype"] in ("Person", "Place", "Group") and not m["cur"]}
