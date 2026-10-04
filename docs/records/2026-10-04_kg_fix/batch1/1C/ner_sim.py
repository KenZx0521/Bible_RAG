"""Replay the NER half offline from raw CKIP tokens (ckip_run.py output).

Modes
  current : exactly today's ner_extractor (repo code reused; only the CKIP call
            is replaced by the pre-computed tokens of the FULL text, positions
            via text.find as at ner_extractor.py:238).  Must reproduce
            output/ner_mentions.jsonl content -> validates the harness.
  1c      : the batch-1C design:
              * input = text from the title region on (book + ' 第N章 ' dropped)
              * CKIP positions from NerToken.idx (+ offset)
              * normalize_surface: strip ASCII/full-width/zero-width spaces, NFC
              * book-abbreviation stoplist (bible_chunking.config.CROSS_REF_ABBREV,
                '但' exempt)
              * single-char '但' must pass the geo rule (GEO variant below)
              * every row tagged source_region = title|body
GEO variant (1c only):  ctx = 10.2-equivalent (cleanup_noise_entities._is_geo_context
  on the ±30 context string, any 但 in the window)   pos = same rule, but only at
  the mention's own position.
Writes rows_<mode>[_<geo>].jsonl (entity_id, source_id, source_type, text_span,
start_pos, end_pos, source_region) and ents_<mode>[_<geo>].jsonl.
Usage: python ner_sim.py current|1c [ctx|pos] [limit]
"""
import json, pickle, re, sys, unicodedata
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
sys.path.insert(0, "/home/kenzx0521/Bible_RAG")
from entity_extraction.ner_extractor import NERExtractor, NERResult
from entity_extraction.entity_normalizer import normalize_and_merge
from bible_chunking.config import CROSS_REF_ABBREV

ROOT = "/home/kenzx0521/Bible_RAG/output"
CH = re.compile(r"^(\S+) 第\d+章 ")
mode = sys.argv[1]
geo = sys.argv[2] if len(sys.argv) > 2 and mode == "1c" else None
limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
suffix = f"_{limit}" if limit else ""

# --- copy of cleanup_noise_entities.py:66-70, 167-183 (no import: module loads .env/neo4j)
PUNCT = set("，。；：、「」？！ \n\t^$（）－")
GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}
LIST_OK_PREV = {"和", "與", "同"} | PUNCT
def _geo_at(ctx, i):
    p = ctx[i - 1] if i > 0 else "^"
    n = ctx[i + 1] if i + 1 < len(ctx) else "$"
    if p in GEO_PREV and n != "以": return True
    if p in NAMING_PREV and (n in PUNCT or n == "$"): return True
    if p in LIST_OK_PREV and n == "、": return True
    if p == "、" and (n in PUNCT or n == "$"): return True
    return False
def is_geo_context(ctx):
    if "別是巴" in ctx: return True
    i = ctx.find("但")
    while i >= 0:
        if _geo_at(ctx, i): return True
        i = ctx.find("但", i + 1)
    return False
def is_geo_at(text, start):
    # position-specific variant: 別是巴 within ±30 or the rule at this 但
    lo, hi = max(0, start - 30), min(len(text), start + 31)
    return "別是巴" in text[lo:hi] or _geo_at(text, start)

WS = " \t\n\r　 ​‌‍﻿"
def normalize_surface(word, start):
    w = unicodedata.normalize("NFC", word)
    lead = len(w) - len(w.lstrip(WS))
    core = w.strip(WS)
    return core, start + lead, start + lead + len(core)

import os
XREF = os.environ.get("XREF", "skip")
CKIP_INPUT = os.environ.get("CKIP_INPUT", "sub")  # sub: CKIP reads title+body; full: CKIP reads the whole text, tokens left of the region are dropped          # skip: no NER on cross-reference-remnant titles
STOP = os.environ.get("STOP", "但,珥")          # exemptions; "none" disables the stoplist
ABBREV_STOP = set() if STOP == "none" else set(CROSS_REF_ABBREV) - set(STOP.split(","))
XREF_TITLE = re.compile(r"^[（(＊*]|\d+‧\d+")
HDR = {"verse": re.compile(r"^(\S+) 第(\d+)章 (.*?) 第([\d\-]+)節："),
       "other": re.compile(r"^(\S+) 第(\d+)章 (.*?) \(([\d\-]+)節\)：")}
def is_xref_title(text, typ):
    title = HDR["verse" if typ == "verse" else "other"].match(text).group(3)
    return title != "(無標題)" and bool(XREF_TITLE.search(title))

