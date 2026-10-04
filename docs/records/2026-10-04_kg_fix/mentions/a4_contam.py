"""Edge-level substring-contamination for high-risk dictionary names.
A positioned BODY mention is 'ext' (inside a longer RCUV name / non-name word)
when its neighbour char is in the curated extension set for that span.
An edge is contaminated when it has >=1 BODY mention and ALL body mentions are
'ext' (no clean standalone occurrence) — book/header-only edges are excluded
here (counted under the book-prefix defect)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, re, collections, pickle
ROOT = BIBLE_RAG_ROOT + "/output"
OUT = KGFIX_SP + "/kgfix/mentions"
EXT = {  # span: (left-set, right-set)  — from neighbour analysis a3/a3b
    "馬利亞": (set("撒"), set()),                      # 撒馬利亞
    "以利亞": (set(), set("撒實敬薩利他巴")),            # 以利亞撒/實/敬/薩/利…
    "利亞":   (set("迦烏撒加比尼敘瑪他"), set()),        # 撒迦利亞/烏利亞/敘利亞…
    "以利":   (set(), set("加法押雅戶約拿撒蓿米薩突")),   # 以利加拿/以利法/以利押…
    "迦勒":   (set("米"), set("底")),                    # 迦勒底 / 米迦勒(dict)
    "撒拉":   (set("布"), set("鐵旦弗")),                # 尼布撒拉旦/撒拉鐵
    "亞拿":   (set(), set("突尼米伯哈")),                # 亞拿突/亞拿尼亞
    "哈拿":   (set(), set("尼篾")),                      # 哈拿尼/哈拿篾
    "西拉":   (set("西摩"), set()),                      # 西西拉
    "腓力":   (set(), set("斯")),                        # 腓力斯
    "亞伯":   (set(), set("尼底頓‧")),                   # 亞伯尼歌/亞伯‧米何拉
    "約拿":   (set(), set("達")),                        # 約拿達
    "閃":     (set("一"), set("電爍亮耀開躲避")),          # 閃電/閃爍
    "含":     (set("包隱蘊"), set("着怒笑羞忍淚冤恨糊有")),  # 含怒/含笑…
    "但":     None,  # handled by cleanup_noise_entities geo gate (see a5)
}
HDR = {"verse": re.compile(r"^(\S+) 第\d+章 .*? 第[\d\-]+節："),
       "other": re.compile(r"^(\S+) 第\d+章 .*?\([\d\-]+節\)：")}
texts = {}
for l in open(f"{ROOT}/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l)
    m = HDR["verse" if r["type"] == "verse" else "other"].match(r["text"])
    texts[r["id"]] = (r["text"], m.end())
edge = collections.defaultdict(lambda: {"clean": 0, "ext": 0, "nonbody": 0, "span": None})
for l in open(f"{ROOT}/entity_mentions.jsonl", encoding="utf-8"):
    r = json.loads(l)
    sp = r["text_span"]
    if sp not in EXT or EXT[sp] is None or r.get("start_pos") is None:
        continue
    sid, st = r["source_id"], r["source_type"]
    t, he = texts[sid]
    key = (("Pericope", sid.split(":v:")[0]) if st == "verse" else
           (("Chunk", sid) if st == "chunk" else ("Pericope", sid))) + (r["entity_id"],)
    s, e = r["start_pos"], r["end_pos"]
    d = edge[key]; d["span"] = sp
    if s < he:
        d["nonbody"] += 1; continue
    L, R = EXT[sp]
    lc = t[s-1] if s > 0 else ""; rc = t[e] if e < len(t) else ""
    if lc in L or rc in R:
        d["ext"] += 1
    else:
        d["clean"] += 1
res = collections.defaultdict(collections.Counter)
bad_edges = []
for k, d in edge.items():
    if d["clean"] + d["ext"] == 0:
        cls = "nonbody_only"
    elif d["clean"] == 0:
        cls = "contaminated"; bad_edges.append(k)
    else:
        cls = "clean"
    res[(d["span"], k[2])][cls] += 1
for k, c in sorted(res.items(), key=lambda kv: -kv[1]["contaminated"]):
    tot = sum(c.values())
    print(k, dict(c), f"contam={c['contaminated']}/{tot}")
print("TOTAL contaminated edges", len(bad_edges))
pickle.dump(bad_edges, open(f"{OUT}/contam_edges.pkl", "wb"))
