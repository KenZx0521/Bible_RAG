"""Run the backend's own classify_intent over GT v2 with one LLM provider; JSONL per question.

usage (from backend/, PYTHONPATH=.:../packages):
  python intent_run.py {vllm|ollama} OUT_JSONL CONCURRENCY [--ids IDS_FILE]
Resumable: question ids already in OUT_JSONL are skipped. The raw LLM reply is kept.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from config import settings
from utils import intent_classifier
from utils.llm import factory

GT = Path("/home/kenzx0521/Bible_RAG/ground_truth.v2.json")


class Recording:
    """Delegates to the real client and keeps each raw reply by question."""

    def __init__(self, inner):
        self.inner, self.raw, self.err = inner, {}, {}

    async def chat(self, messages, temperature=0.1, max_tokens=512):
        key = messages[-1]["content"].rsplit('問題: "', 1)[-1].rstrip('"')
        try:
            text = await self.inner.chat(messages, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:
            self.err[key] = f"{type(exc).__name__}: {exc}"[:300]
            raise
        self.raw[key] = text
        return text


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("provider", choices=("vllm", "ollama"))
    ap.add_argument("out")
    ap.add_argument("concurrency", type=int)
    ap.add_argument("--ids")
    a = ap.parse_args()
    settings.llm_provider = a.provider
    factory._instance = None
    rec = Recording(factory.get_llm_client())
    intent_classifier.get_llm_client = lambda: rec

    qs = json.loads(GT.read_text())["questions"]
    if a.ids:
        keep = set(Path(a.ids).read_text().split())
        qs = [q for q in qs if q["question_id"] in keep]
    out = Path(a.out)
    done = {json.loads(l)["qid"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = [q for q in qs if q["question_id"] not in done]
    print(f"{a.provider}: {len(todo)} to classify ({len(done)} done)", flush=True)
    sem = asyncio.Semaphore(a.concurrency)
    lock = asyncio.Lock()
    n = 0

    async def one(q, f):
        nonlocal n
        async with sem:
            t = time.time()
            r = await intent_classifier.classify_intent(q["question"])
            row = {"qid": q["question_id"], "qtype": q["question_type"], "sec": round(time.time() - t, 2),
                   "type": r["type"], "entities": r["entities"], "keywords": r["keywords"],
                   "verse_refs": [v.display for v in r["verse_refs"]],
                   "raw": rec.raw.get(q["question"]), "llm_error": rec.err.get(q["question"])}
        async with lock:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 50 == 0:
                print(f"{n}/{len(todo)}", flush=True)

    with out.open("a") as f:
        await asyncio.gather(*(one(q, f) for q in todo))
    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
