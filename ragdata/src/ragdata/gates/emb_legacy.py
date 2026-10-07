"""The new encoder against the old index: records whose text is word for word an old
embedding text must get the old vector back (cos >= 0.9999 on 500 sampled records).

The old texts are ``output/embedding_queue.jsonl`` (``{id, type, text}``) and the
old vectors ``output/embeddings.jsonl`` (``{id, type, embedding}``); both are read
only. The sample is drawn with a fixed seed from the records, in file order, whose
text has an old twin. Missing or malformed old files, or fewer twins than the
sample, fail closed.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ragdata.gates.vectors import MAX_LISTED, rowwise_cos

QUEUE = "embedding_queue.jsonl"
EMBEDDINGS = "embeddings.jsonl"
SAMPLE = 500
MIN_COS = 0.9999
SEED = 0
_ID_RE = re.compile(r'"id":\s*"([^"]+)"')


class LegacyError(ValueError):
    """The old files cannot be read as the old build wrote them."""


def _old_texts(path: Path) -> dict[str, str]:
    """Old text -> the first old id embedding it."""
    found: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            try:
                row = json.loads(line)
                found.setdefault(row["text"], row["id"])
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise LegacyError(f"{path}:{number}: {exc}") from None
    return found


def _old_vectors(path: Path, wanted: set[str]) -> dict[str, np.ndarray]:
    found: dict[str, np.ndarray] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = _ID_RE.search(line[:300])
            if m and m.group(1) in wanted:
                found[m.group(1)] = np.asarray(json.loads(line)["embedding"], dtype=np.float32)
    return found


def _sample(records: Sequence[tuple[str, str]], twins: dict[str, str], size: int
            ) -> list[int]:
    rows = [i for i, (_, text) in enumerate(records) if text in twins]
    if len(rows) < size:
        raise LegacyError(f"only {len(rows)} record(s) have an old twin, fewer than the "
                          f"sample of {size}")
    return sorted(random.Random(SEED).sample(rows, size))


def check_compat(records: Sequence[tuple[str, str]], vectors: np.ndarray, legacy_dir: Path,
                 sample: int = SAMPLE) -> tuple[dict[str, Any], list[str]]:
    """``records``: ``(record_id, text)`` in file order, ``vectors`` their rows."""
    queue, embeddings = Path(legacy_dir) / QUEUE, Path(legacy_dir) / EMBEDDINGS
    if not (queue.is_file() and embeddings.is_file()):
        return {"legacy_dir": str(legacy_dir)}, [f"missing input: {queue} and {embeddings}"]
    try:
        twins = _old_texts(queue)
        rows = _sample(records, twins, sample)
    except LegacyError as exc:
        return {"legacy_dir": str(legacy_dir)}, [str(exc)]
    old_ids = [twins[records[i][1]] for i in rows]
    old = _old_vectors(embeddings, set(old_ids))
    violations = [f"{oid}: no old vector" for oid in old_ids if oid not in old]
    have = [(i, oid) for i, oid in zip(rows, old_ids) if oid in old]
    cos = rowwise_cos(vectors[[i for i, _ in have]], np.stack([old[o] for _, o in have])) \
        if have else np.zeros(0)
    violations += [f"{records[i][0]} (old {oid}): cos {c:.7f} < {MIN_COS}"
                   for (i, oid), c in zip(have, cos) if c < MIN_COS][:MAX_LISTED]
    identical = sum(1 for _, text in records if text in twins)
    observed = {"legacy_dir": str(legacy_dir), "identical_texts": identical,
                "sampled": len(rows), "sampled_ids": [records[i][0] for i in rows],
                "min_cos": float(cos.min()) if cos.size else None,
                "below_cos": int((cos < MIN_COS).sum())}
    return observed, violations
