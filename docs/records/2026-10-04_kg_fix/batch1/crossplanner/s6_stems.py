import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import sys, os, json, pickle, re, collections
R = BIBLE_RAG_ROOT; D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, f"{R}/scripts")
s = pickle.load(open(f"{D}/sim1c1d.pkl", "rb"))
from entity_extraction.entity_dict import get_all_person_names, get_all_place_names, get_all_group_names
dict_names = set(get_all_person_names()) | set(get_all_place_names()) | set(get_all_group_names())
stems = {"person:fuyin": "福音", "group:shitu": "使徒", "person:liewang": "列王", "person:liwei": "利未"}
texts = {}
for l in open(f"{R}/output/embedding_queue.jsonl", encoding="utf-8"):
    r = json.loads(l); texts[r["id"]] = r["text"]
BOOK = re.compile(r"^\S+ 第\d+章 ")
for eid, nm in stems.items():
    left = [a for a in s["after1c"] if a[2] == eid]
    regs = collections.Counter()
    for l in open(f"{R}/output/entity_mentions.jsonl", encoding="utf-8"):
        if f'"{eid}"' not in l: continue
        m = json.loads(l); t = texts[m["source_id"]]; be = BOOK.match(t).end(); hb = t.find("：") + 1
        p = m["start_pos"]; regs["book" if p < be else "title" if p < hb else "body"] += 1
    print(eid, nm, "in dict:", nm in dict_names, "edges after 1C sim:", len(left), "JSONL occurrence regions:", dict(regs))
