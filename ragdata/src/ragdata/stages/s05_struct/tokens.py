"""Token counts for S5: the pinned BGE-M3 tokenizer of ``ragcommon.encoder``.

A tokenizer that does not load, or is not the pinned one, stops the build (G19):
there is no character-based fallback like the old ``tokenizer_wrapper``.
Counts exclude special tokens, as the old chunker counted them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ragcommon import encoder
from ragdata.stages.errors import StageError


@dataclass(frozen=True)
class TokenCounter:
    count: Callable[[str], int]
    fingerprint: Mapping[str, Any]   # recorded in the struct report


def pinned_counter(tokenizer_file: Path | None = None) -> TokenCounter:
    """BGE-M3 from the HF cache (or ``tokenizer_file``), checked against its pins."""
    try:
        tokenizer, fp = encoder.load_pinned(encoder.BGE_M3, tokenizer_file)
    except (encoder.EncoderContractError, OSError) as exc:
        raise StageError(f"pinned BGE-M3 tokenizer: {exc}") from exc

    def count(text: str) -> int:
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    keep = {k: fp[k] for k in ("tokenizer_sha", "probe_ids_sha")}
    return TokenCounter(count, MappingProxyType({"model": encoder.BGE_M3.repo_id,
                                                 "revision": encoder.BGE_M3.revision, **keep}))
