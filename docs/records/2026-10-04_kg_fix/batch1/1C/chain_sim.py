"""Attribute the 1C MENTIONS change to each fix by applying them one at a time.

S0 current code (full text, CKIP position = text.find)      [== output/ner_mentions.jsonl]
S1 + CKIP NerToken.idx positions (full text)                 M5
S2 + NER input = title+body (book name and 第N章 dropped)     M1
S3 + no NER on cross-reference-remnant titles                ID-3 (abbreviations' source)
S4 + normalize_surface (strip / NFC, offset)                  ID-3 (whitespace)
S5 + '但' geo gate in NER (position-specific)                 M3   == batch-1C NER
S0..S4 get cleanup 10.2's place:dan edge filter applied after import (as the live chain does).
Edges per import_neo4j (verse -> Pericope).  Writes chain_result.json.
"""
import json, pickle, re, sys, collections, unicodedata
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts"); sys.path.insert(0, "/home/kenzx0521/Bible_RAG"); sys.path.insert(0, ".")
from entity_extraction.ner_extractor import NERExtractor, NERResult
from entity_extraction.entity_normalizer import normalize_and_merge
from edgelib import edge_key, edges_first_wins, load_texts, ROOT, PPG
from ner_sim_geo import is_geo_context, _geo_at
C = collections.Counter
CH = re.compile(r"^(\S+) 第\d+章 ")
HDR = {"verse": re.compile(r"^(\S+) 第(\d+)章 (.*?) 第([\d\-]+)節："),
       "other": re.compile(r"^(\S+) 第(\d+)章 (.*?) \(([\d\-]+)節\)：")}
XREF_TITLE = re.compile(r"^[（(＊*]|\d+‧\d+")
WS = " \t\n\r　 ​‌‍﻿"
items = [json.loads(l) for l in open(f"{ROOT}/embedding_queue.jsonl")]
raw = {m: pickle.load(open(f"ckip_raw_{m}_gpu.pkl", "rb")) for m in ("full", "sub")}
raw["body_xref"] = pickle.load(open("ckip_raw_body_xref_gpu.pkl", "rb"))

class Replay(NERExtractor):
    def _initialize_ckip(self): self._initialized = True
ext = Replay()

def is_xref(text, typ):
    t = HDR["verse" if typ == "verse" else "other"].match(text).group(3)
    return t != "(無標題)" and bool(XREF_TITLE.search(t))

def run(step):
    E, M = {}, []
    for it in items:
        text, sid, typ = it["text"], it["id"], it["type"]
        body = text.find("：") + 1
        if step == 0:
            toks, off, use_find = raw["full"][sid], 0, True
        elif step == 1:
            toks, off, use_find = raw["full"][sid], 0, False
        else:
            toks, off, use_find = raw["sub"][sid], CH.match(text).end(), False
            if step >= 3 and is_xref(text, typ):
                toks, off = raw["body_xref"][sid], body
        sub = text[off:]
        d = [NERResult(r.text, r.entity_type, r.start + off, r.end + off) for r in ext._extract_by_dictionary(sub)]
        c = []
        for word, ner, (a, b) in toks:
            t = ext._map_ckip_type(ner)
            if not t: continue
            if use_find:
                s = text.find(word)
                if s == -1: continue
                c.append(NERResult(word, t, s, s + len(word))); continue
            s, w = a + off, word
            if step >= 4:
                w = unicodedata.normalize("NFC", word); lead = len(w) - len(w.lstrip(WS)); w = w.strip(WS); s += lead
                if not w: continue
            c.append(NERResult(w, t, s, s + len(w)))
        merged = ext._merge_results(d, c)
        if step >= 5:
            merged = [r for r in merged if r.text != "但" or
                      ("別是巴" in text[max(0, r.start - 30):r.start + 31] or _geo_at(text, r.start))]
        ext._extract_by_dictionary = lambda _t, _k=merged: _k
        ext._extract_by_ckip_ner = lambda _t: []
        ents, ments = ext.extract_from_text(text=text, source_id=sid, source_type=typ)
        del ext._extract_by_dictionary
        for e in ents:
            if e.entity_id not in E: E[e.entity_id] = e
            else:
                E[e.entity_id].mention_count += e.mention_count
                for a2 in e.aliases:
                    if a2 not in E[e.entity_id].aliases: E[e.entity_id].aliases.append(a2)
        M.extend(ments)
    ents, ments = normalize_and_merge(E, {}, M, [])
    rows = []
    for m in ments:
        d = m.to_dict()
        rows.append(d)
    return ents, rows

def dan_filter(rows, E):
    keep = {r["source_id"].split(":v:")[0] for r in rows if r["entity_id"] == "place:dan" and is_geo_context(r.get("context", ""))}
    return {k: v for k, v in E.items() if not (k[2] == "place:dan" and k[1] not in keep)}

res, prev = {}, None
for step in range(6):
    ents, rows = run(step)
    E = edges_first_wins(rows)
    if step < 5: E = dan_filter(rows, E)
    names = {eid: e.canonical_name for eid, e in ents.items()}
    info = {"entities": len(ents), "rows": len(rows), "edges": len(E)}
    if prev is not None:
        pE, pents = prev
        rem, add = set(pE) - set(E), set(E) - set(pE)
        info.update({"edges_removed": len(rem), "edges_added": len(add),
                     "entities_gone": len(set(pents) - set(ents)), "entities_new": len(set(ents) - set(pents)),
                     "removed_by_type_flip_or_rename": sum(1 for k in rem if any((k[0], k[1], e2) in add and names.get(e2, "").strip() == pnames.get(k[2], "").strip() for e2 in by_src_add.get((k[0], k[1]), ()))) if False else None})
        # same (source, canonical name) present on the other side under another id => type flip / rename
        pn = prev_names
        add_by_src = collections.defaultdict(set)
        for k in add: add_by_src[(k[0], k[1])].add(names.get(k[2], "").strip())
        flip = sum(1 for k in rem if pn.get(k[2], "").strip() in add_by_src[(k[0], k[1])])
        info["removed_but_same_name_elsewhere_same_source"] = flip
        info["removed_samples"] = [f"{k[1]}->{pn.get(k[2])}" for k in list(rem)[:6]]
        info["added_samples"] = [f"{k[1]}->{names.get(k[2])}" for k in list(add)[:6]]
    res[f"S{step}"] = info
    print(f"S{step}", json.dumps(info, ensure_ascii=False), flush=True)
    prev, prev_names = (E, set(ents)), names
    if True:
        with open(f"rows_S{step}.jsonl", "w") as f:
            for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
json.dump(res, open("chain_result.json", "w"), ensure_ascii=False, indent=1)