items = [json.loads(l) for l in open(f"{ROOT}/embedding_queue.jsonl")]
if limit: items = items[:limit]
import os
RAW = os.environ.get("RAW_SUFFIX", "_gpu")  # _gpu: device=0 run; '' : CPU run (300-item sample only)
raw_xref = pickle.load(open("ckip_raw_body_xref_gpu.pkl", "rb")) if mode == "1c" else {}
raw = pickle.load(open(f"ckip_raw_{'full' if mode == 'current' or CKIP_INPUT == 'full' else 'sub'}{suffix}{RAW}.pkl", "rb"))

class Replay(NERExtractor):
    def _initialize_ckip(self):
        self._initialized = True
ext = Replay()
stats = {"abbrev_dropped": 0, "dan_dropped": 0, "dan_kept": 0, "ws_normalized": 0, "empty_after_strip": 0}

def ckip_results_current(text, toks):
    out = []
    for word, ner, idx in toks:
        t = ext._map_ckip_type(ner)
        if t:
            s = text.find(word)
            if s != -1:
                out.append(NERResult(text=word, entity_type=t, start=s, end=s + len(word)))
    return out

def ckip_results_1c(text, off, toks):
    out = []
    for word, ner, (a, b) in toks:
        t = ext._map_ckip_type(ner)
        if not t: continue
        core, s, e = normalize_surface(word, a + off)
        if core != word: stats["ws_normalized"] += 1
        if not core: stats["empty_after_strip"] += 1; continue
        assert text[s:e] == core, (text[s - 3:e + 3], core)
        out.append(NERResult(text=core, entity_type=t, start=s, end=e))
    return out

all_ents, all_ments, region = {}, [], {}
for it in items:
    text, sid, styp = it["text"], it["id"], it["type"]
    toks = raw[sid]
    if mode == "current":
        ext._extract_by_ckip_ner = lambda _t, _toks=toks, _text=text: ckip_results_current(_text, _toks)
        ents, ments = ext.extract_from_text(text=text, source_id=sid, source_type=styp)
    else:
        body = text.find("：") + 1
        off = CH.match(text).end()
        if XREF == "skip" and is_xref_title(text, styp):
            off = body
            if CKIP_INPUT == "sub": toks = raw_xref[sid]
            stats["xref_title_items"] = stats.get("xref_title_items", 0) + 1
        sub = text[off:]
        d = [NERResult(r.text, r.entity_type, r.start + off, r.end + off) for r in ext._extract_by_dictionary(sub)]
        if CKIP_INPUT == "full":
            c = [r for r in ckip_results_1c(text, 0, toks) if r.start >= off]
        else:
            c = ckip_results_1c(text, off, toks)
        merged = ext._merge_results(d, c)
        keep = []
        for r in merged:
            if r.text in ABBREV_STOP:
                stats["abbrev_dropped"] += 1; continue
            if r.text == "但":
                ok = is_geo_context(ext._get_context(text, r.start, r.end)) if geo == "ctx" else is_geo_at(text, r.start)
                if not ok:
                    stats["dan_dropped"] += 1; continue
                stats["dan_kept"] += 1
            keep.append(r)
        ext._extract_by_dictionary = lambda _t, _k=keep: _k
        ext._extract_by_ckip_ner = lambda _t: []
        ents, ments = ext.extract_from_text(text=text, source_id=sid, source_type=styp)
        del ext._extract_by_dictionary
        for m in ments:
            region[m.mention_id] = "title" if m.start_pos < body else "body"
    for e in ents:
        if e.entity_id not in all_ents: all_ents[e.entity_id] = e
        else:
            all_ents[e.entity_id].mention_count += e.mention_count
            for a in e.aliases:
                if a not in all_ents[e.entity_id].aliases: all_ents[e.entity_id].aliases.append(a)
    all_ments.extend(ments)

ents, ments = normalize_and_merge(all_ents, {}, all_ments, [])
tag = mode + (f"_{geo}" if geo else "") + ("" if mode == "current" or (XREF, STOP) == ("skip", "但,珥") else f"_x{XREF}_s{STOP.replace(',', '')}") + ("_cfull" if CKIP_INPUT == "full" and mode != "current" else "") + suffix
with open(f"rows_{tag}.jsonl", "w") as f:
    for m in ments:
        d = m.to_dict(); d.pop("context", None); d.pop("mention_id", None)
        if mode != "current": d["source_region"] = region[m.mention_id]
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
with open(f"ents_{tag}.jsonl", "w") as f:
    for e in ents.values():
        f.write(e.to_json() + "\n")
print(tag, "entities", len(ents), "mentions", len(ments), stats)
