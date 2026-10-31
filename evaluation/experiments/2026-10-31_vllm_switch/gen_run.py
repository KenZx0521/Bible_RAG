"""Generate answers with one LLM provider from frozen generator inputs; JSONL per question.

The inputs are the 2026-10-26 graph run's context blocks (the generator's own blocks,
context_source "backend") and its aux card, fed through the backend's build_messages and
called exactly as generate_answer calls the client (temperature, max_tokens, fallback).

usage (from backend/, PYTHONPATH=.:../packages):
  python gen_run.py {vllm|ollama} OUT_JSONL CONCURRENCY --ids IDS_FILE
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from config import settings
from utils.generator import build_messages
from utils.llm import factory

RAW = Path("/home/kenzx0521/Bible_RAG/evaluation/results_graph/raw_responses.json")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("provider", choices=("vllm", "ollama"))
    ap.add_argument("out")
    ap.add_argument("concurrency", type=int)
    ap.add_argument("--ids", required=True)
    a = ap.parse_args()
    settings.llm_provider = a.provider
    factory._instance = None
    llm = factory.get_llm_client()

    keep = set(Path(a.ids).read_text().split())
    items = [x for x in json.loads(RAW.read_text()) if x["question_id"] in keep]
    out = Path(a.out)
    done = {json.loads(l)["qid"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = [x for x in items if x["question_id"] not in done]
    print(f"{a.provider} ({llm.provider_name}): {len(todo)} to answer", flush=True)
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()

    async def one(x, f):
        card = x.get("aux_card")
        messages = build_messages(x["question"], "\n\n".join(x["contexts"]),
                                  card["text"] if card else None)
        async with sem:
            t, err = time.time(), None
            try:
                answer = await llm.chat(messages=messages, temperature=settings.llm_temperature,
                                        max_tokens=settings.llm_max_tokens)
                answer = answer or "生成回答時發生錯誤。"
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"[:300]
                answer = f"生成回答時發生錯誤：{exc}"
        row = {"qid": x["question_id"], "sec": round(time.time() - t, 2), "answer": answer,
               "error": err, "has_card": bool(card)}
        async with lock:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()

    with out.open("a") as f:
        await asyncio.gather(*(one(x, f) for x in todo))
    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
