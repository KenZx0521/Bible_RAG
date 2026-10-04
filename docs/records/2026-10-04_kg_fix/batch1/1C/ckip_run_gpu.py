"""Run CKIP NER (CPU, batched) on every embedding_queue item twice:
  full : the whole embedding text (what --stage ner reads today)
  sub  : text from the title region on (book name + ' 第N章 ' removed) = 1C input
Stores raw NerTokens (word, ner, idx) per item -> ckip_raw_<mode>.pkl
Batching does not change a sentence's input (ckip_transformers pads per
sequence with an attention mask), so tokens equal the one-at-a-time calls
up to float noise; check_batch_equiv.py verifies that on a sample.
Usage: python ckip_run.py [limit]
"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, pickle, re, sys, time
sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts")
from ckip_transformers.nlp import CkipNerChunker
ROOT = BIBLE_RAG_ROOT + "/output"
CH = re.compile(r"^(\S+) 第\d+章 ")
limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
items = [json.loads(l) for l in open(f"{ROOT}/embedding_queue.jsonl")]
if limit:
    items = items[:limit]
ner = CkipNerChunker(model="bert-base", device=0)
for mode in ("full", "sub"):
    t0 = time.time()
    texts = []
    for it in items:
        t = it["text"]
        texts.append(t if mode == "full" else t[CH.match(t).end():])
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # less padding
    out_sorted = ner([texts[i] for i in order], batch_size=64, show_progress=False)
    out = [None] * len(texts)
    for k, i in enumerate(order):
        out[i] = out_sorted[k]
    raw = {it["id"]: [(tok.word, tok.ner, tuple(tok.idx)) for tok in toks] for it, toks in zip(items, out)}
    suffix = f"_{limit}" if limit else ""
    pickle.dump(raw, open(f"ckip_raw_{mode}{suffix}_gpu.pkl", "wb"))
    print(mode, len(items), "items", round(time.time() - t0, 1), "s", flush=True)
