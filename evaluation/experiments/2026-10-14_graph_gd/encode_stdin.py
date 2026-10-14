"""Runs INSIDE bible_rag_backend as a stdin script (python -B -); writes no files, no LLM.

prereg §3 查詢與向量: the query vector of each question is the prod
``utils.embedder.encode_query`` output (BGE-M3, fp32, normalised); nothing else is
computed here (no retrieve_dense, no Qdrant). Rewritten from PN/encode_in_container.py.

The host (score.py encode) prepends ``PAYLOAD_B64 = "<base64 json [{sid, query}]>"``.
stdout is JSON lines: first one meta line
``{"type": "meta", "build_id", "embedder_fingerprint" (+ "revision"), "device", "torch_threads"}``,
then per item, in payload order, ``{"type": "q", "sid", "vec_b64" (float32 bytes), "dim",
"elapsed_s"}``. Any failure raises (non-zero exit); the host checks the meta line.
"""
import asyncio
import base64
import json
import logging
import sys
import time

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

import numpy as np  # noqa: E402
import torch  # noqa: E402

from config import settings  # noqa: E402
from database import postgres  # noqa: E402
from ragcommon import encoder  # noqa: E402
from serving import build as build_mod  # noqa: E402
from utils import embedder  # noqa: E402

TORCH_THREADS = 8  # as PN/encode_in_container.py
ITEMS = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))  # noqa: F821  (host-prepended)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def serving_build_id() -> str:
    """The build the backend serves (rag_meta, read-only), for the §10 meta check."""
    async with postgres.connect_meta() as conn:
        build = await build_mod.resolve(conn, settings.rag_env, settings.rag_build_id,
                                        settings.contracts_root)
    return build.build_id


def encode(query: str) -> np.ndarray:
    vec = np.asarray(embedder.encode_query(query), dtype=np.float32)
    if vec.ndim != 1 or not np.all(np.isfinite(vec)):
        raise ValueError(f"encode_query gave a bad vector (shape {vec.shape}) for {query[:30]!r}")
    return vec


def main() -> None:
    if not isinstance(ITEMS, list) or not ITEMS:
        raise ValueError("PAYLOAD_B64 must be a non-empty list of {sid, query}")
    build_id = asyncio.run(serving_build_id())
    torch.set_num_threads(TORCH_THREADS)
    embedder.init_model()
    fingerprint = embedder.get_fingerprint()
    if not fingerprint:
        raise RuntimeError("embedder has no tokenizer fingerprint after init_model()")
    emit({"type": "meta", "build_id": build_id,
          "embedder_fingerprint": {**fingerprint, "revision": encoder.BGE_M3.revision},
          "device": embedder.get_device(), "torch_threads": torch.get_num_threads()})
    for item in ITEMS:
        t0 = time.time()
        vec = encode(item["query"])
        emit({"type": "q", "sid": item["sid"], "vec_b64": base64.b64encode(vec.tobytes()).decode(),
              "dim": int(vec.shape[0]), "elapsed_s": round(time.time() - t0, 3)})


main()
