"""Runs INSIDE bible_rag_backend as a stdin script (python -B -); writes no files.

QD arms of plan.md (2026-10-18). A copy of new82_ans it_container.py with two changes to
decompose: an item may carry its own user template (the frozen one, or the frozen one with
the 「可能相關名稱」 line filled in by the host), and an item may carry the context blocks
themselves instead of passage ids (step 2 reads eval3c's generator blocks). No gold is sent
here: a payload item carries only a question text, names, a sub-query, blocks or passage ids.

The host (qd_stage.py) prepends ``PAYLOAD_B64 = "<base64 json>"`` and replaces the helper
placeholder line (it_host.PLACEHOLDER) with the source of QUOTES, ENUM_RE, LABEL_RE, sha, clean_line,
parse_subquery and decompose taken by AST from iterq/iter_in_container.py (byte-identical
code; its sha256 is recorded in the meta). Payload = {"mode", "items", "prompt"?}:

* decompose  items [{key, question, pids | blocks, user_template?}]: the context blocks are
  `blocks` as given, or the unmodified utils.generator.build_context_blocks over
  postgres.get_content_by_id(pid) records in the given order; the decomposer is prod
  utils.llm.get_llm_client(), temperature 0, max_tokens settings.llm_max_tokens, prompt =
  iterq decomposer_prompt.txt (system / user template from the host; an item's
  user_template replaces the user template for that item only). Emits {"type": "dec", key,
  subquery, fallback, attempts, user_sha256, template_sha256, context_sha256,
  content_sha256, elapsed_s}.
* encode     items [{sid, query}]: utils.embedder.encode_query (as encode_stdin.py of
  the GD experiment, 8 torch threads). Emits {"type": "q", sid, vec_b64, dim}.
* rerank     items [{key, query, pids}] (pids sorted, unique): prod
  utils.reranker.rerank(query, recs, top_k=len, text_key='content') over
  get_content_by_id(pid)["content"] in pid order, 16 pairs per call, 12 torch threads
  (as rerank_stdin.py of the GD experiment). Emits {"type": "r", key, scores, elapsed_s}.

The first stdout line is a meta line (build, model / fingerprints, run settings).
A per-item failure is emitted as {"type": "error", key, error}; the host retries it.
"""
import asyncio
import base64
import hashlib
import json
import logging
import re
import sys
import time

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

import numpy as np  # noqa: E402
import torch  # noqa: E402

from config import settings  # noqa: E402
from database import postgres  # noqa: E402
from ragcommon import encoder, ids  # noqa: E402
from serving import build as build_mod  # noqa: E402
from utils import embedder, generator, reranker  # noqa: E402
from utils.llm import get_llm_client  # noqa: E402

P = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))  # noqa: F821 (host-prepended)
MODE = P["mode"]
ITEMS = P["items"]
DECOMPOSER_TEMPERATURE = 0.0
BATCH = 16
RERANK_THREADS = 12
ENCODE_THREADS = 8
PROMPT = P.get("prompt") or {}
SYSTEM, USER_T = PROMPT.get("system"), PROMPT.get("user_template")
BASE_USER_T = USER_T

#@@ITERQ_HELPERS@@


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def resolve_build():
    async with postgres.connect_meta() as conn:
        return await build_mod.resolve(conn, settings.rag_env, settings.rag_build_id,
                                       settings.contracts_root)


async def records(pids):
    """get_content_by_id records in the given order; a missing passage raises."""
    out = []
    for pid in pids:
        if ids.parse(pid).kind != "passage":
            raise ValueError(f"{pid} is not a passage id")
        rec = await postgres.get_content_by_id(pid)
        if rec is None:
            raise LookupError(f"the build has no passage {pid}")
        out.append(rec)
    return out


