"""Reviewer's independent NER replay (does not import the planner's ner_sim).

CKIP tokens: planner's GPU pickle (word, ner, idx) for the FULL text -- the only
reused artifact; validated here by replaying the CURRENT code path and diffing
against output/ner_mentions.jsonl.

mode current : ner_extractor as of a32fbea (CKIP pos = text.find)
mode final   : planner FINAL design (dict on title+body, CKIP full text with idx,
               drop tokens left of region start, normalize_surface, stoplist
               CROSS_REF_ABBREV-{但,珥} on surface, 但 geo-at-position,
               xref-remnant titles: region starts at body)
Writes rrows_<mode>.jsonl (+ ents).
"""
import json, pickle, re, sys, unicodedata, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts"); sys.path.insert(0, "/home/kenzx0521/Bible_RAG")
from entity_extraction.ner_extractor import NERExtractor, NERResult
from entity_extraction.entity_dict import find_canonical_name
from entity_extraction.models import Entity, EntityMention, EntityType, ExtractionMethod
from entity_extraction.entity_normalizer import normalize_and_merge
from bible_chunking.config import CROSS_REF_ABBREV
mode = sys.argv[1]
STOPEX = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"但", "珥"}
ROOT = "/home/kenzx0521/Bible_RAG/output"
books = {b["id"]: b["name"] for b in map(json.loads, open(f"{ROOT}/books.jsonl"))}
raw = pickle.load(open("../1C/ckip_raw_full_gpu.pkl", "rb"))
ext = NERExtractor.__new__(NERExtractor); NERExtractor.__init__(ext)
ext._initialized = True
CHAP = re.compile(r" 第\d+章 ")
XREF = re.compile(r"^[（(＊*]|\d+‧\d+")
WS = " \t\n\r　 ​‌‍﻿"
def regions(sid, typ, text):
    bn = books[sid.split(":")[0]]
    assert text.startswith(bn)
    m = CHAP.match(text, len(bn)); assert m, (sid, text[:30])
    title_start = m.end()
    body_start = text.find("：") + 1
    title = text[title_start:body_start - 1]
    title = re.sub(r" (\([\d\-]+節\)|第[\d\-]+節)$", "", title)
    kind = "xref" if title != "(無標題)" and XREF.search(title) else "title"
    return title_start, body_start, kind
PUNCT = set("，。；：、「」？！ \n\t^$（）－"); GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}; LIST_OK_PREV = {"和", "與", "同"} | PUNCT
def geo_at(text, i):
    if "別是巴" in text[max(0, i - 30): i + 31]: return True
    p = text[i - 1] if i > 0 else "^"; n = text[i + 1] if i + 1 < len(text) else "$"
    return (p in GEO_PREV and n != "以") or (p in NAMING_PREV and (n in PUNCT or n == "$")) \
        or (p in LIST_OK_PREV and n == "、") or (p == "、" and (n in PUNCT or n == "$"))
STOP = set(CROSS_REF_ABBREV) - STOPEX
st = collections.Counter()
all_ents, all_m = {}, []
items = [json.loads(l) for l in open(f"{ROOT}/embedding_queue.jsonl")]
for it in items:
    text, sid, typ = it["text"], it["id"], it["type"]
    toks = raw[sid]
    if mode == "current":
        d = ext._extract_by_dictionary(text)
        c = []
        for w, ner, idx in toks:
            t = ext._map_ckip_type(ner)
            if t:
                s = text.find(w)
                if s != -1: c.append(NERResult(w, t, s, s + len(w)))
        res = ext._merge_results(d, c); regs = None
    else:
        ts, bs, kind = regions(sid, typ, text)
        off = bs if kind == "xref" else ts
        st["xref_items"] += kind == "xref"
        d = [NERResult(r.text, r.entity_type, r.start + off, r.end + off) for r in ext._extract_by_dictionary(text[off:])]
        c = []
        for w, ner, (a, b) in toks:
            t = ext._map_ckip_type(ner)
            if not t: continue
            assert text[a:b] == w
            w2 = unicodedata.normalize("NFC", w); lead = len(w2) - len(w2.lstrip(WS)); core = w2.strip(WS)
            if not core: st["empty"] += 1; continue
            s = a + lead
            if s < off: st["ckip_dropped_prefix"] += 1; continue
            c.append(NERResult(core, t, s, s + len(core)))
        res = []
        for r in ext._merge_results(d, c):
            if r.text in STOP: st["stop:" + r.text] += 1; continue
            if r.text == "但" and not geo_at(text, r.start): st["dan_drop"] += 1; continue
            res.append(r)
        regs = bs
    ents = {}; k = 0
    for r in res:
        et = EntityType(r.entity_type); cn = find_canonical_name(r.text, r.entity_type)
        eid = ext._generate_entity_id(et, cn)
        if eid not in ents:
            ents[eid] = Entity(entity_id=eid, type=et, canonical_name=cn, aliases=[r.text] if r.text != cn else [],
                               extraction_method=ExtractionMethod.NER, mention_count=1)
        else:
            ents[eid].mention_count += 1
            if r.text != cn and r.text not in ents[eid].aliases: ents[eid].aliases.append(r.text)
        k += 1
        m = EntityMention(mention_id=f"m:{sid}:{k:03d}", entity_id=eid, source_id=sid, source_type=typ,
                          text_span=r.text, start_pos=r.start, end_pos=r.end)
        m.region = None if regs is None else ("title" if r.start < regs else "body")
        all_m.append(m)
    for e in ents.values():
        if e.entity_id not in all_ents: all_ents[e.entity_id] = e
        else:
            all_ents[e.entity_id].mention_count += e.mention_count
            for a in e.aliases:
                if a not in all_ents[e.entity_id].aliases: all_ents[e.entity_id].aliases.append(a)
region = {m.mention_id: m.region for m in all_m}
ents, ments = normalize_and_merge(all_ents, {}, all_m, [])
with open(f"rrows_{mode}.jsonl", "w") as f:
    for m in ments:
        f.write(json.dumps({"entity_id": m.entity_id, "source_id": m.source_id, "source_type": m.source_type,
                            "text_span": m.text_span, "start_pos": m.start_pos, "end_pos": m.end_pos,
                            "region": region[m.mention_id]}, ensure_ascii=False) + "\n")
with open(f"rents_{mode}.jsonl", "w") as f:
    for e in ents.values(): f.write(e.to_json() + "\n")
print(mode, len(ents), len(ments), dict(st))
