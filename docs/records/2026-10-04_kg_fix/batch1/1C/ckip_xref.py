"""CKIP (GPU) on body-only text for the items whose title is a cross-reference
remnant (same predicate as kg_validate R8 _XREF_REMNANT); writes
ckip_raw_body_xref_gpu.pkl {id: tokens, idx relative to body_start}."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, pickle, re
from ckip_transformers.nlp import CkipNerChunker
ROOT = BIBLE_RAG_ROOT + "/output"
HDR_PC = re.compile(r"^(\S+) 第(\d+)章 (.*?) \(([\d\-]+)節\)：")
HDR_V = re.compile(r"^(\S+) 第(\d+)章 (.*?) 第([\d\-]+)節：")
X = re.compile(r"^[（(＊*]|\d+‧\d+")
items = []
for l in open(f"{ROOT}/embedding_queue.jsonl"):
    d = json.loads(l); t = d["text"]
    title = (HDR_V if d["type"] == "verse" else HDR_PC).match(t).group(3)
    if title != "(無標題)" and X.search(title):
        items.append((d["id"], t[t.find("：") + 1:]))
ner = CkipNerChunker(model="bert-base", device=0)
out = ner([t for _, t in items], batch_size=64, show_progress=False)
pickle.dump({i: [(k.word, k.ner, tuple(k.idx)) for k in toks] for (i, _), toks in zip(items, out)},
            open("ckip_raw_body_xref_gpu.pkl", "wb"))
print("xref-title items", len(items))
