"""Verify text_regions split on all 34,072 embedding_queue items.
book region   = book name + ' 第N章 '
title region  = title + ' (a-b節)' / ' 第n節' + '：'
body          = text[text.find('：')+1:]
"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re, collections
ROOT = BIBLE_RAG_ROOT + "/output"
books = {b["id"]: b["name"] for b in map(json.loads, open(f"{ROOT}/books.jsonl")) }
HDR_PC = re.compile(r"^(\S+) 第(\d+)章 (.*?) \(([\d\-]+)節\)：")
HDR_V = re.compile(r"^(\S+) 第(\d+)章 (.*?) 第([\d\-]+)節：")
CH = re.compile(r"^(\S+) 第\d+章 ")
stats = collections.Counter(); bad = []; colon_in_title = []
xref_titles = collections.Counter()
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    r = json.loads(l); t = r["text"]; bn = books[r["id"].split(":")[0]]
    assert t.startswith(bn + " "), r["id"]
    m = (HDR_V if r["type"] == "verse" else HDR_PC).match(t)
    c = CH.match(t)
    body_start = t.find("：") + 1
    if not m: stats["hdr_regex_fail"] += 1; bad.append(r["id"]); continue
    stats["ok"] += 1
    if m.end() != body_start: stats["colon_mismatch"] += 1; colon_in_title.append((r["id"], t[:60]))
    if c.end() > m.end(): stats["chapter_after_hdr"] += 1
    title = m.group(3)
    if re.search(r"[（(＊*]|\d+‧\d+", title): xref_titles[title] += 1
print(stats)
print("colon mismatch samples", colon_in_title[:5])
print("titles with xref remnant:", len(xref_titles), "items", sum(xref_titles.values()))
for k, v in list(xref_titles.items())[:8]: print("  ", v, k)
