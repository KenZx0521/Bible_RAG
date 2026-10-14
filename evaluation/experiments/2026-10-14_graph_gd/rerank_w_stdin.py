"""Runs INSIDE bible_rag_backend as a stdin script (python -B -); writes no files, no LLM.

prereg §3 W (逐窗重排; sensitivity, arms C and GD only): for each question, every pid of its
C∪GD pool is cut into windows by windows(), passage by passage in pid order; a passage
with more than one window has each window scored with the prod reranker
(``utils.reranker.rerank``: bge-reranker-v2-m3, fp32 CPU, max_length 512, sigmoid), BATCH
windows per call with TORCH_THREADS torch threads, and its W score is the maximum over its
windows. A single-window passage is not scored here: its W score is its whole-passage
score, which the host takes from the scores file of the same lists (§3 W). content is PG
passages.content, as in rerank_stdin.py.

windows() and score() are copied verbatim from the canonical implementation
WF/exp/rr_probe_in_container.py:44-70 (store reports/multihop_kg_20261012/
session_15748325_graphsel/wf/exp/, sha256 24a3a143…): the reranker's own tokenizer called
without special tokens, +1 token per "\\n\\n" block, a 512 − len(query) − 4 budget (the
pair's special tokens), greedy windows with a one-block overlap, a block longer than the
budget alone in its window, next start max(j − 1, i + 1). Do not improve them.

The host (score.py rerank-w) prepends ``PAYLOAD_B64 = "<base64 json [{sid, query, pids}]>"``;
pids must already be sorted and unique. stdout is JSON lines: first one meta line
``{"type": "meta", "build_id", "reranker_fingerprint" (+ "revision"), "device",
"torch_threads", "batch", "window_max_length"}``, then per item, in payload order,
``{"type": "w", "sid", "scores": {pid: max window score} (multi-window pids only),
"n_windows": {pid: n} (every pid), "missing", "elapsed_s"}``.
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

MAXLEN = 512        # the reranker's max_length (window budget)
BATCH = 16          # windows per reranker call (§3)
TORCH_THREADS = 12  # §3
ITEMS = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))  # noqa: F821  (host-prepended)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def windows(tok, q, content):
    qlen = len(tok(q, add_special_tokens=False)["input_ids"])
    budget = MAXLEN - qlen - 4
    blocks = content.split("\n\n")
    lens = [len(tok(b, add_special_tokens=False)["input_ids"]) + 1 for b in blocks]
    if sum(lens) <= budget:
        return [content]
    out, i = [], 0
    while i < len(blocks):
        j, tot = i, 0
        while j < len(blocks) and (tot + lens[j] <= budget or j == i):
            tot += lens[j]
            j += 1
        out.append("\n\n".join(blocks[i:j]))
        if j >= len(blocks):
            break
        i = max(j - 1, i + 1)
    return out


def score(q, texts):
    res = []
    for k in range(0, len(texts), BATCH):
        batch = [{"id": str(k + n), "content": t} for n, t in enumerate(texts[k:k + BATCH])]
        sc = {r["id"]: r["rerank_score"] for r in reranker.rerank(q, batch, top_k=len(batch))}
        res.extend(sc[str(k + n)] for n in range(len(batch)))
    return res


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


def window_max(query: str, pids: list[str], contents: dict[str, str]) -> tuple[dict, dict]:
    """(pid -> max window score for multi-window passages, pid -> number of windows), pid order."""
    tok = reranker._tokenizer
    scores, n_windows = {}, {}
    for pid in pids:
        ws = windows(tok, query, contents[pid])
        n_windows[pid] = len(ws)
        if len(ws) > 1:
            scores[pid] = max(score(query, ws))
    return scores, n_windows


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
              "batch": BATCH, "window_max_length": MAXLEN})
        for item in ITEMS:
            t0 = time.time()
            pids = check_item(item)
            contents, missing = await passage_contents(pids)
            scores, n_windows = window_max(item["query"], [p for p in pids if p in contents],
                                           contents)
            emit({"type": "w", "sid": item["sid"], "scores": scores, "n_windows": n_windows,
                  "missing": missing, "elapsed_s": round(time.time() - t0, 3)})
    finally:
        await postgres.close_pool()


asyncio.run(main())
