"""Shared helpers: rows -> MENTIONS edges exactly as import_neo4j.py:286-341 does."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, hashlib, re
from collections import defaultdict, OrderedDict
ROOT = BIBLE_RAG_ROOT + "/output"
PPG = {"Person", "Place", "Group"}
CH = re.compile(r"^(\S+) 第\d+章 ")

def edge_key(row):
    sid, st = row["source_id"], row.get("source_type", "")
    if st == "verse" or ":v:" in sid:
        return ("Pericope", sid.split(":v:")[0], row["entity_id"])
    if st == "chunk":
        return ("Chunk", sid, row["entity_id"])
    return ("Pericope", sid, row["entity_id"])

def edges_first_wins(rows):
    """OrderedDict key -> first row (MERGE ... ON CREATE SET, file order)."""
    out = OrderedDict()
    for r in rows:
        k = edge_key(r)
        if k not in out:
            out[k] = r
    return out

def load_texts():
    texts = {}
    for l in open(f"{ROOT}/embedding_queue.jsonl"):
        d = json.loads(l)
        t = d["text"]
        texts[d["id"]] = {"type": d["type"], "text": t, "book_end": t.find(" "),
                          "title_start": CH.match(t).end(), "body_start": t.find("：") + 1}
    return texts

def load_books():
    return {b["id"]: b["name"] for b in map(json.loads, open(f"{ROOT}/books.jsonl"))}

def load_titles():
    titles = {}
    for l in open(f"{ROOT}/neo4j_nodes.jsonl"):
        d = json.loads(l)
        p = d["properties"]
        if "Pericope" in d["labels"]:
            titles[("Pericope", p["id"])] = p.get("title")
        elif "Chunk" in d["labels"]:
            titles[("Chunk", p["id"])] = p.get("pericope_title")
    return titles

def titles_of(edge_keys, titles):
    """desc_generator.titles_cypher: first six distinct non-empty titles in code-point order."""
    per = defaultdict(set)
    for (lab, sid, eid) in edge_keys:
        t = titles.get((lab, sid))
        if t:
            per[eid].add(t)
    return {eid: sorted(ts)[:6] for eid, ts in per.items()}

def titles_sha(titles):
    payload = json.dumps(list(titles or []), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
