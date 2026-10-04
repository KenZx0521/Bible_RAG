"""Where does the S1->S2 (title+body input) CKIP churn come from?  Compare the CKIP
tokens of the full-text run and the title+body run, in the body region only,
per item kind: short texts (one CKIP segment both times) vs long ones (>510
chars: the fixed 510-char segment cuts move when the prefix is dropped)."""
import json, pickle, re, collections
ROOT = "/home/kenzx0521/Bible_RAG/output"
CH = re.compile(r"^(\S+) 第\d+章 ")
full = pickle.load(open("ckip_raw_full_gpu.pkl", "rb")); sub = pickle.load(open("ckip_raw_sub_gpu.pkl", "rb"))
MAP = {"PERSON", "GPE", "LOC", "ORG", "NORP"}
st = collections.Counter(); ex = collections.defaultdict(list)
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    d = json.loads(l); t = d["text"]; off = CH.match(t).end(); body = t.find("：") + 1
    a = {(w, n, i[0]) for w, n, i in full[d["id"]] if n in MAP and i[0] >= body}
    b = {(w, n, i[0] + off) for w, n, i in sub[d["id"]] if n in MAP and i[0] + off >= body}
    kind = ("long" if len(t) > 510 else "short") + "_" + d["type"]
    st[(kind, "items")] += 1
    st[(kind, "tokens_full")] += len(a); st[(kind, "only_full")] += len(a - b); st[(kind, "only_sub")] += len(b - a)
    if a != b: st[(kind, "items_changed")] += 1
    if len(ex[kind]) < 4 and a != b:
        ex[kind].append((d["id"], sorted(a - b)[:3], sorted(b - a)[:3]))
for k in sorted({k for k, _ in st}):
    print(k, {m: st[(k, m)] for m in ("items", "items_changed", "tokens_full", "only_full", "only_sub")})
for k, v in ex.items():
    print(k); [print("   ", x) for x in v]
