"""The thread the embedding model and the reranker run on, off the event loop.

They take seconds on a CPU. On the event loop that stops every other request, and a Neo4j read waiting out
its 0.8 s times out although Neo4j answered in milliseconds. One thread keeps them one call at a time, as the
event loop did: a fast tokenizer's padding state is not safe across threads ("Already borrowed").
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model")


async def run(call: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """``call(*args, **kwargs)`` on the model thread, after the calls before it."""
    return await asyncio.get_running_loop().run_in_executor(_thread, partial(call, *args, **kwargs))
