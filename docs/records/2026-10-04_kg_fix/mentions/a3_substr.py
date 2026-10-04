"""For every NER mention in the BODY region of pericope/chunk/verse items, record
the left/right neighbouring characters so we can see which dictionary names are
being matched inside longer proper names (撒馬利亞→馬利亞, 以利亞撒→以利亞...).
Only verse items are used for occurrence counting (each verse once)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re, collections, sys
sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts")
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
ROOT = BIBLE_RAG_ROOT + "/output"
books = {}
for l in open(f"{ROOT}/books.jsonl", encoding="utf-8"):
    l = l.strip()
    if l:
        b = json.loads(l); books[b["id"]] = b["name"]
HDR_V = re.compile(r"^(\S+) 第\d+章 .*? 第[\d\-]+節：")
verses = {}
for l in open(f"{ROOT}/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["type"] == "verse":
        m = HDR_V.match(r["text"]); verses[r["id"]] = (r["text"], m.end())
dict_names = set()
for D in (PERSON_DICT, PLACE_DICT, GROUP_DICT):
    for a in D.values():
        dict_names |= a
ctx = collections.defaultdict(collections.Counter)
n_occ = collections.Counter()
for l in open(f"{ROOT}/entity_mentions.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["source_type"] != "verse" or r.get("start_pos") is None:
        continue
    t, he = verses[r["source_id"]]
    s, e = r["start_pos"], r["end_pos"]
    if s < he:
        continue
    span = r["text_span"]
    if span not in dict_names:
        continue
    L = t[s-1] if s > he else "^"
    R = t[e] if e < len(t) else "$"
    n_occ[span] += 1
    ctx[span][(L, R)] += 1
target = sys.argv[1:] or ["馬利亞", "以利亞", "利亞", "以利", "但", "亞伯", "撒拉", "約翰", "西門", "利未", "雅各", "約瑟", "猶大", "亞拿", "閃", "含", "以諾", "迦得", "瑪拿西", "以撒", "亞倫", "以實瑪利", "西拉", "馬可", "提多", "哈拿", "米迦勒", "殿", "主", "神", "基督", "門徒"]
for n in target:
    print(n, n_occ[n], ctx[n].most_common(25))
