"""Runs INSIDE bible_rag_backend as a stdin script (python -B -); writes no files, no LLM.

prereg §3 Reranker: for each question, the prod ``utils.reranker.rerank(question, recs,
top_k=len, text_key='content')`` (bge-reranker-v2-m3, fp32 CPU, max_length 512,
longest_first, sigmoid) scores every pid of the question's pool union, in batches of
BATCH pairs with TORCH_THREADS torch threads. content is PG passages.content (the
serving build's schema). Rewritten from PN/rerank_in_container.py.

The host (score.py rerank / refpairs) prepends ``PAYLOAD_B64 = "<base64 json [{sid,
query, pids}]>"``; pids must already be sorted and unique (the union in pid order).
A pid that is not a passage id raises; passage ids the build lacks are reported in
``missing`` (the host treats that as an infrastructure failure).
stdout is JSON lines: first one meta line ``{"type": "meta", "build_id",
"reranker_fingerprint" (+ "revision"), "device", "torch_threads", "batch"}``, then per
item, in payload order, ``{"type": "r", "sid", "scores": {pid: score}, "missing",
"elapsed_s"}``.
"""
import asyncio
import base64
import json
import logging
import sys
import time

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

import torch  # noqa: E402

from config import settings  # noqa: E402
from database import postgres  # noqa: E402
from ragcommon import encoder, ids  # noqa: E402
from serving import build as build_mod  # noqa: E402
from utils import reranker  # noqa: E402

BATCH = 16          # pairs per reranker call (§3)
TORCH_THREADS = 12  # §3
ITEMS = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))  # noqa: F821  (host-prepended)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def check_item(item: dict) -> list[str]:
    """The item's pids: non-empty, sorted, unique, every one a passage id (ps:…)."""
    pids = item["pids"]
    if not pids or pids != sorted(set(pids)):
        raise ValueError(f"{item['sid']}: pids must be non-empty, sorted and unique")
    for pid in pids:
        kind = ids.parse(pid).kind
        if kind != "passage":
            raise ValueError(f"{item['sid']}: {pid} is a {kind}, not a passage (§3 送整段)")
    return pids


async def passage_contents(pids: list[str]) -> tuple[dict[str, str], list[str]]:
    """PG passages.content of the pids the build has, and the ones it lacks."""
    missing = await postgres.missing_passages(pids)
    lacking = set(missing)
    present = [p for p in pids if p not in lacking]
    sources = await postgres.fetch_sources(present)
    return {p: sources[p]["content"] for p in present}, missing


def score(query: str, pids: list[str], contents: dict[str, str]) -> dict[str, float]:
    """Reranker scores of (query, content) in pid order, BATCH pairs per call."""
    out: dict[str, float] = {}
    for i in range(0, len(pids), BATCH):
        batch = [{"id": p, "content": contents[p]} for p in pids[i:i + BATCH]]
        for rec in reranker.rerank(query, batch, top_k=len(batch), text_key="content"):
            out[rec["id"]] = rec["rerank_score"]
    return out


async def main() -> None:
    if not isinstance(ITEMS, list) or not ITEMS:
        raise ValueError("PAYLOAD_B64 must be a non-empty list of {sid, query, pids}")
    async with postgres.connect_meta() as conn:
        build = await build_mod.resolve(conn, settings.rag_env, settings.rag_build_id,
                                        settings.contracts_root)
    await postgres.init_pool(build.pg_schema)
    try:
        torch.set_num_threads(TORCH_THREADS)
        reranker.init_reranker()
        fingerprint = reranker.get_fingerprint()
        if not fingerprint:
            raise RuntimeError("reranker has no tokenizer fingerprint after init_reranker()")
        emit({"type": "meta", "build_id": build.build_id,
              "reranker_fingerprint": {**fingerprint, "revision": encoder.RERANKER.revision},
              "device": reranker._device, "torch_threads": torch.get_num_threads(),
              "batch": BATCH})
        for item in ITEMS:
            t0 = time.time()
            pids = check_item(item)
            contents, missing = await passage_contents(pids)
            scores = score(item["query"], [p for p in pids if p in contents], contents)
            emit({"type": "r", "sid": item["sid"], "scores": scores, "missing": missing,
                  "elapsed_s": round(time.time() - t0, 3)})
    finally:
        await postgres.close_pool()


asyncio.run(main())