async def run_decompose(build):
    global USER_T
    if not (SYSTEM and BASE_USER_T):
        raise ValueError("decompose needs prompt.system and prompt.user_template")
    llm = get_llm_client()
    emit({"type": "meta", "mode": MODE, "build_id": build.build_id, "pg_schema": build.pg_schema,
          "llm": llm.provider_name, "llm_provider": settings.llm_provider,
          "llm_max_tokens": settings.llm_max_tokens,
          "decomposer_temperature": DECOMPOSER_TEMPERATURE,
          "prompt_file_sha256": PROMPT.get("sha256")})
    for item in ITEMS:
        t0 = time.time()
        try:
            if "blocks" in item:
                recs, blocks = [], list(item["blocks"])
            else:
                recs = await records(item["pids"])
                blocks = generator.build_context_blocks([dict(r) for r in recs])
            USER_T = item.get("user_template") or BASE_USER_T
            sq, fallback, attempts, user_sha = await decompose(item["question"], blocks)  # noqa: F821
            emit({"type": "dec", "key": item["key"], "subquery": sq, "fallback": fallback,
                  "attempts": attempts, "user_sha256": user_sha,
                  "template_sha256": sha(USER_T),  # noqa: F821
                  "context_pids": item.get("pids"),
                  "context_sha256": sha("\n\n".join(blocks)),  # noqa: F821
                  "content_sha256": [sha(r["content"]) for r in recs],  # noqa: F821
                  "elapsed_s": round(time.time() - t0, 1)})
        except Exception as exc:  # noqa: BLE001 — host retries the key
            emit({"type": "error", "key": item["key"], "error": repr(exc)[:500]})
        finally:
            USER_T = BASE_USER_T


def run_encode(build):
    torch.set_num_threads(ENCODE_THREADS)
    embedder.init_model()
    fingerprint = embedder.get_fingerprint()
    if not fingerprint:
        raise RuntimeError("embedder has no tokenizer fingerprint after init_model()")
    emit({"type": "meta", "mode": MODE, "build_id": build.build_id,
          "embedder_fingerprint": {**fingerprint, "revision": encoder.BGE_M3.revision},
          "device": embedder.get_device(), "torch_threads": torch.get_num_threads()})
    for item in ITEMS:
        t0 = time.time()
        vec = np.asarray(embedder.encode_query(item["query"]), dtype=np.float32)
        if vec.ndim != 1 or not np.all(np.isfinite(vec)):
            raise ValueError(f"encode_query gave a bad vector for {item['sid']}")
        emit({"type": "q", "sid": item["sid"], "vec_b64": base64.b64encode(vec.tobytes()).decode(),
              "dim": int(vec.shape[0]), "elapsed_s": round(time.time() - t0, 3)})


def score(query, pids, contents):
    """rerank_stdin.score: reranker scores of (query, content) in pid order, BATCH per call."""
    out = {}
    for i in range(0, len(pids), BATCH):
        batch = [{"id": p, "content": contents[p]} for p in pids[i:i + BATCH]]
        for rec in reranker.rerank(query, batch, top_k=len(batch), text_key="content"):
            out[rec["id"]] = rec["rerank_score"]
    return out


async def run_rerank(build):
    torch.set_num_threads(RERANK_THREADS)
    reranker.init_reranker()
    fingerprint = reranker.get_fingerprint()
    if not fingerprint:
        raise RuntimeError("reranker has no tokenizer fingerprint after init_reranker()")
    emit({"type": "meta", "mode": MODE, "build_id": build.build_id,
          "reranker_fingerprint": {**fingerprint, "revision": encoder.RERANKER.revision},
          "device": reranker._device, "torch_threads": torch.get_num_threads(), "batch": BATCH})
    for item in ITEMS:
        t0 = time.time()
        try:
            pids = item["pids"]
            if not pids or pids != sorted(set(pids)):
                raise ValueError("pids must be non-empty, sorted and unique")
            recs = await records(pids)
            contents = {p: r["content"] for p, r in zip(pids, recs)}
            scores = score(item["query"], pids, contents)
            if sorted(scores) != pids:
                raise RuntimeError("reranker did not score every pid")
            emit({"type": "r", "key": item["key"], "scores": scores,
                  "elapsed_s": round(time.time() - t0, 2)})
        except Exception as exc:  # noqa: BLE001 — host retries the key
            emit({"type": "error", "key": item["key"], "error": repr(exc)[:500]})


async def main():
    build = await resolve_build()
    await postgres.init_pool(build.pg_schema)
    try:
        if MODE == "decompose":
            await run_decompose(build)
        elif MODE == "encode":
            run_encode(build)
        elif MODE == "rerank":
            await run_rerank(build)
        else:
            raise ValueError(f"unknown mode {MODE!r}")
    finally:
        await postgres.close_pool()


asyncio.run(main())
