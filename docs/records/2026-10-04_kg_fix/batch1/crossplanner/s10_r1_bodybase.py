"""If 1C stores body-relative start_pos (plan 1C import_neo4j: '位移一律相對於本文'), how many
surviving edges would validate_kg R1 (start_pos < len(book name), full-text semantics) still count?"""
import json, re, collections
R = "/home/kenzx0521/Bible_RAG"
books = {json.loads(l)["id"]: json.loads(l)["name"] for l in open(f"{R}/output/books.jsonl")}
texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(f"{R}/output/embedding_queue.jsonl")}
ppg = {json.loads(l)["entity_id"] for l in open(f"{R}/output/entities.jsonl") if json.loads(l)["type"] in ("Person", "Place", "Group")}
first = {}
for l in open(f"{R}/output/entity_mentions.jsonl"):
    m = json.loads(l)
    if m["entity_id"] not in ppg or m["start_pos"] is None: continue
    t = texts[m["source_id"]]; hb = t.find("：") + 1
    if m["start_pos"] < hb: continue          # 1C drops book; title kept but count body only here
    sid = m["source_id"]; key = ("Chunk", sid) if m["source_type"] == "chunk" else ("Pericope", sid.split(":v:")[0])
    first.setdefault((*key, m["entity_id"]), (m["start_pos"] - hb, len(books[sid.split(":")[0]])))
fake = sum(1 for p, bl in first.values() if p < bl)
print("body edges:", len(first), "| would be counted by R1 under body-relative positions:", fake)
